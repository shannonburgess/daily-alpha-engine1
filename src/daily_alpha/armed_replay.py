"""Durable replay worker for Pine signals armed outside the tradable window.

The original ingress event is already persisted in the Pine event store. This
module scans only events whose current disposition is still
``ARMED_FOR_NEXT_TRADABLE_WINDOW``, revalidates them through the reconciled
paper executor, and writes the new outcome back to the same audit record.

No live brokerage path is present here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .pine_processor import PineProcessorError

ARMED_DISPOSITION = "ARMED_FOR_NEXT_TRADABLE_WINDOW"
DEFAULT_REPLAY_LIMIT = 25
MAX_REPLAY_LIMIT = 100
DEFAULT_REPLAY_LEASE_SECONDS = 300
MAX_REPLAY_LEASE_SECONDS = 1800
DEFAULT_MONITOR_EVENT_LIMIT = 100
MAX_MONITOR_EVENT_LIMIT = 250
MAX_MONITOR_SCAN_PAGES = 20
MONITOR_SCAN_PAGE_SIZE = 250


def list_armed_ingress(
    store: Any,
    *,
    limit: int = DEFAULT_REPLAY_LIMIT,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return a bounded set of claimable durably armed ingress events."""
    if limit <= 0 or limit > MAX_REPLAY_LIMIT:
        raise PineProcessorError("ARMED_REPLAY_LIMIT_INVALID")
    timestamp = _aware(now or datetime.now(UTC))
    prefix = f"ACCOUNT#{store.account_id}#PINE_EVENT#"
    kwargs: dict[str, Any] = {
        "TableName": store.table_name,
        "FilterExpression": (
            "begins_with(pk, :prefix) AND #sk = :received "
            "AND disposition = :armed AND "
            "(attribute_not_exists(replay_lease_until_epoch) "
            "OR replay_lease_until_epoch < :now_epoch)"
        ),
        "ExpressionAttributeNames": {"#sk": "sk"},
        "ExpressionAttributeValues": {
            ":prefix": {"S": prefix},
            ":received": {"S": "RECEIVED"},
            ":armed": {"S": ARMED_DISPOSITION},
            ":now_epoch": {"N": str(int(timestamp.timestamp()))},
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


def claim_armed_ingress(
    store: Any,
    signal_id: str,
    *,
    now: datetime,
    lease_seconds: int = DEFAULT_REPLAY_LEASE_SECONDS,
) -> str | None:
    """Atomically lease one still-armed event so concurrent replay cannot double-run it.

    A lease deliberately leaves the disposition ARMED. If a worker dies before it
    writes an outcome, the record becomes claimable again after the bounded lease
    expires rather than being stranded in an in-progress state.
    """
    signal_id = str(signal_id).strip()
    if not signal_id:
        raise PineProcessorError("ARMED_REPLAY_SIGNAL_ID_REQUIRED")
    if lease_seconds <= 0 or lease_seconds > MAX_REPLAY_LEASE_SECONDS:
        raise PineProcessorError("ARMED_REPLAY_LEASE_INVALID")

    timestamp = _aware(now)
    now_epoch = int(timestamp.timestamp())
    lease_token = uuid4().hex
    try:
        store.client.update_item(
            TableName=store.table_name,
            Key={
                "pk": {"S": f"ACCOUNT#{store.account_id}#PINE_EVENT#{signal_id}"},
                "sk": {"S": "RECEIVED"},
            },
            UpdateExpression=(
                "SET replay_lease_until_epoch = :lease_until, "
                "replay_lease_token = :lease_token"
            ),
            ExpressionAttributeValues={
                ":armed": {"S": ARMED_DISPOSITION},
                ":now_epoch": {"N": str(now_epoch)},
                ":lease_until": {"N": str(now_epoch + lease_seconds)},
                ":lease_token": {"S": lease_token},
            },
            ConditionExpression=(
                "disposition = :armed AND "
                "(attribute_not_exists(replay_lease_until_epoch) "
                "OR replay_lease_until_epoch < :now_epoch)"
            ),
        )
    except Exception as exc:
        if _aws_error_code(exc) == "ConditionalCheckFailedException":
            return None
        raise PineProcessorError("ARMED_REPLAY_DYNAMODB_CLAIM_FAILED") from exc
    return lease_token


def list_recent_pine_event_state(
    store: Any,
    *,
    limit: int = DEFAULT_MONITOR_EVENT_LIMIT,
) -> dict[str, Any]:
    """Return bounded recent Pine event/outcome evidence for read-only monitoring.

    The paper ledger table has no account/date GSI yet, so this uses a bounded scan
    and reports when the scan-page cap was reached. Older history omitted only by
    the response limit is reported separately and is not treated as an incomplete
    Dynamo scan. It never mutates event or ledger state.
    """
    if limit <= 0 or limit > MAX_MONITOR_EVENT_LIMIT:
        raise PineProcessorError("SHADOW_MONITOR_EVENT_LIMIT_INVALID")

    prefix = f"ACCOUNT#{store.account_id}#PINE_EVENT#"
    kwargs: dict[str, Any] = {
        "TableName": store.table_name,
        "FilterExpression": "begins_with(pk, :prefix) AND #sk = :received",
        "ExpressionAttributeNames": {"#sk": "sk"},
        "ExpressionAttributeValues": {
            ":prefix": {"S": prefix},
            ":received": {"S": "RECEIVED"},
        },
        "Limit": MONITOR_SCAN_PAGE_SIZE,
    }
    records: list[dict[str, Any]] = []
    evaluated = 0
    pages = 0
    scan_truncated = False

    while pages < MAX_MONITOR_SCAN_PAGES:
        try:
            response = store.client.scan(**kwargs)
        except Exception as exc:
            raise PineProcessorError("SHADOW_MONITOR_DYNAMODB_SCAN_FAILED") from exc
        pages += 1
        evaluated += int(response.get("ScannedCount", 0))
        for item in response.get("Items", []):
            record = _decode_monitor_event(item)
            if record is not None:
                records.append(record)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    else:
        scan_truncated = True

    records.sort(key=_monitor_sort_key, reverse=True)
    visible = records[:limit]
    history_omitted = max(0, len(records) - len(visible))

    return {
        "events": visible,
        "event_count_visible": len(visible),
        "event_count_scanned": len(records),
        "event_history_omitted": history_omitted,
        "event_limit": limit,
        "scan_pages": pages,
        "scan_items_evaluated": evaluated,
        "scan_truncated": scan_truncated,
    }


def _decode_monitor_event(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    signal_id = item.get("signal_id", {}).get("S")
    raw_ingress = item.get("ingress_json", {}).get("S")
    if not signal_id or not raw_ingress:
        return None
    try:
        ingress = json.loads(raw_ingress)
    except json.JSONDecodeError as exc:
        raise PineProcessorError("SHADOW_MONITOR_INGRESS_JSON_INVALID") from exc
    if not isinstance(ingress, dict):
        raise PineProcessorError("SHADOW_MONITOR_INGRESS_MUST_BE_OBJECT")

    execution: dict[str, Any] = {}
    raw_execution = item.get("execution_json", {}).get("S")
    if raw_execution:
        try:
            decoded_execution = json.loads(raw_execution)
        except json.JSONDecodeError as exc:
            raise PineProcessorError("SHADOW_MONITOR_EXECUTION_JSON_INVALID") from exc
        if not isinstance(decoded_execution, dict):
            raise PineProcessorError("SHADOW_MONITOR_EXECUTION_MUST_BE_OBJECT")
        execution = decoded_execution

    receipt = execution.get("execution_receipt")
    if receipt is not None and not isinstance(receipt, dict):
        raise PineProcessorError("SHADOW_MONITOR_RECEIPT_MUST_BE_OBJECT")

    return {
        "signal_id": str(signal_id),
        "symbol": str(item.get("symbol", {}).get("S") or ingress.get("symbol") or ""),
        "action": str(item.get("action", {}).get("S") or ingress.get("action") or ""),
        "model_id": ingress.get("model_id"),
        "forward_test_start": ingress.get("forward_test_start"),
        "replay_max_price": ingress.get("replay_max_price"),
        "received_at": ingress.get("received_at"),
        "disposition": str(
            item.get("disposition", {}).get("S")
            or execution.get("disposition")
            or ""
        ),
        "reason": str(item.get("reason", {}).get("S") or execution.get("reason") or ""),
        "evaluated_at": execution.get("evaluated_at"),
        "paper_execution_triggered": execution.get("paper_execution_triggered") is True,
        "paper_ledger_updated": execution.get("paper_ledger_updated") is True,
        "paper_account_id": execution.get("paper_account_id"),
        "execution_receipt": receipt,
        "trading_authorized": execution.get("trading_authorized", False),
        "live_trading_enabled": execution.get("live_trading_enabled", False),
    }


def _monitor_sort_key(record: dict[str, Any]) -> datetime:
    value = record.get("received_at")
    if value:
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def replay_armed_events(
    store: Any,
    executor: Any,
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_REPLAY_LIMIT,
) -> dict[str, Any]:
    """Replay claimable armed events and persist each current outcome."""
    timestamp = _aware(now or datetime.now(UTC))
    records = list_armed_ingress(store, limit=limit, now=timestamp)
    outcomes: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    claimed = 0
    lease_conflicts = 0

    for stored in records:
        ingress = dict(stored)
        persisted_signal_id = str(ingress.pop("_persisted_signal_id"))
        lease_token = claim_armed_ingress(store, persisted_signal_id, now=timestamp)
        if lease_token is None:
            lease_conflicts += 1
            continue
        claimed += 1
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
                    "replay_lease_token_present": bool(lease_token),
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
        "armed_claimed": claimed,
        "lease_conflicts": lease_conflicts,
        "outcome_counts": counts,
        "outcomes": outcomes,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _aws_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code", ""))
    return ""
