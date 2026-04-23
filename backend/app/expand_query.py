"""
Expansión semántica de la consulta para el vector search (bucle de clarificación y RAG clásico).
"""

from __future__ import annotations

import logging
from typing import Any, cast

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger("rag_qc.expand_query")


class ExpandedQuery(BaseModel):
    """Salida estructurada: variantes y query consolidada para embedding."""

    variants: list[str] = Field(
        default_factory=list,
        description="3–5 variantes semánticas distintas del mismo concepto",
    )
    combined: str = Field(
        ...,
        description="Query enriquecida con sinónimos relevantes, lista para búsqueda vectorial MMR",
    )


_EXPAND_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """Eres un experto en recuperación semántica para normativa técnica (incl. eléctrica y de instalaciones).
Dado un texto de consulta, genera variantes semánticas que capturen el mismo concepto con términos técnicos y normativos distintos.

Reglas:
- Genera entre 3 y 5 variantes únicas
- Incluye sinónimos del dominio técnico y, si aplica, del contexto normativo colombiano (p. ej. RETIE, NTC, reglamentos locales)
- Si el usuario fue coloquial, añade el término técnico formal
- Puedes incluir términos en inglés si el estándar suele indexarse en ambos idiomas
- combined: versión enriquecida de la consulta original con los sinónimos más relevantes integrados, breve, lista para un vector search con MMR

Ejemplos de expansión (ilustrativos; adapta a la consulta recibida):
- "tuberías a la vista" → variantes: canalización expuesta, conduit visible, tubería superficial, identificación cromática de canalización, marcación de color; combined integra "canalizaciones a la vista, identificación cromática, codificación de color, RETIE"
- "cómo pongo los cables" → instalación de conductores, tendido, canalización, requisitos de instalación
- "falla eléctrica" → fallo, arco, cortocircuito, falla a tierra, interrupción, defecto de aislamiento""",
        ),
        ("human", "Consulta: {query}"),
    ]
)


def _build_expand_chain(chat: ChatOpenAI) -> Any:
    struct_llm = chat.bind(temperature=0, max_tokens=500).with_structured_output(ExpandedQuery)
    return _EXPAND_PROMPT | struct_llm


def _postprocess_combined(result: ExpandedQuery, q: str) -> str:
    out = (result.combined or "").strip()
    return out if out else q


async def expand_query_async(query: str, chat: ChatOpenAI) -> str:
    """
    Devuelve la query consolidada con sinónimos para el vector search (no bloquea con HTTP sync).
    No llames al LLM con entrada vacía: devuelve "" y deja el retrieve/generate al caller.
    """
    q = (query or "").strip()
    if not q:
        return ""
    try:
        chain = _build_expand_chain(chat)
        result: ExpandedQuery = cast(ExpandedQuery, await chain.ainvoke({"query": q}))
        return _postprocess_combined(result, q)
    except Exception as e:
        logger.warning("Expansión semántica de consulta falló: %s; se usa la query original", e)
        return q


def expand_query(query: str, chat: ChatOpenAI) -> str:
    """
    Variante síncrona (``invoke``). Preferible ``expand_query_async`` bajo un event loop activo.
    Con entrada vacía devuelve "" (sin LLM).
    """
    q = (query or "").strip()
    if not q:
        return ""
    try:
        chain = _build_expand_chain(chat)
        result: ExpandedQuery = cast(ExpandedQuery, chain.invoke({"query": q}))
        return _postprocess_combined(result, q)
    except Exception as e:
        logger.warning("Expansión semántica de consulta falló: %s; se usa la query original", e)
        return q
