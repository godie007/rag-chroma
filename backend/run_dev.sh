#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
# 0.0.0.0: Evolution en Docker debe poder llamar host.docker.internal:8000 (127.0.0.1 no acepta ese tráfico).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
