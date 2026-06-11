import { useCallback, useMemo, useRef, useState } from 'react';
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import { usePipelineLogs, usePipelineMetrics } from '../hooks/useApi';
import { formatDateTime } from '../lib/dateUtils';
import type { LogEntry } from '../types/api';

const SERVICE_OPTIONS = [
  { value: '', label: 'All Services' },
  { value: 'ingestion', label: 'Ingestion' },
  { value: 'calibration', label: 'Calibration' },
  { value: 'anomaly_detector', label: 'Anomaly Detector' },
  { value: 'feature_engineering', label: 'Feature Engineering' },
  { value: 'predictions', label: 'Predictions' },
  { value: 'kriging', label: 'Kriging' },
  { value: 'nlp_pipeline', label: 'NLP Pipeline' },
  { value: 'monitoring', label: 'Monitoring' },
  { value: 'retraining', label: 'Retraining' },
];

const LEVEL_OPTIONS = [
  { value: '', label: 'All Levels' },
  { value: 'DEBUG', label: 'DEBUG' },
  { value: 'INFO', label: 'INFO' },
  { value: 'WARNING', label: 'WARNING' },
  { value: 'ERROR', label: 'ERROR' },
];

function levelBadgeStyle(level: string): string {
  const map: Record<string, string> = {
    DEBUG: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
    INFO: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    WARNING: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    ERROR: 'bg-red-500/20 text-red-400 border-red-500/30',
  };
  return map[level] ?? map.INFO;
}

function serviceStyle(service: string): string {
  const map: Record<string, string> = {
    ingestion: 'text-emerald-400',
    calibration: 'text-cyan-400',
    anomaly_detector: 'text-red-400',
    feature_engineering: 'text-purple-400',
    predictions: 'text-orange-400',
    kriging: 'text-indigo-400',
    nlp_pipeline: 'text-pink-400',
    monitoring: 'text-teal-400',
    retraining: 'text-amber-400',
  };
  return map[service] ?? 'text-slate-400';
}

function exportLogs(logs: LogEntry[], format: 'json' | 'csv') {
  if (format === 'json') {
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: 'application/json' });
    downloadBlob(blob, `pipeline-logs-${Date.now()}.json`);
  } else {
    const header = 'timestamp,service,level,message\n';
    const rows = logs
      .map((l) =>
        [
          l.timestamp,
          l.service,
          l.level,
          `"${(l.message ?? '').replace(/"/g, '""')}"`,
        ].join(','),
      )
      .join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    downloadBlob(blob, `pipeline-logs-${Date.now()}.csv`);
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function LogsPage() {
  const [service, setService] = useState('');
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);

  const { data: logsData, isLoading, isError } = usePipelineLogs({
    service: service || undefined,
    level: level || undefined,
    search: search || undefined,
    limit: 200,
  });
  const { data: metrics } = usePipelineMetrics();

  const logs = useMemo(() => (paused ? [] : logsData?.logs ?? []), [logsData, paused]);
  const allLogs = logsData?.logs ?? [];

  // Compute stats from current visible logs
  const stats = useMemo(() => {
    const levelCounts: Record<string, number> = { DEBUG: 0, INFO: 0, WARNING: 0, ERROR: 0 };
    const serviceCounts: Record<string, number> = {};
    for (const l of allLogs) {
      levelCounts[l.level] = (levelCounts[l.level] ?? 0) + 1;
      serviceCounts[l.service] = (serviceCounts[l.service] ?? 0) + 1;
    }
    const pieData = Object.entries(levelCounts)
      .filter(([, v]) => v > 0)
      .map(([name, value]) => ({ name, value }));
    const barData = Object.entries(serviceCounts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 10)
      .map(([name, value]) => ({ name, value }));
    const errorRate =
      allLogs.length > 0
        ? ((levelCounts.ERROR ?? 0) / allLogs.length) * 100
        : 0;
    return { pieData, barData, errorRate, total: allLogs.length };
  }, [allLogs]);

  const clearFilters = useCallback(() => {
    setService('');
    setLevel('');
    setSearch('');
  }, []);

  const allServices = useMemo(
    () => [...new Set(allLogs.map((l) => l.service))].sort(),
    [allLogs],
  );

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={metrics?.generated_at ?? null} />} />

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">Pipeline Log Stream</h1>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">
              {logsData?.meta.total ?? 0} entries
            </span>
            <button
              className={`rounded px-3 py-1.5 text-xs font-medium ${
                paused ? 'bg-blue-600 text-white' : 'bg-yellow-600 text-white'
              }`}
              onClick={() => setPaused((p) => !p)}
            >
              {paused ? 'Resume' : 'Pause'}
            </button>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-700 bg-slate-800 p-3">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] uppercase text-slate-500">Service</span>
            <select
              className="rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={service}
              onChange={(e) => setService(e.target.value)}
            >
              {SERVICE_OPTIONS.filter(
                (o) => !o.value || allServices.includes(o.value),
              ).map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[10px] uppercase text-slate-500">Level</span>
            <select
              className="rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
            >
              {LEVEL_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-1 flex-col gap-1">
            <span className="text-[10px] uppercase text-slate-500">Search</span>
            <input
              type="text"
              placeholder="Search in messages…"
              className="rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
                className="rounded"
              />
              Auto-scroll
            </label>
          </div>
          <button
            className="rounded bg-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-600"
            onClick={clearFilters}
          >
            Clear
          </button>
          <div className="ml-auto flex gap-2">
            <button
              className="rounded border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
              onClick={() => exportLogs(allLogs, 'json')}
            >
              Export JSON
            </button>
            <button
              className="rounded border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
              onClick={() => exportLogs(allLogs, 'csv')}
            >
              Export CSV
            </button>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          {/* Log List */}
          <div className="lg:col-span-2">
            {isLoading && <Spinner label="Chargement des logs…" />}
            {isError && (
              <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
                Impossible de charger les logs du pipeline.
              </p>
            )}
            {!isLoading && !isError && (
              <div
                ref={listRef}
                className="max-h-[70vh] overflow-y-auto rounded-xl border border-slate-700 bg-slate-800"
              >
                {logs.length === 0 && !paused && (
                  <p className="p-6 text-center text-sm text-slate-500">
                    Aucun log trouvé.
                  </p>
                )}
                {paused && logsData && logsData.logs.length > 0 && (
                  <p className="border-b border-slate-700 bg-yellow-900/30 px-4 py-2 text-xs text-yellow-400">
                    Stream paused — {logsData.logs.length} buffered entries. Click Resume to see latest.
                  </p>
                )}
                {logs.map((entry) => (
                  <div
                    key={entry.id}
                    className="border-b border-slate-700/50 px-4 py-2.5 transition-colors hover:bg-slate-700/30"
                  >
                    <div
                      className="flex cursor-pointer items-start gap-3"
                      onClick={() =>
                        setExpandedId(expandedId === entry.id ? null : entry.id)
                      }
                    >
                      <span className="mt-0.5 shrink-0 text-[10px] text-slate-500">
                        {formatDateTime(entry.timestamp)}
                      </span>
                      <span
                        className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${levelBadgeStyle(entry.level)}`}
                      >
                        {entry.level}
                      </span>
                      <span className={`shrink-0 text-xs font-medium ${serviceStyle(entry.service)}`}>
                        {entry.service}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-xs text-slate-300">
                        {entry.message}
                      </span>
                      <span className="shrink-0 text-[10px] text-slate-600">
                        {expandedId === entry.id ? '▲' : '▼'}
                      </span>
                    </div>
                    {expandedId === entry.id && entry.raw && (
                      <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-3 text-[10px] text-slate-400">
                        {JSON.stringify(entry.raw, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Stats Sidebar */}
          <div className="space-y-4">
            {/* Log Counts Pie */}
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Log Levels
              </h3>
              {stats.pieData.length > 0 ? (
                <>
                  <div className="h-40">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={stats.pieData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={60}
                          innerRadius={30}
                        >
                          {stats.pieData.map((entry) => (
                            <Cell
                              key={entry.name}
                              fill={
                                entry.name === 'ERROR'
                                  ? '#ef4444'
                                  : entry.name === 'WARNING'
                                    ? '#eab308'
                                    : entry.name === 'INFO'
                                      ? '#3b82f6'
                                      : '#64748b'
                              }
                            />
                          ))}
                        </Pie>
                        <Tooltip
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
                  <div className="mt-2 space-y-1">
                    {stats.pieData.map((d) => (
                      <div key={d.name} className="flex items-center justify-between text-xs">
                        <span className={`${levelBadgeStyle(d.name)} rounded border px-1.5 py-0.5`}>
                          {d.name}
                        </span>
                        <span className="text-slate-400">{d.value}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="py-6 text-center text-xs text-slate-500">No data</p>
              )}
            </div>

            {/* Per-Service Bar Chart */}
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Logs by Service
              </h3>
              {stats.barData.length > 0 ? (
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={stats.barData} layout="vertical" margin={{ left: 80 }}>
                      <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                      <YAxis
                        type="category"
                        dataKey="name"
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        width={75}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#1e293b',
                          border: '1px solid #475569',
                          borderRadius: '8px',
                          color: '#f1f5f9',
                          fontSize: '12px',
                        }}
                      />
                      <Bar dataKey="value" fill="#6366f1" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="py-6 text-center text-xs text-slate-500">No data</p>
              )}
            </div>

            {/* Error Rate Trend */}
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Error Rate
              </h3>
              <p className="text-2xl font-bold text-red-400">
                {stats.errorRate.toFixed(1)}%
              </p>
              <p className="text-xs text-slate-500">
                {(stats.pieData.find((d) => d.name === 'ERROR')?.value ?? 0)} errors / {stats.total} total
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
