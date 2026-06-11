import { useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import {
  useAcknowledgeAlert,
  useAcknowledgeAllAlerts,
  useDismissAlert,
  usePipelineAlerts,
  useResolveAlert,
} from '../hooks/useApi';
import { formatDateTime, formatRelative } from '../lib/dateUtils';
import type { AlertDetail } from '../types/api';

const ZONES = [
  '', 'Camberene', 'Camberene1', 'Camberene2',
  'GrandDakar', 'GrandDakar1', 'GrandDakar2',
  'ParcellesAssainies', 'ParcellesAssainies1', 'ParcellesAssainies2',
  'Plateau', 'Plateau1', 'Plateau2',
  'Hann', 'Hann1', 'Hann2',
  'Yoff', 'Yoff1', 'Yoff2',
  'Mermoz', 'Mermoz1', 'Mermoz2',
  'SacreCoeur', 'SacreCoeur1', 'SacreCoeur2',
  'Ouakam', 'Ouakam1', 'Ouakam2',
  'Ngor', 'Ngor1', 'Ngor2',
  'Fann', 'Fann1', 'Fann2',
  'Medina', 'Medina1', 'Medina2',
];

const GRAVITIES = [
  { value: '', label: 'Toutes' },
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'danger', label: 'Danger' },
  { value: 'critical', label: 'Critical' },
] as const;

const ALERT_TYPES = [
  { value: '', label: 'Tous' },
  { value: 'prevision', label: 'Prévision' },
  { value: 'anomaly', label: 'Anomalie' },
  { value: 'citizen_report', label: 'Signalement' },
  { value: 'data_quality', label: 'Qualité données' },
  { value: 'system', label: 'Système' },
] as const;

const DATE_RANGES = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7j' },
  { value: '30d', label: '30j' },
] as const;

function severityColor(severity: string) {
  const map: Record<string, string> = {
    info: 'border-blue-500',
    warning: 'border-yellow-500',
    danger: 'border-orange-500',
    critical: 'border-red-500',
  };
  return map[severity] ?? 'border-slate-500';
}

function severityBadgeClass(severity: string) {
  const map: Record<string, string> = {
    info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    danger: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  };
  return map[severity] ?? 'bg-slate-500/20 text-slate-400 border-slate-500/30';
}

export function AlertsPage() {
  const [zone, setZone] = useState('');
  const [gravite, setGravite] = useState('');
  const [type, setType] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [dateRange, setDateRange] = useState<string>('24h');
  const [page, setPage] = useState(1);
  const pageSize = 12;

  const dateMap: Record<string, { from: string; to: string }> = {
    '24h': { from: new Date(Date.now() - 86400_000).toISOString(), to: new Date().toISOString() },
    '7d': { from: new Date(Date.now() - 604800_000).toISOString(), to: new Date().toISOString() },
    '30d': { from: new Date(Date.now() - 2592000_000).toISOString(), to: new Date().toISOString() },
  };

  const { data, isLoading, isError } = usePipelineAlerts({
    zone_id: zone || undefined,
    gravite: gravite || undefined,
    type: type || undefined,
    active_only: activeOnly || undefined,
    date_from: dateMap[dateRange].from,
    date_to: dateMap[dateRange].to,
    page,
    page_size: pageSize,
  });

  const acknowledgeAlert = useAcknowledgeAlert();
  const resolveAlert = useResolveAlert();
  const dismissAlert = useDismissAlert();
  const acknowledgeAll = useAcknowledgeAllAlerts();

  const alerts = data?.alerts ?? [];
  const total = data?.pagination?.total_count ?? 0;
  const totalPages = data?.pagination?.total_pages ?? 1;

  const activeCount = alerts.filter((a) => a.active).length;
  const resolvedToday = alerts.filter(
    (a) => a.resolved_at && new Date(a.resolved_at).toDateString() === new Date().toDateString(),
  ).length;

  const dailyData: Array<{ date: string; info: number; warning: number; danger: number; critical: number }> = [];
  const dayMap: Record<string, { info: number; warning: number; danger: number; critical: number }> = {};
  alerts.forEach((a) => {
    const d = a.created_at.slice(0, 10);
    if (!dayMap[d]) dayMap[d] = { info: 0, warning: 0, danger: 0, critical: 0 };
    const sev = a.gravite as keyof typeof dayMap[string];
    if (sev in dayMap[d]) dayMap[d][sev]++;
  });
  Object.entries(dayMap)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .forEach(([date, counts]) => {
      dailyData.push({ date, ...counts });
    });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={data?.generated_at ?? null} />} />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">Alert Manager</h1>
        </div>

        {isLoading && <Spinner label="Chargement des alertes…" />}

        <section
          aria-label="Filtres"
          className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-700 bg-slate-800 p-3"
        >
          <select
            value={zone}
            onChange={(e) => { setZone(e.target.value); setPage(1); }}
            className="rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-xs text-slate-200"
          >
            <option value="">Toutes les zones</option>
            {ZONES.filter((z) => z).map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>

          <select
            value={gravite}
            onChange={(e) => { setGravite(e.target.value); setPage(1); }}
            className="rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-xs text-slate-200"
          >
            {GRAVITIES.map((g) => (
              <option key={g.value} value={g.value}>{g.label}</option>
            ))}
          </select>

          <select
            value={type}
            onChange={(e) => { setType(e.target.value); setPage(1); }}
            className="rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-xs text-slate-200"
          >
            {ALERT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>

          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(e) => { setActiveOnly(e.target.checked); setPage(1); }}
              className="rounded border-slate-600 bg-slate-700"
            />
            Actives seulement
          </label>

          <div className="flex rounded border border-slate-600 overflow-hidden ml-auto">
            {DATE_RANGES.map((d) => (
              <button
                key={d.value}
                onClick={() => { setDateRange(d.value); setPage(1); }}
                className={`px-2 py-1.5 text-xs ${
                  dateRange === d.value
                    ? 'bg-slate-600 text-white'
                    : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>
        </section>

        {isError && (
          <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
            Impossible de charger les alertes.
          </p>
        )}

        {data && !isLoading && !isError && (
          <>
            <section aria-label="Statistiques" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <p className="text-2xl font-bold text-white">{activeCount}</p>
                <p className="text-xs text-slate-400">Alertes actives</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <p className="text-2xl font-bold text-green-400">{resolvedToday}</p>
                <p className="text-xs text-slate-400">Résolues aujourd'hui</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <p className="text-2xl font-bold text-white">{total}</p>
                <p className="text-xs text-slate-400">Total</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4 flex flex-col gap-1">
                <button
                  onClick={() => acknowledgeAll.mutate({ severity: 'info' })}
                  disabled={acknowledgeAll.isPending}
                  className="rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Accepter toutes info
                </button>
                <button
                  onClick={() => acknowledgeAll.mutate({})}
                  disabled={acknowledgeAll.isPending}
                  className="rounded bg-green-600 px-2 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                >
                  Accepter toutes actives
                </button>
              </div>
            </section>

            <section aria-label="Tendance" className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Alertes par jour
              </h3>
              {dailyData.length > 0 ? (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={dailyData}>
                      <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="date"
                        tick={{ fill: '#94a3b8', fontSize: 11 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fill: '#94a3b8', fontSize: 11 }}
                        tickLine={false}
                        axisLine={false}
                        width={30}
                      />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: '#1e293b',
                          border: '1px solid #475569',
                          borderRadius: '8px',
                          color: '#f1f5f9',
                          fontSize: '12px',
                        }}
                      />
                      <Area
                        type="monotone"
                        dataKey="critical"
                        stackId="1"
                        stroke="#ef4444"
                        fill="#ef4444"
                        fillOpacity={0.3}
                      />
                      <Area
                        type="monotone"
                        dataKey="danger"
                        stackId="1"
                        stroke="#f97316"
                        fill="#f97316"
                        fillOpacity={0.3}
                      />
                      <Area
                        type="monotone"
                        dataKey="warning"
                        stackId="1"
                        stroke="#eab308"
                        fill="#eab308"
                        fillOpacity={0.3}
                      />
                      <Area
                        type="monotone"
                        dataKey="info"
                        stackId="1"
                        stroke="#3b82f6"
                        fill="#3b82f6"
                        fillOpacity={0.3}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500">Aucune donnée.</p>
              )}
            </section>

            <section aria-label="Alertes">
              <h2 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Alertes ({total})
              </h2>
              {alerts.length === 0 ? (
                <p className="rounded-xl border border-slate-700 bg-slate-800 p-8 text-center text-sm text-slate-500">
                  Aucune alerte trouvée.
                </p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {alerts.map((a) => (
                    <AlertCard
                      key={a.id}
                      alert={a}
                      onAcknowledge={() => acknowledgeAlert.mutate(a.id)}
                      onResolve={() => resolveAlert.mutate(a.id)}
                      onDismiss={() => dismissAlert.mutate(a.id)}
                      ackPending={acknowledgeAlert.isPending}
                      resolvePending={resolveAlert.isPending}
                      dismissPending={dismissAlert.isPending}
                    />
                  ))}
                </div>
              )}

              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
                  <span>
                    Page {page} / {totalPages}
                  </span>
                  <div className="flex gap-1">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page <= 1}
                      className="rounded border border-slate-600 bg-slate-700 px-2 py-1 disabled:opacity-30 text-slate-300"
                    >
                      Précédent
                    </button>
                    <button
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page >= totalPages}
                      className="rounded border border-slate-600 bg-slate-700 px-2 py-1 disabled:opacity-30 text-slate-300"
                    >
                      Suivant
                    </button>
                  </div>
                </div>
              )}
            </section>
          </>
        )}

        {!data && !isLoading && !isError && (
          <p className="py-12 text-center text-sm text-slate-500">
            Utilisez les filtres pour rechercher des alertes.
          </p>
        )}
      </main>
    </div>
  );
}

function AlertCard({
  alert,
  onAcknowledge,
  onResolve,
  onDismiss,
  ackPending,
  resolvePending,
  dismissPending,
}: {
  alert: AlertDetail;
  onAcknowledge: () => void;
  onResolve: () => void;
  onDismiss: () => void;
  ackPending: boolean;
  resolvePending: boolean;
  dismissPending: boolean;
}) {
  const color = severityColor(alert.gravite);
  const isAcknowledged = !!alert.acknowledged_at;
  const isResolved = !!alert.resolved_at;

  return (
    <div className={`rounded-xl border-l-4 ${color} border border-slate-700 bg-slate-800 p-4`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${severityBadgeClass(alert.gravite)}`}
          >
            {alert.gravite}
          </span>
          <span className="truncate text-sm font-medium text-white">{alert.zone_name || alert.zone_id}</span>
        </div>
        <span className="shrink-0 text-[11px] text-slate-500">{formatRelative(alert.created_at)}</span>
      </div>

      <div className="mb-1 flex items-center gap-2 text-[11px] text-slate-400">
        <span className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px]">{alert.type}</span>
        {alert.pollutant && (
          <span className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px]">{alert.pollutant}</span>
        )}
        {isAcknowledged && (
          <span className="rounded border border-blue-700 px-1.5 py-0.5 text-[10px] text-blue-400">
            Accepté
          </span>
        )}
        {isResolved && (
          <span className="rounded border border-green-700 px-1.5 py-0.5 text-[10px] text-green-400">
            Résolu
          </span>
        )}
      </div>

      <p className="mb-3 text-xs text-slate-300 line-clamp-2">{alert.message}</p>

      <p className="mb-3 text-[11px] text-slate-500">
        {formatDateTime(alert.created_at)}
        {alert.resolved_at && ` · Résolue ${formatRelative(alert.resolved_at)}`}
      </p>

      <div className="flex gap-1">
        {!isAcknowledged && (
          <button
            onClick={onAcknowledge}
            disabled={ackPending}
            className="rounded bg-blue-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Accepter
          </button>
        )}
        {!isResolved && (
          <button
            onClick={onResolve}
            disabled={resolvePending}
            className="rounded bg-green-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            Résoudre
          </button>
        )}
        <button
          onClick={onDismiss}
          disabled={dismissPending}
          className="rounded border border-slate-600 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-700 disabled:opacity-50"
        >
          Ignorer
        </button>
      </div>
    </div>
  );
}
