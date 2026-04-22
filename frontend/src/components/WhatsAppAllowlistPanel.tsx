import { useCallback, useEffect, useState } from 'react'
import {
  addWhatsAppAllowlistNumber,
  fetchWhatsAppAllowlist,
  removeWhatsAppAllowlistNumber,
  revertWhatsAppAllowlistToEnv,
} from '../api'
import { Icon } from './Icon'

export function WhatsAppAllowlistPanel() {
  const [numbers, setNumbers] = useState<string[]>([])
  const [source, setSource] = useState<'file' | 'env'>('env')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setError(null)
    const r = await fetchWhatsAppAllowlist()
    setNumbers(r.numbers)
    setSource(r.source)
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    void reload()
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Error al cargar la lista')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])

  const onAdd = async () => {
    const raw = input.trim()
    if (!raw || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await addWhatsAppAllowlistNumber(raw)
      setNumbers(r.numbers)
      setSource(r.source)
      setInput('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo agregar')
    } finally {
      setBusy(false)
    }
  }

  const onRemove = async (n: string) => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await removeWhatsAppAllowlistNumber(n)
      setNumbers(r.numbers)
      setSource(r.source)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo quitar')
    } finally {
      setBusy(false)
    }
  }

  const onRevert = async () => {
    if (busy || !confirm('¿Descartar la lista guardada aquí y volver a la configuración del servidor?')) return
    setBusy(true)
    setError(null)
    try {
      const r = await revertWhatsAppAllowlistToEnv()
      setNumbers(r.numbers)
      setSource(r.source)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo restablecer')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="bg-surface-container-lowest p-6 md:p-8 rounded-xl shadow-sm border border-outline-variant/5">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <h3 className="font-headline text-lg font-bold m-0 flex items-center gap-2 text-on-surface">
          <Icon name="verified_user" className="text-primary text-xl" />
          Números permitidos
        </h3>
        {loading ? (
          <span className="text-xs text-on-surface-variant flex items-center gap-1 shrink-0">
            <Icon name="progress_activity" className="text-base animate-spin" />
            Cargando…
          </span>
        ) : null}
      </div>

      <p className="text-sm text-on-surface-variant mb-5 leading-snug m-0">
        Solo dígitos (código de país, sin +). Si la lista está vacía, se permite cualquier chat individual.
      </p>

      {error ? (
        <div className="mb-4 rounded-lg border border-error/25 bg-error-container/10 px-4 py-3 text-sm text-error">{error}</div>
      ) : null}

      <div className="mb-5">
        <div className="flex flex-wrap gap-2 min-h-[2.5rem] items-start p-4 rounded-xl bg-surface-container-low border border-outline-variant/10">
          {numbers.length === 0 ? (
            <p className="text-sm text-on-surface-variant italic m-0">Ningún número — sin restricción.</p>
          ) : (
            numbers.map((n) => (
              <span
                key={n}
                className="inline-flex items-center gap-1.5 pl-3 pr-1 py-1.5 rounded-full bg-surface-container-highest border border-outline-variant/10 text-sm font-mono font-medium text-on-surface shadow-sm"
              >
                +{n}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onRemove(n)}
                  className="p-1 rounded-full hover:bg-error/12 text-on-surface-variant hover:text-error disabled:opacity-40 transition-colors"
                  title="Quitar"
                  aria-label={`Quitar ${n}`}
                >
                  <Icon name="close" className="text-base" />
                </button>
              </span>
            ))
          )}
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          inputMode="tel"
          autoComplete="tel"
          placeholder="Ej. 573135656345"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void onAdd()
          }}
          className="flex-1 min-w-0 rounded-xl border-none bg-surface-container-low text-sm font-mono py-3 px-4 focus:ring-2 focus:ring-primary placeholder:text-on-surface-variant/45"
        />
        <button
          type="button"
          disabled={busy || !input.trim()}
          onClick={() => void onAdd()}
          className="shrink-0 px-6 py-3 rounded-xl bg-primary text-on-primary text-sm font-bold uppercase tracking-wide hover:bg-primary-dim transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
        >
          <Icon name="person_add" className="text-lg" />
          Añadir
        </button>
      </div>

      {source === 'file' ? (
        <div className="mt-5 pt-5 border-t border-outline-variant/10">
          <button
            type="button"
            disabled={busy}
            onClick={() => void onRevert()}
            className="text-sm font-semibold text-on-surface-variant hover:text-secondary disabled:opacity-40"
          >
            Restablecer lista del servidor
          </button>
        </div>
      ) : null}
    </section>
  )
}
