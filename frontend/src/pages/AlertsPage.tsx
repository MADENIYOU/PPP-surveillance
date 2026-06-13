import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { Spinner } from "../components/ui/Spinner";
import { useAppStore } from "../store/useAppStore";

const severityColors: Record<string, string> = {
  critical: "border-red-500 bg-red-900/20",
  danger: "border-orange-500 bg-orange-900/20",
  warning: "border-yellow-500 bg-yellow-900/20",
  info: "border-blue-500 bg-blue-900/20",
};

export function AlertsPage() {
  const { activeZone, zones } = useAppStore();
  const zoneName = zones.find(z => z.id === activeZone)?.name || "Dakar";

  const { data, isLoading } = useQuery({
    queryKey: ["alerts", activeZone],
    queryFn: () => apiClient.get(`/alerts/zone?zone_id=${activeZone}`).then(r => r.data),
    refetchInterval: 60_000,
    enabled: !!activeZone,
  });

  const alerts = data?.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Alertes · {zoneName}</h1>
          <p className="text-sm text-gray-500">
            {alerts.length} alerte{alerts.length !== 1 ? "s" : ""} active{alerts.length !== 1 ? "s" : ""}
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          {Object.entries(severityColors).map(([k, v]) => (
            <span key={k} className={`rounded-full border px-2 py-0.5 ${v}`}>{k}</span>
          ))}
        </div>
      </div>
      {isLoading ? (
        <div className="flex h-64 items-center justify-center"><Spinner /></div>
      ) : alerts.length === 0 ? (
        <div className="rounded-xl border border-emerald-800 bg-emerald-900/20 p-8 text-center">
          <p className="text-lg text-emerald-400">✓ Aucune alerte active</p>
          <p className="mt-1 text-sm text-gray-500">La qualité de l'air est dans les normes pour cette zone.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((a: any) => (
            <div key={a.alert_id} className={`rounded-xl border-l-4 p-4 ${severityColors[a.gravite] || "border-gray-700 bg-gray-900"}`}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-semibold text-white">{a.message}</p>
                  <p className="mt-1 text-xs text-gray-500">
                    {a.type} · {a.pollutant?.toUpperCase()} ·{" "}
                    {new Date(a.created_at).toLocaleString("fr-FR")}
                  </p>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs font-bold uppercase ${
                  a.statut_envoi === "sent" ? "bg-emerald-900 text-emerald-400" : "bg-gray-800 text-gray-400"
                }`}>
                  {a.statut_envoi}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
