import { useCallback, useEffect, useRef, useState } from 'react';
import type { PipelineMetrics, PipelineStatus } from '../types/api';

/**
 * Hook SSE (Server-Sent Events) pour le pipeline dashboard.
 *
 * Remplace le polling React Query par une connexion EventSource persistante.
 * Le backend pousse les événements en temps réel — latence < 1s, une seule
 * connexion TCP pour toutes les métriques.
 *
 * Événements reçus :
 *   metrics  (toutes les 5s)  — compteurs ingestion/calibration/anomalies
 *   status   (toutes les 10s) — workers, flows, infrastructure
 *   alerts   (toutes les 10s) — 5 dernières alertes actives
 *   heartbeat (toutes les 1s)  — keep-alive, timestamp UTC
 */
export function usePipelineStream() {
  const [metrics, setMetrics] = useState<PipelineMetrics | null>(null);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastHeartbeat, setLastHeartbeat] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const baseUrl = import.meta.env.VITE_API_URL || '/api';

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
    }

    const es = new EventSource(`${baseUrl}/pipeline/stream`);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setError(null);
    };

    es.addEventListener('metrics', (e: MessageEvent) => {
      try {
        setMetrics(JSON.parse(e.data));
      } catch { /* parse error — ignore stale data */ }
    });

    es.addEventListener('status', (e: MessageEvent) => {
      try {
        setStatus(JSON.parse(e.data));
      } catch { /* ignore */ }
    });

    es.addEventListener('alerts', (e: MessageEvent) => {
      try {
        setAlerts(JSON.parse(e.data));
      } catch { /* ignore */ }
    });

    es.addEventListener('heartbeat', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setLastHeartbeat(data.time);
      } catch { /* ignore */ }
    });

    es.addEventListener('error', () => {
      setConnected(false);
      // EventSource reco automatiquement apres quelques secondes
    });

    es.onerror = () => {
      setConnected(false);
      setError('Connexion SSE perdue — reconnexion automatique en cours...');
      es.close();
      esRef.current = null;
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    };
  }, [baseUrl]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [connect]);

  return { metrics, status, alerts, connected, error, lastHeartbeat };
}
