import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from daily_alpha.behavioral_artifacts import write_behavioral_daily_artifacts
from daily_alpha.behavioral_change import (
    BehavioralObservation,
    BehavioralSnapshot,
    BehavioralSource,
    SourceSignal,
    SourceStatus,
)

NOW = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)


def _observation(query, level, *, observed_at=NOW):
    return BehavioralObservation(
        source=BehavioralSource.YOUTUBE,
        entity_id="NVDA",
        ticker="NVDA",
        query_key=query,
        metric="NEW_VIDEO_COUNT_24H",
        observed_at=observed_at,
        source_timestamp=observed_at,
        raw_level=level,
        provenance="youtube-test",
    )


def _snapshot(score=72.5):
    signal = SourceSignal(
        source=BehavioralSource.YOUTUBE,
        as_of=NOW,
        status=SourceStatus.COMPLETE,
        reason="",
        observations_used=2,
        level_7d=10.0,
        level_28d=30.0,
        velocity_7d=0.25,
        prior_velocity_7d=0.10,
        acceleration=0.15,
        abnormality_z=1.5,
        persistence=0.7,
        prototype_score=70.0,
    )
    return BehavioralSnapshot(
        entity_id="NVDA",
        ticker="NVDA",
        as_of=NOW,
        source_signals=(signal,),
        cross_source_confirmation=0.0,
        behavioral_change_score=score,
        information_imbalance_score=None,
        information_imbalance_reason="WALL_STREET_RECOGNITION_NOT_CONNECTED",
    )


def test_daily_artifacts_are_order_independent_idempotent_and_hashed(tmp_path):
    first = _observation("NVIDIA", 2.0)
    second = _observation("Blackwell", 1.0)

    bundle = write_behavioral_daily_artifacts(
        tmp_path,
        observations=(first, second),
        snapshot=_snapshot(),
    )
    repeated = write_behavioral_daily_artifacts(
        tmp_path,
        observations=(second, first),
        snapshot=_snapshot(),
    )

    assert bundle.observations_sha256 == repeated.observations_sha256
    assert bundle.snapshot_sha256 == repeated.snapshot_sha256
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert manifest["observation_count"] == 2
    assert manifest["observations_sha256"] == bundle.observations_sha256
    assert manifest["snapshot_sha256"] == bundle.snapshot_sha256
    assert manifest["research_only"] is True
    assert manifest["trading_authorized"] is False
    assert manifest["live_trading_enabled"] is False


def test_artifact_write_rejects_lookahead(tmp_path):
    future = _observation("NVIDIA", 2.0, observed_at=NOW + timedelta(minutes=1))
    with pytest.raises(ValueError, match="BEHAVIORAL_ARTIFACT_LOOKAHEAD_REJECTED"):
        write_behavioral_daily_artifacts(
            tmp_path,
            observations=(future,),
            snapshot=_snapshot(),
        )


def test_artifact_path_is_immutable_after_first_write(tmp_path):
    row = _observation("NVIDIA", 2.0)
    snapshot = _snapshot()
    write_behavioral_daily_artifacts(tmp_path, observations=(row,), snapshot=snapshot)

    changed = replace(snapshot, behavioral_change_score=99.0)
    with pytest.raises(
        ValueError,
        match="BEHAVIORAL_ARTIFACT_IMMUTABILITY_VIOLATION:behavioral_snapshot.json",
    ):
        write_behavioral_daily_artifacts(
            tmp_path,
            observations=(row,),
            snapshot=changed,
        )
