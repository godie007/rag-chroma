#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
# 0.0.0.0: permite que otros equipos en la red (p. ej. API WhatsApp en Jetson) llamen al backend.
exec uvicorn app.main:app --host 0.0.0.0 --port 3333 --reload
