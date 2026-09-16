#!/usr/bin/env bash
# Exit non-zero if the v2.4 -> v2.5 upgrade should be blocked, and print why.
# Works on a clean checkout with ANTHROPIC_API_KEY in the environment or in .env.
# Pass --offline to run from judge_cache.json without any API calls.
set -euo pipefail
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  uv sync --quiet
  exec uv run python main.py "$@"
fi
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet .
exec .venv/bin/python main.py "$@"
