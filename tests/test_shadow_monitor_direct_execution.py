from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_shadow_monitor_direct_script_help_smoke() -> None:
    """Guard the exact GitHub Actions invocation mode used by the PAPER-shadow monitor."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/shadow_monitor.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--monitor-state" in result.stdout
    assert "--output-json" in result.stdout
    assert "--output-md" in result.stdout
