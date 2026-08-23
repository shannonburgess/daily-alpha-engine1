from datetime import UTC, datetime

import pytest

from daily_alpha.pine_forward_replay_provenance import ForwardReplayProvenance

START = datetime(2026, 8, 1, 20, tzinfo=UTC)
END = datetime(2026, 8, 21, 20, tzinfo=UTC)


def _provenance(**overrides) -> ForwardReplayProvenance:
    values = {
        "model_id": "PAPER_SHADOW_V24",
        "strategy_version": "2.4",
        "strategy_source_blob_sha": "33091e312ad3069ff7d82825b370f2a73d93107c",
        "parameter_manifest_sha256": "1" * 64,
        "market_evidence_sha256": "2" * 64,
        "market_source_revision": "market-snapshot-2026-08-21",
        "python_engine_revision": "pine_v24_parity.py@a25166c",
        "replay_start": START,
        "replay_end": END,
        "replay_bar_count": 15,
        "deployment_commit_sha": "b" * 40,
        "processor_code_sha256": "processor-code-hash",
    }
    values.update(overrides)
    return ForwardReplayProvenance(**values)


def test_forward_replay_identity_is_deterministic_and_input_sensitive() -> None:
    first = _provenance()
    second = _provenance()
    changed_market = _provenance(market_evidence_sha256="3" * 64)

    assert first.evidence_id == second.evidence_id
    assert first.evidence_id != changed_market.evidence_id
    assert len(first.evidence_id) == 64


def test_forward_replay_requires_exact_hashes_and_time_bounds() -> None:
    with pytest.raises(ValueError, match="parameter_manifest_sha256"):
        _provenance(parameter_manifest_sha256="not-a-hash")
    with pytest.raises(ValueError, match="strategy_source_blob_sha"):
        _provenance(strategy_source_blob_sha="not-a-git-blob")
    with pytest.raises(ValueError, match="replay_end cannot be before replay_start"):
        _provenance(replay_start=END, replay_end=START)


def test_forward_replay_provenance_cannot_authorize_trading() -> None:
    with pytest.raises(ValueError, match="cannot authorize trading"):
        _provenance(trading_authorized=True)
