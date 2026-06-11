import { getIQAColor, getIQALabel } from '../../lib/iqaUtils';
import type { ZoneAQI } from '../../types/api';

interface ZoneCardProps {
  zone: ZoneAQI;
  onClick?: () => void;
  hasActiveAlert?: boolean;
}

const TREND_ICONS = { increasing: '↑ hausse', decreasing: '↓ baisse', stable: '→ stable' };

export function ZoneCard({ zone, onClick, hasActiveAlert }: ZoneCardProps) {
  const color = getIQAColor(zone.iqa);
  return (
    <button
      onClick={onClick}
      aria-label={`Zone ${zone.zone_name}, IQA ${zone.iqa ?? 'indisponible'}`}
      className="w-full rounded-lg border border-gray-200 bg-white p-3 text-left shadow-sm transition hover:shadow-md"
      style={{ borderLeftWidth: 6, borderLeftColor: color }}
    >
      <div className="flex items-center justify-between">
        <span className="font-semibold text-gray-800">{zone.zone_name}</span>
        <span className="rounded px-2 py-0.5 text-sm font-bold text-white" style={{ backgroundColor: color }}>
          {zone.iqa ?? '—'}
        </span>
      </div>
      <div className="mt-1 text-sm text-gray-600">
        {getIQALabel(zone.iqa)}
        {zone.pm25_ug_m3 != null && <> · PM2.5 : {zone.pm25_ug_m3.toFixed(1)} µg/m³</>}
      </div>
      <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
        {zone.trend && <span>Tendance : {TREND_ICONS[zone.trend]}</span>}
        {hasActiveAlert && (
          <span className="rounded bg-red-100 px-1.5 py-0.5 font-medium text-red-700">⚠ Alerte</span>
        )}
      </div>
    </button>
  );
}
