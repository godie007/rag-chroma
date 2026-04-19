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
        return {
            "openai_chat_temperature": 0.7,
            "openai_chat_max_output_tokens": 2000,
            "chunk_size": 1280,
            "chunk_overlap": 256,
            "chunk_min_chars": 50,
            "chunk_merge_hard_max": 0,
            "top_k": 3,
            "use_mmr": False,
            "mmr_fetch_k": 5,
            "mmr_lambda": 0.5,
            "max_upload_bytes": 52428800,
            "retrieve_max_l2_distance": 2.0,
            "retrieve_relevance_margin": 0.1,
            "retrieve_elbow_l2_gap": 0.05,
            "whatsapp_polling_active": False,
            "whatsapp_webhook_active": False,
            "whatsapp_poll_mode": "recent",
            "whatsapp_api_base_url": "",
            "whatsapp_poll_interval_sec": 10,
        }
    if path == "stats":
        return {"ready": False, "chunk_count": 0, "collection": "rag-chroma"}
    if path == "stats/sources":
        return {"sources": []}
    if path == "api/health":
        return {"status": "ok", "ready": False}
    if path == "api/config":
        return {
            "openai_chat_temperature": 0.7,
            "openai_chat_max_output_tokens": 2000,
            "chunk_size": 1280,
            "chunk_overlap": 256,
            "chunk_min_chars": 50,
            "chunk_merge_hard_max": 0,
            "top_k": 3,
            "use_mmr": False,
            "mmr_fetch_k": 5,
            "mmr_lambda": 0.5,
            "max_upload_bytes": 52428800,
            "retrieve_max_l2_distance": 2.0,
            "retrieve_relevance_margin": 0.1,
            "retrieve_elbow_l2_gap": 0.05,
            "whatsapp_polling_active": False,
            "whatsapp_webhook_active": False,
            "whatsapp_poll_mode": "recent",
            "whatsapp_api_base_url": "",
            "whatsapp_poll_interval_sec": 10,
        }
    if path == "api/stats":
        return {"ready": False, "chunk_count": 0, "collection": "rag-chroma"}
    if path == "api/stats/sources":
        return {"sources": []}
    if path == "api/chat":
        return {
            "answer": "RAG backend not configured. Please upload documents.",
            "sources": [],
        }
    return {"detail": f"Path not found: {path}"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3333)
