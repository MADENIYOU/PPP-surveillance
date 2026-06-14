import { useQuery } from "@tanstack/react-query";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import { apiClient } from "../lib/apiClient";
import { Spinner } from "../components/ui/Spinner";
import { useAppStore } from "../store/useAppStore";
import { useMemo } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const sensorIcon = (aqi: number) =>
  L.divIcon({
    className: "custom-marker",
    html: `<div style="
      width:18px;height:18px;border-radius:50%;
      background:${aqi > 150 ? "#ef4444" : aqi > 100 ? "#f97316" : aqi > 50 ? "#eab308" : "#22c55e"};
      border:2px solid white;box-shadow:0 0 6px rgba(0,0,0,.4)
    "></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

function HeatmapLayer({ zoneId }: { zoneId: number }) {
  const map = useMap();
  const { data } = useQuery({
    queryKey: ["heatmap", zoneId],
    queryFn: () => apiClient.get(`/heatmap?zone_id=${zoneId}`).then((r) => r.data as GeoJSON.FeatureCollection),
    refetchInterval: 60_000,
    enabled: !!zoneId,
  });
  if (!data) return null;
  const geoLayer = L.geoJSON(data, {
    style: (f) => {
      const v = f?.properties?.pm25_estime ?? 0;
      const alpha = Math.min(0.8, v / 200);
      const r = v > 100 ? 220 : v > 50 ? 240 : 0;
      const g = v > 100 ? 38 : v > 50 ? 180 : 220;
      const b = v > 100 ? 38 : 0;
      return { fillColor: `rgb(${r},${g},${b})`, fillOpacity: alpha, color: "transparent", weight: 0 };
    },
  }).addTo(map);
  return null;
}

export function MapPage() {
  const { activeZone } = useAppStore();

  const { data: allSensors } = useQuery({
    queryKey: ["sensors"],
    queryFn: () => apiClient.get("/sensors?status=active").then((r) => r.data),
    refetchInterval: 5 * 60_000,
  });

  const { data: aqiList } = useQuery({
    queryKey: ["aqi-all"],
    queryFn: () => apiClient.get("/aqi/map").then((r) => r.data).catch(() => null),
    refetchInterval: 60_000,
  });

  const sensors = useMemo(() => {
    if (!allSensors?.data) return [];
    return allSensors.data.map((s: any) => {
      const aqi = aqiList?.points?.[s.id]?.iqa ?? 0;
      return { ...s, aqi };
    });
  }, [allSensors, aqiList]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Carte interactive</h1>
          <p className="text-sm text-gray-500">
            {sensors.length} capteur{sensors.length > 1 ? "s" : ""} actifs · Pollution en temps réel
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-green-500" /> Bon</span>
          <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-yellow-500" /> Modéré</span>
          <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-orange-500" /> Malsain</span>
          <span className="flex items-center gap-1"><span className="h-3 w-3 rounded-full bg-red-500" /> Dangereux</span>
        </div>
      </div>
      <div className="h-[70vh] overflow-hidden rounded-xl border border-gray-800">
        <MapContainer
          center={[14.72, -17.45]}
          zoom={13}
          className="h-full w-full"
          scrollWheelZoom
        >
          <TileLayer
            attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />
          {activeZone && <HeatmapLayer zoneId={activeZone} />}
          {(sensors ?? []).map((s: any) => (
            <Marker key={s.id} position={[s.lat ?? 14.72, s.lon ?? -17.45]} icon={sensorIcon(s.aqi ?? 0)}>
              <Popup>
                <div className="text-sm text-gray-900">
                  <p className="font-semibold">{s.serial_number || s.name}</p>
                  <p>IQA: <strong>{s.aqi ?? "—"}</strong></p>
                  <p>Zone: {s.zone_name || "—"}</p>
                  <p className="text-xs text-gray-500">Dernière mesure: {s.last_seen ? new Date(s.last_seen).toLocaleTimeString("fr-FR") : "—"}</p>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-400">Capteurs en direct</h3>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(sensors ?? []).map((s: any) => (
            <div key={s.id} className="flex items-center justify-between rounded-lg bg-gray-800/50 px-3 py-2">
              <div>
                <p className="text-sm font-medium text-gray-200">{s.serial_number || s.name}</p>
                <p className="text-[11px] text-gray-500">{s.zone_name}</p>
              </div>
              <span
                className="rounded-full px-2 py-0.5 text-xs font-bold"
                style={{
                  background: (s.aqi ?? 0) > 150 ? "#7f1d1d" : (s.aqi ?? 0) > 100 ? "#7c2d12" : (s.aqi ?? 0) > 50 ? "#713f12" : "#14532d",
                  color: (s.aqi ?? 0) > 150 ? "#fca5a5" : (s.aqi ?? 0) > 100 ? "#fdba74" : (s.aqi ?? 0) > 50 ? "#fde047" : "#86efac",
                }}
              >
                {s.aqi ?? "—"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
