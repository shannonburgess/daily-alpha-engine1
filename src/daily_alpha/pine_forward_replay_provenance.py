from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class ForwardReplayProvenance:
    """Immutable lineage for the inputs used to produce one forward Python replay.

    This record does not claim parity by itself. It prevents a receipt-matching signal list from
    being represented as audited forward replay evidence without exact market/earnings, Pine input,
    Python-engine and deployment identities.
    """

    model_id: str
    strategy_version: str
    strategy_source_blob_sha: str
    parameter_manifest_sha256: str
    market_evidence_sha256: str
    market_source_revision: str
    python_engine_revision: str
    replay_start: datetime
    replay_end: datetime
    replay_bar_count: int
    deployment_commit_sha: str
    processor_code_sha256: str
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "model_id",
            "strategy_version",
            "market_source_revision",
            "python_engine_revision",
            "processor_code_sha256",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if not _GIT_SHA_RE.fullmatch(self.strategy_source_blob_sha):
            raise ValueError("strategy_source_blob_sha must be a 40-character Git blob SHA")
        if not _SHA256_RE.fullmatch(self.parameter_manifest_sha256):
            raise ValueError("parameter_manifest_sha256 must be a lowercase SHA-256")
        if not _SHA256_RE.fullmatch(self.market_evidence_sha256):
            raise ValueError("market_evidence_sha256 must be a lowercase SHA-256")
        if not _GIT_SHA_RE.fullmatch(self.deployment_commit_sha):
            raise ValueError("deployment_commit_sha must be a 40-character Git SHA")
        if self.replay_start.tzinfo is None or self.replay_start.utcoffset() is None:
            raise ValueError("replay_start must be timezone-aware")
        if self.replay_end.tzinfo is None or self.replay_end.utcoffset() is None:
            raise ValueError("replay_end must be timezone-aware")
        if self.replay_end < self.replay_start:
            raise ValueError("replay_end cannot be before replay_start")
        if self.replay_bar_count < 1:
            raise ValueError("replay_bar_count must be positive")
        if self.trading_authorized or self.live_trading_enabled:
            raise ValueError("forward replay provenance cannot authorize trading")

    @property
    def evidence_id(self) -> str:
        payload = {
            "model_id": self.model_id,
            "strategy_version": self.strategy_version,
            "strategy_source_blob_sha": self.strategy_source_blob_sha,
            "parameter_manifest_sha256": self.parameter_manifest_sha256,
            "market_evidence_sha256": self.market_evidence_sha256,
            "market_source_revision": self.market_source_revision,
            "python_engine_revision": self.python_engine_revision,
            "replay_start": self.replay_start.isoformat(),
            "replay_end": self.replay_end.isoformat(),
            "replay_bar_count": self.replay_bar_count,
            "deployment_commit_sha": self.deployment_commit_sha,
            "processor_code_sha256": self.processor_code_sha256,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["ForwardReplayProvenance"]
