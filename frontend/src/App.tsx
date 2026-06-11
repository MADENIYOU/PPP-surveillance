import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { AboutPage } from './pages/AboutPage';
import { AlertsPage } from './pages/AlertsPage';
import { AnomaliesPage } from './pages/AnomaliesPage';
import { CalibrationPage } from './pages/CalibrationPage';
import { DashboardPage } from './pages/DashboardPage';
import { DataFlowPage } from './pages/DataFlowPage';
import { FlowDetailPage } from './pages/FlowDetailPage';
import { LogsPage } from './pages/LogsPage';
import { ModelDetailPage } from './pages/ModelDetailPage';
import { PipelinePage } from './pages/PipelinePage';
import { ReportPage } from './pages/ReportPage';
import { SensorGridPage } from './pages/SensorGridPage';
import { WorkerDetailPage } from './pages/WorkerDetailPage';
import { ZonePage } from './pages/ZonePage';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/zone/:zone_id" element={<ZonePage />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/pipeline/anomalies" element={<AnomaliesPage />} />
          <Route path="/pipeline/alerts" element={<AlertsPage />} />
          <Route path="/pipeline/model/:name" element={<ModelDetailPage />} />
          <Route path="/pipeline/worker/:name" element={<WorkerDetailPage />} />
          <Route path="/pipeline/flow/:name" element={<FlowDetailPage />} />
          <Route path="/pipeline/dataflow" element={<DataFlowPage />} />
          <Route path="/pipeline/sensors" element={<SensorGridPage />} />
          <Route path="/pipeline/logs" element={<LogsPage />} />
          <Route path="/pipeline/calibration" element={<CalibrationPage />} />
          <Route path="/about" element={<AboutPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
