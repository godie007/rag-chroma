#!/bin/bash
cd /home/jetson/workspace/codla/backend

# Activar venv
source .venv/bin/activate 2>/dev/null || { echo "ERROR: No se pudo activar .venv"; exit 1; }

# Verificar que las dependencias estén instaladas
python3 -c "import fastapi, uvicorn, langchain" 2>/dev/null || { echo "ERROR: Faltan dependencias"; exit 1; }

# Iniciar backend con logging
exec uvicorn app.main:app --host 0.0.0.0 --port 3333 --log-level info