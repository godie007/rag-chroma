import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_chroma.vectorstores import maximal_marginal_relevance
except ImportError:
    from langchain_community.vectorstores.utils import maximal_marginal_relevance
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.config import Settings
from app.persistence import ChromaStore
from app.persistence.parent_content_store import ParentContentStore
from app.preprocess import build_ingest_recursive_splitter, chunk_text_for_ingest
from app.sectioning import classify_section, parse_exclude_section_types
from app.prompts import (
    RETRIEVAL_PROFILE_CLASSIFY_SYSTEM,
    SYSTEM_NO_RETRIEVAL,
    SYSTEM_RAG,
    build_contextual_chunk_user_message,
    build_no_retrieval_user_message,
    build_rag_user_message,
)
from app.prompt_store import get_system_no_retrieval_for_channel, get_system_rag_for_channel

logger = logging.getLogger(__name__)

GenerateChannel = Literal["web", "whatsapp"]
_MARKDOWN_OUTPUT_GUARDRAIL = (
    "FORMATO OBLIGATORIO DE SALIDA: responde siempre en Markdown válido. "
    "Usa párrafos, listas, tablas o encabezados cuando aporten claridad. "
    "No respondas en JSON, XML ni texto estructurado de máquina."
)

@dataclass
class SourceChunk:
    content: str
    metadata: dict[str, Any]

    @staticmethod
    def from_stored_document(doc: Document) -> "SourceChunk":
        """Texto mostrado al LLM / UI: ``original_text`` si existe (ingesta contextual); si no, ``page_content``."""
        meta = dict(doc.metadata)
        raw = meta.get("original_text")
        if isinstance(raw, str) and raw.strip():
            return SourceChunk(content=raw, metadata=meta)
        return SourceChunk(content=doc.page_content, metadata=meta)


class RAGService:
    @staticmethod
    def _force_markdown_system(system_prompt: str) -> str:
        """Añade una guardrail de formato para que la salida final sea Markdown."""
        base = (system_prompt or "").strip()
        if not base:
            return _MARKDOWN_OUTPUT_GUARDRAIL
        return f"{base}\n\n{_MARKDOWN_OUTPUT_GUARDRAIL}"

    @staticmethod
    def _looks_like_ambiguity_payload(text: str) -> bool:
        """Detecta si el modelo devolvió JSON del evaluador de ambigüedad en vez de respuesta al usuario."""
        raw = (text or "").strip()
        if not raw.startswith("{"):
            return False
        try:
            data = json.loads(raw)
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        keys = set(data.keys())
        # Firma típica de SYSTEM_CLARIFICATION_AMBIGUITY_EVAL
        return "is_ambiguous" in keys and (
            "clarification_question" in keys or "refined_query" in keys or "reason" in keys
        )

    def reopen_chroma_client(self) -> None:
        """API pública por si hace falta forzar reapertura tras errores de disco (también usa ingesta internamente)."""
        self._chroma.reconnect()
        if self._chroma_pr is not None:
            self._chroma_pr.reconnect()

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
        self.splitter = build_ingest_recursive_splitter(
            settings.chunk_size, settings.chunk_overlap
        )
        self._contextual_llm: ChatOpenAI | None = None
        if settings.enable_contextual_retrieval:
            self._contextual_llm = ChatOpenAI(
                model=settings.contextual_retrieval_model,
                temperature=0.0,
                max_tokens=settings.contextual_retrieval_max_output_tokens,
                **common_openai,
            )
        self._chroma = ChromaStore(settings, self.embeddings)
        if settings.parent_rerank_enabled:
            pr_name = f"{settings.chroma_collection_name}{settings.parent_rerank_chroma_suffix}"
            self._chroma_pr = ChromaStore(
                settings, self.embeddings, collection_name=pr_name
            )
            self._parent_text_store = ParentContentStore(
                Path(settings.chroma_persist_directory) / "parent_rerank_parents.json"
            )
        else:
            self._chroma_pr = None
            self._parent_text_store = None
        self._ce_model: Any = None
        self._ce_load_failed: bool = False
        self._parent_rerank_ingest_warned_ctx = False
        # Una sola escritura a Chroma a la vez (SQLite + embeddings), evita contienda y bloqueos raros.
        self._index_write_lock = threading.Lock()

    def collection_chunk_count(self) -> int:
        if self.settings.parent_rerank_enabled and self._chroma_pr is not None:
            return self._chroma_pr.collection_count()
        return self._chroma.collection_count()

    def list_indexed_sources(self) -> list[str]:
        a = set(self._chroma.list_distinct_sources())
        if self._chroma_pr is not None:
            a |= set(self._chroma_pr.list_distinct_sources())
        return sorted(a)

    def delete_indexed_source(self, source_name: str) -> int:
        """Quita del índice todos los trozos asociados a una fuente (metadato ``source``)."""
        with self._index_write_lock:
            n0 = self._chroma.delete_by_source(source_name)
            n1 = 0
            if self._chroma_pr is not None:
                n1 = self._chroma_pr.delete_by_source(source_name)
            if self._parent_text_store is not None:
                self._parent_text_store.delete_by_source(source_name)
            return n0 + n1

    def clear_vector_index(self) -> None:
        """Borra la persistencia de Chroma en disco y recrea una colección vacía."""
        resolved = Path(self.settings.chroma_persist_directory)
        if resolved.resolve() in (Path("/").resolve(), Path.home().resolve()):
            raise ValueError(
                "CHROMA_PERSIST_DIRECTORY apunta a una ruta no permitida para borrado completo."
            )
        with self._index_write_lock:
            if self._chroma_pr is not None:
                self._chroma_pr.close()
            self._chroma.wipe_persist_directory_and_reopen()
            if self._chroma_pr is not None:
                self._chroma_pr.reconnect()
            if self._parent_text_store is not None:
                self._parent_text_store.clear()

    def ingest_text(self, text: str, source_name: str) -> int:
        """Parte el texto en fragmentos, genera embeddings y los guarda en Chroma.

        Devuelve cuántos fragmentos se indexaron (0 si el texto estaba vacío o solo espacios).
        """
        # --- 1. Entrada: nada que indexar ---
        if not text.strip():
            return 0

        with self._index_write_lock:
            if self.settings.parent_rerank_enabled and self._chroma_pr is not None:
                return self._ingest_text_parent_rerank(text, source_name)

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
            to_index = (
                self._contextualize_for_ingest(text_norm, chunk_strings)
                if (self._contextual_llm and chunk_strings)
                else chunk_strings
            )

            # --- 4. Empaquetar cada trozo como Document (contenido + metadatos para citas) ---
            documents: list[Document] = []
            for index, orig in enumerate(chunk_strings):
                meta: dict[str, Any] = {
                    "source": source_name,
                    "chunk_id": f"{source_name}#{index}",
                }
                if self._contextual_llm:
                    meta["original_text"] = orig
                documents.append(
                    Document(
                        page_content=to_index[index] if index < len(to_index) else orig,
                        metadata=meta,
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

    def _ingest_text_parent_rerank(self, text: str, source_name: str) -> int:
        """Hijos (embed) pequeños + padre (texto completo) en disco; requiere parent_rerank_enabled."""
        if self._chroma_pr is None or self._parent_text_store is None:
            return 0
        if self.settings.enable_contextual_retrieval and not self._parent_rerank_ingest_warned_ctx:
            logger.info(
                "PARENT_RERANK: ingesta sin contextual LLM (trozos hijos = texto; padre = disco)."
            )
            self._parent_rerank_ingest_warned_ctx = True
        text_norm = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text_norm.strip():
            return 0
        s = self.settings
        parent_spl = RecursiveCharacterTextSplitter(
            chunk_size=s.parent_rerank_parent_size,
            chunk_overlap=s.parent_rerank_parent_overlap,
        )
        child_spl = RecursiveCharacterTextSplitter(
            chunk_size=s.parent_rerank_child_size,
            chunk_overlap=s.parent_rerank_child_overlap,
        )
        parents = parent_spl.split_text(text_norm)
        total = len(text_norm)
        char_off = 0
        store_batch: list[tuple[str, str, dict[str, Any]]] = []
        documents: list[Document] = []
        for idx, ptext in enumerate(parents):
            if not ptext.strip():
                char_off += len(ptext)
                continue
            sec = classify_section(
                ptext, char_offset=char_off, total_len=max(total, 1)
            )
            char_off += len(ptext)
            pid = str(uuid4())
            store_batch.append(
                (
                    pid,
                    ptext,
                    {
                        "source": source_name,
                        "section_type": sec,
                        "parent_index": str(idx),
                    },
                )
            )
            c_parts = child_spl.split_text(ptext) or [ptext]
            for j, ctext in enumerate(c_parts):
                if not ctext.strip():
                    continue
                meta: dict[str, Any] = {
                    "source": source_name,
                    "parent_id": pid,
                    "section_type": sec,
                    "pr_child": "1",
                    "chunk_id": f"{source_name}#p{idx}#c{j}",
                }
                documents.append(Document(page_content=ctext.strip(), metadata=meta))
        if not documents:
            return 0
        self._parent_text_store.set_parents_batch(store_batch)
        self._chroma_pr.ensure_writable_before_ingest()
        chroma_ids = [str(uuid4()) for _ in documents]
        batch_size = max(1, s.chroma_ingest_batch_size)
        for i in range(0, len(documents), batch_size):
            self._chroma_pr.add_documents_batch(
                documents[i : i + batch_size], chroma_ids[i : i + batch_size]
            )
        return len(documents)

    def _get_cross_encoder(self) -> Any | None:
        if self._ce_load_failed:
            return None
        if self._ce_model is not None:
            return self._ce_model
        if not self.settings.parent_rerank_enabled:
            return None
        try:
            from langchain_community.cross_encoders import HuggingFaceCrossEncoder
        except ImportError as e:
            logger.warning("Cross-encoder no importable: %s; se ordena por distancia L2 de hijo", e)
            self._ce_load_failed = True
            return None
        try:
            self._ce_model = HuggingFaceCrossEncoder(
                model_name=self.settings.rag_cross_encoder_model,
                model_kwargs={"device": "cpu"},
            )
        except Exception as e:
            logger.warning("No se pudo cargar el cross-encoder: %s; se usa solo el orden L2", e)
            self._ce_load_failed = True
            return None
        return self._ce_model

    def _chroma_metadata_where_exclude_sections(self) -> dict[str, Any] | None:
        ex = parse_exclude_section_types(
            self.settings.retrieval_exclude_section_types
        )
        if not ex:
            return None
        return {"section_type": {"$nin": ex}}

    def _retrieve_parent_rerank(self, question: str, *, infer_broad_retrieval: bool) -> list[SourceChunk]:
        if self._chroma_pr is None or self._parent_text_store is None:
            return []
        k = self.settings.top_k
        use_broad = (
            infer_broad_retrieval
            and self.settings.llm_retrieval_profile
            and self._infer_broad_retrieval(question)
        )
        if use_broad:
            fetch_k = max(
                self.settings.rag_retriever_k, k * 20, 120, self.settings.mmr_fetch_k
            )
            max_l2_distance = min(2.2, self.settings.retrieve_max_l2_distance * 2.0)
        else:
            fetch_k = max(
                self.settings.rag_retriever_k, k * 10, 40, self.settings.mmr_fetch_k
            )
            max_l2_distance = self.settings.retrieve_max_l2_distance
        embed_q = self._embedding_query_for_retrieval(question, use_broad=use_broad)
        where = self._chroma_metadata_where_exclude_sections()
        candidates = self._search_sorted_within_l2_cap(
            embed_q,
            fetch_k=fetch_k,
            max_l2_distance=max_l2_distance,
            store=self._chroma_pr,
            where=where,
        )
        if not candidates and use_broad:
            candidates = self._search_sorted_within_l2_cap(
                embed_q,
                fetch_k=fetch_k,
                max_l2_distance=min(2.35, self.settings.retrieve_max_l2_distance * 2.75),
                store=self._chroma_pr,
                where=where,
            )
        if not candidates:
            return []
        if use_broad:
            focused = self._prefix_before_relevance_cutoff(
                candidates, margin_boost=0.35, skip_elbow=True
            )
        else:
            scenario_boost = not use_broad and self._scenario_qualified_question(
                question
            )
            focused = self._prefix_before_relevance_cutoff(
                candidates, margin_boost=0.16 if scenario_boost else 0.0
            )
        if not focused:
            return []
        best_dist: dict[str, float] = {}
        order_by_first: list[str] = []
        for doc, dist in focused:
            meta = doc.metadata or {}
            pid = meta.get("parent_id")
            if not isinstance(pid, str) or not pid:
                continue
            if pid not in best_dist:
                order_by_first.append(pid)
            prev = best_dist.get(pid, 1e9)
            if float(dist) < prev:
                best_dist[pid] = float(dist)
        if not order_by_first:
            return []
        texts = self._parent_text_store.mget(order_by_first)
        unique_ids = [p for p in order_by_first if p in texts]
        if not unique_ids:
            return []
        enc = self._get_cross_encoder()
        top_n = min(self.settings.rag_reranker_top_n, len(unique_ids))
        if enc is not None:
            try:
                pairs: list[tuple[str, str]] = [
                    (question, texts[pid]) for pid in unique_ids
                ]
                raw_scores = enc.score(pairs)
                if hasattr(raw_scores, "tolist"):
                    raw_scores = raw_scores.tolist()  # type: ignore[assignment]
                if isinstance(raw_scores, (int, float)):
                    sc = [float(raw_scores)]
                else:
                    sc = [float(x) for x in list(raw_scores)]
                ranked = sorted(
                    zip(unique_ids, sc, strict=True),
                    key=lambda x: -x[1],
                )[:top_n]
                ordered = [p for p, _ in ranked]
            except Exception as e:
                logger.warning("Rerank parent falló (%s); orden por distancia de hijo", e)
                ordered = sorted(unique_ids, key=lambda p: best_dist.get(p, 0.0))[
                    :top_n
                ]
        else:
            ordered = sorted(
                unique_ids, key=lambda p: best_dist.get(p, 0.0)
            )[:top_n]
        out: list[SourceChunk] = []
        for pid in ordered:
            t = texts.get(pid)
            if t is None or self._parent_text_store is None:
                continue
            meta: dict[str, Any] = {
                "parent_id": pid,
                "retrieval": "parent_rerank",
            }
            meta.update(self._parent_text_store.get_metadata(pid))
            out.append(SourceChunk(content=t, metadata=meta))
        return out

    def _contextualize_for_ingest(self, full_document: str, chunks: list[str]) -> list[str]:
        """Antepone contexto (LLM) a cada trozo para embedding; concurrencia acotada."""
        if not self._contextual_llm or not (full_document or "").strip() or not chunks:
            return chunks
        cap = self.settings.contextual_retrieval_max_doc_chars
        fd = full_document[:cap]
        n = len(chunks)
        conc = min(max(1, self.settings.contextual_retrieval_concurrency), n)

        def one(idx: int, ch: str) -> tuple[int, str]:
            c = (ch or "").strip()
            if not c:
                return idx, ch
            try:
                msg = self._contextual_llm.invoke(
                    [
                        {
                            "role": "user",
                            "content": build_contextual_chunk_user_message(fd, ch),
                        }
                    ]
                )
                head = self._llm_message_text(msg).strip()
                if not head:
                    return idx, ch
                return idx, f"{head}\n\n{ch}"
            except Exception as exc:
                logger.warning("Contextualize chunk %s falló: %s", idx, exc)
                return idx, ch

        if n == 1:
            _, out = one(0, chunks[0])
            return [out]
        out: list[str] = [""] * n
        with ThreadPoolExecutor(max_workers=conc) as pool:
            futures = [pool.submit(one, i, c) for i, c in enumerate(chunks)]
            for fut in as_completed(futures):
                i, text = fut.result()
                out[i] = text
        return out

    def _search_sorted_within_l2_cap(
        self,
        question: str,
        *,
        fetch_k: int,
        max_l2_distance: float,
        store: ChromaStore | None = None,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[Document, float]]:
        """Vecinos por similitud; descarta los que superan el umbral L2; ordena de mejor a peor distancia."""
        s = store or self._chroma
        scored = s.similarity_search_with_score(question, k=fetch_k, filter=where)
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
        return [SourceChunk.from_stored_document(doc) for doc, _ in selected_pairs]

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
        if self.settings.parent_rerank_enabled:
            return self._retrieve_parent_rerank(
                question, infer_broad_retrieval=infer_broad_retrieval
            )
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
        markdown_final: bool = False,
    ) -> tuple[str, list[SourceChunk]]:
        """Genera respuesta del LLM; system prompt según canal (``prompt_store`` + defaults en ``prompts``).

        ``markdown_final`` solo debe ser True en la **respuesta final** al usuario (tras clarificar o RAG clásico).
        Pasos internos o la pregunta de clarificación no usan este método con ``markdown_final=True``.
        """
        def _system_rag_effective() -> str:
            s = get_system_rag_for_channel(channel)
            return self._force_markdown_system(s) if markdown_final else s

        def _system_no_retrieval_effective() -> str:
            s = get_system_no_retrieval_for_channel(channel)
            return self._force_markdown_system(s) if markdown_final else s

        if not contexts:
            user_message = build_no_retrieval_user_message(question)
            message = self.llm.invoke(
                [
                    {"role": "system", "content": _system_no_retrieval_effective()},
                    {"role": "user", "content": user_message},
                ]
            )
            text = self._llm_message_text(message)
            if self._looks_like_ambiguity_payload(text):
                logger.warning(
                    "Salida con firma de evaluador en generate(no_context) canal=%s; reintentando con SYSTEM_NO_RETRIEVAL default.",
                    channel,
                )
                sys_fb = (
                    self._force_markdown_system(SYSTEM_NO_RETRIEVAL)
                    if markdown_final
                    else SYSTEM_NO_RETRIEVAL
                )
                message = self.llm.invoke(
                    [
                        {"role": "system", "content": sys_fb},
                        {"role": "user", "content": user_message},
                    ]
                )
                text = self._llm_message_text(message)
            return text, []

        user_message = self._rag_user_message(question, contexts)
        message = self.llm.invoke(
            [
                {"role": "system", "content": _system_rag_effective()},
                {"role": "user", "content": user_message},
            ]
        )
        text = self._llm_message_text(message)
        if self._looks_like_ambiguity_payload(text):
            logger.warning(
                "Salida con firma de evaluador en generate(with_context) canal=%s; reintentando con SYSTEM_RAG default.",
                channel,
            )
            sys_fb = self._force_markdown_system(SYSTEM_RAG) if markdown_final else SYSTEM_RAG
            message = self.llm.invoke(
                [
                    {"role": "system", "content": sys_fb},
                    {"role": "user", "content": user_message},
                ]
            )
            text = self._llm_message_text(message)
        return text, contexts
