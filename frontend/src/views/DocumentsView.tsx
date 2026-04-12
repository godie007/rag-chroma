import { useCallback, useRef, useState } from 'react'
import {
  ingestFiles,
  resetVectorIndex,
  type ConfigPublic,
  type StatsResponse,
} from '../api'
import { Icon } from '../components/Icon'

type QueueItem = {
  id: string
  file: File
  status: 'pending' | 'uploading' | 'indexed' | 'error'
  detail?: string
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function DocumentsView({
  config,
  stats,
  onRefreshStats,
  onRagStatsPatch,
}: {
  config: ConfigPublic | null
  stats: StatsResponse | null
  onRefreshStats: () => Promise<void>
  onRagStatsPatch: (patch: Partial<StatsResponse>) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [ingestLoading, setIngestLoading] = useState(false)
  const [ingestProgress, setIngestProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [resetLoading, setResetLoading] = useState(false)
  const [resetModalError, setResetModalError] = useState<string | null>(null)
  const [showEmptyModal, setShowEmptyModal] = useState(false)

  const maxBytes = config?.max_upload_bytes ?? 25 * 1024 * 1024
  const maxLabel = formatBytes(maxBytes)
  const hasLargePending = queue.some(
    (x) => x.status === 'pending' && x.file.size >= 4 * 1024 * 1024,
  )

  const addFiles = useCallback((files: FileList | File[]) => {
    const list = Array.from(files)
    setQueue((q) => {
      const next = [...q]
      let i = next.length
      for (const file of list) {
        next.push({
          id: `${file.name}-${file.size}-${i++}-${Date.now()}`,
          file,
          status: 'pending',
        })
      }
      return next
    })
  }, [])

  const onPickFiles = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files?.length) addFiles(e.target.files)
      e.target.value = ''
    },
    [addFiles],
  )

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files)
    },
    [addFiles],
  )

  const onIngestQueue = useCallback(async () => {
    const pending = queue.filter((x) => x.status === 'pending')
    if (!pending.length || ingestLoading) return
    setError(null)
    setIngestLoading(true)
    setIngestProgress(4)
    const total = pending.length
    const tick = window.setInterval(() => {
      setIngestProgress((p) => (p < 94 ? p + 1 : p))
    }, 800)
    try {
      for (let i = 0; i < pending.length; i++) {
        const item = pending[i]
        setQueue((q) =>
          q.map((x) => (x.id === item.id ? { ...x, status: 'uploading' as const } : x)),
        )
        const basePct = Math.round((i / total) * 100)
        setIngestProgress(Math.min(94, basePct + 4))
        try {
          const res = await ingestFiles([item.file])
          const msg = res.messages[0] ?? ''
          setQueue((q) =>
            q.map((x) => {
              if (x.id !== item.id) return x
              if (msg.startsWith('Omitido')) {
                return { ...x, status: 'error' as const, detail: msg }
              }
              return { ...x, status: 'indexed' as const, detail: msg }
            }),
          )
        } catch (err) {
          const isTimeout =
            err instanceof Error &&
            (err.name === 'TimeoutError' || err.name === 'AbortError')
          const detail = isTimeout
            ? 'Tiempo de espera agotado (PDF muy grande: aumenta el límite en api.ts o indexa desde el servidor).'
            : err instanceof Error
              ? err.message
              : 'Error de red o del servidor'
          setError(detail)
          setQueue((q) =>
            q.map((x) =>
              x.id === item.id ? { ...x, status: 'error' as const, detail } : x,
            ),
          )
        }
        setIngestProgress(Math.round(((i + 1) / total) * 100))
        await onRefreshStats()
      }
      setIngestProgress(100)
    } finally {
      window.clearInterval(tick)
      setIngestLoading(false)
      window.setTimeout(() => setIngestProgress(0), 400)
    }
  }, [queue, ingestLoading, onRefreshStats])

  const onConfirmEmpty = useCallback(async () => {
    setError(null)
    setResetModalError(null)
    setResetLoading(true)
    try {
      const res = await resetVectorIndex()
      setShowEmptyModal(false)
      onRagStatsPatch({
        chunk_count: res.chunk_count,
        ready: res.ready,
        collection: res.collection,
      })
      setQueue([])
      await onRefreshStats()
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : 'Error al vaciar el índice. Revisa la consola de red.'
      setResetModalError(msg)
      setError(msg)
    } finally {
      setResetLoading(false)
    }
  }, [onRefreshStats, onRagStatsPatch])

  const chunkCount = stats?.chunk_count ?? 0

  return (
    <main className="p-6 md:p-8 min-h-screen bg-surface">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".txt,.md,.markdown,.pdf"
        className="hidden"
        onChange={onPickFiles}
      />

      <div className="mb-10 flex flex-col gap-4 md:flex-row md:justify-between md:items-end">
        <div>
          <h1 className="text-3xl md:text-4xl font-extrabold tracking-tighter text-on-background mb-1 font-headline">
            RAG · Conocimiento interno
          </h1>
          <p className="text-on-surface-variant font-medium text-sm md:text-base">
            Gestión de documentos y optimización de fragmentación semántica.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={ingestLoading || resetLoading}
            className="px-5 md:px-6 py-2.5 bg-surface-container-high text-on-surface-variant rounded-md font-bold text-sm hover:bg-surface-container-highest transition-colors flex items-center gap-2 outline outline-1 outline-outline-variant/15 disabled:opacity-50"
          >
            <Icon name="sync" className="text-sm" />
            Añadir archivos
          </button>
          <button
            type="button"
            onClick={() => {
              setResetModalError(null)
              setShowEmptyModal(true)
            }}
            disabled={resetLoading || ingestLoading}
            className="px-5 md:px-6 py-2.5 bg-error text-on-error rounded-md font-bold text-sm hover:opacity-90 transition-opacity flex items-center gap-2 disabled:opacity-50"
          >
            <Icon name="delete_forever" className="text-sm" />
            Vaciar índice
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-error/30 bg-error-container/20 px-4 py-3 text-sm text-on-error-container">
          {error}
        </div>
      )}

      <div className="grid grid-cols-12 gap-6 md:gap-8">
        <div className="col-span-12 lg:col-span-4">
          <div className="bg-surface-container-low p-6 md:p-8 rounded-xl">
            <h3 className="text-xs font-bold uppercase tracking-widest text-on-surface-variant mb-2">
              Parámetros de recuperación
            </h3>
            <p className="text-[10px] text-on-surface-variant mb-4">
              Valores efectivos del servidor (configura en <code className="font-mono">backend/.env</code>).
            </p>
            <div className="space-y-4">
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase mb-1 block">
                  Temperatura chat (LLM)
                </label>
                <input
                  className="w-full bg-surface-container-lowest border-none rounded-lg text-sm font-bold text-primary focus:ring-2 focus:ring-primary/20 opacity-90"
                  type="text"
                  readOnly
                  disabled={!config}
                  value={config != null ? String(config.openai_chat_temperature) : ''}
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase mb-1 block">
                  Máx. tokens de salida (chat)
                </label>
                <input
                  className="w-full bg-surface-container-lowest border-none rounded-lg text-sm font-bold text-primary focus:ring-2 focus:ring-primary/20 opacity-90"
                  type="number"
                  readOnly
                  disabled={!config}
                  value={config?.openai_chat_max_output_tokens ?? ''}
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase mb-1 block">
                  Tamaño de fragmento (caracteres)
                </label>
                <input
                  className="w-full bg-surface-container-lowest border-none rounded-lg text-sm font-bold text-primary focus:ring-2 focus:ring-primary/20 opacity-90"
                  type="number"
                  readOnly
                  disabled={!config}
                  value={config?.chunk_size ?? ''}
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase mb-1 block">
                  Solapamiento
                </label>
                <input
                  className="w-full bg-surface-container-lowest border-none rounded-lg text-sm font-bold text-primary focus:ring-2 focus:ring-primary/20 opacity-90"
                  type="number"
                  readOnly
                  disabled={!config}
                  value={config?.chunk_overlap ?? ''}
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase mb-1 block">
                  Mín. caracteres por trozo (fusión)
                </label>
                <input
                  className="w-full bg-surface-container-lowest border-none rounded-lg text-sm font-bold text-primary focus:ring-2 focus:ring-primary/20 opacity-90"
                  type="number"
                  readOnly
                  disabled={!config}
                  value={config?.chunk_min_chars ?? ''}
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase mb-1 block">
                  Tope fusión de trozos (caracteres)
                </label>
                <input
                  className="w-full bg-surface-container-lowest border-none rounded-lg text-sm font-bold text-primary focus:ring-2 focus:ring-primary/20 opacity-90"
                  type="number"
                  readOnly
                  disabled={!config}
                  value={config?.chunk_merge_hard_max ?? ''}
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase mb-1 block">Top K</label>
                <input
                  className="w-full bg-surface-container-lowest border-none rounded-lg text-sm font-bold text-primary focus:ring-2 focus:ring-primary/20 opacity-90"
                  type="number"
                  readOnly
                  disabled={!config}
                  value={config?.top_k ?? ''}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-8">
          <div className="bg-surface-container-lowest p-1 rounded-xl shadow-sm min-h-[420px] flex flex-col">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              onDrop={onDrop}
              className="m-2 p-10 md:p-12 border-2 border-dashed border-outline-variant/30 rounded-xl bg-surface-container-low flex flex-col items-center justify-center text-center group cursor-pointer hover:bg-surface-container-high transition-colors"
            >
              <div className="w-16 h-16 rounded-full bg-white shadow-sm flex items-center justify-center text-primary mb-4 group-hover:scale-110 transition-transform">
                <Icon name="cloud_upload" className="text-3xl" />
              </div>
              <h4 className="font-bold text-on-surface">Arrastra nuevos documentos</h4>
              <p className="text-sm text-on-surface-variant mt-1">
                PDF, TXT o Markdown hasta {maxLabel} cada uno.
              </p>
            </button>

            <div className="px-4 md:px-8 pb-4 flex flex-col gap-2">
              {hasLargePending && !ingestLoading && (
                <p className="text-[11px] text-on-surface-variant leading-snug">
                  Hay PDFs ≥ 4&nbsp;MB en cola: la indexación puede tardar <strong>varios minutos u horas</strong>{' '}
                  (muchas páginas → miles de fragmentos y llamadas a embeddings). El servidor sigue trabajando: mira la
                  consola del backend para ver el progreso.
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void onIngestQueue()}
                  disabled={ingestLoading || !queue.some((q) => q.status === 'pending')}
                  className="px-4 py-2 bg-primary text-on-primary rounded-md text-xs font-bold hover:bg-primary-dim disabled:opacity-50"
                >
                  {ingestLoading ? 'Indexando…' : 'Indexar cola'}
                </button>
              </div>
            </div>

            {ingestLoading && (
              <div className="px-6 md:px-8 py-6 bg-primary/5">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-xs font-bold text-primary flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                    Indexando…
                  </span>
                  <span className="text-xs font-bold text-primary">{ingestProgress}%</span>
                </div>
                <div className="h-1.5 w-full bg-primary/10 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-500"
                    style={{ width: `${ingestProgress}%` }}
                  />
                </div>
              </div>
            )}

            <div className="flex-1 px-6 md:px-8 py-4 overflow-y-auto">
              <h3 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-4">
                Cola de archivos
              </h3>
              {queue.length === 0 ? (
                <p className="text-sm text-on-surface-variant">No hay archivos en cola.</p>
              ) : (
                <div className="space-y-4">
                  {queue.map((item) => (
                    <div
                      key={item.id}
                      className={`flex items-center p-4 bg-surface rounded-xl hover:shadow-md transition-shadow relative ${
                        item.status === 'indexed' ? 'pl-3' : ''
                      }`}
                    >
                      {item.status === 'indexed' && (
                        <div className="absolute left-0 top-1/4 bottom-1/4 w-1 bg-secondary rounded-full" />
                      )}
                      <div className="flex items-center gap-4 min-w-0 flex-1">
                        <div
                          className={`w-10 h-10 rounded-lg bg-white flex items-center justify-center shrink-0 ${
                            item.status === 'indexed' ? 'text-secondary' : 'text-slate-400'
                          }`}
                        >
                          <Icon
                            name={item.status === 'indexed' ? 'task_alt' : 'description'}
                            filled={item.status === 'indexed'}
                          />
                        </div>
                        <div className="min-w-0">
                          <div className="text-sm font-bold text-on-surface truncate">{item.file.name}</div>
                          <div className="text-[10px] text-on-surface-variant uppercase font-medium">
                            {formatBytes(item.file.size)} ·{' '}
                            {item.status === 'pending' && 'Pendiente'}
                            {item.status === 'uploading' && 'Procesando'}
                            {item.status === 'indexed' && 'Indexado'}
                            {item.status === 'error' && (item.detail ?? 'Error')}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {showEmptyModal && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-[100] flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 w-full max-w-md rounded-2xl shadow-2xl overflow-hidden border border-slate-200 dark:border-slate-700">
            <div className="p-8 text-center">
              <div className="w-20 h-20 bg-error-container rounded-full flex items-center justify-center text-on-error-container mx-auto mb-6">
                <Icon name="warning" className="text-4xl" />
              </div>
              <h2 className="text-2xl font-extrabold text-on-surface tracking-tight mb-2 font-headline">
                ¿Vaciar el índice?
              </h2>
              <p className="text-on-surface-variant text-sm leading-relaxed mb-8">
                Esta acción es irreversible. Se borran los{' '}
                <span className="font-bold text-on-surface">{chunkCount} chunks</span> y los archivos físicos de la
                base Chroma en disco; no quedará índice hasta que vuelvas a ingerir documentos.
              </p>
              {resetModalError && (
                <p className="text-left text-sm text-error font-medium mb-4 rounded-lg border border-error/30 bg-error-container/15 px-3 py-2">
                  {resetModalError}
                </p>
              )}
              <div className="flex flex-col gap-3">
                <button
                  type="button"
                  onClick={() => void onConfirmEmpty()}
                  disabled={resetLoading}
                  className="w-full py-3 bg-error text-white rounded-xl font-bold hover:opacity-90 transition-all active:scale-[0.98] disabled:opacity-50"
                >
                  {resetLoading ? '…' : 'Sí, eliminar todo el contenido'}
                </button>
                <button
                  type="button"
                  disabled={resetLoading}
                  onClick={() => {
                    setResetModalError(null)
                    setShowEmptyModal(false)
                  }}
                  className="w-full py-3 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-xl font-bold hover:bg-slate-200 dark:hover:bg-slate-700 transition-all active:scale-[0.98] disabled:opacity-50"
                >
                  No, mantener mis datos
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
