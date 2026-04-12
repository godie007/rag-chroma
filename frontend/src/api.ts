const base = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

export type ChatSource = { content: string; metadata: Record<string, unknown> }

export type ChatResponse = { answer: string; sources: ChatSource[] }

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

export async function chat(question: string): Promise<ChatResponse> {
  const res = await fetch(`${base}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  await handle(res)
  return res.json()
}

export function getApiBase(): string {
  return base
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
  evolution_webhook_enabled: boolean
  evolution_api_base_url: string
  evolution_reply_in_groups: boolean
}

export async function fetchStats(): Promise<StatsResponse> {
  const res = await fetch(`${base}/stats`, { cache: 'no-store' })
  await handle(res)
  return res.json()
}

export async function fetchConfig(): Promise<ConfigPublic> {
  const res = await fetch(`${base}/config`)
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

export async function runRagasEvaluation(evalRelativePath?: string | null): Promise<RagasEvaluateResponse> {
  const u = new URL(`${base}/evaluate`)
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
