import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { useAppStore } from "../store/useAppStore";
import { getAQIColor } from "../lib/iqaUtils";
import { Spinner } from "../components/ui/Spinner";

export function PredictionsPage() {
  const { activeZone, zones } = useAppStore();
  const zoneName = zones.find(z => z.id === activeZone)?.name || "Dakar";

  const horizons = [1, 6, 24, 72];
  const { data, isLoading } = useQuery({
    queryKey: ["predictions-all", activeZone],
    queryFn: async () => {
      const results = await Promise.all(
        horizons.map(h => apiClient.get(`/predictions?zone_id=${activeZone}&horizon=${h}`).then(r => r.data))
      );
      return results;
    },
    refetchInterval: 30 * 60_000,
    enabled: !!activeZone,
  });

  if (isLoading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Prédictions · {zoneName}</h1>
        <p className="text-sm text-gray-500">Modèle LSTM — mis à jour toutes les heures</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {data?.map((pred: any, i: number) => (
          <div key={horizons[i]} className="rounded-xl border border-gray-800 bg-gray-900 p-5">
            <h3 className="mb-1 text-sm font-semibold text-gray-400">Horizon {horizons[i]}h</h3>
            {pred?.data?.model && (
              <p className="mb-4 text-[11px] text-gray-600">
                {pred.data.model.name} v{pred.data.model.version} · RMSE {pred.data.model.rmse} µg/m³
              </p>
            )}
            <div className="space-y-2">
              {pred?.data?.predictions?.map((p: any, j: number) => (
                <div key={j} className="flex items-center justify-between rounded-lg bg-gray-800/40 px-3 py-2.5">
                  <span className="text-sm text-gray-300">
                    {new Date(p.target_timestamp).toLocaleDateString("fr-FR", { weekday: "short", hour: "2-digit" })}
                  </span>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-500">
                      {p.ci_lower?.toFixed(0)}–{p.ci_upper?.toFixed(0)}
                    </span>
                    <span className="text-lg font-bold" style={{ color: getAQIColor(p.predicted_value, "pm25") }}>
                      {p.predicted_value?.toFixed(0)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
