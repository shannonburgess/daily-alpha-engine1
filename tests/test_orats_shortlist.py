from datetime import UTC, datetime

from daily_alpha.models import OptionCandidate
from daily_alpha.orats import OratsChain
from daily_alpha.orats_shortlist import (
    EnrichmentStatus,
    OratsShortlistEnricher,
    RankedCandidate,
)
from daily_alpha.sources import OratsBatchResult

NOW = datetime(2026, 8, 17, 21, 30, tzinfo=UTC)


def chain(symbol):
    contract = OptionCandidate(symbol, "2026-10-16", 100, "CALL", 60, 5, 5.2, 1000, 100)
    return OratsChain(symbol, (contract,), NOW, "delayed")


class FakeSource:
    def __init__(self, failed=()):
        self.failed = set(failed)
        self.requested = ()

    def fetch(self, symbols, *, as_of):
        self.requested = symbols
        return OratsBatchResult(
            tuple(chain(symbol) for symbol in symbols if symbol not in self.failed),
            tuple(
                (symbol, "ORATS_DATA_ERROR")
                for symbol in symbols
                if symbol in self.failed
            ),
        )


def test_only_pine_and_risk_approved_candidates_consume_api_calls():
    source = FakeSource()
    candidates = (
        RankedCandidate("AAPL", 90, True, True),
        RankedCandidate("MSFT", 95, False, True),
        RankedCandidate("NVDA", 85, True, False),
    )
    result = OratsShortlistEnricher(source).enrich(candidates, as_of=NOW)
    assert source.requested == ("AAPL",)
    assert result.api_requests == 1
    assert [item.status for item in result.candidates] == [
        EnrichmentStatus.ENRICHED,
        EnrichmentStatus.NOT_REQUESTED,
        EnrichmentStatus.NOT_REQUESTED,
    ]


def test_request_limit_uses_score_order_without_reordering_output():
    source = FakeSource()
    candidates = (
        RankedCandidate("LOW", 10, True, True),
        RankedCandidate("HIGH", 90, True, True),
        RankedCandidate("MID", 50, True, True),
    )
    result = OratsShortlistEnricher(source, request_limit=2).enrich(
        candidates, as_of=NOW
    )
    assert source.requested == ("HIGH", "MID")
    assert result.candidates[0].reason == "API_LIMIT_REACHED"
    assert [item.candidate.symbol for item in result.candidates] == [
        "LOW",
        "HIGH",
        "MID",
    ]


def test_orats_failure_is_explicit_data_error_with_no_chain():
    source = FakeSource(("AAPL",))
    result = OratsShortlistEnricher(source).enrich(
        (RankedCandidate("AAPL", 90, True, True),), as_of=NOW
    )
    item = result.candidates[0]
    assert item.status == EnrichmentStatus.DATA_ERROR
    assert item.reason == "ORATS_DATA_ERROR"
    assert item.chain is None
    assert result.has_data_errors is True


def test_request_limit_must_be_positive():
    try:
        OratsShortlistEnricher(FakeSource(), request_limit=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected request-limit validation")
