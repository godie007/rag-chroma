import { useCallback, useEffect, useState } from 'react'
import {
  fetchSystemPrompts,
  resetSystemPromptsToCodeDefaults,
  type SystemPromptsConfig,
  saveSystemPrompts,
} from '../api'
import { Icon } from './Icon'

function Field({
  id,
  label,
  description,
  value,
  onChange,
}: {
  id: string
  label: string
  description: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label htmlFor={id} className="block font-bold text-on-surface text-sm mb-1">
        {label}
      </label>
      <p className="text-xs text-on-surface-variant mb-2 m-0 leading-relaxed">{description}</p>
      <textarea
        id={id}
        className="w-full min-h-[160px] md:min-h-[140px] text-xs md:text-sm font-mono p-3 rounded-lg border border-outline-variant/20 bg-surface text-on-surface focus:ring-2 focus:ring-primary/30 focus:border-primary/40 outline-none resize-y"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
      />
    </div>
  )
}

export function SystemPromptsPanel() {
  const [data, setData] = useState<SystemPromptsConfig | null>(null)
  const [draft, setDraft] = useState<SystemPromptsConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setMessage(null)
    try {
      const p = await fetchSystemPrompts()
      setData(p)
      setDraft(p)
    } catch (e) {
      setMessage({ type: 'err', text: e instanceof Error ? e.message : 'No se pudo cargar' })
      setData(null)
      setDraft(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const dirty =
    draft != null &&
    data != null &&
    (draft.system_rag_web !== data.system_rag_web ||
      draft.system_rag_whatsapp !== data.system_rag_whatsapp ||
      draft.system_no_retrieval_web !== data.system_no_retrieval_web ||
      draft.system_no_retrieval_whatsapp !== data.system_no_retrieval_whatsapp)

  const onSave = async () => {
    if (!draft) return
    setSaving(true)
    setMessage(null)
    try {
      const saved = await saveSystemPrompts(draft)
      setData(saved)
      setDraft(saved)
      setMessage({ type: 'ok', text: 'Guardado. Los próximos mensajes (web y WhatsApp) usan ya estos textos.' })
    } catch (e) {
      setMessage({ type: 'err', text: e instanceof Error ? e.message : 'Error al guardar' })
    } finally {
      setSaving(false)
    }
  }

  const onResetFile = async () => {
    if (!confirm('¿Volver a los system prompts del código (borra personalizaciones en disco)?')) return
    setSaving(true)
    setMessage(null)
    try {
      const saved = await resetSystemPromptsToCodeDefaults()
      setData(saved)
      setDraft(saved)
      setMessage({ type: 'ok', text: 'Restaurado a los valores por defecto del repositorio.' })
    } catch (e) {
      setMessage({ type: 'err', text: e instanceof Error ? e.message : 'Error al restaurar' })
    } finally {
      setSaving(false)
    }
  }

  if (loading && !draft) {
    return (
      <section className="bg-surface-container-lowest p-6 md:p-8 rounded-xl shadow-sm border border-outline-variant/5">
        <p className="text-on-surface-variant text-sm m-0">Cargando instrucciones…</p>
      </section>
    )
  }

  if (!draft) {
    return (
      <section className="bg-surface-container-lowest p-6 md:p-8 rounded-xl shadow-sm border border-outline-variant/5">
        {message?.type === 'err' ? (
          <p className="text-tertiary text-sm m-0">{message.text}</p>
        ) : null}
        <button
          type="button"
          onClick={() => void load()}
          className="mt-2 text-sm font-bold text-primary underline"
        >
          Reintentar
        </button>
      </section>
    )
  }

  const set = (k: keyof SystemPromptsConfig) => (v: string) =>
    setDraft((prev) => (prev ? { ...prev, [k]: v } : null))

  return (
    <section className="bg-surface-container-lowest p-6 md:p-8 rounded-xl shadow-sm border border-outline-variant/5 h-full flex flex-col">
      <h3 className="font-headline text-lg font-bold mb-1 flex items-center gap-2 text-on-surface">
        <Icon name="tune" className="text-primary text-xl" />
        Instrucciones del modelo (system prompt)
      </h3>
      <p className="text-on-surface-variant text-sm leading-relaxed mb-4 m-0">
        Texto separado para el <strong className="text-on-surface font-bold">chat web</strong> y para{' '}
        <strong className="text-on-surface font-bold">WhatsApp</strong>. Incluye variantes cuando hay contexto
        recuperado de la documentación y cuando no. Al guardar, se aplica al instante sin reiniciar el backend.
      </p>

      {message ? (
        <div
          className={`mb-4 text-sm p-3 rounded-lg ${
            message.type === 'ok' ? 'bg-secondary-container/30 text-on-surface' : 'bg-tertiary-container/30 text-on-surface'
          }`}
        >
          {message.text}
        </div>
      ) : null}

      <div className="space-y-6 flex-1 min-h-0">
        <div className="grid grid-cols-1 gap-6">
          <Field
            id="sp-rag-web"
            label="Chat web — con documentación (RAG)"
            description="Puedes orientar el tono a Markdown, bloques de código, etc."
            value={draft.system_rag_web}
            onChange={set('system_rag_web')}
          />
          <Field
            id="sp-rag-wa"
            label="WhatsApp — con documentación (RAG)"
            description="Suele pedirse formato *negrita* estilo WA y evitar tablas Markdown."
            value={draft.system_rag_whatsapp}
            onChange={set('system_rag_whatsapp')}
          />
        </div>
        <div className="h-px bg-outline-variant/15" />
        <div className="grid grid-cols-1 gap-6">
          <Field
            id="sp-nr-web"
            label="Chat web — sin documentación relevante"
            description="Saludos, temas fuera del índice o sin coincidencias en Chroma."
            value={draft.system_no_retrieval_web}
            onChange={set('system_no_retrieval_web')}
          />
          <Field
            id="sp-nr-wa"
            label="WhatsApp — sin documentación relevante"
            description="Misma situación, canal móvil."
            value={draft.system_no_retrieval_whatsapp}
            onChange={set('system_no_retrieval_whatsapp')}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-3 mt-6 pt-4 border-t border-outline-variant/10">
        <button
          type="button"
          disabled={saving || !dirty}
          onClick={() => void onSave()}
          className="px-4 py-2.5 rounded-xl bg-primary text-on-primary font-bold text-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? 'Guardando…' : 'Guardar cambios'}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => void onResetFile()}
          className="px-4 py-2.5 rounded-xl border border-outline-variant/40 text-on-surface font-bold text-sm hover:bg-surface-container-high"
        >
          Valores del código
        </button>
        {dirty ? (
          <span className="text-xs text-tertiary self-center">Cambios sin guardar</span>
        ) : null}
      </div>
    </section>
  )
}
