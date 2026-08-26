"""Source ownership and freshness policies for Agentic Intelligence V1."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import EvidenceContractError, EvidenceStatus


@dataclass(frozen=True)
class SourcePolicy:
    source: str
    owner: str
    evidence_types: tuple[str, ...]
    cadence_seconds: int
    max_freshness_seconds: int
    required: bool = True
    requires_cross_source_agreement: bool = False
    fail_closed_statuses: tuple[EvidenceStatus, ...] = (
        EvidenceStatus.STALE,
        EvidenceStatus.SOURCE_UNAVAILABLE,
        EvidenceStatus.CONFLICT,
        EvidenceStatus.DATA_ERROR,
    )

    def __post_init__(self) -> None:
        source = self.source.strip().upper()
        owner = self.owner.strip()
        evidence_types = tuple(sorted({item.strip().upper() for item in self.evidence_types if item}))
        if not source:
            raise EvidenceContractError("SOURCE_POLICY_SOURCE_REQUIRED")
        if not owner:
            raise EvidenceContractError("SOURCE_POLICY_OWNER_REQUIRED")
        if not evidence_types:
            raise EvidenceContractError("SOURCE_POLICY_EVIDENCE_TYPES_REQUIRED")
        if self.cadence_seconds <= 0:
            raise EvidenceContractError("SOURCE_POLICY_CADENCE_MUST_BE_POSITIVE")
        if self.max_freshness_seconds <= 0:
            raise EvidenceContractError("SOURCE_POLICY_FRESHNESS_MUST_BE_POSITIVE")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "evidence_types", evidence_types)


class SourceRegistry:
    """Deterministic registry. A source cannot be silently redefined in place."""

    def __init__(self, policies: tuple[SourcePolicy, ...] = ()) -> None:
        self._policies: dict[str, SourcePolicy] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: SourcePolicy) -> None:
        existing = self._policies.get(policy.source)
        if existing is None:
            self._policies[policy.source] = policy
            return
        if existing != policy:
            raise EvidenceContractError(f"SOURCE_POLICY_CONFLICT:{policy.source}")

    def get(self, source: str) -> SourcePolicy:
        key = source.strip().upper()
        try:
            return self._policies[key]
        except KeyError as exc:
            raise EvidenceContractError(f"SOURCE_POLICY_NOT_REGISTERED:{key}") from exc

    def policies(self) -> tuple[SourcePolicy, ...]:
        return tuple(self._policies[key] for key in sorted(self._policies))

    def policies_for(self, evidence_type: str) -> tuple[SourcePolicy, ...]:
        kind = evidence_type.strip().upper()
        return tuple(policy for policy in self.policies() if kind in policy.evidence_types)


def daily_alpha_v1_registry() -> SourceRegistry:
    """Initial registry for existing Daily Alpha authoritative evidence surfaces.

    These policies do not connect to execution. They define the intended ownership and
    freshness contract for the first adapter slice.
    """
    return SourceRegistry(
        (
            SourcePolicy(
                source="OVTLYR_CANONICAL",
                owner="Daily Alpha OVTLYR ingestion",
                evidence_types=("OVTLYR_STATE",),
                cadence_seconds=86_400,
                max_freshness_seconds=129_600,
                required=True,
            ),
            SourcePolicy(
                source="SERVER_ACTIONABLE_SHORTLIST",
                owner="Daily Alpha server-authoritative sector context",
                evidence_types=("SECTOR",),
                cadence_seconds=43_200,
                max_freshness_seconds=64_800,
                required=True,
            ),
            SourcePolicy(
                source="COMPANY_LIQUIDITY_CANONICAL",
                owner="Daily Alpha company liquidity gate",
                evidence_types=("LIQUIDITY",),
                cadence_seconds=43_200,
                max_freshness_seconds=64_800,
                required=True,
            ),
            SourcePolicy(
                source="TRADINGVIEW_PINE_SENSOR",
                owner="Daily Alpha Pine ingress",
                evidence_types=("PINE_SIGNAL",),
                cadence_seconds=86_400,
                max_freshness_seconds=86_400,
                required=False,
            ),
        )
    )
