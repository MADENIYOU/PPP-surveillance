import {
  Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { Spinner } from "../components/ui/Spinner";
import { useAppStore } from "../store/useAppStore";
import { ZoneRankingBar } from "../components/charts/ZoneRankingBar";
import { getIQAColor } from "../lib/iqaUtils";
import type { AqiCurrentResponse } from "../types/api";

export function ComparePage() {
  const { setActiveZone } = useAppStore();

  const { data, isLoading } = useQuery({
    queryKey: ["aqi-all-compare"],
    queryFn: () => apiClient.get<AqiCurrentResponse>(`/aqi/current`),
    refetchInterval: 60_000,
  });

  if (isLoading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  const zones = data?.zones ?? [];
  const grouped = zones
    .filter((z) => z.pm25_ug_m3 != null || z.pm10_ug_m3 != null)
    .map((z) => ({ name: z.zone_name, "PM2.5": z.pm25_ug_m3, PM10: z.pm10_ug_m3 }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Comparer les zones</h1>
        <p className="text-sm text-gray-500">IQA et polluants par quartier · {zones.length} zones</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Classement PM2.5</h3>
          <ZoneRankingBar zones={zones} onSelect={setActiveZone} height={320} />
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">PM2.5 vs PM10 par zone</h3>
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={grouped} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} stroke="#334155" interval={0} angle={-25} textAnchor="end" height={60} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" width={42} unit=" µg" />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }} cursor={{ fill: '#1e293b55' }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="PM2.5" fill="#38bdf8" radius={[3, 3, 0, 0]} />
              <Bar dataKey="PM10" fill="#a78bfa" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Cartes par zone */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {zones.map((z) => (
          <button key={z.zone_id} onClick={() => setActiveZone(z.zone_id)}
            className="rounded-xl border border-gray-800 bg-gray-900 p-4 text-left transition hover:border-gray-600">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-white">{z.zone_name}</h3>
              <span className="text-3xl font-bold" style={{ color: z.iqa_color || getIQAColor(z.iqa) }}>
                {z.iqa ?? "—"}
              </span>
            </div>
            <p className="mb-3 text-xs text-gray-500">{z.iqa_label_fr ?? "—"} · dominant {z.dominant_pollutant?.toUpperCase() ?? "—"}</p>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <Metric label="PM2.5" value={z.pm25_ug_m3} unit="µg/m³" />
              <Metric label="PM10" value={z.pm10_ug_m3} unit="µg/m³" />
              <Metric label="NO₂" value={z.no2_ppb} unit="ppb" />
              <Metric label="CO" value={z.co_ppm} unit="ppm" />
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value, unit }: { label: string; value: number | null; unit: string }) {
  return (
    <div className="rounded-lg bg-gray-800/40 px-2.5 py-1.5">
      <div className="text-gray-500">{label}</div>
      <div className="font-semibold text-gray-200">{value != null ? value.toFixed(1) : "—"} <span className="text-[10px] text-gray-500">{unit}</span></div>
    </div>
  );
}
