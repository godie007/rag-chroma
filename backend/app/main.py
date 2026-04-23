import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# RAG Service for quality control - v2 with Nginx

from app.config import Settings
from app.conversation_commands import is_new_chat_command, new_chat_acknowledgement
from app.paths import resolve_eval_jsonl_path
from app.preprocess import (
    load_document_bytes,
    sanitize_chunk_text,
    strip_pdf_glyph_tokens,
)
from app.clarify_bridge import reset_clarify_graph
from app.rag_service import RAGService
from app.whatsapp_allowlist_store import (
    add_allowlist_number,
    delete_allowlist_storage_file,
    get_allowlist_numbers,
    remove_allowlist_number,
    set_allowlist_numbers,
)
from app.prompt_store import clear_prompt_overrides, get_effective_prompts, update_prompts
from app.whatsapp_poll import (
    process_raw_whatsapp_inbound_dict,
    run_whatsapp_poll_loop,
    verify_whatsapp_webhook_request,
)

logger = logging.getLogger("rag_qc")

_settings: Settings | None = None
_rag: RAGService | None = None
_whatsapp_poll_task: asyncio.Task[None] | None = None


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
    logging.getLogger("rag_qc.whatsapp").setLevel(logging.INFO)
    global _whatsapp_poll_task
    _settings = Settings()
    if _settings.openai_api_key.strip():
        try:
            _rag = RAGService(_settings)
            logger.info(
                "RAG inicializado (Chroma en %s)", _settings.chroma_persist_directory
            )
        except Exception as e:
            logger.exception("No se pudo inicializar RAG: %s", e)
            _rag = None
    else:
        logger.warning("OPENAI_API_KEY vacía: /ingest y /chat no estarán disponibles")
        _rag = None
    if _settings.whatsapp_enabled and _rag is not None:
        if _settings.whatsapp_poll_enabled:
            _whatsapp_poll_task = asyncio.create_task(
                run_whatsapp_poll_loop(
                    settings_provider=get_settings, rag_provider=lambda: _rag
                ),
                name="whatsapp-poll",
            )
            if _settings.whatsapp_poll_mode == "chats":
                logger.info(
                    "WhatsApp polling (chats) → %s/chats + /messages?chat_jid=… cada %.1f s (GOWA :3000, API :8090)",
                    _settings.whatsapp_api_base_url.rstrip("/"),
                    _settings.whatsapp_poll_interval_sec,
                )
            else:
                logger.info(
                    "WhatsApp polling (recent) → %s/messages/recent cada %.1f s (GOWA :3000, API :8090)",
                    _settings.whatsapp_api_base_url.rstrip("/"),
                    _settings.whatsapp_poll_interval_sec,
                )
        else:
            logger.info(
                "WhatsApp: polling desactivado (WHATSAPP_POLL_ENABLED=false); recepción solo por POST /webhooks/whatsapp",
            )
        if _settings.whatsapp_webhook_secret.strip():
            logger.info(
                "WhatsApp webhook protegido: cabecera X-WhatsApp-Webhook-Secret o Authorization: Bearer …"
            )
        if _settings.whatsapp_process_from_me:
            logger.info(
                "WhatsApp: WHATSAPP_PROCESS_FROM_ME=true (se procesan mensajes salientes/sync; textos from_me > %d chars se ignoran)",
                _settings.whatsapp_from_me_max_question_chars,
            )
    elif _settings.whatsapp_enabled and _rag is None:
        logger.warning(
            "WHATSAPP_ENABLED=true pero RAG no disponible: no hay polling ni webhook útil hasta configurar OPENAI_API_KEY"
        )
    yield
    reset_clarify_graph()
    if _whatsapp_poll_task is not None:
        _whatsapp_poll_task.cancel()
        try:
            await _whatsapp_poll_task
        except asyncio.CancelledError:
            pass
        _whatsapp_poll_task = None
    _rag = None
    _settings = None


app = FastAPI(title="RAG Control de Calidad", lifespan=lifespan)

_cors = Settings()
_origins = [o.strip() for o in _cors.cors_origins.split(",") if o.strip()] or [
    "http://localhost:4444",
    "http://127.0.0.1:4444",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=8000)
    thread_id: str | None = None


class SourceOut(BaseModel):
    content: str
    metadata: dict


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    thread_id: str = ""
    response_type: Literal["answer", "clarification"] = "answer"


class IngestResponse(BaseModel):
    files_processed: int
    chunks_added: int
    messages: list[str]
    # Total de vectores en Chroma al terminar (mismo proceso que escribió; GET /stats puede retrasar o ir a otro worker).
    chunk_count: int = 0
    ready: bool = True


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


class IndexedSourcesResponse(BaseModel):
    sources: list[str]


class DeleteIndexedSourceBody(BaseModel):
    source: str = Field(..., min_length=1, max_length=4096)


class DeleteIndexedSourceResponse(BaseModel):
    source: str
    chunks_removed: int
    chunk_count: int
    ready: bool = True


class WhatsAppAllowlistOut(BaseModel):
    numbers: list[str]
    source: Literal["file", "env"]


class WhatsAppAllowlistPutBody(BaseModel):
    numbers: list[str] = Field(default_factory=list)


class WhatsAppAllowlistAddBody(BaseModel):
    number: str = Field(..., min_length=1, max_length=40)


class SystemPromptsOut(BaseModel):
    system_rag_web: str
    system_rag_whatsapp: str
    system_no_retrieval_web: str
    system_no_retrieval_whatsapp: str


class SystemPromptsUpdate(BaseModel):
    system_rag_web: str | None = None
    system_rag_whatsapp: str | None = None
    system_no_retrieval_web: str | None = None
    system_no_retrieval_whatsapp: str | None = None


_MAX_PROMPT_CHARS = 200_000


class ConfigPublic(BaseModel):
    openai_chat_temperature: float
    openai_chat_max_output_tokens: int
    openai_embedding_model: str
    openai_embedding_dimensions: int | None
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
    enable_contextual_retrieval: bool
    rag_clarification_enabled: bool
    rag_clarification_max_rounds: int
    rag_clarify_semantic_expand: bool
    whatsapp_polling_active: bool
    whatsapp_webhook_active: bool
    whatsapp_poll_mode: str
    whatsapp_api_base_url: str
    whatsapp_poll_interval_sec: float


@app.get("/health")
def health():
    return {"status": "ok", "ready": _rag is not None}


@app.get("/stats", response_model=StatsResponse)
def stats():
    s = get_settings()
    if _rag is None:
        return StatsResponse(
            ready=False, chunk_count=0, collection=s.chroma_collection_name
        )
    return StatsResponse(
        ready=True,
        chunk_count=_rag.collection_chunk_count(),
        collection=s.chroma_collection_name,
    )


@app.get("/stats/sources", response_model=IndexedSourcesResponse)
def stats_indexed_sources():
    if _rag is None:
        return IndexedSourcesResponse(sources=[])
    return IndexedSourcesResponse(sources=_rag.list_indexed_sources())


@app.get("/config/prompts", response_model=SystemPromptsOut)
def get_system_prompts_config():
    """System prompts efectivos (archivo + defaults de código; sin reiniciar servidor)."""
    p = get_effective_prompts()
    return SystemPromptsOut(
        system_rag_web=p["system_rag_web"],
        system_rag_whatsapp=p["system_rag_whatsapp"],
        system_no_retrieval_web=p["system_no_retrieval_web"],
        system_no_retrieval_whatsapp=p["system_no_retrieval_whatsapp"],
    )


@app.put("/config/prompts", response_model=SystemPromptsOut)
def put_system_prompts_config(body: SystemPromptsUpdate):
    """Guarda personalizaciones en ``backend/system_prompts.json``; vacío = vuelve al default de código."""
    for name, val in body.model_dump().items():
        if val is not None and len(val) > _MAX_PROMPT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"{name} supera {_MAX_PROMPT_CHARS} caracteres",
            )
    p = update_prompts(
        system_rag_web=body.system_rag_web,
        system_rag_whatsapp=body.system_rag_whatsapp,
        system_no_retrieval_web=body.system_no_retrieval_web,
        system_no_retrieval_whatsapp=body.system_no_retrieval_whatsapp,
    )
    return SystemPromptsOut(
        system_rag_web=p["system_rag_web"],
        system_rag_whatsapp=p["system_rag_whatsapp"],
        system_no_retrieval_web=p["system_no_retrieval_web"],
        system_no_retrieval_whatsapp=p["system_no_retrieval_whatsapp"],
    )


@app.delete("/config/prompts", response_model=SystemPromptsOut)
def delete_system_prompts_overrides():
    """Elimina ``system_prompts.json``; vuelve a los textos por defecto del código (sin reiniciar)."""
    try:
        clear_prompt_overrides()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"No se pudo borrar overrides: {e}") from e
    out = get_effective_prompts()
    return SystemPromptsOut(
        system_rag_web=out["system_rag_web"],
        system_rag_whatsapp=out["system_rag_whatsapp"],
        system_no_retrieval_web=out["system_no_retrieval_web"],
        system_no_retrieval_whatsapp=out["system_no_retrieval_whatsapp"],
    )


@app.get("/config", response_model=ConfigPublic)
def public_config():
    s = get_settings()
    wa_ok = bool(s.whatsapp_enabled and _rag is not None)
    wa_poll = bool(wa_ok and s.whatsapp_poll_enabled)
    return ConfigPublic(
        openai_chat_temperature=s.openai_chat_temperature,
        openai_chat_max_output_tokens=s.openai_chat_max_output_tokens,
        openai_embedding_model=s.openai_embedding_model,
        openai_embedding_dimensions=s.openai_embedding_dimensions,
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
        enable_contextual_retrieval=s.enable_contextual_retrieval,
        rag_clarification_enabled=s.rag_clarification_enabled,
        rag_clarification_max_rounds=s.rag_clarification_max_rounds,
        rag_clarify_semantic_expand=s.rag_clarify_semantic_expand,
        whatsapp_polling_active=wa_poll,
        whatsapp_webhook_active=wa_ok,
        whatsapp_poll_mode=s.whatsapp_poll_mode,
        whatsapp_api_base_url=s.whatsapp_api_base_url,
        whatsapp_poll_interval_sec=s.whatsapp_poll_interval_sec,
    )


@app.get("/whatsapp/allowlist", response_model=WhatsAppAllowlistOut)
def whatsapp_allowlist_get():
    s = get_settings()
    nums, src = get_allowlist_numbers(s)
    return WhatsAppAllowlistOut(numbers=nums, source=src)


@app.put("/whatsapp/allowlist", response_model=WhatsAppAllowlistOut)
def whatsapp_allowlist_put(body: WhatsAppAllowlistPutBody):
    out = set_allowlist_numbers(body.numbers)
    return WhatsAppAllowlistOut(numbers=out, source="file")


@app.post("/whatsapp/allowlist", response_model=WhatsAppAllowlistOut)
def whatsapp_allowlist_add(body: WhatsAppAllowlistAddBody):
    try:
        out = add_allowlist_number(get_settings(), body.number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return WhatsAppAllowlistOut(numbers=out, source="file")


@app.delete("/whatsapp/allowlist", response_model=WhatsAppAllowlistOut)
def whatsapp_allowlist_delete(number: str = Query(..., min_length=1, max_length=40)):
    out = remove_allowlist_number(get_settings(), number)
    return WhatsAppAllowlistOut(numbers=out, source="file")


@app.post("/whatsapp/allowlist/revert-env", response_model=WhatsAppAllowlistOut)
def whatsapp_allowlist_revert_env():
    delete_allowlist_storage_file()
    s = get_settings()
    nums, src = get_allowlist_numbers(s)
    return WhatsAppAllowlistOut(numbers=nums, source=src)


@app.post("/ingest", response_model=IngestResponse)
async def ingest(files: list[UploadFile] = File(...)):
    settings = get_settings()
    if not settings.openai_api_key.strip():
        raise HTTPException(
            status_code=401, detail="Falta OPENAI_API_KEY en el servidor"
        )
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
            # PDF/MD grande: extrae en hilo para no bloquear el bucle de eventos (/chat, /health siguen vivos).
            text = await asyncio.to_thread(
                load_document_bytes, upload.filename or "unknown", raw
            )
        except ValueError as e:
            messages.append(f"Omitido {upload.filename}: {e}")
            continue
        logger.info(
            "Ingest %s: texto extraído (~%d caracteres), generando embeddings…",
            upload.filename,
            len(text),
        )
        # Indexación (embeddings + Chroma) fuera del hilo principal async; el lock en RAGService serializa escrituras.
        n = await asyncio.to_thread(
            rag.ingest_text, text, upload.filename or "sin_nombre"
        )
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
        # Cede el bucle de eventos entre archivos (multimodal) para atender otras peticiones.
        await asyncio.sleep(0)
    total_in_index = rag.collection_chunk_count()
    return IngestResponse(
        files_processed=processed,
        chunks_added=total_chunks,
        messages=messages,
        chunk_count=total_in_index,
        ready=True,
    )


@app.post("/ingest/delete-source", response_model=DeleteIndexedSourceResponse)
def ingest_delete_source(body: DeleteIndexedSourceBody):
    """Elimina todos los fragmentos indexados para una fuente (nombre de archivo u origen en metadato ``source``)."""
    rag = require_rag()
    removed = rag.delete_indexed_source(body.source)
    return DeleteIndexedSourceResponse(
        source=body.source.strip(),
        chunks_removed=removed,
        chunk_count=rag.collection_chunk_count(),
        ready=True,
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


def _whatsapp_webhook_body_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for k in ("messages", "data"):
            v = body.get(k)
            if isinstance(v, list) and v:
                return [x for x in v if isinstance(x, dict)]
        res = body.get("results")
        if isinstance(res, dict):
            v = res.get("data")
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return [body]
    return []


@app.get("/webhooks/whatsapp")
def whatsapp_webhook_ping():
    """
    GOWA (:3000) → API Flask (:8090). Puedes reenviar desde whatsapp_api.py o whatsapp_receiver.sh con POST aquí.
    Alternativa: el backend hace polling a /messages/recent o modo /chats + /messages por chat.
    """
    return {
        "ok": True,
        "post": "JSON con un mensaje o lista / data / messages (mismo criterio que normalize_whatsapp_inbound).",
        "upstream_ports": {"gowa_docker": 3000, "whatsapp_api_flask": 8090},
        "upstream_read_endpoints": {
            "recent": "GET /messages/recent — cada mensaje incluye is_from_me (true/false)",
            "by_chat": "GET /messages?chat_jid=<jid> — historial de un chat; mismo is_from_me",
        },
        "jetson_scripts": ["whatsapp_api.py", "whatsapp_receiver.sh"],
    }


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request):
    settings = get_settings()
    if not settings.whatsapp_enabled:
        raise HTTPException(status_code=503, detail="WHATSAPP_ENABLED=false")
    if not verify_whatsapp_webhook_request(request, settings):
        raise HTTPException(
            status_code=401,
            detail=(
                "Webhook no autorizado. Define WHATSAPP_WEBHOOK_SECRET en el backend y envía "
                "X-WhatsApp-Webhook-Secret: <secreto> o Authorization: Bearer <secreto>"
            ),
        )
    rag = require_rag()
    raw_bytes = await request.body()
    if not raw_bytes.strip():
        raise HTTPException(status_code=400, detail="Cuerpo vacío")
    try:
        body = json.loads(raw_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido") from None

    items = _whatsapp_webhook_body_items(body)
    if not items:
        return {
            "ok": True,
            "processed": 0,
            "detail": "Sin objetos de mensaje reconocibles",
        }

    results: list[dict[str, Any]] = []
    for item in items:
        out = await process_raw_whatsapp_inbound_dict(
            item, settings=settings, rag=rag, source="webhook"
        )
        results.append(out)
    logger.info("WhatsApp webhook: procesados %d objeto(s)", len(results))
    return {"ok": True, "count": len(results), "results": results}


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    from app import clarify_store as _cs
    from app.clarify_bridge import run_user_turn

    rag = require_rag()
    settings = get_settings()
    thread_id = (body.thread_id or "").strip() or str(uuid.uuid4())
    if is_new_chat_command(body.question):
        _cs.clear_thread(thread_id)
        return ChatResponse(
            answer=new_chat_acknowledgement(),
            sources=[],
            thread_id=thread_id,
            response_type="answer",
        )
    text, used, rtype = run_user_turn(
        rag,
        settings,
        question=body.question.strip(),
        thread_id=thread_id,
        channel="web",
    )
    answer_out = strip_pdf_glyph_tokens(text)
    return ChatResponse(
        answer=answer_out,
        sources=[
            SourceOut(content=sanitize_chunk_text(s.content), metadata=s.metadata) for s in used
        ],
        thread_id=thread_id,
        response_type=rtype,
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
        raise HTTPException(
            status_code=401, detail="Falta OPENAI_API_KEY en el servidor"
        )
    rag = require_rag()
    try:
        eval_path = resolve_eval_jsonl_path(eval_relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not eval_path.is_file():
        raise HTTPException(
            status_code=404, detail=f"No existe el archivo de evaluación: {eval_path}"
        )

    try:
        return await run_ragas_evaluation_async(rag, settings, eval_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Fallo evaluación RAGAS: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Error en evaluación RAGAS: {e!s}"
        ) from e
