from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from daily_alpha.model_training import (
    ModelTrainingError,
    TrainingDatasetSnapshot,
    TrainingExample,
)


@dataclass(frozen=True, slots=True)
class PointInTimeFeatureObservation:
    security_id: str
    decision_at: datetime
    feature_name: str
    feature_value: float
    known_at: datetime
    evidence_id: str
    source_revision: str

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        feature_name = self.feature_name.strip()
        evidence_id = self.evidence_id.strip()
        source_revision = self.source_revision.strip()
        if not security_id:
            raise ModelTrainingError("FEATURE_SECURITY_ID_REQUIRED")
        if not feature_name:
            raise ModelTrainingError("FEATURE_NAME_REQUIRED")
        _require_aware(self.decision_at, "FEATURE_DECISION_AT")
        _require_aware(self.known_at, "FEATURE_KNOWN_AT")
        if self.known_at > self.decision_at:
            raise ModelTrainingError("FEATURE_KNOWN_AFTER_DECISION")
        feature_value = float(self.feature_value)
        if not isfinite(feature_value):
            raise ModelTrainingError("FEATURE_VALUE_MUST_BE_FINITE")
        if not evidence_id:
            raise ModelTrainingError("FEATURE_EVIDENCE_ID_REQUIRED")
        if not source_revision:
            raise ModelTrainingError("FEATURE_SOURCE_REVISION_REQUIRED")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "feature_name", feature_name)
        object.__setattr__(self, "feature_value", feature_value)
        object.__setattr__(self, "evidence_id", evidence_id)
        object.__setattr__(self, "source_revision", source_revision)

    @property
    def observation_id(self) -> str:
        return _sha(
            {
                "security_id": self.security_id,
                "decision_at": self.decision_at.isoformat(),
                "feature_name": self.feature_name,
                "feature_value": self.feature_value,
                "known_at": self.known_at.isoformat(),
                "evidence_id": self.evidence_id,
                "source_revision": self.source_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class RealizedRLabelObservation:
    security_id: str
    decision_at: datetime
    horizon_days: int
    realized_r: float
    known_at: datetime
    evidence_ids: tuple[str, ...]
    source_revision: str

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        source_revision = self.source_revision.strip()
        if not security_id:
            raise ModelTrainingError("LABEL_SECURITY_ID_REQUIRED")
        _require_aware(self.decision_at, "LABEL_DECISION_AT")
        _require_aware(self.known_at, "LABEL_KNOWN_AT")
        if self.known_at <= self.decision_at:
            raise ModelTrainingError("LABEL_MUST_MATURE_AFTER_DECISION")
        if self.horizon_days < 1:
            raise ModelTrainingError("LABEL_HORIZON_DAYS_MUST_BE_POSITIVE")
        realized_r = float(self.realized_r)
        if not isfinite(realized_r):
            raise ModelTrainingError("REALIZED_R_MUST_BE_FINITE")
        evidence_ids = tuple(sorted({item.strip() for item in self.evidence_ids if item.strip()}))
        if not evidence_ids:
            raise ModelTrainingError("LABEL_EVIDENCE_IDS_REQUIRED")
        if not source_revision:
            raise ModelTrainingError("LABEL_SOURCE_REVISION_REQUIRED")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "realized_r", realized_r)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "source_revision", source_revision)

    @property
    def label_id(self) -> str:
        return _sha(
            {
                "security_id": self.security_id,
                "decision_at": self.decision_at.isoformat(),
                "horizon_days": self.horizon_days,
                "realized_r": self.realized_r,
                "known_at": self.known_at.isoformat(),
                "evidence_ids": self.evidence_ids,
                "source_revision": self.source_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class TrainingDatasetAssemblyPolicy:
    feature_schema_version: str
    label_definition: str
    required_feature_names: tuple[str, ...]
    label_horizon_days: int

    def __post_init__(self) -> None:
        feature_schema_version = self.feature_schema_version.strip()
        label_definition = self.label_definition.strip()
        if not feature_schema_version:
            raise ModelTrainingError("FEATURE_SCHEMA_VERSION_REQUIRED")
        if not label_definition:
            raise ModelTrainingError("LABEL_DEFINITION_REQUIRED")
        feature_names = tuple(sorted({item.strip() for item in self.required_feature_names if item.strip()}))
        if not feature_names:
            raise ModelTrainingError("REQUIRED_FEATURE_NAMES_REQUIRED")
        if len(feature_names) != len(self.required_feature_names):
            raise ModelTrainingError("REQUIRED_FEATURE_NAMES_MUST_BE_UNIQUE_AND_NONEMPTY")
        if self.label_horizon_days < 1:
            raise ModelTrainingError("LABEL_HORIZON_DAYS_MUST_BE_POSITIVE")
        object.__setattr__(self, "feature_schema_version", feature_schema_version)
        object.__setattr__(self, "label_definition", label_definition)
        object.__setattr__(self, "required_feature_names", feature_names)

    @property
    def policy_id(self) -> str:
        return _sha(
            {
                "feature_schema_version": self.feature_schema_version,
                "label_definition": self.label_definition,
                "required_feature_names": self.required_feature_names,
                "label_horizon_days": self.label_horizon_days,
            }
        )


@dataclass(frozen=True, slots=True)
class TrainingDatasetAssemblyResult:
    dataset: TrainingDatasetSnapshot
    policy_id: str
    included_feature_observation_ids: tuple[str, ...]
    included_label_ids: tuple[str, ...]
    excluded_immature_label_ids: tuple[str, ...]
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if any(
            (
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("DATASET_ASSEMBLY_CANNOT_AUTHORIZE_TRADING")
        if not self.policy_id.strip():
            raise ModelTrainingError("DATASET_ASSEMBLY_POLICY_ID_REQUIRED")
        if not self.included_feature_observation_ids:
            raise ModelTrainingError("DATASET_ASSEMBLY_FEATURE_LINEAGE_REQUIRED")
        if not self.included_label_ids:
            raise ModelTrainingError("DATASET_ASSEMBLY_LABEL_LINEAGE_REQUIRED")

    @property
    def assembly_id(self) -> str:
        return _sha(
            {
                "dataset_id": self.dataset.dataset_id,
                "policy_id": self.policy_id,
                "included_feature_observation_ids": self.included_feature_observation_ids,
                "included_label_ids": self.included_label_ids,
                "excluded_immature_label_ids": self.excluded_immature_label_ids,
            }
        )


def build_point_in_time_training_dataset(
    *,
    as_of: datetime,
    policy: TrainingDatasetAssemblyPolicy,
    feature_observations: Iterable[PointInTimeFeatureObservation],
    label_observations: Iterable[RealizedRLabelObservation],
) -> TrainingDatasetAssemblyResult:
    _require_aware(as_of, "DATASET_AS_OF")

    feature_by_key: dict[tuple[str, datetime], dict[str, PointInTimeFeatureObservation]] = {}
    feature_ids_seen: set[str] = set()
    for observation in feature_observations:
        if observation.decision_at > as_of:
            raise ModelTrainingError("FUTURE_FEATURE_DECISION_AT_DATASET_AS_OF")
        if observation.observation_id in feature_ids_seen:
            continue
        feature_ids_seen.add(observation.observation_id)
        key = (observation.security_id, observation.decision_at)
        by_name = feature_by_key.setdefault(key, {})
        existing = by_name.get(observation.feature_name)
        if existing is not None and existing.observation_id != observation.observation_id:
            raise ModelTrainingError("CONFLICTING_FEATURE_OBSERVATION")
        by_name[observation.feature_name] = observation

    if not feature_by_key:
        raise ModelTrainingError("FEATURE_OBSERVATIONS_REQUIRED")

    label_by_key: dict[tuple[str, datetime], RealizedRLabelObservation] = {}
    label_ids_seen: set[str] = set()
    for observation in label_observations:
        if observation.decision_at > as_of:
            raise ModelTrainingError("FUTURE_LABEL_DECISION_AT_DATASET_AS_OF")
        if observation.horizon_days != policy.label_horizon_days:
            raise ModelTrainingError("LABEL_HORIZON_MISMATCH")
        if observation.label_id in label_ids_seen:
            continue
        label_ids_seen.add(observation.label_id)
        key = (observation.security_id, observation.decision_at)
        existing = label_by_key.get(key)
        if existing is not None and existing.label_id != observation.label_id:
            raise ModelTrainingError("CONFLICTING_LABEL_OBSERVATION")
        label_by_key[key] = observation

    if not label_by_key:
        raise ModelTrainingError("LABEL_OBSERVATIONS_REQUIRED")

    orphan_labels = set(label_by_key) - set(feature_by_key)
    if orphan_labels:
        raise ModelTrainingError("LABEL_WITHOUT_FEATURE_ROW")

    required_features = set(policy.required_feature_names)
    examples: list[TrainingExample] = []
    included_feature_ids: list[str] = []
    included_label_ids: list[str] = []
    excluded_immature_label_ids: list[str] = []
    included_source_revisions: set[str] = {f"assembly-policy:{policy.policy_id}"}

    for key in sorted(feature_by_key, key=lambda item: (item[1], item[0])):
        observations = feature_by_key[key]
        if set(observations) != required_features:
            raise ModelTrainingError("FEATURE_SCHEMA_MISMATCH")
        label = label_by_key.get(key)
        if label is None:
            raise ModelTrainingError("FEATURE_ROW_MISSING_LABEL")
        if label.known_at > as_of:
            excluded_immature_label_ids.append(label.label_id)
            continue

        ordered_observations = tuple(observations[name] for name in policy.required_feature_names)
        feature_known_at = max(item.known_at for item in ordered_observations)
        evidence_ids = tuple(
            sorted(
                {
                    *(item.evidence_id for item in ordered_observations),
                    *label.evidence_ids,
                }
            )
        )
        examples.append(
            TrainingExample(
                security_id=key[0],
                decision_at=key[1],
                feature_known_at=feature_known_at,
                label_known_at=label.known_at,
                label_horizon_days=policy.label_horizon_days,
                features=tuple(
                    (item.feature_name, item.feature_value) for item in ordered_observations
                ),
                realized_r=label.realized_r,
                evidence_ids=evidence_ids,
            )
        )
        included_feature_ids.extend(item.observation_id for item in ordered_observations)
        included_label_ids.append(label.label_id)
        included_source_revisions.update(item.source_revision for item in ordered_observations)
        included_source_revisions.add(label.source_revision)

    if not examples:
        raise ModelTrainingError("NO_MATURE_TRAINING_EXAMPLES_AT_DATASET_AS_OF")

    dataset = TrainingDatasetSnapshot(
        as_of=as_of,
        feature_schema_version=policy.feature_schema_version,
        label_definition=policy.label_definition,
        examples=tuple(examples),
        source_revisions=tuple(sorted(included_source_revisions)),
    )
    return TrainingDatasetAssemblyResult(
        dataset=dataset,
        policy_id=policy.policy_id,
        included_feature_observation_ids=tuple(sorted(included_feature_ids)),
        included_label_ids=tuple(sorted(included_label_ids)),
        excluded_immature_label_ids=tuple(sorted(excluded_immature_label_ids)),
    )


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelTrainingError(f"{field}_MUST_BE_TIMEZONE_AWARE")


def _sha(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PointInTimeFeatureObservation",
    "RealizedRLabelObservation",
    "TrainingDatasetAssemblyPolicy",
    "TrainingDatasetAssemblyResult",
    "build_point_in_time_training_dataset",
]
