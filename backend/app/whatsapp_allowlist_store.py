"""Persistencia de la allowlist de WhatsApp (dígitos E.164 sin +).

Si existe ``backend/whatsapp_allowlist.json``, solo se usa esa lista (la UI la gestiona).
Si no existe el archivo, se usa ``WHATSAPP_ALLOWED_SENDER_NUMBERS`` del .env.

Lista vacía = permitir todos los chats 1:1 (mismo criterio que .env vacío).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal

from app.config import Settings

logger = logging.getLogger("rag_qc.whatsapp")

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ALLOWLIST_FILE = _BACKEND_DIR / "whatsapp_allowlist.json"
_lock = threading.Lock()


def allowlist_storage_path() -> Path:
    return _ALLOWLIST_FILE


def _normalize_digits(s: str) -> str:
    return "".join(c for c in str(s) if c.isdigit())


def _numbers_from_env_csv(raw: str) -> list[str]:
    if not raw.strip():
        return []
    out: set[str] = set()
    for part in raw.split(","):
        d = _normalize_digits(part)
        if len(d) >= 8:
            out.add(d)
    return sorted(out)


def get_allowlist_numbers(settings: Settings) -> tuple[list[str], Literal["file", "env"]]:
    with _lock:
        if _ALLOWLIST_FILE.is_file():
            try:
                raw_txt = _ALLOWLIST_FILE.read_text(encoding="utf-8")
                data = json.loads(raw_txt)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "WhatsApp allowlist: no se pudo leer %s (%s); se usa .env",
                    _ALLOWLIST_FILE,
                    e,
                )
            else:
                nums = data.get("numbers", [])
                if not isinstance(nums, list):
                    nums = []
                out: list[str] = []
                for x in nums:
                    d = _normalize_digits(str(x))
                    if len(d) >= 8:
                        out.append(d)
                return sorted(set(out)), "file"
    return _numbers_from_env_csv(settings.whatsapp_allowed_sender_numbers), "env"


def effective_allowed_sender_digit_sets(settings: Settings) -> frozenset[str]:
    nums, _ = get_allowlist_numbers(settings)
    if not nums:
        return frozenset()
    return frozenset(nums)


def set_allowlist_numbers(numbers: list[Any]) -> list[str]:
    out: list[str] = []
    for x in numbers:
        d = _normalize_digits(str(x))
        if len(d) >= 8:
            out.append(d)
    out = sorted(set(out))
    payload = json.dumps({"numbers": out}, ensure_ascii=False, indent=2) + "\n"
    with _lock:
        _ALLOWLIST_FILE.write_text(payload, encoding="utf-8")
    logger.info("WhatsApp allowlist: guardada en %s (%d número(s))", _ALLOWLIST_FILE, len(out))
    return out


def add_allowlist_number(settings: Settings, raw: str) -> list[str]:
    d = _normalize_digits(raw)
    if len(d) < 8:
        raise ValueError("Se requieren al menos 8 dígitos (sin + ni espacios).")
    cur, _ = get_allowlist_numbers(settings)
    cur = sorted(set(cur + [d]))
    return set_allowlist_numbers(cur)


def remove_allowlist_number(settings: Settings, raw: str) -> list[str]:
    d = _normalize_digits(raw)
    cur, _ = get_allowlist_numbers(settings)
    cur = sorted(set(x for x in cur if x != d))
    return set_allowlist_numbers(cur)


def delete_allowlist_storage_file() -> None:
    with _lock:
        _ALLOWLIST_FILE.unlink(missing_ok=True)
    logger.info("WhatsApp allowlist: eliminado %s; vuelve a aplicarse .env", _ALLOWLIST_FILE)
