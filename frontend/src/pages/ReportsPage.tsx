import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { useAppStore } from "../store/useAppStore";
import { Spinner } from "../components/ui/Spinner";
import { StatCard } from "../components/ui/StatCard";
import type { ReportsResponse } from "../types/api";

export function ReportsPage() {
  const { activeZone } = useAppStore();
  const [texte, setTexte] = useState("");
  const [lat, setLat] = useState(14.72);
  const [lon, setLon] = useState(-17.45);
  const [submitted, setSubmitted] = useState(false);

  const { data: myReports, isLoading } = useQuery({
    queryKey: ["reports"],
    queryFn: () => apiClient.get<ReportsResponse>("/reports?hours=168").catch(() => ({ reports: [], meta: { total: 0, generated_at: "" } } as ReportsResponse)),
    refetchInterval: 2 * 60_000,
  });

  const mutation = useMutation({
    mutationFn: (body: { texte: string; lat: number; lon: number }) => apiClient.post("/reports", body),
    onSuccess: () => { setTexte(""); setSubmitted(true); setTimeout(() => setSubmitted(false), 5000); },
  });

  const reports = myReports?.reports ?? [];

  // Histogramme par jour (7 derniers jours)
  const days: { day: string; count: number }[] = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i); d.setHours(0, 0, 0, 0);
    const next = new Date(d); next.setDate(d.getDate() + 1);
    const count = reports.filter((r) => { const t = new Date(r.created_at); return t >= d && t < next; }).length;
    days.push({ day: d.toLocaleDateString("fr-FR", { weekday: "short" }), count });
  }
  const withEntities = reports.filter((r) => r.entities?.length).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white">Signalements citoyens</h1>
        <p className="text-sm text-gray-500">Signalez une pollution dans votre quartier · {reports.length} signalements (7 j)</p>
      </div>

      {/* KPIs + histogramme */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid grid-cols-1 gap-3 lg:col-span-1">
          <StatCard label="Signalements (7 j)" value={reports.length} color="#38bdf8" />
          <StatCard label="Avec entités détectées (NLP)" value={withEntities} color="#a78bfa"
                    sub={reports.length ? `${Math.round(withEntities / reports.length * 100)}% analysés` : undefined} />
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4 lg:col-span-2">
          <h3 className="mb-3 text-sm font-semibold text-gray-400">Signalements par jour</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={days} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="day" tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" />
              <YAxis allowDecimals={false} tick={{ fill: '#64748b', fontSize: 11 }} stroke="#334155" width={30} />
              <Tooltip cursor={{ fill: '#1e293b55' }} contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="count" fill="#10b981" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Formulaire */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <h3 className="mb-3 text-sm font-semibold text-gray-400">Nouveau signalement</h3>
        <textarea value={texte} onChange={(e) => setTexte(e.target.value)}
          placeholder="Décrivez ce que vous observez (fumée, odeur, poussière...)"
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-3 text-sm text-gray-200 placeholder-gray-600 focus:border-emerald-500 focus:outline-none"
          rows={3} minLength={10} maxLength={1000} />
        <div className="mt-3 flex flex-wrap gap-3">
          <input type="number" step="0.0001" value={lat} onChange={(e) => setLat(Number(e.target.value))}
            className="w-28 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200" placeholder="Latitude" />
          <input type="number" step="0.0001" value={lon} onChange={(e) => setLon(Number(e.target.value))}
            className="w-28 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200" placeholder="Longitude" />
          <button onClick={() => mutation.mutate({ texte, lat, lon })} disabled={texte.length < 10 || mutation.isPending}
            className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50">
            {mutation.isPending ? "Envoi…" : "Signaler"}
          </button>
        </div>
        {submitted && <p className="mt-2 text-sm text-emerald-400">✓ Signalement envoyé — merci pour votre contribution !</p>}
        {mutation.isError && <p className="mt-2 text-sm text-red-400">Erreur lors de l'envoi. Réessayez.</p>}
      </div>

      {/* Liste */}
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <h3 className="mb-3 text-sm font-semibold text-gray-400">Signalements récents</h3>
        {isLoading ? <Spinner /> : (
          <div className="space-y-2">
            {reports.slice(0, 12).map((r) => (
              <div key={r.id} className="rounded-lg bg-gray-800/50 px-3 py-2">
                <p className="text-sm text-gray-200">{r.description_excerpt}</p>
                <p className="mt-1 text-[11px] text-gray-500">
                  {new Date(r.created_at).toLocaleString("fr-FR")}
                  {r.entities?.length ? ` · ${r.entities.join(", ")}` : ""}
                </p>
              </div>
            ))}
            {reports.length === 0 && <p className="text-sm text-gray-600">Aucun signalement pour l'instant.</p>}
          </div>
        )}
      </div>
    </div>
  );
}
