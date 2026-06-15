import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

export interface DonutSegment {
  name: string;
  value: number;
  color: string;
}

interface Props {
  data: DonutSegment[];
  height?: number;
  centerLabel?: string;
}

/** Donut (anneau) coloré avec total au centre et légende. */
export function DonutChart({ data, height = 220, centerLabel }: Props) {
  const total = data.reduce((s, d) => s + d.value, 0);
  if (!total) return <div className="flex items-center justify-center text-sm text-gray-600" style={{ height }}>aucune donnée</div>;

  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="relative" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%"
                 innerRadius="62%" outerRadius="92%" paddingAngle={2} stroke="none">
              {data.map((d) => <Cell key={d.name} fill={d.color} />)}
            </Pie>
            <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold text-white">{total}</span>
          {centerLabel && <span className="text-[10px] uppercase tracking-wide text-gray-500">{centerLabel}</span>}
        </div>
      </div>
      <div className="space-y-1.5">
        {data.map((d) => (
          <div key={d.name} className="flex items-center gap-2 text-sm">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: d.color }} />
            <span className="text-gray-300">{d.name}</span>
            <span className="text-gray-500">({d.value})</span>
          </div>
        ))}
      </div>
    </div>
  );
}
