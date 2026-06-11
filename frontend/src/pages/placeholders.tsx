export function TimeSeriesChartPlaceholder({ label }: { label: string }) {
  return (
    <div className="rounded border border-dashed border-gray-300 p-6 text-center text-sm text-gray-400">
      {label}
    </div>
  );
}
