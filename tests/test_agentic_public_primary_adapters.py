from datetime import UTC, date, datetime

import pytest

from daily_alpha.agentic.contracts import EvidenceStatus
from daily_alpha.agentic.data_providers import DataDomain
from daily_alpha.agentic.public_primary_adapters import (
    FredAlfredAdapter,
    OpenFigiAdapter,
    PublicPrimaryAdapterError,
    SecEdgarAdapter,
)

NOW = datetime(2026, 8, 21, 20, 0, tzinfo=UTC)


def test_openfigi_request_is_deterministic_and_contains_no_secret():
    request = OpenFigiAdapter.mapping_request(id_type="TICKER", id_value="AAPL")
    assert request.url == "https://api.openfigi.com/v3/mapping"
    assert request.json_body == [{"idType": "TICKER", "idValue": "AAPL"}]
    assert request.requires_secret is False
    assert request.secret_name is None
    assert request.request_id == OpenFigiAdapter.mapping_request(
        id_type="TICKER",
        id_value="AAPL",
    ).request_id


def test_openfigi_mapping_response_normalizes_reference_identity():
    payload = [
        {
            "data": [
                {
                    "figi": "BBG000B9XRY4",
                    "compositeFIGI": "BBG000B9XRY4",
                    "shareClassFIGI": "BBG001S5N8V8",
                    "ticker": "AAPL",
                    "name": "APPLE INC",
                    "securityType": "Common Stock",
                    "marketSector": "Equity",
                    "exchCode": "US",
                }
            ]
        }
    ]
    mappings = OpenFigiAdapter.parse_mapping_response(payload)
    assert len(mappings) == 1
    assert mappings[0].figi == "BBG000B9XRY4"
    assert mappings[0].ticker == "AAPL"
    assert mappings[0].mapping_id


def test_openfigi_error_payload_fails_closed():
    with pytest.raises(PublicPrimaryAdapterError, match="OPENFIGI_MAPPING_ERROR"):
        OpenFigiAdapter.parse_mapping_response([{"error": "No identifier found"}])


def test_sec_cik_normalization_and_request_url():
    assert SecEdgarAdapter.normalize_cik("320193") == "0000320193"
    assert SecEdgarAdapter.normalize_cik("CIK0000320193") == "0000320193"
    request = SecEdgarAdapter.submissions_request("320193")
    assert request.url == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert request.requires_secret is False


def test_sec_recent_filings_parse_to_primary_provider_evidence():
    payload = {
        "cik": "320193",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001"],
                "filingDate": ["2026-08-20"],
                "reportDate": ["2026-08-19"],
                "acceptanceDateTime": ["2026-08-20T16:11:25.000Z"],
                "form": ["8-K"],
                "primaryDocument": ["aapl-20260819.htm"],
                "primaryDocDescription": ["Current report"],
            }
        },
    }
    records = SecEdgarAdapter.parse_recent_filings(payload)
    assert len(records) == 1
    filing = records[0]
    assert filing.cik == "0000320193"
    assert filing.form == "8-K"
    observation = filing.to_provider_observation(
        security_id="DAI-SEC-AAPL",
        received_at=datetime(2026, 8, 20, 16, 11, 26, tzinfo=UTC),
    )
    assert observation.domain is DataDomain.SEC_FILINGS
    assert observation.status is EvidenceStatus.COMPLETE
    assert observation.subject_key == "SECURITY:DAI-SEC-AAPL"
    assert ("source_authority", "REGULATOR_PRIMARY") in observation.provenance


def test_sec_compact_acceptance_timestamp_converts_eastern_to_utc():
    payload = {
        "cik": "320193",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001"],
                "filingDate": ["2026-08-20"],
                "reportDate": ["2026-08-19"],
                "acceptanceDateTime": ["20260820161125"],
                "form": ["8-K"],
                "primaryDocument": ["aapl.htm"],
                "primaryDocDescription": ["Current report"],
            }
        },
    }
    filing = SecEdgarAdapter.parse_recent_filings(payload)[0]
    assert filing.acceptance_datetime == datetime(2026, 8, 20, 20, 11, 25, tzinfo=UTC)


def test_sec_received_before_acceptance_is_rejected():
    payload = {
        "cik": "320193",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001"],
                "filingDate": ["2026-08-20"],
                "reportDate": [""],
                "acceptanceDateTime": ["2026-08-20T16:11:25.000Z"],
                "form": ["8-K"],
                "primaryDocument": ["aapl.htm"],
                "primaryDocDescription": [""],
            }
        },
    }
    filing = SecEdgarAdapter.parse_recent_filings(payload)[0]
    with pytest.raises(PublicPrimaryAdapterError, match="SEC_RECEIVED_BEFORE_ACCEPTANCE"):
        filing.to_provider_observation(
            security_id="DAI-SEC-AAPL",
            received_at=datetime(2026, 8, 20, 16, 11, 24, tzinfo=UTC),
        )


def test_fred_request_uses_as_of_real_time_period_and_secret_reference_only():
    request = FredAlfredAdapter.observations_request(
        series_id="CPIAUCSL",
        as_of_date=date(2024, 1, 15),
    )
    query = dict(request.query)
    assert query["series_id"] == "CPIAUCSL"
    assert query["realtime_start"] == "2024-01-15"
    assert query["realtime_end"] == "2024-01-15"
    assert query["file_type"] == "json"
    assert request.requires_secret is True
    assert request.secret_name == "FRED_API_KEY"
    assert "api_key" not in query


def test_fred_vintage_payload_normalizes_point_in_time_macro_evidence():
    payload = {
        "observations": [
            {
                "realtime_start": "2024-01-15",
                "realtime_end": "2024-02-14",
                "date": "2023-12-01",
                "value": "308.742",
            }
        ]
    }
    vintage = FredAlfredAdapter.parse_observations(payload, series_id="CPIAUCSL")[0]
    observation = vintage.to_provider_observation(
        as_of=datetime(2024, 1, 15, 23, 59, tzinfo=UTC)
    )
    assert observation.domain is DataDomain.MACRO
    assert observation.metric == "CPIAUCSL"
    assert observation.subject_key == "GLOBAL:CPIAUCSL"
    assert observation.status is EvidenceStatus.COMPLETE
    assert observation.value["value"] == pytest.approx(308.742)


def test_fred_missing_dot_value_is_visible_data_error_not_zero():
    payload = {
        "observations": [
            {
                "realtime_start": "2024-01-15",
                "realtime_end": "2024-02-14",
                "date": "2023-12-01",
                "value": ".",
            }
        ]
    }
    vintage = FredAlfredAdapter.parse_observations(payload, series_id="TEST")[0]
    observation = vintage.to_provider_observation(
        as_of=datetime(2024, 1, 15, 23, 59, tzinfo=UTC)
    )
    assert observation.value["value"] is None
    assert observation.status is EvidenceStatus.DATA_ERROR
    assert observation.reason_code == "FRED_MISSING_VALUE"


def test_future_fred_vintage_is_rejected():
    payload = {
        "observations": [
            {
                "realtime_start": "2024-01-16",
                "realtime_end": "2024-02-14",
                "date": "2023-12-01",
                "value": "1.0",
            }
        ]
    }
    vintage = FredAlfredAdapter.parse_observations(payload, series_id="TEST")[0]
    with pytest.raises(PublicPrimaryAdapterError, match="FUTURE_FRED_VINTAGE_NOT_ALLOWED"):
        vintage.to_provider_observation(as_of=datetime(2024, 1, 15, 23, 59, tzinfo=UTC))
