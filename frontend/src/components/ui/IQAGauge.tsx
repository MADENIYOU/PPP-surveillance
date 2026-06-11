import { getIQAColor, getIQALabel } from '../../lib/iqaUtils';

interface IQAGaugeProps {
  iqa: number | null;
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
}

const SIZES = { sm: 60, md: 100, lg: 140 };

export function IQAGauge({ iqa, size = 'md', showLabel = true }: IQAGaugeProps) {
  const px = SIZES[size];
  const color = getIQAColor(iqa);
  // Arc demi-cercle : 0-300 IQA → 0-180°
  const fraction = iqa == null ? 0 : Math.min(iqa, 300) / 300;
  const r = px / 2 - 8;
  const cx = px / 2;
  const cy = px / 2;
  const angle = Math.PI * (1 - fraction);
  const x = cx + r * Math.cos(angle);
  const y = cy - r * Math.sin(angle);
  const largeArc = fraction > 0.5 ? 1 : 0;

  return (
    <div className="flex flex-col items-center" role="img"
         aria-label={`IQA ${iqa ?? 'indisponible'} — ${getIQALabel(iqa)}`}>
      <svg width={px} height={px / 2 + 16}>
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none" stroke="#E5E7EB" strokeWidth={8} strokeLinecap="round"
        />
        {iqa != null && (
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 ${largeArc} 1 ${x} ${y}`}
            fill="none" stroke={color} strokeWidth={8} strokeLinecap="round"
          />
        )}
        <text x={cx} y={cy} textAnchor="middle" fontWeight="bold"
              fontSize={size === 'sm' ? 14 : 22} fill={color}>
          {iqa ?? '—'}
        </text>
      </svg>
      {showLabel && <span className="text-xs font-medium text-gray-600">{getIQALabel(iqa)}</span>}
    </div>
  );
}
