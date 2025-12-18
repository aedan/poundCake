#!/bin/bash
# Run all CI checks locally before pushing

set -e

echo "=== Running Ruff linting ==="
/tmp/venv/bin/pip install ruff >/dev/null 2>&1 || true
/tmp/venv/bin/ruff check src tests

echo ""
echo "=== Running Black formatting check ==="
/tmp/venv/bin/black --check src tests

echo ""
echo "=== Running mypy type checking ==="
/tmp/venv/bin/pip install mypy >/dev/null 2>&1 || true
/tmp/venv/bin/mypy src

echo ""
echo "=== Running pytest ==="
/tmp/venv/bin/pip install -e ".[dev]" >/dev/null 2>&1 || true
/tmp/venv/bin/pytest tests/ -v --cov=poundcake --cov-report=xml

echo ""
echo "✅ All checks passed!"
