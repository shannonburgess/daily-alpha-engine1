"""Public-data adapters for Daily Alpha smart-money research.

Congressional trades are normalized from Bargo's read-only Congress feed, which
links back to official House/Senate STOCK Act filings. Institutional holdings are
read directly from the SEC's official flattened Form 13F data sets. OpenFIGI is
used only to map the small set of top-ranked CUSIPs to exchange tickers.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .smart_money import CongressionalTrade, InstitutionalHolding

BARGO_CONGRESS_URL = "https://www.bargo.ai/free-apis/congress/v1/trades"
OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
_USER_AGENT = "DailyAlphaResearch/0.1 public-disclosure-analysis"
_AMOUNT_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)")


class SmartMoneySourceError(RuntimeError):
    """A public smart-money source could not be normalized safely."""


def fetch_bargo_congress_trades(
    *,
    from_date: date,
    to_date: date,
    max_pages: int = 20,
    page_size: int = 100,
) -> tuple[CongressionalTrade, ...]:
    """Fetch disclosed purchases across both chambers for a bounded date range."""
    if from_date > to_date:
        raise ValueError("from_date must not be after to_date")
    if max_pages <= 0 or page_size <= 0:
        raise ValueError("max_pages and page_size must be positive")
    trades: list[CongressionalTrade] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for page in range(1, max_pages + 1):
        params = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "type": "purchase",
            "limit": min(page_size, 100),
            "page": page,
        }
        payload = _request_json(f"{BARGO_CONGRESS_URL}?{urlencode(params)}")
        rows = _extract_rows(payload)
        if not rows:
            break
        added = 0
        for row in rows:
            trade = parse_congressional_trade(row)
            if trade is None:
                continue
            key = (
                trade.politician,
                trade.symbol,
                trade.transaction_date.isoformat(),
                trade.disclosure_date.isoformat(),
                f"{trade.amount_low}:{trade.amount_high}",
            )
            if key in seen:
                continue
            seen.add(key)
            trades.append(trade)
            added += 1
        if len(rows) < min(page_size, 100) or added == 0:
            break
    return tuple(trades)


def parse_congressional_trade(row: Mapping[str, Any]) -> CongressionalTrade | None:
    transaction_type = _first(row, "type", "trade_type", "transaction", "transaction_type").upper()
    if transaction_type not in {"PURCHASE", "BUY", "BOUGHT"}:
        return None
    symbol = _first(row, "ticker", "symbol").upper()
    if not symbol or symbol in {"--", "N/A", "NA"}:
        return None
    transaction_date = _date(_first(row, "transaction_date", "trade_date", "tx_date", "date"))
    disclosure_date = _date(
        _first(row, "disclosure_date", "report_date", "disclosed", "published", "filed_date")
    )
    if transaction_date is None or disclosure_date is None:
        return None
    amount_low, amount_high = parse_amount_range(_first(row, "amount", "range", "amount_range"))
    if amount_low <= 0:
        return None
    return CongressionalTrade(
        politician=_first(row, "member", "representative", "politician", "name") or "Unknown",
        chamber=(_first(row, "chamber", "house") or "Unknown").title(),
        symbol=symbol,
        issuer=_first(row, "asset", "asset_description", "issuer", "company"),
        transaction_date=transaction_date,
        disclosure_date=disclosure_date,
        transaction_type="PURCHASE",
        amount_low=amount_low,
        amount_high=amount_high,
        source_url=_first(row, "link", "source_url", "url", "filing_url"),
    )


def parse_amount_range(value: str) -> tuple[float, float | None]:
    """Normalize STOCK Act amount bands without pretending they are exact values."""
    text = (value or "").replace("$", "").replace("USD", "").strip()
    numbers = [float(item.replace(",", "")) for item in _AMOUNT_RE.findall(text)]
    if not numbers:
        return 0.0, None
    if len(numbers) == 1:
        if any(token in text.lower() for token in ("over", "more than", "+")):
            return numbers[0], None
        return numbers[0], numbers[0]
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def load_sec_13f_directory(
    root: str | Path,
    *,
    symbol_map: Mapping[str, str] | None = None,
) -> tuple[InstitutionalHolding, ...]:
    """Read one extracted SEC Form 13F bulk data set.

    V1 intentionally uses initial 13F-HR filings only. Amendments are excluded
    rather than double-counted because an amendment can either restate a report
    or add only selected holdings.
    """
    directory = Path(root)
    submission_path = _find_table(directory, "SUBMISSION")
    cover_path = _find_table(directory, "COVERPAGE")
    info_path = _find_table(directory, "INFOTABLE")
    mapping = {str(key).upper(): str(value).upper() for key, value in (symbol_map or {}).items()}

    submissions: dict[str, tuple[str, date]] = {}
    with submission_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if (row.get("SUBMISSIONTYPE") or "").upper() != "13F-HR":
                continue
            accession = (row.get("ACCESSION_NUMBER") or "").strip()
            cik = (row.get("CIK") or "").strip().lstrip("0") or "0"
            period = _sec_date(row.get("PERIODOFREPORT") or "")
            if accession and period:
                submissions[accession] = (cik, period)

    managers: dict[str, str] = {}
    with cover_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            accession = (row.get("ACCESSION_NUMBER") or "").strip()
            if accession in submissions:
                managers[accession] = (row.get("FILINGMANAGER_NAME") or "").strip()

    holdings: list[InstitutionalHolding] = []
    with info_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            accession = (row.get("ACCESSION_NUMBER") or "").strip()
            submission = submissions.get(accession)
            if submission is None:
                continue
            if (row.get("PUTCALL") or "").strip():
                continue
            share_type = (row.get("SSHPRNAMTTYPE") or "").strip().upper()
            if share_type and share_type != "SH":
                continue
            cusip = (row.get("CUSIP") or "").strip().upper()
            if not cusip:
                continue
            shares = _number(row.get("SSHPRNAMT"))
            value = _number(row.get("VALUE"))
            if shares <= 0 or value < 0:
                continue
            cik, period = submission
            holdings.append(
                InstitutionalHolding(
                    manager_cik=cik,
                    manager_name=managers.get(accession, cik),
                    cusip=cusip,
                    issuer=(row.get("NAMEOFISSUER") or "").strip(),
                    symbol=mapping.get(cusip, ""),
                    period_of_report=period,
                    shares=shares,
                    value=value,
                )
            )
    if not holdings:
        raise SmartMoneySourceError("SEC_13F_NO_USABLE_HOLDINGS")
    return tuple(holdings)


def map_cusips_openfigi(cusips: Iterable[str]) -> dict[str, str]:
    """Map a small ranked set of CUSIPs to U.S. tickers using public OpenFIGI."""
    unique = tuple(dict.fromkeys(value.strip().upper() for value in cusips if value.strip()))
    mapped: dict[str, str] = {}
    for offset in range(0, len(unique), 10):
        batch = unique[offset : offset + 10]
        jobs = [{"idType": "ID_CUSIP", "idValue": cusip} for cusip in batch]
        payload = _request_json(
            OPENFIGI_MAPPING_URL,
            method="POST",
            body=json.dumps(jobs).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        if not isinstance(payload, list):
            continue
        for cusip, result in zip(batch, payload, strict=False):
            if not isinstance(result, Mapping):
                continue
            data = result.get("data")
            if not isinstance(data, list):
                continue
            candidates = [item for item in data if isinstance(item, Mapping) and item.get("ticker")]
            if not candidates:
                continue
            chosen = min(
                candidates,
                key=lambda item: (
                    0 if str(item.get("marketSector", "")).upper() == "EQUITY" else 1,
                    0 if str(item.get("exchCode", "")).upper() in {"US", "UN", "UW", "UA"} else 1,
                    str(item.get("ticker", "")),
                ),
            )
            ticker = str(chosen.get("ticker") or "").strip().upper()
            if ticker:
                mapped[cusip] = ticker
    return mapped


def _request_json(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    request_headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    request_headers.update(headers or {})
    request = Request(url, data=body, method=method, headers=request_headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - upstream failures are normalized here
        raise SmartMoneySourceError(f"PUBLIC_DATA_REQUEST_FAILED:{type(exc).__name__}") from exc


def _extract_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("trades", "data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    return []


def _find_table(root: Path, stem: str) -> Path:
    for path in root.rglob("*"):
        if path.is_file() and path.stem.upper() == stem and path.suffix.lower() in {".tsv", ".txt"}:
            return path
    raise SmartMoneySourceError(f"SEC_13F_{stem}_MISSING")


def _sec_date(value: str) -> date | None:
    text = value.strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _number(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0


def _first(row: Mapping[str, Any], *keys: str) -> str:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""
