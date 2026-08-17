"""Minimal ORATS option-chain client with explicit freshness validation."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import OptionCandidate


class OratsError(RuntimeError):
    """Base class for ORATS integration failures."""


class OratsConfigurationError(OratsError):
    """Raised when required local configuration is missing or invalid."""


class OratsRequestError(OratsError):
    """Raised when ORATS cannot return a usable response."""


class OratsDataError(OratsError):
    """Raised when ORATS data is empty, malformed, or stale."""


class OratsNoOptionsError(OratsDataError):
    """Raised when ORATS has no option rows for the requested DTE window."""


@dataclass(frozen=True)
class OratsChain:
    ticker: str
    candidates: tuple[OptionCandidate, ...]
    observed_at: datetime
    source_mode: str


Transport = Callable[[str, float], Any]


class OratsClient:
    """Retrieve and normalize ORATS option-chain data.

    ``delayed`` uses the standard delayed Data API ``/strikes`` endpoint, which
    is separate from the premium one-minute intraday API. ``live`` uses the
    standard live ``/live/strikes`` endpoint.

    The token is read from ORATS_TOKEN and is never accepted in logs or
    serialized objects. A custom transport can be injected for unit tests.
    """

    BASE_URL = "https://api.orats.io/datav2"

    def __init__(
        self,
        *,
        token: str | None = None,
        mode: str = "delayed",
        timeout_seconds: float = 20.0,
        max_age_minutes: int | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._token = token or os.getenv("ORATS_TOKEN", "")
        if not self._token:
            raise OratsConfigurationError(
                "ORATS_TOKEN is not set; store it as an environment secret, never in Git"
            )
        if mode not in {"delayed", "live"}:
            raise OratsConfigurationError("ORATS mode must be 'delayed' or 'live'")
        self.mode = mode
        self.timeout_seconds = timeout_seconds
        # The delayed Data API is suitable for scheduled research and the
        # post-market 14:30 Pacific intake, so allow up to two hours here.
        # The decision runtime still applies its own stricter execution-time
        # freshness gate before any paper trade can be authorized.
        self.max_age_minutes = max_age_minutes or (120 if mode == "delayed" else 5)
        self._transport = transport or self._request_json

    def fetch_chain(
        self,
        ticker: str,
        *,
        as_of: datetime | None = None,
        dte_min: int = 45,
        dte_max: int = 75,
    ) -> OratsChain:
        symbol = ticker.strip().upper()
        if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
            raise OratsConfigurationError(f"Invalid ticker: {ticker!r}")
        if dte_min < 0 or dte_max < dte_min:
            raise OratsConfigurationError("ORATS DTE window is invalid")

        path = "live/strikes" if self.mode == "live" else "strikes"
        query = urlencode(
            {"token": self._token, "ticker": symbol, "dte": f"{dte_min},{dte_max}"}
        )
        payload = self._transport(f"{self.BASE_URL}/{path}?{query}", self.timeout_seconds)
        rows = self._extract_rows(payload)
        if not rows:
            raise OratsNoOptionsError(
                f"ORATS returned no {dte_min}-{dte_max} DTE option rows for {symbol}"
            )

        observed_at = self._latest_observation(rows)
        reference = as_of or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        age_minutes = (reference.astimezone(UTC) - observed_at).total_seconds() / 60
        if age_minutes < -1:
            raise OratsDataError("ORATS observation timestamp is in the future")
        if age_minutes > self.max_age_minutes:
            raise OratsDataError(
                f"ORATS data is stale: {age_minutes:.1f} minutes old "
                f"(limit {self.max_age_minutes})"
            )

        candidates = tuple(self._normalize_rows(symbol, rows))
        if not candidates:
            raise OratsDataError(f"ORATS rows for {symbol} contained no usable contracts")
        return OratsChain(
            ticker=symbol,
            candidates=candidates,
            observed_at=observed_at,
            source_mode=self.mode,
        )

    @staticmethod
    def _extract_rows(payload: Any) -> list[Mapping[str, Any]]:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, Mapping)]
        if isinstance(payload, Mapping):
            for key in ("data", "results", "rows"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, Mapping)]
        raise OratsDataError("Unexpected ORATS response format")

    @staticmethod
    def _latest_observation(rows: list[Mapping[str, Any]]) -> datetime:
        observations = []
        for row in rows:
            value = row.get("updatedAt") or row.get("quoteDate") or row.get("snapShotDate")
            if value:
                observations.append(_parse_timestamp(str(value)))
        if not observations:
            raise OratsDataError("ORATS response has no observation timestamp")
        return max(observations)

    @staticmethod
    def _normalize_rows(
        ticker: str,
        rows: list[Mapping[str, Any]],
    ) -> list[OptionCandidate]:
        candidates: list[OptionCandidate] = []
        for row in rows:
            common = {
                "symbol": ticker,
                "expiration": str(row.get("expirDate", "")),
                "strike": _number(row.get("strike")),
                "dte": int(_number(row.get("dte"))),
            }
            call_delta = _optional_number(row.get("callDelta"))
            if call_delta is None:
                call_delta = _optional_number(row.get("delta"))
            put_delta = _optional_number(row.get("putDelta"))
            if put_delta is None and call_delta is not None:
                put_delta = call_delta - 1.0

            for option_type, prefix, delta in (
                ("CALL", "call", call_delta),
                ("PUT", "put", put_delta),
            ):
                bid = _number(row.get(f"{prefix}BidPrice"))
                ask = _number(row.get(f"{prefix}AskPrice"))
                if bid < 0 or ask <= 0:
                    continue
                candidates.append(
                    OptionCandidate(
                        **common,
                        option_type=option_type,
                        bid=bid,
                        ask=ask,
                        open_interest=int(_number(row.get(f"{prefix}OpenInterest"))),
                        volume=int(_number(row.get(f"{prefix}Volume"))),
                        delta=delta,
                    )
                )
        return candidates

    @staticmethod
    def _request_json(url: str, timeout_seconds: float) -> Any:
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise OratsRequestError(f"ORATS HTTP error {exc.code}") from exc
        except URLError as exc:
            raise OratsRequestError("ORATS request failed") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OratsRequestError("ORATS returned invalid JSON") from exc


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OratsDataError(f"Invalid ORATS timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise OratsDataError(f"Invalid numeric ORATS value: {value!r}") from exc


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _number(value)
