from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from .pine_parameter_manifest import parse_parameter_manifest
from .pine_v24_evidence_readiness import (
    EvidenceArtifactState,
    HistoricalV24EvidenceReadiness,
    assess_historical_v24_evidence_readiness,
)
from .pine_v24_parity import (
    PINE_V24_MODEL_ID,
    PINE_V24_SOURCE_BLOB_SHA,
    PINE_V24_SOURCE_PATH,
    PINE_V24_STRATEGY_VERSION,
    V24Parameters,
)
from .pine_v25_evidence_readiness import (
    HistoricalV25EvidenceReadiness,
    assess_historical_v25_evidence_readiness,
)
from .pine_v25_parity import (
    PINE_V25_MODEL_ID,
    PINE_V25_SOURCE_BLOB_SHA,
    PINE_V25_SOURCE_PATH,
    PINE_V25_STRATEGY_VERSION,
    V25Parameters,
)

MARKET_CSV_HEADERS = (
    "time",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "earnings_state",
    "earnings_actual",
    "earnings_known_at",
    "source_id",
)
TRADINGVIEW_SIGNAL_CSV_HEADERS = (
    "bar_time",
    "symbol",
    "action",
    "price",
    "entry_type",
    "runner_stage",
    "quantity_units",
    "source_id",
)
TRADINGVIEW_BAR_OUTCOME_CSV_HEADERS = (
    "bar_time",
    "symbol",
    "outcome_kind",
    "signal_actions",
    "rejection_reasons",
    "entry_type",
    "source_id",
)


class PinePairedEvidenceCaptureError(ValueError):
    """Paired TradingView evidence is incomplete, ambiguous, or cross-wired."""


@dataclass(frozen=True, slots=True)
class StrategyCaptureSpec:
    model_id: str
    strategy_version: str
    book_id: str
    source_path: str
    source_blob_sha: str
    process_orders_on_close: bool
    parameter_fields: tuple[str, ...]
    datetime_parameter_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PairedParityCapturePacket:
    symbol: str
    market_csv_headers: tuple[str, ...]
    tradingview_signal_csv_headers: tuple[str, ...]
    tradingview_bar_outcome_csv_headers: tuple[str, ...]
    sh24: StrategyCaptureSpec
    sh25: StrategyCaptureSpec
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise PinePairedEvidenceCaptureError("SYMBOL_REQUIRED")
        if self.trading_authorized or self.live_trading_enabled:
            raise PinePairedEvidenceCaptureError("CAPTURE_PACKET_CANNOT_AUTHORIZE_TRADING")
        if self.sh24.book_id == self.sh25.book_id:
            raise PinePairedEvidenceCaptureError("CONTROL_AND_CHALLENGER_BOOKS_MUST_BE_DISTINCT")

    @property
    def packet_id(self) -> str:
        payload = {
            "symbol": self.symbol,
            "market_csv_headers": self.market_csv_headers,
            "tradingview_signal_csv_headers": self.tradingview_signal_csv_headers,
            "tradingview_bar_outcome_csv_headers": self.tradingview_bar_outcome_csv_headers,
            "sh24": _spec_payload(self.sh24),
            "sh25": _spec_payload(self.sh25),
            "trading_authorized": False,
            "live_trading_enabled": False,
        }
        return _digest(payload)


@dataclass(frozen=True, slots=True)
class TradingViewInstanceManifest:
    model_id: str
    strategy_version: str
    book_id: str
    source_path: str
    source_blob_sha: str
    script_instance_id: str
    chart_symbol: str
    chart_timeframe: str
    process_orders_on_close: bool
    parameter_manifest_sha256: str
    export_revision: str
    captured_at: datetime
    sha256: str
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.trading_authorized or self.live_trading_enabled:
            raise PinePairedEvidenceCaptureError("TRADINGVIEW_INSTANCE_CANNOT_AUTHORIZE_TRADING")


@dataclass(frozen=True, slots=True)
class PairedHistoricalEvidenceReadiness:
    symbol: str
    sh24: HistoricalV24EvidenceReadiness
    sh25: HistoricalV25EvidenceReadiness
    sh24_instance_state: EvidenceArtifactState
    sh25_instance_state: EvidenceArtifactState
    shared_market_sha256: str | None
    paired_capture_id: str | None
    blockers: tuple[str, ...]
    diagnostics: tuple[str, ...]
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise PinePairedEvidenceCaptureError("SYMBOL_REQUIRED")
        if self.trading_authorized or self.live_trading_enabled:
            raise PinePairedEvidenceCaptureError("PAIRED_READINESS_CANNOT_AUTHORIZE_TRADING")
        if self.ready and not self.paired_capture_id:
            raise PinePairedEvidenceCaptureError("READY_PAIRED_EVIDENCE_REQUIRES_CAPTURE_ID")

    @property
    def ready(self) -> bool:
        return not self.blockers


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PinePairedEvidenceCaptureError(code)
    return normalized


def _sha256_hex(value: Any, code: str) -> str:
    normalized = _required_text(value, code).lower()
    if len(normalized) != 64:
        raise PinePairedEvidenceCaptureError(code)
    try:
        int(normalized, 16)
    except ValueError as exc:
        raise PinePairedEvidenceCaptureError(code) from exc
    return normalized


def _aware_timestamp(value: Any) -> datetime:
    text = _required_text(value, "TRADINGVIEW_CAPTURED_AT_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_CAPTURED_AT_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_CAPTURED_AT_MUST_BE_TIMEZONE_AWARE")
    return parsed


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _spec_payload(spec: StrategyCaptureSpec) -> dict[str, Any]:
    return {
        "model_id": spec.model_id,
        "strategy_version": spec.strategy_version,
        "book_id": spec.book_id,
        "source_path": spec.source_path,
        "source_blob_sha": spec.source_blob_sha,
        "process_orders_on_close": spec.process_orders_on_close,
        "parameter_fields": spec.parameter_fields,
        "datetime_parameter_fields": spec.datetime_parameter_fields,
    }


def _strategy_spec(
    *,
    model_id: str,
    strategy_version: str,
    source_path: str,
    source_blob_sha: str,
    parameter_type: type[Any],
    datetime_fields: tuple[str, ...],
) -> StrategyCaptureSpec:
    return StrategyCaptureSpec(
        model_id=model_id,
        strategy_version=strategy_version,
        book_id=model_id,
        source_path=source_path,
        source_blob_sha=source_blob_sha,
        process_orders_on_close=True,
        parameter_fields=tuple(field.name for field in fields(parameter_type)),
        datetime_parameter_fields=datetime_fields,
    )


def build_paired_parity_capture_packet(symbol: str) -> PairedParityCapturePacket:
    """Return a deterministic no-default capture contract for CONTROL and CHALLENGER evidence."""
    normalized_symbol = _required_text(symbol, "SYMBOL_REQUIRED").upper()
    return PairedParityCapturePacket(
        symbol=normalized_symbol,
        market_csv_headers=MARKET_CSV_HEADERS,
        tradingview_signal_csv_headers=TRADINGVIEW_SIGNAL_CSV_HEADERS,
        tradingview_bar_outcome_csv_headers=TRADINGVIEW_BAR_OUTCOME_CSV_HEADERS,
        sh24=_strategy_spec(
            model_id=PINE_V24_MODEL_ID,
            strategy_version=PINE_V24_STRATEGY_VERSION,
            source_path=PINE_V24_SOURCE_PATH,
            source_blob_sha=PINE_V24_SOURCE_BLOB_SHA,
            parameter_type=V24Parameters,
            datetime_fields=("start_time", "end_time"),
        ),
        sh25=_strategy_spec(
            model_id=PINE_V25_MODEL_ID,
            strategy_version=PINE_V25_STRATEGY_VERSION,
            source_path=PINE_V25_SOURCE_PATH,
            source_blob_sha=PINE_V25_SOURCE_BLOB_SHA,
            parameter_type=V25Parameters,
            datetime_fields=("start_time", "end_time", "shadow_forward_start"),
        ),
    )


def render_parameter_manifest_skeleton(spec: StrategyCaptureSpec) -> dict[str, Any]:
    """Render required Pine input fields without silently substituting Python/Pine defaults."""
    return {
        "model_id": spec.model_id,
        "strategy_version": spec.strategy_version,
        "source_blob_sha": spec.source_blob_sha,
        "process_orders_on_close": True,
        "parameters": {name: None for name in spec.parameter_fields},
    }


def render_tradingview_instance_manifest_skeleton(
    spec: StrategyCaptureSpec,
    *,
    symbol: str,
) -> dict[str, Any]:
    """Render the external identity evidence that must be captured from the actual TV instance."""
    return {
        "model_id": spec.model_id,
        "strategy_version": spec.strategy_version,
        "book_id": spec.book_id,
        "source_path": spec.source_path,
        "source_blob_sha": spec.source_blob_sha,
        "script_instance_id": None,
        "chart_symbol": _required_text(symbol, "SYMBOL_REQUIRED").upper(),
        "chart_timeframe": None,
        "process_orders_on_close": True,
        "parameter_manifest_sha256": None,
        "export_revision": None,
        "captured_at": None,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def render_paired_capture_skeleton(symbol: str) -> dict[str, Any]:
    """Produce one deterministic capture packet for the same-market SH24/SH25 comparison."""
    packet = build_paired_parity_capture_packet(symbol)
    return {
        "schema": "DAILY_ALPHA_PAIRED_PINE_EVIDENCE_CAPTURE_V1",
        "packet_id": packet.packet_id,
        "symbol": packet.symbol,
        "shared_market_csv_headers": list(packet.market_csv_headers),
        "tradingview_signal_csv_headers": list(packet.tradingview_signal_csv_headers),
        "tradingview_bar_outcome_csv_headers": list(packet.tradingview_bar_outcome_csv_headers),
        "sh24": {
            "parameter_manifest": render_parameter_manifest_skeleton(packet.sh24),
            "tradingview_instance": render_tradingview_instance_manifest_skeleton(
                packet.sh24,
                symbol=packet.symbol,
            ),
        },
        "sh25": {
            "parameter_manifest": render_parameter_manifest_skeleton(packet.sh25),
            "tradingview_instance": render_tradingview_instance_manifest_skeleton(
                packet.sh25,
                symbol=packet.symbol,
            ),
        },
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def parse_tradingview_instance_manifest(
    text: str,
    *,
    spec: StrategyCaptureSpec,
    expected_symbol: str,
    expected_parameter_manifest_sha256: str,
) -> TradingViewInstanceManifest:
    """Bind an actual TradingView script instance/export to the exact frozen source and inputs."""
    if not text.strip():
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_INSTANCE_MANIFEST_REQUIRED")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_INSTANCE_MANIFEST_INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_INSTANCE_MANIFEST_MUST_BE_OBJECT")
    expected_fields = {
        "model_id",
        "strategy_version",
        "book_id",
        "source_path",
        "source_blob_sha",
        "script_instance_id",
        "chart_symbol",
        "chart_timeframe",
        "process_orders_on_close",
        "parameter_manifest_sha256",
        "export_revision",
        "captured_at",
        "trading_authorized",
        "live_trading_enabled",
    }
    if set(payload) != expected_fields:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_INSTANCE_FIELDS_MISMATCH")

    identity_checks = {
        "TRADINGVIEW_MODEL_ID_MISMATCH": (payload.get("model_id"), spec.model_id),
        "TRADINGVIEW_STRATEGY_VERSION_MISMATCH": (
            payload.get("strategy_version"),
            spec.strategy_version,
        ),
        "TRADINGVIEW_BOOK_ID_MISMATCH": (payload.get("book_id"), spec.book_id),
        "TRADINGVIEW_SOURCE_PATH_MISMATCH": (payload.get("source_path"), spec.source_path),
        "TRADINGVIEW_SOURCE_BLOB_SHA_MISMATCH": (
            payload.get("source_blob_sha"),
            spec.source_blob_sha,
        ),
    }
    for code, (actual, expected) in identity_checks.items():
        if _required_text(actual, code) != expected:
            raise PinePairedEvidenceCaptureError(code)

    if payload.get("process_orders_on_close") is not True:
        raise PinePairedEvidenceCaptureError("PROCESS_ORDERS_ON_CLOSE_MUST_BE_TRUE")
    if payload.get("trading_authorized") is not False:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_CAPTURE_TRADING_AUTHORITY_MUST_BE_FALSE")
    if payload.get("live_trading_enabled") is not False:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_CAPTURE_LIVE_AUTHORITY_MUST_BE_FALSE")

    normalized_symbol = _required_text(payload.get("chart_symbol"), "TRADINGVIEW_CHART_SYMBOL_REQUIRED").upper()
    if normalized_symbol != _required_text(expected_symbol, "SYMBOL_REQUIRED").upper():
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_CHART_SYMBOL_MISMATCH")
    timeframe = _required_text(payload.get("chart_timeframe"), "TRADINGVIEW_CHART_TIMEFRAME_REQUIRED").upper()
    if timeframe not in {"D", "1D"}:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_CHART_TIMEFRAME_MUST_BE_DAILY")

    parameter_sha = _sha256_hex(
        payload.get("parameter_manifest_sha256"),
        "TRADINGVIEW_PARAMETER_MANIFEST_SHA256_INVALID",
    )
    expected_parameter_sha = _sha256_hex(
        expected_parameter_manifest_sha256,
        "EXPECTED_PARAMETER_MANIFEST_SHA256_INVALID",
    )
    if parameter_sha != expected_parameter_sha:
        raise PinePairedEvidenceCaptureError("TRADINGVIEW_PARAMETER_MANIFEST_SHA256_MISMATCH")

    canonical_payload = dict(payload)
    captured_at = _aware_timestamp(payload.get("captured_at"))
    return TradingViewInstanceManifest(
        model_id=spec.model_id,
        strategy_version=spec.strategy_version,
        book_id=spec.book_id,
        source_path=spec.source_path,
        source_blob_sha=spec.source_blob_sha,
        script_instance_id=_required_text(
            payload.get("script_instance_id"),
            "TRADINGVIEW_SCRIPT_INSTANCE_ID_REQUIRED",
        ),
        chart_symbol=normalized_symbol,
        chart_timeframe=timeframe,
        process_orders_on_close=True,
        parameter_manifest_sha256=parameter_sha,
        export_revision=_required_text(
            payload.get("export_revision"),
            "TRADINGVIEW_EXPORT_REVISION_REQUIRED",
        ),
        captured_at=captured_at,
        sha256=_digest(canonical_payload),
    )


def _validate_instance(
    *,
    manifest_json: str | None,
    spec: StrategyCaptureSpec,
    symbol: str,
    parameter_manifest_json: str | None,
    parameter_type: type[Any],
    datetime_fields: frozenset[str],
) -> tuple[EvidenceArtifactState, TradingViewInstanceManifest | None, tuple[str, ...]]:
    if not manifest_json or not manifest_json.strip():
        return EvidenceArtifactState.MISSING, None, ("TRADINGVIEW_INSTANCE_MANIFEST_MISSING",)
    if not parameter_manifest_json or not parameter_manifest_json.strip():
        return EvidenceArtifactState.INVALID, None, (
            "TRADINGVIEW_INSTANCE_CANNOT_BIND_WITHOUT_PARAMETER_MANIFEST",
        )
    try:
        parameters = parse_parameter_manifest(
            parameter_manifest_json,
            parameter_type=parameter_type,
            expected_model_id=spec.model_id,
            expected_strategy_version=spec.strategy_version,
            expected_source_blob_sha=spec.source_blob_sha,
            datetime_fields=datetime_fields,
        )
        instance = parse_tradingview_instance_manifest(
            manifest_json,
            spec=spec,
            expected_symbol=symbol,
            expected_parameter_manifest_sha256=parameters.sha256,
        )
    except (TypeError, ValueError) as exc:
        return EvidenceArtifactState.INVALID, None, (
            f"TRADINGVIEW_INSTANCE_MANIFEST_INVALID:{type(exc).__name__}:{str(exc).strip()}",
        )
    return EvidenceArtifactState.PRESENT, instance, ()


def assess_paired_historical_evidence_readiness(
    *,
    symbol: str,
    market_csv: str | None = None,
    market_source: str | None = None,
    market_revision: str | None = None,
    sh24_signal_csv: str | None = None,
    sh24_bar_outcome_csv: str | None = None,
    sh24_parameter_manifest_json: str | None = None,
    sh24_instance_manifest_json: str | None = None,
    sh24_tradingview_source: str | None = None,
    sh24_signal_revision: str | None = None,
    sh24_bar_outcome_revision: str | None = None,
    sh25_signal_csv: str | None = None,
    sh25_bar_outcome_csv: str | None = None,
    sh25_parameter_manifest_json: str | None = None,
    sh25_instance_manifest_json: str | None = None,
    sh25_tradingview_source: str | None = None,
    sh25_signal_revision: str | None = None,
    sh25_bar_outcome_revision: str | None = None,
) -> PairedHistoricalEvidenceReadiness:
    """Gate apples-to-apples CONTROL/CHALLENGER proof on one shared PIT market artifact."""
    packet = build_paired_parity_capture_packet(symbol)
    normalized_symbol = packet.symbol
    sh24 = assess_historical_v24_evidence_readiness(
        symbol=normalized_symbol,
        market_csv=market_csv,
        tradingview_signal_csv=sh24_signal_csv,
        tradingview_bar_outcome_csv=sh24_bar_outcome_csv,
        parameter_manifest_json=sh24_parameter_manifest_json,
        market_source=market_source,
        market_revision=market_revision,
        tradingview_source=sh24_tradingview_source,
        tradingview_signal_revision=sh24_signal_revision,
        tradingview_bar_outcome_revision=sh24_bar_outcome_revision,
    )
    sh25 = assess_historical_v25_evidence_readiness(
        symbol=normalized_symbol,
        market_csv=market_csv,
        tradingview_signal_csv=sh25_signal_csv,
        tradingview_bar_outcome_csv=sh25_bar_outcome_csv,
        parameter_manifest_json=sh25_parameter_manifest_json,
        market_source=market_source,
        market_revision=market_revision,
        tradingview_source=sh25_tradingview_source,
        tradingview_signal_revision=sh25_signal_revision,
        tradingview_bar_outcome_revision=sh25_bar_outcome_revision,
    )

    sh24_instance_state, sh24_instance, sh24_instance_diagnostics = _validate_instance(
        manifest_json=sh24_instance_manifest_json,
        spec=packet.sh24,
        symbol=normalized_symbol,
        parameter_manifest_json=sh24_parameter_manifest_json,
        parameter_type=V24Parameters,
        datetime_fields=frozenset({"start_time", "end_time"}),
    )
    sh25_instance_state, sh25_instance, sh25_instance_diagnostics = _validate_instance(
        manifest_json=sh25_instance_manifest_json,
        spec=packet.sh25,
        symbol=normalized_symbol,
        parameter_manifest_json=sh25_parameter_manifest_json,
        parameter_type=V25Parameters,
        datetime_fields=frozenset({"start_time", "end_time", "shadow_forward_start"}),
    )

    blockers = list(sh24.blockers) + list(sh25.blockers)
    diagnostics = list(sh24.diagnostics) + list(sh25.diagnostics)
    if sh24_instance_state is not EvidenceArtifactState.PRESENT:
        blockers.append("SH24_TRADINGVIEW_INSTANCE_EVIDENCE_NOT_PRESENT")
        diagnostics.extend(sh24_instance_diagnostics)
    if sh25_instance_state is not EvidenceArtifactState.PRESENT:
        blockers.append("SH25_TRADINGVIEW_INSTANCE_EVIDENCE_NOT_PRESENT")
        diagnostics.extend(sh25_instance_diagnostics)
    if (
        sh24_instance is not None
        and sh25_instance is not None
        and sh24_instance.script_instance_id == sh25_instance.script_instance_id
    ):
        blockers.append("CONTROL_AND_CHALLENGER_SCRIPT_INSTANCES_MUST_BE_DISTINCT")

    shared_market_sha256 = None
    if market_csv and market_csv.strip():
        shared_market_sha256 = hashlib.sha256(market_csv.encode("utf-8")).hexdigest()

    paired_capture_id: str | None = None
    unique_blockers = tuple(dict.fromkeys(blockers))
    if not unique_blockers and sh24_instance and sh25_instance:
        paired_capture_id = _digest(
            {
                "schema": "DAILY_ALPHA_PAIRED_HISTORICAL_PARITY_CAPTURE_V1",
                "symbol": normalized_symbol,
                "packet_id": packet.packet_id,
                "shared_market_sha256": shared_market_sha256,
                "market_source": market_source,
                "market_revision": market_revision,
                "sh24_reference_id": sh24.locked_reference_id,
                "sh25_reference_id": sh25.locked_reference_id,
                "sh24_instance_sha256": sh24_instance.sha256,
                "sh25_instance_sha256": sh25_instance.sha256,
                "trading_authorized": False,
                "live_trading_enabled": False,
            }
        )

    return PairedHistoricalEvidenceReadiness(
        symbol=normalized_symbol,
        sh24=sh24,
        sh25=sh25,
        sh24_instance_state=sh24_instance_state,
        sh25_instance_state=sh25_instance_state,
        shared_market_sha256=shared_market_sha256,
        paired_capture_id=paired_capture_id,
        blockers=unique_blockers,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "MARKET_CSV_HEADERS",
    "TRADINGVIEW_BAR_OUTCOME_CSV_HEADERS",
    "TRADINGVIEW_SIGNAL_CSV_HEADERS",
    "PairedHistoricalEvidenceReadiness",
    "PairedParityCapturePacket",
    "PinePairedEvidenceCaptureError",
    "StrategyCaptureSpec",
    "TradingViewInstanceManifest",
    "assess_paired_historical_evidence_readiness",
    "build_paired_parity_capture_packet",
    "parse_tradingview_instance_manifest",
    "render_paired_capture_skeleton",
    "render_parameter_manifest_skeleton",
    "render_tradingview_instance_manifest_skeleton",
]
