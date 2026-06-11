// Hooks React Query — cadences de refresh selon FRONTEND_SPEC.md §4.1
import { useQuery } from '@tanstack/react-query';

import { apiFetch } from '../lib/apiClient';
import type {
  AlertsResponse,
  AqiCurrentResponse,
  AqiHistoryResponse,
  KrigingResponse,
  PredictionsResponse,
  ReportsResponse,
  SensorsResponse,
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
