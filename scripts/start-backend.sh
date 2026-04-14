#!/bin/bash
cd /home/jetson/workspace/codla/backend
source .venv/bin/activate 2>/dev/null || true
exec uvicorn app.main:app --host 127.0.0.1 --port 3333