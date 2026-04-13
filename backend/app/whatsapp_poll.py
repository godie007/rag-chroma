"""WhatsApp (API Flask :8090 ↔ GOWA :3000 en el Jetson): recepción vía polling y/o webhook → RAG → POST …/send/text.

Contrato habitual de la API Flask en el Jetson (consultar README del dispositivo si cambia):

- ``GET /messages/recent?limit=…`` — últimos mensajes de todos los chats; cada ítem incluye
  ``is_from_me: true|false``. El RAG ignora ``from_me`` salvo ``WHATSAPP_PROCESS_FROM_ME=true``
  (y aplica filtro de eco de respuestas del bot).
- ``GET /messages?chat_jid=<jid>&limit=…`` — historial de un chat concreto; mismo campo
  ``is_from_me``. Modo polling ``chats``: se usa tras ``GET /chats`` para recorrer cada JID.

Cada **conversación** (``chat_jid`` / bucket de eco) es independiente: la deduplicación de IDs de
mensaje y el registro de eco del bot van por chat, de modo que hablar contigo mismo en un hilo no
mezcla estado con otro chat. La respuesta siempre se envía al JID/teléfono derivado del mensaje
que disparó el procesamiento.

En **polling**, los mensajes deben traer ``timestamp`` (API Jetson): se ignoran los anteriores al
arranque del worker para no contestar todo el historial de ``/messages/recent`` al iniciar uvicorn.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import Request

from app.config import Settings
from app.conversation_commands import NEW_CHAT_COMMAND, is_new_chat_command, new_chat_acknowledgement
from app.preprocess import strip_pdf_glyph_tokens
from app.rag_service import RAGService

logger = logging.getLogger("rag_qc.whatsapp")

_STATUS_OR_BROADCAST = re.compile(r"status@|broadcast", re.I)

# Hora UTC en que arrancó el bucle de polling (una vez por vida del worker). Ver run_whatsapp_poll_loop.
_WHATSAPP_POLL_STARTED_AT_UTC: datetime | None = None

_DEDUP_LOCK = threading.Lock()
# /messages/recent repite los mismos IDs en cada poll: LRU sin caducidad temporal corta.
_DEDUP_SEEN: dict[str, float] = {}
_DEDUP_MAX_KEYS = 50_000

_ECHO_LOCK = threading.Lock()
# Texto que acabamos de enviar con /send/text (por chat); si vuelve en el poll, no pasar otra vez por el RAG.
_ECHO_SENT_AT: dict[str, float] = {}
_ECHO_TTL_SEC = 900.0
_ECHO_MAX_KEYS = 8000
_MAX_OUTBOUND_CHARS = 8000


def _normalize_echo_text(text: str) -> str:
    return "\n".join(text.strip().splitlines())


def _echo_chat_bucket(chat_jid: str) -> str:
    cj = chat_jid.strip()
    if "@g.us" in cj:
        return cj.lower()
    digits = _jid_user_digits(cj)
    return digits if digits else cj.lower()


def _echo_fingerprint_key(chat_jid: str, normalized_body: str) -> str:
    h = hashlib.sha256(normalized_body.encode("utf-8")).hexdigest()
    return f"echo:{_echo_chat_bucket(chat_jid)}|{h}"


def _purge_echo_expired(now: float) -> None:
    stale = [k for k, exp in _ECHO_SENT_AT.items() if exp < now]
    for k in stale:
        del _ECHO_SENT_AT[k]
    if len(_ECHO_SENT_AT) > _ECHO_MAX_KEYS:
        oldest = sorted(_ECHO_SENT_AT.items(), key=lambda kv: kv[1])
        for k, _ in oldest[: max(1, len(_ECHO_SENT_AT) - _ECHO_MAX_KEYS // 2)]:
            del _ECHO_SENT_AT[k]


def register_bot_sent_echo(chat_jid: str, text_sent: str) -> None:
    """Registrar el cuerpo enviado para ignorarlo cuando reaparezca en /messages/recent."""
    chunk = _normalize_echo_text(text_sent[:_MAX_OUTBOUND_CHARS])
    if not chunk:
        return
    key = _echo_fingerprint_key(chat_jid, chunk)
    now = time.monotonic()
    with _ECHO_LOCK:
        _purge_echo_expired(now)
        _ECHO_SENT_AT[key] = now + _ECHO_TTL_SEC


def is_recent_bot_sent_echo(chat_jid: str, content: str) -> bool:
    chunk = _normalize_echo_text(content[:_MAX_OUTBOUND_CHARS])
    if not chunk:
        return False
    key = _echo_fingerprint_key(chat_jid, chunk)
    now = time.monotonic()
    with _ECHO_LOCK:
        _purge_echo_expired(now)
        exp = _ECHO_SENT_AT.get(key)
        return exp is not None and exp > now


def _allowed_sender_digit_sets(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    out: set[str] = set()
    for part in raw.split(","):
        d = "".join(c for c in part if c.isdigit())
        if d:
            out.add(d)
    return frozenset(out)


def _jid_user_digits(chat_jid: str) -> str:
    if "@g.us" in chat_jid:
        return ""
    user = chat_jid.split("@", 1)[0]
    user = user.split(":", 1)[0]
    return "".join(c for c in user if c.isdigit())


def _incoming_sender_allowed(chat_jid: str, allowed: frozenset[str]) -> bool:
    """
    Compara dígitos del JID con la lista (solo dígitos en .env, sin +).
    Acepta: igualdad exacta; sufijo (lista corta vs JID E.164); prefijo inverso
    (lista en E.164 y JID solo nacional); últimas 10 cifras iguales (p. ej. CO +57).
    """
    if not allowed:
        return True
    d = _jid_user_digits(chat_jid)
    if not d:
        return False
    if d in allowed:
        return True
    for a in allowed:
        if not a:
            continue
        if len(a) >= 8 and len(d) >= 8:
            if d.endswith(a) or a.endswith(d):
                return True
        if len(d) >= 10 and len(a) >= 10 and d[-10:] == a[-10:]:
            return True
    return False


def _chat_jid_to_e164_phone(chat_jid: str) -> str | None:
    """Solo chats 1:1; devuelve +57321… o None si es grupo u otro JID."""
    if not chat_jid or "@g.us" in chat_jid:
        return None
    if _STATUS_OR_BROADCAST.search(chat_jid):
        return None
    d = _jid_user_digits(chat_jid)
    if not d or len(d) < 8:
        return None
    return f"+{d}"


def _is_duplicate_message_id(dedup_key: str) -> bool:
    """True si este mensaje ya se vio en esta conversación. ``dedup_key`` = bucket|id (no global)."""
    now = time.monotonic()
    key = dedup_key.strip()
    if not key:
        return True
    with _DEDUP_LOCK:
        if len(_DEDUP_SEEN) > _DEDUP_MAX_KEYS:
            oldest = sorted(_DEDUP_SEEN.items(), key=lambda kv: kv[1])
            for k, _ in oldest[: max(1, len(_DEDUP_SEEN) - _DEDUP_MAX_KEYS // 2)]:
                del _DEDUP_SEEN[k]
        if key in _DEDUP_SEEN:
            return True
        _DEDUP_SEEN[key] = now
        return False


def _str_from(v: Any) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _parse_whatsapp_api_timestamp(v: Any) -> datetime | None:
    """
    Parsea el ``timestamp`` de la API Flask (:8090), p. ej. ``2026-04-13T00:00:00Z``.
    Acepta ISO-8601 con Z, offset, entero/float Unix en s o ms.
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(v, (int, float)):
        x = float(v)
        if x > 1e12:
            x /= 1000.0
        try:
            return datetime.fromtimestamp(x, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_bool(v: Any) -> bool | None:
    if v is True or v is False:
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        if v == 1:
            return True
        if v == 0:
            return False
    if isinstance(v, str):
        low = v.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return None


def normalize_whatsapp_inbound(m: dict[str, Any]) -> dict[str, Any] | None:
    """
    Unifica distintas formas de JSON (Flask/GOWA/Baileys) a:
    id, chat_jid, content, is_from_me (bool|None), pushName (str|None).
    """
    if not isinstance(m, dict):
        return None

    mid = (
        _str_from(m.get("id"))
        or _str_from(m.get("messageId"))
        or _str_from(m.get("message_id"))
    )
    key = m.get("key")
    if not mid and isinstance(key, dict):
        mid = _str_from(key.get("id"))

    chat_jid = (
        _str_from(m.get("chat_jid"))
        or _str_from(m.get("chatJid"))
        or _str_from(m.get("remoteJid"))
        or _str_from(m.get("remote_jid"))
        or _str_from(m.get("from"))
    )

    content = _str_from(m.get("content"))
    if not content:
        content = _str_from(m.get("body"))
    if not content:
        content = _str_from(m.get("text"))
    if not content:
        msg = m.get("message")
        if isinstance(msg, str):
            content = _str_from(msg)
        elif isinstance(msg, dict):
            content = _str_from(msg.get("conversation"))
            if not content and isinstance(msg.get("extendedTextMessage"), dict):
                content = _str_from(msg["extendedTextMessage"].get("text"))

    if not chat_jid or not content:
        return None

    fm: bool | None = None
    for k in ("is_from_me", "isFromMe", "from_me", "fromMe"):
        b = _coerce_bool(m.get(k))
        if b is not None:
            fm = b
            break
    if fm is None and isinstance(key, dict):
        b = _coerce_bool(key.get("fromMe"))
        if b is not None:
            fm = b

    push = (
        _str_from(m.get("pushName"))
        or _str_from(m.get("push_name"))
        or _str_from(m.get("sender_name"))
    )

    ts = m.get("timestamp")
    ts_s = str(ts).strip() if ts is not None else ""
    ts_utc = _parse_whatsapp_api_timestamp(ts)

    if not mid:
        h = hashlib.sha256(f"{chat_jid}|{ts_s}|{content}".encode("utf-8")).hexdigest()[:24]
        mid = f"adhoc:{h}"

    return {
        "id": mid,
        "chat_jid": chat_jid,
        "content": content,
        "is_from_me": fm,
        "pushName": push,
        "timestamp": ts,
        "timestamp_utc": ts_utc,
    }


def parse_recent_messages_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae lista de mensajes de GET /messages/recent o GET /messages?chat_jid=… (y variantes de envoltorio JSON)."""
    candidates: list[Any] = []

    results = data.get("results")
    if isinstance(results, dict):
        inner = results.get("data")
        if isinstance(inner, list):
            candidates.extend(inner)
    if isinstance(data.get("data"), list):
        candidates.extend(data["data"])
    if isinstance(data.get("messages"), list):
        candidates.extend(data["messages"])
    if isinstance(data.get("results"), list):
        candidates.extend(data["results"])

    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for i, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        oid = id(item)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(item)
    return out


def verify_whatsapp_webhook_request(request: Request, settings: Settings) -> bool:
    """Si WHATSAPP_WEBHOOK_SECRET está definido, exige el mismo valor por cabecera o Bearer."""
    expected = settings.whatsapp_webhook_secret.strip()
    if not expected:
        return True

    def _eq(got: str) -> bool:
        ga = got.strip().encode("utf-8")
        exp = expected.encode("utf-8")
        if len(ga) != len(exp):
            return False
        return secrets.compare_digest(ga, exp)

    h = request.headers.get("x-whatsapp-webhook-secret") or request.headers.get("X-WhatsApp-Webhook-Secret")
    if h and _eq(h):
        return True
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token and _eq(token):
            return True
    return False


async def send_whatsapp_text(
    *,
    settings: Settings,
    phone: str,
    text: str,
    echo_register_chat_jid: str | None = None,
) -> None:
    base = settings.whatsapp_api_base_url.rstrip("/")
    url = f"{base}/send/text"
    headers = {"Content-Type": "application/json"}
    if settings.whatsapp_api_key.strip():
        headers["Authorization"] = f"Bearer {settings.whatsapp_api_key.strip()}"
    truncated = text[:_MAX_OUTBOUND_CHARS]
    payload = {"phone": phone, "message": truncated}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        logger.error("WhatsApp send/text falló: %s %s — %s", r.status_code, url, r.text[:500])
        r.raise_for_status()
    if echo_register_chat_jid and echo_register_chat_jid.strip():
        register_bot_sent_echo(echo_register_chat_jid.strip(), truncated)


async def process_normalized_whatsapp_message(
    norm: dict[str, Any],
    *,
    settings: Settings,
    rag: RAGService,
    source: str = "poll",
) -> dict[str, Any]:
    """Procesa un mensaje ya normalizado (dedup por chat, allowlist, RAG, respuesta)."""
    msg_id = str(norm.get("id") or "").strip()
    if not msg_id:
        return {"ok": False, "error": "missing_id"}

    chat_jid = str(norm.get("chat_jid") or "").strip()
    if not chat_jid:
        return {"ok": False, "error": "missing_chat_jid"}

    conv_bucket = _echo_chat_bucket(chat_jid)
    dedup_key = f"{conv_bucket}|{msg_id}"
    if _is_duplicate_message_id(dedup_key):
        return {"ok": True, "ignored": True, "reason": "duplicate"}

    if norm.get("is_from_me") is True:
        if not settings.whatsapp_process_from_me:
            logger.info(
                "WhatsApp %s: ignorado is_from_me=true (si escribes desde el mismo WA que GOWA, "
                "WHATSAPP_PROCESS_FROM_ME=true en backend/.env y reinicia)",
                source,
            )
            return {"ok": True, "ignored": True, "reason": "from_me"}

    if not settings.whatsapp_reply_in_groups and "@g.us" in chat_jid:
        return {"ok": True, "ignored": True, "reason": "groups_disabled"}

    allow_src = settings.whatsapp_allowed_sender_numbers.strip()
    allow = _allowed_sender_digit_sets(allow_src)
    if not _incoming_sender_allowed(chat_jid, allow):
        logger.info(
            "WhatsApp %s: remitente no permitido chat_jid=%s dígitos_extraídos=%s allowlist=%s",
            source,
            chat_jid,
            _jid_user_digits(chat_jid),
            sorted(allow),
        )
        return {"ok": True, "ignored": True, "reason": "sender_not_allowed"}

    content = str(norm.get("content") or "").strip()
    if not content:
        return {"ok": True, "ignored": True, "reason": "no_text"}

    if is_recent_bot_sent_echo(chat_jid, content):
        logger.info(
            "WhatsApp %s: ignorado eco de respuesta del bot (mismo texto en este chat, ~%.0f s)",
            source,
            _ECHO_TTL_SEC,
        )
        return {"ok": True, "ignored": True, "reason": "bot_sent_echo"}

    if norm.get("is_from_me") is True and settings.whatsapp_process_from_me:
        lim = int(settings.whatsapp_from_me_max_question_chars)
        if len(content) > lim:
            logger.info(
                "WhatsApp %s: ignorado from_me con texto largo (%d>%d chars) — suele ser respuesta del bot, no re-RAG",
                source,
                len(content),
                lim,
            )
            return {"ok": True, "ignored": True, "reason": "from_me_long_skip"}

    phone = _chat_jid_to_e164_phone(chat_jid)
    if not phone:
        logger.info("WhatsApp %s: sin teléfono E.164 para chat_jid=%s", source, chat_jid)
        return {"ok": True, "ignored": True, "reason": "no_e164_phone"}

    push = norm.get("pushName")
    push_s = push if isinstance(push, str) else None
    logger.info(
        "WhatsApp mensaje entrante [%s] | jid=%s | pushName=%s | texto=%r",
        source,
        chat_jid,
        push_s,
        content if len(content) <= 2000 else content[:2000] + "…",
    )

    if is_new_chat_command(content):
        logger.info("WhatsApp comando %s | jid=%s", NEW_CHAT_COMMAND, chat_jid)
        ack = new_chat_acknowledgement()
        await send_whatsapp_text(
            settings=settings,
            phone=phone,
            text=ack,
            echo_register_chat_jid=chat_jid,
        )
        return {"ok": True, "replied": True, "replied_to": phone, "reason": "new_chat_command"}

    contexts = await asyncio.to_thread(rag.retrieve, content)
    answer, _used = await asyncio.to_thread(rag.generate, content, contexts)
    answer_out = strip_pdf_glyph_tokens(answer)
    logger.info("WhatsApp enviando respuesta [%s] | destino=%s | len=%s", source, phone, len(answer_out))
    await send_whatsapp_text(
        settings=settings,
        phone=phone,
        text=answer_out,
        echo_register_chat_jid=chat_jid,
    )
    return {"ok": True, "replied": True, "replied_to": phone}


async def process_raw_whatsapp_inbound_dict(
    raw: dict[str, Any],
    *,
    settings: Settings,
    rag: RAGService,
    source: str,
) -> dict[str, Any]:
    norm = normalize_whatsapp_inbound(raw)
    if not norm:
        return {"ok": False, "error": "unrecognized_payload"}
    return await process_normalized_whatsapp_message(norm, settings=settings, rag=rag, source=source)


def _whatsapp_request_headers(settings: Settings) -> dict[str, str] | None:
    if settings.whatsapp_api_key.strip():
        return {"Authorization": f"Bearer {settings.whatsapp_api_key.strip()}"}
    return None


async def _whatsapp_get_json(
    settings: Settings,
    path: str,
    params: dict[str, Any],
    *,
    timeout: float = 45.0,
) -> dict[str, Any]:
    base = settings.whatsapp_api_base_url.rstrip("/")
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, params=params, headers=_whatsapp_request_headers(settings))
    r.raise_for_status()
    body = r.json()
    return body if isinstance(body, dict) else {}


async def _fetch_recent_raw(settings: Settings) -> dict[str, Any]:
    return await _whatsapp_get_json(
        settings,
        "/messages/recent",
        {"limit": settings.whatsapp_poll_limit},
    )


def parse_chat_jids_from_chats_payload(data: dict[str, Any]) -> list[str]:
    """Respuesta GET /chats → results.data[].jid (README Jetson)."""
    results = data.get("results")
    if not isinstance(results, dict):
        return []
    inner = results.get("data")
    if not isinstance(inner, list):
        return []
    out: list[str] = []
    for item in inner:
        if not isinstance(item, dict):
            continue
        jid = item.get("jid") or item.get("chat_jid")
        if isinstance(jid, str) and jid.strip():
            out.append(jid.strip())
    return out


def _msg_timestamp_key(m: dict[str, Any]) -> str:
    t = m.get("timestamp")
    if t is None:
        return ""
    parsed = _parse_whatsapp_api_timestamp(t)
    if parsed is not None:
        return f"{parsed.timestamp():.6f}"
    return str(t)


def _poll_message_not_before_threshold(
    *,
    started_at_utc: datetime,
    skew_sec: float,
) -> datetime:
    return started_at_utc - timedelta(seconds=float(skew_sec))


async def _process_raw_message_items(
    raw_items: list[dict[str, Any]],
    *,
    settings: Settings,
    rag: RAGService,
    log_keys: bool,
    raw_for_log: dict[str, Any] | None,
    poll_not_before_utc: datetime | None = None,
    poll_start_skew_sec: float = 0.0,
) -> None:
    if log_keys and raw_for_log is not None:
        logger.debug("WhatsApp polling: claves JSON %s", list(raw_for_log.keys()))
    if not raw_items:
        return
    raw_items = sorted(raw_items, key=_msg_timestamp_key)
    threshold: datetime | None = None
    if poll_not_before_utc is not None:
        threshold = _poll_message_not_before_threshold(
            started_at_utc=poll_not_before_utc,
            skew_sec=poll_start_skew_sec,
        )
    skipped_stale = 0
    skipped_no_ts = 0
    for item in raw_items:
        if threshold is not None:
            ts_item = _parse_whatsapp_api_timestamp(item.get("timestamp"))
            if ts_item is None:
                skipped_no_ts += 1
                continue
            if ts_item < threshold:
                skipped_stale += 1
                continue
        if not settings.whatsapp_process_from_me:
            if _coerce_bool(item.get("is_from_me")) is True:
                continue
        try:
            norm = normalize_whatsapp_inbound(item)
            if not norm:
                continue
            await process_normalized_whatsapp_message(norm, settings=settings, rag=rag, source="poll")
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError as e:
            logger.exception("WhatsApp polling: fallo HTTP al responder: %s", e)
        except Exception:
            logger.exception("WhatsApp polling: error procesando mensaje")
    if skipped_stale or skipped_no_ts:
        logger.debug(
            "WhatsApp polling: omitidos por ventana de arranque — antiguos=%d sin_timestamp=%d (umbral UTC≈%s)",
            skipped_stale,
            skipped_no_ts,
            threshold.isoformat() if threshold is not None else "n/a",
        )


async def _poll_iteration_recent(settings: Settings, rag: RAGService) -> None:
    raw = await _fetch_recent_raw(settings)
    raw_items = parse_recent_messages_payload(raw)
    gate = _WHATSAPP_POLL_STARTED_AT_UTC if settings.whatsapp_poll_skip_messages_before_start else None
    await _process_raw_message_items(
        raw_items,
        settings=settings,
        rag=rag,
        log_keys=settings.whatsapp_poll_log_body,
        raw_for_log=raw,
        poll_not_before_utc=gate,
        poll_start_skew_sec=settings.whatsapp_poll_start_skew_sec,
    )


async def _poll_iteration_chats(settings: Settings, rag: RAGService) -> None:
    chats_body = await _whatsapp_get_json(
        settings,
        "/chats",
        {"limit": settings.whatsapp_chats_poll_limit},
    )
    jids = parse_chat_jids_from_chats_payload(chats_body)
    if settings.whatsapp_poll_log_body:
        logger.debug("WhatsApp polling [/chats]: %d jid(s)", len(jids))

    merged: list[dict[str, Any]] = []
    for jid in jids:
        if not settings.whatsapp_reply_in_groups and "@g.us" in jid:
            continue
        try:
            msg_body = await _whatsapp_get_json(
                settings,
                "/messages",
                {
                    "chat_jid": jid,
                    "limit": settings.whatsapp_messages_per_chat_limit,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("WhatsApp polling: error GET /messages chat_jid=%s: %s", jid, e)
            continue
        merged.extend(parse_recent_messages_payload(msg_body))

    gate = _WHATSAPP_POLL_STARTED_AT_UTC if settings.whatsapp_poll_skip_messages_before_start else None
    await _process_raw_message_items(
        merged,
        settings=settings,
        rag=rag,
        log_keys=False,
        raw_for_log=None,
        poll_not_before_utc=gate,
        poll_start_skew_sec=settings.whatsapp_poll_start_skew_sec,
    )


async def run_whatsapp_poll_loop(
    *,
    settings_provider: Callable[[], Settings],
    rag_provider: Callable[[], RAGService | None],
) -> None:
    global _WHATSAPP_POLL_STARTED_AT_UTC
    _WHATSAPP_POLL_STARTED_AT_UTC = datetime.now(timezone.utc)

    s0 = settings_provider()
    mode = s0.whatsapp_poll_mode
    base = s0.whatsapp_api_base_url.rstrip("/")
    if mode == "chats":
        logger.info(
            "WhatsApp polling: modo chats → %s/chats + /messages?chat_jid=…",
            base,
        )
    else:
        logger.info("WhatsApp polling: modo recent → %s/messages/recent", base)
    if s0.whatsapp_poll_skip_messages_before_start:
        logger.info(
            "WhatsApp polling: solo mensajes con timestamp API ≥ arranque − %.0fs (evita bucle con histórico)",
            s0.whatsapp_poll_start_skew_sec,
        )
    try:
        while True:
            settings = settings_provider()
            interval = max(float(settings.whatsapp_poll_interval_sec), 0.5)
            rag = rag_provider()
            if rag is None:
                logger.debug("WhatsApp polling: RAG no disponible, esperando…")
                await asyncio.sleep(interval)
                continue
            try:
                if settings.whatsapp_poll_mode == "chats":
                    await _poll_iteration_chats(settings, rag)
                else:
                    await _poll_iteration_recent(settings, rag)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "WhatsApp polling: error (%s): %s",
                    settings.whatsapp_poll_mode,
                    e,
                )
                await asyncio.sleep(interval)
                continue

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("WhatsApp polling: bucle detenido")
        raise
