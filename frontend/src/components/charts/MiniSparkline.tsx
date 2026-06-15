import { Area, AreaChart, ResponsiveContainer, YAxis } from 'recharts';

interface MiniSparklineProps {
  data: Array<{ value: number }> | number[];
  color?: string;
  height?: number;
}

/** Petite courbe de tendance sans axes — pour cartes KPI et grille capteurs. */
export function MiniSparkline({ data, color = '#38bdf8', height = 40 }: MiniSparklineProps) {
  const series = (data as unknown[]).map((d, i) =>
    typeof d === 'number' ? { i, value: d } : { i, value: (d as { value: number }).value },
  );
  if (series.length === 0) {
    return <div style={{ height }} className="flex items-center text-xs text-gray-600">—</div>;
  }
  const id = `spark-${color.replace('#', '')}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.5} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <YAxis hide domain={['dataMin', 'dataMax']} />
        <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.5}
              fill={`url(#${id})`} isAnimationActive={false} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
