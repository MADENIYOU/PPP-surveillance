import {
  Area, ComposedChart, CartesianGrid, Line, ResponsiveContainer,
  Tooltip, XAxis, YAxis, ReferenceLine,
} from 'recharts';
import type { ZonePredictions } from '../../types/api';

interface Props {
  prediction: ZonePredictions | undefined;
  currentPm25?: number | null;
  height?: number;
}

/** Prédiction PM2.5 (maintenant → +1h/+6h/+24h) avec bande de confiance à 95 %. */
export function PredictionTrendChart({ prediction, currentPm25, height = 260 }: Props) {
  const horizons = prediction?.horizons;
  const points: Array<Record<string, number | string | null>> = [];

  if (currentPm25 != null) {
    points.push({ label: 'Maintenant', pred: currentPm25, lo: currentPm25, hi: currentPm25, band: 0 });
  }
  (['h1', 'h6', 'h24'] as const).forEach((h) => {
    const hz = horizons?.[h];
    if (hz) {
      const lo = hz.ci_lower_95 ?? hz.pm25_pred;
      const hi = hz.ci_upper_95 ?? hz.pm25_pred;
      points.push({ label: h.toUpperCase().replace('H', '+') + 'h', pred: hz.pm25_pred, lo, hi, band: hi - lo });
    }
  });

  if (points.length <= 1) {
    return <div className="flex items-center justify-center text-sm text-gray-600" style={{ height }}>Prédictions en attente de données…</div>;
  }

  // Pour dessiner la bande : on empile lo (transparent) puis (hi-lo) visible.
  const rows = points.map((p) => ({ ...p, base: p.lo, span: (p.hi as number) - (p.lo as number) }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <defs>
          <linearGradient id="predband" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22c55e" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#22c55e" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
        <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} stroke="#334155" />
        <YAxis tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" width={42} unit=" µg" />
        <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
                 formatter={(v: number, n) => n === 'pred' ? [`${v.toFixed(1)} µg/m³`, 'Prévu'] : [null, null]} />
        <ReferenceLine y={25} stroke="#eab308" strokeDasharray="4 4" label={{ value: 'OMS', fill: '#eab308', fontSize: 10 }} />
        <Area dataKey="base" stackId="ci" stroke="none" fill="transparent" isAnimationActive={false} />
        <Area dataKey="span" stackId="ci" stroke="none" fill="url(#predband)" name="IC 95%" isAnimationActive />
        <Line type="monotone" dataKey="pred" name="Prévu" stroke="#22c55e" strokeWidth={2.5}
              dot={{ r: 4, fill: '#22c55e' }} activeDot={{ r: 6 }} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
