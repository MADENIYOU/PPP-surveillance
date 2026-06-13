import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Sidebar } from "./components/ui/Sidebar";
import { Header } from "./components/ui/Header";
import { DashboardPage } from "./pages/DashboardPage";
import { MapPage } from "./pages/MapPage";
import { PredictionsPage } from "./pages/PredictionsPage";
import { AlertsPage } from "./pages/AlertsPage";
import { SensorsPage } from "./pages/SensorsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ComparePage } from "./pages/ComparePage";
import { AboutPage } from "./pages/AboutPage";
import { LiveIndicator } from "./components/ui/LiveIndicator";
import { useAppStore } from "./store/useAppStore";
import { useEffect } from "react";
import { fetchInitialData } from "./lib/apiClient";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchInterval: 60_000, staleTime: 30_000 } },
});

function AppShell() {
  const { setZones, setActiveZone } = useAppStore();

  useEffect(() => {
    fetchInitialData().then((data) => {
      if (data?.zones) setZones(data.zones);
      if (data?.zones?.[0]) setActiveZone(data.zones[0].id);
    }).catch(() => {});
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-gray-950 text-gray-100">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header>
          <LiveIndicator />
        </Header>
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/predictions" element={<PredictionsPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/sensors" element={<SensorsPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/compare" element={<ComparePage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <footer className="border-t border-gray-800 px-4 py-2 text-center text-xs text-gray-600">
          Surveillance Citoyenne de la Pollution — Dakar, Sénégal · Données mises à jour en continu
        </footer>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
