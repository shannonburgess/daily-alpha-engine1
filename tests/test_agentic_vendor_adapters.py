from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from daily_alpha.agentic.aws_transport import RetryDisposition, TransportResponseReceipt
from daily_alpha.agentic.data_providers import DataDomain, ProviderRole
from daily_alpha.agentic.event_reconciliation import SourceAuthority
from daily_alpha.agentic.market_reconciliation import MarketBar
from daily_alpha.agentic.research_facts import ResearchFactCandidate
from daily_alpha.agentic.vendor_adapters import (
    BenzingaNewsAdapter,
    DatabentoHistoricalAdapter,
    FinancialModelingPrepAdapter,
    MassiveStocksAdapter,
    VendorAdapterError,
    VendorAdapterRoute,
    institutional_vendor_definitions,
    institutional_vendor_registry,
    parse_vendor_transport_receipt,
)


def _receipt(
    provider_id: str,
    body: bytes,
    *,
    received_at: datetime,
    disposition: RetryDisposition = RetryDisposition.SUCCESS,
    status_code: int = 200,
) -> TransportResponseReceipt:
    return TransportResponseReceipt(
        envelope_id="env-1",
        idempotency_key="idem-1",
        provider_id=provider_id,
        request_id="request-1",
        received_at=received_at,
        status_code=status_code,
        latency_ms=25.0,
        body_sha256=hashlib.sha256(body).hexdigest(),
        content_length=len(body),
        disposition=disposition,
    )


def test_vendor_request_specs_use_logical_secrets_without_embedding_keys() -> None:
    massive = MassiveStocksAdapter.aggregate_request(
        ticker="AAPL",
        multiplier=1,
        timespan="day",
        start="2026-08-01",
        end="2026-08-20",
    )
    databento = DatabentoHistoricalAdapter.ohlcv_request(
        dataset="XNAS.ITCH",
        symbol="AAPL",
        schema="ohlcv-1d",
        start="2026-08-01",
        end="2026-08-20",
    )
    fmp = FinancialModelingPrepAdapter.analyst_estimates_request(symbol="AAPL")
    benzinga = BenzingaNewsAdapter.news_request(ticker="AAPL", date_from="2026-08-20")

    assert massive.requires_secret and massive.secret_name == "MASSIVE_API_KEY"
    assert databento.requires_secret and databento.secret_name == "DATABENTO_API_KEY"
    assert fmp.requires_secret and fmp.secret_name == "FMP_API_KEY"
    assert benzinga.requires_secret and benzinga.secret_name == "BENZINGA_API_KEY"

    for request in (massive, databento, fmp, benzinga):
        query = dict(request.query)
        assert "apiKey" not in query
        assert "apikey" not in query
        assert "token" not in query
        assert "YOUR_API_KEY" not in request.url
        assert request.trading_authorized if hasattr(request, "trading_authorized") else True


def test_massive_request_matches_documented_custom_bar_shape() -> None:
    request = MassiveStocksAdapter.aggregate_request(
        ticker="aapl",
        multiplier=5,
        timespan="minute",
        start="2026-08-20",
        end="2026-08-21",
        limit=120,
    )
    assert request.url.endswith("/v2/aggs/ticker/AAPL/range/5/minute/2026-08-20/2026-08-21")
    assert dict(request.query) == {"adjusted": "true", "limit": "120", "sort": "asc"}


def test_massive_fixture_normalizes_to_market_bar_observation() -> None:
    start = datetime(2026, 8, 20, tzinfo=UTC)
    payload = {
        "status": "OK",
        "ticker": "AAPL",
        "request_id": "massive-r1",
        "results": [
            {
                "t": int(start.timestamp() * 1000),
                "o": 225.0,
                "h": 230.0,
                "l": 224.0,
                "c": 229.0,
                "v": 50_000_000,
                "vw": 227.5,
                "n": 1000,
            }
        ],
    }
    observations = MassiveStocksAdapter.parse_aggregate_response(
        payload,
        security_id="sec-aapl",
        ticker="AAPL",
        multiplier=1,
        timespan="day",
        received_at=datetime(2026, 8, 21, 1, tzinfo=UTC),
    )
    assert len(observations) == 1
    observation = observations[0]
    assert observation.provider_id == "MASSIVE"
    assert observation.independence_group == "MASSIVE_MARKET_DATA"
    assert observation.domain is DataDomain.MARKET_BARS
    assert not observation.trading_authorized and not observation.live_trading_enabled
    bar = MarketBar.from_observation(observation)
    assert bar.security_id == "SEC-AAPL"
    assert bar.timeframe == "1D"
    assert bar.close == 229.0
    assert bar.volume == 50_000_000


def test_massive_rejects_symbol_mismatch_and_incomplete_bar() -> None:
    start = datetime(2026, 8, 20, tzinfo=UTC)
    base = {
        "status": "OK",
        "ticker": "MSFT",
        "results": [
            {
                "t": int(start.timestamp() * 1000),
                "o": 100,
                "h": 101,
                "l": 99,
                "c": 100,
                "v": 10,
            }
        ],
    }
    with pytest.raises(VendorAdapterError, match="MASSIVE_RESPONSE_TICKER_MISMATCH"):
        MassiveStocksAdapter.parse_aggregate_response(
            base,
            security_id="SEC-AAPL",
            ticker="AAPL",
            multiplier=1,
            timespan="day",
            received_at=datetime(2026, 8, 21, 1, tzinfo=UTC),
        )

    base["ticker"] = "AAPL"
    with pytest.raises(VendorAdapterError, match="MASSIVE_FUTURE_OR_INCOMPLETE_BAR"):
        MassiveStocksAdapter.parse_aggregate_response(
            base,
            security_id="SEC-AAPL",
            ticker="AAPL",
            multiplier=1,
            timespan="day",
            received_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        )


def test_databento_request_uses_historical_json_contract() -> None:
    request = DatabentoHistoricalAdapter.ohlcv_request(
        dataset="XNAS.ITCH",
        symbol="AAPL",
        schema="ohlcv-1m",
        start="2026-08-20T13:30:00Z",
        end="2026-08-20T20:00:00Z",
        limit=500,
    )
    assert request.url == "https://hist.databento.com/v0/timeseries.get_range"
    query = dict(request.query)
    assert query["dataset"] == "XNAS.ITCH"
    assert query["schema"] == "ohlcv-1m"
    assert query["encoding"] == "json"
    assert query["pretty_px"] == "true"
    assert query["pretty_ts"] == "true"
    assert query["map_symbols"] == "true"


def test_databento_json_lines_transport_handoff_normalizes_bar() -> None:
    record = {
        "hd": {
            "ts_event": "2026-08-20T00:00:00Z",
            "rtype": 35,
            "publisher_id": 90,
            "instrument_id": 38,
        },
        "open": "225.0",
        "high": "230.0",
        "low": "224.0",
        "close": "229.0",
        "volume": 50_000_000,
        "symbol": "AAPL",
    }
    body = (json.dumps(record) + "\n").encode()
    received = datetime(2026, 8, 21, 1, tzinfo=UTC)
    observations = parse_vendor_transport_receipt(
        route=VendorAdapterRoute.DATABENTO_OHLCV,
        receipt=_receipt("DATABENTO", body, received_at=received),
        body=body,
        security_id="SEC-AAPL",
        symbol="AAPL",
        schema="ohlcv-1d",
    )
    assert len(observations) == 1
    observation = observations[0]
    assert observation.provider_id == "DATABENTO"
    assert observation.independence_group == "DATABENTO_MARKET_DATA"
    bar = MarketBar.from_observation(observation)
    assert bar.timeframe == "1D"
    assert bar.open == 225.0
    assert dict(observation.provenance)["publisher_id"] == "90"


def test_databento_rejects_wrong_symbol_and_malformed_json_lines() -> None:
    record = {
        "hd": {"ts_event": "2026-08-20T00:00:00Z"},
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 2,
        "volume": 10,
        "symbol": "MSFT",
    }
    with pytest.raises(VendorAdapterError, match="DATABENTO_RECORD_SYMBOL_MISMATCH"):
        DatabentoHistoricalAdapter.parse_ohlcv_response(
            [record],
            security_id="SEC-AAPL",
            symbol="AAPL",
            schema="ohlcv-1d",
            received_at=datetime(2026, 8, 21, 1, tzinfo=UTC),
        )

    bad = b'{"symbol":"AAPL"}\nnot-json\n'
    with pytest.raises(VendorAdapterError, match="VENDOR_RESPONSE_JSON_LINES_INVALID"):
        parse_vendor_transport_receipt(
            route=VendorAdapterRoute.DATABENTO_OHLCV,
            receipt=_receipt(
                "DATABENTO", bad, received_at=datetime(2026, 8, 21, 1, tzinfo=UTC)
            ),
            body=bad,
            security_id="SEC-AAPL",
            symbol="AAPL",
        )


def test_fmp_income_statement_is_vendor_normalized_capture_time_fact() -> None:
    received = datetime(2026, 8, 21, 12, tzinfo=UTC)
    payload = [
        {
            "date": "2026-06-30",
            "symbol": "AAPL",
            "reportedCurrency": "USD",
            "cik": "0000320193",
            "fillingDate": "2026-07-31",
            "acceptedDate": "2026-07-31 16:05:00",
            "period": "Q3",
            "revenue": 100.0,
            "grossProfit": 40.0,
            "operatingIncome": 30.0,
            "netIncome": 25.0,
            "eps": 1.5,
            "ebitda": 35.0,
        }
    ]
    observations = FinancialModelingPrepAdapter.parse_income_statements(
        payload,
        security_id="SEC-AAPL",
        symbol="AAPL",
        received_at=received,
    )
    observation = observations[0]
    assert observation.domain is DataDomain.FUNDAMENTALS
    candidate = ResearchFactCandidate.from_observation(observation)
    assert candidate.authority is SourceAuthority.VENDOR_NORMALIZED
    assert candidate.known_at == received
    assert candidate.published_at == received
    assert candidate.period_end == datetime(2026, 6, 30, tzinfo=UTC)
    assert candidate.fact_value["revenue"] == 100.0
    assert candidate.primary_document_id is None


def test_fmp_estimate_snapshot_does_not_claim_historical_revision_tape() -> None:
    received = datetime(2026, 8, 21, 12, tzinfo=UTC)
    payload = [
        {
            "symbol": "AAPL",
            "date": "2026-09-30",
            "revenueAvg": 110.0,
            "epsAvg": 1.6,
            "numAnalystsRevenue": 31,
            "numAnalystsEps": 29,
        }
    ]
    observation = FinancialModelingPrepAdapter.parse_analyst_estimates(
        payload,
        security_id="SEC-AAPL",
        symbol="AAPL",
        received_at=received,
    )[0]
    candidate = ResearchFactCandidate.from_observation(observation)
    assert candidate.domain is DataDomain.ESTIMATES_REVISIONS
    assert candidate.period_end == datetime(2026, 9, 30, tzinfo=UTC)
    assert candidate.known_at == received
    assert candidate.revision_id is not None
    assert dict(observation.provenance)["historical_revision_tape_claimed"] == "false"


def test_fmp_rejects_partial_or_cross_symbol_payloads() -> None:
    received = datetime(2026, 8, 21, 12, tzinfo=UTC)
    with pytest.raises(VendorAdapterError, match="FMP_RECORD_SYMBOL_MISMATCH"):
        FinancialModelingPrepAdapter.parse_analyst_estimates(
            [{"symbol": "MSFT", "date": "2026-09-30", "epsAvg": 1.0}],
            security_id="SEC-AAPL",
            symbol="AAPL",
            received_at=received,
        )
    with pytest.raises(VendorAdapterError, match="FMP_STATEMENT_FACT_FIELDS_REQUIRED"):
        FinancialModelingPrepAdapter.parse_income_statements(
            [{"symbol": "AAPL", "date": "2026-06-30", "period": "Q3"}],
            security_id="SEC-AAPL",
            symbol="AAPL",
            received_at=received,
        )


def test_benzinga_news_remains_secondary_vendor_fact() -> None:
    received = datetime(2026, 8, 21, 18, tzinfo=UTC)
    payload = [
        {
            "id": 36444586,
            "author": "Benzinga Insights",
            "created": "Fri, 21 Aug 2026 10:35:14 -0400",
            "updated": "Fri, 21 Aug 2026 10:36:15 -0400",
            "title": "Apple supplier update moves shares",
            "teaser": "A catalyst headline",
            "url": "https://www.benzinga.com/example",
            "channels": [{"name": "News"}],
            "stocks": [{"name": "AAPL", "exchange": "NASDAQ"}],
            "tags": [{"name": "Catalyst"}],
        }
    ]
    observation = BenzingaNewsAdapter.parse_news_response(
        payload,
        security_id="SEC-AAPL",
        ticker="AAPL",
        received_at=received,
    )[0]
    candidate = ResearchFactCandidate.from_observation(observation)
    assert candidate.domain is DataDomain.NEWS_CATALYSTS
    assert candidate.authority is SourceAuthority.SECONDARY
    assert candidate.fact_key == "NEWS:36444586"
    assert candidate.known_at == received
    assert candidate.primary_document_id is None
    assert not observation.trading_authorized and not observation.live_trading_enabled


def test_benzinga_rejects_unassociated_and_future_items() -> None:
    received = datetime(2026, 8, 21, 18, tzinfo=UTC)
    base = {
        "id": 1,
        "created": "Fri, 21 Aug 2026 10:35:14 -0400",
        "updated": "Fri, 21 Aug 2026 10:36:15 -0400",
        "title": "Headline",
        "stocks": [{"name": "MSFT"}],
    }
    with pytest.raises(VendorAdapterError, match="BENZINGA_NEWS_TICKER_MISMATCH"):
        BenzingaNewsAdapter.parse_news_response(
            [base],
            security_id="SEC-AAPL",
            ticker="AAPL",
            received_at=received,
        )

    base["stocks"] = [{"name": "AAPL"}]
    base["created"] = "Sat, 22 Aug 2026 10:35:14 -0400"
    base["updated"] = base["created"]
    with pytest.raises(VendorAdapterError, match="BENZINGA_FUTURE_NEWS_NOT_ALLOWED"):
        BenzingaNewsAdapter.parse_news_response(
            [base],
            security_id="SEC-AAPL",
            ticker="AAPL",
            received_at=received,
        )


def test_transport_handoff_checks_checksum_provider_and_disposition() -> None:
    received = datetime(2026, 8, 21, 18, tzinfo=UTC)
    body = b"[]"
    receipt = _receipt("FMP", body, received_at=received)
    with pytest.raises(VendorAdapterError, match="VENDOR_TRANSPORT_BODY_INVALID"):
        parse_vendor_transport_receipt(
            route=VendorAdapterRoute.FMP_ANALYST_ESTIMATES,
            receipt=receipt,
            body=b"[ ]",
            security_id="SEC-AAPL",
            symbol="AAPL",
        )

    with pytest.raises(VendorAdapterError, match="VENDOR_TRANSPORT_PROVIDER_ROUTE_MISMATCH"):
        parse_vendor_transport_receipt(
            route=VendorAdapterRoute.BENZINGA_NEWS,
            receipt=receipt,
            body=body,
            security_id="SEC-AAPL",
            symbol="AAPL",
        )

    failed = _receipt(
        "FMP",
        body,
        received_at=received,
        disposition=RetryDisposition.RETRYABLE,
        status_code=500,
    )
    with pytest.raises(VendorAdapterError, match="VENDOR_TRANSPORT_RECEIPT_NOT_SUCCESS"):
        parse_vendor_transport_receipt(
            route=VendorAdapterRoute.FMP_ANALYST_ESTIMATES,
            receipt=failed,
            body=body,
            security_id="SEC-AAPL",
            symbol="AAPL",
        )


def test_transport_handoff_rejects_malformed_json() -> None:
    received = datetime(2026, 8, 21, 18, tzinfo=UTC)
    body = b"not-json"
    with pytest.raises(VendorAdapterError, match="VENDOR_RESPONSE_JSON_INVALID"):
        parse_vendor_transport_receipt(
            route=VendorAdapterRoute.FMP_INCOME_STATEMENT,
            receipt=_receipt("FMP", body, received_at=received),
            body=body,
            security_id="SEC-AAPL",
            symbol="AAPL",
        )


def test_vendor_registry_preserves_independent_market_sources_and_roles() -> None:
    definitions = institutional_vendor_definitions()
    assert {item.provider_id for item in definitions} == {
        "MASSIVE",
        "DATABENTO",
        "FMP",
        "BENZINGA",
    }
    registry = institutional_vendor_registry()
    market = registry.providers_for(DataDomain.MARKET_BARS)
    assert {item.independence_group for item in market} == {
        "MASSIVE_MARKET_DATA",
        "DATABENTO_MARKET_DATA",
    }
    roles = {
        item.provider_id: item.capability_for(DataDomain.MARKET_BARS).role
        for item in market
    }
    assert roles == {"DATABENTO": ProviderRole.SECONDARY, "MASSIVE": ProviderRole.PRIMARY}


def test_all_vendor_definitions_and_observations_remain_research_only() -> None:
    for definition in institutional_vendor_definitions():
        assert definition.research_only
        assert not definition.trading_authorized
        assert not definition.live_trading_enabled
