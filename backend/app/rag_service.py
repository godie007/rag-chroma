import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from langchain_core.documents import Document

try:
    from langchain_chroma.vectorstores import maximal_marginal_relevance
except ImportError:
    from langchain_community.vectorstores.utils import maximal_marginal_relevance
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.persistence import ChromaStore
from app.preprocess import chunk_text_for_ingest
from app.prompts import (
    RETRIEVAL_PROFILE_CLASSIFY_SYSTEM,
    build_no_retrieval_user_message,
    build_rag_user_message,
)
from app.prompt_store import get_system_no_retrieval_for_channel, get_system_rag_for_channel

logger = logging.getLogger(__name__)

GenerateChannel = Literal["web", "whatsapp"]

@dataclass
class SourceChunk:
    content: str
    metadata: dict[str, Any]


class RAGService:
    def reopen_chroma_client(self) -> None:
        """API pública por si hace falta forzar reapertura tras errores de disco (también usa ingesta internamente)."""
        self._chroma.reconnect()

    def __init__(self, settings: Settings):
        self.settings = settings
        common_openai: dict[str, Any] = {"api_key": settings.openai_api_key}
        if settings.openai_api_base:
            common_openai["base_url"] = settings.openai_api_base
        emb_kw: dict[str, Any] = {
            "model": settings.openai_embedding_model,
            **common_openai,
        }
        if settings.openai_embedding_dimensions is not None:
            emb_kw["dimensions"] = settings.openai_embedding_dimensions
        self.embeddings = OpenAIEmbeddings(**emb_kw)
        self.llm = ChatOpenAI(
            model=settings.openai_chat_model,
            temperature=settings.openai_chat_temperature,
            max_tokens=settings.openai_chat_max_output_tokens,
            **common_openai,
        )
        self._retrieval_profile_llm = self.llm.bind(temperature=0, max_tokens=64)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=len,
            separators=["\n\n", "```", "\n", ". ", "; ", " ", ""],
        )
        self._chroma = ChromaStore(settings, self.embeddings)
        # Una sola escritura a Chroma a la vez (SQLite + embeddings), evita contienda y bloqueos raros.
        self._index_write_lock = threading.Lock()

    def collection_chunk_count(self) -> int:
        return self._chroma.collection_count()

    def list_indexed_sources(self) -> list[str]:
        return self._chroma.list_distinct_sources()

    def delete_indexed_source(self, source_name: str) -> int:
        """Quita del índice todos los trozos asociados a una fuente (metadato ``source``)."""
        with self._index_write_lock:
            return self._chroma.delete_by_source(source_name)

    def clear_vector_index(self) -> None:
        """Borra la persistencia de Chroma en disco y recrea una colección vacía."""
        resolved = Path(self.settings.chroma_persist_directory)
        if resolved.resolve() in (Path("/").resolve(), Path.home().resolve()):
            raise ValueError(
                "CHROMA_PERSIST_DIRECTORY apunta a una ruta no permitida para borrado completo."
            )
        with self._index_write_lock:
            self._chroma.wipe_persist_directory_and_reopen()

    def ingest_text(self, text: str, source_name: str) -> int:
        """Parte el texto en fragmentos, genera embeddings y los guarda en Chroma.

        Devuelve cuántos fragmentos se indexaron (0 si el texto estaba vacío o solo espacios).
        """
        # --- 1. Entrada: nada que indexar ---
        if not text.strip():
            return 0

        with self._index_write_lock:
            # --- 2. Normalizar saltos de línea (mismo criterio que en preprocesado de archivos) ---
            text_norm = text.replace("\r\n", "\n").replace("\r", "\n")

            # --- 3. Fragmentar: prosa vs fences Markdown, fusionar trozos muy cortos ---
            merge_cap = self.settings.chunk_merge_hard_max or (self.settings.chunk_size * 2)
            merge_hard_max = max(merge_cap, self.settings.chunk_min_chars)
            chunk_strings = chunk_text_for_ingest(
                text_norm,
                self.splitter,
                chunk_size=self.settings.chunk_size,
                chunk_overlap=self.settings.chunk_overlap,
                merge_min_chars=self.settings.chunk_min_chars,
                merge_hard_max=merge_hard_max,
            )

            # --- 4. Empaquetar cada trozo como Document (contenido + metadatos para citas) ---
            documents: list[Document] = []
            for index, content in enumerate(chunk_strings):
                documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "source": source_name,
                            "chunk_id": f"{source_name}#{index}",
                        },
                    )
                )

            # --- 5. Un id único por vector en Chroma (obligatorio para upserts y trazabilidad) ---
            chroma_ids = [str(uuid4()) for _ in documents]

            # --- 6. Asegurar disco escribible antes de insertar (evita sqlite 1032 en algunos entornos) ---
            self._chroma.ensure_writable_before_ingest()

            # --- 7. Insertar en lotes para no saturar SQLite/memoria en PDFs enormes ---
            batch_size = max(1, self.settings.chroma_ingest_batch_size)
            for batch_start in range(0, len(documents), batch_size):
                batch_end = batch_start + batch_size
                self._chroma.add_documents_batch(
                    documents[batch_start:batch_end],
                    chroma_ids[batch_start:batch_end],
                )

            return len(documents)

    def _search_sorted_within_l2_cap(
        self,
        question: str,
        *,
        fetch_k: int,
        max_l2_distance: float,
    ) -> list[tuple[Document, float]]:
        """Vecinos por similitud; descarta los que superan el umbral L2; ordena de mejor a peor distancia."""
        scored = self._chroma.similarity_search_with_score(question, k=fetch_k)
        within_cap = [
            (doc, float(dist)) for doc, dist in scored if float(dist) <= max_l2_distance
        ]
        within_cap.sort(key=lambda pair: pair[1])
        return within_cap

    def _prefix_before_relevance_cutoff(
        self,
        sorted_by_distance: list[tuple[Document, float]],
        *,
        margin_boost: float = 0.0,
        skip_elbow: bool = False,
    ) -> list[tuple[Document, float]]:
        """Recorre candidatos ya ordenados y corta por margen respecto al mejor y opcionalmente por 'codo' L2."""
        if not sorted_by_distance:
            return []

        best_distance = sorted_by_distance[0][1]
        margin = self.settings.retrieve_relevance_margin + margin_boost
        elbow_gap = 0.0 if skip_elbow else self.settings.retrieve_elbow_l2_gap
        # Consultas débiles (distancia alta): margen más estrecho para no arrastrar ruido
        if best_distance >= 0.75:
            margin = min(margin, best_distance * 0.08)

        kept: list[tuple[Document, float]] = []
        previous_distance: float | None = None
        for doc, distance in sorted_by_distance:
            if distance > best_distance + margin:
                break
            if previous_distance is not None and elbow_gap > 0 and (distance - previous_distance) > elbow_gap:
                break
            kept.append((doc, distance))
            previous_distance = distance
        return kept

    @staticmethod
    def _scenario_qualified_question(question: str) -> bool:
        """True si la pregunta acota escenario de instalación (visible vs enterrada, etc.)."""
        q = question.lower()
        exposed = (
            "a la vista",
            "a la intemperie",
            "al descubierto",
            "instalación visible",
            "instalacion visible",
            "exposed",
            "at sight",
            "surface installation",
        )
        buried = (
            "enterrad",
            "subterráne",
            "subterrane",
            "bajo tierra",
            "empotrad",
            "buried",
            "underground",
        )
        return any(s in q for s in exposed + buried)

    def _embedding_query_for_retrieval(self, question: str, *, use_broad: bool) -> str:
        """Texto enviado al embedding de la consulta; en escenarios acotados enriquece el vector."""
        q = question.strip()
        if use_broad or not self._scenario_qualified_question(q):
            return q
        return (
            f"{q}\n\n"
            "Marcado o señalización distintiva en instalación visible, superficial o al descubierto; "
            "franjas, color, diferenciación respecto a otras redes; canalización y tubería cuando aplique."
        )

    @staticmethod
    def _coerce_retrieval_profile(raw: str) -> bool | None:
        """True = recuperación amplia, False = normal, None = respuesta ilegible."""
        t = raw.strip()
        if t.startswith("```"):
            t = "\n".join(t.split("\n")[1:])
            if "```" in t:
                t = t.split("```", 1)[0]
            t = t.strip()
        start, end = t.find("{"), t.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            return None
        val = data.get("retrieval")
        if not isinstance(val, str):
            return None
        v = val.strip().lower()
        if v == "broad":
            return True
        if v == "normal":
            return False
        return None

    def _infer_broad_retrieval(self, question: str) -> bool:
        try:
            message = self._retrieval_profile_llm.invoke(
                [
                    {"role": "system", "content": RETRIEVAL_PROFILE_CLASSIFY_SYSTEM},
                    {"role": "user", "content": question.strip()},
                ]
            )
            parsed = self._coerce_retrieval_profile(self._llm_message_text(message))
            if parsed is None:
                logger.warning("Clasificador de recuperación: JSON no interpretable; perfil normal")
                return False
            return parsed
        except Exception as exc:
            logger.warning("Clasificador de recuperación falló (%s); perfil normal", exc)
            return False

    def _chunks_by_relevance_order(
        self,
        ranked: list[tuple[Document, float]],
        question: str,
        k: int,
    ) -> list[SourceChunk]:
        """De un conjunto ya filtrado, elige hasta k trozos (MMR opcional) y devuelve ordenados por distancia."""
        if not ranked:
            return []

        documents = [doc for doc, _ in ranked]

        # --- MMR: diversificar entre candidatos cercanos en embedding ---
        if self.settings.use_mmr and len(documents) > k:
            distances = [dist for _, dist in ranked]
            texts = [doc.page_content for doc in documents]
            query_embedding = np.asarray(self.embeddings.embed_query(question), dtype=np.float32)
            doc_embeddings = np.asarray(self.embeddings.embed_documents(texts), dtype=np.float32)
            picked_indexes = maximal_marginal_relevance(
                query_embedding,
                doc_embeddings,
                lambda_mult=self.settings.mmr_lambda,
                k=k,
            )
            selected_pairs = [(documents[i], distances[i]) for i in picked_indexes]
        else:
            selected_pairs = ranked[:k]

        selected_pairs.sort(key=lambda pair: pair[1])
        return [
            SourceChunk(content=doc.page_content, metadata=dict(doc.metadata))
            for doc, _ in selected_pairs
        ]

    def retrieve(
        self,
        question: str,
        *,
        infer_broad_retrieval: bool = True,
    ) -> list[SourceChunk]:
        """Búsqueda vectorial → filtros → MMR opcional → orden por distancia.

        Si ``infer_broad_retrieval`` y ``llm_retrieval_profile`` están activos, una llamada
        ligera al LLM decide si ampliar ventana L2 y fragmentos para preguntas de cobertura.
        """
        k = self.settings.top_k
        use_broad = (
            infer_broad_retrieval
            and self.settings.llm_retrieval_profile
            and self._infer_broad_retrieval(question)
        )

        if use_broad:
            fetch_k = max(self.settings.mmr_fetch_k, k * 20, 120)
            max_l2_distance = min(2.2, self.settings.retrieve_max_l2_distance * 2.0)
        else:
            fetch_k = max(self.settings.mmr_fetch_k, k * 10, 40)
            max_l2_distance = self.settings.retrieve_max_l2_distance

        embed_q = self._embedding_query_for_retrieval(question, use_broad=use_broad)
        scenario_boost = not use_broad and self._scenario_qualified_question(question)

        candidates = self._search_sorted_within_l2_cap(
            embed_q,
            fetch_k=fetch_k,
            max_l2_distance=max_l2_distance,
        )
        if not candidates and use_broad:
            candidates = self._search_sorted_within_l2_cap(
                embed_q,
                fetch_k=fetch_k,
                max_l2_distance=min(2.35, self.settings.retrieve_max_l2_distance * 2.75),
            )
        if not candidates:
            return []

        if use_broad:
            focused = self._prefix_before_relevance_cutoff(
                candidates,
                margin_boost=0.35,
                skip_elbow=True,
            )
        else:
            focused = self._prefix_before_relevance_cutoff(
                candidates,
                margin_boost=0.16 if scenario_boost else 0.0,
            )
        if not focused:
            return []

        if use_broad:
            expanded_k = min(len(focused), max(k * 3, 15))
        else:
            expanded_k = min(len(focused), k + (5 if scenario_boost else 0))

        return self._chunks_by_relevance_order(focused, question, expanded_k)

    @staticmethod
    def _llm_message_text(message: Any) -> str:
        """Extrae texto de la respuesta del chat model (LangChain / proveedores)."""
        body = message.content if hasattr(message, "content") else message
        return str(body)

    @staticmethod
    def _format_context_block(contexts: list[SourceChunk]) -> str:
        """Une fragmentos con separador fijo (formato descrito en app.prompts.SYSTEM_RAG)."""
        parts: list[str] = []
        for chunk in contexts:
            source = chunk.metadata.get("source", "unknown")
            chunk_id = chunk.metadata.get("chunk_id", "N/A")
            parts.append(f"[Source: {source} - {chunk_id}]\n{chunk.content}")
        return "\n\n---\n\n".join(parts)

    def _rag_user_message(self, question: str, contexts: list[SourceChunk]) -> str:
        """Mensaje de usuario con contexto + pregunta (plantilla en app.prompts)."""
        return build_rag_user_message(self._format_context_block(contexts), question)

    def generate(
        self,
        question: str,
        contexts: list[SourceChunk],
        *,
        channel: GenerateChannel = "web",
    ) -> tuple[str, list[SourceChunk]]:
        """Genera respuesta del LLM; system prompt según canal (``prompt_store`` + defaults en ``prompts``)."""
        if not contexts:
            message = self.llm.invoke(
                [
                    {"role": "system", "content": get_system_no_retrieval_for_channel(channel)},
                    {"role": "user", "content": build_no_retrieval_user_message(question)},
                ]
            )
            return self._llm_message_text(message), []

        message = self.llm.invoke(
            [
                {"role": "system", "content": get_system_rag_for_channel(channel)},
                {"role": "user", "content": self._rag_user_message(question, contexts)},
            ]
        )
        return self._llm_message_text(message), contexts
