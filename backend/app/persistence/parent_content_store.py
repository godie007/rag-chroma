"""
Almacenamiento en disco de textos "padre" (p. ej. tramo de artículo) para RAG parent–child.
Los embeddings viven en Chroma (hijos); aquí el texto entregado al LLM.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("rag_qc")

_STORE_VERSION = 1


class ParentContentStore:
    def __init__(self, file_path: Path) -> None:
        self._path = file_path
        # parent_id -> {text, source, section_type, ...}
        self._parents: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "parents" in raw:
                self._parents = {k: dict(v) for k, v in raw["parents"].items() if isinstance(v, dict)}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("No se pudo leer %s: %s; store vacío", self._path, e)
            self._parents = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _STORE_VERSION, "parents": self._parents}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(self._path)

    def set_parent(self, parent_id: str, text: str, **meta: Any) -> None:
        self._parents[parent_id] = {"text": text, **meta}
        self._save()

    def set_parents_batch(self, items: list[tuple[str, str, dict[str, Any]]]) -> None:
        for pid, text, extra in items:
            self._parents[pid] = {"text": text, **extra}
        self._save()

    def get_text(self, parent_id: str) -> str | None:
        rec = self._parents.get(parent_id)
        if not rec:
            return None
        t = rec.get("text")
        return t if isinstance(t, str) else None

    def mget(self, parent_ids: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in parent_ids:
            t = self.get_text(p)
            if t is not None:
                out[p] = t
        return out

    def get_metadata(self, parent_id: str) -> dict[str, Any]:
        """Metadatos del padre sin el campo text (para el LLM / UI)."""
        rec = self._parents.get(parent_id)
        if not rec:
            return {}
        m = {k: v for k, v in rec.items() if k != "text"}
        return m

    def delete_by_source(self, source: str) -> int:
        name = (source or "").strip()
        if not name:
            return 0
        before = len(self._parents)
        to_del = [k for k, v in self._parents.items() if v.get("source") == name]
        for k in to_del:
            del self._parents[k]
        n = before - len(self._parents)
        if to_del:
            self._save()
        return n

    def clear(self) -> None:
        self._parents = {}
        try:
            if self._path.is_file():
                self._path.unlink()
        except OSError as e:
            logger.warning("No se pudo borrar parent store: %s", e)

    def has_any(self) -> bool:
        return bool(self._parents)
