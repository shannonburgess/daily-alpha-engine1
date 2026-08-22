"""Research Council contracts for the Daily Alpha Quantitative Investment Platform.

Specialized analysts interpret canonical, point-in-time inputs. They do not place orders,
authorize trading, mutate portfolio state, change risk limits, or inspect peer opinions
before submitting their first-pass view. Disagreement is preserved for a later CIO/Fusion
layer rather than collapsed into a majority vote here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .contracts import ReadinessStatus


class ResearchCouncilError(ValueError):
    """Research Council contract or assembly invariant failed."""


class CouncilRole(StrEnum):
    MOMENTUM = "MOMENTUM"
    ROTATION = "ROTATION"
    CATALYST = "CATALYST"
    FUNDAMENTAL = "FUNDAMENTAL"
    MACRO = "MACRO"
    INSTITUTIONAL = "INSTITUTIONAL"
    BEHAVIORAL = "BEHAVIORAL"
    BULL = "BULL"
    BEAR = "BEAR"
    SKEPTIC = "SKEPTIC"
    RISK_ANALYST = "RISK_ANALYST"


class CouncilInputKind(StrEnum):
    FEATURE = "FEATURE"
    EVIDENCE = "EVIDENCE"
    MARKET_STATE = "MARKET_STATE"
    EVENT_STATE = "EVENT_STATE"
    RESEARCH_FACT = "RESEARCH_FACT"
    QUANT_MODEL = "QUANT_MODEL"
    PORTFOLIO_CONTEXT = "PORTFOLIO_CONTEXT"
    REGIME_CONTEXT = "REGIME_CONTEXT"


class OpinionStance(StrEnum):
    STRONGLY_NEGATIVE = "STRONGLY_NEGATIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"
    STRONGLY_POSITIVE = "STRONGLY_POSITIVE"
    NO_VIEW = "NO_VIEW"


class EvidenceEffect(StrEnum):
    SUPPORTS = "SUPPORTS"
    OPPOSES = "OPPOSES"
    UNCERTAINTY = "UNCERTAINTY"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResearchCouncilError(f"{field_name}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResearchCouncilError("RESEARCH_COUNCIL_VALUE_NOT_CANONICAL_JSON") from exc


def _normalized_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({value.strip().upper() for value in values if value.strip()}))


@dataclass(frozen=True, order=True)
class CouncilInputRef:
    """One exact point-in-time input made available to an analyst."""

    input_kind: CouncilInputKind
    input_id: str
    available_at: datetime
    quality_label: str = "UNSPECIFIED"
    status: ReadinessStatus = ReadinessStatus.PASS

    def __post_init__(self) -> None:
        input_id = self.input_id.strip().lower()
        quality = self.quality_label.strip().upper()
        if not input_id:
            raise ResearchCouncilError("COUNCIL_INPUT_ID_REQUIRED")
        if not quality:
            raise ResearchCouncilError("COUNCIL_INPUT_QUALITY_REQUIRED")
        object.__setattr__(self, "input_id", input_id)
        object.__setattr__(self, "available_at", _aware_utc(self.available_at, "INPUT_AVAILABLE_AT"))
        object.__setattr__(self, "quality_label", quality)


@dataclass(frozen=True)
class AgentMandate:
    """Governed mandate for one independent first-pass research analyst."""

    role: CouncilRole
    version: str
    objective: str
    required_input_kinds: tuple[CouncilInputKind, ...]
    optional_input_kinds: tuple[CouncilInputKind, ...] = ()
    peer_opinion_access: bool = False
    may_place_orders: bool = False
    may_authorize_trading: bool = False
    may_mutate_portfolio: bool = False
    may_modify_risk_limits: bool = False

    def __post_init__(self) -> None:
        version = self.version.strip()
        objective = self.objective.strip()
        required = tuple(sorted(set(self.required_input_kinds), key=lambda item: item.value))
        optional = tuple(sorted(set(self.optional_input_kinds), key=lambda item: item.value))
        if not version:
            raise ResearchCouncilError("AGENT_MANDATE_VERSION_REQUIRED")
        if not objective:
            raise ResearchCouncilError("AGENT_MANDATE_OBJECTIVE_REQUIRED")
        if set(required) & set(optional):
            raise ResearchCouncilError("AGENT_MANDATE_INPUT_KIND_OVERLAP")
        if (
            self.peer_opinion_access
            or self.may_place_orders
            or self.may_authorize_trading
            or self.may_mutate_portfolio
            or self.may_modify_risk_limits
        ):
            raise ResearchCouncilError("RESEARCH_ANALYST_MUST_NOT_HAVE_CONTROL_AUTHORITY")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "required_input_kinds", required)
        object.__setattr__(self, "optional_input_kinds", optional)

    @property
    def mandate_id(self) -> str:
        payload = {
            "role": self.role.value,
            "version": self.version,
            "objective": self.objective,
            "required_input_kinds": [item.value for item in self.required_input_kinds],
            "optional_input_kinds": [item.value for item in self.optional_input_kinds],
            "peer_opinion_access": self.peer_opinion_access,
            "may_place_orders": self.may_place_orders,
            "may_authorize_trading": self.may_authorize_trading,
            "may_mutate_portfolio": self.may_mutate_portfolio,
            "may_modify_risk_limits": self.may_modify_risk_limits,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class AgentMandateRegistry:
    """Versioned analyst-mandate registry with no silent same-role replacement."""

    def __init__(self, mandates: tuple[AgentMandate, ...] = ()) -> None:
        self._mandates: dict[CouncilRole, AgentMandate] = {}
        for mandate in mandates:
            self.register(mandate)

    def register(self, mandate: AgentMandate) -> None:
        existing = self._mandates.get(mandate.role)
        if existing is None:
            self._mandates[mandate.role] = mandate
            return
        if existing != mandate:
            raise ResearchCouncilError(f"AGENT_MANDATE_CONFLICT:{mandate.role.value}")

    def get(self, role: CouncilRole) -> AgentMandate:
        try:
            return self._mandates[role]
        except KeyError as exc:
            raise ResearchCouncilError(f"AGENT_MANDATE_NOT_FOUND:{role.value}") from exc

    def mandates(self) -> tuple[AgentMandate, ...]:
        return tuple(
            self._mandates[role]
            for role in sorted(self._mandates, key=lambda item: item.value)
        )

    @property
    def registry_id(self) -> str:
        payload = [
            {"role": mandate.role.value, "mandate_id": mandate.mandate_id}
            for mandate in self.mandates()
        ]
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentInputPacket:
    """Exact governed input surface for one independent analyst invocation."""

    security_id: str
    role: CouncilRole
    as_of: datetime
    mandate_id: str
    inputs: tuple[CouncilInputRef, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        mandate_id = self.mandate_id.strip().lower()
        boundary = _aware_utc(self.as_of, "AGENT_INPUT_AS_OF")
        if not security_id:
            raise ResearchCouncilError("AGENT_INPUT_SECURITY_ID_REQUIRED")
        if not mandate_id:
            raise ResearchCouncilError("AGENT_INPUT_MANDATE_ID_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ResearchCouncilError("AGENT_INPUT_PACKET_MUST_REMAIN_RESEARCH_ONLY")
        input_ids = [item.input_id for item in self.inputs]
        if len(set(input_ids)) != len(input_ids):
            raise ResearchCouncilError("AGENT_INPUT_IDS_MUST_BE_UNIQUE")
        for item in self.inputs:
            if item.available_at > boundary:
                raise ResearchCouncilError(f"FUTURE_AGENT_INPUT_NOT_ALLOWED:{item.input_id}")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "mandate_id", mandate_id)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(
            self,
            "inputs",
            tuple(sorted(self.inputs, key=lambda item: (item.input_kind.value, item.input_id))),
        )

    @property
    def input_ids(self) -> tuple[str, ...]:
        return tuple(item.input_id for item in self.inputs)

    @property
    def input_kinds(self) -> tuple[CouncilInputKind, ...]:
        return tuple(sorted({item.input_kind for item in self.inputs}, key=lambda item: item.value))

    @property
    def packet_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "role": self.role.value,
            "as_of": self.as_of.isoformat(),
            "mandate_id": self.mandate_id,
            "inputs": [
                {
                    "input_kind": item.input_kind.value,
                    "input_id": item.input_id,
                    "available_at": item.available_at.isoformat(),
                    "quality_label": item.quality_label,
                    "status": item.status.value,
                }
                for item in self.inputs
            ],
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def validate_against(self, mandate: AgentMandate) -> None:
        if mandate.role is not self.role or mandate.mandate_id != self.mandate_id:
            raise ResearchCouncilError("AGENT_INPUT_MANDATE_MISMATCH")
        missing = set(mandate.required_input_kinds) - set(self.input_kinds)
        if missing:
            names = ",".join(sorted(item.value for item in missing))
            raise ResearchCouncilError(
                f"AGENT_REQUIRED_INPUT_KIND_MISSING:{self.role.value}:{names}"
            )


@dataclass(frozen=True, order=True)
class OpinionEvidenceRef:
    input_id: str
    effect: EvidenceEffect
    note: str

    def __post_init__(self) -> None:
        input_id = self.input_id.strip().lower()
        note = self.note.strip()
        if not input_id:
            raise ResearchCouncilError("OPINION_EVIDENCE_INPUT_ID_REQUIRED")
        if not note:
            raise ResearchCouncilError("OPINION_EVIDENCE_NOTE_REQUIRED")
        object.__setattr__(self, "input_id", input_id)
        object.__setattr__(self, "note", note)


@dataclass(frozen=True)
class AgentOpinion:
    """Structured analyst output. This is research, not a portfolio instruction."""

    security_id: str
    role: CouncilRole
    as_of: datetime
    mandate_id: str
    input_packet_id: str
    status: ReadinessStatus
    stance: OpinionStance
    score: int | None
    confidence: float
    input_quality_score: float
    thesis: str
    counterpoint: str
    evidence_refs: tuple[OpinionEvidenceRef, ...]
    invalidation_conditions: tuple[str, ...]
    uncertainty_codes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    reasoning_engine: str = "UNSPECIFIED"
    reasoning_engine_version: str = "UNSPECIFIED"
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        mandate_id = self.mandate_id.strip().lower()
        packet_id = self.input_packet_id.strip().lower()
        thesis = self.thesis.strip()
        counterpoint = self.counterpoint.strip()
        engine = self.reasoning_engine.strip().upper()
        engine_version = self.reasoning_engine_version.strip()
        boundary = _aware_utc(self.as_of, "AGENT_OPINION_AS_OF")
        if not security_id:
            raise ResearchCouncilError("AGENT_OPINION_SECURITY_ID_REQUIRED")
        if not mandate_id or not packet_id:
            raise ResearchCouncilError("AGENT_OPINION_LINEAGE_REQUIRED")
        if not thesis or not counterpoint:
            raise ResearchCouncilError("AGENT_OPINION_THESIS_AND_COUNTERPOINT_REQUIRED")
        if not engine or not engine_version:
            raise ResearchCouncilError("AGENT_OPINION_REASONING_ENGINE_REQUIRED")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ResearchCouncilError("AGENT_OPINION_CONFIDENCE_OUT_OF_RANGE")
        if not math.isfinite(self.input_quality_score) or not 0.0 <= self.input_quality_score <= 1.0:
            raise ResearchCouncilError("AGENT_OPINION_INPUT_QUALITY_OUT_OF_RANGE")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ResearchCouncilError("AGENT_OPINION_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED:
            if self.score is not None or self.stance is not OpinionStance.NO_VIEW:
                raise ResearchCouncilError("BLOCKED_OPINION_CANNOT_HAVE_DIRECTIONAL_VIEW")
            if self.confidence != 0.0 or not self.blockers:
                raise ResearchCouncilError(
                    "BLOCKED_OPINION_REQUIRES_ZERO_CONFIDENCE_AND_BLOCKER"
                )
        else:
            if self.score is None or not -100 <= self.score <= 100:
                raise ResearchCouncilError("AGENT_OPINION_SCORE_OUT_OF_RANGE")
            if self.stance is OpinionStance.NO_VIEW:
                raise ResearchCouncilError("NONBLOCKED_OPINION_REQUIRES_DIRECTIONAL_STANCE")
            if not self.evidence_refs:
                raise ResearchCouncilError("NONBLOCKED_OPINION_REQUIRES_EVIDENCE_REFS")
            if not self.invalidation_conditions:
                raise ResearchCouncilError(
                    "NONBLOCKED_OPINION_REQUIRES_INVALIDATION_CONDITION"
                )
        evidence_ids = [item.input_id for item in self.evidence_refs]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ResearchCouncilError("OPINION_EVIDENCE_REFS_MUST_BE_UNIQUE")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "mandate_id", mandate_id)
        object.__setattr__(self, "input_packet_id", packet_id)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(self, "thesis", thesis)
        object.__setattr__(self, "counterpoint", counterpoint)
        object.__setattr__(self, "reasoning_engine", engine)
        object.__setattr__(self, "reasoning_engine_version", engine_version)
        object.__setattr__(
            self,
            "evidence_refs",
            tuple(sorted(self.evidence_refs, key=lambda item: (item.input_id, item.effect.value))),
        )
        object.__setattr__(
            self,
            "invalidation_conditions",
            tuple(sorted({item.strip() for item in self.invalidation_conditions if item.strip()})),
        )
        object.__setattr__(self, "uncertainty_codes", _normalized_strings(self.uncertainty_codes))
        object.__setattr__(self, "blockers", _normalized_strings(self.blockers))
        object.__setattr__(self, "warnings", _normalized_strings(self.warnings))

    @property
    def opinion_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "role": self.role.value,
            "as_of": self.as_of.isoformat(),
            "mandate_id": self.mandate_id,
            "input_packet_id": self.input_packet_id,
            "status": self.status.value,
            "stance": self.stance.value,
            "score": self.score,
            "confidence": self.confidence,
            "input_quality_score": self.input_quality_score,
            "thesis": self.thesis,
            "counterpoint": self.counterpoint,
            "evidence_refs": [
                {"input_id": item.input_id, "effect": item.effect.value, "note": item.note}
                for item in self.evidence_refs
            ],
            "invalidation_conditions": list(self.invalidation_conditions),
            "uncertainty_codes": list(self.uncertainty_codes),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "reasoning_engine": self.reasoning_engine,
            "reasoning_engine_version": self.reasoning_engine_version,
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


DEFAULT_COUNCIL_ROLES = tuple(CouncilRole)


@dataclass(frozen=True)
class ResearchCouncilPacket:
    """Auditable collection of independent opinions with no fusion or capital decision."""

    security_id: str
    as_of: datetime
    mandate_registry_id: str
    input_packets: tuple[AgentInputPacket, ...]
    opinions: tuple[AgentOpinion, ...]
    required_roles: tuple[CouncilRole, ...]
    missing_roles: tuple[CouncilRole, ...]
    status: ReadinessStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        security_id = self.security_id.strip().upper()
        registry_id = self.mandate_registry_id.strip().lower()
        boundary = _aware_utc(self.as_of, "RESEARCH_COUNCIL_AS_OF")
        if not security_id or not registry_id:
            raise ResearchCouncilError("RESEARCH_COUNCIL_IDENTITY_REQUIRED")
        if not self.research_only or self.trading_authorized or self.live_trading_enabled:
            raise ResearchCouncilError("RESEARCH_COUNCIL_MUST_REMAIN_RESEARCH_ONLY")
        if self.status is ReadinessStatus.BLOCKED and not self.blockers:
            raise ResearchCouncilError("BLOCKED_COUNCIL_REQUIRES_BLOCKER")
        object.__setattr__(self, "security_id", security_id)
        object.__setattr__(self, "mandate_registry_id", registry_id)
        object.__setattr__(self, "as_of", boundary)
        object.__setattr__(
            self,
            "input_packets",
            tuple(sorted(self.input_packets, key=lambda item: item.role.value)),
        )
        object.__setattr__(
            self,
            "opinions",
            tuple(sorted(self.opinions, key=lambda item: item.role.value)),
        )
        object.__setattr__(
            self,
            "required_roles",
            tuple(sorted(set(self.required_roles), key=lambda item: item.value)),
        )
        object.__setattr__(
            self,
            "missing_roles",
            tuple(sorted(set(self.missing_roles), key=lambda item: item.value)),
        )
        object.__setattr__(self, "blockers", _normalized_strings(self.blockers))
        object.__setattr__(self, "warnings", _normalized_strings(self.warnings))

    @property
    def council_packet_id(self) -> str:
        payload = {
            "security_id": self.security_id,
            "as_of": self.as_of.isoformat(),
            "mandate_registry_id": self.mandate_registry_id,
            "input_packet_ids": [item.packet_id for item in self.input_packets],
            "opinion_ids": [item.opinion_id for item in self.opinions],
            "required_roles": [item.value for item in self.required_roles],
            "missing_roles": [item.value for item in self.missing_roles],
            "status": self.status.value,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class ResearchCouncilAssembler:
    """Validate lineage and assemble independent opinions without creating consensus."""

    def __init__(self, registry: AgentMandateRegistry) -> None:
        self.registry = registry

    def assemble(
        self,
        *,
        security_id: str,
        as_of: datetime,
        input_packets: tuple[AgentInputPacket, ...],
        opinions: tuple[AgentOpinion, ...],
        required_roles: tuple[CouncilRole, ...] = DEFAULT_COUNCIL_ROLES,
    ) -> ResearchCouncilPacket:
        ticker_id = security_id.strip().upper()
        boundary = _aware_utc(as_of, "RESEARCH_COUNCIL_AS_OF")
        packet_by_role = self._validate_packets(ticker_id, boundary, input_packets)
        opinion_by_role = self._validate_opinions(
            ticker_id,
            boundary,
            packet_by_role,
            opinions,
        )
        required = tuple(sorted(set(required_roles), key=lambda item: item.value))
        missing = tuple(role for role in required if role not in opinion_by_role)
        blockers: list[str] = [f"MISSING_COUNCIL_ROLE:{role.value}" for role in missing]
        warnings: list[str] = []

        for role in required:
            opinion = opinion_by_role.get(role)
            if opinion is None:
                continue
            if opinion.status is ReadinessStatus.BLOCKED:
                blockers.append(f"BLOCKED_COUNCIL_ROLE:{role.value}")
            elif opinion.status is ReadinessStatus.WARNING:
                warnings.append(f"WARNING_COUNCIL_ROLE:{role.value}")
            warnings.extend(f"{role.value}:{item}" for item in opinion.warnings)

        status = (
            ReadinessStatus.BLOCKED
            if blockers
            else ReadinessStatus.WARNING
            if warnings
            else ReadinessStatus.PASS
        )
        return ResearchCouncilPacket(
            security_id=ticker_id,
            as_of=boundary,
            mandate_registry_id=self.registry.registry_id,
            input_packets=tuple(packet_by_role.values()),
            opinions=tuple(opinion_by_role.values()),
            required_roles=required,
            missing_roles=missing,
            status=status,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def _validate_packets(
        self,
        security_id: str,
        as_of: datetime,
        packets: tuple[AgentInputPacket, ...],
    ) -> dict[CouncilRole, AgentInputPacket]:
        result: dict[CouncilRole, AgentInputPacket] = {}
        for packet in packets:
            if packet.security_id != security_id or packet.as_of != as_of:
                raise ResearchCouncilError("COUNCIL_INPUT_PACKET_CONTEXT_MISMATCH")
            if packet.role in result:
                raise ResearchCouncilError(f"DUPLICATE_COUNCIL_INPUT_ROLE:{packet.role.value}")
            mandate = self.registry.get(packet.role)
            packet.validate_against(mandate)
            result[packet.role] = packet
        return result

    def _validate_opinions(
        self,
        security_id: str,
        as_of: datetime,
        packets: dict[CouncilRole, AgentInputPacket],
        opinions: tuple[AgentOpinion, ...],
    ) -> dict[CouncilRole, AgentOpinion]:
        result: dict[CouncilRole, AgentOpinion] = {}
        for opinion in opinions:
            if opinion.security_id != security_id or opinion.as_of != as_of:
                raise ResearchCouncilError("COUNCIL_OPINION_CONTEXT_MISMATCH")
            if opinion.role in result:
                raise ResearchCouncilError(
                    f"DUPLICATE_COUNCIL_OPINION_ROLE:{opinion.role.value}"
                )
            packet = packets.get(opinion.role)
            if packet is None:
                raise ResearchCouncilError(
                    f"COUNCIL_OPINION_INPUT_PACKET_MISSING:{opinion.role.value}"
                )
            mandate = self.registry.get(opinion.role)
            if (
                opinion.mandate_id != mandate.mandate_id
                or opinion.input_packet_id != packet.packet_id
            ):
                raise ResearchCouncilError("COUNCIL_OPINION_LINEAGE_MISMATCH")
            allowed_ids = set(packet.input_ids)
            cited_ids = {item.input_id for item in opinion.evidence_refs}
            if not cited_ids <= allowed_ids:
                unknown = ",".join(sorted(cited_ids - allowed_ids))
                raise ResearchCouncilError(f"COUNCIL_OPINION_CITES_UNKNOWN_INPUT:{unknown}")
            result[opinion.role] = opinion
        return result


def default_research_council_registry() -> AgentMandateRegistry:
    """Institutional V1 first-pass analyst mandates.

    Each role sees its governed input packet independently. The later CIO/Fusion layer may
    inspect these opinions; the analysts themselves may not inspect one another here.
    """
    return AgentMandateRegistry(
        (
            AgentMandate(
                role=CouncilRole.MOMENTUM,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Assess price trend, relative strength, persistence and momentum quality."
                ),
                required_input_kinds=(CouncilInputKind.FEATURE, CouncilInputKind.MARKET_STATE),
                optional_input_kinds=(CouncilInputKind.QUANT_MODEL, CouncilInputKind.EVIDENCE),
            ),
            AgentMandate(
                role=CouncilRole.ROTATION,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Assess sector, industry and cross-sectional leadership and rotation."
                ),
                required_input_kinds=(CouncilInputKind.FEATURE, CouncilInputKind.EVIDENCE),
                optional_input_kinds=(
                    CouncilInputKind.MARKET_STATE,
                    CouncilInputKind.REGIME_CONTEXT,
                ),
            ),
            AgentMandate(
                role=CouncilRole.CATALYST,
                version="RESEARCH_COUNCIL_V1",
                objective="Assess material events, catalysts, timing and event-path asymmetry.",
                required_input_kinds=(
                    CouncilInputKind.EVENT_STATE,
                    CouncilInputKind.RESEARCH_FACT,
                ),
                optional_input_kinds=(
                    CouncilInputKind.MARKET_STATE,
                    CouncilInputKind.FEATURE,
                ),
            ),
            AgentMandate(
                role=CouncilRole.FUNDAMENTAL,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Assess business quality, fundamentals, revisions and fundamental trajectory."
                ),
                required_input_kinds=(CouncilInputKind.RESEARCH_FACT,),
                optional_input_kinds=(CouncilInputKind.FEATURE, CouncilInputKind.EVENT_STATE),
            ),
            AgentMandate(
                role=CouncilRole.MACRO,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Assess macro regime, rates, inflation, liquidity and systemic backdrop."
                ),
                required_input_kinds=(
                    CouncilInputKind.RESEARCH_FACT,
                    CouncilInputKind.REGIME_CONTEXT,
                ),
                optional_input_kinds=(CouncilInputKind.MARKET_STATE,),
            ),
            AgentMandate(
                role=CouncilRole.INSTITUTIONAL,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Assess institutional ownership, insider activity and disclosed capital flows."
                ),
                required_input_kinds=(CouncilInputKind.RESEARCH_FACT,),
                optional_input_kinds=(CouncilInputKind.EVENT_STATE, CouncilInputKind.FEATURE),
            ),
            AgentMandate(
                role=CouncilRole.BEHAVIORAL,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Assess behavioral and alternative-data acceleration without overstating "
                    "source authority."
                ),
                required_input_kinds=(CouncilInputKind.RESEARCH_FACT,),
                optional_input_kinds=(CouncilInputKind.FEATURE, CouncilInputKind.MARKET_STATE),
            ),
            AgentMandate(
                role=CouncilRole.BULL,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Construct the strongest evidence-backed case for positive investment asymmetry."
                ),
                required_input_kinds=(
                    CouncilInputKind.FEATURE,
                    CouncilInputKind.RESEARCH_FACT,
                ),
                optional_input_kinds=(
                    CouncilInputKind.EVENT_STATE,
                    CouncilInputKind.QUANT_MODEL,
                    CouncilInputKind.MARKET_STATE,
                ),
            ),
            AgentMandate(
                role=CouncilRole.BEAR,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Construct the strongest evidence-backed case against committing or retaining "
                    "risk."
                ),
                required_input_kinds=(
                    CouncilInputKind.FEATURE,
                    CouncilInputKind.RESEARCH_FACT,
                ),
                optional_input_kinds=(
                    CouncilInputKind.EVENT_STATE,
                    CouncilInputKind.QUANT_MODEL,
                    CouncilInputKind.MARKET_STATE,
                ),
            ),
            AgentMandate(
                role=CouncilRole.SKEPTIC,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Search for missing, stale, contradictory, crowded or weakly supported evidence."
                ),
                required_input_kinds=(CouncilInputKind.EVIDENCE, CouncilInputKind.FEATURE),
                optional_input_kinds=(
                    CouncilInputKind.EVENT_STATE,
                    CouncilInputKind.RESEARCH_FACT,
                    CouncilInputKind.MARKET_STATE,
                ),
            ),
            AgentMandate(
                role=CouncilRole.RISK_ANALYST,
                version="RESEARCH_COUNCIL_V1",
                objective=(
                    "Assess downside paths, concentration, correlation, liquidity and portfolio "
                    "risk context."
                ),
                required_input_kinds=(
                    CouncilInputKind.FEATURE,
                    CouncilInputKind.PORTFOLIO_CONTEXT,
                ),
                optional_input_kinds=(
                    CouncilInputKind.EVENT_STATE,
                    CouncilInputKind.REGIME_CONTEXT,
                    CouncilInputKind.MARKET_STATE,
                ),
            ),
        )
    )
