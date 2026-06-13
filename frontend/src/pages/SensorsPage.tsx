import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { Spinner } from "../components/ui/Spinner";

export function SensorsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["sensors"],
    queryFn: () => apiClient.get("/sensors?status=active").then(r => r.data),
    refetchInterval: 60_000,
  });

  const { data: status } = useQuery({
    queryKey: ["pipeline-status"],
    queryFn: () => apiClient.get("/pipeline/status").then(r => r.data).catch(() => null),
    refetchInterval: 30_000,
  });

  const sensors = data?.data ?? [];
  const workers = status?.data?.workers ?? {};
  const freshness = status?.data?.freshness ?? {};

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Capteurs & Pipeline</h1>
        <p className="text-sm text-gray-500">{sensors.length} capteurs actifs</p>
      </div>
      {isLoading ? (
        <div className="flex h-64 items-center justify-center"><Spinner /></div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {sensors.map((s: any) => (
              <div key={s.id} className="rounded-xl border border-gray-800 bg-gray-900 p-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-white">{s.serial_number}</h3>
                  <span className={`h-2 w-2 rounded-full ${s.status === "active" ? "bg-emerald-400" : "bg-gray-600"}`} />
                </div>
                <div className="mt-2 space-y-1 text-xs text-gray-400">
                  <p>Type: {s.type}</p>
                  <p>Zone: {s.zone_name || s.zone_id}</p>
                  <p>Firmware: {s.firmware_version || "—"}</p>
                  <p>Dernière mesure: {s.last_seen ? new Date(s.last_seen).toLocaleString("fr-FR") : "—"}</p>
                  {freshness[s.id] !== undefined && (
                    <p className={freshness[s.id] ? "text-emerald-400" : "text-red-400"}>
                      {freshness[s.id] ? "● En ligne" : "○ Hors ligne"}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
          {workers && Object.keys(workers).length > 0 && (
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-400">État du pipeline</h3>
              <div className="grid gap-2 sm:grid-cols-3">
                {Object.entries(workers).map(([name, w]: [string, any]) => (
                  <div key={name} className="rounded-lg bg-gray-800/50 px-3 py-2">
                    <p className="text-sm font-medium text-gray-200">{name}</p>
                    <p className={`text-xs ${w?.healthy ? "text-emerald-400" : "text-red-400"}`}>
                      {w?.healthy ? "● Healthy" : "○ Down"}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
