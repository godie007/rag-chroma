"""Webhook Evolution API → RAG (/chat lógico) → respuesta por sendText."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import threading
import time
from typing import Any

import httpx
from fastapi import Request

from app.config import Settings
from app.conversation_commands import NEW_CHAT_COMMAND, is_new_chat_command, new_chat_acknowledgement
from app.preprocess import strip_pdf_glyph_tokens
from app.rag_service import RAGService

logger = logging.getLogger("rag_qc.evolution")

_STATUS_JID = re.compile(r"status@|broadcast", re.I)
_PN_JID = re.compile(r"@s\.whatsapp\.net$|@c\.us$", re.I)

# Tamaño máximo al volcar JSON en log DEBUG (evita logs enormes).
_WEBHOOK_BODY_LOG_MAX = 12_000

# Evolution/Baileys puede entregar el mismo messages.upsert dos veces (p. ej. notify + append) → dos respuestas.
_DEDUP_LOCK = threading.Lock()
_DEDUP_SEEN: dict[str, float] = {}
_DEDUP_TTL_SEC = 180.0
_DEDUP_MAX_KEYS = 8_000


def _dedup_message_key(instance: str, remote_jid: str, data: dict[str, Any]) -> str | None:
    """Incluye siempre el mismo `remote_jid` que usamos para allowlist y envío (evita colisiones entre chats)."""
    key = data.get("key")
    if not isinstance(key, dict):
        return None
    mid = key.get("id")
    if not isinstance(mid, str) or not mid.strip():
        return None
    rj = remote_jid.strip()
    if not rj:
        return None
    return f"{instance.strip()}|{rj}|{mid.strip()}"


def _is_duplicate_upsert(dkey: str) -> bool:
    """True si ya procesamos este mensaje hace poco (no volver a responder)."""
    now = time.monotonic()
    with _DEDUP_LOCK:
        cutoff = now - _DEDUP_TTL_SEC
        stale = [k for k, t in _DEDUP_SEEN.items() if t < cutoff]
        for k in stale:
            del _DEDUP_SEEN[k]
        if len(_DEDUP_SEEN) > _DEDUP_MAX_KEYS:
            oldest = sorted(_DEDUP_SEEN.items(), key=lambda kv: kv[1])
            for k, _ in oldest[: max(1, len(_DEDUP_SEEN) - _DEDUP_MAX_KEYS // 2)]:
                del _DEDUP_SEEN[k]
        if dkey in _DEDUP_SEEN:
            return True
        _DEDUP_SEEN[dkey] = now
        return False


def extract_webhook_api_key(request: Request, body: dict[str, Any]) -> str:
    """Clave que envía Evolution en el POST (header y/o cuerpo; nombres variables según versión)."""
    for hk in ("apikey", "Apikey", "API-Key", "x-api-key", "X-Api-Key"):
        h = request.headers.get(hk)
        if h and str(h).strip():
            return str(h).strip()
    for bk in ("apikey", "apiKey", "API_KEY"):
        v = body.get(bk)
        if v is None:
            continue
        s = str(v).strip() if not isinstance(v, str) else v.strip()
        if s:
            return s
    return ""


def _keys_equal_constant_time(a: str, b: str) -> bool:
    try:
        return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
    except Exception:
        return False


async def verify_evolution_webhook_credential(
    got: str,
    instance: str | None,
    *,
    settings: Settings,
) -> bool:
    """
    Evolution envía en el JSON del webhook `apikey` = token de la instancia (hash), no AUTHENTICATION_API_KEY,
    cuando AUTHENTICATION_EXPOSE_IN_FETCH_INSTANCES=true (channel.service sendDataWebhook).
    Aceptamos: misma cadena que EVOLUTION_API_KEY (global) o token válido para `instance` vía fetchInstances.
    """
    if not got or got == "Apikey not found":
        return False
    expected = settings.evolution_api_key.strip()
    if expected and _keys_equal_constant_time(got, expected):
        return True
    name = instance.strip() if isinstance(instance, str) else ""
    if not name or not expected:
        return False
    base = settings.evolution_api_base_url.rstrip("/")
    url = f"{base}/instance/fetchInstances"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers={"apikey": got}, params={"instanceName": name})
    except httpx.RequestError as e:
        logger.warning("Evolution verify: fetchInstances no alcanzable: %s", e)
        return False
    return r.status_code == 200


def _extract_text_from_message(message: dict[str, Any] | None) -> str | None:
    if not message or not isinstance(message, dict):
        return None
    conv = message.get("conversation")
    if isinstance(conv, str) and conv.strip():
        return conv.strip()
    ext = message.get("extendedTextMessage")
    if isinstance(ext, dict):
        t = ext.get("text")
        if isinstance(t, str) and t.strip():
            return t.strip()
    return None


def _is_pn_whatsapp_jid(jid: str) -> bool:
    """JID de chat 1:1 por número (no @lid)."""
    return bool(jid and _PN_JID.search(jid))


def _choose_peer_jid_for_inbound(remote_jid: str | None, remote_jid_alt: str | None) -> str | None:
    """
    Elige un único JID de conversación para este mensaje entrante.

    Con identificadores LID, `remoteJid` puede ser `...@lid` y el número real en `remoteJidAlt`.
    Responder usando solo el trozo del LID rompe el enrutado y puede mezclar hilos; priorizamos el JID PN
    cuando el primario es @lid y el alternativo es número @s.whatsapp.net / @c.us.
    """
    rj = remote_jid.strip() if isinstance(remote_jid, str) and remote_jid.strip() else None
    alt = remote_jid_alt.strip() if isinstance(remote_jid_alt, str) and remote_jid_alt.strip() else None
    if rj and "@g.us" in rj:
        return rj
    if rj and rj.lower().endswith("@lid") and alt and _is_pn_whatsapp_jid(alt):
        return alt
    if alt and alt.lower().endswith("@lid") and rj and _is_pn_whatsapp_jid(rj):
        return rj
    return rj or alt


def _remote_jid_for_reply(data: dict[str, Any]) -> str | None:
    key = data.get("key")
    if not isinstance(key, dict):
        return None
    if key.get("fromMe") is True:
        return None
    jid = _choose_peer_jid_for_inbound(key.get("remoteJid"), key.get("remoteJidAlt"))
    if not isinstance(jid, str) or not jid:
        return None
    if _STATUS_JID.search(jid):
        return None
    return jid


def _number_for_send_api(remote_jid: str) -> str:
    """Destino para Evolution sendText: mismo chat que el remitente (JID completo si no es solo dígitos)."""
    if "@g.us" in remote_jid:
        return remote_jid
    if "@" in remote_jid:
        user = remote_jid.split("@", 1)[0]
        device = user.split(":", 1)[0]
        if device.isdigit():
            return device
        return remote_jid
    return remote_jid


def _jid_user_digits(remote_jid: str) -> str:
    """Parte usuario del JID 1:1 solo dígitos (p. ej. 573136413967 desde 573136413967@s.whatsapp.net)."""
    if "@g.us" in remote_jid:
        return ""
    user = remote_jid.split("@", 1)[0]
    user = user.split(":", 1)[0]
    return "".join(c for c in user if c.isdigit())


def _allowed_sender_digit_sets(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    out: set[str] = set()
    for part in raw.split(","):
        d = "".join(c for c in part if c.isdigit())
        if d:
            out.add(d)
    return frozenset(out)


def _incoming_sender_allowed(remote_jid: str, allowed: frozenset[str]) -> bool:
    if not allowed:
        return True
    d = _jid_user_digits(remote_jid)
    if not d:
        return False
    if d in allowed:
        return True
    for a in allowed:
        if len(a) >= 9 and d.endswith(a):
            return True
    return False


async def _evolution_composing_pulse_loop(
    *,
    settings: Settings,
    instance: str,
    number: str,
    pulse_ms: int,
) -> None:
    """Renueva composing hasta que la tarea sea cancelada (Evolution bloquea ~pulse_ms por petición)."""
    base = settings.evolution_api_base_url.rstrip("/")
    url = f"{base}/chat/sendPresence/{instance}"
    headers = {
        "Content-Type": "application/json",
        "apikey": settings.evolution_api_key,
    }
    payload = {"number": number, "presence": "composing", "delay": int(pulse_ms)}
    pulse_sec = max(pulse_ms / 1000.0, 1.0)
    timeout = httpx.Timeout(connect=15.0, read=pulse_sec + 30.0, write=30.0, pool=15.0)
    try:
        while True:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.post(url, headers=headers, json=payload)
                    if r.status_code >= 400:
                        logger.debug(
                            "Evolution sendPresence: %s %s",
                            r.status_code,
                            r.text[:200],
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("Evolution sendPresence: %s", e)
    except asyncio.CancelledError:
        raise


async def send_evolution_text(
    *,
    settings: Settings,
    instance: str,
    number: str,
    text: str,
) -> None:
    base = settings.evolution_api_base_url.rstrip("/")
    url = f"{base}/message/sendText/{instance}"
    headers = {
        "Content-Type": "application/json",
        "apikey": settings.evolution_api_key,
    }
    payload = {"number": number, "text": text[:8000]}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        logger.error(
            "Evolution sendText falló: %s %s — %s",
            r.status_code,
            url,
            r.text[:500],
        )
        r.raise_for_status()


async def handle_evolution_payload(
    body: dict[str, Any],
    *,
    settings: Settings,
    rag: RAGService,
) -> dict[str, Any]:
    if not settings.evolution_enabled:
        return {"ok": False, "ignored": True, "reason": "evolution_disabled"}

    event = body.get("event")
    if settings.evolution_webhook_log_body:
        try:
            raw = json.dumps(body, ensure_ascii=False, default=str)
        except TypeError:
            raw = str(body)
        logger.info(
            "Evolution webhook cuerpo (truncado): %s",
            raw[:_WEBHOOK_BODY_LOG_MAX] + ("…" if len(raw) > _WEBHOOK_BODY_LOG_MAX else ""),
        )

    if event != "messages.upsert":
        logger.info("Evolution webhook ignorado: event=%s", event)
        return {"ok": True, "ignored": True, "reason": "event_not_handled"}

    instance = body.get("instance")
    if not isinstance(instance, str) or not instance.strip():
        return {"ok": False, "error": "missing_instance"}

    data = body.get("data")
    if not isinstance(data, dict):
        return {"ok": True, "ignored": True, "reason": "no_data"}

    remote_jid = _remote_jid_for_reply(data)
    if not remote_jid:
        logger.info(
            "Evolution messages.upsert sin respuesta (fromMe/status/etc.): instance=%s key=%s",
            instance,
            data.get("key"),
        )
        return {"ok": True, "ignored": True, "reason": "no_remote_jid"}

    if not settings.evolution_reply_in_groups and "@g.us" in remote_jid:
        return {"ok": True, "ignored": True, "reason": "groups_disabled"}

    allow = _allowed_sender_digit_sets(settings.evolution_allowed_sender_numbers)
    if not _incoming_sender_allowed(remote_jid, allow):
        logger.info(
            "Evolution messages.upsert ignorado: remitente no permitido jid=%s (allowlist activa)",
            remote_jid,
        )
        return {"ok": True, "ignored": True, "reason": "sender_not_allowed"}

    dkey = _dedup_message_key(instance.strip(), remote_jid, data)
    if dkey and _is_duplicate_upsert(dkey):
        logger.info(
            "Evolution messages.upsert ignorado: duplicado (mismo key.id) instancia=%s",
            instance.strip(),
        )
        return {"ok": True, "ignored": True, "reason": "duplicate_upsert"}

    text_in = _extract_text_from_message(data.get("message") if isinstance(data.get("message"), dict) else None)
    if not text_in:
        logger.info(
            "Evolution messages.upsert sin texto (audio/imagen/etc.): instance=%s jid=%s",
            instance,
            remote_jid,
        )
        return {"ok": True, "ignored": True, "reason": "no_text"}

    push = data.get("pushName") if isinstance(data.get("pushName"), str) else None
    logger.info(
        "Evolution mensaje entrante | instancia=%s | jid=%s | pushName=%s | texto=%r",
        instance.strip(),
        remote_jid,
        push,
        text_in if len(text_in) <= 2000 else text_in[:2000] + "…",
    )

    number = _number_for_send_api(remote_jid)
    if is_new_chat_command(text_in):
        logger.info(
            "Evolution comando %s | instancia=%s | jid=%s",
            NEW_CHAT_COMMAND,
            instance.strip(),
            remote_jid,
        )
        await send_evolution_text(
            settings=settings,
            instance=instance.strip(),
            number=number,
            text=new_chat_acknowledgement(),
        )
        return {"ok": True, "replied": True, "replied_to": number, "reason": "new_chat_command"}

    inst = instance.strip()
    typing_task: asyncio.Task[None] | None = None
    if settings.evolution_typing_indicator:
        typing_task = asyncio.create_task(
            _evolution_composing_pulse_loop(
                settings=settings,
                instance=inst,
                number=number,
                pulse_ms=settings.evolution_typing_pulse_ms,
            ),
            name=f"evolution-typing-{inst}",
        )
    try:
        if settings.evolution_typing_indicator:
            contexts = await asyncio.to_thread(rag.retrieve, text_in)
            answer, _used = await asyncio.to_thread(rag.generate, text_in, contexts)
        else:
            contexts = rag.retrieve(text_in)
            answer, _used = rag.generate(text_in, contexts)
    finally:
        if typing_task is not None:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

    answer_out = strip_pdf_glyph_tokens(answer)
    logger.info(
        "Evolution enviando respuesta al remitente | instancia=%s | destino=%s | texto_len=%s",
        instance.strip(),
        number,
        len(answer_out),
    )
    await send_evolution_text(
        settings=settings,
        instance=instance.strip(),
        number=number,
        text=answer_out,
    )
    return {"ok": True, "replied": True, "replied_to": number}
