import json
import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import Settings
from app.conversation_commands import is_new_chat_command, new_chat_acknowledgement
from app.paths import resolve_eval_jsonl_path
from app.preprocess import load_document_bytes, sanitize_chunk_text, strip_pdf_glyph_tokens
from app.evolution_webhook import (
    extract_webhook_api_key,
    handle_evolution_payload,
    verify_evolution_webhook_credential,
)
from app.rag_service import RAGService

logger = logging.getLogger("rag_qc")

_settings: Settings | None = None
_rag: RAGService | None = None


def get_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("Settings no inicializadas")
    return _settings


def require_rag() -> RAGService:
    if _rag is None:
        raise HTTPException(
            status_code=401,
            detail="Falta OPENAI_API_KEY o el RAG no pudo inicializarse. Revisa backend/.env",
        )
    return _rag


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _settings, _rag
    # Uvicorn configura el root antes del lifespan; sin force=True los INFO de rag_qc no salen a consola.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    logging.getLogger("rag_qc").setLevel(logging.INFO)
    logging.getLogger("rag_qc.evolution").setLevel(logging.INFO)
    _settings = Settings()
    if _settings.openai_api_key.strip():
        try:
            _rag = RAGService(_settings)
            logger.info("RAG inicializado (Chroma en %s)", _settings.chroma_persist_directory)
        except Exception as e:
            logger.exception("No se pudo inicializar RAG: %s", e)
            _rag = None
    else:
        logger.warning("OPENAI_API_KEY vacía: /ingest y /chat no estarán disponibles")
        _rag = None
    yield
    _rag = None
    _settings = None


app = FastAPI(title="RAG Control de Calidad", lifespan=lifespan)

_cors = Settings()
_origins = [o.strip() for o in _cors.cors_origins.split(",") if o.strip()] or ["http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8000)


class SourceOut(BaseModel):
    content: str
    metadata: dict


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceOut]


class IngestResponse(BaseModel):
    files_processed: int
    chunks_added: int
    messages: list[str]


class ResetIndexResponse(BaseModel):
    status: str
    collection: str
    message: str
    chunk_count: int
    ready: bool = True


class StatsResponse(BaseModel):
    ready: bool
    chunk_count: int
    collection: str


class ConfigPublic(BaseModel):
    openai_chat_temperature: float
    openai_chat_max_output_tokens: int
    chunk_size: int
    chunk_overlap: int
    chunk_min_chars: int
    chunk_merge_hard_max: int
    top_k: int
    use_mmr: bool
    mmr_fetch_k: int
    mmr_lambda: float
    max_upload_bytes: int
    retrieve_max_l2_distance: float
    retrieve_relevance_margin: float
    retrieve_elbow_l2_gap: float
    evolution_webhook_enabled: bool
    evolution_api_base_url: str
    evolution_reply_in_groups: bool


@app.get("/health")
def health():
    return {"status": "ok", "ready": _rag is not None}


@app.get("/stats", response_model=StatsResponse)
def stats():
    s = get_settings()
    if _rag is None:
        return StatsResponse(ready=False, chunk_count=0, collection=s.chroma_collection_name)
    return StatsResponse(
        ready=True,
        chunk_count=_rag.collection_chunk_count(),
        collection=s.chroma_collection_name,
    )


@app.get("/config", response_model=ConfigPublic)
def public_config():
    s = get_settings()
    evo_ready = bool(s.evolution_enabled and s.evolution_api_key.strip())
    return ConfigPublic(
        openai_chat_temperature=s.openai_chat_temperature,
        openai_chat_max_output_tokens=s.openai_chat_max_output_tokens,
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        chunk_min_chars=s.chunk_min_chars,
        chunk_merge_hard_max=s.chunk_merge_hard_max or (s.chunk_size * 2),
        top_k=s.top_k,
        use_mmr=s.use_mmr,
        mmr_fetch_k=s.mmr_fetch_k,
        mmr_lambda=s.mmr_lambda,
        max_upload_bytes=s.max_upload_bytes,
        retrieve_max_l2_distance=s.retrieve_max_l2_distance,
        retrieve_relevance_margin=s.retrieve_relevance_margin,
        retrieve_elbow_l2_gap=s.retrieve_elbow_l2_gap,
        evolution_webhook_enabled=evo_ready,
        evolution_api_base_url=s.evolution_api_base_url,
        evolution_reply_in_groups=s.evolution_reply_in_groups,
    )


@app.post("/ingest", response_model=IngestResponse)
async def ingest(files: list[UploadFile] = File(...)):
    settings = get_settings()
    if not settings.openai_api_key.strip():
        raise HTTPException(status_code=401, detail="Falta OPENAI_API_KEY en el servidor")
    rag = require_rag()
    total_chunks = 0
    processed = 0
    messages: list[str] = []
    for upload in files:
        t0 = time.perf_counter()
        raw = await upload.read()
        if len(raw) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Archivo {upload.filename} supera el límite de {settings.max_upload_bytes} bytes",
            )
        try:
            text = load_document_bytes(upload.filename or "unknown", raw)
        except ValueError as e:
            messages.append(f"Omitido {upload.filename}: {e}")
            continue
        logger.info(
            "Ingest %s: texto extraído (~%d caracteres), generando embeddings…",
            upload.filename,
            len(text),
        )
        n = rag.ingest_text(text, upload.filename or "sin_nombre")
        elapsed = time.perf_counter() - t0
        total_chunks += n
        processed += 1
        messages.append(f"{upload.filename}: {n} fragmentos indexados")
        logger.info(
            "Ingest %s: %d fragmentos en %.1f s",
            upload.filename,
            n,
            elapsed,
        )
    return IngestResponse(
        files_processed=processed,
        chunks_added=total_chunks,
        messages=messages,
    )


@app.post("/ingest/reset", response_model=ResetIndexResponse)
def ingest_reset():
    rag = require_rag()
    name = get_settings().chroma_collection_name
    try:
        rag.clear_vector_index()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    n = rag.collection_chunk_count()
    return ResetIndexResponse(
        status="ok",
        collection=name,
        message="Índice y archivos de Chroma eliminados en disco. Sube de nuevo los documentos para regenerar embeddings.",
        chunk_count=n,
        ready=True,
    )


@app.get("/webhooks/evolution")
def evolution_webhook_ping():
    """Comprueba que el backend es alcanzable desde Evolution (GET). El webhook real es POST."""
    return {
        "ok": True,
        "path": "/webhooks/evolution",
        "method": "Usa POST desde Evolution; este GET solo verifica red/firewall.",
    }


async def _evolution_webhook_impl(request: Request) -> dict:
    """POST a /webhooks/evolution o /webhooks/evolution/<sufijo> (WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS)."""
    peer = request.client.host if request.client else "?"
    logger.info("Evolution webhook: POST recibido (cliente=%s)", peer)
    settings = get_settings()
    if not settings.evolution_enabled:
        logger.warning("Evolution webhook: rechazado 503 — EVOLUTION_ENABLED=false")
        raise HTTPException(status_code=503, detail="Integración Evolution desactivada (EVOLUTION_ENABLED=false)")
    if not settings.evolution_api_key.strip():
        logger.warning("Evolution webhook: rechazado 503 — falta EVOLUTION_API_KEY")
        raise HTTPException(
            status_code=503,
            detail="Falta EVOLUTION_API_KEY en backend/.env (misma clave que AUTHENTICATION_API_KEY en Evolution)",
        )
    raw_bytes = await request.body()
    if not raw_bytes.strip():
        logger.warning("Evolution webhook: cuerpo vacío")
        raise HTTPException(status_code=400, detail="Cuerpo vacío")
    try:
        body = json.loads(raw_bytes)
    except json.JSONDecodeError:
        logger.warning(
            "Evolution webhook: JSON inválido (primeros 400 bytes): %r",
            raw_bytes[:400],
        )
        raise HTTPException(status_code=400, detail="JSON inválido") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON")

    logger.info(
        "Evolution webhook: cuerpo parseado event=%r instance=%r",
        body.get("event"),
        body.get("instance"),
    )

    if settings.evolution_api_key.strip() and settings.evolution_verify_webhook_apikey:
        got = extract_webhook_api_key(request, body)
        inst = body.get("instance")
        ok = await verify_evolution_webhook_credential(got, inst if isinstance(inst, str) else None, settings=settings)
        if not ok:
            logger.warning(
                "Evolution webhook 401: credencial inválida o ausente "
                "(header apikey: %s; cuerpo trae apikey/apiKey: %s). "
                "Evolution suele enviar el token de la instancia, no AUTHENTICATION_API_KEY; "
                "o apikey null si AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES=false.",
                "sí" if request.headers.get("apikey") or request.headers.get("Apikey") else "no",
                "sí" if body.get("apikey") is not None or body.get("apiKey") is not None else "no",
            )
            raise HTTPException(
                status_code=401,
                detail=(
                    "Credencial del webhook inválida o ausente. Debe ser EVOLUTION_API_KEY (global) o el token "
                    "de la instancia (hash). Requiere EVOLUTION_API_KEY=AUTHENTICATION_API_KEY y "
                    "EVOLUTION_API_BASE_URL alcanzable para validar el token. Si no hay apikey en el JSON, "
                    "activa AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES=true en Evolution o pon "
                    "EVOLUTION_VERIFY_WEBHOOK_APIKEY=false (menos seguro)."
                ),
            )

    err = body.get("error") if isinstance(body.get("error"), str) else None
    if err:
        return {"ok": True, "ignored": True, "reason": "evolution_error_event", "detail": err}

    rag = require_rag()
    try:
        out = await handle_evolution_payload(body, settings=settings, rag=rag)
        if out.get("replied"):
            if out.get("reason") == "new_chat_command":
                logger.info("Evolution webhook: comando /nuevo — conversación reiniciada (mensaje al remitente)")
            else:
                logger.info("Evolution webhook: respuesta RAG enviada por WhatsApp")
        elif out.get("ignored"):
            logger.info("Evolution webhook: sin respuesta automática — %s", out.get("reason"))
        return out
    except httpx.HTTPError as e:
        logger.exception("Error HTTP contra Evolution API: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo enviar la respuesta por WhatsApp (Evolution): {e!s}",
        ) from e


@app.post("/webhooks/evolution")
async def evolution_webhook(request: Request):
    """Recibe eventos globales de Evolution (p. ej. messages.upsert) y responde con el RAG."""
    return await _evolution_webhook_impl(request)


@app.post("/webhooks/evolution/{rest:path}")
async def evolution_webhook_by_event_suffix(request: Request, rest: str):
    """Misma lógica que POST /webhooks/evolution cuando WEBHOOK_GLOBAL_WEBHOOK_BY_EVENTS=true (p. ej. …/chats-update)."""
    _ = rest
    return await _evolution_webhook_impl(request)


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    if is_new_chat_command(body.question):
        return ChatResponse(answer=new_chat_acknowledgement(), sources=[])
    rag = require_rag()
    contexts = rag.retrieve(body.question)
    answer, used = rag.generate(body.question, contexts)
    answer_out = strip_pdf_glyph_tokens(answer)
    return ChatResponse(
        answer=answer_out,
        sources=[
            SourceOut(content=sanitize_chunk_text(s.content), metadata=s.metadata) for s in used
        ],
    )


@app.get("/retrieve")
def retrieve_debug(q: str, infer_profile: bool = True):
    """infer_profile=False evita la clasificación por LLM (solo recuperación normal)."""
    rag = require_rag()
    contexts = rag.retrieve(q, infer_broad_retrieval=infer_profile)
    return {
        "contexts": [sanitize_chunk_text(c.content) for c in contexts],
        "metadata": [c.metadata for c in contexts],
    }


@app.post("/evaluate")
async def evaluate_ragas(eval_relative_path: str | None = None):
    try:
        from app.evaluation import run_ragas_evaluation_async
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail="Instala dependencias del backend: pip install -r requirements.txt (incluye RAGAS)",
        ) from e

    settings = get_settings()
    if not settings.openai_api_key.strip():
        raise HTTPException(status_code=401, detail="Falta OPENAI_API_KEY en el servidor")
    rag = require_rag()
    try:
        eval_path = resolve_eval_jsonl_path(eval_relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not eval_path.is_file():
        raise HTTPException(status_code=404, detail=f"No existe el archivo de evaluación: {eval_path}")

    try:
        return await run_ragas_evaluation_async(rag, settings, eval_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Fallo evaluación RAGAS: %s", e)
        raise HTTPException(status_code=500, detail=f"Error en evaluación RAGAS: {e!s}") from e
