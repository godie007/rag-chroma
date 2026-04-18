#!/bin/bash
cd /home/jetson/workspace/codla/backend

# Iniciar backend con system Python
exec uvicorn app.main:app --host 0.0.0.0 --port 3333 --log-level info