# RAG para control de calidad del conocimiento interno

Stack: **FastAPI** (Python), **React + Vite + TypeScript**, **Chroma** (vectores locales), **OpenAI** (embeddings + chat). Las claves y parámetros van en **variables de entorno** (nunca en el frontend).

- **Arquitectura** (Mermaid, flujos, API): [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md)
- **Variables `.env`** (definición y razón de los valores por defecto): [docs/VARIABLES_ENTORNO.md](docs/VARIABLES_ENTORNO.md)

## Interfaz de la aplicación

La aplicación web ofrece tres vistas principales, alineadas con el flujo de trabajo: **ingerir y gobernar el índice**, **consultar el conocimiento** y **medir la calidad del RAG**. Las capturas siguientes muestran el aspecto real de la UI (tema claro/oscuro según preferencias del sistema).

| Archivo en `docs/images/` | Vista | Funcionalidades que se observan |
|----------------------------|--------|----------------------------------|
| `homePage.png` | **Documentos** | Subida de archivos (PDF, Markdown, TXT), cola de procesamiento, **Vaciar índice** con confirmación, parámetros de recuperación y chunking desde el servidor (`/config`), estado del índice (fragmentos, colección). |
| `chatBotPage.png` | **Chat** | Conversación con respuestas ancladas al material indexado, historial, **fuentes** (extractos) por mensaje, estado de WhatsApp si está activo (`/config`), `/health`. |
| `EvaluateRAGASPage.png` | **Evaluación** | Ejecución de **RAGAS** vía `POST /evaluate`, dataset (p. ej. `evals/sample_eval.jsonl`), métricas agregadas y desglose por pregunta. |

### Vista Documentos

Gestión del corpus: arrastra o selecciona archivos, revisa la cola, indexa por lotes y, si cambias chunking o quieres rehacer embeddings, vacía la persistencia de Chroma. La columna lateral resume la configuración efectiva del API para chunk size, overlap, MMR y umbrales L2.

<p align="center">
  <img src="docs/images/homePage.png" alt="Vista Documentos: subida de archivos, cola de ingesta, parámetros de recuperación y vaciado del índice" width="920" />
</p>

<p align="center"><em>Pestaña Documentos: ingesta, índice vectorial y parámetros del servidor.</em></p>

### Vista Chat

El asistente responde en el idioma de la pregunta usando el contenido indexado. Cada turno puede expandirse para inspeccionar los extractos de las fuentes y validar frente a la documentación cargada.

<p align="center">
  <img src="docs/images/chatBotPage.png" alt="Vista Chat: historial, respuesta del asistente y fuentes de contexto" width="920" />
</p>

<p align="center"><em>Pestaña Chat: preguntas al índice y trazabilidad por fuentes.</em></p>

### Vista Evaluación RAGAS

Evaluación offline sobre un fichero `.jsonl` con pares pregunta / *ground truth*: el backend invoca recuperación y generación igual que en producción y muestra promedios de fidelidad, relevancia, precisión de contexto y recall, con detalle por pregunta.

<p align="center">
  <img src="docs/images/EvaluateRAGASPage.png" alt="Vista Evaluación: métricas RAGAS y resultados por pregunta" width="920" />
</p>

<p align="center"><em>Pestaña Evaluación: métricas RAGAS y panel por pregunta.</em></p>

## Flujo del sistema

1. **Preprocesado:** lectura de `.txt` / `.md` / `.pdf`. Los PDF usan **PyMuPDF** (mejor orden de lectura) con **pypdf** como respaldo; se filtran líneas dominadas por `|` (artefactos típicos de figuras vectoriales) para que el texto se parezca más al cuerpo del libro. Tras actualizar esta lógica, **vacia el índice y vuelve a ingerir** los PDF ya subidos.
2. **Fragmentación:** `RecursiveCharacterTextSplitter` con `CHUNK_SIZE`, `CHUNK_OVERLAP` y separadores pensados para texto extraído de PDF (párrafos, líneas, frases).
3. **Embeddings + índice:** embeddings OpenAI → almacenamiento en Chroma persistido en disco.
4. **Recuperación:** candidatos por similitud L2; se descartan los que superan `RETRIEVE_MAX_L2_DISTANCE`. El resto se **ordena de más a menos relevante** y se recorta con `RETRIEVE_RELEVANCE_MARGIN` (distancia ≤ mejor + margen). Opcionalmente `RETRIEVE_ELBOW_L2_GAP` corta cuando hay un salto grande entre dos vecinos consecutivos. Sobre el conjunto resultante, **MMR** (opcional) elige hasta `TOP_K` y el orden final vuelve a ser **por relevancia** (menor distancia primero) para el prompt.
5. **Generación:** prompts de sistema y plantillas de usuario en **`backend/app/prompts.py`**; el modelo chat es configurable por `.env`. Sin contexto documental recuperado se usa un system prompt distinto para no inventar contenido del índice. Las respuestas al usuario final evitan jerga técnica (“fragmentos”, “RAG”): lenguaje de profesional a usuario.

### WhatsApp (opcional)

Si tienes una **API Flask en red** (p. ej. en un Jetson con **GOWA en :3000** y **API en :8090**), el backend puede:

- **Enviar** respuestas con `POST {WHATSAPP_API_BASE_URL}/send/text` (`phone`, `message`).
- **Recibir** mensajes con **polling**: `GET /messages/recent` (cada mensaje trae `is_from_me: true/false` para distinguir entrantes/salientes) o modo **chats** → `GET /chats` y luego `GET /messages?chat_jid=…` por conversación (mismo campo `is_from_me`). Alternativa: **`POST /webhooks/whatsapp`** hacia este servidor (p. ej. `whatsapp_receiver.sh` en el Jetson).

Variables: ver **`backend/.env.example`** (`WHATSAPP_*`) y [docs/VARIABLES_ENTORNO.md](docs/VARIABLES_ENTORNO.md). El backend debe alcanzar la IP del Jetson y, en dev, suele usarse `uvicorn --host 0.0.0.0` para que el Jetson pueda llamar al webhook si aplica.

## Requisitos

- Python 3.11+ recomendado (3.14 puede mostrar avisos de LangChain).
- Node.js 20+ para el frontend.
- Cuenta OpenAI con API key (o endpoint compatible vía `OPENAI_API_BASE`).

## Backend

```bash
cd backend
cp .env.example .env
# Edita .env y pon OPENAI_API_KEY

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 3333
```

También puedes usar `chmod +x run_dev.sh && ./run_dev.sh` desde `backend/`.

Arranca desde `backend/` para que se cargue `backend/.env`.

**Rutas útiles:** `GET /health`, `POST /ingest` (multipart, campo `files`), `POST /ingest/reset` (borra la colección Chroma; necesario si cambias chunking y quieres re-embeddar), `POST /chat` (JSON `{"question":"..."}`), `GET /retrieve?q=...` (solo contextos, útil para evaluación), `POST /evaluate` (query opcional `eval_relative_path=evals/sample_eval.jsonl`) — ejecuta RAGAS en el servidor; tarda varios minutos. **WhatsApp:** `GET /webhooks/whatsapp` (comprobación), `POST /webhooks/whatsapp` (mensaje entrante JSON; opcional `WHATSAPP_WEBHOOK_SECRET`).

**Ajuste para PDFs muy largos** (p. ej. `PDF-GenAI-Challenge.pdf`, ~600+ páginas): por defecto `CHUNK_SIZE=1280`, `CHUNK_OVERLAP=256` (~20 %), `TOP_K=6`, `MMR_FETCH_K=80`, `MMR_LAMBDA=0.91`. Si cambias `CHUNK_SIZE` u `CHUNK_OVERLAP`, usa **Vaciar índice** y vuelve a ingerir el PDF. Cambios solo de `TOP_K`/MMR: reinicia uvicorn.

La **UI** incluye la sección «Evaluación RAGAS» que llama a `POST /evaluate` y muestra promedios y detalle por pregunta.

**Tamaño de subida:** `MAX_UPLOAD_BYTES` en `.env` limita cada archivo (por defecto 200 MiB, apto para libros en PDF). Sube el valor si necesitas archivos mayores.

## Frontend

```bash
cd frontend
cp .env.example .env
# Opcional: VITE_API_BASE_URL si el API no está en 127.0.0.1:3333

npm install
npm run dev
# UI en http://localhost:4444 (Vite)
```

Coloca tus PDF/MD/TXT en `data/` (ver `data/README.md`), súbelos desde la UI y pregunta en el chat.

## Evaluación con RAGAS

La evaluación corre **en el servidor** con el mismo `RAGService` que el chat (`POST /evaluate` o la sección en la UI). El dataset por defecto `evals/sample_eval.jsonl` contiene **10 pares** en inglés alineados con *An Introduction to Statistical Learning with Applications in Python* (**ISLP**): el archivo raíz `PDF-GenAI-Challenge.pdf` es ese libro. Las preguntas citan definiciones del texto (estimación de *f*, error reducible, supervisado/no supervisado, sesgo–varianza, mínimos cuadrados, logit, *k*-fold CV, PCA, *random forests* vs *bagging*, *torch* / deep learning). **Indexa ese PDF** antes de evaluar.

RAGAS ya forma parte de `requirements.txt`; usa el mismo entorno del backend (`OPENAI_API_KEY` requerida).

| Enunciado (ES) | Métrica RAGAS |
|----------------|---------------|
| Fidelidad | `faithfulness` |
| Relevancia | `answer_relevancy` |
| Precisión del contexto | `context_precision` |
| Recuperación | `context_recall` |

Ejemplo por HTTP:

```bash
curl -s -X POST "http://127.0.0.1:3333/evaluate?eval_relative_path=evals/sample_eval.jsonl"
```

## Estructura

```
pruebaScanntech/
├── backend/
│   └── app/
│       ├── main.py, config.py, rag_service.py, preprocess.py, paths.py, evaluation.py
│       ├── prompts.py          # instrucciones LLM (SYSTEM_RAG, SYSTEM_NO_RETRIEVAL, tono usuario)
│       ├── whatsapp_poll.py    # integración WhatsApp (polling + eco de respuestas + webhook)
│       └── persistence/        # Chroma en disco (ChromaStore)
├── docs/             # ARQUITECTURA.md, VARIABLES_ENTORNO.md, images/ (capturas de la UI)
├── frontend/         # React (Vite)
├── evals/            # sample_eval.jsonl + README
├── data/             # Documentos a indexar (vacío salvo README)
└── README.md
```
