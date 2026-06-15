import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { IQAGauge } from "../components/ui/IQAGauge";
import { Spinner } from "../components/ui/Spinner";
import { StatCard } from "../components/ui/StatCard";
import { useAppStore } from "../store/useAppStore";
import { PollutionMap } from "../components/map/PollutionMap";
import { MultiPollutantArea } from "../components/charts/MultiPollutantArea";
import { ZoneRankingBar } from "../components/charts/ZoneRankingBar";
import { PollutantRadar } from "../components/charts/PollutantRadar";
import { PredictionTrendChart } from "../components/charts/PredictionTrendChart";
import { AlertBanner } from "../components/ui/AlertBanner";
import { getHealthAdvice } from "../lib/iqaUtils";
import type { AqiCurrentResponse, AlertsResponse, PredictionsResponse, SensorsResponse } from "../types/api";

export function DashboardPage() {
  const { activeZone, zones, setActiveZone } = useAppStore();
  const activeZoneName = zones.find(z => z.id === activeZone)?.name || "Dakar";

  const { data: aqi, isLoading: aqiLoading } = useQuery({
    queryKey: ["aqi", activeZone],
    queryFn: () => apiClient.get<AqiCurrentResponse>(`/aqi/current?zone_id=${activeZone}`),
    refetchInterval: 60_000,
    enabled: !!activeZone,
  });

  const { data: allZones } = useQuery({
    queryKey: ["aqi-all"],
    queryFn: () => apiClient.get<AqiCurrentResponse>(`/aqi/current`),
    refetchInterval: 60_000,
  });

  const { data: predictions } = useQuery({
    queryKey: ["predictions", activeZone],
    queryFn: () => apiClient.get<PredictionsResponse>(`/predictions?zone_id=${activeZone}`),
    refetchInterval: 15 * 60_000,
    enabled: !!activeZone,
  });

  const { data: alerts } = useQuery({
    queryKey: ["alerts", activeZone],
    queryFn: () => apiClient.get<AlertsResponse>(`/alerts?zone_id=${activeZone}`),
    refetchInterval: 60_000,
    enabled: !!activeZone,
  });

  const { data: sensors } = useQuery({
    queryKey: ["sensors"],
    queryFn: () => apiClient.get<SensorsResponse>("/sensors?status=active"),
    refetchInterval: 5 * 60_000,
  });

  const activeZoneData = aqi?.zones?.find((z) => z.zone_id === activeZone);
  const iqaValue = activeZoneData?.iqa ?? null;
  const dominantPollutant = activeZoneData?.dominant_pollutant?.toUpperCase() ?? "—";
  const sensorCount = activeZoneData?.sensor_count ?? sensors?.sensors?.length ?? 0;
  const lastUpdated = activeZoneData?.timestamp ?? null;

  const hasAlert = alerts?.alerts?.some((a) => a.gravite === "danger" || a.gravite === "critical");
  const zonePred = predictions?.predictions?.find((p) => p.zone_id === activeZone) ?? predictions?.predictions?.[0];

  // Stats globales réseau
  const zonesList = allZones?.zones ?? [];
  const cityAvg = zonesList.filter(z => z.pm25_ug_m3 != null);
  const avgPm25 = cityAvg.length ? cityAvg.reduce((s, z) => s + (z.pm25_ug_m3 || 0), 0) / cityAvg.length : null;
  const worst = [...cityAvg].sort((a, b) => (b.pm25_ug_m3 || 0) - (a.pm25_ug_m3 || 0))[0];
  const totalActive = zonesList.reduce((s, z) => s + (z.sensors_active || 0), 0);

  return (
    <div className="space-y-6">
      {/* Header + zone selector */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">Qualité de l'air · {activeZoneName}</h1>
          <p className="text-sm text-gray-500">
            {lastUpdated ? `Mis à jour ${new Date(lastUpdated).toLocaleTimeString("fr-FR")}` : "Chargement…"}
            {" · "}{sensorCount} capteur{sensorCount > 1 ? "s" : ""} actifs
          </p>
        </div>
        <select value={activeZone ?? ""} onChange={(e) => setActiveZone(e.target.value || null)}
          className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200">
          {zones?.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
        </select>
      </div>

      {hasAlert && alerts && <AlertBanner alerts={alerts.alerts} />}

      {/* KPIs réseau */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="IQA actuel" value={iqaValue ?? "—"} color={activeZoneData?.iqa_color ?? "#38bdf8"}
                  trend={activeZoneData?.trend} sub={activeZoneData?.iqa_label_fr ?? undefined} />
        <StatCard label="Polluant dominant" value={dominantPollutant} color="#a78bfa" />
        <StatCard label="Moyenne ville PM2.5" value={avgPm25 != null ? avgPm25.toFixed(1) : "—"} unit="µg/m³" color="#fbbf24"
                  sub={worst ? `Pire : ${worst.zone_name}` : undefined} />
        <StatCard label="Capteurs actifs (réseau)" value={totalActive || sensorCount} color="#22c55e"
                  sub={`${zonesList.length} zones suivies`} />
      </div>

      {/* IQA gauge + multi-pollutant trend */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-1 flex items-center justify-center rounded-xl border border-gray-800 bg-gray-900 p-4">
          {aqiLoading ? <div className="flex h-64 items-center justify-center"><Spinner /></div>
                      : <IQAGauge iqa={iqaValue} size="lg" />}
        </div>
        <div className="lg:col-span-2 rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Évolution multi-polluants — 24 heures</h3>
          {activeZone && <MultiPollutantArea zoneId={activeZone} window="24h" height={240} />}
        </div>
      </div>

      {/* Ranking + radar */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Classement des zones · PM2.5</h3>
          <ZoneRankingBar zones={zonesList} onSelect={setActiveZone} height={300} />
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Profil polluants · {activeZoneName}</h3>
          <PollutantRadar zone={activeZoneData} height={300} />
        </div>
      </div>

      {/* Map + prediction chart */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Carte de pollution (kriging)</h3>
          <div className="h-72 overflow-hidden rounded-lg"><PollutionMap /></div>
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Prévision PM2.5 · {activeZoneName}</h3>
          <PredictionTrendChart prediction={zonePred} currentPm25={activeZoneData?.pm25_ug_m3} height={260} />
        </div>
      </div>

      {/* Health advice */}
      <div className="rounded-xl border border-gray-800 bg-gradient-to-r from-emerald-900/30 to-gray-900 p-5">
        <h3 className="mb-2 text-sm font-semibold text-emerald-400">Conseil santé</h3>
        <p className="text-sm leading-relaxed text-gray-300">
          {iqaValue != null ? getHealthAdvice(iqaValue) : "En attente des données de qualité de l'air…"}
        </p>
      </div>
    </div>
  );
}
