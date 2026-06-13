import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { useAppStore } from "../store/useAppStore";
import { useQuery } from "@tanstack/react-query";
import { Spinner } from "../components/ui/Spinner";

export function ReportsPage() {
  const { activeZone } = useAppStore();
  const [texte, setTexte] = useState("");
  const [lat, setLat] = useState(14.72);
  const [lon, setLon] = useState(-17.45);
  const [submitted, setSubmitted] = useState(false);

  const { data: myReports, isLoading } = useQuery({
    queryKey: ["reports"],
    queryFn: () => apiClient.get("/reports/mine").then(r => r.data).catch(() => ({ data: [] })),
    refetchInterval: 2 * 60_000,
  });

  const mutation = useMutation({
    mutationFn: (body: { texte: string; lat: number; lon: number }) =>
      apiClient.post("/reports", body),
    onSuccess: () => {
      setTexte("");
      setSubmitted(true);
      setTimeout(() => setSubmitted(false), 5000);
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Signalements citoyens</h1>
        <p className="text-sm text-gray-500">Signalez une pollution dans votre quartier</p>
      </div>
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <h3 className="mb-3 text-sm font-semibold text-gray-400">Nouveau signalement</h3>
        <textarea
          value={texte}
          onChange={(e) => setTexte(e.target.value)}
          placeholder="Décrivez ce que vous observez (fumée, odeur, poussière...)"
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-3 text-sm text-gray-200 placeholder-gray-600 focus:border-emerald-500 focus:outline-none"
          rows={3}
          minLength={10}
          maxLength={1000}
        />
        <div className="mt-3 flex gap-3">
          <input
            type="number"
            step="0.0001"
            value={lat}
            onChange={(e) => setLat(Number(e.target.value))}
            className="w-28 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200"
            placeholder="Latitude"
          />
          <input
            type="number"
            step="0.0001"
            value={lon}
            onChange={(e) => setLon(Number(e.target.value))}
            className="w-28 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200"
            placeholder="Longitude"
          />
          <button
            onClick={() => mutation.mutate({ texte, lat, lon })}
            disabled={texte.length < 10 || mutation.isPending}
            className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {mutation.isPending ? "Envoi…" : "Signaler"}
          </button>
        </div>
        {submitted && (
          <p className="mt-2 text-sm text-emerald-400">✓ Signalement envoyé — merci pour votre contribution !</p>
        )}
        {mutation.isError && (
          <p className="mt-2 text-sm text-red-400">Erreur lors de l'envoi. Réessayez.</p>
        )}
      </div>
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-400">Mes signalements</h3>
        {isLoading ? <Spinner /> : (
          <div className="space-y-2">
            {myReports?.data?.slice(0, 10).map((r: any) => (
              <div key={r.report_id} className="rounded-lg bg-gray-800/50 px-3 py-2">
                <p className="text-sm text-gray-200">{r.texte}</p>
                <p className="mt-1 text-[11px] text-gray-500">
                  {new Date(r.created_at).toLocaleString("fr-FR")}
                  {r.matched_anomaly && " · 🔗 Anomalie détectée"}
                  {r.nlp_status === "processed" ? " · ✓ Traité" : " · ⏳ En attente"}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
