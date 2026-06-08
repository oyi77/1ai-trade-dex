#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────────
# BNB HACK — Bot Runner
# Wrapper for systemd: activates venv, sources .env, runs the bot.
# Usage: ./scripts/run_bnb_hack.sh [--loop] [--paper]
# ───────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# ── Activate virtualenv ─────────────────────────────────────────
VENV="$PROJECT_DIR/.venv"
if [ -d "$VENV" ]; then
    source "$VENV/bin/activate"
fi

# ── Source environment variables ─────────────────────────────────
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# ── Run ──────────────────────────────────────────────────────────
exec python -m backend.bot.bnb_hack_bot "$@"
