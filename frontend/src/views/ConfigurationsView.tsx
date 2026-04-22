import { SystemPromptsPanel } from '../components/SystemPromptsPanel'
import { IndexFragmentBadge } from '../components/IndexFragmentBadge'
import type { StatsResponse } from '../api'

export function ConfigurationsView({ stats }: { stats: StatsResponse | null }) {
  return (
    <main className="flex-1 ml-0 p-6 md:p-8 bg-surface min-h-screen">
      <div className="mb-8 max-w-4xl">
        <h1 className="font-headline text-3xl md:text-4xl font-extrabold tracking-tight text-on-surface mb-2">
          Configuraciones
        </h1>
        <p className="text-on-surface-variant text-sm md:text-base leading-relaxed m-0">
          Ajustes de la aplicación: instrucciones del modelo (system prompt) por canal, sin reiniciar el backend.
        </p>
        <div className="mt-3">
          <IndexFragmentBadge stats={stats} className="text-on-surface-variant" />
        </div>
      </div>

      <div className="max-w-5xl">
        <SystemPromptsPanel />
      </div>
    </main>
  )
}
