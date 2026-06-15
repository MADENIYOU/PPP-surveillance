import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { useAqiHistory } from '../../hooks/useApi';
import { formatDateTime } from '../../lib/dateUtils';
import { Spinner } from '../ui/Spinner';

interface Props {
  zoneId: string;
  window?: '24h' | '7j' | '30j';
  height?: number;
}

const SERIES = [
  { key: 'pm25', name: 'PM2.5', field: 'pm25_mean', color: '#38bdf8' },
  { key: 'pm10', name: 'PM10', field: 'pm10_mean', color: '#a78bfa' },
  { key: 'no2', name: 'NO₂', field: 'no2_ppb_mean', color: '#f472b6' },
  { key: 'co', name: 'CO', field: 'co_ppm_mean', color: '#fbbf24' },
] as const;

/** Aires superposées multi-polluants avec dégradés (PM2.5/PM10/NO₂/CO). */
export function MultiPollutantArea({ zoneId, window = '24h', height = 280 }: Props) {
  const { data, isLoading } = useAqiHistory(zoneId, window);
  const rows = (data?.data ?? []).map((p) => ({
    t: p.timestamp,
    pm25: p.pm25_mean, pm10: p.pm10_mean, no2: p.no2_ppb_mean, co: p.co_ppm_mean,
  }));

  if (isLoading) return <div className="flex items-center justify-center" style={{ height }}><Spinner /></div>;
  if (!rows.length) return <div className="flex items-center justify-center text-sm text-gray-600" style={{ height }}>Données en cours d'accumulation…</div>;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <defs>
          {SERIES.map((s) => (
            <linearGradient key={s.key} id={`g-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
        <XAxis dataKey="t" tickFormatter={(t: string) => formatDateTime(t)} minTickGap={48}
               tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" />
        <YAxis tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" width={42} />
        <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
                 labelFormatter={(t) => formatDateTime(String(t))} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {SERIES.map((s) => (
          <Area key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color}
                strokeWidth={2} fill={`url(#g-${s.key})`} connectNulls dot={false} />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
