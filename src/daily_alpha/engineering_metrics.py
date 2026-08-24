"""Deterministic engineering-footprint metrics for the tracked repository state.

This module measures tracked text files only. It intentionally separates source,
tests, infrastructure/CI, scripts, TradingView, configuration, and documentation so
management reporting cannot inflate executable engineering footprint with raw data or
opaque generated payloads.

The metrics are descriptive engineering evidence only. They do not grant PAPER or
live-trading authority and make no claim about investment performance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_SCHEMA = "DAILY_ALPHA_ENGINEERING_METRICS_V1"

_LANGUAGE_BY_SUFFIX = {
    ".cfg": "Config",
    ".css": "CSS",
    ".html": "HTML",
    ".ini": "Config",
    ".js": "JavaScript",
    ".json": "JSON",
    ".md": "Markdown",
    ".pine": "Pine Script",
    ".py": "Python",
    ".sh": "Shell",
    ".sql": "SQL",
    ".tf": "Terraform",
    ".toml": "TOML",
    ".ts": "TypeScript",
    ".txt": "Text",
    ".yaml": "YAML",
    ".yml": "YAML",
}

_DEVELOPED_CATEGORIES = frozenset(
    {
        "source",
        "tests",
        "infrastructure_ci",
        "scripts",
        "tradingview",
        "configuration",
    }
)

_EXCLUDED_PREFIXES = (
    "data/",
    ".git/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".venv/",
    "venv/",
)

_EXCLUDED_SUFFIXES = (".b64", ".gz.b64")


@dataclass(frozen=True, slots=True)
class FileMetric:
    """One tracked text file's deterministic line-count evidence."""

    path: str
    category: str
    language: str
    physical_lines: int
    nonblank_lines: int

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "category": self.category,
            "language": self.language,
            "physical_lines": self.physical_lines,
            "nonblank_lines": self.nonblank_lines,
        }


@dataclass(frozen=True, slots=True)
class EngineeringMetricsReport:
    """Exact repository-footprint report tied to one Git commit."""

    commit_sha: str
    files: tuple[FileMetric, ...]
    report_id: str
    trading_authorized: bool = False
    live_trading_enabled: bool = False

    @property
    def developed_nonblank_lines(self) -> int:
        return sum(
            metric.nonblank_lines
            for metric in self.files
            if metric.category in _DEVELOPED_CATEGORIES
        )

    @property
    def documentation_nonblank_lines(self) -> int:
        return sum(
            metric.nonblank_lines for metric in self.files if metric.category == "documentation"
        )

    @property
    def total_nonblank_lines(self) -> int:
        return sum(metric.nonblank_lines for metric in self.files)

    @property
    def total_physical_lines(self) -> int:
        return sum(metric.physical_lines for metric in self.files)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "commit_sha": self.commit_sha,
            "report_id": self.report_id,
            "scope": "git_tracked_supported_text_files",
            "definitions": {
                "physical_lines": "text.splitlines() count",
                "nonblank_lines": "physical lines containing non-whitespace characters",
                "developed_nonblank_lines": (
                    "source + tests + infrastructure_ci + scripts + tradingview + configuration"
                ),
                "documentation_excluded_from_developed_total": True,
                "raw_data_and_generated_base64_excluded": True,
            },
            "totals": {
                "files": len(self.files),
                "physical_lines": self.total_physical_lines,
                "nonblank_lines": self.total_nonblank_lines,
                "developed_nonblank_lines": self.developed_nonblank_lines,
                "documentation_nonblank_lines": self.documentation_nonblank_lines,
            },
            "categories": _aggregate(self.files, "category"),
            "languages": _aggregate(self.files, "language"),
            "files": [metric.as_dict() for metric in self.files],
            "trading_authorized": self.trading_authorized,
            "live_trading_enabled": self.live_trading_enabled,
        }


def collect_engineering_metrics(
    repo_root: Path | str,
    *,
    tracked_paths: Iterable[str] | None = None,
    commit_sha: str | None = None,
) -> EngineeringMetricsReport:
    """Collect deterministic line metrics from tracked, supported text files."""

    root = Path(repo_root).resolve()
    if tracked_paths is None:
        tracked_paths = _git_tracked_paths(root)
    if commit_sha is None:
        commit_sha = _git_head_sha(root)

    normalized_sha = commit_sha.strip().lower()
    if not normalized_sha:
        raise ValueError("ENGINEERING_METRICS_COMMIT_SHA_REQUIRED")

    metrics: list[FileMetric] = []
    for raw_path in sorted(set(tracked_paths)):
        relative_path = _normalize_relative_path(raw_path)
        if not _is_supported(relative_path):
            continue

        path = root / relative_path
        if not path.is_file():
            raise ValueError(f"ENGINEERING_METRICS_TRACKED_FILE_MISSING:{relative_path}")

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"ENGINEERING_METRICS_NOT_UTF8:{relative_path}") from exc

        lines = text.splitlines()
        metrics.append(
            FileMetric(
                path=relative_path,
                category=classify_path(relative_path),
                language=_language_for(relative_path),
                physical_lines=len(lines),
                nonblank_lines=sum(1 for line in lines if line.strip()),
            )
        )

    file_tuple = tuple(metrics)
    report_id = _report_id(normalized_sha, file_tuple)
    return EngineeringMetricsReport(
        commit_sha=normalized_sha,
        files=file_tuple,
        report_id=report_id,
    )


def classify_path(path: str) -> str:
    """Map a repository-relative path to one management reporting category."""

    normalized = _normalize_relative_path(path)
    pure = PurePosixPath(normalized)
    parts = pure.parts
    first = parts[0] if parts else ""

    if first == "tests":
        return "tests"
    if first in {"src", "lambda_handlers", "staging_lambda_handlers"}:
        return "source"
    if first == "infra" or parts[:2] == (".github", "workflows"):
        return "infrastructure_ci"
    if first == "scripts":
        return "scripts"
    if first == "tradingview":
        return "tradingview"
    if first == "docs" or normalized == "README.md":
        return "documentation"
    if first == "config" or normalized in {"pyproject.toml", ".env.example"}:
        return "configuration"
    return "other"


def render_markdown(report: EngineeringMetricsReport) -> str:
    """Render a compact GitHub-summary view without changing metric semantics."""

    rows = [
        "# Daily Alpha Engineering Metrics",
        "",
        f"- Commit: `{report.commit_sha}`",
        f"- Report ID: `{report.report_id}`",
        f"- Developed nonblank lines: **{report.developed_nonblank_lines:,}**",
        f"- Documentation nonblank lines: **{report.documentation_nonblank_lines:,}**",
        f"- Total tracked supported files: **{len(report.files):,}**",
        "",
        "| Category | Files | Physical lines | Nonblank lines |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, values in _aggregate(report.files, "category").items():
        rows.append(
            f"| {category} | {values['files']:,} | {values['physical_lines']:,} | "
            f"{values['nonblank_lines']:,} |"
        )
    rows.extend(
        [
            "",
            (
                "> Documentation is excluded from the developed-line total. Raw data and "
                "generated/base64 payloads are excluded from this metric."
            ),
            "",
            "`trading_authorized=false` · `live_trading_enabled=false`",
        ]
    )
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the Daily Alpha engineering footprint")
    parser.add_argument("--repo-root", default=".", help="Repository root; default: current directory")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)

    report = collect_engineering_metrics(args.repo_root)
    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


def _aggregate(files: Iterable[FileMetric], field: str) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(
        lambda: {"files": 0, "physical_lines": 0, "nonblank_lines": 0}
    )
    for metric in files:
        key = getattr(metric, field)
        result[key]["files"] += 1
        result[key]["physical_lines"] += metric.physical_lines
        result[key]["nonblank_lines"] += metric.nonblank_lines
    return {key: result[key] for key in sorted(result)}


def _is_supported(path: str) -> bool:
    lowered = path.lower()
    if lowered.startswith(_EXCLUDED_PREFIXES):
        return False
    if lowered.endswith(_EXCLUDED_SUFFIXES):
        return False
    if path == ".env.example":
        return True
    return PurePosixPath(path).suffix.lower() in _LANGUAGE_BY_SUFFIX


def _language_for(path: str) -> str:
    if path == ".env.example":
        return "Config"
    suffix = PurePosixPath(path).suffix.lower()
    try:
        return _LANGUAGE_BY_SUFFIX[suffix]
    except KeyError as exc:
        raise ValueError(f"ENGINEERING_METRICS_LANGUAGE_UNSUPPORTED:{path}") from exc


def _normalize_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"ENGINEERING_METRICS_PATH_INVALID:{path}")
    return pure.as_posix()


def _git_tracked_paths(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    decoded = result.stdout.decode("utf-8")
    return tuple(path for path in decoded.split("\0") if path)


def _git_head_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _report_id(commit_sha: str, files: tuple[FileMetric, ...]) -> str:
    payload = {
        "schema": _SCHEMA,
        "commit_sha": commit_sha,
        "files": [metric.as_dict() for metric in files],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
