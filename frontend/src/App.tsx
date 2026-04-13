import { useCallback, useEffect, useState } from 'react'
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

function App() {
  const [view, setView] = useState<AppView>('documents')
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [config, setConfig] = useState<ConfigPublic | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  const refreshStats = useCallback(async () => {
    try {
      const s = await fetchStats()
      setStats(s)
      setBanner(null)
    } catch {
      setStats(null)
      setBanner(`No se pudo conectar con ${getApiBase()}. ¿Está el backend en marcha?`)
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
      try {
        setStats(await fetchStats())
        setBanner(null)
      } catch {
        setStats(null)
        setBanner(`No se pudo conectar con ${getApiBase()}. ¿Está el backend en marcha?`)
      }
    })()
  }, [])

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
    <AppShell view={view} setView={setView} stats={stats}>
      {banner && (
        <div className="mx-4 md:mx-8 mt-4 rounded-lg border border-tertiary/40 bg-tertiary-container/15 px-4 py-2 text-sm text-on-tertiary-container shrink-0">
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
          <ChatView config={config} stats={stats} />
        </div>
        <div
          className={
            view === 'evaluation'
              ? 'flex min-h-0 flex-1 flex-col overflow-y-auto'
              : 'hidden'
          }
          aria-hidden={view !== 'evaluation'}
        >
          <EvaluationView stats={stats} onGoDocuments={() => setView('documents')} />
        </div>
      </div>
    </AppShell>
  )
}

export default App
