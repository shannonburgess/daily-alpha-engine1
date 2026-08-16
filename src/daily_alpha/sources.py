"""Production source discovery and fail-closed batch retrieval adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .orats import (
    OratsChain,
    OratsClient,
    OratsConfigurationError,
    OratsDataError,
    OratsNoOptionsError,
    OratsRequestError,
)


class SourceError(RuntimeError):
    """A required source cannot safely support a Daily Alpha run."""


@dataclass(frozen=True)
class OvtlyrSourceFile:
    path: Path
    observed_at: datetime
    size_bytes: int


class OvtlyrInbox:
    """Select the newest complete CSV copied into the configured inbox."""

    def __init__(
        self, root: str | Path, *, max_age: timedelta = timedelta(hours=36)
    ) -> None:
        self.root = Path(root)
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        self.max_age = max_age

    def latest(self, *, as_of: datetime | None = None) -> OvtlyrSourceFile:
        reference = as_of or datetime.now(UTC)
        if reference.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if not self.root.exists() or not self.root.is_dir():
            raise SourceError("OVTLYR_INBOX_MISSING")
        files = tuple(
            path
            for path in self.root.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".csv"
            and not path.name.startswith((".", "~"))
            and not path.name.endswith((".partial.csv", ".tmp.csv"))
            and path.stat().st_size > 0
        )
        if not files:
            raise SourceError("OVTLYR_CSV_MISSING")
        selected = max(files, key=lambda path: (path.stat().st_mtime, path.name))
        observed = datetime.fromtimestamp(selected.stat().st_mtime, tz=UTC)
        age = reference.astimezone(UTC) - observed
        if age < -timedelta(minutes=1):
            raise SourceError("OVTLYR_TIMESTAMP_IN_FUTURE")
        if age > self.max_age:
            raise SourceError("OVTLYR_CSV_STALE")
        return OvtlyrSourceFile(selected, observed, selected.stat().st_size)


@dataclass(frozen=True)
class OratsBatchResult:
    chains: tuple[OratsChain, ...]
    errors: tuple[tuple[str, str], ...]

    @property
    def complete(self) -> bool:
        return not self.errors


class OratsBatchSource:
    """Retrieve required chains and preserve per-symbol DATA_ERROR reason codes."""

    def __init__(self, client: OratsClient) -> None:
        self.client = client

    def fetch(self, symbols: tuple[str, ...], *, as_of: datetime) -> OratsBatchResult:
        chains: list[OratsChain] = []
        errors: list[tuple[str, str]] = []
        for symbol in tuple(
            dict.fromkeys(value.strip().upper() for value in symbols if value.strip())
        ):
            try:
                chains.append(self.client.fetch_chain(symbol, as_of=as_of))
            except OratsConfigurationError:
                errors.append((symbol, "ORATS_CONFIGURATION_ERROR"))
            except OratsRequestError:
                errors.append((symbol, "ORATS_REQUEST_ERROR"))
            except OratsNoOptionsError:
                errors.append((symbol, "ORATS_NO_45_75_DTE_OPTIONS"))
            except OratsDataError:
                errors.append((symbol, "ORATS_DATA_ERROR"))
        return OratsBatchResult(tuple(chains), tuple(errors))
