"""Cliente Chroma persistido en disco (SQLite) y utilidades de permisos / carpeta."""

from __future__ import annotations

import gc
import logging
import shutil
import stat
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from app.config import Settings

logger = logging.getLogger("rag_qc")


def chroma_client_settings() -> chromadb.Settings:
    """allow_reset hace viable client.reset(); close() evita bloqueos SQLite al borrar la carpeta."""
    return chromadb.Settings(allow_reset=True)


def ensure_chroma_storage_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    except OSError:
        pass
    probe = path / ".chroma_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as e:
        raise RuntimeError(
            f"Chroma no puede escribir en {path}: {e}. "
            "Comprueba permisos (la carpeta debe permitir crear/editar sqlite y WAL). "
            "Si viene de un zip o otra máquina: chmod -R u+rwX sobre chroma_db o bórrala y reinicia."
        ) from e
    try:
        probe.unlink()
    except OSError:
        pass


def chmod_chroma_existing_files(path: Path) -> None:
    if not path.is_dir():
        return
    try:
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            try:
                mode = child.stat().st_mode
                child.chmod(mode | stat.S_IWUSR | stat.S_IRUSR)
            except OSError:
                pass
    except OSError:
        pass


class ChromaStore:
    """Encapsula el vector store local: apertura, reintentos de escritura y borrado del índice."""

    def __init__(self, settings: Settings, embeddings: OpenAIEmbeddings) -> None:
        self.settings = settings
        self.embeddings = embeddings
        self._vectorstore: Chroma | None = None
        self._open_client()

    def _open_client(self) -> None:
        persist = Path(self.settings.chroma_persist_directory)
        ensure_chroma_storage_writable(persist)
        chmod_chroma_existing_files(persist)
        self._vectorstore = Chroma(
            collection_name=self.settings.chroma_collection_name,
            embedding_function=self.embeddings,
            persist_directory=self.settings.chroma_persist_directory,
            client_settings=chroma_client_settings(),
        )

    @property
    def vectorstore(self) -> Chroma:
        if self._vectorstore is None:
            raise RuntimeError("Chroma no inicializado")
        return self._vectorstore

    def reconnect(self) -> None:
        """Cierra el cliente, refresca permisos y vuelve a abrir (p. ej. tras error sqlite readonly)."""
        persist = Path(self.settings.chroma_persist_directory)
        ensure_chroma_storage_writable(persist)
        chmod_chroma_existing_files(persist)
        vs = self._vectorstore
        self._vectorstore = None
        if vs is not None:
            try:
                vs._client.close()
            except Exception as e:
                logger.warning("Chroma close en reconnect: %s", e)
        gc.collect()
        self._vectorstore = Chroma(
            collection_name=self.settings.chroma_collection_name,
            embedding_function=self.embeddings,
            persist_directory=self.settings.chroma_persist_directory,
            client_settings=chroma_client_settings(),
        )

    def ensure_writable_before_ingest(self) -> None:
        """Comprueba carpeta y permisos antes de insertar lotes (misma ruta que la persistencia)."""
        persist = Path(self.settings.chroma_persist_directory)
        ensure_chroma_storage_writable(persist)
        chmod_chroma_existing_files(persist)

    def add_documents_batch(self, docs: list[Document], ids: list[str]) -> None:
        for attempt in range(3):
            try:
                self.vectorstore.add_documents(docs, ids=ids)
                return
            except Exception as e:
                msg = str(e).lower()
                if attempt < 2 and (
                    "readonly" in msg or "1032" in msg or "read-only" in msg or "read only" in msg
                ):
                    logger.warning(
                        "Chroma/sqlite no escribible (intento %s/3), permisos + reapertura del cliente: %s",
                        attempt + 1,
                        e,
                    )
                    self.reconnect()
                    continue
                raise

    def collection_count(self) -> int:
        try:
            return int(self.vectorstore._collection.count())
        except Exception:
            return 0

    def similarity_search_with_score(self, question: str, k: int):
        return self.vectorstore.similarity_search_with_score(question, k=k)

    def wipe_persist_directory_and_reopen(self) -> None:
        """Vacía la base vía API de Chroma, cierra SQLite y borra la carpeta en disco antes de reabrir.

        Sin ``client.close()`` el sqlite puede seguir abierto: ``rmtree`` falla o el directorio queda
        vacío mientras el proceso sigue leyendo el inode borrado (el contador no baja en /stats).
        """
        resolved = Path(self.settings.chroma_persist_directory)
        vs = self._vectorstore
        self._vectorstore = None
        if vs is not None:
            client = getattr(vs, "_client", None)
            if client is not None:
                try:
                    client.reset()
                except Exception as e:
                    logger.warning("Chroma reset() no completó (se intenta borrar en disco): %s", e)
                try:
                    client.close()
                except Exception as e:
                    logger.warning("Chroma close() tras wipe: %s", e)
        gc.collect()
        try:
            if resolved.exists():
                shutil.rmtree(resolved)
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise RuntimeError(
                f"No se pudo borrar o recrear la carpeta Chroma en {resolved}: {e}. "
                "Cierra otros procesos que usen esa carpeta y reintenta."
            ) from e
        ensure_chroma_storage_writable(resolved)
        chmod_chroma_existing_files(resolved)
        self._vectorstore = Chroma(
            collection_name=self.settings.chroma_collection_name,
            embedding_function=self.embeddings,
            persist_directory=self.settings.chroma_persist_directory,
            client_settings=chroma_client_settings(),
        )
