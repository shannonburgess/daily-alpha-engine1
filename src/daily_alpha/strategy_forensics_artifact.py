"""Deterministic research artifacts for Daily Alpha strategy forensics.

The writer consumes already-computed forensics diagnostics and model-disagreement
observations. It does not fetch future prices, alter a decision, mutate a paper
ledger, or authorize any trade.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .strategy_forensics import (
    ForensicsDiagnostic,
    ModelDisagreement,
    summarize_forensics,
)


def write_strategy_forensics_artifacts(
    output_dir: str | Path,
    diagnostics: Iterable[ForensicsDiagnostic],
    *,
    disagreements: Iterable[ModelDisagreement] = (),
) -> dict[str, Path]:
    """Write stable JSON/CSV research artifacts without changing strategy state."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    ordered_diagnostics = sorted(
        diagnostics,
        key=lambda item: (
            item.strategy_version,
            item.symbol,
            item.decision,
            item.reason,
            item.classification,
        ),
    )
    ordered_disagreements = sorted(
        disagreements,
        key=lambda item: (
            item.symbol,
            item.champion_version,
            item.challenger_version,
            item.champion_decision,
            item.challenger_decision,
        ),
    )

    payload = {
        "summary": summarize_forensics(ordered_diagnostics),
        "diagnostics": [item.to_dict() for item in ordered_diagnostics],
        "model_disagreements": [item.to_dict() for item in ordered_disagreements],
        "research_only": True,
        "trading_authorized": False,
        "live_trading_enabled": False,
    }

    json_path = destination / "strategy_forensics.json"
    csv_path = destination / "strategy_forensics.csv"
    disagreement_path = destination / "strategy_model_disagreements.json"

    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    rows = [item.to_dict() for item in ordered_diagnostics]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        else:
            handle.write("symbol,strategy_version,decision,reason,classification\n")

    disagreement_path.write_text(
        json.dumps(
            {
                "observations": [item.to_dict() for item in ordered_disagreements],
                "count": len(ordered_disagreements),
                "disagreement_count": sum(
                    item.disagrees for item in ordered_disagreements
                ),
                "research_only": True,
                "trading_authorized": False,
                "live_trading_enabled": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "json": json_path,
        "csv": csv_path,
        "model_disagreements": disagreement_path,
    }
