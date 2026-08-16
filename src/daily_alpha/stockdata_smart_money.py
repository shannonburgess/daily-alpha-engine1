"""Authenticated smart-money data adapter for reliable GitHub automation.

Uses stockdata.dev as a normalized read-only transport for congressional STOCK
Act disclosures and SEC Form 13F holdings. The adapter never places trades and
never accepts execution instructions.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .smart_money import CongressionalTrade, InstitutionalHolding
from .smart_money_sources import SmartMoneySourceError

Transport = Callable[[str, Mapping[str, str]], Any]


@dataclass(frozen=True)
class InstitutionalCoverage:
    current_period: str
    previous_period: str
    institutions_requested: int
    current_rows: int
    previous_rows: int
    portfolio_limit: int


class StockDataSmartMoneyClient:
    BASE_URL = "https://api.stockdata.dev/v1"
    USER_AGENT = "DailyAlphaResearch/0.1 (+https://github.com/shannonburgess/daily-alpha-engine1)"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: Transport | None = None,
        min_request_interval_seconds: float = 1.05,
    ) -> None:
        self._api_key = api_key or os.getenv("STOCKDATA_API_KEY", "")
        if not self._api_key:
            raise SmartMoneySourceError("STOCKDATA_API_KEY_MISSING")
        if min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds must be non-negative")
        self._transport = transport or self._request_json
        self._min_interval = min_request_interval_seconds
        self._last_request_monotonic: float | None = None

    def fetch_congressional_purchases(
        self,
        *,
        days: int = 90,
        limit: int = 500,
    ) -> tuple[CongressionalTrade, ...]:
        if days <= 0 or days > 365:
            raise ValueError("days must be between 1 and 365")
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        payload = self._get("congress-trades", {"days": days, "limit": limit})
        rows = _rows(payload, "trades")
        trades: list[CongressionalTrade] = []
        for row in rows:
            transaction_type = str(row.get("transaction_type") or "").upper()
            if transaction_type not in {"PURCHASE", "BUY", "BOUGHT"}:
                continue
            symbol = str(row.get("ticker") or "").strip().upper()
            if not symbol or symbol in {"--", "N/A", "NA"}:
                continue
            transaction_date = _date(row.get("transaction_date"))
            disclosure_date = _date(
                row.get("disclosure_date")
                or row.get("filing_date")
                or row.get("report_date")
            )
            if transaction_date is None or disclosure_date is None:
                continue
            politician = row.get("politician")
            person = politician if isinstance(politician, Mapping) else {}
            amount_low = _number(row.get("amount_min") or row.get("amount_low"))
            amount_high = _optional_number(row.get("amount_max") or row.get("amount_high"))
            if amount_low <= 0:
                continue
            trades.append(
                CongressionalTrade(
                    politician=str(person.get("name") or row.get("member") or "Unknown"),
                    chamber=str(person.get("chamber") or row.get("chamber") or "Unknown").title(),
                    symbol=symbol,
                    issuer=str(row.get("company") or row.get("asset_name") or symbol),
                    transaction_date=transaction_date,
                    disclosure_date=disclosure_date,
                    transaction_type="PURCHASE",
                    amount_low=amount_low,
                    amount_high=amount_high,
                    source_url=str(row.get("url") or row.get("source_url") or ""),
                )
            )
        return tuple(trades)

    def fetch_institutional_holdings_pair(
        self,
        *,
        as_of: date,
        institution_limit: int = 25,
        portfolio_limit: int = 500,
    ) -> tuple[
        tuple[InstitutionalHolding, ...],
        tuple[InstitutionalHolding, ...],
        InstitutionalCoverage,
    ]:
        if institution_limit <= 0 or institution_limit > 200:
            raise ValueError("institution_limit must be between 1 and 200")
        if portfolio_limit <= 0 or portfolio_limit > 500:
            raise ValueError("portfolio_limit must be between 1 and 500")

        current_period, current_end = _latest_reportable_quarter(as_of)
        previous_period, previous_end = _previous_quarter(current_period)
        institutions_payload = self._get(
            "institutions",
            {"period": current_period, "limit": institution_limit},
        )
        institutions = _rows(institutions_payload, "institutions")[:institution_limit]
        if not institutions:
            raise SmartMoneySourceError("STOCKDATA_INSTITUTIONS_EMPTY")

        current_rows: list[InstitutionalHolding] = []
        previous_rows: list[InstitutionalHolding] = []
        for item in institutions:
            cik = str(item.get("institution_cik") or "").strip()
            name = str(item.get("institution") or cik).strip()
            if not cik:
                continue
            current_payload = self._get(
                f"institutions/portfolio/{cik}",
                {"period": current_period, "limit": portfolio_limit},
            )
            previous_payload = self._get(
                f"institutions/portfolio/{cik}",
                {"period": previous_period, "limit": portfolio_limit},
            )
            current_rows.extend(
                _portfolio_holdings(current_payload, cik=cik, manager_name=name, period=current_end)
            )
            previous_rows.extend(
                _portfolio_holdings(previous_payload, cik=cik, manager_name=name, period=previous_end)
            )

        if not current_rows:
            raise SmartMoneySourceError("STOCKDATA_CURRENT_13F_EMPTY")
        coverage = InstitutionalCoverage(
            current_period=current_period,
            previous_period=previous_period,
            institutions_requested=len(institutions),
            current_rows=len(current_rows),
            previous_rows=len(previous_rows),
            portfolio_limit=portfolio_limit,
        )
        return tuple(current_rows), tuple(previous_rows), coverage

    def _get(self, path: str, params: Mapping[str, object]) -> Any:
        self._throttle()
        query = urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{self.BASE_URL}/{path}"
        if query:
            url = f"{url}?{query}"
        headers = {
            "X-API-Key": self._api_key,
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
            "Connection": "close",
        }
        try:
            return self._transport(url, headers)
        except SmartMoneySourceError:
            raise
        except Exception as exc:
            raise SmartMoneySourceError(
                f"STOCKDATA_REQUEST_FAILED:{type(exc).__name__}"
            ) from exc
        finally:
            self._last_request_monotonic = time.monotonic()

    def _throttle(self) -> None:
        if self._last_request_monotonic is None or self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self._min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _request_json(url: str, headers: Mapping[str, str]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            request = Request(url, headers=dict(headers))
            try:
                with urlopen(request, timeout=20) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise SmartMoneySourceError(f"STOCKDATA_HTTP_{exc.code}") from exc
                last_error = exc
            except URLError as exc:
                last_error = exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SmartMoneySourceError("STOCKDATA_INVALID_JSON") from exc

            if attempt < 3:
                time.sleep(float(attempt * 2))

        if isinstance(last_error, HTTPError):
            raise SmartMoneySourceError(f"STOCKDATA_HTTP_{last_error.code}") from last_error
        raise SmartMoneySourceError("STOCKDATA_NETWORK_ERROR") from last_error


def _portfolio_holdings(
    payload: Any,
    *,
    cik: str,
    manager_name: str,
    period: date,
) -> list[InstitutionalHolding]:
    holdings = _rows(payload, "holdings")
    normalized: list[InstitutionalHolding] = []
    for row in holdings:
        symbol = str(row.get("ticker") or "").strip().upper()
        shares = _number(row.get("shares"))
        value = _number(row.get("value"))
        if not symbol or shares <= 0 or value < 0:
            continue
        normalized.append(
            InstitutionalHolding(
                manager_cik=cik,
                manager_name=str(row.get("institution") or manager_name),
                cusip=f"TICKER:{symbol}",
                issuer=str(row.get("name") or row.get("issuer") or symbol),
                symbol=symbol,
                period_of_report=_date(row.get("report_date")) or period,
                shares=shares,
                value=value,
            )
        )
    return normalized


def _rows(payload: Any, key: str) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise SmartMoneySourceError("STOCKDATA_UNEXPECTED_RESPONSE")
    value = payload.get(key)
    if not isinstance(value, list):
        raise SmartMoneySourceError(f"STOCKDATA_{key.upper()}_MISSING")
    return [item for item in value if isinstance(item, Mapping)]


def _latest_reportable_quarter(as_of: date) -> tuple[str, date]:
    year = as_of.year
    candidates = [
        (f"{year}-Q2", date(year, 6, 30)),
        (f"{year}-Q1", date(year, 3, 31)),
        (f"{year - 1}-Q4", date(year - 1, 12, 31)),
        (f"{year - 1}-Q3", date(year - 1, 9, 30)),
    ]
    for label, quarter_end in candidates:
        if as_of >= quarter_end + timedelta(days=46):
            return label, quarter_end
    return f"{year - 1}-Q2", date(year - 1, 6, 30)


def _previous_quarter(period: str) -> tuple[str, date]:
    year_text, quarter_text = period.split("-Q", maxsplit=1)
    year = int(year_text)
    quarter = int(quarter_text)
    if quarter == 1:
        year -= 1
        quarter = 4
    else:
        quarter -= 1
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    month, day = ends[quarter]
    return f"{year}-Q{quarter}", date(year, month, day)


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _number(value)
