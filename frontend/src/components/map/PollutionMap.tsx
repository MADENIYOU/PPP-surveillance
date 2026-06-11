import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet';
import { useNavigate } from 'react-router-dom';

import { useKrigingMap, useSensors } from '../../hooks/useApi';
import { formatRelative } from '../../lib/dateUtils';
import { getIQAColor, pm25ToHexColor } from '../../lib/iqaUtils';
import type { Sensor } from '../../types/api';
import { MapLegend } from './MapLegend';

const DAKAR_CENTER: [number, number] = [14.7167, -17.4677];
const INITIAL_ZOOM = 12;
const MAX_BOUNDS: [[number, number], [number, number]] = [
  [14.5, -17.65],
  [14.95, -17.1],
];

function iqaFromPm25(pm25: number | null): number | null {
  // approximation locale pour la couleur des marqueurs (la vraie valeur vient du backend)
  if (pm25 == null) return null;
  if (pm25 <= 25) return Math.round((pm25 / 25) * 50);
  if (pm25 <= 55) return Math.round(50 + ((pm25 - 25) / 30) * 50);
  return Math.round(100 + Math.min(pm25 - 55, 95));
}

function SensorPopupContent({ sensor }: { sensor: Sensor }) {
  return (
    <div className="text-sm">
      <div className="font-bold">
        {sensor.sensor_id}{' '}
        <span className={sensor.status === 'active' ? 'text-green-600' : 'text-gray-400'}>
          ● {sensor.status === 'active' ? 'Actif' : sensor.status}
        </span>
      </div>
      <div className="text-gray-600">Zone : {sensor.zone_name}</div>
      <hr className="my-1" />
      {sensor.last_pm25 != null && <div>PM2.5 : {sensor.last_pm25.toFixed(1)} µg/m³</div>}
      {sensor.battery_pct != null && <div>Batterie : {Math.round(sensor.battery_pct)}%</div>}
      {sensor.rssi_dbm != null && <div>Signal : {Math.round(sensor.rssi_dbm)} dBm</div>}
      <div className="text-gray-500">Dernière MAJ : {formatRelative(sensor.last_seen)}</div>
    </div>
  );
}

export function PollutionMap() {
  const { data: sensorsData } = useSensors();
  const { data: kriging } = useKrigingMap();
  const navigate = useNavigate();

  const heatPoints =
    kriging?.geojson?.features?.filter(
      (f) => f.geometry?.type === 'Point' && f.properties?.pm25 != null,
    ) ?? [];

  return (
    <MapContainer
      center={DAKAR_CENTER}
      zoom={INITIAL_ZOOM}
      maxBounds={MAX_BOUNDS}
      scrollWheelZoom
      aria-label="Carte de la pollution à Dakar"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {/* Heatmap kriging — points colorés semi-transparents */}
      {heatPoints.map((f, i) => {
        const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates;
        const pm25 = f.properties!.pm25 as number;
        return (
          <CircleMarker
            key={`k-${i}`}
            center={[lat, lon]}
            radius={14}
            pathOptions={{ fillColor: pm25ToHexColor(pm25), weight: 0, fillOpacity: 0.35 }}
          />
        );
      })}

      {/* Marqueurs capteurs */}
      {sensorsData?.sensors.map((s) => (
        <CircleMarker
          key={s.sensor_id}
          center={[s.lat, s.lon]}
          radius={8}
          pathOptions={{
            fillColor: getIQAColor(iqaFromPm25(s.last_pm25)),
            color: s.status === 'active' ? '#000' : '#666',
            weight: s.status === 'active' ? 2 : 1,
            opacity: s.status === 'active' ? 1 : 0.5,
            fillOpacity: 0.85,
          }}
          eventHandlers={{ dblclick: () => navigate(`/zone/${s.zone_id}`) }}
        >
          <Popup>
            <SensorPopupContent sensor={s} />
          </Popup>
        </CircleMarker>
      ))}

      <MapLegend />
    </MapContainer>
  );
}
