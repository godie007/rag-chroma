"""Bridge HTTP :8090 ↔ GOWA (go-whatsapp-web-multidevice) :3000.

Expone el mismo contrato que la API Flask documentada para ``whatsapp_poll.py``:
``GET /chats``, ``GET /messages/recent``, ``GET /messages``, ``POST /send/text``.

Variables de entorno (opcionales):
- ``GOWA_UPSTREAM_URL`` — base de GOWA (default ``http://127.0.0.1:3000``).
- ``GOWA_DEVICE_ID`` — cabecera ``X-Device-Id`` si usas multi-device.
- ``GOWA_BASIC_USER`` / ``GOWA_BASIC_PASS`` — Basic auth hacia GOWA si está activado.
- ``WHATSAPP_BRIDGE_API_KEY`` — si se define, el bridge exige ``Authorization: Bearer <valor>``
  (mismo valor que ``WHATSAPP_API_KEY`` en el backend RAG).

Arranque: ``python -m uvicorn app.whatsapp_gowa_bridge:app --host 127.0.0.1 --port 8090``
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("rag_qc.whatsapp_bridge")

GOWA_BASE = os.environ.get("GOWA_UPSTREAM_URL", "http://127.0.0.1:3000").rstrip("/")
BRIDGE_KEY = os.environ.get("WHATSAPP_BRIDGE_API_KEY", "").strip()
GOWA_DEVICE_ID = os.environ.get("GOWA_DEVICE_ID", "").strip()
GOWA_BASIC_USER = os.environ.get("GOWA_BASIC_USER", "").strip()
GOWA_BASIC_PASS = os.environ.get("GOWA_BASIC_PASS", "").strip()
REQUEST_TIMEOUT = float(os.environ.get("WHATSAPP_BRIDGE_TIMEOUT", "60"))
RECENT_MAX_CHATS = int(os.environ.get("WHATSAPP_BRIDGE_RECENT_MAX_CHATS", "20"))


def _gowa_auth() -> httpx.Auth | None:
    if GOWA_BASIC_USER and GOWA_BASIC_PASS:
        return httpx.BasicAuth(GOWA_BASIC_USER, GOWA_BASIC_PASS)
    return None


def _upstream_headers() -> dict[str, str]:
    h: dict[str, str] = {}
    if GOWA_DEVICE_ID:
        h["X-Device-Id"] = GOWA_DEVICE_ID
    return h


async def verify_bridge_key(request: Request) -> None:
    if not BRIDGE_KEY:
        return
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer ") and auth[7:].strip() == BRIDGE_KEY:
        return
    raise HTTPException(status_code=401, detail="Invalid or missing bridge API key")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        auth=_gowa_auth(),
        follow_redirects=True,
    ) as client:
        app.state.http = client
        yield


app = FastAPI(title="WhatsApp GOWA bridge", lifespan=lifespan)


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


async def _gowa_get(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{GOWA_BASE}{path if path.startswith('/') else '/' + path}"
    r = await client.get(url, params=params or {}, headers=_upstream_headers())
    if r.status_code >= 400:
        logger.warning("GOWA GET %s → %s %s", path, r.status_code, (r.text or "")[:300])
    r.raise_for_status()
    return r.json()


async def _gowa_post_json(client: httpx.AsyncClient, path: str, body: dict[str, Any]) -> Any:
    url = f"{GOWA_BASE}{path if path.startswith('/') else '/' + path}"
    r = await client.post(
        url,
        json=body,
        headers={**_upstream_headers(), "Content-Type": "application/json"},
    )
    if r.status_code >= 400:
        logger.warning("GOWA POST %s → %s %s", path, r.status_code, (r.text or "")[:500])
    r.raise_for_status()
    return r.json()


def _chat_sort_ts(chat: dict[str, Any]) -> str:
    return str(
        chat.get("last_message_time")
        or chat.get("updated_at")
        or chat.get("created_at")
        or "",
    )


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    client = _client(request)
    try:
        await _gowa_get(client, "/chats", {"limit": 1, "offset": 0})
        return {"ok": True, "gowa_reachable": True, "gowa_base": GOWA_BASE}
    except Exception as e:
        logger.warning("health: GOWA no accesible: %s: %s", type(e).__name__, e)
        return {"ok": True, "gowa_reachable": False, "gowa_base": GOWA_BASE, "error": str(e)}


@app.get("/chats")
async def chats(
    request: Request,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: None = Depends(verify_bridge_key),
) -> Any:
    client = _client(request)
    return await _gowa_get(client, "/chats", {"limit": limit, "offset": offset})


@app.get("/messages")
async def messages_by_chat(
    request: Request,
    chat_jid: str = Query(..., min_length=3),
    limit: int = Query(50, ge=5, le=200),
    offset: int = Query(0, ge=0),
    _: None = Depends(verify_bridge_key),
) -> Any:
    client = _client(request)
    enc = quote(chat_jid.strip(), safe="")
    return await _gowa_get(
        client,
        f"/chat/{enc}/messages",
        {"limit": limit, "offset": offset},
    )


@app.get("/messages/recent")
async def messages_recent(
    request: Request,
    limit: int = Query(50, ge=5, le=200),
    _: None = Depends(verify_bridge_key),
) -> dict[str, Any]:
    """Agrega mensajes de varios chats (GOWA no tiene un único endpoint equivalente)."""
    client = _client(request)
    chats_body = await _gowa_get(client, "/chats", {"limit": 25, "offset": 0})
    results = chats_body.get("results")
    chat_list = results.get("data") if isinstance(results, dict) else None
    if not isinstance(chat_list, list):
        return {"results": {"data": []}}

    chat_list_sorted = sorted(
        [c for c in chat_list if isinstance(c, dict)],
        key=_chat_sort_ts,
        reverse=True,
    )
    max_chats = max(1, min(RECENT_MAX_CHATS, len(chat_list_sorted)))
    per_chat = max(5, min(50, (limit + max_chats - 1) // max_chats))

    jids: list[str] = []
    for chat in chat_list_sorted[:max_chats]:
        jid = chat.get("jid")
        if isinstance(jid, str) and jid.strip():
            jids.append(jid.strip())

    async def fetch_messages(jid: str) -> list[dict[str, Any]]:
        enc = quote(jid, safe="")
        try:
            msg_body = await _gowa_get(
                client,
                f"/chat/{enc}/messages",
                {"limit": per_chat, "offset": 0},
            )
        except httpx.HTTPError as e:
            logger.debug("recent: omitiendo jid=%s: %s", jid, e)
            return []
        inner = msg_body.get("results")
        data = inner.get("data") if isinstance(inner, dict) else None
        if not isinstance(data, list):
            return []
        return [m for m in data if isinstance(m, dict)]

    chunks = await asyncio.gather(*[fetch_messages(j) for j in jids])
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for block in chunks:
        for m in block:
            mid = str(m.get("id") or "").strip()
            if mid:
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
            if not str(m.get("content") or "").strip():
                continue
            merged.append(m)

    def ts_key(item: dict[str, Any]) -> str:
        return str(item.get("timestamp") or item.get("created_at") or "")

    merged.sort(key=ts_key)
    if len(merged) > limit:
        merged = merged[-limit:]
    return {"results": {"data": merged}}


class SendTextBody(BaseModel):
    phone: str = Field(..., min_length=3)
    message: str = Field(..., min_length=1)


def _phone_to_gowa_recipient(phone: str) -> str:
    p = phone.strip().replace(" ", "")
    if "@" in p:
        return p
    digits = "".join(c for c in p if c.isdigit())
    if not digits or len(digits) < 8:
        raise HTTPException(status_code=400, detail="Invalid phone (need E.164 digits or JID)")
    return f"{digits}@s.whatsapp.net"


@app.post("/send/text")
async def send_text(
    request: Request,
    body: SendTextBody,
    _: None = Depends(verify_bridge_key),
) -> Any:
    client = _client(request)
    recipient = _phone_to_gowa_recipient(body.phone)
    return await _gowa_post_json(
        client,
        "/send/message",
        {"phone": recipient, "message": body.message},
    )
