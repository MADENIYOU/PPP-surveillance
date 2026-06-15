import {
  PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip,
} from 'recharts';
import type { ZoneAQI } from '../../types/api';

interface Props {
  zone: ZoneAQI | undefined;
  height?: number;
}

/** Profil radar des polluants d'une zone, normalisé en % du seuil OMS/référence. */
export function PollutantRadar({ zone, height = 260 }: Props) {
  if (!zone) return <div className="flex items-center justify-center text-sm text-gray-600" style={{ height }}>—</div>;

  // Normalisation : valeur / seuil de référence * 100 (capé à 150 %)
  const refs: Array<[string, number | null, number]> = [
    ['PM2.5', zone.pm25_ug_m3, 25],
    ['PM10', zone.pm10_ug_m3, 50],
    ['NO₂', zone.no2_ppb, 100],
    ['CO', zone.co_ppm, 9],
    ['Temp.', zone.temperature_c, 40],
    ['Humid.', zone.humidity_pct, 100],
  ];
  const data = refs.map(([name, val, ref]) => ({
    axis: name,
    pct: val == null ? 0 : Math.min(150, (val / ref) * 100),
    raw: val,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="#1f2937" />
        <PolarAngleAxis dataKey="axis" tick={{ fill: '#94a3b8', fontSize: 11 }} />
        <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
                 formatter={(_v: number, _n, p: any) => [`${p.payload.raw ?? '—'} (${p.payload.pct.toFixed(0)}% seuil)`, p.payload.axis]} />
        <Radar name="Niveau" dataKey="pct" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.4} />
      </RadarChart>
    </ResponsiveContainer>
  );
}
