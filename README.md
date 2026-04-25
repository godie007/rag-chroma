# RAG para control de calidad del conocimiento interno

Stack: **FastAPI** (Python), **React + Vite + TypeScript**, **Chroma** (vectores locales), **OpenAI** (embeddings + chat). Las claves y parámetros van en **variables de entorno** (nunca en el frontend).

- **Arquitectura** (Mermaid, flujos, API): [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md)
- **Chatbot** (preguntas, system prompts, clarificación, hilos): [docs/ARQUITECTURA_CHATBOT.md](docs/ARQUITECTURA_CHATBOT.md)
- **Variables `.env`** (definición y razón de los valores por defecto): [docs/VARIABLES_ENTORNO.md](docs/VARIABLES_ENTORNO.md)

## Interfaz de la aplicación

La aplicación web ofrece tres vistas principales, alineadas con el flujo de trabajo: **ingerir y gobernar el índice**, **consultar el conocimiento** y **medir la calidad del RAG**. Las capturas siguientes muestran el aspecto real de la UI (tema claro/oscuro según preferencias del sistema).

| Archivo en `docs/images/` | Vista | Funcionalidades que se observan |
|----------------------------|--------|----------------------------------|
| `homePage.png` | **Documentos** | Subida (PDF, Markdown, TXT), **cola** (Pendiente → Indexado), botón **Indexar cola**, panel de progreso por archivos, chip de fragmentos (`GET /stats`), listado de fuentes en el índice, **Vaciar índice** con confirmación, parámetros vía `GET /config`. | 
| `chatBotPage.png` | **Chat** | Conversación con respuestas ancladas al material indexado, historial, **fuentes** (extractos) por mensaje, estado de WhatsApp si está activo (`/config`), `/health`. |
| `EvaluateRAGASPage.png` | **Evaluación** | Ejecución de **RAGAS** vía `POST /evaluate`, dataset (p. ej. `evals/sample_eval.jsonl`), métricas agregadas y desglose por pregunta. |
| (sin captura) | **WhatsApp** | Referencia a integración y lista de allowlist; instrucciones del modelo se editan en **Configuraciones**. |
| (sin captura) | **Configuraciones** | Instrucciones de sistema (prompts) por canal **web** y **WhatsApp** vía `GET`/`PUT` `/config/prompts` (archivo en disco en el backend). |

### Vista Documentos

Gestión del corpus: añade archivos a la cola, pulsa **Indexar cola** (los documentos quedan en *Pendiente* hasta entonces), revisa el progreso y el mensaje al finalizar, y vuelve a indexar o vacía el índice si cambias chunking. La columna lateral resume la configuración efectiva del API (chunk size, overlap, MMR, umbrales L2, etc.).

**Contador de fragmentos e ingesta:** el chip del encabezado usa `GET /stats` (`cache: 'no-store'` en el cliente). Tras `POST /ingest`, el backend responde con **`chunk_count`** (total de vectores en Chroma *en ese mismo proceso*). La UI reconcilia fragmentos a partir de esa respuesta y de `/stats` para no mostrar 0 mientras el índice ya tiene datos. Detalle técnico: [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) (sección API e ingesta).

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
3. **Embeddings + índice:** embeddings OpenAI (`OPENAI_EMBEDDING_MODEL`, opcional `OPENAI_EMBEDDING_DIMENSIONS` para MRL con `text-embedding-3-*`) → almacenamiento en Chroma persistido en disco. Cada colección fija un **tamaño de vector** (p. ej. 1536 con `text-embedding-3-small` en modo nativo, 3072 con `text-embedding-3-large` en modo nativo). **Si cambias modelo, dimensiones MRL o el índice fue creado con otro esquema,** vacía el índice (`POST /ingest/reset` o «Vaciar índice» en la UI) y vuelve a ingerir; si no, la ingesta puede fallar o no añadir fragmentos. Detalle: [docs/VARIABLES_ENTORNO.md](docs/VARIABLES_ENTORNO.md) (reglas prácticas).
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

**Rutas útiles:** `GET /health`, `GET /stats`, `GET /stats/sources` (fuentes listadas en el índice), `GET /config`, `GET`/`PUT`/`DELETE` `/config/prompts` (system prompts por canal, sin reiniciar), `POST /ingest` (multipart, campo `files`; cuerpo de respuesta incluye `files_processed`, `chunks_added`, `messages`, `chunk_count`, `ready`), `POST /ingest/delete-source` (quitar una fuente por nombre), `POST /ingest/reset` (borra la colección Chroma; necesario si cambias chunking, **modelo de embeddings** o **OPENAI_EMBEDDING_DIMENSIONS** y quieres un índice coherente), `POST /chat` (JSON `{"question":"..."}`), `GET /retrieve?q=...` (solo contextos, útil para evaluación), `POST /evaluate` (query opcional `eval_relative_path=evals/sample_eval.jsonl`) — ejecuta RAGAS en el servidor; tarda varios minutos. **WhatsApp:** `GET/POST` `/webhooks/whatsapp`, `GET`/`POST`/`PUT` `/whatsapp/allowlist` (ver `.env`).

`POST /ingest` aplica carga y chunking en **hilo** (`asyncio.to_thread`) para no bloquear el *event loop*; subidas largas (PDFs muy grandes) siguen ocupando al worker hasta completar; Nginx en producción usa `proxy_read_timeout` alto (ver `scripts/nginx-rag.conf`).

**Ajuste para PDFs muy largos** (p. ej. `PDF-GenAI-Challenge.pdf`, ~600+ páginas): por defecto `CHUNK_SIZE=1280`, `CHUNK_OVERLAP=256` (~20 %), `TOP_K=6`, `MMR_FETCH_K=80`, `MMR_LAMBDA=0.91`. Si cambias `CHUNK_SIZE` u `CHUNK_OVERLAP`, usa **Vaciar índice** y vuelve a ingerir el PDF. Cambios solo de `TOP_K`/MMR: reinicia uvicorn.

La **UI** incluye la sección «Evaluación RAGAS» que llama a `POST /evaluate` y muestra promedios y detalle por pregunta.

**Tamaño de subida:** `MAX_UPLOAD_BYTES` en `.env` limita cada archivo (por defecto 200 MiB, apto para libros en PDF). Sube el valor si necesitas archivos mayores.

## Frontend

```bash
cd frontend
cp .env.example .env
# Opcional: VITE_API_BASE_URL (p. ej. http://127.0.0.1:3333 o vacío = mismo origen
#   detrás de Nginx, con las rutas del API bajo /api/)

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

## Despliegue con GitHub Actions (Self-Hosted Runner)

### Arquitectura del Sistema

```
┌─────────────────┐     ┌─────────────────────┐
│   GitHub Repo    │────▶│  GitHub Actions     │
│   (codla.git)   │     │  Workflow: deploy  │
└─────────────────┘     └──────────┬──────────┘
                                  │
                         ┌────────▼──────────┐
                         │ Self-Hosted Runner │
                         │  (NVIDIA Jetson    │
                         │   Nano - ARM64)    │
                         └────────┬──────────┘
                                  │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  FastAPI Backend│    │  React Frontend │    │   WhatsApp      │
│  (Port 3333)    │    │  (Port 4444)     │    │  Integration    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────┐
                    │  Chroma Vector Store        │
                    │  (Embeddings + RAG)        │
                    └─────────────────────────────┘
```

### Componentes

| Componente | Ubicación | Descripción |
|------------|-----------|------------|
| **GitHub Actions** | cloud | Orquesta el deployment en push a `main` |
| **Self-Hosted Runner** | Jetson Nano (192.168.1.254) | Ejecuta los jobs localmente |
| **Backend (FastAPI)** | Jetson :3333 | API RAG con Chroma |
| **Frontend (React)** | `npm run dev` :4444 en desarrollo; en producción suele ser estático en Nginx (`/var/www/rag`) | UI web |
| **WhatsApp Bridge** | Jetson :8090 | Integración con GOWA |

### Configuración del Runner

El runner se ejecuta en la NVIDIA Jetson Nano:

```bash
# En la Jetson (una sola vez)
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-arm64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.333.1/actions-runner-linux-arm64-2.333.1.tar.gz
tar xzf actions-runner-linux-arm64.tar.gz
./config.sh --url https://github.com/godie007/codla --token <TOKEN>
./run.sh

# O como servicio systemd
sudo ./svc.sh install && sudo ./svc.sh start
```

### Workflow de Deployment

El workflow real está en [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) (resumen):

1. **Build del frontend** (`npm ci` y `npm run build` en `frontend/`, o falla si no hay Node y no hay `dist/`).
2. **Copia** del contenido de `frontend/dist` a la raíz de documento de Nginx (p. ej. `/var/www/rag`).
3. **Copia** del backend a una ruta fija en el dispositivo (p. ej. `~/workspace/codla/backend`).
4. Ajuste de **Nginx** desde `scripts/nginx-rag.conf` (proxy largo a `:3333` para `/ingest` pesado, `client_max_body_size`, etc.).

El YAML puede incluir un **paso mínimo** de arranque de API para *health*; en producción suele usarse el **RAG completo** (p. ej. `uvicorn` o **PM2** con el mismo `backend/`) y no un stub. Revisa el archivo del workflow y los scripts del servidor.

## Estructura

```
rag-chroma/   (o nombre del clon)
├── .github/
│   └── workflows/
│       └── deploy.yml      # Workflow de deployment
├── backend/
│   ├── app/
│   │   ├── main.py, config.py, rag_service.py, preprocess.py, paths.py, evaluation.py
│   │   ├── prompts.py, prompt_store.py
│   │   ├── whatsapp_poll.py   # integración WhatsApp
│   │   └── persistence/       # Chroma
│   ├── rag-backend.service    # Servicio systemd
│   └── requirements.txt
├── frontend/
│   ├── src/                  # React + Vite
│   ├── rag-frontend.service  # Servicio systemd
│   └── package.json
├── scripts/
│   └── install-runner.sh     # Script instalación runner
├── docs/                     # Documentación
├── evals/                    # Evaluación RAGAS
└── README.md
```
