import { useNavigate } from 'react-router-dom';

import { TimeSeriesChartPlaceholder } from './placeholders';
import { PollutionMap } from '../components/map/PollutionMap';
import { AlertBanner } from '../components/ui/AlertBanner';
import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import { ZoneCard } from '../components/ui/ZoneCard';
import { useAlerts, useAqiCurrent } from '../hooks/useApi';

export function DashboardPage() {
  const { data: aqi, isLoading, isError } = useAqiCurrent();
  const { data: alertsData } = useAlerts();
  const navigate = useNavigate();

  const alerts = alertsData?.alerts ?? [];
  const alertZones = new Set(alerts.map((a) => a.zone_id));

  return (
    <div className="flex min-h-screen flex-col bg-gray-50">
      <Header live={<LiveIndicator lastUpdate={aqi?.meta.generated_at ?? null} />} />
      <AlertBanner alerts={alerts} />

      <main className="flex flex-1 flex-col gap-4 p-4 lg:flex-row">
        <section className="h-[50vh] flex-1 overflow-hidden rounded-lg border border-gray-200 lg:h-auto"
                 aria-label="Carte de pollution">
          <PollutionMap />
        </section>

        <aside className="w-full space-y-2 lg:w-80" aria-label="IQA par zone">
          <h2 className="text-sm font-semibold uppercase text-gray-500">Zones</h2>
          {isLoading && <Spinner />}
          {isError && (
            <p className="rounded bg-red-50 p-3 text-sm text-red-700">
              Impossible de joindre l'API. Vérifiez que le backend est démarré.
            </p>
          )}
          {aqi?.zones.map((z) => (
            <ZoneCard
              key={z.zone_id}
              zone={z}
              hasActiveAlert={alertZones.has(z.zone_id)}
              onClick={() => navigate(`/zone/${z.zone_id}`)}
            />
          ))}
          {aqi && aqi.zones.length === 0 && <TimeSeriesChartPlaceholder label="Aucune zone" />}
        </aside>
      </main>

      <footer className="border-t bg-white px-4 py-2 text-center text-xs text-gray-500">
        © DIC2 ESP Dakar 2026 — Surveillance Citoyenne de la Pollution
      </footer>
    </div>
  );
}
