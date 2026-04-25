import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchConfig,
  fetchStats,
  getApiBase,
  type ConfigPublic,
  type StatsResponse,
} from './api'
import { AppShell, type AppView } from './layout/AppShell'
import { ChatView } from './views/ChatView'
import { DocumentsView } from './views/DocumentsView'
import { EvaluationView } from './views/EvaluationView'
import { ConfigurationsView } from './views/ConfigurationsView'
import { WhatsAppSettingsView } from './views/WhatsAppSettingsView'

const VIEW_TO_PATH: Record<AppView, string> = {
  documents: '#/documents',
  chat: '#/chat',
  evaluation: '#/evaluation',
  whatsapp: '#/whatsapp',
  settings: '#/settings',
}

function hashToView(rawHash: string): AppView {
  const clean = (rawHash || '#/documents').replace(/\/+$/, '') || '#/documents'
  switch (clean) {
    case '#':
    case '#/':
    case '#/documents':
      return 'documents'
    case '#/chat':
      return 'chat'
    case '#/evaluation':
      return 'evaluation'
    case '#/whatsapp':
      return 'whatsapp'
    case '#/settings':
      return 'settings'
    default:
      return 'documents'
  }
}

function App() {
  const [view, setViewState] = useState<AppView>(() =>
    typeof window === 'undefined' ? 'documents' : hashToView(window.location.hash),
  )
  const [stats, setStats] = useState<StatsResponse | null>(null)
  /** Hasta el primer GET /stats terminado no mostrar "0 fragmentos" como si fuera el total real. */
  /** Solo true hasta el primer GET /stats (éxito o error), para no mostrar 0 al recargar. Refrescos posteriores no enmascaran el total. */
  const [statsLoading, setStatsLoading] = useState(true)
  const statsFirstSettled = useRef(false)
  const [config, setConfig] = useState<ConfigPublic | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  const refreshStats = useCallback(async (): Promise<StatsResponse | null> => {
    if (!statsFirstSettled.current) {
      setStatsLoading(true)
    }
    try {
      const s = await fetchStats()
      setStats(s)
      setBanner(null)
      return s
    } catch {
      setStats(null)
      setBanner(`No se pudo conectar con ${getApiBase()}. ¿Está el backend en marcha?`)
      return null
    } finally {
      if (!statsFirstSettled.current) {
        statsFirstSettled.current = true
        setStatsLoading(false)
      }
    }
  }, [])

  const patchRagStats = useCallback((patch: Partial<StatsResponse>) => {
    setStats((prev) => {
      if (!prev) {
        return {
          ready: patch.ready ?? true,
          chunk_count: patch.chunk_count ?? 0,
          collection: patch.collection ?? '',
        }
      }
      return { ...prev, ...patch }
    })
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        setConfig(await fetchConfig())
      } catch {
        setConfig(null)
      }
      await refreshStats()
    })()
  }, [refreshStats])

  useEffect(() => {
    const onHashChange = () => {
      setViewState(hashToView(window.location.hash))
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const setView = useCallback((next: AppView) => {
    setViewState(next)
    if (typeof window === 'undefined') return
    const targetHash = VIEW_TO_PATH[next] ?? '#/documents'
    const currentHash = window.location.hash || ''
    if (currentHash !== targetHash) {
      window.location.hash = targetHash
    }
  }, [])

  useEffect(() => {
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) void refreshStats()
    }
    window.addEventListener('pageshow', onPageShow)
    return () => window.removeEventListener('pageshow', onPageShow)
  }, [refreshStats])

  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | undefined
    const schedule = () => {
      window.clearTimeout(t)
      t = window.setTimeout(() => void refreshStats(), 150)
    }
    const onVisible = () => {
      if (document.visibilityState === 'visible') schedule()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', schedule)
    return () => {
      window.clearTimeout(t)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', schedule)
    }
  }, [refreshStats])

  return (
    <AppShell view={view} setView={setView} stats={stats} statsLoading={statsLoading}>
      {banner && (
        <div className="mx-4 md:mx-8 mt-4 rounded-lg border border-tertiary/30 bg-tertiary-container/10 px-4 py-2.5 text-sm text-on-tertiary-container flex items-center gap-2.5 shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-tertiary shrink-0" />
          {banner}
        </div>
      )}
      <div className="flex flex-1 flex-col min-h-0">
        <div
          className={
            view === 'documents'
              ? 'flex min-h-0 flex-1 flex-col overflow-y-auto'
              : 'hidden'
          }
          aria-hidden={view !== 'documents'}
        >
          <DocumentsView
            config={config}
            stats={stats}
            statsLoading={statsLoading}
            onRefreshStats={refreshStats}
            onRagStatsPatch={patchRagStats}
          />
        </div>
        <div
          className={
            view === 'chat'
              ? 'flex min-h-0 flex-1 flex-col overflow-hidden min-h-[calc(100dvh-4.5rem)]'
              : 'hidden'
          }
          aria-hidden={view !== 'chat'}
        >
          <ChatView stats={stats} statsLoading={statsLoading} />
        </div>
        <div
          className={
            view === 'evaluation'
              ? 'flex min-h-0 flex-1 flex-col overflow-y-auto'
              : 'hidden'
          }
          aria-hidden={view !== 'evaluation'}
        >
          <EvaluationView
            stats={stats}
            statsLoading={statsLoading}
            onGoDocuments={() => setView('documents')}
          />
        </div>
        <div
          className={
            view === 'whatsapp'
              ? 'flex min-h-0 flex-1 flex-col overflow-y-auto'
              : 'hidden'
          }
          aria-hidden={view !== 'whatsapp'}
        >
          <WhatsAppSettingsView config={config} stats={stats} statsLoading={statsLoading} />
        </div>
        <div
          className={
            view === 'settings'
              ? 'flex min-h-0 flex-1 flex-col overflow-y-auto'
              : 'hidden'
          }
          aria-hidden={view !== 'settings'}
        >
          <ConfigurationsView stats={stats} statsLoading={statsLoading} />
        </div>
      </div>
    </AppShell>
  )
}

export default App
