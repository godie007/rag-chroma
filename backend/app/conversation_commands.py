"""Comandos de conversación (mismo criterio en /chat y en WhatsApp via Evolution)."""

# Solo este texto (tras strip), sin más palabras.
NEW_CHAT_COMMAND = "/nuevo"


def is_new_chat_command(text: str) -> bool:
    return text.strip().lower() == NEW_CHAT_COMMAND


def new_chat_acknowledgement() -> str:
    return (
        "Listo: conversación nueva. Seguimos sin memoria de mensajes anteriores; "
        "cuando quieras, escribe tu siguiente pregunta."
    )
