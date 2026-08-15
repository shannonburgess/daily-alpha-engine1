"""Append-only JSON Lines audit output."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Decision


def append_decision(path: str | Path, decision: Decision) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(decision.to_dict(), sort_keys=True) + "\n")
