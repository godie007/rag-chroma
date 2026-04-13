# Variables de entorno (`.env`)

Este documento describe **qué hace** cada variable y **por qué** los valores por defecto del repositorio están elegidos así. Copia `backend/.env.example` → `backend/.env` y `frontend/.env.example` → `frontend/.env` y ajusta según tu entorno.

---

## Backend (`backend/.env`)

Todas se cargan vía Pydantic Settings (`app.config.Settings`). Los nombres en el archivo usan **MAYÚSCULAS**; en código aparecen en `snake_case`.

### OpenAI

| Variable | Valor ejemplo | Definición | Razón del valor por defecto |
|----------|---------------|------------|------------------------------|
| `OPENAI_API_KEY` | *(vacío en example)* | Clave secreta de la API OpenAI. | Sin ella el backend arranca pero **no** inicializa el RAG (`/ingest`, `/chat` no operan). Debe permanecer **solo en el servidor**, nunca en el frontend. |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Modelo para generar respuestas y para el modo sin fragmentos recuperados. | Buen equilibrio **coste / latencia / calidad** para una demo y para RAG con contexto acotado. Puedes subir a `gpt-4o` si la prueba exige máxima calidad. |
| `OPENAI_CHAT_TEMPERATURE` | `0.1` | Temperatura del modelo de chat en `/chat` (RAG y sin recuperación). Rango típico 0–2. | Valores **bajos** (p. ej. `0`–`0.2`) favorecen respuestas más estables y alineadas al contexto; sube un poco si quieres redacción menos rígida. La evaluación **RAGAS** en `evaluation.py` usa `temperature=0` en el LLM de métricas, independiente de esta variable. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Modelo de vectores para indexar y consultar. | Dimensión y coste moderados; suficiente para recuperación semántica en documentación técnica y libros. `text-embedding-3-large` mejora a veces la recuperación a costa de precio y tamaño de vector. |
| `OPENAI_API_BASE` | *(omitida)* | URL base alternativa (p. ej. Azure OpenAI o proxy). | Por defecto el cliente usa la API pública de OpenAI. Solo necesaria si tu clave y tráfico van por otro endpoint compatible. |

### Chroma (vectores locales)

| Variable | Valor ejemplo | Definición | Razón del valor por defecto |
|----------|---------------|------------|------------------------------|
| `CHROMA_PERSIST_DIRECTORY` | `./chroma_db` | Carpeta donde Chroma guarda SQLite y datos del índice. | Ruta **relativa resuelta respecto a `backend/`** (no depende del directorio desde el que ejecutes uvicorn), coherente con el layout del repo. Evita carpetas sincronizadas (iCloud/Dropbox) si aparece error SQLite **readonly (1032)**. |
| `CHROMA_COLLECTION_NAME` | `internal_knowledge` | Nombre lógico de la colección en esa persistencia. | Nombre estable y descriptivo para un solo índice de “conocimiento interno”. Cámbialo si conviven varios productos en el mismo directorio (no recomendado sin separar `CHROMA_PERSIST_DIRECTORY`). |
| `CHROMA_INGEST_BATCH_SIZE` | `128` | Cuántos documentos (fragmentos) se envían a Chroma por llamada a `add_documents`. | Reduce presión sobre SQLite y memoria al indexar PDFs **muy grandes** (miles de fragmentos). Valores muy bajos = más round-trips; muy altos = transacciones más pesadas. |

### Fragmentación (chunking)

| Variable | Valor ejemplo | Definición | Razón del valor por defecto |
|----------|---------------|------------|------------------------------|
| `CHUNK_SIZE` | `1280` | Tamaño objetivo del fragmento en caracteres (splitter recursivo). | Para libros/PDFs largos (~600 páginas), ~1280 caracteres suele **capturar párrafos o bloques con contexto** sin explotar el contexto del LLM. Muy pequeño → más ruido y más embeddings; muy grande → un solo tema mezclado o límites de modelo. |
| `CHUNK_OVERLAP` | `256` | Caracteres compartidos entre fragmentos consecutivos. | ~**20 %** del `CHUNK_SIZE`: mitiga cortes en mitad de definición o fórmula al recuperar vecinos. |
| `CHUNK_MIN_CHARS` | `400` | Tras el split, los trozos más cortos se **fusionan** con el siguiente (hasta un tope). | Evita chunks solo con títulos tipo “Linear Regression” sin párrafo; mejora la utilidad del embedding sin mezclar capítulos enteros. |
| `CHUNK_MERGE_HARD_MAX` | `0` | Tope de caracteres al fusionar trozos cortos; **`0` significa `2 × CHUNK_SIZE`**. | Un bloque Markdown de código grande puede quedar entero hasta ~2× chunk; si un fence supera eso, se subdivide por líneas. |

### Recuperación y MMR

| Variable | Valor ejemplo | Definición | Razón del valor por defecto |
|----------|---------------|------------|------------------------------|
| `TOP_K` | `6` | Máximo de fragmentos que pasan al prompt tras filtros y MMR. | Suficiente contexto para preguntas conceptuales sin saturar el prompt ni el coste. Sube si las respuestas se quedan cortas; baja si hay mucha redundancia. |
| `USE_MMR` | `true` | Activa **Maximum Marginal Relevance** sobre candidatos ya filtrados por distancia. | Reduce fragmentos casi duplicados (misma sección repetida), lo que suele **subir precisión del contexto** en RAGAS y claridad en el chat. |
| `MMR_FETCH_K` | `80` | Cuántos vecinos pide Chroma antes de MMR y recorte. | Debe ser **≥ TOP_K** y bastante mayor para que MMR tenga variedad. 80 es razonable para índices medianos; en índices enormes puedes subir si el coste de embedding en MMR lo permite. |
| `MMR_LAMBDA` | `0.91` | De 0 a 1: más alto → más peso a **relevancia** frente a **diversidad**. | 0.91 prioriza seguir muy alineado con la consulta y solo separa un poco redundancia; valores bajos diversifican más a costa de traer trozos menos centrados. |
| `RETRIEVE_MAX_L2_DISTANCE` | `1.3` | Distancia L2 máxima aceptada en la búsqueda vectorial de Chroma. | Umbral empírico para embeddings small: por debajo suelen quedar resultados útiles; por encima, consultas vagas o fuera de dominio no llenan el contexto con ruido. **Bajar** si entra basura; **subir** si consultas en otro idioma que el índice empeoran las distancias. |
| `RETRIEVE_RELEVANCE_MARGIN` | `0.10` | Tras ordenar por distancia, se descartan fragmentos con distancia **> mejor_distancia + margen**. | Recorta la “cola” poco relacionada sin forzar siempre `TOP_K` documentos irrelevantes. Con `best_d` alto (p. ej. consultas cruzando idioma), el código **reduce el margen** de forma adaptativa. |
| `RETRIEVE_ELBOW_L2_GAP` | `0` | Si > 0, corta la lista cuando el salto L2 entre dos vecinos consecutivos supera este valor (“codo”). | `0` = desactivado: comportamiento más simple. Actívalo (p. ej. `0.15`) si quieres cortar cuando el índice ordenado muestra un salto brusco de relevancia. |
| `LLM_RETRIEVAL_PROFILE` | `true` | Una llamada ligera al LLM decide si ampliar umbrales de recuperación para preguntas de cobertura (“¿qué cubre el índice?”). | `false` ahorra esa llamada y usa siempre el perfil de recuperación “normal”. |

### CORS y subidas

| Variable | Valor ejemplo | Definición | Razón del valor por defecto |
|----------|---------------|------------|------------------------------|
| `CORS_ORIGINS` | `http://localhost:4444,http://127.0.0.1:4444` | Orígenes del navegador permitidos para llamar al API, separados por coma. | Coincide con **Vite** en este repo (puerto **4444**) con host `localhost` o `127.0.0.1`. Añade tu dominio en despliegue real. |
| `MAX_UPLOAD_BYTES` | `209715200` | Tamaño máximo **por archivo** en `POST /ingest` (bytes). | ~**200 MiB**: admite PDFs de libro completo sin rechazo 413 frecuente. Sube el valor si tus manuales son mayores (valor en bytes, p. ej. `524288000` ≈ 500 MiB). |

### Reglas prácticas

- Si cambias **`CHUNK_SIZE`** o **`CHUNK_OVERLAP`**, los vectores antiguos no son comparables: usa **`POST /ingest/reset`** y vuelve a ingerir.
- Si solo cambias **`TOP_K`**, MMR o umbrales de recuperación, basta **reiniciar** uvicorn.

<a id="whatsapp-jetson"></a>

### WhatsApp (Jetson / API :8090)

Integración **opcional** con una API Flask propia (p. ej. en NVIDIA Jetson: **GOWA Docker :3000** + **API :8090**). El backend RAG solo habla HTTP con `WHATSAPP_API_BASE_URL`; no incluye contenedores de terceros en este repositorio.

| Variable | Default / ejemplo | Definición |
|----------|-------------------|------------|
| `WHATSAPP_ENABLED` | `false` | Activa la integración (polling y/o webhook). Requiere RAG inicializado (`OPENAI_API_KEY`). |
| `WHATSAPP_API_BASE_URL` | `http://192.168.1.254:8090` | Base URL de la API Flask (sin barra final). |
| `WHATSAPP_POLL_ENABLED` | `true` | Si `false`, no arranca el bucle de polling; puedes usar solo `POST /webhooks/whatsapp`. |
| `WHATSAPP_POLL_MODE` | `recent` | `recent` → `GET /messages/recent` (incluye `is_from_me` por mensaje; el backend filtra salvo `WHATSAPP_PROCESS_FROM_ME`). `chats` → `GET /chats` + por cada JID `GET /messages?chat_jid=…` (mismo campo `is_from_me`). |
| `WHATSAPP_POLL_INTERVAL_SEC` | `4` | Segundos entre consultas de polling. |
| `WHATSAPP_POLL_LIMIT` | `50` | Límite en `messages/recent`. |
| `WHATSAPP_CHATS_POLL_LIMIT` | `25` | Máx. chats en modo `chats`. |
| `WHATSAPP_MESSAGES_PER_CHAT_LIMIT` | `40` | Mensajes por chat en modo `chats`. |
| `WHATSAPP_API_KEY` | *(vacío)* | Si la API :8090 exige `Authorization: Bearer`, colócala aquí. |
| `WHATSAPP_WEBHOOK_SECRET` | *(vacío)* | Si tiene valor, `POST /webhooks/whatsapp` exige `X-WhatsApp-Webhook-Secret` o `Authorization: Bearer` con el mismo valor. |
| `WHATSAPP_REPLY_IN_GROUPS` | `false` | Responder en grupos `@g.us` (la API de envío debe soportarlo). |
| `WHATSAPP_POLL_LOG_BODY` | `false` | Log de depuración de claves JSON del poll. |
| `WHATSAPP_ALLOWED_SENDER_NUMBERS` | *(vacío)* | Solo dígitos (E.164 sin `+`), separados por coma. Vacío = todos los chats 1:1. |
| `WHATSAPP_PROCESS_FROM_ME` | `false` | `true` si tus mensajes llegan como `is_from_me` (mismo número que GOWA); puede requerir filtro de eco. |
| `WHATSAPP_FROM_ME_MAX_QUESTION_CHARS` | `4000` | Con `PROCESS_FROM_ME`, ignora textos `from_me` más largos (heurística anti-respuesta del bot). |

**Eco / bucles:** el código registra el texto enviado con `POST /send/text` y evita volver a pasar por el RAG el mismo contenido en el mismo chat durante ~15 minutos.

**Red:** el host del backend debe resolver la IP del Jetson; para webhooks desde el Jetson hacia tu PC de desarrollo, suele usarse `uvicorn --host 0.0.0.0`.

---

## Frontend (`frontend/.env`)

Solo las variables con prefijo **`VITE_`** llegan al código del navegador.

| Variable | Valor ejemplo | Definición | Razón del valor por defecto |
|----------|---------------|------------|------------------------------|
| `VITE_API_BASE_URL` | `http://127.0.0.1:3333` | URL base del backend FastAPI **sin barra final**. | Misma máquina y puertos por defecto del README (backend en **3333**). En producción sustituye por la URL pública del API. Si no se define, el código usa el valor por defecto embebido en `frontend/src/api.ts`. |

**Seguridad:** nunca pongas `OPENAI_API_KEY` ni secretos en el frontend; solo esta URL pública del backend.

---

## Referencias

- Definición técnica de campos: `backend/app/config.py`
- Instrucciones del LLM (no son variables de entorno; se editan en código): `backend/app/prompts.py`
- Plantilla copiable: `backend/.env.example`, `frontend/.env.example`
- Arquitectura y diagramas: [ARQUITECTURA.md](./ARQUITECTURA.md)
