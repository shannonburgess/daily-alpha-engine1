"""Stage the V1 prospect Top-3 + complete opportunity board into real report delivery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from html import escape
from typing import Any

from .candidates import CandidateAssessment, CandidateBucket
from .prospect_launch_gate import (
    ProspectInitialRolloutGate,
    evaluate_prospect_initial_rollout_gate,
)
from .prospect_opportunity_board import (
    ProspectOpportunityBoard,
    build_prospect_opportunity_board,
)
from .prospect_opportunity_outputs import (
    ProspectOpportunityOutput,
    ProspectOutputChannel,
    build_all_v1_prospect_outputs,
    render_prospect_newsletter_html,
)


class ProspectStagingRuntimeError(RuntimeError):
    """The staging prospect rollout cannot be prepared without violating V1 contracts."""


@dataclass(frozen=True, slots=True)
class PreparedProspectStagingRuntime:
    board: ProspectOpportunityBoard
    outputs: tuple[ProspectOpportunityOutput, ...]
    newsletter_html: str
    history_prefix: str
    latest_prefix: str
    published: Mapping[str, str]

    def summary(self) -> dict[str, object]:
        return {
            "board_id": self.board.board_id,
            "total_qualifying": self.board.total_qualifying,
            "top_pick_symbols": [item.symbol for item in self.board.top_picks],
            "additional_qualifying_count": len(self.board.additional_opportunities),
            "filtered_count": len(self.board.filtered),
            "verified_channels": [item.channel.value for item in self.outputs],
            "trading_authorized": False,
            "live_trading_enabled": False,
        }


class AwsProspectStagingRuntimePublisher:
    """Bridge the merged V1 prospect contracts into the existing staging report path.

    The canonical stock-primary shortlist is treated as research discovery, not execution
    authority. Every actionable lifecycle row remains qualifying even when optional ORATS
    enrichment is unavailable. Pine/risk gates are not invented; the staging prospect board
    represents them as ENTRY_WATCH research until later evidence exists.
    """

    SHORTLIST_KEY = "ovtlyr/shortlist/latest/shortlist.json"
    DEFAULT_LATEST_PREFIX = "daily-alpha/outputs/latest"
    ACTIONABLE_LIFECYCLES = frozenset(
        {"NEW_BUY", "EMERGING", "LEADER", "ENTRY_WATCH", "RE_ENTRY"}
    )

    def __init__(self, *, s3_client: Any, bucket: str) -> None:
        self.s3 = s3_client
        self.bucket = str(bucket or "").strip()
        if not self.bucket:
            raise ProspectStagingRuntimeError("PROSPECT_STAGING_BUCKET_REQUIRED")

    def prepare(
        self,
        *,
        history_prefix: str,
        as_of,
    ) -> PreparedProspectStagingRuntime:
        normalized_history = str(history_prefix or "").strip().strip("/")
        if not normalized_history:
            raise ProspectStagingRuntimeError("PROSPECT_HISTORY_PREFIX_REQUIRED")

        shortlist_bytes = self._read(self.SHORTLIST_KEY)
        try:
            raw_rows = json.loads(shortlist_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProspectStagingRuntimeError("PROSPECT_SHORTLIST_JSON_INVALID") from exc
        if not isinstance(raw_rows, list):
            raise ProspectStagingRuntimeError("PROSPECT_SHORTLIST_MUST_BE_ARRAY")

        assessments = tuple(
            _assessment_from_shortlist_row(raw)
            for raw in raw_rows
            if isinstance(raw, Mapping)
        )
        source_revision = "S3_SHORTLIST_SHA256:" + hashlib.sha256(shortlist_bytes).hexdigest()
        board = build_prospect_opportunity_board(
            items=assessments,
            as_of=as_of,
            source_revision=source_revision,
        )
        outputs = build_all_v1_prospect_outputs(board)

        latest_prefix = self.DEFAULT_LATEST_PREFIX
        newsletter_key = f"{latest_prefix}/newsletter.html"
        current_newsletter = self._read(newsletter_key)
        try:
            current_html = current_newsletter.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProspectStagingRuntimeError("PROSPECT_BASE_NEWSLETTER_INVALID_UTF8") from exc
        newsletter_html = _inject_prospect_section(current_html, board)

        standalone = render_prospect_newsletter_html(board)
        artifacts: dict[str, tuple[bytes, str]] = {
            "prospect_opportunity_board.json": (
                _json_bytes(board.to_dict()),
                "application/json",
            ),
            "prospect_newsletter.json": (
                _json_bytes(_output_for(outputs, ProspectOutputChannel.NEWSLETTER).to_dict()),
                "application/json",
            ),
            "prospect_dashboard.json": (
                _json_bytes(_output_for(outputs, ProspectOutputChannel.DASHBOARD).to_dict()),
                "application/json",
            ),
            "prospect_api.json": (
                _json_bytes(_output_for(outputs, ProspectOutputChannel.API).to_dict()),
                "application/json",
            ),
            "prospect_newsletter.html": (
                standalone.encode("utf-8"),
                "text/html; charset=utf-8",
            ),
        }

        published: dict[str, str] = {}
        self._write(
            newsletter_key,
            newsletter_html.encode("utf-8"),
            "text/html; charset=utf-8",
        )
        self._write(
            f"{normalized_history}/newsletter.html",
            newsletter_html.encode("utf-8"),
            "text/html; charset=utf-8",
        )
        published["newsletter.html"] = newsletter_key

        for name, (body, content_type) in artifacts.items():
            latest_key = f"{latest_prefix}/{name}"
            history_key = f"{normalized_history}/{name}"
            self._write(latest_key, body, content_type)
            self._write(history_key, body, content_type)
            published[name] = latest_key

        return PreparedProspectStagingRuntime(
            board=board,
            outputs=outputs,
            newsletter_html=newsletter_html,
            history_prefix=normalized_history,
            latest_prefix=latest_prefix,
            published=published,
        )

    def finalize_delivery(
        self,
        prepared: PreparedProspectStagingRuntime,
        *,
        delivery_contract_validated: bool,
    ) -> ProspectInitialRolloutGate:
        gate = evaluate_prospect_initial_rollout_gate(
            board=prepared.board,
            outputs=prepared.outputs,
            newsletter_html=prepared.newsletter_html,
            delivery_contract_validated=delivery_contract_validated,
        )
        payload = asdict(gate)
        payload["ready"] = gate.ready
        payload["trading_authorized"] = False
        payload["live_trading_enabled"] = False
        body = _json_bytes(payload)
        self._write(
            f"{prepared.latest_prefix}/prospect_launch_gate.json",
            body,
            "application/json",
        )
        self._write(
            f"{prepared.history_prefix}/prospect_launch_gate.json",
            body,
            "application/json",
        )
        return gate

    def _read(self, key: str) -> bytes:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"].read()
        except Exception as exc:
            raise ProspectStagingRuntimeError(f"PROSPECT_S3_READ_FAILED:{key}") from exc
        if not isinstance(body, (bytes, bytearray)):
            raise ProspectStagingRuntimeError(f"PROSPECT_S3_BODY_INVALID:{key}")
        return bytes(body)

    def _write(self, key: str, body: bytes, content_type: str) -> None:
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except Exception as exc:
            raise ProspectStagingRuntimeError(f"PROSPECT_S3_WRITE_FAILED:{key}") from exc


def _assessment_from_shortlist_row(raw: Mapping[str, Any]) -> CandidateAssessment:
    symbol = str(raw.get("symbol") or "").strip().upper()
    if not symbol:
        raise ProspectStagingRuntimeError("PROSPECT_SHORTLIST_SYMBOL_REQUIRED")
    lifecycle = str(raw.get("ovtlyr_status") or "UNKNOWN").strip().upper()
    qualifying = lifecycle in AwsProspectStagingRuntimePublisher.ACTIONABLE_LIFECYCLES
    bucket = CandidateBucket.ENTRY_WATCH if qualifying else CandidateBucket.NO_TRADE

    optionable_value = raw.get("optionable")
    optionable = optionable_value if isinstance(optionable_value, bool) else None
    selected_expiration = str(raw.get("selected_expiration") or "").strip()
    selected_volume = _integer(raw.get("selected_volume"), default=0)
    selected_open_interest = _integer(raw.get("selected_open_interest"), default=0)
    unusual = bool(
        selected_open_interest > 0
        and selected_volume / selected_open_interest >= 1.0
    )

    orats_status = str(raw.get("orats_status") or "SOURCE_UNAVAILABLE").strip().upper()
    orats_reason = str(raw.get("orats_reason") or "RESEARCH_ONLY").strip()
    fallback_reason = "STOCK_PRIMARY_RESEARCH_ONLY"
    if orats_status == "DATA_ERROR":
        fallback_reason += ":ORATS_NONBLOCKING_DATA_ERROR"
    elif orats_reason:
        fallback_reason += f":{orats_reason}"

    preferred_expression = "OPTION" if selected_expiration else "STOCK"
    return CandidateAssessment(
        symbol=symbol,
        ovtlyr_status=lifecycle,
        bucket=bucket,
        score=_number(raw.get("score"), default=0.0),
        instrument_selected=preferred_expression,
        fallback_reason=fallback_reason,
        sector=str(raw.get("sector") or "UNKNOWN").strip() or "UNKNOWN",
        sector_net_score=_integer(raw.get("sector_net_score"), default=0),
        pine_entry=False,
        risk_gate_passed=False,
        optionable=optionable,
        selected_expiration=selected_expiration,
        selected_strike=_number(raw.get("selected_strike"), default=0.0),
        selected_delta=_optional_number(raw.get("selected_delta")),
        selected_spread_pct=_optional_number(raw.get("selected_spread_pct")),
        unusual_options_activity=unusual,
    )


def _inject_prospect_section(html: str, board: ProspectOpportunityBoard) -> str:
    if "<main>" not in html:
        raise ProspectStagingRuntimeError("PROSPECT_BASE_NEWSLETTER_MAIN_MISSING")
    if 'class="prospect-opportunity-board"' in html:
        raise ProspectStagingRuntimeError("PROSPECT_SECTION_ALREADY_PRESENT")

    top_cards = "".join(
        '<article class="candidate-card prospect-top-pick">'
        f'<div class="section-kicker">RANK #{item.rank}</div>'
        f'<h3>{escape(item.symbol)}</h3>'
        f'<p><strong>{escape(item.lifecycle_status)}</strong> · Score {item.score:.2f}</p>'
        f'<p>{escape(item.sector)} · research expression {escape(item.instrument_selected)}</p>'
        "</article>"
        for item in board.top_picks
    )
    if not top_cards:
        top_cards = (
            '<p class="section-note">No opportunities currently meet the governed '
            "qualification gates.</p>"
        )

    additional_rows = "".join(
        "<tr>"
        f"<td>{item.rank}</td>"
        f"<td><strong>{escape(item.symbol)}</strong></td>"
        f"<td>{escape(item.lifecycle_status)}</td>"
        f"<td>{item.score:.2f}</td>"
        f"<td>{escape(item.sector)}</td>"
        f"<td>{escape(item.instrument_selected)}</td>"
        "</tr>"
        for item in board.additional_opportunities
    )
    if additional_rows:
        additional = (
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Rank</th><th>Symbol</th><th>Status</th><th>Score</th>"
            "<th>Sector</th><th>Expression</th>"
            f"</tr></thead><tbody>{additional_rows}</tbody></table></div>"
        )
    else:
        additional = (
            '<p class="section-note">No additional qualifying opportunities beyond the '
            "featured set.</p>"
        )

    canonical_ids = ",".join(item.candidate_id for item in board.opportunities)
    section = (
        '<section class="prospect-opportunity-board report-section" '
        f'data-board-id="{escape(board.board_id)}" '
        f'data-total-qualifying="{board.total_qualifying}" '
        f'data-canonical-candidate-ids="{escape(canonical_ids)}">'
        '<div class="section-kicker">CONVEXRIDGE OPPORTUNITY BOARD</div>'
        "<h2>Top 3 ConvexRidge Picks</h2>"
        '<p class="section-note">Highest-ranked governed research/model signals receive '
        "priority presentation. Every other qualifying setup remains available below; Top 3 "
        "is not a truncation rule.</p>"
        f'<div class="card-grid">{top_cards}</div>'
        f"<h3>Additional Qualified Opportunities ({len(board.additional_opportunities)})</h3>"
        f"{additional}"
        '<p class="section-note">Governed research/model signals only; not personalized '
        "advice. Portfolio recommendation authority: false. Trading authorization: false. "
        "Live trading: false.</p>"
        "</section>"
    )
    return html.replace("<main>", f"<main>{section}", 1)


def _output_for(
    outputs: tuple[ProspectOpportunityOutput, ...],
    channel: ProspectOutputChannel,
) -> ProspectOpportunityOutput:
    for output in outputs:
        if output.channel is channel:
            return output
    raise ProspectStagingRuntimeError(f"PROSPECT_OUTPUT_MISSING:{channel.value}")


def _json_bytes(payload: object) -> bytes:
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    return serialized.encode("utf-8")


def _number(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: object, *, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


__all__ = [
    "AwsProspectStagingRuntimePublisher",
    "PreparedProspectStagingRuntime",
    "ProspectStagingRuntimeError",
]
