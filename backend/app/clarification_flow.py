"""
Clarification loop: grafo LangGraph (retrieve → evaluar → clarificar o generar vía RAG).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.config import Settings
from app.expand_query import expand_query
from app.prompts import SYSTEM_CLARIFICATION_AMBIGUITY_EVAL
from app.rag_service import RAGService, SourceChunk, GenerateChannel

logger = logging.getLogger("rag_qc.clarify")


class AmbiguityEvaluation(BaseModel):
    is_ambiguous: bool
    reason: str = Field(default="", max_length=2000)
    clarification_question: str | None = None
    refined_query: str | None = Field(
        default=None,
        description="Si no es ambiguo: reformulación breve para el retriever, opcional.",
    )


class _GraphState(TypedDict, total=False):
    query: str
    expanded_query: str
    channel: str
    n_clarif_sent_before: int
    max_clarif: int
    chunks: list[SourceChunk]
    eval_result: AmbiguityEvaluation | None
    route: Literal["clarify", "answer"]
    clarify_text: str
    final_answer: str
    used_chunks: list[SourceChunk]
    re_retrieve_done: bool


def _chunks_preview(chunks: list[SourceChunk], max_chars: int = 12_000) -> str:
    parts: list[str] = []
    n = 0
    for c in chunks:
        t = c.content
        if n + len(t) > max_chars:
            t = t[: max(0, max_chars - n)] + "…"
        parts.append(t)
        n += len(t)
        if n >= max_chars:
            break
    return "\n\n---\n\n".join(parts)


def _node_retrieve(rag: RAGService, settings: Settings) -> Any:
    def _run(s: _GraphState) -> dict[str, Any]:
        q = (s.get("query") or "").strip() or " "
        if settings.rag_clarify_semantic_expand:
            expanded = expand_query(q, rag.llm)
        else:
            expanded = q
        ch = rag.retrieve(expanded)
        return {"chunks": ch, "expanded_query": expanded}

    return _run


def _node_evaluate(rag: RAGService, _settings: Settings) -> Any:
    def _run(s: _GraphState) -> dict[str, Any]:
        q = (s.get("query") or "").strip()
        max_r = int(s.get("max_clarif") or 0)
        n0 = int(s.get("n_clarif_sent_before") or 0)
        ch = s.get("chunks") or []
        if not ch:
            return {
                "eval_result": None,
                "route": "answer",
            }
        if n0 >= max_r:
            return {
                "eval_result": None,
                "route": "answer",
            }
        try:
            struct = rag.llm.bind(temperature=0, max_tokens=800).with_structured_output(
                AmbiguityEvaluation
            )
            human = f"""Pregunta / consulta (análisis interno):

{q}

Documentos (extractos recuperados, uso interno):
{_chunks_preview(ch)}
"""
            out: AmbiguityEvaluation = struct.invoke(  # type: ignore[assignment]
                [
                    {"role": "system", "content": SYSTEM_CLARIFICATION_AMBIGUITY_EVAL},
                    {"role": "user", "content": human},
                ]
            )
        except Exception as e:
            logger.warning("Evaluación de ambigüedad falló: %s; se responde sin clarificar", e)
            return {
                "eval_result": None,
                "route": "answer",
            }
        if out.is_ambiguous and n0 < max_r and (out.clarification_question or "").strip():
            return {
                "eval_result": out,
                "route": "clarify",
            }
        return {
            "eval_result": out,
            "route": "answer",
        }

    return _run


def _node_clarify() -> Any:
    def _run(s: _GraphState) -> dict[str, Any]:
        ev = s.get("eval_result")
        t = (ev.clarification_question or "").strip() if ev else ""
        if not t:
            t = "¿Podrías concretar el contexto, la norma o el alcance que te interesa?"
        return {
            "clarify_text": t,
        }

    return _run


def _node_re_refine(rag: RAGService) -> Any:
    def _run(s: _GraphState) -> dict[str, Any]:
        if s.get("re_retrieve_done"):
            return {"re_retrieve_done": True}
        ev = s.get("eval_result")
        rq = (ev.refined_query or "").strip() if ev else ""
        if not rq:
            # El primer retrieve ya usó expanded_query; no hay reformulación adicional.
            return {"re_retrieve_done": True}
        ch2 = rag.retrieve(rq)
        if ch2:
            return {"chunks": ch2, "query": rq, "re_retrieve_done": True}
        return {"re_retrieve_done": True}

    return _run


def _node_answer(rag: RAGService) -> Any:
    def _run(s: _GraphState) -> dict[str, Any]:
        ch = s.get("chunks") or []
        q = (s.get("query") or "").strip()
        ch_t = s.get("channel") or "web"
        if ch_t not in ("web", "whatsapp"):
            ch_t = "web"
        channel: GenerateChannel = "whatsapp" if ch_t == "whatsapp" else "web"
        text, used = rag.generate(q, ch, channel=channel)
        return {
            "final_answer": text,
            "used_chunks": used,
        }

    return _run


def _route_after_eval(s: _GraphState) -> str:
    if s.get("route") == "clarify":
        return "clarify"
    return "re_refine"


def build_clarify_graph(rag: RAGService, settings: Settings) -> Any:
    g = StateGraph(_GraphState)
    g.add_node("retrieve", _node_retrieve(rag, settings))
    g.add_node("evaluate", _node_evaluate(rag, settings))
    g.add_node("clarify", _node_clarify())
    g.add_node("re_refine", _node_re_refine(rag))
    g.add_node("answer", _node_answer(rag))
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "evaluate")
    g.add_conditional_edges("evaluate", _route_after_eval, {"clarify": "clarify", "re_refine": "re_refine"})
    g.add_edge("clarify", END)
    g.add_edge("re_refine", "answer")
    g.add_edge("answer", END)
    return g.compile()


@dataclass
class ClarifyTurnResult:
    response_type: Literal["answer", "clarification"]
    text: str
    sources: list[SourceChunk]
    effective_query: str
    n_clarifications_asked_after: int


def run_clarify_turn(
    graph: Any,
    *,
    query: str,
    channel: GenerateChannel,
    n_clarif_sent_before: int,
    max_clarif: int,
) -> ClarifyTurnResult:
    out: _GraphState = graph.invoke(
        {
            "query": query,
            "channel": channel,
            "n_clarif_sent_before": n_clarif_sent_before,
            "max_clarif": max_clarif,
            "re_retrieve_done": False,
        }
    )
    if (out.get("clarify_text") or "").strip():
        c = (out.get("clarify_text") or "").strip()
        n_after = n_clarif_sent_before + 1
        return ClarifyTurnResult(
            response_type="clarification",
            text=c,
            sources=[],
            effective_query=query,
            n_clarifications_asked_after=n_after,
        )
    ans = (out.get("final_answer") or "").strip()
    used: list[SourceChunk] = out.get("used_chunks") or []
    return ClarifyTurnResult(
        response_type="answer",
        text=ans,
        sources=used,
        effective_query=query,
        n_clarifications_asked_after=n_clarif_sent_before,
    )
