import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { Spinner } from "../components/ui/Spinner";
import { StatCard } from "../components/ui/StatCard";
import { MiniSparkline } from "../components/charts/MiniSparkline";
import { DonutChart } from "../components/charts/DonutChart";
import { useSensorDetail } from "../hooks/useApi";
import { pm25ToHexColor } from "../lib/iqaUtils";
import type { PipelineStatus } from "../types/api";

function batteryColor(p: number | null) {
  if (p == null) return "#64748b";
  if (p > 60) return "#22c55e";
  if (p > 30) return "#eab308";
  return "#ef4444";
}

export function SensorsPage() {
  const { data, isLoading } = useSensorDetail();
  const { data: status } = useQuery({
    queryKey: ["pipeline-status"],
    queryFn: () => apiClient.get<PipelineStatus>("/pipeline/status").catch(() => null),
    refetchInterval: 30_000,
  });

  const sensors = data?.sensors ?? [];
  const meta = data?.meta;
  const workers = status?.workers ?? {};

  const active = sensors.filter((s) => s.status === "active").length;
  const batteries = sensors.map((s) => ({ name: s.sensor_id.replace("ESP32-DK-", ""), battery: s.battery_pct ?? 0 }));
  const statusDonut = [
    { name: "Actifs", value: active, color: "#22c55e" },
    { name: "Inactifs", value: sensors.length - active, color: "#475569" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Capteurs & Réseau IoT</h1>
        <p className="text-sm text-gray-500">{sensors.length} capteurs · {active} actifs</p>
      </div>

      {isLoading ? <div className="flex h-64 items-center justify-center"><Spinner /></div> : (
        <>
          {/* KPIs réseau */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Capteurs actifs" value={active} unit={`/ ${sensors.length}`} color="#22c55e" />
            <StatCard label="Batterie moyenne" value={meta?.avg_battery != null ? `${meta.avg_battery}` : "—"} unit="%" color="#38bdf8" />
            <StatCard label="Signal moyen" value={meta?.avg_rssi != null ? `${meta.avg_rssi}` : "—"} unit="dBm" color="#a78bfa" />
            <StatCard label="Messages aujourd'hui" value={sensors.reduce((s, x) => s + (x.messages_today || 0), 0).toLocaleString("fr-FR")} color="#fbbf24" />
          </div>

          {/* Donut statut + barres batterie */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-400">Disponibilité du parc</h3>
              <DonutChart data={statusDonut} height={200} centerLabel="capteurs" />
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-400">Niveau de batterie</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={batteries} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 9 }} stroke="#334155" interval={0} angle={-30} textAnchor="end" height={50} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" width={38} unit="%" domain={[0, 100]} />
                  <Tooltip cursor={{ fill: '#1e293b55' }} contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="battery" radius={[3, 3, 0, 0]}>
                    {batteries.map((b, i) => <Cell key={i} fill={batteryColor(b.battery)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Cartes capteurs avec sparkline */}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {sensors.map((s) => (
              <div key={s.sensor_id} className="rounded-xl border border-gray-800 bg-gray-900 p-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-white">{s.sensor_id}</h3>
                  <span className={`h-2 w-2 rounded-full ${s.status === "active" ? "bg-emerald-400" : "bg-gray-600"}`} />
                </div>
                <p className="text-xs text-gray-500">{s.zone_name || s.zone_id}</p>
                <div className="my-2 flex items-center justify-between">
                  {s.last_pm25 != null && (
                    <span className="rounded px-1.5 py-0.5 text-xs font-bold text-white" style={{ backgroundColor: pm25ToHexColor(s.last_pm25) }}>
                      {s.last_pm25.toFixed(1)} µg/m³
                    </span>
                  )}
                  <span className="text-[11px] text-gray-500">{s.messages_today ?? 0} msgs/j</span>
                </div>
                {s.pm25_history?.length > 1 && (
                  <MiniSparkline data={s.pm25_history.map((h) => ({ value: h.value }))} color="#38bdf8" height={36} />
                )}
                <div className="mt-2 grid grid-cols-2 gap-1 text-[11px] text-gray-400">
                  <span>🔋 {s.battery_pct != null ? `${Math.round(s.battery_pct)}%` : "—"}</span>
                  <span>📶 {s.rssi_dbm != null ? `${Math.round(s.rssi_dbm)} dBm` : "—"}</span>
                  <span className="col-span-2">FW {s.firmware || "—"}</span>
                </div>
              </div>
            ))}
          </div>

          {/* État pipeline */}
          {Object.keys(workers).length > 0 && (
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-400">État du pipeline</h3>
              <div className="grid gap-2 sm:grid-cols-3">
                {Object.entries(workers).map(([name, w]: [string, any]) => (
                  <div key={name} className="rounded-lg bg-gray-800/50 px-3 py-2">
                    <p className="text-sm font-medium capitalize text-gray-200">{name.replace("_", " ")}</p>
                    <p className={`text-xs ${w.status === "running" ? "text-emerald-400" : "text-red-400"}`}>
                      {w.status === "running" ? "● Running" : "○ " + w.status}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
