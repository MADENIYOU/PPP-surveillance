import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { useAppStore } from "../store/useAppStore";
import { useFlowDetail } from "../hooks/useApi";
import { getAQIColor } from "../lib/iqaUtils";
import { Spinner } from "../components/ui/Spinner";
import { StatCard } from "../components/ui/StatCard";
import { PredictionTrendChart } from "../components/charts/PredictionTrendChart";
import type { AqiCurrentResponse, PredictionsResponse } from "../types/api";

export function PredictionsPage() {
  const { activeZone, zones } = useAppStore();
  const zoneName = zones.find(z => z.id === activeZone)?.name || "Dakar";

  const { data, isLoading } = useQuery({
    queryKey: ["predictions-all", activeZone],
    queryFn: () => apiClient.get<PredictionsResponse>(`/predictions?zone_id=${activeZone}`),
    refetchInterval: 30 * 60_000,
    enabled: !!activeZone,
  });

  const { data: aqi } = useQuery({
    queryKey: ["aqi", activeZone],
    queryFn: () => apiClient.get<AqiCurrentResponse>(`/aqi/current?zone_id=${activeZone}`),
    refetchInterval: 60_000,
    enabled: !!activeZone,
  });

  const { data: flow } = useFlowDetail("predictions");

  if (isLoading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  const zonePred = data?.predictions?.find((p) => p.zone_id === activeZone) ?? data?.predictions?.[0];
  const current = aqi?.zones?.find((z) => z.zone_id === activeZone)?.pm25_ug_m3;
  const horizonMetrics = (flow as any)?.horizon_metrics ?? [];
  const rmseRows = horizonMetrics.map((m: any) => ({
    horizon: `+${Math.round((m.horizon ?? 0) / 60)}h`,
    rmse: m.rmse, predictions: m.predictions,
  }));

  const hz = zonePred?.horizons;
  const cards = (['h1', 'h6', 'h24'] as const)
    .map((k) => ({ k, h: hz?.[k] })).filter((x) => x.h);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Prédictions · {zoneName}</h1>
        <p className="text-sm text-gray-500">Modèles LSTM / Prophet — horizon +1h, +6h, +24h</p>
      </div>

      {/* Cartes horizon */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {cards.length ? cards.map(({ k, h }) => (
          <StatCard key={k} label={`Horizon ${k.toUpperCase()}`}
            value={h!.pm25_pred?.toFixed(0) ?? "—"} unit="µg/m³"
            color={getAQIColor(h!.pm25_pred ?? 0, "pm25")}
            sub={h!.ci_lower_95 != null ? `IC95 ${h!.ci_lower_95.toFixed(0)}–${h!.ci_upper_95?.toFixed(0)}` : undefined} />
        )) : <p className="text-sm text-gray-600">Prédictions en attente de données…</p>}
      </div>

      {/* Courbe de prévision */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-400">Trajectoire prévue PM2.5 (bande IC 95 %)</h3>
        <PredictionTrendChart prediction={zonePred} currentPm25={current} height={300} />
      </div>

      {/* Précision du modèle par horizon */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-400">Précision du modèle · RMSE par horizon</h3>
        {rmseRows.length ? (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={rmseRows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="horizon" tick={{ fill: '#94a3b8', fontSize: 11 }} stroke="#334155" />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" width={42} unit=" µg" />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
                       formatter={(v: number) => [v != null ? `${Number(v).toFixed(2)} µg/m³` : '—', 'RMSE']} />
              <Bar dataKey="rmse" fill="#38bdf8" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-gray-600">RMSE disponible après accumulation de mesures réelles à comparer aux prévisions passées.</p>
        )}
      </div>
    </div>
  );
}
