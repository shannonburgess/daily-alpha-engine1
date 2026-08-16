"""Official White House source adapter for the Trump policy-watch layer."""

from __future__ import annotations

import math
import re
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .trump_policy import TrumpPolicyCompany

WHITE_HOUSE_INVESTMENTS_URL = "https://www.whitehouse.gov/investments/"
_USER_AGENT = "DailyAlphaResearch/0.1 (+https://github.com/shannonburgess/daily-alpha-engine1)"
_AMOUNT_RE = re.compile(r"\$?\s*([0-9][0-9,.]*)\s*(trillion|billion|million)", re.I)


class TrumpPolicySourceError(RuntimeError):
    """Official Trump-administration policy source could not be normalized safely."""


# Public-company aliases intentionally remain explicit and auditable. Private
# companies and companies without a straightforward U.S.-tradable ticker are
# omitted rather than guessed.
COMPANY_SYMBOLS = {
    "meta": "META",
    "ibm": "IBM",
    "micron": "MU",
    "micron technology": "MU",
    "nvidia": "NVDA",
    "apple": "AAPL",
    "siemens": "SIEGY",
    "fiserv": "FISV",
    "amazon": "AMZN",
    "general dynamics": "GD",
    "l3harris": "LHX",
    "lockheed martin": "LMT",
    "blackrock": "BLK",
    "jpmorgan chase": "JPM",
    "jpmorganchase": "JPM",
    "cencora": "COR",
    "johnson & johnson": "JNJ",
    "pfizer": "PFE",
    "gsk": "GSK",
    "astrazeneca": "AZN",
    "bristol myers squibb": "BMY",
    "gilead sciences": "GILD",
    "abbvie": "ABBV",
    "thermo fisher scientific": "TMO",
    "amgen": "AMGN",
    "eli lilly and company": "LLY",
    "novartis": "NVS",
    "abbott labs": "ABT",
    "abbott laboratories": "ABT",
    "merck": "MRK",
    "merck & co.": "MRK",
    "regeneron pharmaceuticals": "REGN",
    "biogen": "BIIB",
    "nokia": "NOK",
    "arm inc.": "ARM",
    "arm inc": "ARM",
    "whirlpool": "WHR",
    "oklo inc.": "OKLO",
    "oklo": "OKLO",
    "ford": "F",
    "caterpillar": "CAT",
    "boeing": "BA",
    "ge aerospace": "GE",
    "corning, inc.": "GLW",
    "corning": "GLW",
    "eaton corporation": "ETN",
    "abb": "ABBNY",
    "carrier": "CARR",
    "nippon steel": "NPSCY",
    "u.s. steel": "X",
    "gm": "GM",
    "general motors": "GM",
    "jabil": "JBL",
    "rolls royce": "RYCEY",
    "century aluminum co.": "CENX",
    "century aluminum": "CENX",
    "globalfoundries": "GFS",
    "honda": "HMC",
    "tesla": "TSLA",
    "stellantis": "STLA",
    "toyota motor corporation": "TM",
    "toyota motor": "TM",
    "at&t": "T",
    "kimberly-clark": "KMB",
    "kimberly clark": "KMB",
    "philip morris": "PM",
    "philips": "PHG",
}


class _InvestmentTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._table_depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr" and self._table_depth:
            self._row = []
        elif tag in {"td", "th"} and self._table_depth and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = " ".join("".join(self._cell).split())
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1


def fetch_white_house_investments(*, limit: int = 50) -> tuple[TrumpPolicyCompany, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    html = _fetch_html(WHITE_HOUSE_INVESTMENTS_URL)
    parser = _InvestmentTableParser()
    parser.feed(html)
    rows: list[TrumpPolicyCompany] = []
    for cells in parser.rows:
        if len(cells) < 4 or cells[0].strip().lower() == "company":
            continue
        company, amount_text, sector, focus = cells[:4]
        symbol = _symbol_for_company(company)
        if not symbol:
            continue
        investment = parse_investment_amount(amount_text)
        if investment <= 0:
            continue
        score = _policy_score(investment)
        rows.append(
            TrumpPolicyCompany(
                rank=0,
                symbol=symbol,
                company=company,
                score=score,
                investment_usd=investment,
                sector=sector or "UNKNOWN",
                investment_focus=focus,
                source_type="WHITE_HOUSE_INVESTMENTS",
                source_url=WHITE_HOUSE_INVESTMENTS_URL,
                direct_trump_mention=False,
                administration_beneficiary=True,
                trump_affiliated=False,
            )
        )
    if not rows:
        raise TrumpPolicySourceError("WHITE_HOUSE_INVESTMENTS_NO_PUBLIC_COMPANIES")
    rows.sort(key=lambda item: (-item.score, -item.investment_usd, item.symbol))
    return tuple(rows[:limit])


def parse_investment_amount(value: str) -> float:
    match = _AMOUNT_RE.search(value or "")
    if not match:
        return 0.0
    number = float(match.group(1).replace(",", ""))
    multiplier = {"million": 1e6, "billion": 1e9, "trillion": 1e12}[match.group(2).lower()]
    return number * multiplier


def _policy_score(investment_usd: float) -> float:
    # Broad ranking score for the standalone watch. The research bonus used by
    # the shortlist is separately capped at +5 in TrumpPolicyCompany.
    magnitude = max(0.0, math.log10(max(investment_usd, 1.0)) - 6.0)
    return round(min(100.0, 35.0 + magnitude * 11.0), 2)


def _symbol_for_company(company: str) -> str:
    normalized = " ".join(company.strip().lower().split())
    if normalized in COMPANY_SYMBOLS:
        return COMPANY_SYMBOLS[normalized]
    # A few White House rows combine multiple companies. Use only a mapping
    # when exactly one auditable public ticker is unambiguous.
    return ""


def _fetch_html(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        request = Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Connection": "close",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise TrumpPolicySourceError(f"WHITE_HOUSE_HTTP_{exc.code}") from exc
        except URLError as exc:
            last_error = exc
        if attempt < 3:
            time.sleep(float(attempt * 2))
    if isinstance(last_error, HTTPError):
        raise TrumpPolicySourceError(f"WHITE_HOUSE_HTTP_{last_error.code}") from last_error
    raise TrumpPolicySourceError("WHITE_HOUSE_NETWORK_ERROR") from last_error
