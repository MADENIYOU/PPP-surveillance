import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Header } from '../components/ui/Header';
import { Spinner } from '../components/ui/Spinner';
import { useModelDetail } from '../hooks/useApi';
import { formatDateTime } from '../lib/dateUtils';
import type { ModelVersion } from '../types/api';

function statusBadge(isActive: boolean) {
  return isActive
    ? 'bg-green-500/20 text-green-400 border-green-500/30'
    : 'bg-slate-500/20 text-slate-400 border-slate-500/30';
}

function typeBadge(type: string) {
  const map: Record<string, string> = {
    LSTM: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    GRU: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
    Prophet: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    GCN: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
    RandomForest: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    AutoEncoder: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    IsolationForest: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    GaussianProcess: 'bg-indigo-500/20 text-indigo-400 border-indigo-500/30',
  };
  return map[type] ?? 'bg-slate-500/20 text-slate-400 border-slate-500/30';
}

export function ModelDetailPage() {
  const { name = '' } = useParams();
  const { data, isLoading, isError } = useModelDetail(name);
  const [compareA, setCompareA] = useState<string | null>(null);
  const [compareB, setCompareB] = useState<string | null>(null);
  const [showCompare, setShowCompare] = useState(false);

  const toggleCompare = () => setShowCompare((v) => !v);
  const versions: ModelVersion[] = data?.version_history ?? [];

  const compareAVersion = versions.find((v) => v.version === compareA);
  const compareBVersion = versions.find((v) => v.version === compareB);

  const historyChart = versions
    .filter((v) => {
      const m = v.metrics as Record<string, number> | null;
      return m && (m.rmse != null || m.mae != null);
    })
    .map((v) => {
      const m = v.metrics as Record<string, number>;
      return {
        version: `v${v.version}`,
        training_end: v.training_end ? formatDateTime(v.training_end) : '—',
        rmse: m?.rmse ?? null,
        mae: m?.mae ?? null,
        r2: m?.r2 ?? null,
      };
    })
    .reverse();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header />

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6">
        <div className="flex items-center gap-4">
          <Link to="/pipeline" className="text-sm text-blue-400 hover:underline">
            ← Pipeline
          </Link>
          <h1 className="text-xl font-bold text-white">{name}</h1>
        </div>

        {isLoading && <Spinner label="Chargement du modèle…" />}

        {isError && (
          <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
            Impossible de charger les détails du modèle.
          </p>
        )}

        {data && !isLoading && !isError && (
          <>
            <section
              aria-label="En-tête du modèle"
              className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-700 bg-slate-800 p-4"
            >
              <div>
                <h2 className="text-lg font-bold text-white">{data.name}</h2>
                <p className="text-xs text-slate-400">
                  {data.description || 'Aucune description'}
                </p>
              </div>
              <div className="ml-auto flex items-center gap-2">
                <span
                  className={`inline-block rounded border px-2 py-1 text-xs font-medium uppercase ${typeBadge(data.type)}`}
                >
                  {data.type}
                </span>
                <span className="font-mono text-xs text-slate-400">v{data.current_version}</span>
                <span
                  className={`inline-block rounded border px-2 py-1 text-xs font-medium uppercase ${statusBadge(data.is_active)}`}
                >
                  {data.is_active ? 'Actif' : 'Inactif'}
                </span>
              </div>
              <div className="w-full mt-1 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-400">
                <span>
                  Dernier entraînement :{' '}
                  <span className="text-slate-300">
                    {data.training_metadata?.training_end
                      ? formatDateTime(data.training_metadata.training_end)
                      : '—'}
                  </span>
                </span>
                <span>
                  Période données :{' '}
                  <span className="text-slate-300">
                    {data.training_metadata?.data_window_start
                      ? formatDateTime(data.training_metadata.data_window_start)
                      : '—'}{' '}
                    →{' '}
                    {data.training_metadata?.data_window_end
                      ? formatDateTime(data.training_metadata.data_window_end)
                      : '—'}
                  </span>
                </span>
              </div>
            </section>

            <section
              aria-label="Historique des performances"
              className="rounded-xl border border-slate-700 bg-slate-800 p-4"
            >
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Historique RMSE / MAE
              </h3>
              {historyChart.length > 0 ? (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={historyChart}>
                      <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="version"
                        tick={{ fill: '#94a3b8', fontSize: 11 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fill: '#94a3b8', fontSize: 11 }}
                        tickLine={false}
                        axisLine={false}
                        width={50}
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
                      <Line
                        type="monotone"
                        dataKey="rmse"
                        stroke="#ef4444"
                        strokeWidth={2}
                        dot={{ fill: '#ef4444', r: 3 }}
                        name="RMSE"
                      />
                      <Line
                        type="monotone"
                        dataKey="mae"
                        stroke="#3b82f6"
                        strokeWidth={2}
                        dot={{ fill: '#3b82f6', r: 3 }}
                        name="MAE"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500">
                  Aucun historique d'entraînement.
                </p>
              )}
            </section>

            <section aria-label="Détails" className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">Hyperparamètres</h3>
                {data.hyperparams && Object.keys(data.hyperparams).length > 0 ? (
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-700 text-slate-500">
                        <th className="pb-2 pr-3 font-medium">Paramètre</th>
                        <th className="pb-2 font-medium">Valeur</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(data.hyperparams).map(([key, val]) => (
                        <tr key={key} className="border-b border-slate-800">
                          <td className="py-2 pr-3 font-mono text-slate-400">{key}</td>
                          <td className="py-2 font-mono text-slate-300">
                            {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="py-4 text-center text-sm text-slate-500">Aucun hyperparamètre.</p>
                )}
              </div>

              <div className="rounded-xl border border-slate-700 bg-slate-800 p-4">
                <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                  Métriques actuelles
                </h3>
                {data.performance && Object.keys(data.performance).length > 0 ? (
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-700 text-slate-500">
                        <th className="pb-2 pr-3 font-medium">Métrique</th>
                        <th className="pb-2 font-medium">Valeur</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(data.performance).map(([key, val]) => (
                        <tr key={key} className="border-b border-slate-800">
                          <td className="py-2 pr-3 font-mono text-slate-400">{key}</td>
                          <td className="py-2 font-mono text-slate-300">
                            {typeof val === 'number' ? (val as number).toFixed(4) : String(val)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="py-4 text-center text-sm text-slate-500">Aucune métrique.</p>
                )}
              </div>
            </section>

            <section aria-label="Métadonnées d'entraînement" className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <h3 className="mb-3 text-xs font-semibold uppercase text-slate-500">
                Métadonnées d'entraînement
              </h3>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-400">Début entraînement</span>
                  <span className="text-slate-300">
                    {data.training_metadata?.training_start
                      ? formatDateTime(data.training_metadata.training_start)
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Fin entraînement</span>
                  <span className="text-slate-300">
                    {data.training_metadata?.training_end
                      ? formatDateTime(data.training_metadata.training_end)
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Début fenêtre données</span>
                  <span className="text-slate-300">
                    {data.training_metadata?.data_window_start
                      ? formatDateTime(data.training_metadata.data_window_start)
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Fin fenêtre données</span>
                  <span className="text-slate-300">
                    {data.training_metadata?.data_window_end
                      ? formatDateTime(data.training_metadata.data_window_end)
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Fichier</span>
                  <span className="font-mono text-slate-300">{data.file_path || '—'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Créé le</span>
                  <span className="text-slate-300">
                    {data.created_at ? formatDateTime(data.created_at) : '—'}
                  </span>
                </div>
              </div>
            </section>

            <section aria-label="Historique des versions" className="rounded-xl border border-slate-700 bg-slate-800 p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold uppercase text-slate-500">
                  Historique des versions ({versions.length})
                </h3>
                <button
                  onClick={toggleCompare}
                  className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-400 hover:bg-slate-700"
                >
                  {showCompare ? 'Fermer comparaison' : 'Comparer 2 versions'}
                </button>
              </div>

              {showCompare && (
                <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
                  <select
                    value={compareA ?? ''}
                    onChange={(e) => setCompareA(e.target.value || null)}
                    className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-slate-200"
                  >
                    <option value="">Version A</option>
                    {versions.map((v) => (
                      <option key={v.version} value={v.version}>v{v.version}</option>
                    ))}
                  </select>
                  <span className="text-slate-500">vs</span>
                  <select
                    value={compareB ?? ''}
                    onChange={(e) => setCompareB(e.target.value || null)}
                    className="rounded border border-slate-600 bg-slate-700 px-2 py-1 text-slate-200"
                  >
                    <option value="">Version B</option>
                    {versions.map((v) => (
                      <option key={v.version} value={v.version}>v{v.version}</option>
                    ))}
                  </select>

                  {compareAVersion && compareBVersion && (
                    <div className="ml-4 rounded border border-slate-600 bg-slate-700/50 px-3 py-2 text-[11px]">
                      <div className="grid grid-cols-2 gap-x-6 gap-y-1">
                        <span className="text-slate-400 font-medium">v{compareA}</span>
                        <span className="text-slate-400 font-medium">v{compareB}</span>
                        {(
                          ['rmse', 'mae', 'r2'] as const
                        ).map((k) => {
                          const ma = (compareAVersion.metrics as Record<string, number>)?.[k];
                          const mb = (compareBVersion.metrics as Record<string, number>)?.[k];
                          return (
                            <>
                              <span className="font-mono text-slate-300" key={`a-${k}`}>
                                {k.toUpperCase()} {ma != null ? ma.toFixed(2) : '—'}
                              </span>
                              <span className="font-mono text-slate-300" key={`b-${k}`}>
                                {k.toUpperCase()} {mb != null ? mb.toFixed(2) : '—'}
                              </span>
                            </>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {versions.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-700 text-slate-500">
                        <th className="pb-2 pr-3 font-medium">Version</th>
                        <th className="pb-2 pr-3 font-medium">Entraînement</th>
                        <th className="pb-2 pr-3 font-medium">RMSE</th>
                        <th className="pb-2 pr-3 font-medium">MAE</th>
                        <th className="pb-2 pr-3 font-medium">R²</th>
                        <th className="pb-2 font-medium">Statut</th>
                      </tr>
                    </thead>
                    <tbody>
                      {versions.map((v) => {
                        const m = v.metrics as Record<string, number> | null;
                        return (
                          <tr key={v.version} className="border-b border-slate-800">
                            <td className="py-2.5 pr-3 font-mono text-slate-300">v{v.version}</td>
                            <td className="py-2.5 pr-3 text-slate-400">
                              {v.training_end ? formatDateTime(v.training_end) : '—'}
                            </td>
                            <td className="py-2.5 pr-3 font-mono text-slate-400">
                              {m?.rmse != null ? m.rmse.toFixed(2) : '—'}
                            </td>
                            <td className="py-2.5 pr-3 font-mono text-slate-400">
                              {m?.mae != null ? m.mae.toFixed(2) : '—'}
                            </td>
                            <td className="py-2.5 pr-3 font-mono text-slate-400">
                              {m?.r2 != null ? m.r2.toFixed(3) : '—'}
                            </td>
                            <td className="py-2.5">
                              <span
                                className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase ${statusBadge(v.is_active)}`}
                              >
                                {v.is_active ? 'Actif' : 'Archivé'}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="py-4 text-center text-sm text-slate-500">Aucune version.</p>
              )}
            </section>
          </>
        )}

        {!data && !isLoading && !isError && (
          <p className="py-12 text-center text-sm text-slate-500">Modèle introuvable.</p>
        )}
      </main>
    </div>
  );
}
