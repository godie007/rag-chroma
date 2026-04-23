"""
Expansión semántica de la consulta para el vector search en el bucle de clarificación.
"""

from __future__ import annotations

import logging
from typing import Any

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


def expand_query(query: str, chat: ChatOpenAI) -> str:
    """
    Devuelve la query consolidada con sinónimos para el vector search.
    Si el LLM falla o la entrada es vacía, retorna la query original.
    """
    q = (query or "").strip()
    if not q:
        return query or " "
    try:
        struct_llm = chat.bind(temperature=0, max_tokens=500).with_structured_output(ExpandedQuery)
        chain: Any = _EXPAND_PROMPT | struct_llm
        result: ExpandedQuery = chain.invoke({"query": q})
        out = (result.combined or "").strip()
        return out if out else q
    except Exception as e:
        logger.warning("Expansión semántica de consulta falló: %s; se usa la query original", e)
        return q
