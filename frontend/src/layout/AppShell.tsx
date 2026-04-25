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
      className={[
        'relative pb-1 shrink-0 text-sm font-semibold tracking-tight transition-colors duration-150',
        active
          ? 'text-on-surface'
          : 'text-on-surface-variant hover:text-on-surface',
      ].join(' ')}
    >
      {label}
      {active && (
        <span className="absolute bottom-0 left-0 right-0 h-[2px] rounded-full bg-primary" />
      )}
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
      <header className="sticky top-0 z-50 shrink-0 liquid-glass border-b border-outline/60">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between w-full px-4 md:px-8 py-3.5 max-w-full">
          <div className="flex flex-col gap-3 min-w-0 sm:flex-row sm:items-center sm:gap-8">
            <span className="text-base font-bold text-on-surface tracking-[-0.03em] font-headline truncate select-none">
              RAG
              <span className="text-on-surface-variant font-medium mx-1">·</span>
              <span className="text-primary">Control de calidad</span>
            </span>
            <nav className="flex flex-wrap items-center gap-5 sm:gap-6 font-manrope">
              <NavTab active={view === 'documents'}    label="Documentos"      onClick={() => setView('documents')} />
              <NavTab active={view === 'chat'}         label="Chat"            onClick={() => setView('chat')} />
              <NavTab active={view === 'evaluation'}   label="Evaluación"      onClick={() => setView('evaluation')} />
              <NavTab active={view === 'whatsapp'}     label="WhatsApp"        onClick={() => setView('whatsapp')} />
              <NavTab active={view === 'settings'}     label="Configuraciones" onClick={() => setView('settings')} />
            </nav>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs shrink-0">
            <span
              className="inline-flex items-center gap-2 px-3 py-1.5 bg-surface-container-low rounded-full border border-outline/50 max-w-[min(100%,22rem)] min-w-0"
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
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${
                  ready ? 'bg-secondary shadow-[0_0_6px_theme(colors.secondary/0.5)]' : 'bg-error'
                }`}
              />
              <span className="font-semibold text-on-surface-variant truncate">
                {countLabel}
                {stats?.collection && !statsLoading ? (
                  <span className="text-on-surface-variant/60"> · {stats.collection}</span>
                ) : null}
              </span>
            </span>

            <a
              href={`${apiBase}/health`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-xs text-primary/80 hover:text-primary transition-colors underline-offset-2 hover:underline"
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
