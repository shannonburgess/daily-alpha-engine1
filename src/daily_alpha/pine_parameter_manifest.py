from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any


class PineParameterManifestError(ValueError):
    """A Pine input manifest is incomplete or does not match frozen strategy identity."""


@dataclass(frozen=True, slots=True)
class PineParameterManifest:
    model_id: str
    strategy_version: str
    source_blob_sha: str
    process_orders_on_close: bool
    parameters: Any
    sha256: str


def _required(value: Any, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PineParameterManifestError(f"{name}_REQUIRED")
    return normalized


def _aware_timestamp(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_required(value, name))
    except ValueError as exc:
        raise PineParameterManifestError(f"{name}_INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PineParameterManifestError(f"{name}_MUST_BE_TIMEZONE_AWARE")
    return parsed


def parse_parameter_manifest(
    text: str,
    *,
    parameter_type: type[Any],
    expected_model_id: str,
    expected_strategy_version: str,
    expected_source_blob_sha: str,
    datetime_fields: frozenset[str],
) -> PineParameterManifest:
    """Parse a complete exported Pine input manifest; defaults may not fill missing fields."""
    if not text.strip():
        raise PineParameterManifestError("PARAMETER_MANIFEST_REQUIRED")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PineParameterManifestError("PARAMETER_MANIFEST_INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise PineParameterManifestError("PARAMETER_MANIFEST_MUST_BE_OBJECT")
    allowed_top_level = {
        "model_id",
        "strategy_version",
        "source_blob_sha",
        "process_orders_on_close",
        "parameters",
    }
    if set(payload) != allowed_top_level:
        raise PineParameterManifestError("PARAMETER_MANIFEST_TOP_LEVEL_FIELDS_MISMATCH")

    model_id = _required(payload.get("model_id"), "PARAMETER_MODEL_ID")
    strategy_version = _required(
        payload.get("strategy_version"),
        "PARAMETER_STRATEGY_VERSION",
    )
    source_blob_sha = _required(
        payload.get("source_blob_sha"),
        "PARAMETER_SOURCE_BLOB_SHA",
    )
    if model_id != expected_model_id:
        raise PineParameterManifestError("PARAMETER_MODEL_ID_MISMATCH")
    if strategy_version != expected_strategy_version:
        raise PineParameterManifestError("PARAMETER_STRATEGY_VERSION_MISMATCH")
    if source_blob_sha != expected_source_blob_sha:
        raise PineParameterManifestError("PARAMETER_SOURCE_BLOB_SHA_MISMATCH")
    if payload.get("process_orders_on_close") is not True:
        raise PineParameterManifestError("PROCESS_ORDERS_ON_CLOSE_MUST_BE_TRUE")

    raw_parameters = payload.get("parameters")
    if not isinstance(raw_parameters, dict):
        raise PineParameterManifestError("PARAMETERS_MUST_BE_OBJECT")
    expected_fields = {field.name for field in fields(parameter_type)}
    actual_fields = set(raw_parameters)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        extra = sorted(actual_fields - expected_fields)
        detail = f"missing={','.join(missing)};extra={','.join(extra)}"
        raise PineParameterManifestError(f"PARAMETER_FIELDS_MISMATCH:{detail}")

    values = dict(raw_parameters)
    for field_name in datetime_fields:
        if field_name not in expected_fields:
            raise PineParameterManifestError("PARAMETER_DATETIME_FIELD_NOT_IN_SCHEMA")
        values[field_name] = _aware_timestamp(
            values[field_name],
            f"PARAMETER_{field_name.upper()}",
        )
    try:
        parameters = parameter_type(**values)
    except (TypeError, ValueError) as exc:
        raise PineParameterManifestError("PARAMETER_VALUES_INVALID") from exc

    return PineParameterManifest(
        model_id=model_id,
        strategy_version=strategy_version,
        source_blob_sha=source_blob_sha,
        process_orders_on_close=True,
        parameters=parameters,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


__all__ = [
    "PineParameterManifest",
    "PineParameterManifestError",
    "parse_parameter_manifest",
]
