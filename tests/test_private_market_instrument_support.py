import pytest

from daily_alpha.opportunity_contracts import (
    InstrumentType,
    OpportunityContractError,
    PrivateMarketTerms,
)


@pytest.mark.parametrize(
    "instrument",
    [
        InstrumentType.PRIVATE_COMPANY_EQUITY,
        InstrumentType.SAFE,
        InstrumentType.CONVERTIBLE_NOTE,
        InstrumentType.CREDIT,
        InstrumentType.FUND_INTEREST,
    ],
)
def test_private_market_terms_explicitly_support_required_private_instruments(
    instrument: InstrumentType,
) -> None:
    terms = PrivateMarketTerms(
        stage="private",
        financing_instrument=instrument,
        source_evidence_ids=(f"ev-{instrument.value.lower()}",),
        expected_liquidity_horizon_months=60,
    )

    assert terms.financing_instrument is instrument
    assert terms.stage == "PRIVATE"


def test_public_option_is_not_accepted_as_private_financing_terms() -> None:
    with pytest.raises(
        OpportunityContractError,
        match="PRIVATE_FINANCING_INSTRUMENT_INVALID",
    ):
        PrivateMarketTerms(
            stage="private",
            financing_instrument=InstrumentType.OPTION,
            source_evidence_ids=("ev-option",),
        )
