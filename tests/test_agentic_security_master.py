from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.agentic.security_master import (
    AssetType,
    IdentifierNamespace,
    InMemorySecurityMaster,
    ListingStatus,
    SecurityIdentifier,
    SecurityMasterError,
    SecurityMasterRecord,
    TickerAlias,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 6, 1, tzinfo=UTC)
T2 = datetime(2026, 8, 21, tzinfo=UTC)


def _record(
    *,
    security_id: str = "DAI-SEC-0001",
    issuer_id: str = "DAI-ISSUER-0001",
    issuer_name: str = "Example Energy Corp",
    ticker: str = "OLD",
    exchange: str = "XNYS",
    start: datetime = T0,
    end: datetime | None = T1,
    identifier: str = "BBG000TEST01",
    alias_start: datetime | None = None,
    alias_end: datetime | None = None,
    status: ListingStatus = ListingStatus.ACTIVE,
) -> SecurityMasterRecord:
    return SecurityMasterRecord(
        security_id=security_id,
        issuer_id=issuer_id,
        issuer_name=issuer_name,
        asset_type=AssetType.COMPANY_EQUITY,
        primary_ticker=ticker,
        exchange_mic=exchange,
        currency="USD",
        country="US",
        sector="Energy",
        industry="Oil & Gas",
        listing_status=status,
        optionable=True,
        effective_from=start,
        effective_to=end,
        source_version="SECMASTER_V1",
        identifiers=(SecurityIdentifier(IdentifierNamespace.FIGI, identifier),),
        aliases=(
            TickerAlias(
                symbol=ticker,
                exchange_mic=exchange,
                effective_from=alias_start or start,
                effective_to=alias_end if alias_end is not None else end,
            ),
        ),
        provenance={"source": "test"},
    )


def test_ticker_change_preserves_permanent_security_identity():
    master = InMemorySecurityMaster()
    old = _record()
    new = _record(
        ticker="NEW",
        start=T1,
        end=None,
        alias_start=T1,
        alias_end=None,
    )
    master.add(old)
    master.add(new)

    assert master.resolve_symbol("OLD", as_of=T0 + timedelta(days=30)).security_id == old.security_id
    assert master.resolve_symbol("NEW", as_of=T2).security_id == old.security_id
    with pytest.raises(SecurityMasterError, match="SYMBOL_NOT_RESOLVED:OLD"):
        master.resolve_symbol("OLD", as_of=T2)


def test_security_versions_may_not_overlap():
    master = InMemorySecurityMaster()
    master.add(_record(end=T2))
    overlapping = _record(
        ticker="NEW",
        start=T1,
        end=None,
        alias_start=T1,
        alias_end=None,
    )
    with pytest.raises(SecurityMasterError, match="SECURITY_MASTER_VERSION_OVERLAP"):
        master.add(overlapping)


def test_durable_identifier_cannot_be_reassigned_to_another_security():
    master = InMemorySecurityMaster()
    master.add(_record())
    other = _record(
        security_id="DAI-SEC-0002",
        issuer_id="DAI-ISSUER-0002",
        issuer_name="Other Corp",
        ticker="OTH",
        identifier="BBG000TEST01",
    )
    with pytest.raises(SecurityMasterError, match="DURABLE_IDENTIFIER_REASSIGNMENT_BLOCKED"):
        master.add(other)


def test_symbol_resolution_fails_closed_when_symbol_is_ambiguous():
    master = InMemorySecurityMaster()
    first = _record(
        ticker="ABC",
        exchange="XNYS",
        end=None,
        alias_end=None,
    )
    second = _record(
        security_id="DAI-SEC-0002",
        issuer_id="DAI-ISSUER-0002",
        issuer_name="Second ABC Corp",
        ticker="ABC",
        exchange="XNAS",
        end=None,
        alias_end=None,
        identifier="BBG000TEST02",
    )
    master.add(first)
    master.add(second)

    with pytest.raises(SecurityMasterError, match="SYMBOL_AMBIGUOUS:ABC"):
        master.resolve_symbol("ABC", as_of=T2)
    assert master.resolve_symbol("ABC", exchange_mic="XNYS", as_of=T2) == first
    assert master.resolve_symbol("ABC", exchange_mic="XNAS", as_of=T2) == second


def test_identifier_resolution_is_point_in_time():
    master = InMemorySecurityMaster()
    record = _record()
    master.add(record)
    identifier = record.identifiers[0]

    assert master.resolve_identifier(identifier, as_of=T0 + timedelta(days=1)) == record
    with pytest.raises(SecurityMasterError, match="SECURITY_ID_NOT_ACTIVE"):
        master.resolve_identifier(identifier, as_of=T2)


def test_snapshot_identity_is_deterministic_regardless_of_insert_order():
    first = _record(end=None, alias_end=None)
    second = _record(
        security_id="DAI-SEC-0002",
        issuer_id="DAI-ISSUER-0002",
        issuer_name="Second Corp",
        ticker="TWO",
        end=None,
        alias_end=None,
        identifier="BBG000TEST02",
    )
    left = InMemorySecurityMaster()
    right = InMemorySecurityMaster()
    left.add(first)
    left.add(second)
    right.add(second)
    right.add(first)

    assert left.snapshot(T2).snapshot_id == right.snapshot(T2).snapshot_id
    assert left.snapshot(T2).record_ids == right.snapshot(T2).record_ids


def test_primary_ticker_requires_active_alias_at_version_start():
    with pytest.raises(SecurityMasterError, match="PRIMARY_TICKER_MUST_HAVE_ACTIVE_ALIAS"):
        SecurityMasterRecord(
            security_id="DAI-SEC-0001",
            issuer_id="DAI-ISSUER-0001",
            issuer_name="Example Corp",
            asset_type=AssetType.COMPANY_EQUITY,
            primary_ticker="ABC",
            exchange_mic="XNYS",
            currency="USD",
            country="US",
            sector="Energy",
            industry="Oil & Gas",
            listing_status=ListingStatus.ACTIVE,
            optionable=True,
            effective_from=T0,
            effective_to=None,
            source_version="SECMASTER_V1",
            identifiers=(SecurityIdentifier(IdentifierNamespace.FIGI, "BBG000TEST01"),),
            aliases=(
                TickerAlias(
                    symbol="XYZ",
                    exchange_mic="XNYS",
                    effective_from=T0,
                    effective_to=None,
                ),
            ),
        )


def test_security_master_cannot_enable_trading_or_live_execution():
    with pytest.raises(SecurityMasterError, match="SECURITY_MASTER_MUST_REMAIN_RESEARCH_ONLY"):
        SecurityMasterRecord(
            security_id="DAI-SEC-0001",
            issuer_id="DAI-ISSUER-0001",
            issuer_name="Example Corp",
            asset_type=AssetType.COMPANY_EQUITY,
            primary_ticker="ABC",
            exchange_mic="XNYS",
            currency="USD",
            country="US",
            sector="Energy",
            industry="Oil & Gas",
            listing_status=ListingStatus.ACTIVE,
            optionable=True,
            effective_from=T0,
            effective_to=None,
            source_version="SECMASTER_V1",
            identifiers=(SecurityIdentifier(IdentifierNamespace.FIGI, "BBG000TEST01"),),
            aliases=(
                TickerAlias(
                    symbol="ABC",
                    exchange_mic="XNYS",
                    effective_from=T0,
                    effective_to=None,
                ),
            ),
            trading_authorized=True,
        )


def test_naive_as_of_is_rejected():
    master = InMemorySecurityMaster()
    master.add(_record(end=None, alias_end=None))
    with pytest.raises(SecurityMasterError, match="AS_OF_MUST_BE_TIMEZONE_AWARE"):
        master.snapshot(datetime(2026, 8, 21))  # noqa: DTZ001 - deliberate invalid input
