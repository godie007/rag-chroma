import type { ConfigPublic, StatsResponse } from '../api'
import { getApiBase } from '../api'
import { WhatsAppAllowlistPanel } from '../components/WhatsAppAllowlistPanel'
import { IndexFragmentBadge } from '../components/IndexFragmentBadge'
import { Icon } from '../components/Icon'

export function WhatsAppSettingsView({
  config,
  stats,
}: {
  config: ConfigPublic | null
  stats: StatsResponse | null
}) {
  const api = getApiBase()
  const wa = config?.whatsapp_webhook_active ?? false
  const poll = config?.whatsapp_polling_active ?? false

  return (
    <main className="flex-1 ml-0 p-6 md:p-8 bg-surface min-h-screen">
      <div className="mb-10 max-w-4xl">
        <h1 className="font-headline text-3xl md:text-4xl font-extrabold tracking-tight text-on-surface mb-2">
          WhatsApp
        </h1>
        <p className="text-on-surface-variant text-sm md:text-base leading-relaxed">
          Administración del canal WhatsApp: control de acceso por número y referencia rápida del enlace con el backend.
        </p>
        <div className="mt-3">
          <IndexFragmentBadge stats={stats} className="text-on-surface-variant" />
        </div>
      </div>

      {!wa ? (
        <div className="mb-8 max-w-3xl rounded-xl border border-tertiary/30 bg-tertiary-container/10 px-5 py-4 text-sm text-on-surface">
          <div className="flex gap-3">
            <Icon name="info" className="text-tertiary text-xl shrink-0" />
            <div>
              <p className="font-bold text-on-surface mb-1">Integración inactiva en el servidor</p>
              <p className="text-on-surface-variant leading-relaxed m-0">
                Activa <code className="text-xs bg-surface-container-high px-1 rounded">WHATSAPP_ENABLED</code> y asegura un RAG
                operativo. La lista de números se puede editar igualmente; se aplicará cuando el flujo WhatsApp esté en marcha.
              </p>
            </div>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-12 gap-6 md:gap-8 max-w-7xl">
        <div className="col-span-12 xl:col-span-5 space-y-6">
          <WhatsAppAllowlistPanel />
        </div>

        <div className="col-span-12 xl:col-span-7 space-y-6">
          <section className="bg-surface-container-lowest p-6 md:p-8 rounded-xl shadow-sm border border-outline-variant/5">
            <h3 className="font-headline text-lg font-bold mb-4 flex items-center gap-2 text-on-surface">
              <Icon name="hub" className="text-primary text-xl" />
              Estado de la integración
            </h3>
            <dl className="space-y-4 text-sm">
              <div className="flex flex-wrap justify-between gap-2 py-2 border-b border-outline-variant/10">
                <dt className="text-on-surface-variant font-semibold">Recepción</dt>
                <dd className="text-on-surface font-mono text-xs md:text-sm">
                  {poll ? (
                    <span className="inline-flex items-center gap-1 text-secondary font-bold">
                      <Icon name="sync" className="text-base" />
                      Polling ({config?.whatsapp_poll_mode})
                    </span>
                  ) : (
                    <span className="text-on-surface-variant">Webhook / sin polling</span>
                  )}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2 py-2 border-b border-outline-variant/10">
                <dt className="text-on-surface-variant font-semibold">API puente (mensajes / envío)</dt>
                <dd className="text-on-surface break-all font-mono text-xs md:text-sm text-right max-w-full md:max-w-[65%]">
                  {config?.whatsapp_api_base_url ?? '—'}
                </dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2 py-2 border-b border-outline-variant/10">
                <dt className="text-on-surface-variant font-semibold">Intervalo de sondeo</dt>
                <dd className="text-on-surface font-mono">
                  {config?.whatsapp_poll_interval_sec != null ? `${config.whatsapp_poll_interval_sec} s` : '—'}
                </dd>
              </div>
              <div className="pt-1">
                <dt className="text-on-surface-variant font-semibold mb-2">Webhook del RAG</dt>
                <dd className="m-0">
                  <code className="block w-full text-xs md:text-sm p-3 rounded-xl bg-surface-container-low font-mono break-all text-primary">
                    {api}/webhooks/whatsapp
                  </code>
                </dd>
              </div>
            </dl>
          </section>

          <section className="bg-slate-900 text-white p-6 md:p-8 rounded-2xl relative overflow-hidden">
            <div className="absolute top-0 right-0 w-56 h-56 bg-primary/15 blur-[80px] rounded-full -translate-y-1/2 translate-x-1/2 pointer-events-none" />
            <div className="relative z-10">
              <h4 className="font-headline text-lg font-bold mb-3 flex items-center gap-2">
                <Icon name="lightbulb" className="text-amber-200" />
                Buenas prácticas
              </h4>
              <ul className="text-slate-300 text-sm space-y-2.5 leading-relaxed list-none m-0 p-0">
                <li className="flex gap-2">
                  <span className="text-secondary font-bold">·</span>
                  Los números autorizados son los del <strong className="text-white">remitente del chat</strong> (quien escribe al
                  número conectado a GOWA), no el de la sesión del servidor.
                </li>
                <li className="flex gap-2">
                  <span className="text-secondary font-bold">·</span>
                  Los grupos siguen la configuración del backend; esta lista filtra por JID en conversaciones 1:1.
                </li>
                <li className="flex gap-2">
                  <span className="text-secondary font-bold">·</span>
                  Tras cambios masivos en producción, conviene revisar los logs del servicio RAG ante cualquier bloqueo
                  inesperado.
                </li>
              </ul>
            </div>
          </section>
        </div>
      </div>
    </main>
  )
}
