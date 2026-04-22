/**
 * Prefijo para `fetch`: cadena vacía = mismo origen que la página (producción detrás de Nginx).
 * Solo `??` no basta: `.env` puede tener VITE_API_BASE_URL= (vacío explícito).
 */
function apiBasePrefix(): string {
  const raw = import.meta.env.VITE_API_BASE_URL
  if (raw === undefined || raw === null) return 'http://127.0.0.1:3333'
  const s = String(raw).trim()
  if (s === '') return ''
  return s.replace(/\/$/, '')
}

const base = apiBasePrefix()

/** URL absoluta para `new URL()` (evita "Invalid URL" cuando el prefijo es vacío). */
function apiAbsoluteUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  if (base === '') {
    if (typeof window !== 'undefined' && window.location?.origin) {
      return `${window.location.origin}${p}`
    }
    return `http://127.0.0.1:3333${p}`
  }
  return `${base}${p}`
}

export type ChatSource = { content: string; metadata: Record<string, unknown> }

export type ChatResponse = {
  answer: string
  sources: ChatSource[]
  thread_id: string
  response_type: 'answer' | 'clarification'
}

export type IngestResponse = {
  files_processed: number
  chunks_added: number
  messages: string[]
}

async function handle(res: Response): Promise<void> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      if (j?.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      void 0
    }
    throw new Error(detail)
  }
}

/** PDFs muy grandes pueden tardar muchos minutos (extracción + miles de embeddings). */
const INGEST_TIMEOUT_MS = 3_600_000

function ingestAbortSignal(): AbortSignal | undefined {
  if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
    return AbortSignal.timeout(INGEST_TIMEOUT_MS)
  }
  return undefined
}

export async function ingestFiles(files: File[]): Promise<IngestResponse> {
  const fd = new FormData()
  for (const f of files) fd.append('files', f)
  const res = await fetch(`${base}/ingest`, {
    method: 'POST',
    body: fd,
    signal: ingestAbortSignal(),
  })
  await handle(res)
  return res.json()
}

export type ResetIndexResponse = {
  status: string
  collection: string
  message: string
  chunk_count: number
  ready: boolean
}

const RESET_INDEX_TIMEOUT_MS = 120_000

export async function resetVectorIndex(): Promise<ResetIndexResponse> {
  const res = await fetch(`${base}/ingest/reset`, {
    method: 'POST',
    cache: 'no-store',
    signal:
      typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
        ? AbortSignal.timeout(RESET_INDEX_TIMEOUT_MS)
        : undefined,
  })
  await handle(res)
  return res.json()
}

export type DeleteIndexedSourceResponse = {
  source: string
  chunks_removed: number
  chunk_count: number
  ready: boolean
}

export async function deleteIndexedSource(source: string): Promise<DeleteIndexedSourceResponse> {
  const res = await fetch(`${base}/ingest/delete-source`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source }),
    cache: 'no-store',
  })
  await handle(res)
  return res.json()
}

const CHAT_THREAD_KEY = 'rag_chat_thread_id'

export function getChatThreadId(): string | null {
  if (typeof window === 'undefined' || !window.sessionStorage) return null
  return window.sessionStorage.getItem(CHAT_THREAD_KEY)
}

export function setChatThreadId(id: string | null): void {
  if (typeof window === 'undefined' || !window.sessionStorage) return
  if (id) window.sessionStorage.setItem(CHAT_THREAD_KEY, id)
  else window.sessionStorage.removeItem(CHAT_THREAD_KEY)
}

export async function chat(
  question: string,
  threadId: string | null = getChatThreadId()
): Promise<ChatResponse> {
  const body: { question: string; thread_id?: string } = { question }
  if (threadId) body.thread_id = threadId
  const res = await fetch(`${base}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  await handle(res)
  return res.json()
}

export function getApiBase(): string {
  return base === '' && typeof window !== 'undefined' && window.location?.origin
    ? window.location.origin
    : base || 'http://127.0.0.1:3333'
}

export type StatsResponse = {
  ready: boolean
  chunk_count: number
  collection: string
}

export type ConfigPublic = {
  openai_chat_temperature: number
  openai_chat_max_output_tokens: number
  chunk_size: number
  chunk_overlap: number
  chunk_min_chars: number
  chunk_merge_hard_max: number
  top_k: number
  use_mmr: boolean
  mmr_fetch_k: number
  mmr_lambda: number
  max_upload_bytes: number
  retrieve_max_l2_distance: number
  retrieve_relevance_margin: number
  retrieve_elbow_l2_gap: number
  rag_clarification_enabled: boolean
  rag_clarification_max_rounds: number
  whatsapp_polling_active: boolean
  whatsapp_webhook_active: boolean
  whatsapp_poll_mode: 'recent' | 'chats'
  whatsapp_api_base_url: string
  whatsapp_poll_interval_sec: number
}

export async function fetchStats(): Promise<StatsResponse> {
  const res = await fetch(`${base}/stats`, { cache: 'no-store' })
  await handle(res)
  return res.json()
}

export type IndexedSourcesResponse = { sources: string[] }

export async function fetchIndexedSources(): Promise<IndexedSourcesResponse> {
  const res = await fetch(`${base}/stats/sources`, { cache: 'no-store' })
  await handle(res)
  return res.json()
}

export async function fetchConfig(): Promise<ConfigPublic> {
  const res = await fetch(`${base}/config`)
  await handle(res)
  return res.json()
}

export type WhatsAppAllowlistResponse = {
  numbers: string[]
  source: 'file' | 'env'
}

export async function fetchWhatsAppAllowlist(): Promise<WhatsAppAllowlistResponse> {
  const res = await fetch(`${base}/whatsapp/allowlist`, { cache: 'no-store' })
  await handle(res)
  return res.json()
}

export async function addWhatsAppAllowlistNumber(number: string): Promise<WhatsAppAllowlistResponse> {
  const res = await fetch(`${base}/whatsapp/allowlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ number }),
  })
  await handle(res)
  return res.json()
}

export async function removeWhatsAppAllowlistNumber(number: string): Promise<WhatsAppAllowlistResponse> {
  const u = new URL(apiAbsoluteUrl('/whatsapp/allowlist'))
  u.searchParams.set('number', number)
  const res = await fetch(u.toString(), { method: 'DELETE' })
  await handle(res)
  return res.json()
}

export async function revertWhatsAppAllowlistToEnv(): Promise<WhatsAppAllowlistResponse> {
  const res = await fetch(`${base}/whatsapp/allowlist/revert-env`, { method: 'POST' })
  await handle(res)
  return res.json()
}

export type RagasEvaluateResponse = {
  eval_file: string
  averages: Record<string, number>
  metric_labels_es: Record<string, string>
  ragas_metric_keys: string[]
  per_question: {
    question: string
    answer_preview?: string
    scores: Record<string, number | null>
  }[]
}

export type SystemPromptsConfig = {
  system_rag_web: string
  system_rag_whatsapp: string
  system_no_retrieval_web: string
  system_no_retrieval_whatsapp: string
}

export async function fetchSystemPrompts(): Promise<SystemPromptsConfig> {
  const res = await fetch(`${base}/config/prompts`, { cache: 'no-store' })
  await handle(res)
  return res.json()
}

export async function saveSystemPrompts(updates: Partial<SystemPromptsConfig>): Promise<SystemPromptsConfig> {
  const res = await fetch(`${base}/config/prompts`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  await handle(res)
  return res.json()
}

export async function resetSystemPromptsToCodeDefaults(): Promise<SystemPromptsConfig> {
  const res = await fetch(`${base}/config/prompts`, { method: 'DELETE' })
  await handle(res)
  return res.json()
}

export async function runRagasEvaluation(evalRelativePath?: string | null): Promise<RagasEvaluateResponse> {
  const u = new URL(apiAbsoluteUrl('/evaluate'))
  if (evalRelativePath?.trim()) {
    u.searchParams.set('eval_relative_path', evalRelativePath.trim())
  }
  const res = await fetch(u.toString(), {
    method: 'POST',
    signal: AbortSignal.timeout(600_000),
  })
  await handle(res)
  return res.json()
}
