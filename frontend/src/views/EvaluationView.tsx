import { useCallback, useState } from 'react'
import { runRagasEvaluation, type RagasEvaluateResponse, type StatsResponse } from '../api'
import { IndexFragmentBadge } from '../components/IndexFragmentBadge'
import { Icon } from '../components/Icon'

const PRESET_FILES = ['evals/sample_eval.jsonl']

function scoreBand(v: number): { tag: string; border: string } {
  if (!Number.isFinite(v)) return { tag: '—', border: 'border-outline-variant' }
  if (v >= 0.85) return { tag: 'Excelente', border: 'border-secondary' }
  if (v >= 0.65) return { tag: 'Fuerte', border: 'border-secondary' }
  if (v >= 0.45) return { tag: 'Mejorable', border: 'border-tertiary' }
  return { tag: 'Crítico', border: 'border-error' }
}

function cellClass(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return 'bg-surface-container-high text-on-surface text-xs font-bold'
  if (v >= 0.75) return 'bg-secondary-container text-on-secondary-container text-xs font-bold'
  if (v >= 0.45) return 'bg-tertiary-container text-on-tertiary-container text-xs font-bold'
  return 'bg-error-container text-on-error-container text-xs font-bold'
}

function shortMetricKey(k: string): string {
  const m: Record<string, string> = {
    faithfulness: 'Fid',
    answer_relevancy: 'Rel',
    context_precision: 'Prc',
    context_recall: 'Rec',
  }
  return m[k] ?? k.slice(0, 4)
}

function buildInsight(r: RagasEvaluateResponse): string {
  const f = r.averages.faithfulness
  const ar = r.averages.answer_relevancy
  const cp = r.averages.context_precision
  const cr = r.averages.context_recall
  const parts: string[] = []
  if (Number.isFinite(f)) {
    parts.push(
      f >= 0.8
        ? `La fidelidad (${f.toFixed(2)}) es alta: el modelo se apega al contexto recuperado.`
        : `La fidelidad (${f.toFixed(2)}) es mejorable: revisa alucinaciones y el prompt del sistema.`,
    )
  }
  if (Number.isFinite(cr) && cr < 0.5) {
    parts.push(
      `La recuperación (${cr.toFixed(2)}) es baja: sube más documentos al índice o ajusta fragmentación y top_k.`,
    )
  }
  if (Number.isFinite(cp) && cp < 0.5) {
    parts.push(
      `La precisión del contexto (${cp.toFixed(2)}) sugiere ruido en los fragmentos devueltos (MMR/top_k).`,
    )
  }
  if (Number.isFinite(ar) && ar < 0.5) {
    parts.push(`La relevancia de la respuesta (${ar.toFixed(2)}) está por debajo del objetivo típico.`)
  }
  if (!parts.length) return 'Ejecuta una evaluación para obtener recomendaciones automáticas.'
  return parts.join(' ')
}

export function EvaluationView({
  stats,
  statsLoading = false,
  onGoDocuments,
}: {
  stats: StatsResponse | null
  statsLoading?: boolean
  onGoDocuments?: () => void
}) {
  const [preset, setPreset] = useState(PRESET_FILES[0])
  const [manualPath, setManualPath] = useState('')
  const [evalLoading, setEvalLoading] = useState(false)
  const [evalResult, setEvalResult] = useState<RagasEvaluateResponse | null>(null)
  const [evalError, setEvalError] = useState<string | null>(null)

  const effectivePath = manualPath.trim() || preset

  const onRun = useCallback(async () => {
    setEvalError(null)
    setEvalResult(null)
    setEvalLoading(true)
    try {
      const rel = effectivePath.trim()
      const r = await runRagasEvaluation(rel || null)
      setEvalResult(r)
    } catch (err) {
      setEvalError(err instanceof Error ? err.message : 'Error en evaluación RAGAS')
    } finally {
      setEvalLoading(false)
    }
  }, [effectivePath])

  const onDownload = useCallback(() => {
    if (!evalResult) return
    const blob = new Blob([JSON.stringify(evalResult, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'ragas_eval_result.json'
    a.click()
    URL.revokeObjectURL(url)
  }, [evalResult])

  const keys = evalResult?.ragas_metric_keys ?? []

  return (
    <main className="flex-1 ml-0 p-6 md:p-8 bg-background min-h-screen">
      <div className="mb-10">
        <h1 className="font-headline text-3xl md:text-4xl font-extrabold tracking-tight text-on-surface mb-2">
          Evaluación RAGAS
        </h1>
        <p className="text-on-surface-variant max-w-2xl text-sm md:text-base">
          Valida el pipeline RAG con métricas estándar: fidelidad, relevancia, precisión y recuperación del contexto.
        </p>
        <div className="mt-3">
          <IndexFragmentBadge stats={stats} statsLoading={statsLoading} className="text-on-surface-variant" />
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6 md:gap-8">
        <div className="col-span-12 lg:col-span-4 space-y-6">
          <section className="bg-surface-container-low p-6 rounded-xl border border-outline/40">
            <h3 className="font-headline text-lg font-bold mb-4 flex items-center gap-2 text-on-surface">
              <Icon name="settings_input_component" className="text-primary" />
              Configuración
            </h3>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-on-surface-variant uppercase tracking-wider mb-1.5">
                  Archivo de evaluación
                </label>
                <select
                  className="w-full min-w-0 bg-surface-container border border-outline/50 text-on-surface rounded-lg text-sm focus:ring-2 focus:ring-primary/40 py-2.5 px-3"
                  value={preset}
                  onChange={(e) => setPreset(e.target.value)}
                  disabled={evalLoading}
                  title={preset}
                >
                  {PRESET_FILES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <p className="text-[10px] text-on-surface-variant mt-1 font-mono break-all">
                  Ruta usada: {effectivePath}
                </p>
              </div>
              <div>
                <label className="block text-xs font-bold text-on-surface-variant uppercase tracking-wider mb-1.5">
                  Ruta manual (relativa a pruebaScanntech/)
                </label>
                <input
                  className="w-full bg-surface-container border border-outline/50 text-on-surface rounded-lg text-sm focus:ring-2 focus:ring-primary/40 py-2.5 px-3"
                  placeholder="evals/sample_eval.jsonl"
                  type="text"
                  value={manualPath}
                  onChange={(e) => setManualPath(e.target.value)}
                  disabled={evalLoading}
                />
                <p className="text-[10px] text-on-surface-variant mt-1">
                  Si rellenas la ruta manual, tiene prioridad sobre el selector.
                </p>
              </div>
              <div className="pt-2">
                <button
                  type="button"
                  disabled={evalLoading}
                  onClick={() => void onRun()}
                  className="w-full bg-primary text-on-primary py-3 rounded-xl font-bold flex items-center justify-center gap-3 transition-all hover:bg-primary-dim active:scale-[0.98] disabled:opacity-60"
                >
                  <Icon name="sync" className={`text-xl ${evalLoading ? 'animate-spin' : ''}`} />
                  Ejecutar evaluación
                </button>
                <p className="text-center text-xs text-on-surface-variant mt-3 flex items-center justify-center gap-1">
                  <Icon name="schedule" className="text-sm" />
                  Tiempo estimado 3–10 min
                </p>
              </div>
            </div>
          </section>

          <section className="bg-surface-container-low p-6 rounded-xl border border-outline/40">
            <h3 className="font-headline text-lg font-bold mb-4 text-on-surface">Exportar resultados</h3>
            <p className="text-sm text-on-surface-variant mb-4">
              Descarga el JSON completo de la última evaluación para análisis externo o CI/CD.
            </p>
            <button
              type="button"
              disabled={!evalResult}
              onClick={onDownload}
              className="w-full py-2.5 px-4 bg-surface-container-high text-primary rounded-xl font-bold flex items-center justify-center gap-2 hover:bg-surface-variant transition-colors disabled:opacity-40"
            >
              <Icon name="download" />
              Descargar JSON
            </button>
          </section>
        </div>

        <div className="col-span-12 lg:col-span-8 space-y-8">
          {evalError && (
            <div className="rounded-xl border border-error/30 bg-error-container/15 px-4 py-3 text-sm text-on-error-container">
              {evalError}
            </div>
          )}

          {evalResult && keys.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4">
              {keys.map((k) => {
                const v = evalResult.averages[k]
                const num = typeof v === 'number' && Number.isFinite(v) ? v : NaN
                const { tag, border } = scoreBand(num)
                return (
                  <div
                    key={k}
                    className={`bg-surface-container-low p-4 md:p-5 rounded-xl border border-outline/40 border-l-4 ${border}`}
                  >
                    <span className="text-[10px] md:text-xs font-bold text-on-surface-variant uppercase line-clamp-2">
                      {evalResult.metric_labels_es[k] ?? k}
                    </span>
                    <div className="flex items-end gap-2 mt-2 flex-wrap">
                      <span className="text-2xl md:text-3xl font-extrabold text-on-surface leading-none">
                        {Number.isFinite(num) ? num.toFixed(2) : '—'}
                      </span>
                      <span className="text-[10px] md:text-xs font-bold pb-0.5 text-secondary">{tag}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {evalResult && (
            <>
              <div className="bg-surface-container-low rounded-xl border border-outline/40 overflow-hidden">
                <div className="px-6 py-4 border-b border-outline-variant/10 flex justify-between items-center bg-surface-container-low/50 flex-wrap gap-2">
                  <h3 className="font-headline font-bold">Detalle por pregunta</h3>
                  <span className="text-xs font-bold bg-primary-container text-on-primary-container px-2.5 py-1 rounded-full uppercase">
                    {evalResult.per_question.length} muestras
                  </span>
                </div>
                <div className="overflow-x-auto no-scrollbar">
                  <table className="w-full text-left min-w-[640px]">
                    <thead>
                      <tr className="bg-surface-container-low">
                        <th className="px-4 md:px-6 py-3 md:py-4 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
                          Pregunta
                        </th>
                        <th className="px-4 md:px-6 py-3 md:py-4 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
                          Extracto de respuesta
                        </th>
                        {keys.map((k) => (
                          <th
                            key={k}
                            className="px-2 md:px-4 py-3 md:py-4 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant text-center whitespace-nowrap"
                          >
                            {shortMetricKey(k)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-outline-variant/10">
                      {evalResult.per_question.map((row, i) => (
                        <tr key={i} className="hover:bg-surface transition-colors">
                          <td className="px-4 md:px-6 py-3 md:py-4 text-sm font-medium text-on-surface align-top max-w-[200px]">
                            {row.question}
                          </td>
                          <td className="px-4 md:px-6 py-3 md:py-4 text-sm text-on-surface-variant italic align-top max-w-[240px]">
                            &ldquo;{(row.answer_preview ?? '').slice(0, 120)}
                            {(row.answer_preview?.length ?? 0) > 120 ? '…' : ''}&rdquo;
                          </td>
                          {keys.map((k) => {
                            const v = row.scores[k]
                            return (
                              <td key={k} className="px-2 py-3 md:py-4 text-center align-top">
                                <span className={`inline-block px-2 py-1 rounded-md ${cellClass(v)}`}>
                                  {v != null && Number.isFinite(v) ? v.toFixed(2) : '—'}
                                </span>
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="bg-surface-container-high border border-outline/50 text-on-surface p-6 md:p-8 rounded-2xl relative overflow-hidden">
                <div className="absolute top-0 right-0 w-72 h-72 bg-primary/10 blur-[120px] rounded-full -translate-y-1/2 translate-x-1/2 pointer-events-none" />
                <div className="absolute bottom-0 left-0 w-48 h-48 bg-secondary/8 blur-[80px] rounded-full translate-y-1/2 -translate-x-1/2 pointer-events-none" />
                <div className="relative z-10">
                  <h4 className="font-headline text-xl font-bold mb-4 text-on-surface">Resumen</h4>
                  <p className="text-on-surface-variant leading-relaxed mb-6 text-sm whitespace-pre-wrap">
                    {buildInsight(evalResult)}
                  </p>
                  {onGoDocuments && (
                    <button
                      type="button"
                      onClick={() => onGoDocuments()}
                      className="bg-surface-container text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface border border-outline/50 px-4 py-2 rounded-lg text-sm font-semibold transition-all"
                    >
                      Ir a documentos
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  )
}
