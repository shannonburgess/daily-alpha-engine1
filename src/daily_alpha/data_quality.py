"""Deterministic data-quality, lineage, and run-health records."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


class DataStatus(StrEnum):
    DATA_OK = "DATA_OK"
    PARTIAL_DATA = "PARTIAL_DATA"
    STALE_DATA = "STALE_DATA"
    DATA_ERROR = "DATA_ERROR"
    DUPLICATE_DATA = "DUPLICATE_DATA"


class FailureCode(StrEnum):
    DUPLICATE_FILE = "DUPLICATE_FILE"
    EMPTY_FILE = "EMPTY_FILE"
    MISSING_COLUMNS = "MISSING_COLUMNS"
    NO_VALID_ROWS = "NO_VALID_ROWS"
    DUPLICATE_SYMBOLS = "DUPLICATE_SYMBOLS"
    STALE_SOURCE = "STALE_SOURCE"
    FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
    INVALID_ENCODING = "INVALID_ENCODING"


@dataclass(frozen=True)
class DataQualityResult:
    source: str
    file_name: str
    content_hash: str
    as_of: str
    received_at: str
    status: DataStatus
    failure_codes: tuple[FailureCode, ...]
    total_rows: int
    valid_rows: int
    duplicate_symbols: tuple[str, ...] = ()

    @property
    def permits_decisions(self) -> bool:
        return self.status == DataStatus.DATA_OK

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["failure_codes"] = [code.value for code in self.failure_codes]
        return payload


class DataQualityGate:
    def __init__(self, *, max_age: timedelta = timedelta(hours=36)) -> None:
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        self.max_age = max_age
        self._seen_hashes: set[str] = set()

    def assess_csv(
        self,
        *,
        source: str,
        file_name: str,
        content: bytes,
        as_of: datetime,
        required_columns: frozenset[str],
        symbol_column: str = "symbol",
        received_at: datetime | None = None,
    ) -> DataQualityResult:
        now = received_at or datetime.now(UTC)
        if now.tzinfo is None or as_of.tzinfo is None:
            raise ValueError("as_of and received_at must be timezone-aware")
        content_hash = hashlib.sha256(content).hexdigest()
        failures: list[FailureCode] = []
        if content_hash in self._seen_hashes:
            failures.append(FailureCode.DUPLICATE_FILE)
            return self._result(
                source, file_name, content_hash, as_of, now, DataStatus.DUPLICATE_DATA, failures
            )
        self._seen_hashes.add(content_hash)

        if not content:
            failures.append(FailureCode.EMPTY_FILE)
            return self._result(
                source, file_name, content_hash, as_of, now, DataStatus.DATA_ERROR, failures
            )
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            failures.append(FailureCode.INVALID_ENCODING)
            return self._result(
                source, file_name, content_hash, as_of, now, DataStatus.DATA_ERROR, failures
            )

        reader = csv.DictReader(io.StringIO(text))
        columns = frozenset((name or "").strip().lower() for name in (reader.fieldnames or []))
        normalized_required = frozenset(name.strip().lower() for name in required_columns)
        if not normalized_required.issubset(columns):
            failures.append(FailureCode.MISSING_COLUMNS)
            return self._result(
                source, file_name, content_hash, as_of, now, DataStatus.DATA_ERROR, failures
            )

        rows = list(reader)
        symbols = [str(row.get(symbol_column, "")).strip().upper() for row in rows]
        valid_symbols = [symbol for symbol in symbols if symbol]
        duplicates = tuple(sorted({symbol for symbol in valid_symbols if valid_symbols.count(symbol) > 1}))
        if not valid_symbols:
            failures.append(FailureCode.NO_VALID_ROWS)
        if duplicates:
            failures.append(FailureCode.DUPLICATE_SYMBOLS)
        age = now - as_of
        if age < -timedelta(minutes=1):
            failures.append(FailureCode.FUTURE_TIMESTAMP)
        elif age > self.max_age:
            failures.append(FailureCode.STALE_SOURCE)

        status = self._status(failures)
        return DataQualityResult(
            source=source,
            file_name=file_name,
            content_hash=content_hash,
            as_of=as_of.isoformat(),
            received_at=now.isoformat(),
            status=status,
            failure_codes=tuple(failures),
            total_rows=len(rows),
            valid_rows=len(valid_symbols),
            duplicate_symbols=duplicates,
        )

    @staticmethod
    def _status(failures: list[FailureCode]) -> DataStatus:
        if FailureCode.STALE_SOURCE in failures:
            return DataStatus.STALE_DATA
        if any(
            code in failures
            for code in (
                FailureCode.EMPTY_FILE,
                FailureCode.MISSING_COLUMNS,
                FailureCode.NO_VALID_ROWS,
                FailureCode.FUTURE_TIMESTAMP,
                FailureCode.INVALID_ENCODING,
            )
        ):
            return DataStatus.DATA_ERROR
        if failures:
            return DataStatus.PARTIAL_DATA
        return DataStatus.DATA_OK

    @staticmethod
    def _result(
        source: str,
        file_name: str,
        content_hash: str,
        as_of: datetime,
        received_at: datetime,
        status: DataStatus,
        failures: list[FailureCode],
    ) -> DataQualityResult:
        return DataQualityResult(
            source,
            file_name,
            content_hash,
            as_of.isoformat(),
            received_at.isoformat(),
            status,
            tuple(failures),
            0,
            0,
        )


@dataclass(frozen=True)
class RunHealth:
    run_id: str
    schedule_name: str
    scheduled_for: str
    started_at: str
    completed_at: str
    data_status: DataStatus
    processed_records: int
    rejected_records: int
    message: str = ""

    @property
    def healthy(self) -> bool:
        return self.data_status == DataStatus.DATA_OK and self.rejected_records == 0
