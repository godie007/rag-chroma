#!/bin/bash
cd /home/jetson/workspace/codla/backend

# Backend simple sin RAG - solo API
exec python3 -c "
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import os

app = FastAPI()

@app.get('/health')
def health():
    return {'status': 'ok', 'ready': False, 'note': 'RAG requires Python 3.10+'}

@app.get('/config')
def config():
    return {'note': 'Full RAG not available - Python version too old'}

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=3333)
" > /tmp/rag-backend.log 2>&1 &

echo 'Backend simple started'
sleep 3
curl -s http://127.0.0.1:3333/health