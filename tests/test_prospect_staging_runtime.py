import json
from datetime import UTC, datetime

import pytest

from daily_alpha.prospect_staging_runtime import (
    AwsProspectStagingRuntimePublisher,
    ProspectStagingRuntimeError,
)

NOW = datetime(2026, 8, 24, 13, 5, tzinfo=UTC)


def _row(rank: int, *, status: str = "LEADER", orats_status: str = "ENRICHED"):
    return {
        "rank": rank,
        "symbol": f"T{rank:02d}",
        "ovtlyr_status": status,
        "display_label": status.replace("_", " "),
        "classification_reason": "Governed stock-primary research candidate.",
        "score": float(101 - rank),
        "sector": "Technology",
        "industry": "Semiconductors",
        "sector_net_score": 10,
        "trend": "UP",
        "momentum": "RISING",
        "optionable": True,
        "price": 100.0 + rank,
        "average_volume": 2_500_000.0,
        "orats_status": orats_status,
        "orats_reason": (
            "ORATS_PROVIDER_ERROR_STOCK_RETAINED"
            if orats_status == "DATA_ERROR"
            else "QUALIFIED_OPTION_RESEARCH_ONLY"
        ),
        "selected_expiration": "2026-10-16" if orats_status == "ENRICHED" else "",
        "selected_strike": 100.0 if orats_status == "ENRICHED" else 0.0,
        "selected_delta": 0.55 if orats_status == "ENRICHED" else None,
        "selected_spread_pct": 0.03 if orats_status == "ENRICHED" else None,
        "selected_volume": 200 if orats_status == "ENRICHED" else 0,
        "selected_open_interest": 100 if orats_status == "ENRICHED" else 0,
    }


def _classification(rank: int, *, status: str = "LEADER", reason: str | None = None):
    return {
        "symbol": f"T{rank:02d}",
        "status": status,
        "display_label": status.replace("_", " "),
        "signal": "BUY" if status != "REMOVED" else "HOLD",
        "previous_signal": "BUY",
        "signal_date": "2026-08-24",
        "sector": "Technology",
        "industry": "Semiconductors",
        "trend": "UP" if status != "REMOVED" else "DOWN",
        "momentum": "WEAKENING" if status == "DETERIORATING" else "RISING",
        "optionable": True,
        "reason": reason or f"Lifecycle audit: {status}",
    }


class _Body:
    def __init__(self, value: bytes):
        self.value = value

    def read(self) -> bytes:
        return self.value


class _S3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get_object(self, *, Bucket, Key):
        assert Bucket == "unit-bucket"
        return {"Body": _Body(self.objects[Key])}

    def put_object(self, *, Bucket, Key, Body, ContentType, ServerSideEncryption):
        assert Bucket == "unit-bucket"
        assert ContentType
        assert ServerSideEncryption == "AES256"
        self.objects[Key] = bytes(Body)
        return {}


def _publisher(rows, *, classifications=None):
    s3 = _S3()
    s3.objects["ovtlyr/shortlist/latest/shortlist.json"] = (
        json.dumps(rows, sort_keys=True) + "\n"
    ).encode()
    lifecycle_rows = classifications
    if lifecycle_rows is None:
        lifecycle_rows = [
            _classification(
                int(str(row["symbol"])[1:]),
                status=str(row.get("ovtlyr_status") or "UNCHANGED"),
                reason=str(row.get("classification_reason") or ""),
            )
            for row in rows
        ]
    s3.objects["ovtlyr/shortlist/latest/classifications.json"] = (
        json.dumps(lifecycle_rows, sort_keys=True) + "\n"
    ).encode()
    s3.objects["daily-alpha/outputs/latest/newsletter.html"] = (
        b"<!doctype html><html><head><title>Daily Alpha</title></head>"
        b"<body><main><section><h2>Existing Daily Alpha Research</h2></section>"
        b"</main></body></html>"
    )
    return s3, AwsProspectStagingRuntimePublisher(s3_client=s3, bucket="unit-bucket")


def test_prepare_preserves_all_50_qualifiers_with_top3_plus_47():
    rows = [_row(rank) for rank in range(1, 51)]
    s3, publisher = _publisher(rows)

    prepared = publisher.prepare(
        history_prefix="daily-alpha/outputs/history/2026-08-24/morning-run",
        as_of=NOW,
    )

    assert prepared.board.total_qualifying == 50
    assert [item.symbol for item in prepared.board.top_picks] == ["T01", "T02", "T03"]
    assert all(item.instrument_selected == "OPTION" for item in prepared.board.top_picks)
    assert len(prepared.board.additional_opportunities) == 47
    assert tuple(item.rank for item in prepared.board.opportunities) == tuple(range(1, 51))
    assert {item.symbol for item in prepared.board.opportunities} == {
        f"T{rank:02d}" for rank in range(1, 51)
    }
    assert prepared.board.filtered == ()
    assert "shortlist=" in prepared.board.source_revision
    assert "classifications=" in prepared.board.source_revision

    for output in prepared.outputs:
        assert output.board_id == prepared.board.board_id
        assert output.total_qualifying == 50
        assert len(output.complete_qualifying) == 50
        assert [item.symbol for item in output.top_picks] == ["T01", "T02", "T03"]
        assert output.trading_authorized is False
        assert output.live_trading_enabled is False

    html = prepared.newsletter_html
    assert "Top 3 ConvexRidge Picks" in html
    assert "Additional Qualified Opportunities (47)" in html
    assert f'data-board-id="{prepared.board.board_id}"' in html
    assert 'data-total-qualifying="50"' in html
    for rank in range(1, 51):
        assert f"T{rank:02d}" in html

    latest = "daily-alpha/outputs/latest/"
    history = "daily-alpha/outputs/history/2026-08-24/morning-run/"
    for name in (
        "newsletter.html",
        "prospect_opportunity_board.json",
        "prospect_newsletter.json",
        "prospect_dashboard.json",
        "prospect_api.json",
        "prospect_newsletter.html",
    ):
        assert latest + name in s3.objects
        assert history + name in s3.objects


def test_orats_data_error_is_nonblocking_for_actionable_stock_research():
    rows = [
        _row(1, status="NEW_BUY", orats_status="DATA_ERROR"),
        _row(2, status="EMERGING", orats_status="ENRICHED"),
    ]
    _, publisher = _publisher(rows)

    prepared = publisher.prepare(
        history_prefix="daily-alpha/outputs/history/2026-08-24/manual-run",
        as_of=NOW,
    )

    assert prepared.board.total_qualifying == 2
    first = next(item for item in prepared.board.opportunities if item.symbol == "T01")
    assert first.lifecycle_status == "NEW_BUY"
    assert first.bucket == "ENTRY_WATCH"
    assert first.instrument_selected == "STOCK"
    assert first.pine_entry is False
    assert first.risk_gate_passed is False
    assert "ORATS_NONBLOCKING_DATA_ERROR" in first.fallback_reason


def test_complete_classification_source_adds_filtered_lifecycle_without_qualifying_names():
    shortlist = [_row(1, status="LEADER")]
    classifications = [
        _classification(1, status="LEADER"),
        _classification(2, status="DETERIORATING", reason="Existing BUY momentum is weakening"),
        _classification(3, status="REMOVED", reason="Prior BUY is no longer rated BUY"),
        _classification(4, status="ACTIVE_BUY", reason="No higher-priority setup"),
    ]
    _, publisher = _publisher(shortlist, classifications=classifications)

    prepared = publisher.prepare(
        history_prefix="daily-alpha/outputs/history/2026-08-24/manual-run",
        as_of=NOW,
    )

    assert [item.symbol for item in prepared.board.opportunities] == ["T01"]
    assert {item.symbol for item in prepared.board.filtered} == {"T02", "T03", "T04"}
    filtered = {item.symbol: item for item in prepared.board.filtered}
    assert filtered["T02"].lifecycle_status == "DETERIORATING"
    assert "Existing BUY momentum is weakening" in filtered["T02"].reason
    assert filtered["T03"].lifecycle_status == "REMOVED"
    assert "Prior BUY is no longer rated BUY" in filtered["T03"].reason
    assert filtered["T04"].lifecycle_status == "ACTIVE_BUY"
    assert all(item.evidence_lineage == (prepared.board.source_revision,) for item in filtered.values())


def test_missing_classification_audit_source_fails_closed():
    rows = [_row(1)]
    s3, publisher = _publisher(rows)
    del s3.objects["ovtlyr/shortlist/latest/classifications.json"]

    with pytest.raises(
        ProspectStagingRuntimeError,
        match="PROSPECT_S3_READ_FAILED:ovtlyr/shortlist/latest/classifications.json",
    ):
        publisher.prepare(
            history_prefix="daily-alpha/outputs/history/2026-08-24/manual-run",
            as_of=NOW,
        )


def test_delivery_true_completes_initial_rollout_gate_and_persists_receipt():
    s3, publisher = _publisher([_row(rank) for rank in range(1, 6)])
    prepared = publisher.prepare(
        history_prefix="daily-alpha/outputs/history/2026-08-24/morning-run",
        as_of=NOW,
    )

    gate = publisher.finalize_delivery(prepared, delivery_contract_validated=True)

    assert gate.ready is True
    assert gate.reasons == ()
    assert gate.delivery_contract_validated is True
    assert gate.trading_authorized is False
    assert gate.live_trading_enabled is False
    latest = json.loads(
        s3.objects["daily-alpha/outputs/latest/prospect_launch_gate.json"].decode()
    )
    history = json.loads(
        s3.objects[
            "daily-alpha/outputs/history/2026-08-24/morning-run/prospect_launch_gate.json"
        ].decode()
    )
    assert latest == history
    assert latest["ready"] is True
    assert latest["total_qualifying"] == 5
    assert latest["trading_authorized"] is False
    assert latest["live_trading_enabled"] is False


def test_delivery_false_keeps_v1_launch_gate_closed():
    s3, publisher = _publisher([_row(rank) for rank in range(1, 4)])
    prepared = publisher.prepare(
        history_prefix="daily-alpha/outputs/history/2026-08-24/morning-run",
        as_of=NOW,
    )

    gate = publisher.finalize_delivery(prepared, delivery_contract_validated=False)

    assert gate.ready is False
    assert "NEWSLETTER_DELIVERY_CONTRACT_NOT_VALIDATED" in gate.reasons
    persisted = json.loads(
        s3.objects["daily-alpha/outputs/latest/prospect_launch_gate.json"].decode()
    )
    assert persisted["ready"] is False
    assert persisted["delivery_contract_validated"] is False
