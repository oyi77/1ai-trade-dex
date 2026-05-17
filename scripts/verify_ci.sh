#!/bin/bash
set -e

echo "=== Ruff Lint ==="
venv/bin/ruff check backend/ --select=E,F,W --ignore=E501,E712

echo "=== Pyright Type Check ==="
npx pyright backend/ 2>&1 | tail -3

echo "=== Backend Tests ==="
WALLET_FERNET_KEY=test-key-for-dev-only venv/bin/python -m pytest backend/tests/ tests/ -q --tb=line -k "not live"

echo "=== Frontend ==="
cd frontend && npm test && npm run build && cd ..

echo "=== All CI checks passed ==="
