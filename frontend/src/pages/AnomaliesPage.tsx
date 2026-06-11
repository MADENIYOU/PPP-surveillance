import { useState } from 'react';
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
} from 'recharts';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import { useAnomaliesSearch } from '../hooks/useApi';
import { formatDateTime, formatRelative } from '../lib/dateUtils';
import type { AnomalySearchResult } from '../types/api';

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

const SEVERITIES = [
  { value: '', label: 'Toutes' },
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'danger', label: 'Danger' },
  { value: 'critical', label: 'Critical' },
] as const;

const TYPES = [
  { value: '', label: 'Tous' },
  { value: 'threshold_exceeded', label: 'Seuil dépassé' },
  { value: 'pollution_anomaly', label: 'Anomalie pollution' },
  { value: 'stuck_sensor', label: 'Capteur bloqué' },
  { value: 'implausible_ratio', label: 'Ratio invraisemblable' },
] as const;

const POLLUTANTS = [
  { value: '', label: 'Tous' },
  { value: 'pm25', label: 'PM2.5' },
  { value: 'pm10', label: 'PM10' },
  { value: 'co', label: 'CO' },
  { value: 'no2', label: 'NO₂' },
  { value: 'o3', label: 'O₃' },
] as const;

const DATE_RANGES = [
  { value: '1h', label: '1h' },
  { value: '6h', label: '6h' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7j' },
  { value: '30d', label: '30j' },
] as const;

const PAGE_SIZES = [10, 25, 50, 100];

function severityBadgeClass(severity: string) {
  const map: Record<string, string> = {
    info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    danger: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  };
  return map[severity] ?? map.info;
}

function severityColorHex(severity: string) {
  const map: Record<string, string> = {
    info: '#3b82f6',
    warning: '#eab308',
    danger: '#f97316',
    critical: '#ef4444',
  };
  return map[severity] ?? '#94a3b8';
}

function computeDateRange(range: string): { from: string; to: string } {
  const now = Date.now();
  const map: Record<string, number> = {
    '1h': 3600_000,
    '6h': 21600_000,
    '24h': 86400_000,
    '7d': 604800_000,
    '30d': 2592000_000,
  };
  const ms = map[range] ?? 86400_000;
  return {
    from: new Date(now - ms).toISOString(),
    to: new Date(now).toISOString(),
  };
}

export function AnomaliesPage() {
  const [zone, setZone] = useState('');
  const [severity, setSeverity] = useState('');
  const [type, setType] = useState('');
  const [pollutant, setPollutant] = useState('');
  const [dateRange, setDateRange] = useState<string>('24h');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [sortKey, setSortKey] = useState<string>('detected_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const dateFilter = computeDateRange(dateRange);

  const { data, isLoading, isError } = useAnomaliesSearch({
    zone_id: zone || undefined,
    severity: severity || undefined,
    type: type || undefined,
    pollutant: pollutant || undefined,
    date_from: dateFilter.from,
    date_to: dateFilter.to,
    page,
    page_size: pageSize,
  });

  const anomalies = data?.anomalies ?? [];
  const total = data?.pagination?.total_count ?? 0;
  const totalPages = Math.max(1, data?.pagination?.total_pages ?? 1);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const sortedAnomalies = [...anomalies].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    const aVal = (a as unknown as Record<string, unknown>)[sortKey];
    const bVal = (b as unknown as Record<string, unknown>)[sortKey];
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return 1;
    if (bVal == null) return -1;
    if (typeof aVal === 'number' && typeof bVal === 'number') return (aVal - bVal) * dir;
    return String(aVal).localeCompare(String(bVal)) * dir;
  });

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const severityCounts: Record<string, number> = {};
  const zoneCounts: Record<string, number> = {};
  const pollutantCounts: Record<string, number> = {};
  sortedAnomalies.forEach((a) => {
    severityCounts[a.severity] = (severityCounts[a.severity] || 0) + 1;
    zoneCounts[a.zone_id] = (zoneCounts[a.zone_id] || 0) + 1;
    pollutantCounts[a.pollutant] = (pollutantCounts[a.pollutant] || 0) + 1;
  });

  const pieData = [
    { name: 'Info', value: severityCounts.info || 0, color: severityColorHex('info') },
    { name: 'Warning', value: severityCounts.warning || 0, color: severityColorHex('warning') },
    { name: 'Danger', value: severityCounts.danger || 0, color: severityColorHex('danger') },
    { name: 'Critical', value: severityCounts.critical || 0, color: severityColorHex('critical') },
  ].filter((d) => d.value > 0);

  const mostAffectedZone = Object.entries(zoneCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
  const mostAffectedPollutant =
    Object.entries(pollutantCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;

  const timeline: Record<string, AnomalySearchResult[]> = {};
  sortedAnomalies.forEach((a) => {
    const hour = new Date(a.detected_at).toISOString().slice(0, 13) + ':00';
    if (!timeline[hour]) timeline[hour] = [];
    timeline[hour].push(a);
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={data?.generated_at ?? null} />} />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">Anomaly Explorer</h1>
        </div>

        {isLoading && <Spinner label="Chargement des anomalies…" />}

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
            value={severity}
            onChange={(e) => { setSeverity(e.target.value); setPage(1); }}
            className="rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-xs text-slate-200"
          >
            {SEVERITIES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>

          <select
            value={type}
            onChange={(e) => { setType(e.target.value); setPage(1); }}
            className="rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-xs text-slate-200"
          >
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>

          <select
            value={pollutant}
            onChange={(e) => { setPollutant(e.target.value); setPage(1); }}
            className="rounded border border-slate-600 bg-slate-700 px-2 py-1.5 text-xs text-slate-200"
          >
            {POLLUTANTS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>

          <div className="flex rounded border border-slate-600 overflow-hidden">
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
            Impossible de charger les anomalies.
          </p>
        )}

        {data && !isLoading && !isError && (
          <>
            <section aria-label="Résumé" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <SummaryCard label="Anomalies" value={total} />
              <SummaryCard
                label="Par sévérité"
                value={`${severityCounts.critical || 0}C / ${severityCounts.danger || 0}D / ${severityCounts.warning || 0}W`}
              />
              <SummaryCard label="Zone la + touchée" value={mostAffectedZone ?? '—'} />
              <SummaryCard label="Polluant dominant" value={mostAffectedPollutant?.toUpperCase() ?? '—'} />
            </section>

            <section aria-label="Distribution et périmètre" className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                  Distribution par sévérité
                </h3>
                {pieData.length > 0 ? (
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={pieData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={80}
                          innerRadius={40}
                          paddingAngle={3}
                        >
                          {pieData.map((entry, idx) => (
                            <Cell key={idx} fill={entry.color} stroke="#1e293b" strokeWidth={2} />
                          ))}
                        </Pie>
                        <RechartsTooltip
                          contentStyle={{
                            backgroundColor: '#1e293b',
                            border: '1px solid #475569',
                            borderRadius: '8px',
                            color: '#f1f5f9',
                            fontSize: '12px',
                          }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="py-8 text-center text-sm text-slate-500">Aucune anomalie.</p>
                )}
                <div className="mt-2 flex justify-center gap-4 text-xs">
                  {pieData.map((d) => (
                    <span key={d.name} className="flex items-center gap-1">
                      <span className="h-2.5 w-2.5 rounded" style={{ backgroundColor: d.color }} />
                      {d.name}: {d.value}
                    </span>
                  ))}
                </div>
              </div>

              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                  Heat map par zone
                </h3>
                <div className="max-h-64 overflow-y-auto space-y-1">
                  {Object.entries(zoneCounts)
                    .sort((a, b) => b[1] - a[1])
                    .map(([z, count]) => (
                      <div
                        key={z}
                        className="flex items-center justify-between rounded border border-slate-700/50 px-3 py-1.5 text-xs"
                      >
                        <span className="text-slate-300">{z}</span>
                        <span className="font-mono text-slate-400">{count}</span>
                      </div>
                    ))}
                  {Object.keys(zoneCounts).length === 0 && (
                    <p className="py-4 text-center text-sm text-slate-500">Aucune zone.</p>
                  )}
                </div>
              </div>
            </section>

            <section aria-label="Chronologie" className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">Chronologie</h3>
              {Object.keys(timeline).length > 0 ? (
                <div className="max-h-80 overflow-y-auto space-y-3">
                  {Object.entries(timeline)
                    .sort((a, b) => b[0].localeCompare(a[0]))
                    .map(([hour, items]) => (
                      <div key={hour}>
                        <p className="mb-1 text-xs font-medium text-slate-400">{formatDateTime(hour + 'Z')}</p>
                        <div className="space-y-1">
                          {items.map((a) => (
                            <div
                              key={a.id}
                              className="flex items-start justify-between rounded border border-slate-700/50 bg-slate-800/50 px-3 py-2"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <span
                                    className={`inline-block shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${severityBadgeClass(a.severity)}`}
                                  >
                                    {a.severity}
                                  </span>
                                  <span className="truncate text-xs font-medium text-white">
                                    {a.zone_name || a.zone_id} · {a.pollutant}
                                  </span>
                                </div>
                                <p className="mt-0.5 text-[11px] text-slate-400">
                                  {a.type} — {a.detected_value?.toFixed(2) ?? '?'} / {a.threshold?.toFixed(2) ?? '?'}
                                </p>
                              </div>
                              <span className="shrink-0 text-[11px] text-slate-500">
                                {formatRelative(a.detected_at)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500">Aucune anomalie.</p>
              )}
            </section>

            <section aria-label="Tableau des anomalies">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-semibold uppercase text-slate-500">
                  Anomalies ({total})
                </h2>
                <select
                  value={pageSize}
                  onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
                  className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-xs text-slate-200"
                >
                  {PAGE_SIZES.map((s) => (
                    <option key={s} value={s}>{s} / page</option>
                  ))}
                </select>
              </div>

              <div className="overflow-x-auto rounded-xl border border-slate-700">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-700 bg-slate-800 text-slate-400">
                      <SortableTh active={sortKey === 'zone_id'} dir={sortDir} onClick={() => handleSort('zone_id')}>
                        Zone
                      </SortableTh>
                      <SortableTh active={sortKey === 'type'} dir={sortDir} onClick={() => handleSort('type')}>
                        Type
                      </SortableTh>
                      <SortableTh active={sortKey === 'pollutant'} dir={sortDir} onClick={() => handleSort('pollutant')}>
                        Polluant
                      </SortableTh>
                      <SortableTh active={sortKey === 'severity'} dir={sortDir} onClick={() => handleSort('severity')}>
                        Sévérité
                      </SortableTh>
                      <SortableTh active={sortKey === 'detected_value'} dir={sortDir} onClick={() => handleSort('detected_value')}>
                        Valeur
                      </SortableTh>
                      <SortableTh active={sortKey === 'threshold'} dir={sortDir} onClick={() => handleSort('threshold')}>
                        Seuil
                      </SortableTh>
                      <SortableTh active={sortKey === 'detected_at'} dir={sortDir} onClick={() => handleSort('detected_at')}>
                        Date
                      </SortableTh>
                      <SortableTh active={sortKey === 'sensor_id'} dir={sortDir} onClick={() => handleSort('sensor_id')}>
                        Capteur
                      </SortableTh>
                      <th className="px-3 py-2 font-medium">Détails</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedAnomalies.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="px-3 py-12 text-center text-slate-500">
                          Aucune anomalie trouvée.
                        </td>
                      </tr>
                    ) : (
                      sortedAnomalies.map((a) => (
                        <tr key={a.id} className="border-b border-slate-800 hover:bg-slate-800/50">
                          <td className="px-3 py-2 text-slate-300">{a.zone_name || a.zone_id}</td>
                          <td className="px-3 py-2 text-slate-400">{a.type}</td>
                          <td className="px-3 py-2 text-slate-400">{a.pollutant}</td>
                          <td className="px-3 py-2">
                            <span
                              className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${severityBadgeClass(a.severity)}`}
                            >
                              {a.severity}
                            </span>
                          </td>
                          <td className="px-3 py-2 font-mono text-slate-400">{a.detected_value?.toFixed(2) ?? '?'}</td>
                          <td className="px-3 py-2 font-mono text-slate-400">{a.threshold?.toFixed(2) ?? '?'}</td>
                          <td className="px-3 py-2 text-slate-400">{formatDateTime(a.detected_at)}</td>
                          <td className="px-3 py-2 font-mono text-slate-400">{a.sensor_id || '—'}</td>
                          <td className="px-3 py-2">
                            <button
                              onClick={() => toggleExpand(a.id)}
                              className="text-slate-400 hover:text-white text-xs"
                            >
                              {expanded.has(a.id) ? '−' : '+'}
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
                {sortedAnomalies.map((a) =>
                  expanded.has(a.id) ? (
                    <div
                      key={`detail-${a.id}`}
                      className="border-t border-slate-700 bg-slate-800/50 px-4 py-3 text-xs text-slate-400 space-y-1"
                    >
                      <p>
                        <span className="text-slate-500">Score anomalie :</span>{' '}
                        {a.anomaly_score != null ? a.anomaly_score.toFixed(4) : '—'}
                      </p>
                      <p>
                        <span className="text-slate-500">Durée :</span>{' '}
                        {a.duration_minutes != null ? `${a.duration_minutes} min` : '—'}
                      </p>
                      <p>
                        <span className="text-slate-500">Alert ID :</span>{' '}
                        {a.alert_id != null ? a.alert_id : '—'}
                      </p>
                      {a.alert_message && (
                        <p>
                          <span className="text-slate-500">Message :</span> {a.alert_message}
                        </p>
                      )}
                      <p>
                        <span className="text-slate-500">Détecté le :</span> {formatDateTime(a.detected_at)}
                      </p>
                      <p>
                        <span className="text-slate-500">Traité :</span>{' '}
                        {a.handled ? 'Oui' : 'Non'}
                      </p>
                    </div>
                  ) : null,
                )}
              </div>

              <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
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
            </section>
          </>
        )}

        {!data && !isLoading && !isError && (
          <p className="py-12 text-center text-sm text-slate-500">
            Utilisez les filtres pour rechercher des anomalies.
          </p>
        )}
      </main>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className="text-xs text-slate-400">{label}</p>
    </div>
  );
}

function SortableTh({
  active,
  dir,
  onClick,
  children,
}: {
  active: boolean;
  dir: 'asc' | 'desc';
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <th className="px-3 py-2 font-medium cursor-pointer select-none hover:text-white" onClick={onClick}>
      {children} {active && (dir === 'asc' ? '\u2191' : '\u2193')}
    </th>
  );
}
