"""System prompts personalizables por canal (web vs WhatsApp), persistidos en JSON.

Valores vacíos o claves ausentes usan los defaults de ``app.prompts`` (código), sin reiniciar uvicorn.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal

from app.prompts import SYSTEM_NO_RETRIEVAL, SYSTEM_RAG

_DEFAULTS: dict[str, str] = {
    "system_rag_web": SYSTEM_RAG,
    "system_rag_whatsapp": SYSTEM_RAG,
    "system_no_retrieval_web": SYSTEM_NO_RETRIEVAL,
    "system_no_retrieval_whatsapp": SYSTEM_NO_RETRIEVAL,
}

logger = logging.getLogger("rag_qc")

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROMPTS_FILE = _BACKEND_DIR / "system_prompts.json"
_lock = threading.Lock()

Channel = Literal["web", "whatsapp"]


def prompt_storage_path() -> Path:
    return _PROMPTS_FILE


def _read_raw() -> dict[str, Any]:
    if not _PROMPTS_FILE.is_file():
        return {}
    try:
        data = json.loads(_PROMPTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("System prompts: no se pudo leer %s (%s); defaults del código", _PROMPTS_FILE, e)
        return {}
    return data if isinstance(data, dict) else {}


def get_effective_prompts() -> dict[str, str]:
    """Resuelve los cuatro textos (RAG y sin contexto) para web y WhatsApp."""
    with _lock:
        raw = _read_raw()
    def _g(key: str) -> str:
        default = _DEFAULTS[key]
        v = raw.get(key)
        if v is None:
            return default
        if not isinstance(v, str):
            return default
        s = v.strip()
        if not s:
            return default
        return v

    return {k: _g(k) for k in _DEFAULTS}


def get_system_rag_for_channel(channel: Channel) -> str:
    p = get_effective_prompts()
    if channel == "whatsapp":
        return p["system_rag_whatsapp"]
    return p["system_rag_web"]


def get_system_no_retrieval_for_channel(channel: Channel) -> str:
    p = get_effective_prompts()
    if channel == "whatsapp":
        return p["system_no_retrieval_whatsapp"]
    return p["system_no_retrieval_web"]


def _write_raw(data: dict[str, Any]) -> None:
    _PROMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PROMPTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(_PROMPTS_FILE)


def update_prompts(
    *,
    system_rag_web: str | None = None,
    system_rag_whatsapp: str | None = None,
    system_no_retrieval_web: str | None = None,
    system_no_retrieval_whatsapp: str | None = None,
) -> dict[str, str]:
    """Fusiona actualizaciones. Cadena vacía o solo espacios elimina la clave (vuelve al default de código)."""
    keys = (
        "system_rag_web",
        "system_rag_whatsapp",
        "system_no_retrieval_web",
        "system_no_retrieval_whatsapp",
    )
    values = (
        system_rag_web,
        system_rag_whatsapp,
        system_no_retrieval_web,
        system_no_retrieval_whatsapp,
    )
    with _lock:
        data = _read_raw()
        for k, v in zip(keys, values, strict=True):
            if v is None:
                continue
            if not isinstance(v, str):
                continue
            if not v.strip():
                data.pop(k, None)
            elif v == _DEFAULTS.get(k, ""):
                data.pop(k, None)
            else:
                data[k] = v
        if data:
            _write_raw(data)
        elif _PROMPTS_FILE.is_file():
            try:
                _PROMPTS_FILE.unlink()
            except OSError as e:
                logger.warning("No se pudo borrar %s: %s", _PROMPTS_FILE, e)
    return get_effective_prompts()


def clear_prompt_overrides() -> None:
    """Borra el archivo de overrides; los efectivos vuelven a ser los de ``app.prompts``."""
    with _lock:
        if _PROMPTS_FILE.is_file():
            _PROMPTS_FILE.unlink()
