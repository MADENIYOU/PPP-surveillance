import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { Spinner } from "../components/ui/Spinner";
import { StatCard } from "../components/ui/StatCard";
import { DonutChart } from "../components/charts/DonutChart";
import { useAppStore } from "../store/useAppStore";
import type { AlertsResponse } from "../types/api";

const severityColors: Record<string, string> = {
  critical: "border-red-500 bg-red-900/20",
  danger: "border-orange-500 bg-orange-900/20",
  warning: "border-yellow-500 bg-yellow-900/20",
  info: "border-blue-500 bg-blue-900/20",
};

const SEV_HEX: Record<string, string> = {
  critical: "#dc2626", danger: "#f97316", warning: "#eab308", info: "#3b82f6",
};

export function AlertsPage() {
  const { activeZone, zones } = useAppStore();
  const zoneName = zones.find(z => z.id === activeZone)?.name || "Dakar";

  const { data, isLoading } = useQuery({
    queryKey: ["alerts", activeZone],
    queryFn: () => apiClient.get<AlertsResponse>(`/alerts?zone_id=${activeZone}&active_only=true`),
    refetchInterval: 60_000,
    enabled: !!activeZone,
  });

  const alerts = data?.alerts ?? [];
  const byGravite = alerts.reduce<Record<string, number>>((acc, a) => {
    acc[a.gravite] = (acc[a.gravite] || 0) + 1; return acc;
  }, {});
  const donut = Object.entries(byGravite).map(([k, v]) => ({ name: k, value: v, color: SEV_HEX[k] || "#64748b" }));
  const danger = (byGravite.danger || 0) + (byGravite.critical || 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Alertes · {zoneName}</h1>
          <p className="text-sm text-gray-500">{alerts.length} alerte{alerts.length !== 1 ? "s" : ""} active{alerts.length !== 1 ? "s" : ""}</p>
        </div>
        <div className="flex gap-2 text-xs">
          {Object.entries(severityColors).map(([k, v]) => (
            <span key={k} className={`rounded-full border px-2 py-0.5 ${v}`}>{k}</span>
          ))}
        </div>
      </div>

      {isLoading ? <div className="flex h-64 items-center justify-center"><Spinner /></div> : alerts.length === 0 ? (
        <div className="rounded-xl border border-emerald-800 bg-emerald-900/20 p-8 text-center">
          <p className="text-lg text-emerald-400">✓ Aucune alerte active</p>
          <p className="mt-1 text-sm text-gray-500">La qualité de l'air est dans les normes pour cette zone.</p>
        </div>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="grid grid-cols-2 gap-3 lg:col-span-2 lg:grid-cols-2">
              <StatCard label="Total actives" value={alerts.length} color="#38bdf8" />
              <StatCard label="Critiques / Danger" value={danger} color="#ef4444" />
              <StatCard label="Avertissements" value={byGravite.warning || 0} color="#eab308" />
              <StatCard label="Zones touchées" value={new Set(alerts.map(a => a.zone_id)).size} color="#a78bfa" />
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-400">Répartition par gravité</h3>
              <DonutChart data={donut} height={180} centerLabel="alertes" />
            </div>
          </div>

          <div className="space-y-3">
            {alerts.map((a) => (
              <div key={a.id} className={`rounded-xl border-l-4 p-4 ${severityColors[a.gravite] || "border-gray-700 bg-gray-900"}`}>
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-semibold text-white">{a.message}</p>
                    <p className="mt-1 text-xs text-gray-500">{a.type} · {a.zone_id} · {new Date(a.created_at).toLocaleString("fr-FR")}</p>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-bold uppercase ${a.active ? "bg-red-900 text-red-400" : "bg-gray-800 text-gray-400"}`}>
                    {a.active ? "Actif" : "Inactif"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
