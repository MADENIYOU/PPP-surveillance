import {
  Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import type { ZoneAQI } from '../../types/api';
import { pm25ToHexColor } from '../../lib/iqaUtils';

interface Props {
  zones: ZoneAQI[];
  onSelect?: (zoneId: string) => void;
  height?: number;
}

/** Classement horizontal des zones par PM2.5, barres colorées selon le niveau. */
export function ZoneRankingBar({ zones, onSelect, height = 300 }: Props) {
  const rows = zones
    .filter((z) => z.pm25_ug_m3 != null)
    .map((z) => ({ id: z.zone_id, name: z.zone_name, pm25: Number(z.pm25_ug_m3) }))
    .sort((a, b) => b.pm25 - a.pm25);

  if (!rows.length) return <div className="flex items-center justify-center text-sm text-gray-600" style={{ height }}>Pas de données zone</div>;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 36, bottom: 4, left: 8 }}>
        <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" />
        <YAxis type="category" dataKey="name" width={90} tick={{ fill: '#94a3b8', fontSize: 11 }} stroke="#334155" />
        <Tooltip cursor={{ fill: '#1e293b55' }}
                 contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
                 formatter={(v: number) => [`${v.toFixed(1)} µg/m³`, 'PM2.5']} />
        <Bar dataKey="pm25" radius={[0, 4, 4, 0]} cursor={onSelect ? 'pointer' : undefined}
             onClick={(d: any) => onSelect?.(d.id)} isAnimationActive>
          {rows.map((r) => <Cell key={r.id} fill={pm25ToHexColor(r.pm25)} />)}
          <LabelList dataKey="pm25" position="right" formatter={(v: number) => v.toFixed(0)}
                     style={{ fill: '#cbd5e1', fontSize: 11 }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
