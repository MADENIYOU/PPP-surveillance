import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiFetch, apiPost } from '../lib/apiClient';
import type {
  AlertsDetailResponse,
  AlertsResponse,
  AnomaliesSearchResponse,
  AnomalyRecord,
  AqiCurrentResponse,
  AqiHistoryResponse,
  CalibrationDriftResponse,
  CalibrationResponse,
  DataFlowSnapshot,
  FlowDetail,
  KrigingResponse,
  ModelDetail,
  PipelineLogsResponse,
  PipelineMetrics,
  PipelineModels,
  PipelineStatus,
  PredictionsResponse,
  ReportsResponse,
  SensorsDetailResponse,
  SensorsResponse,
  WorkerDetail,
} from '../types/api';

export function useAqiCurrent(zoneId?: string) {
  return useQuery({
    queryKey: ['aqi', 'current', zoneId],
    queryFn: () =>
      apiFetch<AqiCurrentResponse>(`/aqi/current${zoneId ? `?zone_id=${zoneId}` : ''}`),
    refetchInterval: 30_000,
    staleTime: 25_000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
  });
}

export function useAqiHistory(zoneId: string, period: '24h' | '7j' | '30j') {
  const params = {
    '24h': { hours: 24, resolution: '1h' },
    '7j': { hours: 24 * 7, resolution: '6h' },
    '30j': { hours: 24 * 30, resolution: '24h' },
  }[period];
  const start = new Date(Date.now() - params.hours * 3600_000).toISOString();
  return useQuery({
    queryKey: ['aqi', 'history', zoneId, period],
    queryFn: () =>
      apiFetch<AqiHistoryResponse>(
        `/aqi/history?zone_id=${zoneId}&start=${start}&resolution=${params.resolution}&page_size=1000`,
      ),
    staleTime: 5 * 60_000,
    enabled: !!zoneId,
  });
}

export function usePredictions(zoneId?: string) {
  return useQuery({
    queryKey: ['predictions', zoneId],
    queryFn: () =>
      apiFetch<PredictionsResponse>(`/predictions${zoneId ? `?zone_id=${zoneId}` : ''}`),
    refetchInterval: 5 * 60_000,
  });
}

export function useKrigingMap() {
  return useQuery({
    queryKey: ['kriging', 'latest'],
    queryFn: () => apiFetch<KrigingResponse>('/map/kriging?max_age_hours=24'),
    refetchInterval: 60_000,
    staleTime: 55_000,
    retry: 1, // 404 tant que le flow kriging n'a pas tourné — pas la peine d'insister
  });
}

export function useSensors(zoneId?: string) {
  return useQuery({
    queryKey: ['sensors', zoneId],
    queryFn: () =>
      apiFetch<SensorsResponse>(`/sensors${zoneId ? `?zone_id=${zoneId}` : ''}`),
    refetchInterval: 30_000,
  });
}

export function useAlerts() {
  return useQuery({
    queryKey: ['alerts', 'active'],
    queryFn: () => apiFetch<AlertsResponse>('/alerts?active_only=true'),
    refetchInterval: 15_000,
  });
}

export function useReports(zoneId?: string) {
  return useQuery({
    queryKey: ['reports', zoneId],
    queryFn: () =>
      apiFetch<ReportsResponse>(`/reports?hours=24${zoneId ? `&zone_id=${zoneId}` : ''}`),
    refetchInterval: 60_000,
  });
}

// Pipeline hooks
export function usePipelineStatus() {
  return useQuery({
    queryKey: ['pipeline', 'status'],
    queryFn: () => apiFetch<PipelineStatus>('/pipeline/status'),
    refetchInterval: 5000,
    staleTime: 4000,
  });
}

export function usePipelineMetrics() {
  return useQuery({
    queryKey: ['pipeline', 'metrics'],
    queryFn: () => apiFetch<PipelineMetrics>('/pipeline/metrics'),
    refetchInterval: 10000,
    staleTime: 8000,
  });
}

export function usePipelineModels() {
  return useQuery({
    queryKey: ['pipeline', 'models'],
    queryFn: () => apiFetch<PipelineModels>('/pipeline/models'),
    refetchInterval: 30000,
    staleTime: 25000,
  });
}

export function useRecentAnomalies() {
  return useQuery({
    queryKey: ['pipeline', 'anomalies'],
    queryFn: () => apiFetch<{ anomalies: AnomalyRecord[] }>('/pipeline/recent-anomalies'),
    refetchInterval: 15000,
    staleTime: 10000,
  });
}

export function useDataFlow() {
  return useQuery({
    queryKey: ['pipeline', 'dataflow'],
    queryFn: () => apiFetch<DataFlowSnapshot>('/pipeline/dataflow'),
    refetchInterval: 30000,
    staleTime: 25000,
  });
}

export function usePipelineLogs(params?: {
  service?: string;
  level?: string;
  search?: string;
  limit?: number;
  offset?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.service) qs.set('service', params.service);
  if (params?.level) qs.set('level', params.level);
  if (params?.search) qs.set('search', params.search);
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return useQuery({
    queryKey: ['pipeline', 'logs', params],
    queryFn: () =>
      apiFetch<PipelineLogsResponse>(`/pipeline/logs${q ? `?${q}` : ''}`),
    refetchInterval: 5000,
    staleTime: 4000,
  });
}

export function useSensorDetail(zoneId?: string) {
  return useQuery({
    queryKey: ['sensors', 'detail', zoneId],
    queryFn: () =>
      apiFetch<SensorsDetailResponse>(
        `/sensors/detail${zoneId ? `?zone_id=${zoneId}` : ''}`,
      ),
    refetchInterval: 15000,
    staleTime: 10000,
  });
}

export function useCalibrationHistory(params?: {
  sensorId?: string;
  zoneId?: string;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.sensorId) qs.set('sensor_id', params.sensorId);
  if (params?.zoneId) qs.set('zone_id', params.zoneId);
  if (params?.limit) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return useQuery({
    queryKey: ['pipeline', 'calibration', params],
    queryFn: () =>
      apiFetch<CalibrationResponse>(
        `/pipeline/calibration/history${q ? `?${q}` : ''}`,
      ),
    refetchInterval: 30000,
    staleTime: 25000,
  });
}

export function useCalibrationDrift(params?: { hours?: number }) {
  const qs = new URLSearchParams();
  if (params?.hours) qs.set('hours', String(params.hours));
  const q = qs.toString();
  return useQuery({
    queryKey: ['pipeline', 'calibration-drift', params],
    queryFn: () =>
      apiFetch<CalibrationDriftResponse>(
        `/pipeline/calibration/drift${q ? `?${q}` : ''}`,
      ),
    refetchInterval: 60000,
    staleTime: 50000,
  });
}

export function useAnomaliesSearch(params: {
  zone_id?: string;
  severity?: string;
  type?: string;
  pollutant?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}) {
  const qs = new URLSearchParams();
  if (params.zone_id) qs.set('zone_id', params.zone_id);
  if (params.severity) qs.set('severity', params.severity);
  if (params.type) qs.set('type', params.type);
  if (params.pollutant) qs.set('pollutant', params.pollutant);
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const q = qs.toString();
  return useQuery({
    queryKey: ['pipeline', 'anomalies', 'search', params],
    queryFn: () =>
      apiFetch<AnomaliesSearchResponse>(
        `/pipeline/anomalies/search${q ? `?${q}` : ''}`,
      ),
    refetchInterval: 30000,
    staleTime: 25000,
  });
}

export function usePipelineAlerts(params: {
  zone_id?: string;
  gravite?: string;
  type?: string;
  active_only?: boolean;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}) {
  const qs = new URLSearchParams();
  if (params.zone_id) qs.set('zone_id', params.zone_id);
  if (params.gravite) qs.set('gravite', params.gravite);
  if (params.type) qs.set('type', params.type);
  if (params.active_only != null) qs.set('active_only', String(params.active_only));
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  if (params.page) qs.set('page', String(params.page));
  if (params.page_size) qs.set('page_size', String(params.page_size));
  const q = qs.toString();
  return useQuery({
    queryKey: ['pipeline', 'alerts', params],
    queryFn: () =>
      apiFetch<AlertsDetailResponse>(
        `/pipeline/alerts${q ? `?${q}` : ''}`,
      ),
    refetchInterval: 15000,
    staleTime: 10000,
  });
}

export function useModelDetail(name: string) {
  return useQuery({
    queryKey: ['pipeline', 'model', name],
    queryFn: () => apiFetch<ModelDetail>(`/pipeline/model/${name}`),
    refetchInterval: 30000,
    staleTime: 25000,
    enabled: !!name,
  });
}

export function useAcknowledgeAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId: number) =>
      apiPost<{ ok: boolean }>(`/pipeline/alerts/${alertId}/acknowledge`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline', 'alerts'] });
    },
  });
}

export function useResolveAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId: number) =>
      apiPost<{ ok: boolean }>(`/pipeline/alerts/${alertId}/resolve`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline', 'alerts'] });
    },
  });
}

export function useDismissAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId: number) =>
      apiPost<{ ok: boolean }>(`/pipeline/alerts/${alertId}/dismiss`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline', 'alerts'] });
    },
  });
}

export function useAcknowledgeAllAlerts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { severity?: string }) =>
      apiPost<{ acknowledged_count: number }>('/pipeline/alerts/acknowledge-all', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline', 'alerts'] });
    },
  });
}

// Worker & Flow detail hooks
export function useWorkerDetail(name: string) {
  return useQuery({
    queryKey: ['pipeline', 'worker', name],
    queryFn: () => apiFetch<WorkerDetail>(`/pipeline/worker/${name}`),
    refetchInterval: 10000,
    staleTime: 8000,
    enabled: !!name,
  });
}

export function useFlowDetail(name: string) {
  return useQuery({
    queryKey: ['pipeline', 'flow', name],
    queryFn: () => apiFetch<FlowDetail>(`/pipeline/flow/${name}`),
    refetchInterval: 15000,
    staleTime: 12000,
    enabled: !!name,
  });
}
