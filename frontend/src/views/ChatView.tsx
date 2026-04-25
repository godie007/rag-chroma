import { useCallback, useEffect, useRef, useState } from 'react'
import {
  chat,
  setChatThreadId,
  type ChatResponse,
  type StatsResponse,
} from '../api'
import { MarkdownContent } from '../components/MarkdownContent'
import { Icon } from '../components/Icon'

type ChatTurn = {
  role: 'user' | 'assistant'
  text: string
  sources?: ChatResponse['sources']
  responseType?: ChatResponse['response_type']
  timeLabel?: string
}

const CHAT_TURNS_KEY = 'rag_chat_turns_v1'

function timeLabel(): string {
  return new Intl.DateTimeFormat('es', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

export function ChatView({
  stats: _stats,
  statsLoading: _statsLoading,
}: {
  stats: StatsResponse | null
  statsLoading?: boolean
}) {
  void _stats
  void _statsLoading
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<{ turnIndex: number; sourceIndex: number } | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (typeof window === 'undefined' || !window.sessionStorage) return
    const raw = window.sessionStorage.getItem(CHAT_TURNS_KEY)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw) as ChatTurn[]
      if (Array.isArray(parsed)) {
        setTurns(
          parsed.filter(
            (x) => x && (x.role === 'user' || x.role === 'assistant') && typeof x.text === 'string',
          ),
        )
      }
    } catch {
      window.sessionStorage.removeItem(CHAT_TURNS_KEY)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined' || !window.sessionStorage) return
    window.sessionStorage.setItem(CHAT_TURNS_KEY, JSON.stringify(turns))
  }, [turns])

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
      setChatThreadId(r.thread_id)
      setTurns((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: r.answer,
          sources: r.sources,
          responseType: r.response_type,
          timeLabel: timeLabel(),
        },
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

  const onNewConversation = useCallback(() => {
    if (loading) return
    setChatThreadId(null)
    setTurns([])
    if (typeof window !== 'undefined' && window.sessionStorage) {
      window.sessionStorage.removeItem(CHAT_TURNS_KEY)
    }
    setInput('')
    setError(null)
    setSelection(null)
  }, [loading])

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <main className="flex-1 overflow-y-auto bg-background flex flex-col items-center min-h-0 max-h-[calc(100dvh-9rem)] md:max-h-[calc(100dvh-10rem)]">
        <div className="w-full max-w-[44rem] px-5 py-5 md:py-6 space-y-6">

          {/* Empty state */}
          {turns.length === 0 && (
            <div className="text-center space-y-2 py-3">
              <div className="w-12 h-12 rounded-2xl bg-surface-container-low border border-outline/50 flex items-center justify-center mx-auto">
                <Icon name="smart_toy" className="text-xl text-primary" filled />
              </div>
              <p className="text-sm text-on-surface-variant max-w-sm mx-auto">
                Haz una pregunta sobre los documentos indexados.
              </p>
            </div>
          )}

          {/* Conversation turns */}
          {turns.map((m, i) =>
            m.role === 'user' ? (
              <div key={i} className="flex flex-col items-end gap-1.5">
                <div className="bg-primary text-on-primary px-5 py-3.5 rounded-2xl rounded-tr-sm shadow-md max-w-[85%] glow-primary">
                  <p className="text-sm font-medium leading-relaxed whitespace-pre-wrap">{m.text}</p>
                </div>
                <span className="text-[10px] font-semibold text-on-surface-variant/60 uppercase tracking-widest px-1">
                  Tú · {m.timeLabel ?? ''}
                </span>
              </div>
            ) : (
              <div key={i} className="flex flex-col items-start gap-4">
                <div className="flex gap-4 w-full">
                  {/* AI avatar */}
                  <div className="w-8 h-8 rounded-lg bg-surface-container-high border border-outline/60 shrink-0 flex items-center justify-center">
                    <Icon name="smart_toy" className="text-primary text-base" />
                  </div>

                  <div
                    className={[
                      'flex-1 space-y-5 min-w-0 pl-1',
                      m.responseType === 'clarification'
                        ? 'border-l-2 border-warn -ml-1 pl-4 bg-tertiary-container/10 rounded-r-xl py-3 pr-3'
                        : '',
                    ].join(' ').trim()}
                  >
                    {m.responseType === 'clarification' && (
                      <p className="text-[10px] font-bold text-tertiary uppercase tracking-widest m-0">
                        Aclaración
                      </p>
                    )}

                    <div className="text-on-surface leading-relaxed prose prose-sm max-w-none prose-p:text-sm prose-p:leading-relaxed prose-headings:font-headline">
                      <MarkdownContent content={m.text} />
                    </div>

                    {/* Sources */}
                    {m.sources && m.sources.length > 0 && (
                      <div className="space-y-3">
                        <div className="flex items-center gap-1.5 text-[10px] font-bold text-on-surface-variant/70 uppercase tracking-widest">
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
                                className={[
                                  'px-3 py-1.5 text-[11px] font-semibold rounded-full transition-all duration-150 flex items-center gap-1.5',
                                  active
                                    ? 'bg-primary/20 text-primary border border-primary/40'
                                    : 'bg-surface-container-low text-on-surface-variant border border-outline/50 hover:border-primary/30 hover:text-primary',
                                ].join(' ')}
                              >
                                <span className="w-4 h-4 rounded-full bg-surface-container-high text-on-surface-variant flex items-center justify-center text-[9px] font-bold shrink-0">
                                  {j + 1}
                                </span>
                                <span className="truncate max-w-[12rem]">{name}</span>
                              </button>
                            )
                          })}
                        </div>

                        {/* Source excerpt */}
                        {selection?.turnIndex === i && m.sources[selection.sourceIndex] != null && (
                          <div className="mt-3 p-4 bg-surface-container-low rounded-xl border border-outline/50 modal-enter">
                            <div className="flex justify-between items-center mb-3 gap-2">
                              <div className="flex flex-wrap items-center gap-2 min-w-0">
                                <span className="text-[10px] font-bold text-secondary uppercase tracking-tighter shrink-0">
                                  Extracto
                                </span>
                                <span className="text-[10px] text-on-surface-variant/70 truncate">
                                  · {String(m.sources[selection.sourceIndex].metadata.source ?? 'doc')}
                                </span>
                              </div>
                              <button
                                type="button"
                                className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant shrink-0"
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
                              <pre className="text-xs text-on-surface-variant leading-relaxed whitespace-pre-wrap break-words font-sans font-normal m-0 max-w-full border-0 bg-transparent">
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
                {m.timeLabel && (
                  <span className="text-[10px] font-semibold text-on-surface-variant/50 uppercase tracking-widest pl-12">
                    {m.timeLabel}
                  </span>
                )}
              </div>
            ),
          )}

          {/* Loading */}
          {loading && (
            <div className="flex items-center gap-3 pl-12 py-2">
              <span className="flex gap-1.5">
                {[0, 200, 400].map((delay) => (
                  <span
                    key={delay}
                    className="w-1.5 h-1.5 bg-primary rounded-full"
                    style={{
                      animation: `pulse-dot 1.4s ease-in-out ${delay}ms infinite`,
                    }}
                  />
                ))}
              </span>
              <span className="text-xs font-medium text-on-surface-variant">Procesando consulta…</span>
            </div>
          )}

          {/* Error */}
          {error && (
            <p className="text-center text-sm text-error/90 bg-error-container/20 border border-error/20 rounded-lg px-4 py-2.5">
              {error}
            </p>
          )}

          <div ref={bottomRef} className="h-4" />
        </div>
      </main>

      {/* Input footer */}
      <footer className="sticky bottom-0 z-20 w-full flex justify-center pb-3 pt-2 bg-gradient-to-t from-background via-background/95 to-transparent shrink-0">
        <div className="w-full max-w-[44rem] px-5">
          <div className="relative liquid-glass rounded-2xl group focus-within:border-primary/25 transition-all">
            <textarea
              className="w-full bg-transparent border-none focus:ring-0 p-5 pr-[8.5rem] text-sm resize-none min-h-[80px] font-medium placeholder:text-on-surface-variant/35 rounded-2xl text-on-surface outline-none"
              placeholder="Pregunta algo sobre el índice de conocimiento…"
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
            <div className="absolute bottom-4 right-4 flex items-center gap-2">
              <button
                type="button"
                onClick={onNewConversation}
                disabled={loading}
                className="inline-flex items-center gap-1.5 px-2.5 py-2 rounded-lg bg-surface-container border border-outline/50 text-[11px] font-semibold text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-all disabled:opacity-50"
                title="Limpiar historial del chat y comenzar un nuevo hilo"
              >
                <Icon name="add_comment" className="text-sm" />
                <span className="hidden sm:inline">Nueva</span>
              </button>
              <button
                type="button"
                disabled={loading || !input.trim()}
                onClick={() => void onSend()}
                className="w-9 h-9 bg-primary text-on-primary rounded-xl flex items-center justify-center glow-primary active:scale-95 transition-transform disabled:opacity-40 disabled:shadow-none"
                aria-label="Enviar"
              >
                {loading ? (
                  <span className="flex gap-0.5 px-1">
                    {[0, -150, -300].map((delay) => (
                      <span
                        key={delay}
                        className="w-1 h-1 bg-on-primary rounded-full"
                        style={{ animation: `pulse-dot 1.2s ease-in-out ${delay}ms infinite` }}
                      />
                    ))}
                  </span>
                ) : (
                  <Icon name="send" className="text-base" />
                )}
              </button>
            </div>
            <div className="absolute bottom-4 left-5 flex items-center">
              <span className="text-[10px] font-medium text-on-surface-variant/30 hidden md:block">
                Shift + Enter · nueva línea
              </span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}
