"""
Clasificación heurística de trozos (sin layout por página) para filtrar portada/índice.
"""

from __future__ import annotations

import re


def classify_section(text: str, *, char_offset: int, total_len: int) -> str:
    """
    Devuelve un tipo de sección almacenable en metadatos (Chroma) para excluir en retrieve.

    - total_len/char_offset: posición aproximada en el documento (sin nº de página del PDF).
    """
    t = (text or "").lower()
    if not t.strip():
        return "contenido"

    head = t[:240]
    # Inicio del documento (p. ej. portada, legal): solo heurística por posición + palabras
    if total_len > 0 and char_offset < int(total_len * 0.02):
        if any(
            k in t[:1_200]
            for k in (
                "isbn",
                "derechos reservados",
                "reimpresión",
                "primera edición",
                "editorial",
            )
        ):
            return "portada_indice"
        if "tabla" in head and "contenido" in head:
            return "portada_indice"
    if any(
        k in head
        for k in (
            "tabla de contenido",
            "índice",
            "indice",
            "contenido",
        )
    ) and not re.search(r"art[íi]culo\s+\d", head, re.I):
        if "artículo" not in head[:100]:
            return "indice"
    if re.match(r"^\s*art[íi]culo\s+[\d.]+", t) or re.match(
        r"^\s*art\.\s*[\d.]+", t, re.I
    ):
        return "articulo"
    if any(
        k in head
        for k in (
            "definici",
            "glosario",
            "términos técnicos",
            "terminos tecnicos",
        )
    ):
        return "definiciones"
    return "contenido"


def parse_exclude_section_types(csv: str) -> list[str]:
    s = (csv or "").strip()
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]
