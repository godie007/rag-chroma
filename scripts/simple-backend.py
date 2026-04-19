from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def catch_all(path: str, request: Request):
    print(f"DEBUG: path={path}")
    if path == "health":
        return {"status": "ok", "ready": False}
    if path == "config":
        return {"note": "RAG mode", "chunk_size": 1280, "top_k": 3}
    if path == "stats":
        return {"chunks": 0, "ready": False, "sources": []}
    if path == "api/health":
        return {"status": "ok", "ready": False}
    if path == "api/config":
        return {"note": "RAG mode", "chunk_size": 1280, "top_k": 3}
    if path == "api/stats":
        return {"chunks": 0, "ready": False, "sources": []}
    return {"detail": f"Path not found: {path}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3333)
