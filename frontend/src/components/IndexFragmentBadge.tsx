import type { StatsResponse } from '../api'

/** Misma métrica que el chip del header: fragmentos (vectores) en Chroma. */
export function IndexFragmentBadge({
  stats,
  statsLoading = false,
  className = '',
}: {
  stats: StatsResponse | null
  statsLoading?: boolean
  className?: string
}) {
  const n = stats?.chunk_count
  const ready = stats?.ready ?? false
  if (statsLoading) {
    return (
      <span className={`text-xs text-on-surface-variant ${className}`.trim()}>Consultando el índice…</span>
    )
  }
  if (n == null) {
    return (
      <span className={`text-xs text-on-surface-variant ${className}`.trim()}>Sin datos del índice</span>
    )
  }
  return (
    <span
      className={`inline-flex items-center gap-2 text-xs font-semibold text-on-surface ${className}`.trim()}
      title={stats?.collection ? `${n} fragmentos · ${stats.collection}` : `${n} fragmentos`}
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${ready ? 'bg-secondary' : 'bg-error'}`} />
      <span>
        {n} fragmento{n === 1 ? '' : 's'} en el índice
      </span>
    </span>
  )
}
