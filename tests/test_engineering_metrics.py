from __future__ import annotations

from pathlib import Path

import pytest

from daily_alpha.engineering_metrics import (
    classify_path,
    collect_engineering_metrics,
    render_markdown,
)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_classify_path_separates_management_categories() -> None:
    assert classify_path("src/daily_alpha/engine.py") == "source"
    assert classify_path("lambda_handlers/engine.py") == "source"
    assert classify_path("staging_lambda_handlers/engine.py") == "source"
    assert classify_path("tests/test_engine.py") == "tests"
    assert classify_path("infra/aws/template.json") == "infrastructure_ci"
    assert classify_path(".github/workflows/test.yml") == "infrastructure_ci"
    assert classify_path("scripts/inspect.py") == "scripts"
    assert classify_path("tradingview/strategy.pine") == "tradingview"
    assert classify_path("docs/runbook.md") == "documentation"
    assert classify_path("README.md") == "documentation"
    assert classify_path("config/risk.json") == "configuration"
    assert classify_path("pyproject.toml") == "configuration"


def test_collect_metrics_counts_only_supported_tracked_text(tmp_path: Path) -> None:
    files = {
        "src/daily_alpha/engine.py": "x = 1\n\n# retained comment\n",
        "tests/test_engine.py": "def test_x():\n    assert True\n",
        ".github/workflows/test.yml": "name: test\n\njobs: {}\n",
        "tradingview/strategy.pine": "//@version=6\nstrategy('x')\n",
        "config/risk.json": "{\n  \"risk\": false\n}\n",
        "docs/runbook.md": "# Runbook\n\nSafe operations.\n",
        "data/raw/provider.csv": "should,not,count\n1,2\n",
        "tradingview/source.pine.gz.b64": "opaque-generated-payload\n",
        "image.png": "not-supported\n",
    }
    for relative, text in files.items():
        _write(tmp_path, relative, text)

    report = collect_engineering_metrics(
        tmp_path,
        tracked_paths=files,
        commit_sha="ABC123",
    )

    by_path = {metric.path: metric for metric in report.files}
    assert set(by_path) == {
        "src/daily_alpha/engine.py",
        "tests/test_engine.py",
        ".github/workflows/test.yml",
        "tradingview/strategy.pine",
        "config/risk.json",
        "docs/runbook.md",
    }
    assert by_path["src/daily_alpha/engine.py"].physical_lines == 3
    assert by_path["src/daily_alpha/engine.py"].nonblank_lines == 2
    assert report.commit_sha == "abc123"
    assert report.developed_nonblank_lines == 13
    assert report.documentation_nonblank_lines == 2
    assert report.total_nonblank_lines == 15
    assert report.trading_authorized is False
    assert report.live_trading_enabled is False

    payload = report.as_dict()
    assert payload["schema"] == "DAILY_ALPHA_ENGINEERING_METRICS_V1"
    assert payload["definitions"]["documentation_excluded_from_developed_total"] is True
    assert payload["definitions"]["raw_data_and_generated_base64_excluded"] is True
    assert payload["categories"]["source"]["nonblank_lines"] == 2
    assert payload["languages"]["Python"]["files"] == 2


def test_report_identity_is_stable_under_tracked_path_order(tmp_path: Path) -> None:
    _write(tmp_path, "src/daily_alpha/a.py", "a = 1\n")
    _write(tmp_path, "tests/test_a.py", "assert True\n")

    first = collect_engineering_metrics(
        tmp_path,
        tracked_paths=("tests/test_a.py", "src/daily_alpha/a.py"),
        commit_sha="deadbeef",
    )
    second = collect_engineering_metrics(
        tmp_path,
        tracked_paths=("src/daily_alpha/a.py", "tests/test_a.py"),
        commit_sha="deadbeef",
    )

    assert first.files == second.files
    assert first.report_id == second.report_id


def test_markdown_summary_states_scope_and_false_authority(tmp_path: Path) -> None:
    _write(tmp_path, "src/daily_alpha/a.py", "a = 1\n")
    report = collect_engineering_metrics(
        tmp_path,
        tracked_paths=("src/daily_alpha/a.py",),
        commit_sha="deadbeef",
    )

    rendered = render_markdown(report)

    assert "Developed nonblank lines: **1**" in rendered
    assert "Documentation is excluded" in rendered
    assert "`trading_authorized=false`" in rendered
    assert "`live_trading_enabled=false`" in rendered


def test_invalid_or_missing_tracked_paths_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ENGINEERING_METRICS_PATH_INVALID"):
        collect_engineering_metrics(
            tmp_path,
            tracked_paths=("../outside.py",),
            commit_sha="deadbeef",
        )

    with pytest.raises(ValueError, match="ENGINEERING_METRICS_TRACKED_FILE_MISSING"):
        collect_engineering_metrics(
            tmp_path,
            tracked_paths=("src/daily_alpha/missing.py",),
            commit_sha="deadbeef",
        )


def test_commit_sha_is_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ENGINEERING_METRICS_COMMIT_SHA_REQUIRED"):
        collect_engineering_metrics(tmp_path, tracked_paths=(), commit_sha="   ")
