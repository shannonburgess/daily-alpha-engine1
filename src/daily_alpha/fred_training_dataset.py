"""Bind a FRED PIT macro corpus into the immutable training-dataset boundary.

This module is intentionally narrow. It does not download provider data, create labels,
fit models, select candidates, mutate PAPER state, authorize trading, or enable live
execution. It packages an already-validated ``FredMacroFeatureCorpus`` with independently
valid realized labels through the existing point-in-time dataset assembler while retaining
exact corpus lineage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .fred_feature_corpus import FredMacroFeatureCorpus
from .model_dataset_builder import (
    RealizedRLabelObservation,
    TrainingDatasetAssemblyPolicy,
    TrainingDatasetAssemblyResult,
    build_point_in_time_training_dataset,
)
from .model_training import ModelTrainingError

_PACKET_CONTRACT = "FRED_MACRO_TRAINING_DATASET_PACKET_V1"


@dataclass(frozen=True, slots=True)
class FredMacroTrainingDatasetPacket:
    """Immutable research-only dataset assembly bound to one FRED macro corpus."""

    corpus_id: str
    assembly: TrainingDatasetAssemblyResult
    feature_spec_ids: tuple[str, ...]
    batch_ids: tuple[str, ...]
    corpus_source_revisions: tuple[str, ...]
    contract: str = _PACKET_CONTRACT
    research_only: bool = True
    labels_created: bool = False
    retuning_authorized: bool = False
    promotion_authorized: bool = False
    paper_mutation_authorized: bool = False
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        if self.contract != _PACKET_CONTRACT:
            raise ModelTrainingError("FRED_TRAINING_PACKET_CONTRACT_INVALID")
        if not self.corpus_id.strip():
            raise ModelTrainingError("FRED_TRAINING_CORPUS_ID_REQUIRED")
        if not isinstance(self.assembly, TrainingDatasetAssemblyResult):
            raise ModelTrainingError("FRED_TRAINING_ASSEMBLY_TYPE_INVALID")
        _require_canonical_nonempty_ids(
            self.feature_spec_ids,
            field="FRED_TRAINING_FEATURE_SPEC_IDS",
        )
        _require_canonical_nonempty_ids(
            self.batch_ids,
            field="FRED_TRAINING_BATCH_IDS",
        )
        _require_canonical_nonempty_ids(
            self.corpus_source_revisions,
            field="FRED_TRAINING_CORPUS_SOURCE_REVISIONS",
        )
        if self.labels_created:
            raise ModelTrainingError("FRED_TRAINING_PACKET_CANNOT_CREATE_LABELS")
        if not self.research_only:
            raise ModelTrainingError("FRED_TRAINING_PACKET_MUST_REMAIN_RESEARCH_ONLY")
        if any(
            (
                self.retuning_authorized,
                self.promotion_authorized,
                self.paper_mutation_authorized,
                self.trading_authorized,
                self.live_trading_enabled,
            )
        ):
            raise ModelTrainingError("FRED_TRAINING_PACKET_CANNOT_AUTHORIZE_ACTION")

    @property
    def dataset_id(self) -> str:
        return self.assembly.dataset.dataset_id

    @property
    def packet_id(self) -> str:
        return _sha(
            {
                "contract": self.contract,
                "corpus_id": self.corpus_id,
                "assembly_id": self.assembly.assembly_id,
                "feature_spec_ids": self.feature_spec_ids,
                "batch_ids": self.batch_ids,
                "corpus_source_revisions": self.corpus_source_revisions,
            }
        )


def build_fred_macro_training_dataset(
    *,
    corpus: FredMacroFeatureCorpus,
    policy: TrainingDatasetAssemblyPolicy,
    label_observations: Iterable[RealizedRLabelObservation],
    as_of,
) -> FredMacroTrainingDatasetPacket:
    """Assemble a training snapshot while preserving the exact FRED corpus identity."""
    if not isinstance(corpus, FredMacroFeatureCorpus):
        raise ModelTrainingError("FRED_TRAINING_CORPUS_TYPE_INVALID")
    if not isinstance(policy, TrainingDatasetAssemblyPolicy):
        raise ModelTrainingError("FRED_TRAINING_POLICY_TYPE_INVALID")
    if not corpus.research_only or corpus.labels_created:
        raise ModelTrainingError("FRED_TRAINING_CORPUS_AUTHORITY_INVALID")
    if any(
        (
            corpus.retuning_authorized,
            corpus.promotion_authorized,
            corpus.paper_mutation_authorized,
            corpus.trading_authorized,
            corpus.live_trading_enabled,
        )
    ):
        raise ModelTrainingError("FRED_TRAINING_CORPUS_AUTHORITY_INVALID")

    corpus_feature_names = tuple(sorted(item.feature_name for item in corpus.feature_specs))
    if policy.required_feature_names != corpus_feature_names:
        raise ModelTrainingError("FRED_TRAINING_FEATURE_SCHEMA_MISMATCH")

    normalized_labels = tuple(label_observations)
    if not normalized_labels:
        raise ModelTrainingError("FRED_TRAINING_LABELS_REQUIRED")
    if any(not isinstance(item, RealizedRLabelObservation) for item in normalized_labels):
        raise ModelTrainingError("FRED_TRAINING_LABEL_TYPE_INVALID")

    assembly = build_point_in_time_training_dataset(
        as_of=as_of,
        policy=policy,
        feature_observations=corpus.observations,
        label_observations=normalized_labels,
    )

    corpus_observation_ids = {item.observation_id for item in corpus.observations}
    if not set(assembly.included_feature_observation_ids).issubset(corpus_observation_ids):
        raise ModelTrainingError("FRED_TRAINING_FEATURE_LINEAGE_ESCAPED_CORPUS")

    return FredMacroTrainingDatasetPacket(
        corpus_id=corpus.corpus_id,
        assembly=assembly,
        feature_spec_ids=tuple(sorted(item.spec_id for item in corpus.feature_specs)),
        batch_ids=corpus.batch_ids,
        corpus_source_revisions=corpus.source_revisions,
    )


def _require_canonical_nonempty_ids(values: tuple[str, ...], *, field: str) -> None:
    if not values:
        raise ModelTrainingError(f"{field}_REQUIRED")
    normalized = tuple(item.strip() for item in values)
    if any(not item for item in normalized):
        raise ModelTrainingError(f"{field}_NONEMPTY_REQUIRED")
    if tuple(sorted(normalized)) != values:
        raise ModelTrainingError(f"{field}_ORDER_INVALID")
    if len(set(normalized)) != len(normalized):
        raise ModelTrainingError(f"{field}_DUPLICATE")


def _sha(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FredMacroTrainingDatasetPacket",
    "build_fred_macro_training_dataset",
]
