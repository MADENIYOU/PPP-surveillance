import { Link, useParams } from 'react-router-dom';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
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
import { useWorkerDetail } from '../hooks/useApi';
import { formatDateTime } from '../lib/dateUtils';
import type {
  AnomalyDetectorDetail,
  CalibrationWorkerDetail,
  IngestionWorkerDetail,
} from '../types/api';

const LEVEL_COLORS: Record<string, string> = {
  critical: '#ef4444',
  danger: '#f97316',
  warning: '#eab308',
  info: '#3b82f6',
  unclassified: '#64748b',
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#ef4444',
  danger: '#f97316',
  warning: '#eab308',
  info: '#3b82f6',
};

function StatCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
      <p className="text-2xl font-bold text-white" style={color ? { color } : undefined}>
        {value}
      </p>
      <p className="text-xs text-slate-400">{label}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
      <h3 className="mb-4 text-xs font-semibold uppercase text-slate-500">{title}</h3>
      {children}
    </div>
  );
}

function ChartTooltip() {
  return (
    <Tooltip
      contentStyle={{
        backgroundColor: '#1e293b',
        border: '1px solid #475569',
        borderRadius: '8px',
        color: '#f1f5f9',
        fontSize: '12px',
      }}
    />
  );
}

/* ── Ingestion Worker ─────────────────────────────────────────────────────── */

function IngestionView({ data }: { data: IngestionWorkerDetail }) {
  const totalMsg = data.messages_per_min.reduce((s, p) => s + p.count, 0);
  const avgPerMin = data.messages_per_min.length
    ? Math.round(totalMsg / data.messages_per_min.length)
    : 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard label="Msg/min (moy)" value={avgPerMin} />
        <StatCard
          label="Buffer utilisé"
          value={`${data.buffer_utilization_pct}%`}
          color={data.buffer_utilization_pct > 80 ? '#ef4444' : '#22c55e'}
        />
        <StatCard
          label="Messages rejetés (stale)"
          value={`${data.stale_pct}%`}
          color={data.stale_pct > 10 ? '#f97316' : '#22c55e'}
        />
        <StatCard label="Dead letter queue" value={data.dead_letter_count} />
        <StatCard label="Reconnexions MQTT" value={data.total_mqtt_reconnects} />
      </div>

      {/* Throughput chart */}
      <Section title="Débit (msg/min) — dernière heure">
        {data.messages_per_min.length > 0 ? (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data.messages_per_min}>
                <defs>
                  <linearGradient id="throughputGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22c55e" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                <XAxis dataKey="minute" tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => new Date(v).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })} tickLine={false} axisLine={false} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} width={35} />
                <ChartTooltip />
                <Area type="monotone" dataKey="count" stroke="#22c55e" strokeWidth={2} fill="url(#throughputGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucune donnée de débit.</p>
        )}
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Per-sensor distribution table */}
        <Section title="Distribution par capteur (dernière heure)">
          {data.per_sensor.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Capteur</th>
                    <th className="pb-2 pr-2 font-medium">Zone</th>
                    <th className="pb-2 pr-2 font-medium">Messages</th>
                    <th className="pb-2 font-medium">Dernier</th>
                  </tr>
                </thead>
                <tbody>
                  {data.per_sensor.map((s) => (
                    <tr key={s.sensor_id} className="border-b border-slate-800">
                      <td className="py-2 pr-2 font-mono text-white">{s.sensor_id}</td>
                      <td className="py-2 pr-2 text-slate-400">{s.zone_id}</td>
                      <td className="py-2 pr-2 text-slate-300">{s.messages_received}</td>
                      <td className="py-2 text-slate-400">{s.last_message ? formatDateTime(s.last_message) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucun capteur actif.</p>
          )}
        </Section>

        {/* MQTT status */}
        <Section title="Statut MQTT">
          {data.mqtt_status.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Capteur</th>
                    <th className="pb-2 pr-2 font-medium">Statut</th>
                    <th className="pb-2 pr-2 font-medium">Reconnexions</th>
                    <th className="pb-2 font-medium">Vu</th>
                  </tr>
                </thead>
                <tbody>
                  {data.mqtt_status.map((s) => (
                    <tr key={s.sensor_id} className="border-b border-slate-800">
                      <td className="py-2 pr-2 font-mono text-white">{s.sensor_id}</td>
                      <td className="py-2 pr-2">
                        <span className={`inline-block h-2 w-2 rounded-full ${s.status === 'active' ? 'bg-green-500' : 'bg-red-500'}`} />
                        <span className="ml-1.5 text-slate-400">{s.status}</span>
                      </td>
                      <td className="py-2 pr-2">
                        <span className={s.mqtt_reconnects > 5 ? 'text-orange-400' : 'text-slate-300'}>
                          {s.mqtt_reconnects}
                        </span>
                      </td>
                      <td className="py-2 text-slate-400">{s.last_seen ? formatDateTime(s.last_seen) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucun capteur MQTT.</p>
          )}
        </Section>
      </div>

      {/* Dead letter entries */}
      <Section title="Messages rejetés (Dead Letter) — dernière heure">
        {data.dead_letter_entries.length > 0 ? (
          <div className="max-h-48 overflow-y-auto space-y-1">
            {data.dead_letter_entries.map((e, i) => (
              <div key={i} className="rounded-lg border border-slate-700/50 bg-slate-800/50 px-3 py-2 flex items-center justify-between text-xs">
                <span className="font-mono text-slate-300">{e.sensor_id}</span>
                <span className="text-slate-400">{formatDateTime(e.timestamp)}</span>
                <span className="text-orange-400 capitalize">{e.reason}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucune entrée dead letter.</p>
        )}
      </Section>
    </div>
  );
}

/* ── Calibration Worker ────────────────────────────────────────────────────── */

function CalibrationView({ data }: { data: CalibrationWorkerDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard
          label="Taux de succès"
          value={`${data.success_rate_pct}%`}
          color={data.success_rate_pct >= 90 ? '#22c55e' : data.success_rate_pct >= 70 ? '#eab308' : '#ef4444'}
        />
        <StatCard label="Fallbacks (linéaire)" value={data.fallback_count} sub={`${data.fallback_pct}%`} />
        <StatCard label="Kalman gain moy" value={data.kalman_effectiveness.avg_kalman_gain?.toFixed(4) ?? '—'} />
        <StatCard label="Réduction incertitude" value={data.kalman_effectiveness.uncertainty_reduction_pct != null ? `${data.kalman_effectiveness.uncertainty_reduction_pct}%` : '—'} />
        <StatCard label="Capteurs actifs" value={data.active_sensors.length} />
      </div>

      {/* Model info */}
      {data.model_info && (
        <Section title="Modèle de calibration">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <p className="text-slate-500">Modèle</p>
              <p className="font-medium text-white">{data.model_info.name}</p>
            </div>
            <div>
              <p className="text-slate-500">Version</p>
              <p className="font-mono text-white">{data.model_info.version}</p>
            </div>
            <div>
              <p className="text-slate-500">Dernier entraînement</p>
              <p className="text-white">{data.model_info.last_trained ? formatDateTime(data.model_info.last_trained) : '—'}</p>
            </div>
            <div>
              <p className="text-slate-500">R² / RMSE</p>
              <p className="text-white">
                {data.model_info.r2 != null ? data.model_info.r2.toFixed(3) : '—'}
                {' / '}
                {data.model_info.rmse != null ? data.model_info.rmse.toFixed(3) : '—'}
              </p>
            </div>
          </div>
          {data.model_info.features_used.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1">
              {data.model_info.features_used.map((f) => (
                <span key={f} className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">{f}</span>
              ))}
            </div>
          )}
        </Section>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Per-pollutant MAE */}
        <Section title="MAE par polluant">
          {data.per_pollutant_mae.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.per_pollutant_mae} layout="vertical">
                  <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                  <XAxis type="number" domain={[0, 1]} tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} />
                  <YAxis type="category" dataKey="pollutant" tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} width={40} />
                  <ChartTooltip />
                  <Bar dataKey="avg_r2" fill="#22c55e" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune donnée de calibration.</p>
          )}
        </Section>

        {/* Active sensors */}
        <Section title="Capteurs calibrés (24h)">
          {data.active_sensors.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Capteur</th>
                    <th className="pb-2 pr-2 font-medium">Zone</th>
                    <th className="pb-2 pr-2 font-medium">Calibrations</th>
                    <th className="pb-2 font-medium">Dernière</th>
                  </tr>
                </thead>
                <tbody>
                  {data.active_sensors.map((s) => (
                    <tr key={s.sensor_id} className="border-b border-slate-800">
                      <td className="py-2 pr-2 font-mono text-white">{s.sensor_id}</td>
                      <td className="py-2 pr-2 text-slate-400">{s.zone_id}</td>
                      <td className="py-2 pr-2 text-slate-300">{s.calibrations_count}</td>
                      <td className="py-2 text-slate-400">{formatDateTime(s.last_calibrated)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucun capteur calibré récemment.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

/* ── Anomaly Detector Worker ──────────────────────────────────────────────── */

function AnomalyDetectorView({ data }: { data: AnomalyDetectorDetail }) {
  const totalDetections = (data.detection_rate ?? []).reduce((s, p) => s + p.count, 0);
  const levelData = (data.level_distribution ?? []).map((l) => ({
    name: l.level,
    value: l.count,
    color: LEVEL_COLORS[l.level] || '#64748b',
  }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard label="Anomalies (24h)" value={totalDetections} />
        <StatCard
          label="Score moyen"
          value={data.model_health.mean_anomaly_score?.toFixed(4) ?? '—'}
        />
        <StatCard
          label="Contamination"
          value={data.model_health.contamination_rate != null ? `${(data.model_health.contamination_rate * 100).toFixed(1)}%` : '—'}
        />
        <StatCard
          label="LISTEN/NOTIFY"
          value={data.listen_status.active_listeners > 0 ? 'Actif' : 'Inactif'}
          sub={`${data.listen_status.active_listeners} listener(s)`}
          color={data.listen_status.active_listeners > 0 ? '#22c55e' : '#ef4444'}
        />
        <StatCard label="Violations structurelles" value={data.structural_violations.length} />
      </div>

      {/* Detection rate chart */}
      <Section title="Taux de détection par heure (24h)">
        {data.detection_rate.length > 0 ? (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.detection_rate}>
                <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                <XAxis dataKey="hour" tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => new Date(v).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })} tickLine={false} axisLine={false} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} width={35} />
                <ChartTooltip />
                <Bar dataKey="count" fill="#f97316" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucune détection.</p>
        )}
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Level distribution pie */}
        <Section title="Distribution par niveau">
          {levelData.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={levelData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                    {levelData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <ChartTooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune donnée.</p>
          )}
        </Section>

        {/* Per-zone heatmap (table) */}
        <Section title="Anomalies par zone">
          {data.per_zone_heatmap.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Zone</th>
                    <th className="pb-2 pr-2 font-medium">Anomalies</th>
                    <th className="pb-2 pr-2 font-medium">Score moy</th>
                    <th className="pb-2 font-medium">Score max</th>
                  </tr>
                </thead>
                <tbody>
                  {data.per_zone_heatmap.map((z) => (
                    <tr key={z.zone_id} className="border-b border-slate-800">
                      <td className="py-2 pr-2 text-white">{z.zone_id}</td>
                      <td className="py-2 pr-2 text-slate-300">{z.anomaly_count}</td>
                      <td className="py-2 pr-2 text-slate-400">{z.avg_score?.toFixed(3) ?? '—'}</td>
                      <td className="py-2 text-slate-400">{z.max_score?.toFixed(3) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune anomalie par zone.</p>
          )}
        </Section>
      </div>

      {/* Structural violations */}
      <Section title="Violations structurelles récentes">
        {data.structural_violations.length > 0 ? (
          <div className="max-h-48 overflow-y-auto space-y-1">
            {data.structural_violations.map((v) => (
              <div key={v.id} className="rounded-lg border border-slate-700/50 bg-slate-800/50 px-3 py-2.5 flex items-start justify-between text-xs">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-white">{v.zone_id}</span>
                    <span className="text-slate-400">{v.pollutant}</span>
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${SEVERITY_COLORS[v.severity] ? `bg-${v.severity === 'critical' ? 'red' : v.severity === 'danger' ? 'orange' : v.severity === 'warning' ? 'yellow' : 'blue'}-500/20 text-${v.severity === 'critical' ? 'red' : v.severity === 'danger' ? 'orange' : v.severity === 'warning' ? 'yellow' : 'blue'}-400 border-${v.severity === 'critical' ? 'red' : v.severity === 'danger' ? 'orange' : v.severity === 'warning' ? 'yellow' : 'blue'}-500/30` : ''}`}>
                      {v.severity}
                    </span>
                  </div>
                  <p className="mt-1 text-slate-500">
                    {v.type === 'stuck_sensor' ? 'Capteur bloqué' : 'Ratio invraisemblable'} · Valeur {v.detected_value} · {v.sensor_id}
                  </p>
                </div>
                <span className="text-slate-500 shrink-0">{formatDateTime(v.detected_at)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucune violation structurelle.</p>
        )}
      </Section>
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────────────── */

export function WorkerDetailPage() {
  const { name = '' } = useParams();
  const { data, isLoading, isError } = useWorkerDetail(name);

  const title = {
    ingestion: 'Worker — Ingestion',
    calibration: 'Worker — Calibration',
    anomaly_detector: 'Worker — Détecteur d’anomalies',
  }[name] || `Worker — ${name}`;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={data?.generated_at ?? null} />} />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <div className="flex items-center gap-4">
          <Link to="/pipeline" className="text-sm text-slate-400 hover:text-white transition-colors">
            ← Pipeline
          </Link>
          <h1 className="text-xl font-bold text-white">{title}</h1>
        </div>

        {isLoading && <Spinner label="Chargement du worker…" />}

        {isError && (
          <div className="rounded-xl border border-red-800 bg-red-900/30 p-6 text-center">
            <p className="text-sm text-red-400">
              Impossible de charger les détails du worker.
            </p>
          </div>
        )}

        {data && !isLoading && !isError && (
          <>
            {name === 'ingestion' && <IngestionView data={data as IngestionWorkerDetail} />}
            {name === 'calibration' && <CalibrationView data={data as CalibrationWorkerDetail} />}
            {name === 'anomaly_detector' && <AnomalyDetectorView data={data as AnomalyDetectorDetail} />}
          </>
        )}
      </main>
    </div>
  );
}
