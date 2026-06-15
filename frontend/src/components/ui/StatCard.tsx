import type { ReactNode } from 'react';
import { MiniSparkline } from '../charts/MiniSparkline';

interface StatCardProps {
  label: string;
  value: ReactNode;
  unit?: string;
  icon?: ReactNode;
  color?: string;
  trend?: 'increasing' | 'decreasing' | 'stable' | null;
  spark?: number[];
  sub?: string;
}

const TREND = {
  increasing: { sym: '▲', cls: 'text-red-400' },
  decreasing: { sym: '▼', cls: 'text-emerald-400' },
  stable: { sym: '►', cls: 'text-gray-400' },
};

/** Carte KPI : grande valeur, pastille tendance, mini-sparkline optionnelle. */
export function StatCard({ label, value, unit, icon, color = '#38bdf8', trend, spark, sub }: StatCardProps) {
  const t = trend ? TREND[trend] : null;
  return (
    <div className="group relative overflow-hidden rounded-xl border border-gray-800 bg-gray-900 p-4
                    transition hover:border-gray-700 hover:shadow-lg hover:shadow-sky-500/5">
      <div className="absolute inset-x-0 top-0 h-0.5" style={{ background: color }} />
      <div className="flex items-start justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</span>
        {icon && <span className="text-gray-600">{icon}</span>}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-2xl font-bold text-white">{value}</span>
        {unit && <span className="text-sm text-gray-500">{unit}</span>}
        {t && <span className={`ml-auto text-sm ${t.cls}`}>{t.sym}</span>}
      </div>
      {sub && <p className="mt-0.5 text-[11px] text-gray-600">{sub}</p>}
      {spark && spark.length > 1 && (
        <div className="mt-2 -mb-1"><MiniSparkline data={spark} color={color} height={32} /></div>
      )}
    </div>
  );
}
