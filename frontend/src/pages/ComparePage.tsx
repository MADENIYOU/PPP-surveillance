import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { Spinner } from "../components/ui/Spinner";
import { useAppStore } from "../store/useAppStore";
import { PollutantBar } from "../components/ui/PollutantBar";

export function ComparePage() {
  const { zones } = useAppStore();

  const { data, isLoading } = useQuery({
    queryKey: ["aqi-all-zones"],
    queryFn: async () => {
      if (!zones.length) return [];
      const results = await Promise.all(
        zones.slice(0, 6).map(z =>
          apiClient.get(`/aqi/current?zone_id=${z.id}`).then(r => ({ zone: z.name, ...r.data })).catch(() => null)
        )
      );
      return results.filter(Boolean);
    },
    refetchInterval: 60_000,
    enabled: zones.length > 0,
  });

  if (isLoading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Comparer les zones</h1>
        <p className="text-sm text-gray-500">IQA et polluants par quartier</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data?.map((zone: any) => (
          <div key={zone.zone} className="rounded-xl border border-gray-800 bg-gray-900 p-4">
            <h3 className="mb-2 font-semibold text-white">{zone.zone}</h3>
            <div className="mb-3 flex items-baseline gap-2">
              <span className="text-3xl font-bold" style={{ color: zone?.data?.iqa_color || "#888" }}>
                {zone?.data?.iqa_value ?? "—"}
              </span>
              <span className="text-xs text-gray-500">IQA</span>
            </div>
            {zone?.data?.pollutants && Object.entries(zone.data.pollutants as Record<string, any>).map(([k, v]) => (
              <PollutantBar key={k} name={k.toUpperCase()} value={v.value} unit={v.unit} iqa={v.iqa} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
