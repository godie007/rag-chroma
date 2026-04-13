import { useCallback, useEffect, useRef, useState } from 'react'
import { chat, getApiBase, type ChatResponse, type ConfigPublic } from '../api'
import { MarkdownContent } from '../components/MarkdownContent'
import { Icon } from '../components/Icon'

type ChatTurn = {
  role: 'user' | 'assistant'
  text: string
  sources?: ChatResponse['sources']
  timeLabel?: string
}

function timeLabel(): string {
  return new Intl.DateTimeFormat('es', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

export function ChatView({ config }: { config: ConfigPublic | null }) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<{ turnIndex: number; sourceIndex: number } | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, loading])

  const onSend = useCallback(async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setError(null)
    const t = timeLabel()
    setTurns((prev) => [...prev, { role: 'user', text: q, timeLabel: t }])
    setLoading(true)
    setSelection(null)
    try {
      const r = await chat(q)
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', text: r.answer, sources: r.sources, timeLabel: timeLabel() },
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error en el chat')
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', text: 'No se pudo obtener respuesta.', timeLabel: timeLabel() },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading])

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <main className="flex-1 overflow-y-auto bg-surface-bright flex flex-col items-center min-h-0">
        <div className="w-full max-w-[44rem] px-6 py-10 md:py-12 space-y-10">
          {turns.length === 0 && (
            <p className="text-center text-sm text-on-surface-variant">
              Haz una pregunta sobre los documentos indexados.
            </p>
          )}
          {turns.map((m, i) =>
            m.role === 'user' ? (
              <div key={i} className="flex flex-col items-end gap-2">
                <div className="bg-primary text-on-primary px-6 py-4 rounded-2xl rounded-tr-none shadow-sm max-w-[85%]">
                  <p className="text-sm font-medium leading-relaxed whitespace-pre-wrap">{m.text}</p>
                </div>
                <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest px-2">
                  Tú • {m.timeLabel ?? ''}
                </span>
              </div>
            ) : (
              <div key={i} className="flex flex-col items-start gap-4">
                <div className="flex gap-4 w-full">
                  <div className="w-8 h-8 rounded-lg bg-surface-container-highest shrink-0 flex items-center justify-center">
                    <Icon name="smart_toy" className="text-primary text-sm" />
                  </div>
                  <div className="flex-1 space-y-6 min-w-0">
                    <div className="text-on-surface leading-relaxed prose prose-sm max-w-none prose-p:text-sm prose-p:leading-relaxed prose-headings:font-headline">
                      <MarkdownContent content={m.text} />
                    </div>
                    {m.sources && m.sources.length > 0 && (
                      <div className="space-y-3">
                        <div className="flex items-center gap-2 text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">
                          <Icon name="library_books" className="text-sm" />
                          Fuentes
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {m.sources.map((s, j) => {
                            const name = String(s.metadata.source ?? 'doc')
                            const active = selection?.turnIndex === i && selection?.sourceIndex === j
                            return (
                              <button
                                key={j}
                                type="button"
                                onClick={() =>
                                  setSelection(active ? null : { turnIndex: i, sourceIndex: j })
                                }
                                className={`px-3 py-1.5 text-[11px] font-bold text-primary rounded-full transition-colors flex items-center gap-2 group ${
                                  active
                                    ? 'bg-surface-container-highest ring-2 ring-primary/20'
                                    : 'bg-surface-container-high hover:bg-surface-container-highest'
                                }`}
                              >
                                <span className="w-4 h-4 rounded-full bg-secondary-container text-on-secondary-container flex items-center justify-center text-[9px]">
                                  {j + 1}
                                </span>
                                {name}
                              </button>
                            )
                          })}
                        </div>
                        {selection?.turnIndex === i &&
                          m.sources[selection.sourceIndex] != null && (
                            <div className="mt-4 p-4 bg-surface-container-lowest rounded-xl border border-outline-variant/10 shadow-sm">
                              <div className="flex justify-between items-center mb-3 gap-2">
                                <div className="flex flex-wrap items-center gap-2 min-w-0">
                                  <span className="text-[10px] font-bold text-secondary uppercase tracking-tighter shrink-0">
                                    Extracto
                                  </span>
                                  <span className="text-[10px] text-on-surface-variant truncate">
                                    • {String(m.sources[selection.sourceIndex].metadata.source ?? 'doc')}
                                  </span>
                                </div>
                                <button
                                  type="button"
                                  className="p-1.5 hover:bg-surface-container-low rounded-md transition-colors text-on-surface-variant shrink-0"
                                  title="Copiar"
                                  onClick={() =>
                                    void navigator.clipboard.writeText(
                                      m.sources![selection.sourceIndex].content,
                                    )
                                  }
                                >
                                  <Icon name="content_copy" className="text-sm" />
                                </button>
                              </div>
                              <div className="max-h-64 overflow-y-auto pr-2">
                                <pre className="text-xs text-on-surface leading-relaxed whitespace-pre-wrap break-words font-sans font-normal m-0 max-w-full border-0 bg-transparent">
                                  {m.sources[selection.sourceIndex].content.slice(0, 2000)}
                                  {m.sources[selection.sourceIndex].content.length > 2000 ? '…' : ''}
                                </pre>
                              </div>
                            </div>
                          )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ),
          )}
          {loading && (
            <div className="flex items-center gap-3 text-[10px] font-bold text-secondary uppercase tracking-widest justify-center py-2">
              <span className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-secondary rounded-full animate-bounce" />
                <span className="w-1.5 h-1.5 bg-secondary rounded-full animate-bounce [animation-delay:200ms]" />
                <span className="w-1.5 h-1.5 bg-secondary rounded-full animate-bounce [animation-delay:400ms]" />
              </span>
              Procesando consulta…
            </div>
          )}
          {error && (
            <p className="text-center text-sm text-error">{error}</p>
          )}
          <div ref={bottomRef} className="h-8" />
        </div>
      </main>
      <footer className="w-full flex justify-center pb-8 pt-4 bg-gradient-to-t from-surface-bright via-surface-bright/90 to-transparent shrink-0">
        <div className="w-full max-w-[44rem] px-6">
          <div className="relative bg-surface-container-lowest rounded-2xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-outline-variant/10 group focus-within:ring-2 ring-primary/10 transition-all">
            <textarea
              className="w-full bg-transparent border-none focus:ring-0 p-5 pr-14 text-sm resize-none min-h-[80px] font-medium placeholder:text-on-surface-variant/40 rounded-2xl"
              placeholder="Pregunta algo sobre el índice de conocimiento..."
              rows={2}
              value={input}
              disabled={loading}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void onSend()
                }
              }}
            />
            <div className="absolute bottom-4 right-4 flex items-center gap-4">
              <span className="text-[10px] font-bold text-on-surface-variant/40 hidden md:block uppercase tracking-widest">
                Shift + Enter salto de línea
              </span>
              <button
                type="button"
                disabled={loading}
                onClick={() => void onSend()}
                className="w-10 h-10 bg-primary text-on-primary rounded-xl flex items-center justify-center shadow-lg active:scale-95 transition-transform group-hover:bg-primary-dim disabled:opacity-50"
                aria-label="Enviar"
              >
                {loading ? (
                  <span className="flex gap-1 px-1">
                    <span className="w-1 h-1 bg-white rounded-full animate-bounce" />
                    <span className="w-1 h-1 bg-white rounded-full animate-bounce [animation-delay:-.15s]" />
                    <span className="w-1 h-1 bg-white rounded-full animate-bounce [animation-delay:-.3s]" />
                  </span>
                ) : (
                  <Icon name="send" className="text-lg" />
                )}
              </button>
            </div>
          </div>
          <p className="text-[10px] text-center mt-4 text-on-surface-variant/50 font-medium">
            Comprueba las respuestas con el texto de las fuentes cuando proceda.
          </p>
          {config?.whatsapp_webhook_active ? (
            <div className="text-[10px] text-center mt-2 text-on-surface-variant/60 font-medium max-w-xl mx-auto leading-relaxed space-y-1">
              {config.whatsapp_polling_active ? (
                <p>
                  WhatsApp: polling ({config.whatsapp_poll_mode}) a{' '}
                  <span className="text-on-surface-variant">{config.whatsapp_api_base_url}</span>
                  {config.whatsapp_poll_mode === 'chats'
                    ? ' → /chats + /messages?chat_jid=…'
                    : ' → /messages/recent'}
                  {' '}
                  cada {config.whatsapp_poll_interval_sec}s → RAG →{' '}
                  <code className="text-[9px] bg-surface-container-high px-1 rounded">POST /send/text</code>{' '}
                  (API :8090; GOWA :3000).
                </p>
              ) : (
                <p>WhatsApp: sin polling; recepción vía POST al webhook de abajo (API Flask puede reenviar desde GOWA).</p>
              )}
              <p>
                Webhook RAG:{' '}
                <code className="text-[9px] bg-surface-container-high px-1 rounded break-all">
                  {getApiBase()}/webhooks/whatsapp
                </code>
              </p>
            </div>
          ) : null}
        </div>
      </footer>
    </div>
  )
}
