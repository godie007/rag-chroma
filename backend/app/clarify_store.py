"""Estado in-memory de hilos para el bucle de clarificación (Iterative Query Refinement)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

_LOCK = threading.Lock()
_TTL_SEC = 7200.0
_STORE: dict[str, _Entry] = {}


@dataclass
class ClarifyContext:
    """Texto acumulado para el siguiente retriever y cuántas preguntas de clarificación llevamos."""

    cumulative_query: str
    clarifications_asked: int = 0
    awaiting_clarification: bool = True


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


def set_after_clarification(thread_id: str, effective_query_just_used: str, clarifications_asked: int) -> None:
    with _LOCK:
        _prune()
        _STORE[thread_id] = _Entry(
            ctx=ClarifyContext(
                cumulative_query=effective_query_just_used,
                clarifications_asked=clarifications_asked,
                awaiting_clarification=True,
            )
        )


def clear_thread(thread_id: str) -> None:
    with _LOCK:
        _STORE.pop(thread_id, None)


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
    Si hay hilo en espera de matiz, combina con la consulta acumulada.
    """
    if not thread_id or not (ctx := get_context(thread_id)):
        return user_text, False
    if not ctx.awaiting_clarification:
        return user_text, False
    q = f"{ctx.cumulative_query}\n\n(Respuesta o matiz del usuario: {user_text})"
    return q, True
