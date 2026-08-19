"""Versioned company/brand/product/domain dictionary for behavioral research."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .behavioral_change import BehavioralEntity


def load_behavioral_entities(path: str | Path) -> tuple[BehavioralEntity, ...]:
    """Load and validate the versioned behavioral entity dictionary."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("behavioral entity dictionary must be an object")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise ValueError("behavioral entity dictionary version is required")
    raw_entities = payload.get("entities")
    if not isinstance(raw_entities, list) or not raw_entities:
        raise ValueError("behavioral entity dictionary must contain entities")

    entities: list[BehavioralEntity] = []
    entity_ids: set[str] = set()
    tickers: set[str] = set()
    for raw in raw_entities:
        if not isinstance(raw, dict):
            raise ValueError("behavioral entity entries must be objects")
        entity = _entity_from_dict(raw, version=version)
        ticker = entity.ticker.upper()
        if entity.entity_id in entity_ids:
            raise ValueError(f"duplicate behavioral entity_id: {entity.entity_id}")
        if ticker in tickers:
            raise ValueError(f"duplicate behavioral ticker: {ticker}")
        entity_ids.add(entity.entity_id)
        tickers.add(ticker)
        entities.append(entity)
    return tuple(sorted(entities, key=lambda item: item.ticker.upper()))


def _entity_from_dict(raw: dict[str, Any], *, version: str) -> BehavioralEntity:
    ticker = str(raw.get("ticker") or "").strip().upper()
    entity_id = str(raw.get("entity_id") or f"{ticker}:{version}").strip()
    return BehavioralEntity(
        entity_id=entity_id,
        ticker=ticker,
        version=version,
        company_name=str(raw.get("company_name") or "").strip(),
        aliases=_strings(raw.get("aliases")),
        brands=_strings(raw.get("brands")),
        products=_strings(raw.get("products")),
        apps=_strings(raw.get("apps")),
        domains=_strings(raw.get("domains")),
        technologies=_strings(raw.get("technologies")),
    )


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("behavioral entity list fields must be arrays")
    return tuple(str(item).strip() for item in value if str(item).strip())
