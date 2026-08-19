"""Durable replay worker for Pine signals armed outside the tradable window.

The original ingress event is already persisted in the Pine event store. This
module scans only events whose current disposition is still
``ARMED_FOR_NEXT_TRADABLE_WINDOW``, revalidates them through the reconciled
paper executor, and writes the new outcome back to the same audit record.

No live brokerage path is present here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .pine_processor import PineProcessorError

ARMED_DISPOSITION = "ARMED_FOR_NEXT_TRADABLE_WINDOW"
DEFAULT_REPLAY_LIMIT = 25
MAX_REPLAY_LIMIT = 100


def list_armed_ingress(store: Any, *, limit: int = DEFAULT_REPLAY_LIMIT) -> list[dict[str, Any]]:
    """Return a bounded set of durably armed ingress events from DynamoDB."""
    if limit <= 0 or limit > MAX_REPLAY_LIMIT:
        raise PineProcessorError("ARMED_REPLAY_LIMIT_INVALID")
    prefix = f"ACCOUNT#{store.account_id}#PINE_EVENT#"
    kwargs: dict[str, Any] = {
        "TableName": store.table_name,
        "FilterExpression": (
            "begins_with(pk, :prefix) AND #sk = :received "
            "AND disposition = :armed"
        ),
        "ExpressionAttributeNames": {"#sk": "sk"},
        "ExpressionAttributeValues": {
            ":prefix": {"S": prefix},
            ":received": {"S": "RECEIVED"},
            ":armed": {"S": ARMED_DISPOSITION},
        },
        "Limit": limit,
    }
    records: list[dict[str, Any]] = []
    while len(records) < limit:
        try:
            response = store.client.scan(**kwargs)
        except Exception as exc:
            raise PineProcessorError("ARMED_REPLAY_DYNAMODB_SCAN_FAILED") from exc
        for item in response.get("Items", []):
            raw = item.get("ingress_json", {}).get("S")
            signal_id = item.get("signal_id", {}).get("S")
            if not raw or not signal_id:
                continue
            try:
                ingress = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise PineProcessorError("ARMED_REPLAY_INGRESS_JSON_INVALID") from exc
            if not isinstance(ingress, dict):
                raise PineProcessorError("ARMED_REPLAY_INGRESS_MUST_BE_OBJECT")
            ingress["_persisted_signal_id"] = str(signal_id)
            records.append(ingress)
            if len(records) >= limit:
                break
        last_key = response.get("LastEvaluatedKey")
        if not last_key or len(records) >= limit:
            break
        kwargs["ExclusiveStartKey"] = last_key
        kwargs["Limit"] = limit - len(records)
    return records


def replay_armed_events(
    store: Any,
    executor: Any,
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_REPLAY_LIMIT,
) -> dict[str, Any]:
    """Replay armed events idempotently and persist each current outcome."""
    timestamp = _aware(now or datetime.now(UTC))
    records = list_armed_ingress(store, limit=limit)
    outcomes: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for stored in records:
        ingress = dict(stored)
        persisted_signal_id = str(ingress.pop("_persisted_signal_id"))
        try:
            execution = executor.replay_armed(ingress, now=timestamp)
        except Exception as exc:  # noqa: BLE001 - replay worker must fail closed per event
            execution = {
                "disposition": ARMED_DISPOSITION,
                "reason": "REPLAY_WORKER_ERROR_RETRY_REQUIRED",
                "action": str(ingress.get("action", "")),
                "symbol": str(ingress.get("symbol", "")),
                "paper_execution_triggered": False,
                "paper_ledger_updated": False,
                "trading_authorized": False,
                "live_trading_enabled": False,
                "paper": {},
                "context": {
                    "retry_allowed": True,
                    "error_code": str(exc) or type(exc).__name__,
                },
            }
        store.mark_execution(persisted_signal_id, execution)
        disposition = str(execution.get("disposition", ""))
        counts[disposition] = counts.get(disposition, 0) + 1
        outcomes.append(
            {
                "persisted_signal_id": persisted_signal_id,
                "symbol": execution.get("symbol"),
                "action": execution.get("action"),
                "disposition": disposition,
                "reason": execution.get("reason"),
                "paper_execution_triggered": bool(
                    execution.get("paper_execution_triggered") is True
                ),
                "paper_ledger_updated": bool(
                    execution.get("paper_ledger_updated") is True
                ),
            }
        )

    return {
        "ok": True,
        "operation": "REPLAY_ARMED_SIGNALS",
        "processed_at": timestamp.isoformat(),
        "armed_found": len(records),
        "outcome_counts": counts,
        "outcomes": outcomes,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
