import { Link, useParams } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import { useFlowDetail } from '../hooks/useApi';
import { formatDateTime } from '../lib/dateUtils';
import type {
  FeatureEngineeringDetail,
  PredictionsDetail,
  KrigingDetail,
  NlpPipelineDetail,
  MonitoringDetail,
  RetrainingDetail,
} from '../types/api';

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

/* ── Feature Engineering View ─────────────────────────────────────────────── */

function FeatureEngineeringView({ data }: { data: FeatureEngineeringDetail }) {
  const radarData = (data.per_zone_completeness ?? []).slice(0, 8).map((z) => ({
    zone: z.zone_id,
    completude: z.completeness_pct,
  }));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Couverture features" value={`${data.feature_coverage_pct}%`} color={data.feature_coverage_pct >= 80 ? '#22c55e' : '#eab308'} />
        <StatCard label="Total lignes" value={data.total_feature_rows.toLocaleString()} />
        <StatCard label="Dernière exécution" value={data.last_run ? formatDateTime(data.last_run) : '—'} />
        <StatCard label="Zones avec features" value={data.per_zone_completeness.length} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Per-zone completeness radar */}
        <Section title="Complétude par zone (radar)">
          {radarData.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#334155" />
                  <PolarAngleAxis dataKey="zone" tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <PolarRadiusAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 9 }} />
                  <Radar name="Complétude %" dataKey="completude" stroke="#22c55e" fill="#22c55e" fillOpacity={0.2} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune donnée de complétude.</p>
          )}
        </Section>

        {/* Per-zone completeness table */}
        <Section title="Détail par zone">
          {data.per_zone_completeness.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Zone</th>
                    <th className="pb-2 pr-2 font-medium">Features</th>
                    <th className="pb-2 pr-2 font-medium">Non-null</th>
                    <th className="pb-2 font-medium">Complétude</th>
                  </tr>
                </thead>
                <tbody>
                  {data.per_zone_completeness.map((z) => (
                    <tr key={z.zone_id} className="border-b border-slate-800">
                      <td className="py-2 pr-2 text-white">{z.zone_id}</td>
                      <td className="py-2 pr-2 text-slate-300">{z.feature_count}</td>
                      <td className="py-2 pr-2 text-slate-300">{z.non_null_features}</td>
                      <td className="py-2">
                        <span className={z.completeness_pct >= 80 ? 'text-green-400' : z.completeness_pct >= 50 ? 'text-yellow-400' : 'text-red-400'}>
                          {z.completeness_pct}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune zone traitée.</p>
          )}
        </Section>
      </div>

      {/* Latest feature vector preview */}
      <Section title="Aperçu des features récents">
        {data.latest_features.length > 0 ? (
          <div className="max-h-48 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-500">
                  <th className="pb-2 pr-2 font-medium">Zone</th>
                  <th className="pb-2 pr-2 font-medium">Timestamp</th>
                  <th className="pb-2 font-medium">Features (extrait)</th>
                </tr>
              </thead>
              <tbody>
                {data.latest_features.slice(0, 10).map((f, i) => (
                  <tr key={i} className="border-b border-slate-800">
                    <td className="py-2 pr-2 text-white">{f.zone_id}</td>
                    <td className="py-2 pr-2 text-slate-400">{f.timestamp ? formatDateTime(f.timestamp) : '—'}</td>
                    <td className="py-2 font-mono text-slate-300 truncate max-w-xs">
                      {JSON.stringify(f.features).slice(0, 120)}...
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucun feature récent.</p>
        )}
      </Section>
    </div>
  );
}

/* ── Predictions View ──────────────────────────────────────────────────────── */

function PredictionsView({ data }: { data: PredictionsDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Total prédictions" value={data.total_predictions.toLocaleString()} />
        <StatCard label="Dernière exécution" value={data.last_run ? formatDateTime(data.last_run) : '—'} />
        <StatCard
          label="Zones avec prédictions"
          value={data.per_zone_summary.length}
        />
        {data.active_model && (
          <StatCard label="Modèle actif" value={data.active_model.name} sub={`v${data.active_model.version}`} />
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Horizon metrics */}
        <Section title="RMSE par horizon">
          {data.horizon_metrics.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.horizon_metrics}>
                  <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                  <XAxis dataKey="horizon" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} width={50} />
                  <ChartTooltip />
                  <Bar dataKey="rmse" fill="#3b82f6" radius={[4, 4, 0, 0]}>
                    {data.horizon_metrics.map((_, i) => (
                      <Cell key={i} fill={['#3b82f6', '#8b5cf6', '#ec4899'][i % 3]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune métrique d'horizon.</p>
          )}
        </Section>

        {/* Predicted vs Actual scatter */}
        <Section title="Prédit vs Réel">
          {data.predicted_vs_actual.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart>
                  <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                  <XAxis type="number" dataKey="predicted" name="Prédit" tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} />
                  <YAxis type="number" dataKey="actual" name="Réel" tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} />
                  <ZAxis range={[20]} />
                  <ChartTooltip />
                  <Scatter data={data.predicted_vs_actual} fill="#22c55e" opacity={0.6} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune donnée de comparaison.</p>
          )}
        </Section>
      </div>

      {/* Per-zone summary */}
      <Section title="Résumé par zone">
        {data.per_zone_summary.length > 0 ? (
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-500">
                  <th className="pb-2 pr-2 font-medium">Zone</th>
                  <th className="pb-2 pr-2 font-medium">Prédictions</th>
                  <th className="pb-2 pr-2 font-medium">Moy. prédite</th>
                  <th className="pb-2 font-medium">Dernière</th>
                </tr>
              </thead>
              <tbody>
                {data.per_zone_summary.map((z) => (
                  <tr key={z.zone_id} className="border-b border-slate-800">
                    <td className="py-2 pr-2 text-white">{z.zone_id}</td>
                    <td className="py-2 pr-2 text-slate-300">{z.prediction_count}</td>
                    <td className="py-2 pr-2 text-slate-300">{z.avg_predicted?.toFixed(2) ?? '—'}</td>
                    <td className="py-2 text-slate-400">{z.last_prediction ? formatDateTime(z.last_prediction) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucune zone.</p>
        )}
      </Section>
    </div>
  );
}

/* ── Kriging View ─────────────────────────────────────────────────────────── */

function KrigingView({ data }: { data: KrigingDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Couverture" value={`${data.coverage_pct}%`} sub={`${data.zones_with_kriging}/${data.total_zones} zones`} />
        <StatCard label="Points de grille" value={data.total_grid_points.toLocaleString()} />
        <StatCard label="RMSE (LOO)" value={data.rmse_loo?.toFixed(3) ?? '—'} />
        <StatCard label="Dernière exécution" value={data.last_run ? formatDateTime(data.last_run) : '—'} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Grid bbox info */}
        <Section title="Emprise de la grille">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-slate-500">Latitude</p>
              <p className="text-white">{data.grid_bbox.lat[0]?.toFixed(4) ?? '—'} → {data.grid_bbox.lat[1]?.toFixed(4) ?? '—'}</p>
            </div>
            <div>
              <p className="text-slate-500">Longitude</p>
              <p className="text-white">{data.grid_bbox.lon[0]?.toFixed(4) ?? '—'} → {data.grid_bbox.lon[1]?.toFixed(4) ?? '—'}</p>
            </div>
          </div>
        </Section>

        {/* Per-zone quality */}
        <Section title="Qualité par zone">
          {data.per_zone_quality.length > 0 ? (
            <div className="max-h-48 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Zone</th>
                    <th className="pb-2 pr-2 font-medium">Cellules</th>
                    <th className="pb-2 pr-2 font-medium">Valeur moy</th>
                    <th className="pb-2 font-medium">Std</th>
                  </tr>
                </thead>
                <tbody>
                  {data.per_zone_quality.map((z) => (
                    <tr key={z.zone_id} className="border-b border-slate-800">
                      <td className="py-2 pr-2 text-white">{z.zone_id}</td>
                      <td className="py-2 pr-2 text-slate-300">{z.grid_cells}</td>
                      <td className="py-2 pr-2 text-slate-300">{z.avg_value ?? '—'}</td>
                      <td className="py-2 text-slate-400">{z.stddev ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune donnée de qualité.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

/* ── NLP Pipeline View ────────────────────────────────────────────────────── */

function NlpPipelineView({ data }: { data: NlpPipelineDetail }) {
  const urgencyData = (data.urgency_distribution ?? []).map((u) => ({
    name: u.urgency,
    value: u.count,
  }));
  const URGENCY_COLORS: Record<string, string> = {
    haute: '#ef4444',
    moyenne: '#f97316',
    basse: '#3b82f6',
    non_classe: '#64748b',
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Rapports traités" value={data.reports_processed.toLocaleString()} />
        <StatCard label="Corrélations spatio-temp." value={`${data.correlation_success_rate_pct}%`} />
        <StatCard label="Embeddings" value={data.embedding_metrics.total_embeddings.toLocaleString()} />
        <StatCard label="Dernière exécution" value={data.last_run ? formatDateTime(data.last_run) : '—'} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Urgency distribution */}
        <Section title="Classification d'urgence">
          {urgencyData.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={urgencyData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                    {urgencyData.map((entry, i) => (
                      <Cell key={i} fill={URGENCY_COLORS[entry.name] || '#64748b'} />
                    ))}
                  </Pie>
                  <ChartTooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune classification.</p>
          )}
        </Section>

        {/* Top entities */}
        <Section title="Entités extraites (top)">
          {data.top_entities.length > 0 ? (
            <div className="max-h-56 overflow-y-auto space-y-1">
              {data.top_entities.slice(0, 15).map((e, i) => (
                <div key={i} className="flex items-center justify-between rounded border border-slate-700/50 bg-slate-800/50 px-3 py-1.5 text-xs">
                  <div>
                    <span className="rounded bg-slate-700 px-1.5 py-0.5 text-slate-400">{e.type}</span>
                    <span className="ml-2 text-white">{e.value}</span>
                  </div>
                  <span className="text-slate-500">{e.count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune entité extraite.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

/* ── Monitoring View ──────────────────────────────────────────────────────── */

function MonitoringView({ data }: { data: MonitoringDetail }) {
  const latencyData = data.latency_p95;
  const coverageData = data.coverage_over_time;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Dernière exécution" value={data.last_run ? formatDateTime(data.last_run) : '—'} />
        <StatCard
          label="Points de métriques"
          value={data.metrics_timeseries.length}
        />
        <StatCard
          label="P95 latence (récente)"
          value={latencyData.length > 0 ? `${latencyData[latencyData.length - 1].p95_latency_ms?.toFixed(0) ?? '—'} ms` : '—'}
        />
        <StatCard
          label="Couverture (récente)"
          value={coverageData.length > 0 ? `${coverageData[coverageData.length - 1].coverage_pct?.toFixed(1) ?? '—'}%` : '—'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Pipeline latency p95 */}
        <Section title="Latence pipeline (p95)">
          {latencyData.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={latencyData}>
                  <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                  <XAxis dataKey="computed_at" tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => formatDateTime(v)} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} width={50} />
                  <ChartTooltip />
                  <Line type="monotone" dataKey="p95_latency_ms" stroke="#f97316" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune donnée de latence.</p>
          )}
        </Section>

        {/* Coverage over time */}
        <Section title="Couverture dans le temps">
          {coverageData.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={coverageData}>
                  <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                  <XAxis dataKey="computed_at" tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => formatDateTime(v)} tickLine={false} axisLine={false} />
                  <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} tickLine={false} axisLine={false} width={40} />
                  <ChartTooltip />
                  <Line type="monotone" dataKey="coverage_pct" stroke="#22c55e" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune donnée de couverture.</p>
          )}
        </Section>
      </div>

      {/* Q1-Q6 metrics table */}
      <Section title="Métriques de qualité (Q1-Q6)">
        {data.metrics_timeseries.length > 0 ? (
          <div className="max-h-64 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-500">
                  <th className="pb-2 pr-2 font-medium">Date</th>
                  <th className="pb-2 font-medium">Métriques</th>
                </tr>
              </thead>
              <tbody>
                {data.metrics_timeseries.map((m, i) => (
                  <tr key={i} className="border-b border-slate-800">
                    <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">{formatDateTime(m.computed_at)}</td>
                    <td className="py-2 font-mono text-slate-300 text-[10px] truncate max-w-md">
                      {JSON.stringify(m.metrics).slice(0, 200)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucune métrique enregistrée.</p>
        )}
      </Section>
    </div>
  );
}

/* ── Retraining View ──────────────────────────────────────────────────────── */

function RetrainingView({ data }: { data: RetrainingDetail }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Versions de modèles" value={data.model_versions.length} />
        <StatCard label="Modèles actifs" value={data.model_versions.filter((m) => m.is_active).length} />
        <StatCard label="Archives" value={data.archived_versions.length} />
        <StatCard label="Prochain entraînement" value={data.next_retraining_at ? formatDateTime(data.next_retraining_at) : '—'} />
      </div>

      {/* Last retraining details */}
      <Section title="Derniers entraînements">
        {data.last_retraining.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-500">
                  <th className="pb-2 pr-2 font-medium">Modèle</th>
                  <th className="pb-2 pr-2 font-medium">Type</th>
                  <th className="pb-2 pr-2 font-medium">Version</th>
                  <th className="pb-2 pr-2 font-medium">Date</th>
                  <th className="pb-2 pr-2 font-medium">MAE</th>
                  <th className="pb-2 pr-2 font-medium">RMSE</th>
                  <th className="pb-2 pr-2 font-medium">R²</th>
                  <th className="pb-2 font-medium">Données</th>
                </tr>
              </thead>
              <tbody>
                {data.last_retraining.map((m) => (
                  <tr key={m.name + m.version} className="border-b border-slate-800">
                    <td className="py-2.5 pr-2 font-medium text-white">{m.name}</td>
                    <td className="py-2.5 pr-2 text-slate-400">{m.type}</td>
                    <td className="py-2.5 pr-2 font-mono text-slate-400">{m.version}</td>
                    <td className="py-2.5 pr-2 text-slate-400">{m.training_end ? formatDateTime(m.training_end) : '—'}</td>
                    <td className="py-2.5 pr-2 text-slate-300">{m.mae?.toFixed(3) ?? '—'}</td>
                    <td className="py-2.5 pr-2 text-slate-300">{m.rmse?.toFixed(3) ?? '—'}</td>
                    <td className="py-2.5 pr-2 text-slate-300">{m.r2?.toFixed(3) ?? '—'}</td>
                    <td className="py-2.5 text-slate-400">{m.data_points?.toLocaleString() ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-8 text-center text-sm text-slate-500">Aucun entraînement récent.</p>
        )}
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Model versions history */}
        <Section title="Historique des versions">
          {data.model_versions.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Modèle</th>
                    <th className="pb-2 pr-2 font-medium">Version</th>
                    <th className="pb-2 pr-2 font-medium">Date</th>
                    <th className="pb-2 font-medium">Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {data.model_versions.map((m) => (
                    <tr key={m.name + m.version} className="border-b border-slate-800">
                      <td className="py-2 pr-2 text-white">{m.name}</td>
                      <td className="py-2 pr-2 font-mono text-slate-400">{m.version}</td>
                      <td className="py-2 pr-2 text-slate-400">{m.training_end ? formatDateTime(m.training_end) : '—'}</td>
                      <td className="py-2">
                        <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase ${m.is_active ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-slate-500/20 text-slate-400 border-slate-500/30'}`}>
                          {m.is_active ? 'actif' : 'inactif'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucun modèle.</p>
          )}
        </Section>

        {/* Archived versions */}
        <Section title="Versions archivées">
          {data.archived_versions.length > 0 ? (
            <div className="max-h-64 overflow-y-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-500">
                    <th className="pb-2 pr-2 font-medium">Modèle</th>
                    <th className="pb-2 pr-2 font-medium">Version</th>
                    <th className="pb-2 font-medium">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {data.archived_versions.map((m) => (
                    <tr key={m.name + m.version} className="border-b border-slate-800">
                      <td className="py-2 pr-2 text-white">{m.name}</td>
                      <td className="py-2 pr-2 font-mono text-slate-400">{m.version}</td>
                      <td className="py-2 text-slate-400">{m.training_end ? formatDateTime(m.training_end) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Aucune version archivée.</p>
          )}
        </Section>
      </div>
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────────────── */

const FLOW_TITLES: Record<string, string> = {
  feature_engineering: 'Flow — Feature Engineering',
  predictions: 'Flow — Prédictions',
  kriging: 'Flow — Krigeage',
  nlp_pipeline: 'Flow — NLP Pipeline',
  monitoring: 'Flow — Monitoring',
  retraining: 'Flow — Réentraînement',
};

export function FlowDetailPage() {
  const { name = '' } = useParams();
  const { data, isLoading, isError } = useFlowDetail(name);

  const title = FLOW_TITLES[name] || `Flow — ${name}`;

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

        {isLoading && <Spinner label="Chargement du flow…" />}

        {isError && (
          <div className="rounded-xl border border-red-800 bg-red-900/30 p-6 text-center">
            <p className="text-sm text-red-400">
              Impossible de charger les détails du flow.
            </p>
          </div>
        )}

        {data && !isLoading && !isError && (
          <>
            {name === 'feature_engineering' && <FeatureEngineeringView data={data as FeatureEngineeringDetail} />}
            {name === 'predictions' && <PredictionsView data={data as PredictionsDetail} />}
            {name === 'kriging' && <KrigingView data={data as KrigingDetail} />}
            {name === 'nlp_pipeline' && <NlpPipelineView data={data as NlpPipelineDetail} />}
            {name === 'monitoring' && <MonitoringView data={data as MonitoringDetail} />}
            {name === 'retraining' && <RetrainingView data={data as RetrainingDetail} />}
          </>
        )}
      </main>
    </div>
  );
}
