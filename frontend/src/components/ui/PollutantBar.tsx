import { getAQIColor } from "../../lib/iqaUtils";

export function PollutantBar({ name, value, unit, iqa }: {
  name: string; value: number; unit: string; iqa: number;
}) {
  const pct = Math.min(100, (iqa / 500) * 100);
  return (
    <div className="mb-1 flex items-center gap-2 text-xs">
      <span className="w-10 text-gray-400">{name}</span>
      <div className="flex-1 h-2 rounded-full bg-gray-800 overflow-hidden">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: getAQIColor(value, name.toLowerCase()) }}
        />
      </div>
      <span className="w-16 text-right text-gray-300">{value?.toFixed(0)} {unit}</span>
    </div>
  );
}
