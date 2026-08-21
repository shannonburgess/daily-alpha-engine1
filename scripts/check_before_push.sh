#!/usr/bin/env bash
set -euo pipefail

echo "Running Daily Alpha pre-push quality checks..."
python -m ruff check .
python -m pytest -q
echo "Pre-push checks passed."
