import { useNavigate } from 'react-router-dom';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import {
  useDataFlow,
  usePipelineMetrics,
  usePipelineStatus,
} from '../hooks/useApi';
import { formatRelative } from '../lib/dateUtils';

type NodeId =
  | 'mqtt'
  | 'ingestion'
  | 'influxdb_raw'
  | 'calibration'
  | 'influxdb_cleansed'
  | 'feature_engineering'
  | 'feature_store'
  | 'predictions'
  | 'api'
  | 'kriging'
  | 'geojson'
  | 'anomaly'
  | 'alerts'
  | 'nlp'
  | 'report_embeddings';

interface FlowNode {
  id: NodeId;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  route?: string;
  count: number | null;
  countLabel: string;
  active: boolean;
}

interface FlowArrow {
  from: NodeId;
  to: NodeId;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  latencyMs: number | null;
  throughput: number | null;
  backpressure: boolean;
}

function latencyLabel(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function throughputLabel(rate: number | null): string {
  if (rate == null) return '—';
  if (rate < 1) return `${rate.toFixed(2)}/s`;
  return `${Math.round(rate)}/s`;
}

const NODE_W = 130;
const NODE_H = 52;

const NODES: FlowNode[] = [
  { id: 'mqtt', label: 'MQTT Sensors', x: 20, y: 30, w: NODE_W, h: NODE_H, count: null, countLabel: 'sensors', active: true },
  { id: 'ingestion', label: 'Ingestion', x: 190, y: 30, w: NODE_W, h: NODE_H, route: '/pipeline', count: null, countLabel: 'msg', active: true },
  { id: 'influxdb_raw', label: 'InfluxDB Raw', x: 360, y: 30, w: NODE_W, h: NODE_H, count: null, countLabel: 'points', active: true },
  { id: 'calibration', label: 'Calibration', x: 530, y: 30, w: NODE_W, h: NODE_H, route: '/pipeline/calibration', count: null, countLabel: 'calibrated', active: true },
  { id: 'influxdb_cleansed', label: 'InfluxDB Cleansed', x: 700, y: 30, w: NODE_W, h: NODE_H, count: null, countLabel: 'points', active: true },
  { id: 'feature_engineering', label: 'Feature Engineering', x: 530, y: 130, w: NODE_W, h: NODE_H, route: '/pipeline', count: null, countLabel: 'features', active: true },
  { id: 'feature_store', label: 'Feature Store', x: 700, y: 130, w: NODE_W, h: NODE_H, count: null, countLabel: 'rows', active: true },
  { id: 'predictions', label: 'Predictions LSTM', x: 530, y: 240, w: NODE_W, h: NODE_H, route: '/pipeline', count: null, countLabel: 'predictions', active: true },
  { id: 'api', label: 'API', x: 700, y: 240, w: NODE_W, h: NODE_H, count: null, countLabel: 'calls', active: true },
  { id: 'kriging', label: 'Kriging', x: 360, y: 240, w: NODE_W, h: NODE_H, route: '/pipeline', count: null, countLabel: 'cells', active: true },
  { id: 'geojson', label: 'GeoJSON Map', x: 190, y: 240, w: NODE_W, h: NODE_H, count: null, countLabel: 'tiles', active: true },
  { id: 'anomaly', label: 'Anomaly Detector', x: 360, y: 350, w: NODE_W, h: NODE_H, route: '/pipeline', count: null, countLabel: 'detected', active: true },
  { id: 'alerts', label: 'Alerts', x: 530, y: 350, w: NODE_W, h: NODE_H, count: null, countLabel: 'alerts', active: true },
  { id: 'nlp', label: 'NLP', x: 190, y: 350, w: NODE_W, h: NODE_H, route: '/pipeline', count: null, countLabel: 'reports', active: true },
  { id: 'report_embeddings', label: 'Report Embeddings', x: 20, y: 350, w: NODE_W, h: NODE_H, count: null, countLabel: 'embeddings', active: true },
];

const arrows: { from: NodeId; to: NodeId }[] = [
  { from: 'mqtt', to: 'ingestion' },
  { from: 'ingestion', to: 'influxdb_raw' },
  { from: 'influxdb_raw', to: 'calibration' },
  { from: 'calibration', to: 'influxdb_cleansed' },
  { from: 'influxdb_cleansed', to: 'feature_engineering' },
  { from: 'feature_engineering', to: 'feature_store' },
  { from: 'feature_store', to: 'predictions' },
  { from: 'predictions', to: 'api' },
  { from: 'feature_store', to: 'kriging' },
  { from: 'kriging', to: 'geojson' },
  { from: 'feature_store', to: 'anomaly' },
  { from: 'anomaly', to: 'alerts' },
  { from: 'influxdb_cleansed', to: 'nlp' },
  { from: 'nlp', to: 'report_embeddings' },
];

export function DataFlowPage() {
  const navigate = useNavigate();

  const { data: status, isLoading: statusLoading } = usePipelineStatus();
  const { data: metrics, isLoading: metricsLoading } = usePipelineMetrics();
  const { data: dataFlow, isLoading: dataFlowLoading } = useDataFlow();

  const isLoading = statusLoading || metricsLoading || dataFlowLoading;

  const mergedNodes: FlowNode[] = NODES.map((n) => {
    const node = { ...n };
    if (metrics) {
      if (n.id === 'ingestion') node.count = metrics.messages_ingested_total;
      else if (n.id === 'calibration') node.count = metrics.messages_calibrated_total;
      else if (n.id === 'anomaly') node.count = metrics.anomalies_detected_total;
      else if (n.id === 'alerts') node.count = metrics.alerts_generated_total;
      else if (n.id === 'predictions') node.count = metrics.predictions_generated_total;
      else if (n.id === 'feature_store') node.count = metrics.feature_store_rows_today;
    }
    if (status) {
      if (n.id === 'ingestion') node.active = status.workers.ingestion.status === 'running';
      else if (n.id === 'calibration') node.active = status.workers.calibration.status === 'running';
      else if (n.id === 'anomaly') node.active = status.workers.anomaly_detector.status === 'running';
      else if (n.id === 'feature_engineering') node.active = status.flows.feature_engineering.status === 'healthy';
      else if (n.id === 'predictions') node.active = status.flows.predictions.status === 'healthy';
      else if (n.id === 'kriging') node.active = status.flows.kriging.status === 'healthy';
      else if (n.id === 'nlp') node.active = status.flows.nlp_pipeline.status === 'healthy';
    }
    return node;
  });

  const nodeMap = new Map(mergedNodes.map((n) => [n.id, n]));
  const mergedArrows: FlowArrow[] = arrows.map((a) => {
    const from = nodeMap.get(a.from)!;
    const to = nodeMap.get(a.to)!;
    return {
      from: a.from,
      to: a.to,
      x1: from.x + from.w,
      y1: from.y + from.h / 2,
      x2: to.x,
      y2: to.y + to.h / 2,
      latencyMs: null,
      throughput: null,
      backpressure: false,
    };
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={metrics?.generated_at ?? null} />} />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">Live Data Flow</h1>
          <span className="text-xs text-slate-500">
            {metrics?.generated_at ? `Updated ${formatRelative(metrics.generated_at)}` : ''}
          </span>
        </div>

        {isLoading && <Spinner label="Chargement du flux de données…" />}

        {!isLoading && (
          <>
            {/* Summary Stats */}
            <section className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
              <StatCard label="Ingestion Rate" value={throughputLabel(metrics?.messages_ingested_total ? metrics.messages_ingested_total / Math.max(metrics.data_freshness_min || 1, 1) / 60 : null)} />
              <StatCard label="Calibration Rate" value={throughputLabel(metrics?.messages_calibrated_total ? metrics.messages_calibrated_total / Math.max(metrics.data_freshness_min || 1, 1) / 60 : null)} />
              <StatCard label="Data Freshness" value={metrics ? `${metrics.data_freshness_min} min` : '—'} />
              <StatCard label="Kriging Coverage" value={metrics ? `${metrics.kriging_coverage_pct}%` : '—'} />
              <StatCard label="Features Today" value={metrics ? String(metrics.feature_store_rows_today) : '—'} />
              <StatCard label="Predictions" value={metrics ? String(metrics.predictions_generated_total) : '—'} />
            </section>

            {/* Flow Diagram */}
            <section className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h2 className="mb-3 text-xs font-semibold uppercase text-slate-500">Pipeline Flow Diagram</h2>
              <div className="overflow-x-auto">
                <svg
                  viewBox="0 0 860 430"
                  className="w-full"
                  style={{ minWidth: 860, height: 'auto' }}
                >
                  <defs>
                    <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                      <polygon points="0 0, 8 3, 0 6" fill="#64748b" />
                    </marker>
                    <marker id="arrowhead-back" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                      <polygon points="0 0, 8 3, 0 6" fill="#f59e0b" />
                    </marker>
                    <filter id="shadow">
                      <feDropShadow dx="0" dy="1" stdDeviation="2" floodOpacity={0.3} />
                    </filter>
                  </defs>

                  {mergedArrows.map((a) => {
                    const backpressure = a.backpressure;
                    const midX = (a.x1 + a.x2) / 2;
                    const midY = (a.y1 + a.y2) / 2;
                    const isDown = a.y2 > a.y1 + 20;
                    const isUp = a.y1 > a.y2 + 20;
                    const path =
                      isDown || isUp
                        ? `M ${a.x1} ${a.y1} C ${a.x1 + 30} ${a.y1}, ${a.x2 - 30} ${a.y2}, ${a.x2} ${a.y2}`
                        : `M ${a.x1} ${a.y1} L ${a.x2} ${a.y2}`;

                    return (
                      <g key={`${a.from}-${a.to}`}>
                        <path
                          d={path}
                          fill="none"
                          stroke={backpressure ? '#f59e0b' : '#475569'}
                          strokeWidth={backpressure ? 2.5 : 1.5}
                          markerEnd={backpressure ? 'url(#arrowhead-back)' : 'url(#arrowhead)'}
                        />
                        {a.latencyMs != null && (
                          <text
                            x={midX}
                            y={midY - 6}
                            fill="#94a3b8"
                            fontSize="9"
                            textAnchor="middle"
                          >
                            {latencyLabel(a.latencyMs)}
                          </text>
                        )}
                        {a.throughput != null && (
                          <text
                            x={midX}
                            y={midY + 8}
                            fill="#64748b"
                            fontSize="8"
                            textAnchor="middle"
                          >
                            {throughputLabel(a.throughput)}
                          </text>
                        )}
                      </g>
                    );
                  })}

                  {mergedNodes.map((n) => (
                    <g
                      key={n.id}
                      transform={`translate(${n.x}, ${n.y})`}
                      style={{ cursor: n.route ? 'pointer' : 'default' }}
                      onClick={() => {
                        if (n.route) navigate(n.route);
                      }}
                    >
                      <rect
                        width={n.w}
                        height={n.h}
                        rx="8"
                        ry="8"
                        fill={n.active ? '#064e3b' : '#1e293b'}
                        stroke={n.active ? '#10b981' : '#475569'}
                        strokeWidth="1.5"
                        filter="url(#shadow)"
                        className="transition-colors hover:opacity-90"
                      />
                      <text
                        x={n.w / 2}
                        y={n.h / 2 - 4}
                        fill={n.active ? '#6ee7b7' : '#94a3b8'}
                        fontSize="10"
                        fontWeight="600"
                        textAnchor="middle"
                        dominantBaseline="middle"
                      >
                        {n.label}
                      </text>
                      {n.count != null && (
                        <text
                          x={n.w / 2}
                          y={n.h / 2 + 13}
                          fill={n.active ? '#34d399' : '#64748b'}
                          fontSize="9"
                          textAnchor="middle"
                          dominantBaseline="middle"
                        >
                          {n.count.toLocaleString()} {n.countLabel}
                        </text>
                      )}
                    </g>
                  ))}

                  {/* Latency overlay labels */}
                  <text x={50} y={420} fill="#64748b" fontSize="9">
                    Click nodes to navigate · Green = active · Gray = inactive
                  </text>
                </svg>
              </div>
            </section>

            {/* Per-zone throughput */}
            {dataFlow && dataFlow.per_zone && dataFlow.per_zone.length > 0 && (
              <section className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <h2 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                  Throughput per Zone
                </h2>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                  {dataFlow.per_zone.slice(0, 10).map((z) => (
                    <div
                      key={z.zone}
                      className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2"
                    >
                      <span className="text-xs font-medium text-white">{z.zone}</span>
                      <span className="text-xs text-slate-400">{z.count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
      <p className="text-lg font-bold text-white">{value}</p>
      <p className="text-xs text-slate-400">{label}</p>
    </div>
  );
}
