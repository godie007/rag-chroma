from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuración desde variables de entorno (.env bajo backend/)."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_chat_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    # Límite de tokens de salida del chat RAG (respuestas largas / prompts detallados).
    openai_chat_max_output_tokens: int = Field(default=2096, ge=256, le=128_000)
    openai_embedding_model: str = "text-embedding-3-small"
    openai_api_base: str | None = None
    chroma_persist_directory: str = "./chroma_db"
    chroma_collection_name: str = "internal_knowledge"
    chroma_ingest_batch_size: int = 128
    chunk_size: int = 1280
    chunk_overlap: int = 256
    chunk_min_chars: int = 400
    chunk_merge_hard_max: int = 0
    top_k: int = 6
    use_mmr: bool = True
    mmr_fetch_k: int = 80
    mmr_lambda: float = 0.91
    retrieve_max_l2_distance: float = 1.3
    retrieve_relevance_margin: float = 0.10
    retrieve_elbow_l2_gap: float = 0.0
    # Si es False, no se llama al LLM antes de recuperar (siempre perfil "normal"; ahorra coste/latencia).
    llm_retrieval_profile: bool = True
    # Incluye 4444 (Vite según README) y 5173/5174 (puertos por defecto/alternativo de Vite).
    cors_origins: str = (
        "http://localhost:4444,http://127.0.0.1:4444,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )
    max_upload_bytes: int = 200 * 1024 * 1024

    # WhatsApp: API Flask :8090 (GOWA Docker :3000 en Jetson). Envío: POST /send/text (phone + message).
    # Recepción: polling recent | chats, y/o POST …/webhooks/whatsapp (p. ej. desde whatsapp_receiver.sh).
    whatsapp_enabled: bool = False
    whatsapp_api_base_url: str = "http://192.168.1.254:8090"
    whatsapp_poll_enabled: bool = True
    # recent = GET /messages/recent?limit=… (cada msg: is_from_me) | chats = GET /chats + GET /messages?chat_jid=… por chat
    whatsapp_poll_mode: Literal["recent", "chats"] = "recent"
    whatsapp_poll_interval_sec: float = Field(default=4.0, ge=0.5, le=120.0)
    whatsapp_poll_limit: int = Field(default=50, ge=5, le=200)
    whatsapp_chats_poll_limit: int = Field(default=25, ge=1, le=100)
    whatsapp_messages_per_chat_limit: int = Field(default=40, ge=5, le=200)
    whatsapp_api_key: str = ""
    whatsapp_webhook_secret: str = ""
    whatsapp_reply_in_groups: bool = False
    whatsapp_poll_log_body: bool = False
    whatsapp_allowed_sender_numbers: str = ""
    # true = procesa también is_from_me (mensajes salientes vistos por GOWA). Necesario si escribes desde el mismo
    # número/WhatsApp que está en el Jetson; en producción puede re-encolar respuestas largas del bot → usar heurística.
    whatsapp_process_from_me: bool = False
    whatsapp_from_me_max_question_chars: int = Field(default=4000, ge=500, le=32000)
    # Polling: no ejecutar RAG sobre el histórico que devuelve /messages/recent o /messages al arrancar.
    # Solo mensajes con timestamp API >= (hora de arranque del bucle de poll − skew). Webhook no usa este filtro.
    whatsapp_poll_skip_messages_before_start: bool = True
    whatsapp_poll_start_skew_sec: float = Field(default=90.0, ge=0.0, le=86400.0)

    @field_validator("whatsapp_poll_mode", mode="before")
    @classmethod
    def coerce_whatsapp_poll_mode(cls, v: Any) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return "recent"
        s = str(v).strip().lower()
        return s if s in ("recent", "chats") else "recent"

    @field_validator("whatsapp_api_key", "whatsapp_webhook_secret", mode="after")
    @classmethod
    def strip_whatsapp_secrets(cls, v: str) -> str:
        return v.strip().strip("\ufeff").strip()

    @field_validator("whatsapp_allowed_sender_numbers", mode="after")
    @classmethod
    def strip_whatsapp_allowed_senders(cls, v: str) -> str:
        return v.strip().strip("\ufeff").strip()

    @field_validator("openai_chat_model", "openai_embedding_model", mode="after")
    @classmethod
    def normalize_model_ids(cls, v: str) -> str:
        """Quita espacios/comillas y corrige typos frecuentes (p. ej. gpt-5o-mini → gpt-4o-mini)."""
        s = v.strip().strip("'\"")
        aliases = {
            "gpt-5o-mini": "gpt-4o-mini",
            "gpt5o-mini": "gpt-4o-mini",
            "gpt-50-mini": "gpt-4o-mini",
        }
        return aliases.get(s.lower(), s)

    @field_validator("chroma_persist_directory", mode="after")
    @classmethod
    def chroma_persist_absolute(cls, v: str) -> str:
        """Resuelve rutas relativas respecto al directorio backend/."""
        p = Path(v).expanduser()
        if not p.is_absolute():
            p = (_BACKEND_DIR / p).resolve()
        else:
            p = p.resolve()
        return str(p)
