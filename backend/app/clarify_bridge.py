"""
Orquesta el bucle de clarificación opcional o el RAG clásico; usado en /chat y en WhatsApp.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app import clarify_store as cs
from app.clarification_flow import build_clarify_graph, run_clarify_turn
from app.config import Settings
from app.expand_query import expand_query_async
from app.rag_service import RAGService, SourceChunk, GenerateChannel

logger = logging.getLogger("rag_qc.clarify")

_compiled_graph: Any = None


def get_clarify_graph(rag: RAGService, settings: Settings) -> Any | None:
    global _compiled_graph
    if not settings.rag_clarification_enabled:
        return None
    if _compiled_graph is None:
        _compiled_graph = build_clarify_graph(rag, settings)
    return _compiled_graph


def reset_clarify_graph() -> None:
    """Llamar al reiniciar el RAG (p. ej. en shutdown)."""
    global _compiled_graph
    _compiled_graph = None


async def _classic_rag_answer(
    rag: RAGService,
    settings: Settings,
    question: str,
    channel: GenerateChannel,
) -> tuple[str, list[SourceChunk]]:
    """
    Retriever: puede usar query expandida (sinónimos) si RAG_CLARIFY_SEMANTIC_EXPAND.
    Generación: siempre con la pregunta original del usuario.
    """
    q_stripped = (question or "").strip()
    if not q_stripped:
        logger.warning("Pregunta vacía o solo espacios: se omite retrieve y expansión")
        return rag.generate(question or "", [], channel=channel)
    if settings.rag_clarify_semantic_expand:
        ret_q = await expand_query_async(q_stripped, rag.llm)
        if not ret_q.strip():
            ret_q = q_stripped
    else:
        ret_q = q_stripped
    chunks = rag.retrieve(ret_q)
    return rag.generate(question, chunks, channel=channel)


async def run_user_turn(
    rag: RAGService,
    settings: Settings,
    *,
    question: str,
    thread_id: str,
    channel: GenerateChannel,
) -> tuple[str, list[SourceChunk], Literal["answer", "clarification"]]:
    """
    Retorna (texto al usuario, fuentes, tipo). Actualiza almacenamiento de hilo
    (set / clear) según el caso.
    """
    g = get_clarify_graph(rag, settings)
    if g is None:
        ans, used = await _classic_rag_answer(rag, settings, question, channel)
        return ans, used, "answer"
    try:
        eff, _f = cs.build_effective_query(thread_id, question)
        n0 = cs.clarifications_sent_before(thread_id)
        tr = await run_clarify_turn(
            g,
            query=eff,
            thread_id=thread_id,
            channel=channel,
            n_clarif_sent_before=n0,
            max_clarif=settings.rag_clarification_max_rounds,
        )
        if tr.response_type == "clarification":
            cs.set_after_clarification(
                thread_id, tr.effective_query, tr.n_clarifications_asked_after
            )
            return tr.text, tr.sources, "clarification"
        cs.mark_answered(thread_id, question, tr.text)
        return tr.text, tr.sources, "answer"
    except Exception as e:
        logger.exception("Bucle de clarificación falló (%s); RAG clásico", e)
        ans, used = await _classic_rag_answer(rag, settings, question, channel)
        return ans, used, "answer"
