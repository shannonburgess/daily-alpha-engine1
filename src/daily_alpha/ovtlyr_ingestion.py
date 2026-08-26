"""Fail-closed ingestion and deterministic transformation of OVTLYR exports."""

from __future__ import annotations

import csv
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .ovtlyr import (
    ClassifiedRecord,
    OvtlyrRecord,
    SectorRotation,
    compare_universes,
    load_ovtlyr_csv,
    summarize_sector_rotation,
)
from .ovtlyr_report import ArchiveResult, archive_daily_run

EXPORT_NAME = re.compile(r"^OVTLYR_(\d{4}-\d{2}-\d{2})\.csv$")
REQUIRED_COLUMNS = frozenset(
    {
        "symbol",
        "company_name",
        "sector_index",
        "industry",
        "last_close_price_($)",
        "fear_and_greed_heatmap_value",
        "current_signal_status",
        "signal_start_date",
        "overlay",
        "overlay_start_date",
        "30_day_avg_volume",
        "ovtlyr_signal_return_(%)",
        "capital_efficiency",
        "price_change",
        "fear_and_greed_heatmap_direction",
        "oc_channel",
        "unusual_news_activity_(una)",
        "top_mentions_today_(tmt)",
        "ovtlyr_nine",
        "sector_relative_greed",
        "partial_data_stocks",
        "signal_type",
    }
)
SIGNALS = {"BUY", "SELL"}
OVERLAYS = {"UPTREND", "DOWNTREND", "NEUTRAL"}
HEATMAP_DIRECTIONS = {"MOVING UP", "MOVING DOWN"}


class OvtlyrIngestionError(ValueError):
    """The source export failed a deterministic ingestion contract."""


@dataclass(frozen=True)
class IngestedOvtlyrExport:
    path: Path
    source_date: date
    sha256: str
    header_count: int
    row_count: int
    partial_row_count: int
    records: tuple[OvtlyrRecord, ...]


@dataclass(frozen=True)
class OvtlyrTransformation:
    previous: IngestedOvtlyrExport
    current: IngestedOvtlyrExport
    classified: tuple[ClassifiedRecord, ...]
    sectors: tuple[SectorRotation, ...]
    trading_authorized: bool = False
    live_trading_enabled: bool = False


def ingest_ovtlyr_export(path: str | Path) -> IngestedOvtlyrExport:
    """Validate one provider export before converting it to engine records."""
    source = Path(path)
    source_date = _source_date(source)
    payload = source.read_bytes()

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise OvtlyrIngestionError("OVTLYR_HEADER_MISSING")
        normalized = [_normalize(value) for value in fieldnames]
        if len(normalized) != len(set(normalized)):
            raise OvtlyrIngestionError("OVTLYR_DUPLICATE_HEADER")
        missing = sorted(REQUIRED_COLUMNS.difference(normalized))
        if missing:
            raise OvtlyrIngestionError(
                f"OVTLYR_REQUIRED_COLUMNS_MISSING:{','.join(missing)}"
            )
        columns = dict(zip(normalized, fieldnames, strict=True))
        seen: set[str] = set()
        rows = 0
        partial_rows = 0
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise OvtlyrIngestionError(f"OVTLYR_MALFORMED_ROW:{line_number}")
            symbol = _cell(row, columns, "symbol").upper()
            if not symbol:
                raise OvtlyrIngestionError(f"OVTLYR_SYMBOL_MISSING:{line_number}")
            if symbol in seen:
                raise OvtlyrIngestionError(f"OVTLYR_DUPLICATE_SYMBOL:{symbol}")
            seen.add(symbol)
            rows += 1

            partial = _strict_boolean(
                _cell(row, columns, "partial_data_stocks"), line_number
            )
            signal = _cell(row, columns, "current_signal_status").upper()
            signal_date = _cell(row, columns, "signal_start_date")
            if partial:
                partial_rows += 1
                if signal or signal_date:
                    raise OvtlyrIngestionError(
                        f"OVTLYR_PARTIAL_ROW_HAS_SIGNAL:{line_number}"
                    )
            else:
                if signal not in SIGNALS:
                    raise OvtlyrIngestionError(
                        f"OVTLYR_SIGNAL_INVALID:{line_number}:{signal or 'BLANK'}"
                    )
                parsed_signal_date = _provider_date(signal_date, line_number)
                if parsed_signal_date > source_date:
                    raise OvtlyrIngestionError(
                        f"OVTLYR_SIGNAL_DATE_IN_FUTURE:{line_number}"
                    )

            _required_text(row, columns, "sector_index", line_number)
            _required_text(row, columns, "industry", line_number)
            _required_text(row, columns, "company_name", line_number)
            if _cell(row, columns, "signal_type").upper() != "SWING":
                raise OvtlyrIngestionError(f"OVTLYR_SIGNAL_TYPE_INVALID:{line_number}")
            if _cell(row, columns, "overlay").upper() not in OVERLAYS:
                raise OvtlyrIngestionError(f"OVTLYR_OVERLAY_INVALID:{line_number}")

            direction = _cell(row, columns, "fear_and_greed_heatmap_direction").upper()
            if not partial and direction and direction not in HEATMAP_DIRECTIONS:
                raise OvtlyrIngestionError(
                    f"OVTLYR_HEATMAP_DIRECTION_INVALID:{line_number}"
                )
            if partial and direction:
                raise OvtlyrIngestionError(
                    f"OVTLYR_PARTIAL_ROW_HAS_DIRECTION:{line_number}"
                )

            _finite_number(
                _cell(row, columns, "last_close_price_($)"),
                line_number,
                "PRICE",
                minimum_exclusive=0.0,
            )
            _finite_number(
                _cell(row, columns, "30_day_avg_volume"),
                line_number,
                "AVERAGE_VOLUME",
                minimum=0.0,
            )
            for column, code in (
                ("fear_and_greed_heatmap_value", "HEATMAP_VALUE"),
                ("ovtlyr_signal_return_(%)", "SIGNAL_RETURN"),
                ("capital_efficiency", "CAPITAL_EFFICIENCY"),
                ("price_change", "PRICE_CHANGE"),
            ):
                value = _cell(row, columns, column)
                if value:
                    _finite_number(value, line_number, code)
                elif not partial:
                    raise OvtlyrIngestionError(
                        f"OVTLYR_{code}_MISSING:{line_number}"
                    )

    if rows == 0:
        raise OvtlyrIngestionError("OVTLYR_ROWS_MISSING")
    records = tuple(load_ovtlyr_csv(source))
    if len(records) != rows:
        raise OvtlyrIngestionError("OVTLYR_TRANSFORM_COUNT_MISMATCH")
    return IngestedOvtlyrExport(
        path=source,
        source_date=source_date,
        sha256=hashlib.sha256(payload).hexdigest(),
        header_count=len(fieldnames),
        row_count=rows,
        partial_row_count=partial_rows,
        records=records,
    )


def transform_ovtlyr_exports(
    previous_path: str | Path,
    current_path: str | Path,
) -> OvtlyrTransformation:
    """Validate two point-in-time exports and classify matched-symbol transitions."""
    previous = ingest_ovtlyr_export(previous_path)
    current = ingest_ovtlyr_export(current_path)
    if previous.source_date >= current.source_date:
        raise OvtlyrIngestionError("OVTLYR_BASELINE_NOT_BEFORE_CURRENT")
    classified = tuple(compare_universes(list(previous.records), list(current.records)))
    sectors = tuple(summarize_sector_rotation(list(classified)))
    return OvtlyrTransformation(previous, current, classified, sectors)


def ingest_transform_archive(
    *,
    previous_csv: str | Path,
    current_csv: str | Path,
    history_root: str | Path,
    engine_version: str,
    run_date: str | None = None,
    created_at: datetime | None = None,
) -> tuple[OvtlyrTransformation, ArchiveResult]:
    """Run the governed import/transform/archive flow without trading authority."""
    transformation = transform_ovtlyr_exports(previous_csv, current_csv)
    current_date = transformation.current.source_date.isoformat()
    if run_date is not None and run_date != current_date:
        raise OvtlyrIngestionError("OVTLYR_RUN_DATE_SOURCE_DATE_MISMATCH")
    archive = archive_daily_run(
        history_root=history_root,
        run_date=current_date,
        source_csv=transformation.current.path,
        classified=list(transformation.classified),
        sectors=list(transformation.sectors),
        engine_version=engine_version,
        created_at=created_at,
        manifest_metadata={
            "baseline": {
                "source_date": transformation.previous.source_date.isoformat(),
                "original_filename": transformation.previous.path.name,
                "sha256": transformation.previous.sha256,
                "row_count": transformation.previous.row_count,
            },
            "validation": {
                "contract": "OVTLYR_22_COLUMN_SWING_V1",
                "header_count": transformation.current.header_count,
                "source_row_count": transformation.current.row_count,
                "partial_row_count": transformation.current.partial_row_count,
                "rejected_row_count": 0,
                "transition_method": "MATCHED_SYMBOL_DAY_OVER_DAY",
            },
            "trading_authorized": False,
            "live_trading_enabled": False,
        },
    )
    return transformation, archive


def _source_date(path: Path) -> date:
    match = EXPORT_NAME.fullmatch(path.name)
    if match is None:
        raise OvtlyrIngestionError("OVTLYR_FILENAME_INVALID")
    try:
        return date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise OvtlyrIngestionError("OVTLYR_FILENAME_DATE_INVALID") from exc


def _normalize(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("&", "and")
        .replace("/", "_")
        .replace(" ", "_")
        .replace("-", "_")
    )


def _cell(row: dict[str, str], columns: dict[str, str], column: str) -> str:
    return (row.get(columns[column]) or "").strip()


def _required_text(
    row: dict[str, str], columns: dict[str, str], column: str, line_number: int
) -> str:
    value = _cell(row, columns, column)
    if not value:
        raise OvtlyrIngestionError(
            f"OVTLYR_{column.upper()}_MISSING:{line_number}"
        )
    return value


def _strict_boolean(value: str, line_number: int) -> bool:
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise OvtlyrIngestionError(f"OVTLYR_PARTIAL_FLAG_INVALID:{line_number}")


def _provider_date(value: str, line_number: int) -> date:
    try:
        return datetime.strptime(value, "%b %d, %Y").replace(tzinfo=UTC).date()
    except ValueError as exc:
        raise OvtlyrIngestionError(
            f"OVTLYR_SIGNAL_DATE_INVALID:{line_number}"
        ) from exc


def _finite_number(
    value: str,
    line_number: int,
    code: str,
    *,
    minimum: float | None = None,
    minimum_exclusive: float | None = None,
) -> float:
    if not value:
        raise OvtlyrIngestionError(f"OVTLYR_{code}_MISSING:{line_number}")
    try:
        parsed = float(value.replace(",", "").replace("$", ""))
    except ValueError as exc:
        raise OvtlyrIngestionError(
            f"OVTLYR_{code}_INVALID:{line_number}"
        ) from exc
    if not math.isfinite(parsed):
        raise OvtlyrIngestionError(f"OVTLYR_{code}_NONFINITE:{line_number}")
    if minimum is not None and parsed < minimum:
        raise OvtlyrIngestionError(f"OVTLYR_{code}_OUT_OF_RANGE:{line_number}")
    if minimum_exclusive is not None and parsed <= minimum_exclusive:
        raise OvtlyrIngestionError(f"OVTLYR_{code}_OUT_OF_RANGE:{line_number}")
    return parsed
