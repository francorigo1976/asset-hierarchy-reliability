#!/usr/bin/env bash
# One-step launcher: creates a virtualenv, installs dependencies, starts the web UI.
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python) || { echo "Python 3.11+ not found. Install it from python.org"; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11 or newer is required."; exit 1; }
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt uvicorn
echo "Open http://127.0.0.1:8000  (Ctrl+C to stop)"
exec python -m uvicorn asset_hierarchy.web.app:app --host 127.0.0.1 --port "${PORT:-8000}"
