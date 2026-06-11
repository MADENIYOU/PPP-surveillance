import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import {
  useCalibrationDrift,
  useCalibrationHistory,
  useSensors,
} from '../hooks/useApi';
import { formatDateTime } from '../lib/dateUtils';
import type { CalibrationRecord } from '../types/api';

const DRIFT_HOURS_OPTIONS = [
  { value: 24, label: 'Last 24h' },
  { value: 72, label: 'Last 3d' },
  { value: 168, label: 'Last 7d' },
  { value: 720, label: 'Last 30d' },
];

export function CalibrationPage() {
  const { data: sensorsData, isLoading: sensorsLoading } = useSensors();
  const {
    data: historyData,
    isLoading: historyLoading,
    isError: historyError,
  } = useCalibrationHistory({ limit: 200 });
  const {
    data: driftData,
    isLoading: driftLoading,
    isError: driftError,
  } = useCalibrationDrift({ hours: 168 });

  const [driftHours, setDriftHours] = useState(168);
  const [selectedSensor, setSelectedSensor] = useState<string | null>(null);
  const [comparisonSensors, setComparisonSensors] = useState<string[]>([]);

  // Fetch drift with selected hours via re-triggering hook
  const {
    data: driftFiltered,
    isLoading: driftFilteredLoading,
    isError: driftFilteredError,
  } = useCalibrationDrift({ hours: driftHours });

  const sensors = sensorsData?.sensors ?? [];
  const records: CalibrationRecord[] = historyData?.records ?? [];
  const drifts = driftFiltered?.drifts ?? driftData?.drifts ?? [];

  const sensorIds = useMemo(
    () => [...new Set(records.map((r) => r.sensor_id))].sort(),
    [records],
  );

  const filteredRecords = useMemo(
    () =>
      selectedSensor
        ? records.filter((r) => r.sensor_id === selectedSensor)
        : records,
    [records, selectedSensor],
  );

  // Per-sensor drift chart data
  const driftChartData = useMemo(() => {
    if (!selectedSensor) return [];
    const sensorDrifts = drifts
      .filter((d) => d.sensor_id === selectedSensor)
      .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
    return sensorDrifts.map((d) => ({
      ts: formatDateTime(d.timestamp),
      drift: d.drift_pct,
    }));
  }, [drifts, selectedSensor]);

  // Cross-sensor comparison data (R² over time for selected sensors)
  const comparisonData = useMemo(() => {
    const sensorsToComp: string[] = comparisonSensors.length > 0
      ? comparisonSensors
      : selectedSensor ? [selectedSensor] : [];
    if (sensorsToComp.length === 0) return [];
    const bySensor: Record<string, CalibrationRecord[]> = {};
    for (const r of records) {
      if (sensorsToComp.includes(r.sensor_id)) {
        if (!bySensor[r.sensor_id]) bySensor[r.sensor_id] = [];
        bySensor[r.sensor_id].push(r);
      }
    }
    const allTimestamps = [...new Set(
      Object.values(bySensor).flat().map((r) => formatDateTime(r.calibrated_at)),
    )].slice(0, 50);
    return allTimestamps.map((ts) => {
      const point: Record<string, string | number | null> = { ts };
      for (const sid of sensorsToComp) {
        const rec = bySensor[sid]?.find((r) => formatDateTime(r.calibrated_at) === ts);
        point[sid] = rec?.r2_score ?? null;
      }
      return point;
    });
  }, [records, comparisonSensors, selectedSensor]);

  // Drift rate histogram
  const driftHistogram = useMemo(() => {
    const buckets: Record<string, number> = {};
    const allDrifts = drifts.filter((d) => d.drift_pct > 0);
    for (const d of allDrifts) {
      if (d.drift_pct <= 1) buckets['0-1%'] = (buckets['0-1%'] ?? 0) + 1;
      else if (d.drift_pct <= 2) buckets['1-2%'] = (buckets['1-2%'] ?? 0) + 1;
      else if (d.drift_pct <= 3) buckets['2-3%'] = (buckets['2-3%'] ?? 0) + 1;
      else if (d.drift_pct <= 5) buckets['3-5%'] = (buckets['3-5%'] ?? 0) + 1;
      else if (d.drift_pct <= 10) buckets['5-10%'] = (buckets['5-10%'] ?? 0) + 1;
      else buckets['10%+'] = (buckets['10%+'] ?? 0) + 1;
    }
    return Object.entries(buckets)
      .map(([range, count]) => ({ range, count }))
      .sort((a, b) => {
        const order = ['0-1%', '1-2%', '2-3%', '3-5%', '5-10%', '10%+'];
        return order.indexOf(a.range) - order.indexOf(b.range);
      });
  }, [drifts]);

  const isLoading = sensorsLoading || historyLoading || driftLoading || driftFilteredLoading;
  const isDriftError = driftError || driftFilteredError;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={historyData?.meta.generated_at ?? null} />} />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <h1 className="text-xl font-bold text-white">Calibration Dashboard</h1>

        {isLoading && <Spinner label="Chargement des données de calibration…" />}

        {!isLoading && (
          <>
            {/* Sensor Selector */}
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-700 bg-slate-800 p-3">
              <span className="text-xs text-slate-400">Filter by sensor:</span>
              <select
                className="rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
                value={selectedSensor ?? ''}
                onChange={(e) => setSelectedSensor(e.target.value || null)}
              >
                <option value="">All Sensors ({sensorIds.length})</option>
                {sensorIds.map((sid) => (
                  <option key={sid} value={sid}>{sid}</option>
                ))}
              </select>
              {selectedSensor && (
                <button
                  className="rounded bg-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-600"
                  onClick={() => setSelectedSensor(null)}
                >
                  Clear
                </button>
              )}
            </div>

            {/* Calibration Event Log */}
            <section className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h2 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Calibration Event Log
              </h2>
              {historyError ? (
                <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
                  Impossible de charger l'historique de calibration.
                </p>
              ) : filteredRecords.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  Aucun événement de calibration trouvé.
                </p>
              ) : (
                <div className="max-h-80 overflow-y-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-700 text-slate-500">
                        <th className="pb-2 pr-3 font-medium">Date</th>
                        <th className="pb-2 pr-3 font-medium">Sensor</th>
                        <th className="pb-2 pr-3 font-medium">Zone</th>
                        <th className="pb-2 pr-3 font-medium">R²</th>
                        <th className="pb-2 pr-3 font-medium">RMSE</th>
                        <th className="pb-2 pr-3 font-medium">Samples</th>
                        <th className="pb-2 font-medium">Coefficients</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredRecords.slice(0, 100).map((r) => (
                        <tr key={r.id} className="border-b border-slate-800">
                          <td className="py-2.5 pr-3 text-slate-400">
                            {formatDateTime(r.calibrated_at)}
                          </td>
                          <td className="py-2.5 pr-3 font-mono text-white">{r.sensor_id}</td>
                          <td className="py-2.5 pr-3 text-slate-400">{r.zone_id}</td>
                          <td className="py-2.5 pr-3">
                            <span
                              className={
                                r.r2_score >= 0.8
                                  ? 'text-green-400'
                                  : r.r2_score >= 0.5
                                    ? 'text-yellow-400'
                                    : 'text-red-400'
                              }
                            >
                              {r.r2_score.toFixed(3)}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 font-mono text-slate-400">
                            {r.rmse.toFixed(3)}
                          </td>
                          <td className="py-2.5 pr-3 text-slate-400">{r.n_samples}</td>
                          <td className="py-2.5">
                            <code className="text-[10px] text-slate-500">
                              {Object.entries(r.new_coefficients)
                                .slice(0, 3)
                                .map(([k, v]) => `${k}:${Number(v).toFixed(2)}`)
                                .join(', ')}
                              {Object.keys(r.new_coefficients).length > 3 ? '…' : ''}
                            </code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* Per-Sensor Calibration Drift Chart */}
            <section className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-xs font-semibold uppercase text-slate-500">
                  Calibration Drift Over Time
                  {selectedSensor ? ` — ${selectedSensor}` : ''}
                </h2>
                <div className="flex gap-1">
                  {DRIFT_HOURS_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      className={`rounded px-2 py-0.5 text-[10px] ${
                        driftHours === opt.value
                          ? 'bg-slate-600 text-white'
                          : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                      }`}
                      onClick={() => setDriftHours(opt.value)}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              {isDriftError ? (
                <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
                  Impossible de charger les données de dérive.
                </p>
              ) : !selectedSensor ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  Select a sensor above to view its calibration drift.
                </p>
              ) : driftChartData.length < 2 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  Not enough data points for drift analysis.
                </p>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={driftChartData}>
                      <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="ts"
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        interval="preserveStartEnd"
                      />
                      <YAxis
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        unit="%"
                        width={45}
                      />
                      <RechartsTooltip
                        contentStyle={{
                          backgroundColor: '#1e293b',
                          border: '1px solid #475569',
                          borderRadius: '8px',
                          color: '#f1f5f9',
                          fontSize: '12px',
                        }}
                        formatter={(value: number) => [`${value.toFixed(2)}%`, 'Drift']}
                      />
                      <Line
                        type="monotone"
                        dataKey="drift"
                        stroke="#f59e0b"
                        strokeWidth={2}
                        dot={{ r: 3, fill: '#f59e0b' }}
                        name="Drift %"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>

            {/* Cross-Sensor Comparison */}
            <section className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-xs font-semibold uppercase text-slate-500">
                  Cross-Sensor R² Comparison
                </h2>
                <div className="flex flex-wrap gap-1">
                  {sensorIds.slice(0, 12).map((sid) => (
                    <button
                      key={sid}
                      className={`rounded px-2 py-0.5 text-[10px] ${
                        comparisonSensors.includes(sid)
                          ? 'bg-indigo-600 text-white'
                          : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                      }`}
                      onClick={() =>
                        setComparisonSensors((prev) =>
                          prev.includes(sid)
                            ? prev.filter((s) => s !== sid)
                            : [...prev, sid].slice(0, 5),
                        )
                      }
                    >
                      {sid}
                    </button>
                  ))}
                  {comparisonSensors.length > 0 && (
                    <button
                      className="rounded bg-slate-700 px-2 py-0.5 text-[10px] text-slate-300"
                      onClick={() => setComparisonSensors([])}
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
              {comparisonSensors.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  Select 1–5 sensors above to compare their calibration R² curves.
                </p>
              ) : comparisonData.length < 2 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  Not enough shared data points for comparison.
                </p>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={comparisonData}>
                      <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="ts"
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        interval="preserveStartEnd"
                      />
                      <YAxis
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                        domain={[0, 1]}
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
                      <Legend
                        wrapperStyle={{ fontSize: '10px', color: '#94a3b8' }}
                      />
                      {comparisonSensors.map((sid, i) => {
                        const colors = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6'];
                        return (
                          <Line
                            key={sid}
                            type="monotone"
                            dataKey={sid}
                            stroke={colors[i % colors.length]}
                            strokeWidth={1.5}
                            dot={false}
                            connectNulls
                            name={sid}
                          />
                        );
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>

            {/* Drift Rate Histogram */}
            <section className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h2 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Drift Rate Distribution
              </h2>
              {isDriftError ? (
                <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
                  Impossible de charger la distribution de dérive.
                </p>
              ) : driftHistogram.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  No drift data available.
                </p>
              ) : (
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={driftHistogram}>
                      <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="range"
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
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
                        formatter={(value: number) => [`${value} sensors`, 'Count']}
                      />
                      <Bar dataKey="count" fill="#22c55e" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </section>

            {/* Sensor Summary Table */}
            <section className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h2 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Sensor Calibration Summary
              </h2>
              {sensors.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  No sensors available.
                </p>
              ) : (
                <div className="max-h-80 overflow-y-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-700 text-slate-500">
                        <th className="pb-2 pr-3 font-medium">Sensor</th>
                        <th className="pb-2 pr-3 font-medium">Zone</th>
                        <th className="pb-2 pr-3 font-medium">Last Calibration</th>
                        <th className="pb-2 pr-3 font-medium">Best R²</th>
                        <th className="pb-2 pr-3 font-medium">Events</th>
                        <th className="pb-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sensors.map((s) => {
                        const sensorRecords = records.filter((r) => r.sensor_id === s.sensor_id);
                        const lastCal = sensorRecords[0];
                        const bestR2 = sensorRecords.reduce(
                          (max, r) => Math.max(max, r.r2_score),
                          0,
                        );
                        return (
                          <tr key={s.sensor_id} className="border-b border-slate-800">
                            <td className="py-2.5 pr-3 font-mono text-white">
                              <button
                                className="hover:underline"
                                onClick={() => setSelectedSensor(s.sensor_id)}
                              >
                                {s.sensor_id}
                              </button>
                            </td>
                            <td className="py-2.5 pr-3 text-slate-400">{s.zone_id}</td>
                            <td className="py-2.5 pr-3 text-slate-400">
                              {lastCal ? formatDateTime(lastCal.calibrated_at) : '—'}
                            </td>
                            <td className="py-2.5 pr-3">
                              {sensorRecords.length > 0 ? (
                                <span
                                  className={
                                    bestR2 >= 0.8
                                      ? 'text-green-400'
                                      : bestR2 >= 0.5
                                        ? 'text-yellow-400'
                                        : 'text-red-400'
                                  }
                                >
                                  {bestR2.toFixed(3)}
                                </span>
                              ) : (
                                <span className="text-slate-600">—</span>
                              )}
                            </td>
                            <td className="py-2.5 pr-3 text-slate-400">
                              {sensorRecords.length}
                            </td>
                            <td className="py-2.5">
                              <span
                                className={`inline-block h-2 w-2 rounded-full ${
                                  s.status === 'active' ? 'bg-green-500' : 'bg-red-500'
                                }`}
                              />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
