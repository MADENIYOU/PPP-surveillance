const LEGEND = [
  { color: '#00E400', label: 'Bon (0-50)' },
  { color: '#FFA500', label: 'Modéré (51-100)' },
  { color: '#FF7E00', label: 'Mauvais-sensibles (101-150)' },
  { color: '#FF0000', label: 'Mauvais (151-200)' },
  { color: '#8F3F97', label: 'Très mauvais (201+)' },
];

export function MapLegend() {
  return (
    <div
      className="leaflet-bottom leaflet-left"
      style={{ pointerEvents: 'none' }}
      aria-hidden="true"
    >
      <div className="leaflet-control m-2 rounded bg-white/90 p-2 text-xs shadow">
        <div className="mb-1 font-bold">IQA</div>
        {LEGEND.map((l) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm" style={{ backgroundColor: l.color }} />
            {l.label}
          </div>
        ))}
      </div>
    </div>
  );
}
