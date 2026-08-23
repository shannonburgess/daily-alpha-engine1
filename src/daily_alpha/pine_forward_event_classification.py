from __future__ import annotations

from dataclasses import dataclass

from .pine_forward_deployment_evidence import (
    ForwardParityBookEvidence,
    ForwardPersistedEventEvidence,
)

# Immutable signal IDs explicitly tagged as staging/E2E validation traffic in retained #213
# runtime evidence. They remain in the audit trail but cannot count as genuine forward Pine
# strategy evidence. The registry is exact by design: future events are never excluded by a
# fuzzy name/prefix heuristic.
EXPLICIT_STAGING_E2E_SIGNAL_IDS = frozenset(
    {
        "TV-SHADOW-E2E-20260819-01",
        "API-GATEWAY-SHADOW-E2E-20260819T175443Z",
        "STAGING-SHADOW-E2E-V25-20260819T173111Z",
    }
)


@dataclass(frozen=True, slots=True)
class ForwardEventPartition:
    reference_candidates: tuple[ForwardPersistedEventEvidence, ...]
    explicit_staging_tests: tuple[ForwardPersistedEventEvidence, ...]

    @property
    def reference_candidate_count(self) -> int:
        return len(self.reference_candidates)

    @property
    def explicit_staging_test_count(self) -> int:
        return len(self.explicit_staging_tests)


def partition_forward_events(book: ForwardParityBookEvidence) -> ForwardEventPartition:
    """Separate exact retained E2E traffic without rewriting or deleting audit history."""
    tests: list[ForwardPersistedEventEvidence] = []
    candidates: list[ForwardPersistedEventEvidence] = []
    for event in book.events:
        if event.signal_id in EXPLICIT_STAGING_E2E_SIGNAL_IDS:
            tests.append(event)
        else:
            candidates.append(event)
    return ForwardEventPartition(
        reference_candidates=tuple(candidates),
        explicit_staging_tests=tuple(tests),
    )


__all__ = [
    "EXPLICIT_STAGING_E2E_SIGNAL_IDS",
    "ForwardEventPartition",
    "partition_forward_events",
]
