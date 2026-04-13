# CLAUDE.md - test3

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**pruebaScanntech** is a RAG (Retrieval-Augmented Generation) system for quality control. It ingests documents (PDF/MD/TXT), chunks them, embeds them via OpenAI, stores vectors in Chroma, and retrieves relevant context to answer questions with LLM-generated responses. It includes RAGAS evaluation to measure faithfulness, relevance, and context precision.

## Commands

### Backend (FastAPI + Python)

**Setup:**
```bash
cd backend
cp .env.example .env
# Edit .env and add OPENAI_API_KEY (and adjust parameters if needed)

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Incluye **RAGAS** para `POST /evaluate` (sin archivo `requirements` aparte).

**Development:**
```bash
# Option 1: using the convenience script
cd backend && chmod +x run_dev.sh && ./run_dev.sh

# Option 2: manually
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 3333
```

Server runs at `http://127.0.0.1:3333` with auto-reload enabled.

**Evaluation (RAGAS):**
```bash
# Tras pip install -r requirements.txt, POST /evaluate (UI o curl; tarda varios minutos)
curl -X POST "http://127.0.0.1:3333/evaluate?eval_relative_path=evals/sample_eval.jsonl"
```

### Frontend (React + Vite + TypeScript)

**Setup:**
```bash
cd frontend
cp .env.example .env
# Optional: set VITE_API_BASE_URL if backend is not at 127.0.0.1:3333

npm install
```

**Development:**
```bash
npm run dev
```

Development server runs at `http://localhost:4444` with HMR enabled.

**Build:**
```bash
npm run build
```

**Lint:**
```bash
npm run lint
```

## High-Level Architecture

### Backend Structure

**Entry point:** `backend/app/main.py`
- FastAPI application with lifespan context manager
- CORS middleware configured via `Settings.cors_origins`
- Global instances: `_settings` (config), `_rag` (RAG service), optional asyncio task `_whatsapp_poll_task` when `WHATSAPP_ENABLED` and polling is on

**Core modules:**

1. **`config.py`** — `Settings` dataclass
   - Loads environment variables (OpenAI API key, Chroma paths, chunking params, retrieval thresholds)
   - Key params: `CHUNK_SIZE`, `CHUNK_OVERLAP`, `TOP_K`, `MMR_LAMBDA`, `RETRIEVE_MAX_L2_DISTANCE`, etc.

2. **`rag_service.py`** — `RAGService` class (orchestration)
   - `ingest_text(text, source_name)`: chunks text and adds to Chroma via `ChromaStore`
   - `retrieve(question)`: vector search with L2 cap, relevance margin/elbow, optional MMR
   - `generate(question, contexts)`: LLM with prompts from `prompts.py`
   - `collection_chunk_count()`, `clear_vector_index()`, `reopen_chroma_client()`: index utilities

3. **`persistence/chroma.py`** — `ChromaStore`
   - LangChain `Chroma` client, persist directory permissions, write probe, batched `add_documents` with retry on readonly/sqlite 1032
   - `similarity_search_with_score`, `collection_count`, `wipe_persist_directory_and_reopen`

4. **`prompts.py`** — LLM instruction strings
   - `SYSTEM_RAG`, `SYSTEM_NO_RETRIEVAL`, `build_rag_user_message`, `build_no_retrieval_user_message`
   - User-facing answers avoid technical jargon (“fragments”, “RAG”); professional tone toward end users

5. **`preprocess.py`** — document handling
   - `load_document_bytes(filename, raw_bytes)`: dispatches to PDF/Markdown/text loaders
   - PDF: uses PyMuPDF (primary, preserves reading order) with PyPDF as fallback; filters lines dominated by `|` (vector figure artifacts)
   - `RecursiveCharacterTextSplitter` configured with separators tuned for extracted PDF text
   - `sanitize_chunk_text()`, `strip_pdf_glyph_tokens()`: clean up OCR/extraction artifacts

6. **`evaluation.py`** — RAGAS evaluation (only imported if evaluation is requested)
   - `run_ragas_evaluation_async()`: runs RAGAS metrics (faithfulness, answer_relevancy, context_precision, context_recall)
   - Reads eval dataset from `.jsonl` (format: `{"question": "...", "ground_truth": "..."}`), invokes `rag.retrieve` and `rag.generate` per row
   - Returns aggregated scores and per-question details

7. **`paths.py`** — path resolution
   - `resolve_eval_jsonl_path()`: normalizes eval file paths relative to project root

8. **`whatsapp_poll.py`** — optional WhatsApp bridge (no Evolution API)
   - Polls Jetson Flask API (`WHATSAPP_API_BASE_URL`, default example `http://192.168.1.254:8090`): mode `recent` → `GET /messages/recent` (items include `is_from_me`); mode `chats` → `GET /chats` then `GET /messages?chat_jid=…` (same `is_from_me` per message)
   - Sends replies via `POST /send/text` (`phone`, `message`)
   - `POST /webhooks/whatsapp` on this backend for push-style delivery from the Jetson (`whatsapp_receiver.sh` or Flask); optional `WHATSAPP_WEBHOOK_SECRET` header
   - Dedup: message IDs, bot reply echo (same text in chat), allowlist `WHATSAPP_ALLOWED_SENDER_NUMBERS`, optional `WHATSAPP_PROCESS_FROM_ME` for same-line-as-GOWA testing

**API Endpoints:**
- `GET /health` — service availability
- `GET /stats` — chunk count, collection name, readiness
- `GET /config` — public config values (chunk_size, top_k, mmr_lambda, etc.)
- `POST /ingest` — multipart file upload, processes and stores documents
- `POST /ingest/reset` — clears Chroma collection (required when changing `CHUNK_SIZE`/`CHUNK_OVERLAP`)
- `POST /chat` — `{"question": "..."}` → `{"answer": "...", "sources": [...]}`
- `GET /retrieve` — debug endpoint; returns raw retrieved contexts and metadata
- `POST /evaluate` — runs RAGAS evaluation (RAGAS pinned in `requirements.txt`)
- `GET /webhooks/whatsapp` — ping / integration hints (WhatsApp)
- `POST /webhooks/whatsapp` — inbound message JSON for RAG reply (WhatsApp)

### WhatsApp deployment note

Typical edge setup: **GOWA** (Docker) on port **3000** and **Flask API** on **8090** on a Jetson (or similar). This RAG backend only talks HTTP to **8090**. Use `uvicorn --host 0.0.0.0` if the Jetson must call back to `POST /webhooks/whatsapp` on the dev machine.

### Frontend Structure

**Framework:** React 19 + TypeScript + Vite + Tailwind CSS

**Key components:**
- Chat interface with message history and markdown rendering
- Document upload with drag-and-drop
- Retrieval debug viewer (shows contexts used for answer)
- RAGAS evaluation section (displays metrics and per-question results)
- When WhatsApp is enabled, chat footer can show polling mode and webhook URL (`/config` fields `whatsapp_*`)
- Responsive layout with dark/light mode support

**Configuration:**
- API base URL via `VITE_API_BASE_URL` env var (defaults to `http://127.0.0.1:3333`)

### Data Flow

1. **Ingestion:**
   - User uploads PDF/MD/TXT → `/ingest` multipart endpoint
   - `preprocess.py` loads and extracts text (PDF: PyMuPDF or PyPDF; MD/TXT: direct read)
   - Text split into chunks (recursively by paragraphs, lines, sentences)
   - Each chunk → OpenAI embedding → stored in Chroma with metadata

2. **Retrieval:**
   - User asks question → query vector via OpenAI embeddings
   - Chroma searches by L2 distance
   - Filter: discard results with distance > `RETRIEVE_MAX_L2_DISTANCE`
   - Optionally apply MMR (maximum marginal relevance) to reduce redundancy
   - Return top-K chunks, sorted by relevance (ascending L2 distance)

3. **Generation:**
   - Pass question + retrieved contexts to LLM using `prompts.py` system and user templates (contextual mode when documentation excerpts exist)
   - Return answer + list of retrieved contexts passed to the model

4. **Evaluation (RAGAS):**
   - RAGAS loads eval dataset (questions + ground truth answers)
   - For each question: `rag.retrieve` then `rag.generate` to build contexts and answer
   - Compute metrics (faithfulness, answer_relevancy, context_precision, context_recall)
   - Average across all questions; return aggregates and per-question breakdown

5. **WhatsApp (optional):**
   - Background poll or webhook receives a user message → same `retrieve` + `generate` as `/chat` → `POST` Jetson `/send/text`
   - See `backend/.env.example` (`WHATSAPP_*`) and `docs/ARQUITECTURA.md`

## Key Considerations

- **Environment variables are mandatory:** Backend will not initialize without `OPENAI_API_KEY`. Frontend API default is `http://127.0.0.1:3333` if `VITE_API_BASE_URL` is not set.
- **Chroma persistence:** Vector DB is persisted on disk in the directory specified by `CHROMA_PERSIST_DIRECTORY` (defaults to `backend/chroma_db`). Clearing requires calling `POST /ingest/reset`.
- **Chunking params affect indexing:** Changing `CHUNK_SIZE` or `CHUNK_OVERLAP` requires calling `POST /ingest/reset` and re-uploading documents to regenerate embeddings. Changes to `TOP_K` or MMR params only require restarting the backend.
- **Large PDFs:** The default PDF-GenAI-Challenge.pdf is ~600+ pages. Default chunk size is 1280 with 20% overlap to handle this gracefully. Adjust `CHUNK_SIZE`, `TOP_K`, `MMR_FETCH_K` if needed.
- **RAGAS evaluation:** Included in `requirements.txt`. Evaluation is slow (several minutes) due to LLM calls per metric, per question.
- **WhatsApp:** Configure `WHATSAPP_*` in `backend/.env`; details in `docs/VARIABLES_ENTORNO.md` and `docs/ARQUITECTURA.md`. No Docker Evolution stack in this repo.
