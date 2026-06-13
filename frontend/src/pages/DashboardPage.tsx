import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { IQAGauge } from "../components/ui/IQAGauge";
import { Spinner } from "../components/ui/Spinner";
import { useAppStore } from "../store/useAppStore";
import { PollutionMap } from "../components/map/PollutionMap";
import { TimeSeriesChart } from "../components/charts/TimeSeriesChart";
import { AlertBanner } from "../components/ui/AlertBanner";
import { getAQIColor, getHealthAdvice } from "../lib/iqaUtils";

export function DashboardPage() {
  const { activeZone, zones, setActiveZone } = useAppStore();
  const activeZoneName = zones.find(z => z.id === activeZone)?.name || "Dakar";

  const { data: aqi, isLoading: aqiLoading } = useQuery({
    queryKey: ["aqi", activeZone],
    queryFn: () => apiClient.get(`/aqi/current?zone_id=${activeZone}`).then(r => r.data),
    refetchInterval: 60_000,
    enabled: !!activeZone,
  });

  const { data: predictions } = useQuery({
    queryKey: ["predictions", activeZone],
    queryFn: () => apiClient.get(`/predictions?zone_id=${activeZone}&horizon=6`).then(r => r.data),
    refetchInterval: 15 * 60_000,
    enabled: !!activeZone,
  });

  const { data: alerts } = useQuery({
    queryKey: ["alerts", activeZone],
    queryFn: () => apiClient.get(`/alerts/zone?zone_id=${activeZone}`).then(r => r.data),
    refetchInterval: 60_000,
    enabled: !!activeZone,
  });

  const { data: sensors } = useQuery({
    queryKey: ["sensors"],
    queryFn: () => apiClient.get("/sensors?status=active").then(r => r.data),
    refetchInterval: 5 * 60_000,
  });

  const iqaValue = aqi?.data?.iqa_value ?? null;
  const iqaCategory = aqi?.data?.iqa_category ?? "—";
  const dominantPollutant = aqi?.data?.dominant_pollutant?.toUpperCase() ?? "—";
  const sensorCount = aqi?.data?.sensor_count ?? sensors?.data?.length ?? 0;
  const lastUpdated = aqi?.data?.last_updated ?? null;

  const hasAlert = alerts?.data?.some((a: any) => a.gravite === "danger" || a.gravite === "critical");

  return (
    <div className="space-y-6">
      {/* Zone selector + header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">
            Qualité de l'air · {activeZoneName}
          </h1>
          <p className="text-sm text-gray-500">
            {lastUpdated
              ? `Mis à jour ${new Date(lastUpdated).toLocaleTimeString("fr-FR")}`
              : "Chargement…"}
            {" · "}{sensorCount} capteur{sensorCount > 1 ? "s" : ""} actifs
          </p>
        </div>
        <select
          value={activeZone ?? ""}
          onChange={(e) => setActiveZone(Number(e.target.value))}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200"
        >
          {zones.map((z) => (
            <option key={z.id} value={z.id}>{z.name}</option>
          ))}
        </select>
      </div>

      {/* Alert banner */}
      {hasAlert && <AlertBanner alerts={alerts.data} />}

      {/* Top row: IQA + Pollutant breakdown */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-1">
          {aqiLoading ? (
            <div className="flex h-64 items-center justify-center rounded-xl border border-gray-800 bg-gray-900">
              <Spinner />
            </div>
          ) : (
            <IQAGauge
              value={iqaValue}
              category={iqaCategory}
              dominantPollutant={dominantPollutant}
              sensorCount={sensorCount}
            />
          )}
        </div>
        <div className="lg:col-span-2 rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Évolution PM2.5 — 24 heures</h3>
          <TimeSeriesChart zoneId={activeZone!} pollutant="pm25" window="24h" height={220} />
        </div>
      </div>

      {/* Mid row: Map + Predictions */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Carte de pollution</h3>
          <div className="h-72 overflow-hidden rounded-lg">
            <PollutionMap center={[14.72, -17.45]} zoom={12} />
          </div>
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">
            Prédictions PM2.5 — {predictions?.data?.horizon_hours || 6}h
          </h3>
          {predictions?.data?.predictions ? (
            <div className="space-y-3">
              {predictions?.data?.predictions?.map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between rounded-lg bg-gray-800/50 px-3 py-2">
                  <span className="text-sm text-gray-300">
                    {new Date(p.target_timestamp).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <div className="text-right">
                    <span className="text-lg font-bold" style={{ color: getAQIColor(p.predicted_value, "pm25") }}>
                      {p.predicted_value?.toFixed(0)} µg/m³
                    </span>
                    <p className="text-[10px] text-gray-500">
                      ±{(p.ci_upper - p.predicted_value)?.toFixed(1) || "—"}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-600">Prédictions en attente de données…</p>
          )}
        </div>
      </div>

      {/* Bottom: Health advice */}
      <div className="rounded-xl border border-gray-800 bg-gradient-to-r from-emerald-900/30 to-gray-900 p-5">
        <h3 className="mb-2 text-sm font-semibold text-emerald-400">Conseil santé</h3>
        <p className="text-sm leading-relaxed text-gray-300">
          {iqaValue ? getHealthAdvice(iqaValue) : "En attente des données de qualité de l'air…"}
        </p>
      </div>
    </div>
  );
}
