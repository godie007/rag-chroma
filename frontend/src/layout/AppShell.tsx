import type { StatsResponse } from '../api'
import { getApiBase } from '../api'

export type AppView = 'documents' | 'chat' | 'evaluation' | 'whatsapp' | 'settings'

type AppShellProps = {
  view: AppView
  setView: (v: AppView) => void
  stats: StatsResponse | null
  /** Hasta el primer /stats, no tratar 0 o vacío como dato real. */
  statsLoading: boolean
  children: React.ReactNode
}

function NavTab({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? 'text-slate-900 dark:text-white border-b-2 border-slate-600 dark:border-slate-300 pb-1 shrink-0'
          : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors shrink-0'
      }
    >
      {label}
    </button>
  )
}

export function AppShell({ view, setView, stats, statsLoading, children }: AppShellProps) {
  const apiBase = getApiBase()
  const chunks = stats?.chunk_count
  const ready = stats?.ready ?? false
  const countLabel = statsLoading
    ? 'Cargando…'
    : chunks != null
      ? `${chunks} fragmentos`
      : 'Sin datos'

  return (
    <div className="min-h-screen flex flex-col bg-background text-on-background font-body">
      <header className="sticky top-0 z-50 bg-slate-50/80 dark:bg-slate-900/80 backdrop-blur-xl shadow-sm dark:shadow-none shrink-0 border-b border-outline-variant/10">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between w-full px-4 md:px-8 py-3 max-w-full">
          <div className="flex flex-col gap-3 min-w-0 sm:flex-row sm:items-center sm:gap-8">
            <span className="text-lg font-bold text-slate-800 dark:text-slate-100 tracking-tighter font-headline truncate">
              RAG · Control de calidad
            </span>
            <nav className="flex flex-wrap items-center gap-4 sm:gap-6 text-sm font-semibold tracking-tight font-manrope">
              <NavTab active={view === 'documents'} label="Documentos" onClick={() => setView('documents')} />
              <NavTab active={view === 'chat'} label="Chat" onClick={() => setView('chat')} />
              <NavTab active={view === 'evaluation'} label="Evaluación" onClick={() => setView('evaluation')} />
              <NavTab active={view === 'whatsapp'} label="WhatsApp" onClick={() => setView('whatsapp')} />
              <NavTab active={view === 'settings'} label="Configuraciones" onClick={() => setView('settings')} />
            </nav>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-on-surface-variant shrink-0">
            <span
              className="inline-flex items-center gap-2 px-3 py-1 bg-surface-container-low rounded-full max-w-[min(100%,22rem)] min-w-0"
              title={
                [
                  ready ? 'RAG operativo' : 'RAG no disponible o sin clave',
                  statsLoading ? 'Consultando el servidor' : chunks != null ? `${chunks} fragmentos` : null,
                  stats?.collection,
                ]
                  .filter(Boolean)
                  .join(' · ') || undefined
              }
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${ready ? 'bg-secondary' : 'bg-error'}`} />
              <span className="font-semibold text-on-surface truncate">
                {countLabel}
                {stats?.collection && !statsLoading ? ` · ${stats.collection}` : ''}
              </span>
            </span>
            <a
              href={`${apiBase}/health`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-primary hover:text-primary-dim underline-offset-2 hover:underline"
            >
              /health
            </a>
          </div>
        </div>
      </header>
      <div className="flex-1 flex flex-col min-h-0">{children}</div>
    </div>
  )
}
