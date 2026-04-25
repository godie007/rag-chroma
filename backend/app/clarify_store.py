"""Estado in-memory de hilos para el bucle de clarificación (Iterative Query Refinement)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

_LOCK = threading.Lock()
_TTL_SEC = 7200.0
_STORE: dict[str, _Entry] = {}
_MAX_TURNS_KEPT = 8
_MAX_SUMMARY_LEN = 480


@dataclass
class ClarifyContext:
    """Texto acumulado para el siguiente retriever, rondas de clarificación e historial Q/A resuelto."""

    cumulative_query: str
    clarifications_asked: int = 0
    awaiting_clarification: bool = True
    # Turnos ya cerrados (respuesta final) para el evaluador; no se borra al contestar.
    turn_history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _Entry:
    ctx: ClarifyContext
    touched: float = field(default_factory=time.time)


def new_thread_id() -> str:
    return str(uuid.uuid4())


def _prune() -> None:
    now = time.time()
    for k in [k for k, e in _STORE.items() if now - e.touched > _TTL_SEC]:
        _STORE.pop(k, None)


def get_context(thread_id: str) -> ClarifyContext | None:
    with _LOCK:
        _prune()
        e = _STORE.get(thread_id)
        if e is None:
            return None
        e.touched = time.time()
        return e.ctx


def _summary_answer(text: str) -> str:
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= _MAX_SUMMARY_LEN:
        return t
    return t[: _MAX_SUMMARY_LEN - 1] + "…"


def set_after_clarification(thread_id: str, effective_query_just_used: str, clarifications_asked: int) -> None:
    with _LOCK:
        _prune()
        prev = _STORE.get(thread_id)
        hist = list(prev.ctx.turn_history) if prev is not None else []
        _STORE[thread_id] = _Entry(
            ctx=ClarifyContext(
                cumulative_query=effective_query_just_used,
                clarifications_asked=clarifications_asked,
                awaiting_clarification=True,
                turn_history=hist,
            )
        )


def mark_answered(thread_id: str, user_question: str, answer_text: str) -> None:
    """Tras un turno con respuesta completa: conserva resúmenes Q/A para el evaluador; reinicia ronda de clarificación."""
    uq = (user_question or "").strip()[:4000]
    with _LOCK:
        _prune()
        e = _STORE.get(thread_id)
        hist: list[dict[str, str]] = list(e.ctx.turn_history) if e is not None else []
        hist.append(
            {
                "question": uq,
                "answer_summary": _summary_answer(answer_text),
            }
        )
        if len(hist) > _MAX_TURNS_KEPT:
            hist = hist[-_MAX_TURNS_KEPT:]
        _STORE[thread_id] = _Entry(
            ctx=ClarifyContext(
                cumulative_query="",
                clarifications_asked=0,
                awaiting_clarification=False,
                turn_history=hist,
            )
        )


def clear_thread(thread_id: str) -> None:
    with _LOCK:
        _STORE.pop(thread_id, None)


def thread_history_for_evaluator(thread_id: str | None, *, max_turns: int = 3) -> str:
    """
    Texto a inyectar en el mensaje de usuario del nodo *evaluate* (no visible al usuario final).
    Vacío si no hay historial.
    """
    if not thread_id:
        return ""
    ctx = get_context(thread_id)
    if not ctx or not ctx.turn_history:
        return ""
    turns = ctx.turn_history[-max_turns:]
    lines = [
        "## Historial reciente del hilo (turnos previos resueltos)",
        "",
    ]
    for t in turns:
        q = (t.get("question") or "").strip()
        a = (t.get("answer_summary") or "").strip()
        if not q and not a:
            continue
        lines.append(f"- **Pregunta:** {q}")
        lines.append(f"  **Respondido (resumen):** {a}")
        lines.append("")
    return "\n".join(lines).strip() + "\n" if len(lines) > 2 else ""


def clarifications_sent_before(thread_id: str | None) -> int:
    """Cuántas clarificaciones ya se enviaron al usuario en este hilo (para el nodo de evaluación)."""
    if not thread_id:
        return 0
    ctx = get_context(thread_id)
    if not ctx or not ctx.awaiting_clarification:
        return 0
    return ctx.clarifications_asked


def build_effective_query(thread_id: str | None, user_text: str) -> tuple[str, bool]:
    """
    Devuelve (texto para retrieve/generate, is_followup).
    - Si el hilo espera matiz tras una *clarification*, combina con la consulta acumulada.
    - Si ya hubo una respuesta final pero hay historial, enriquece el retrieve para el seguimiento.
    """
    if not thread_id or not (ctx := get_context(thread_id)):
        return user_text, False
    if ctx.awaiting_clarification:
        q = f"{ctx.cumulative_query}\n\n(Respuesta o matiz del usuario: {user_text})"
        return q, True
    if ctx.turn_history:
        last = ctx.turn_history[-1]
        tq = (last.get("question") or "")[:200]
        sm = (last.get("answer_summary") or "")[:320]
        prefix = (
            f"[Contexto de seguimiento — consulta previa: {tq}. Resumen de lo respondido: {sm}]\n\n"
        )
        return prefix + user_text, True
    return user_text, False
