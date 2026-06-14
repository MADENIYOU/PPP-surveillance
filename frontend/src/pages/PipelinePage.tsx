import { Link } from 'react-router-dom';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import {
  usePipelineModels,
} from '../hooks/useApi';
import { usePipelineStream } from '../hooks/usePipelineStream';
import type { FlowStatus, WorkerStatus } from '../types/api';

function formatUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}j ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function workerStatusColor(status: string) {
  return status === 'running' ? 'bg-green-500' : status === 'degraded' ? 'bg-yellow-500' : 'bg-red-500';
}

function flowStatusColor(status: string) {
  return status === 'healthy' ? 'bg-green-500' : status === 'degraded' || status === 'idle' ? 'bg-yellow-500' : 'bg-red-500';
}

function severityBadge(severity: string) {
  const map: Record<string, string> = {
    info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    danger: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  };
  return map[severity] ?? map.info;
}

function modelStatusBadge(status: string) {
  return status === 'active'
    ? 'bg-green-500/20 text-green-400 border-green-500/30'
    : status === 'training'
      ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
      : 'bg-slate-500/20 text-slate-400 border-slate-500/30';
}

function infStatusColor(status: string) {
  if (status === 'ok' || status === 'connected' || status === 'running') return 'bg-green-500';
  if (status === 'degraded') return 'bg-yellow-500';
  return 'bg-red-500';
}

function MetricCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
      <div className="mb-2 flex items-center gap-2 text-slate-400">{icon}</div>
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className="text-xs text-slate-400">{label}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function WorkerCard({ name, worker }: { name: string; worker: WorkerStatus }) {
  return (
    <Link to={`/pipeline/worker/${name}`} className="block">
      <div className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-3 hover:border-slate-500 transition-colors">
        <div className="flex items-center gap-3">
          <span className={`h-3 w-3 rounded-full ${workerStatusColor(worker.status)}`} />
          <div>
            <p className="text-sm font-medium capitalize text-white">{name.replace('_', ' ')}</p>
            <p className="text-xs text-slate-400">
              Uptime {formatUptime(worker.uptime_s)}
              {worker.last_message_at && ` · Dernier msg ${formatDateTime(worker.last_message_at)}`}
            </p>
          </div>
        </div>
        <span className="text-xs capitalize text-slate-500">{worker.status}</span>
      </div>
    </Link>
  );
}

function FlowCard({ name, flow }: { name: string; flow: FlowStatus }) {
  return (
    <Link to={`/pipeline/flow/${name}`} className="block">
      <div className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-3 hover:border-slate-500 transition-colors">
        <div className="flex items-center gap-3">
          <span className={`h-3 w-3 rounded-full ${flowStatusColor(flow.status)}`} />
          <div>
            <p className="text-sm font-medium text-white">
              {name === 'nlp_pipeline'
                ? 'NLP Pipeline'
                : name
                    .replace(/_/g, ' ')
                    .replace(/\b\w/g, (c) => c.toUpperCase())}
            </p>
            <p className="text-xs text-slate-400">
              {flow.last_run ? `Dernière exécution ${formatDateTime(flow.last_run)}` : 'Aucune exécution'}
              {flow.zones_processed != null && ` · ${flow.zones_processed} zones`}
              {flow.zones_with_predictions != null && ` · ${flow.zones_with_predictions} prédictions`}
              {flow.reports_processed != null && ` · ${flow.reports_processed} signalements`}
            </p>
          </div>
        </div>
        <span className="text-xs capitalize text-slate-500">{flow.status}</span>
      </div>
    </Link>
  );
}

export function PipelinePage() {
  const { status, metrics, alerts: sseAlerts, connected, error: sseError, lastHeartbeat } = usePipelineStream();
  const { data: models, isLoading: modelsLoading, isError: modelsError } = usePipelineModels();

  const streamLoading = !connected && !status && !metrics;
  const allLoading = streamLoading && modelsLoading;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={(metrics?.generated_at || lastHeartbeat) ?? undefined} />} />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">Pipeline Control Center</h1>
          <div className="flex items-center gap-2 text-xs">
            <span className={`inline-block h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
            <span className="text-slate-400">{connected ? 'SSE connecté' : sseError || 'Connexion...'}</span>
          </div>
        </div>

        {allLoading && <Spinner label="Chargement du pipeline…" />}

        {/* Metrics Overview Row */}
        <section aria-label="Métriques en temps réel">
          <h2 className="mb-3 text-sm font-semibold uppercase text-slate-500">Métriques (SSE · temps réel)</h2>
          {!metrics ? (
            streamLoading ? <Spinner /> : null
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <MetricCard
                icon={<MessageIcon />}
                label="Messages ingérés"
                value={(metrics.messages_ingested_total ?? 0).toLocaleString()}
              />
              <MetricCard
                icon={<AnomalyIcon />}
                label="Anomalies détectées"
                value={(metrics.anomalies_detected_total ?? 0).toLocaleString()}
              />
              <MetricCard
                icon={<AlertIcon />}
                label="Alertes générées"
                value={(metrics.alerts_generated_total ?? 0).toLocaleString()}
              />
              <MetricCard
                icon={<PredictionIcon />}
                label="Prédictions"
                value={(metrics.predictions_generated_total ?? 0).toLocaleString()}
              />
              <MetricCard
                icon={<CoverageIcon />}
                label="Couverture krigeage"
                value={`${metrics.kriging_coverage_pct ?? 0}%`}
              />
              <MetricCard
                icon={<FreshnessIcon />}
                label="Fraîcheur données"
                value={metrics.data_freshness_min != null ? `${metrics.data_freshness_min} min` : '—'}
                sub={`Features: ${(metrics.feature_store_rows_today ?? 0).toLocaleString()} auj.`}
              />
            </div>
          )}
        </section>

        {/* Pipeline Status Grid */}
        <section aria-label="État du pipeline">
          <h2 className="mb-3 text-sm font-semibold uppercase text-slate-500">État du Pipeline (SSE)</h2>
          {!status ? (
            streamLoading ? <Spinner /> : null
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">Workers</h3>
                <div className="space-y-2">
                  <WorkerCard name="ingestion" worker={status.workers.ingestion} />
                  <WorkerCard name="calibration" worker={status.workers.calibration} />
                  <WorkerCard name="anomaly_detector" worker={status.workers.anomaly_detector} />
                </div>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">Flows</h3>
                <div className="space-y-2">
                  {Object.entries(status.flows).map(([key, flow]) => (
                    <FlowCard key={key} name={key} flow={flow} />
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>

        {/* Alerts SSE + Model Registry */}
        <section aria-label="Alertes et modèles">
          <div className="grid gap-4 lg:grid-cols-2">
            {/* SSE Alerts Stream */}
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Alertes actives (SSE · push)
              </h3>
              {!sseAlerts || sseAlerts.length === 0 ? (
                <div className="max-h-80 space-y-1 overflow-y-auto pr-1">
                  {sseAlerts.map((a) => (
                    <div key={a.id} className="flex items-start justify-between rounded-lg border border-slate-700/50 bg-slate-800/50 px-3 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className={`inline-block shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${severityBadge(a.gravite)}`}>
                            {a.gravite}
                          </span>
                          <span className="truncate text-xs font-medium text-white">
                            {a.zone_id} · {a.type}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-slate-400">{a.message}</p>
                        <p className="mt-0.5 text-[11px] text-slate-500">{formatDateTime(a.created_at)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500">Aucune alerte active.</p>
              )}
            </div>

            {/* Model Registry */}
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Registre des Modèles
              </h3>
              {modelsLoading ? (
                <Spinner />
              ) : modelsError ? (
                <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
                  Impossible de charger les modèles.
                </p>
              ) : models && models.models.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-700 text-slate-500">
                        <th className="pb-2 pr-3 font-medium">Modèle</th>
                        <th className="pb-2 pr-3 font-medium">Type</th>
                        <th className="pb-2 pr-3 font-medium">Version</th>
                        <th className="pb-2 pr-3 font-medium">Dernier entraînement</th>
                        <th className="pb-2 pr-3 font-medium">Métrique</th>
                        <th className="pb-2 font-medium">Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      {models.models.map((m) => (
                        <tr key={m.name + m.version} className="border-b border-slate-800">
                          <td className="py-2.5 pr-3 font-medium text-white">{m.name}</td>
                          <td className="py-2.5 pr-3 text-slate-400">{m.type}</td>
                          <td className="py-2.5 pr-3 font-mono text-slate-400">{m.version}</td>
                          <td className="py-2.5 pr-3 text-slate-400">
                            {m.last_trained ? formatDateTime(m.last_trained) : '—'}
                          </td>
                          <td className="py-2.5 pr-3 font-mono text-slate-400">
                            {m.mae != null ? `MAE ${m.mae.toFixed(2)}` : ''}
                            {m.val_rmse != null ? `RMSE ${m.val_rmse.toFixed(2)}` : ''}
                            {m.contamination != null ? `${m.contamination.toFixed(3)}` : ''}
                            {m.mae == null && m.val_rmse == null && m.contamination == null && '—'}
                          </td>
                          <td className="py-2.5">
                            <span
                              className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase ${modelStatusBadge(m.status)}`}
                            >
                              {m.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500">
                  Aucun modèle enregistré.
                </p>
              )}
            </div>
          </div>
        </section>

        {/* Infra Health */}
        <section aria-label="Infrastructure">
          <div className="grid gap-4 lg:grid-cols-1">
            <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Infrastructure
              </h3>
              {!status ? (
                streamLoading ? <Spinner /> : null
              ) : (
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {Object.entries(status.infrastructure).map(([key, info]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/50 px-4 py-3"
                    >
                      <div className="flex items-center gap-3">
                        <span className={`h-3 w-3 rounded-full ${infStatusColor(info.status)}`} />
                        <div>
                          <p className="text-sm font-medium capitalize text-white">
                            {key === 'mosquitto' ? 'Mosquitto MQTT' : key}
                          </p>
                          <p className="text-xs text-slate-400">{info.status}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

/* --- Inline SVG Icons --- */

function MessageIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  );
}

function CalibrateIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 20V10M18 20V4M6 20v-4" />
    </svg>
  );
}

function AnomalyIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

function AlertIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
    </svg>
  );
}

function PredictionIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}

function CoverageIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
    </svg>
  );
}

function FreshnessIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}
