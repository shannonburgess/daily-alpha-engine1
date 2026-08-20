import io
import json
from datetime import UTC, datetime

from daily_alpha.equity_liquidity import (
    CANONICAL_COMPANY_MIN_AVERAGE_VOLUME,
    LiquidityGatedPaperExecutor,
    S3ActionableLiquidityStore,
    evaluate_persisted_liquidity,
    prepare_actionable_liquidity_inputs,
)

NOW = datetime(2026, 8, 19, 19, 0, tzinfo=UTC)


def _write_csv(path):
    path.write_text(
        "Ticker,Signal,Industry,Last Close Price ($),30-Day Avg Volume,Security Type\n"
        "ABOVE,Buy,Software,100,1500001,Common Stock\n"
        "EQUAL,Buy,Software,100,1500000,Common Stock\n"
        "BELOW,Buy,Software,100,1499999,Common Stock\n"
        "MISSING,Buy,Software,100,,Common Stock\n"
        "ETF1,Buy,ETF,100,100000,ETF\n",
        encoding="utf-8",
    )
    return path


def test_prepare_inputs_filters_companies_but_preserves_etf(tmp_path):
    previous = _write_csv(tmp_path / "OVTLYR_2026-08-18.csv")
    current = _write_csv(tmp_path / "OVTLYR_2026-08-19.csv")

    prepared = prepare_actionable_liquidity_inputs(
        previous,
        current,
        output_dir=tmp_path / "filtered",
        as_of=NOW,
    )

    text = prepared.current_path.read_text(encoding="utf-8")
    assert "ABOVE" in text
    assert "ETF1" in text
    assert "EQUAL" not in text
    assert "BELOW" not in text
    assert "MISSING" not in text
    assert prepared.company_eligible_count == 1
    assert prepared.company_filtered_count == 2
    assert prepared.company_missing_volume_count == 1
    assert prepared.etf_count == 1

    snapshot = json.loads(prepared.snapshot_path.read_text(encoding="utf-8"))
    rows = {row["symbol"]: row for row in snapshot["rows"]}
    assert rows["ABOVE"]["status"] == "ELIGIBLE"
    assert rows["EQUAL"]["status"] == "LIQUIDITY_FILTERED"
    assert rows["BELOW"]["status"] == "LIQUIDITY_FILTERED"
    assert rows["MISSING"]["detail"] == "MISSING_OR_NONPOSITIVE_VOLUME"
    assert rows["ETF1"]["status"] == "ETF_SEPARATE_RULES"
    assert snapshot["company_min_average_volume"] == 1_500_000
    assert snapshot["trading_authorized"] is False
    assert snapshot["live_trading_enabled"] is False


def _snapshot(source_date="2026-08-19"):
    return {
        "source_file": f"OVTLYR_{source_date}.csv",
        "source_date": source_date,
        "generated_at": "2026-08-19T18:00:00+00:00",
        "company_min_average_volume": CANONICAL_COMPANY_MIN_AVERAGE_VOLUME,
        "company_threshold_semantics": "STRICTLY_GREATER_THAN",
        "trading_authorized": False,
        "live_trading_enabled": False,
        "rows": [
            {
                "symbol": "PASS",
                "security_type": "COMPANY_EQUITY",
                "average_daily_share_volume_30d": 1_500_001,
                "status": "ELIGIBLE",
                "detail": "STRICTLY_ABOVE_THRESHOLD",
            },
            {
                "symbol": "FAIL",
                "security_type": "COMPANY_EQUITY",
                "average_daily_share_volume_30d": 1_500_000,
                "status": "LIQUIDITY_FILTERED",
                "detail": "AT_OR_BELOW_THRESHOLD",
            },
            {
                "symbol": "ETF1",
                "security_type": "ETF",
                "average_daily_share_volume_30d": 100_000,
                "status": "ETF_SEPARATE_RULES",
                "detail": "COMPANY_SHARE_VOLUME_GATE_NOT_APPLIED",
            },
        ],
    }


def test_persisted_gate_enforces_strict_company_threshold_and_shortlist():
    snapshot = _snapshot()
    summary = {"current_file": "OVTLYR_2026-08-19.csv"}
    shortlist = [{"symbol": "PASS"}, {"symbol": "FAIL"}, {"symbol": "ETF1"}]

    passed = evaluate_persisted_liquidity(
        "PASS", snapshot=snapshot, shortlist=shortlist, summary=summary, as_of=NOW
    )
    failed = evaluate_persisted_liquidity(
        "FAIL", snapshot=snapshot, shortlist=shortlist, summary=summary, as_of=NOW
    )
    etf = evaluate_persisted_liquidity(
        "ETF1", snapshot=snapshot, shortlist=shortlist, summary=summary, as_of=NOW
    )

    assert passed.allowed is True
    assert failed.allowed is False
    assert failed.reason == "LIQUIDITY_FILTERED"
    assert failed.detail == "AT_OR_BELOW_THRESHOLD"
    assert etf.allowed is True
    assert etf.reason == "ETF_SEPARATE_RULES"

    universe_miss = evaluate_persisted_liquidity(
        "PASS", snapshot=snapshot, shortlist=[], summary=summary, as_of=NOW
    )
    assert universe_miss.allowed is False
    assert universe_miss.reason == "ACTIONABLE_UNIVERSE_FILTERED"


def test_stale_source_fails_closed_as_liquidity_filtered():
    snapshot = _snapshot(source_date="2026-08-14")
    snapshot["generated_at"] = "2026-08-14T18:00:00+00:00"
    decision = evaluate_persisted_liquidity(
        "PASS",
        snapshot=snapshot,
        shortlist=[{"symbol": "PASS"}],
        summary={"current_file": "OVTLYR_2026-08-14.csv"},
        as_of=NOW,
    )
    assert decision.allowed is False
    assert decision.reason == "LIQUIDITY_FILTERED"
    assert decision.detail == "LIQUIDITY_EVIDENCE_STALE"


class FakeDelegate:
    def __init__(self):
        self.calls = []
        self.ledger = object()

    def execute(self, ingress, *, now=None):
        self.calls.append(("execute", ingress["symbol"]))
        return {"disposition": "EXECUTED_PAPER"}

    def replay_armed(self, ingress, *, now=None):
        self.calls.append(("replay", ingress["symbol"]))
        return {"disposition": "EXECUTED_PAPER"}


class FakeStore:
    def __init__(self, decisions):
        self.decisions = decisions

    def evaluate(self, symbol, *, as_of):
        return self.decisions[symbol]


def _decision(symbol, allowed, security_type="COMPANY_EQUITY"):
    from daily_alpha.equity_liquidity import LiquidityDecision

    return LiquidityDecision(
        symbol=symbol,
        allowed=allowed,
        security_type=security_type,
        reason="ELIGIBLE" if allowed else "LIQUIDITY_FILTERED",
        detail="TEST",
        average_daily_share_volume_30d=2_000_000 if allowed else 1_000_000,
        source_date="2026-08-19",
    )


def test_paper_entry_and_replay_cannot_bypass_liquidity_gate():
    delegate = FakeDelegate()
    store = FakeStore({"PASS": _decision("PASS", True), "FAIL": _decision("FAIL", False)})
    executor = LiquidityGatedPaperExecutor(delegate, store)

    blocked = executor.execute({"action": "ENTRY_LONG", "symbol": "FAIL"}, now=NOW)
    blocked_replay = executor.replay_armed(
        {"action": "ENTRY_LONG", "symbol": "FAIL"}, now=NOW
    )
    passed = executor.execute({"action": "ENTRY_LONG", "symbol": "PASS"}, now=NOW)
    exit_result = executor.execute({"action": "EXIT", "symbol": "FAIL"}, now=NOW)

    assert blocked["disposition"] == "NO_TRADE"
    assert blocked["reason"] == "LIQUIDITY_FILTERED"
    assert blocked_replay["reason"] == "LIQUIDITY_FILTERED"
    assert blocked["trading_authorized"] is False
    assert blocked["live_trading_enabled"] is False
    assert passed["disposition"] == "EXECUTED_PAPER"
    assert exit_result["disposition"] == "EXECUTED_PAPER"
    assert delegate.calls == [("execute", "PASS"), ("execute", "FAIL")]


class FakeS3:
    def __init__(self, payloads):
        self.payloads = payloads
        self.keys = []

    def get_object(self, *, Bucket, Key):
        self.keys.append((Bucket, Key))
        name = Key.rsplit("/", 1)[-1]
        return {"Body": io.BytesIO(json.dumps(self.payloads[name]).encode("utf-8"))}


def test_s3_store_binds_snapshot_shortlist_and_summary():
    fake = FakeS3(
        {
            "company_liquidity_eligibility.json": _snapshot(),
            "shortlist.json": [{"symbol": "PASS"}],
            "summary.json": {"current_file": "OVTLYR_2026-08-19.csv"},
        }
    )
    store = S3ActionableLiquidityStore(s3_client=fake, bucket="bucket", prefix="prefix")
    result = store.evaluate("PASS", as_of=NOW)
    assert result.allowed is True
    assert [key for _, key in fake.keys] == [
        "prefix/company_liquidity_eligibility.json",
        "prefix/shortlist.json",
        "prefix/summary.json",
    ]
