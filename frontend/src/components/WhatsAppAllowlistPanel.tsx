import { useCallback, useEffect, useState } from 'react'
import {
  addWhatsAppAllowlistNumber,
  fetchWhatsAppAllowlist,
  removeWhatsAppAllowlistNumber,
  revertWhatsAppAllowlistToEnv,
} from '../api'
import { Icon } from './Icon'

/**
 * Tarjeta de gestión de allowlist (diseño alineado con las secciones de EvaluationView).
 */
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
    if (
      busy ||
      !confirm(
        '¿Restaurar la configuración desde el archivo .env del servidor? Se eliminará la lista guardada por esta interfaz.',
      )
    )
      return
    setBusy(true)
    setError(null)
    try {
      const r = await revertWhatsAppAllowlistToEnv()
      setNumbers(r.numbers)
      setSource(r.source)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo revertir')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="bg-surface-container-lowest p-6 md:p-8 rounded-xl shadow-sm border border-outline-variant/5">
      <h3 className="font-headline text-lg font-bold mb-1 flex items-center gap-2 text-on-surface">
        <Icon name="verified_user" className="text-primary text-xl" />
        Números permitidos
      </h3>
      <p className="text-sm text-on-surface-variant mb-6 leading-relaxed">
        Define qué contactos (chats 1:1) pueden recibir respuestas automáticas del RAG. Usa el número en formato internacional
        sin símbolo <span className="font-mono text-xs">+</span>, solo dígitos.
      </p>

      <div className="flex flex-wrap items-center gap-3 mb-5">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Origen de la lista</span>
        <span
          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-bold uppercase tracking-wide ${
            source === 'file'
              ? 'bg-primary-container text-on-primary-container'
              : 'bg-surface-container-high text-on-surface-variant'
          }`}
        >
          <Icon name={source === 'file' ? 'save' : 'tune'} className="text-sm" />
          {source === 'file' ? 'Persistido (interfaz)' : 'Variable de entorno (.env)'}
        </span>
        {loading ? (
          <span className="text-xs text-on-surface-variant flex items-center gap-1">
            <Icon name="progress_activity" className="text-base animate-spin" />
            Cargando…
          </span>
        ) : null}
      </div>

      <div className="rounded-lg bg-surface-container-low/60 px-4 py-3 mb-5 text-xs text-on-surface-variant leading-relaxed space-y-2">
        <p>
          <strong className="text-on-surface">Lista vacía:</strong> no hay restricción; el bot puede responder a cualquier chat
          individual.
        </p>
        <p>
          Al guardar desde aquí se crea{' '}
          <code className="px-1.5 py-0.5 rounded bg-surface-container-highest font-mono text-[10px]">whatsapp_allowlist.json</code>{' '}
          en el servidor y tiene prioridad sobre{' '}
          <code className="px-1.5 py-0.5 rounded bg-surface-container-highest font-mono text-[10px]">
            WHATSAPP_ALLOWED_SENDER_NUMBERS
          </code>
          .
        </p>
      </div>

      {error ? (
        <div className="mb-4 rounded-lg border border-error/25 bg-error-container/10 px-4 py-3 text-sm text-error">{error}</div>
      ) : null}

      <div className="mb-5">
        <span className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-wider mb-2">
          Contactos autorizados ({numbers.length})
        </span>
        <div className="flex flex-wrap gap-2 min-h-[2.5rem] items-start p-4 rounded-xl bg-surface-container-low border border-outline-variant/10">
          {numbers.length === 0 ? (
            <p className="text-sm text-on-surface-variant italic m-0">Sin restricciones activas para chats 1:1.</p>
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
                  title="Eliminar de la lista"
                  aria-label={`Eliminar ${n}`}
                >
                  <Icon name="close" className="text-base" />
                </button>
              </span>
            ))
          )}
        </div>
      </div>

      <div className="space-y-3">
        <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
          Añadir número
        </label>
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            inputMode="tel"
            autoComplete="tel"
            placeholder="Ej. 573135656345 o +57 313 565 6345"
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
      </div>

      {source === 'file' ? (
        <div className="mt-6 pt-6 border-t border-outline-variant/10">
          <button
            type="button"
            disabled={busy}
            onClick={() => void onRevert()}
            className="text-sm font-bold text-secondary hover:text-secondary-dim underline-offset-4 hover:underline disabled:opacity-40 inline-flex items-center gap-2"
          >
            <Icon name="restart_alt" className="text-lg" />
            Volver a usar solo la lista del .env
          </button>
        </div>
      ) : null}
    </section>
  )
}
