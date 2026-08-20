"""Route explicitly tagged Pine models into isolated paper shadow accounts.

Existing untagged Pine traffic remains on the configured default paper account.
Only an explicit PAPER_SHADOW_V24 / PAPER_SHADOW_V25 model_id may enter a shadow
book. This prevents an accidental cutover of existing paper state.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from .dynamo_ledger import DynamoPaperLedger
from .equity_liquidity import LiquidityEvidenceStore, LiquidityGatedPaperExecutor
from .pine_processor import DynamoPineEventStore, PineProcessorError, PineProcessorResult
from .reconciled_receipt_executor import ReceiptReconciledAwsPinePaperExecutor

PAPER_SHADOW_V24 = "PAPER_SHADOW_V24"
PAPER_SHADOW_V25 = "PAPER_SHADOW_V25"
SHADOW_MODELS = {
    PAPER_SHADOW_V24: "2.4",
    PAPER_SHADOW_V25: "2.5",
}
SHADOW_FORWARD_START_ENV = "DAILY_ALPHA_SHADOW_FORWARD_START"


def default_paper_account_id() -> str:
    return os.getenv("DAILY_ALPHA_PAPER_ACCOUNT_ID", "").strip() or "paper-staging"


def account_id_for_ingress(ingress: Mapping[str, Any]) -> str:
    """Return the isolated account for an explicit shadow signal."""
    default_account = default_paper_account_id()
    model_id = str(ingress.get("model_id", "") or "").strip().upper()
    if not model_id:
        return default_account
    expected_version = SHADOW_MODELS.get(model_id)
    if expected_version is None:
        raise PineProcessorError("PINE_SHADOW_MODEL_ID_INVALID")
    version = str(ingress.get("strategy_version", "")).strip()
    if version != expected_version:
        raise PineProcessorError("PINE_SHADOW_MODEL_VERSION_MISMATCH")
    if str(ingress.get("source", "")).strip() != "TRADINGVIEW_PINE":
        raise PineProcessorError("PINE_SHADOW_SOURCE_INVALID")
    _validate_forward_test_start(ingress)
    return model_id


def _validate_forward_test_start(ingress: Mapping[str, Any]) -> str:
    """Require both shadow models to identify the same configured start date."""
    configured = os.getenv(SHADOW_FORWARD_START_ENV, "").strip()
    if not configured:
        raise PineProcessorError("PINE_SHADOW_FORWARD_START_NOT_CONFIGURED")
    try:
        configured_date = date.fromisoformat(configured)
    except ValueError as exc:
        raise PineProcessorError("PINE_SHADOW_FORWARD_START_CONFIG_INVALID") from exc

    supplied = str(ingress.get("forward_test_start", "") or "").strip()
    if not supplied:
        raise PineProcessorError("PINE_SHADOW_FORWARD_START_REQUIRED")
    try:
        supplied_date = date.fromisoformat(supplied)
    except ValueError as exc:
        raise PineProcessorError("PINE_SHADOW_FORWARD_START_INVALID") from exc
    if supplied_date != configured_date:
        raise PineProcessorError("PINE_SHADOW_FORWARD_START_MISMATCH")
    return configured_date.isoformat()


class ShadowRoutedPineEventStore:
    """Persist each Pine event under the same account as its shadow ledger."""

    def __init__(
        self,
        *,
        table_name: str | None = None,
        client: Any | None = None,
        store_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.table_name = table_name
        self.client = client
        self._signal_accounts: dict[str, str] = {}
        self._stores: dict[str, Any] = {}
        self._store_factory = store_factory

    def _store(self, account_id: str):
        if account_id not in self._stores:
            if self._store_factory is not None:
                store = self._store_factory(account_id)
            else:
                kwargs: dict[str, Any] = {"account_id": account_id}
                if self.table_name is not None:
                    kwargs["table_name"] = self.table_name
                if self.client is not None:
                    kwargs["client"] = self.client
                store = DynamoPineEventStore(**kwargs)
            self._stores[account_id] = store
        return self._stores[account_id]

    def persist(
        self,
        ingress: Mapping[str, Any],
        result: PineProcessorResult,
    ) -> bool:
        account_id = account_id_for_ingress(ingress)
        self._signal_accounts[result.signal_id] = account_id
        return bool(self._store(account_id).persist(ingress, result))

    def mark_execution(
        self,
        signal_id: str,
        execution: Mapping[str, Any],
    ) -> None:
        account_id = self._signal_accounts.get(signal_id)
        if not account_id:
            raise PineProcessorError("PINE_SHADOW_SIGNAL_ACCOUNT_UNKNOWN")
        self._store(account_id).mark_execution(signal_id, execution)


class ShadowRoutedPinePaperExecutor:
    """Execute and replay tagged models against isolated receipt-aware paper ledgers."""

    def __init__(
        self,
        *,
        paper_nav: float | None = None,
        secrets_client: Any | None = None,
        secret_id: str | None = None,
        orats_factory: Any | None = None,
        ledger_factory: Callable[[str], Any] | None = None,
        liquidity_store: LiquidityEvidenceStore | None = None,
    ) -> None:
        self.paper_nav = paper_nav
        self.secrets_client = secrets_client
        self.secret_id = secret_id
        self.orats_factory = orats_factory
        self.ledger_factory = ledger_factory
        self.liquidity_store = liquidity_store

    def _ledger(self, account_id: str):
        if self.ledger_factory is not None:
            return self.ledger_factory(account_id)
        return DynamoPaperLedger(account_id=account_id)

    def _executor(self, account_id: str):
        kwargs: dict[str, Any] = {"ledger": self._ledger(account_id)}
        if self.paper_nav is not None:
            kwargs["paper_nav"] = self.paper_nav
        if self.secrets_client is not None:
            kwargs["secrets_client"] = self.secrets_client
        if self.secret_id is not None:
            kwargs["secret_id"] = self.secret_id
        if self.orats_factory is not None:
            kwargs["orats_factory"] = self.orats_factory
        executor: Any = ReceiptReconciledAwsPinePaperExecutor(**kwargs)
        if self.liquidity_store is not None:
            executor = LiquidityGatedPaperExecutor(executor, self.liquidity_store)
        return executor

    def _decorate(
        self,
        ingress: Mapping[str, Any],
        execution: Mapping[str, Any],
        account_id: str,
    ) -> dict[str, Any]:
        result = dict(execution)
        result["paper_account_id"] = account_id
        result["model_id"] = (
            account_id if account_id in SHADOW_MODELS else ingress.get("model_id")
        )
        result["forward_test_start"] = (
            _validate_forward_test_start(ingress)
            if account_id in SHADOW_MODELS
            else ingress.get("forward_test_start")
        )
        result["trading_authorized"] = False
        result["live_trading_enabled"] = False
        return result

    def execute(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        account_id = account_id_for_ingress(ingress)
        execution = self._executor(account_id).execute(ingress, now=now)
        return self._decorate(ingress, execution, account_id)

    def replay_armed(
        self,
        ingress: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        account_id = account_id_for_ingress(ingress)
        execution = self._executor(account_id).replay_armed(ingress, now=now)
        return self._decorate(ingress, execution, account_id)
