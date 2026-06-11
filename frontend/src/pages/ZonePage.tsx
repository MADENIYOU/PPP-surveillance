import { Link, useParams } from 'react-router-dom';

import { TimeSeriesChartPlaceholder } from './placeholders';
import { TimeSeriesChart, type Pollutant } from '../components/charts/TimeSeriesChart';
import { Header } from '../components/ui/Header';
import { IQAGauge } from '../components/ui/IQAGauge';
import { Spinner } from '../components/ui/Spinner';
import { useAqiCurrent, useAqiHistory, usePredictions, useReports, useSensors } from '../hooks/useApi';
import { formatRelative } from '../lib/dateUtils';
import { useAppStore, type HistoryPeriod } from '../store/useAppStore';
import { useState } from 'react';

const TABS: { key: Pollutant; label: string }[] = [
  { key: 'pm25', label: 'PM2.5' },
  { key: 'pm10', label: 'PM10' },
  { key: 'no2', label: 'NO₂' },
  { key: 'co', label: 'CO' },
  { key: 'temperature', label: 'Température' },
  { key: 'humidity', label: 'Humidité' },
];

const PERIODS: HistoryPeriod[] = ['24h', '7j', '30j'];

export function ZonePage() {
  const { zone_id = '' } = useParams();
  const [pollutant, setPollutant] = useState<Pollutant>('pm25');
  const { historyPeriod, setHistoryPeriod } = useAppStore();

  const { data: aqi } = useAqiCurrent(zone_id);
  const { data: history, isLoading } = useAqiHistory(zone_id, historyPeriod);
  const { data: predictions } = usePredictions(zone_id);
  const { data: sensors } = useSensors(zone_id);
  const { data: reports } = useReports(zone_id);

  const zone = aqi?.zones[0];
  const zonePred = predictions?.predictions.find((p) => p.zone_id === zone_id);
  const horizons = zonePred
    ? (['h1', 'h6', 'h24'] as const).map((k) => zonePred.horizons[k]).filter((h) => h != null)
    : [];

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <main className="mx-auto max-w-5xl space-y-4 p-4">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-sm text-blue-600 hover:underline">
            ← Retour
          </Link>
          <h1 className="text-xl font-bold text-gray-800">{zone?.zone_name ?? zone_id}</h1>
          <IQAGauge iqa={zone?.iqa ?? null} size="sm" />
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Polluant">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={pollutant === t.key}
                  onClick={() => setPollutant(t.key)}
                  className={`rounded px-3 py-1 text-sm ${
                    pollutant === t.key
                      ? 'bg-slate-800 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  onClick={() => setHistoryPeriod(p)}
                  className={`rounded px-2 py-1 text-xs ${
                    historyPeriod === p ? 'bg-blue-600 text-white' : 'bg-gray-100 hover:bg-gray-200'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {isLoading && <Spinner />}
          {history && history.data.length > 0 ? (
            <TimeSeriesChart data={history.data} predictions={horizons} pollutant={pollutant} />
          ) : (
            !isLoading && <TimeSeriesChartPlaceholder label="Pas encore de données pour cette zone." />
          )}
        </div>

        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold uppercase text-gray-500">
            Capteurs actifs dans la zone
          </h2>
          <div className="flex flex-wrap gap-2">
            {sensors?.sensors.map((s) => (
              <span key={s.sensor_id}
                    className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-xs">
                {s.sensor_id}{' '}
                <span className={s.status === 'active' ? 'text-green-600' : 'text-gray-400'}>●</span>
                {s.battery_pct != null && ` 🔋${Math.round(s.battery_pct)}%`}
              </span>
            ))}
            {sensors && sensors.sensors.length === 0 && (
              <span className="text-sm text-gray-400">Aucun capteur dans cette zone.</span>
            )}
          </div>
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold uppercase text-gray-500">
            Signalements récents (24h)
          </h2>
          <ul className="space-y-1 text-sm text-gray-700">
            {reports?.reports.map((r) => (
              <li key={r.id}>
                • « {r.description_excerpt} » — {formatRelative(r.created_at)}
              </li>
            ))}
            {reports && reports.reports.length === 0 && (
              <li className="text-gray-400">Aucun signalement récent.</li>
            )}
          </ul>
        </section>
      </main>
    </div>
  );
}
