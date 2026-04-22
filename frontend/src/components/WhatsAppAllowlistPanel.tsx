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
    if (busy || !confirm('¿Volver a usar solo la lista del archivo .env del servidor? Se borrará la lista guardada por la UI.')) return
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
    <div className="mt-4 rounded-xl border border-outline-variant/15 bg-surface-container-lowest/80 p-4 text-left max-w-xl mx-auto space-y-3">
      <div className="flex items-center gap-2 text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">
        <Icon name="call" className="text-sm text-primary" />
        WhatsApp · números permitidos
      </div>
      <p className="text-[11px] text-on-surface-variant leading-relaxed">
        Solo dígitos (p. ej. <code className="text-[10px] bg-surface-container-high px-1 rounded">573135656345</code>).
        Lista vacía = el bot puede responder a cualquier chat 1:1. La UI guarda en el servidor (
        <code className="text-[10px] bg-surface-container-high px-1 rounded">whatsapp_allowlist.json</code>
        ) y sustituye a <code className="text-[10px] bg-surface-container-high px-1 rounded">WHATSAPP_ALLOWED_SENDER_NUMBERS</code>{' '}
        mientras exista ese archivo.
      </p>
      <div className="flex items-center gap-2 text-[10px] text-on-surface-variant/80">
        <span
          className={`px-2 py-0.5 rounded-full font-bold uppercase ${
            source === 'file' ? 'bg-secondary-container text-on-secondary-container' : 'bg-surface-container-high'
          }`}
        >
          {source === 'file' ? 'Lista en archivo (UI)' : 'Solo .env'}
        </span>
        {loading ? <span>Cargando…</span> : null}
      </div>
      {error ? <p className="text-[11px] text-error">{error}</p> : null}
      <div className="flex flex-wrap gap-2 min-h-[2rem]">
        {numbers.length === 0 ? (
          <span className="text-[11px] text-on-surface-variant italic">Nadie restringido — todos los 1:1 permitidos</span>
        ) : (
          numbers.map((n) => (
            <span
              key={n}
              className="inline-flex items-center gap-1 pl-2.5 pr-1 py-1 rounded-full bg-surface-container-high text-[11px] font-mono text-on-surface"
            >
              +{n}
              <button
                type="button"
                disabled={busy}
                onClick={() => void onRemove(n)}
                className="p-0.5 rounded-full hover:bg-error/15 text-on-surface-variant hover:text-error disabled:opacity-40"
                title="Quitar"
                aria-label={`Quitar ${n}`}
              >
                <Icon name="close" className="text-sm" />
              </button>
            </span>
          ))
        )}
      </div>
      <div className="flex flex-col sm:flex-row gap-2">
        <input
          type="text"
          inputMode="numeric"
          autoComplete="tel"
          placeholder="+57 313… o solo dígitos"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void onAdd()
          }}
          className="flex-1 min-w-0 rounded-lg border border-outline-variant/20 bg-surface-bright px-3 py-2 text-sm font-mono placeholder:text-on-surface-variant/40"
        />
        <button
          type="button"
          disabled={busy || !input.trim()}
          onClick={() => void onAdd()}
          className="shrink-0 px-4 py-2 rounded-lg bg-primary text-on-primary text-xs font-bold uppercase tracking-wide disabled:opacity-40"
        >
          Añadir
        </button>
      </div>
      {source === 'file' ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void onRevert()}
          className="text-[10px] font-bold text-secondary uppercase tracking-widest hover:underline disabled:opacity-40"
        >
          Volver a usar solo .env
        </button>
      ) : null}
    </div>
  )
}
