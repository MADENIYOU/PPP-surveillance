import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useAqiHistory, usePredictions } from '../../hooks/useApi';
import { formatDateTime } from '../../lib/dateUtils';
import { getUnit } from '../../lib/iqaUtils';
import { Spinner } from '../ui/Spinner';
import type { HistoryPoint, PredictionHorizon } from '../../types/api';

export type Pollutant = 'pm25' | 'pm10' | 'no2' | 'co' | 'temperature' | 'humidity';

const FIELD_BY_POLLUTANT: Record<Pollutant, keyof HistoryPoint> = {
  pm25: 'pm25_mean',
  pm10: 'pm10_mean',
  no2: 'no2_ppb_mean',
  co: 'co_ppm_mean',
  temperature: 'temperature_c',
  humidity: 'humidity_pct',
};

interface TimeSeriesChartProps {
  zoneId: string;
  pollutant: Pollutant;
  window: '24h' | '7j' | '30j';
  height?: number;
}

export function TimeSeriesChart({ zoneId, pollutant, window: timeWindow = '24h', height = 320 }: TimeSeriesChartProps) {
  const { data: historyData, isLoading } = useAqiHistory(zoneId, timeWindow);

  const rawData = historyData?.data ?? [];
  const field = FIELD_BY_POLLUTANT[pollutant];
  const chartData: Record<string, unknown>[] = rawData.map((p) => ({
    t: p.timestamp,
    mesure: p[field],
  }));

  if (isLoading) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <Spinner />
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="t" tickFormatter={(t: string) => formatDateTime(t)} minTickGap={40} />
        <YAxis unit={` ${getUnit(pollutant)}`} width={80} />
        <Tooltip
          labelFormatter={(t) => formatDateTime(String(t))}
          formatter={(value: number | string) => [
            `${Number(value).toFixed(1)} ${getUnit(pollutant)}`,
          ]}
        />
        <Legend />
        {pollutant === 'pm25' && (
          <>
            <ReferenceLine y={25} stroke="#FFD700" strokeDasharray="3 3" label="OMS 24h" />
            <ReferenceLine y={55} stroke="#FFA500" strokeDasharray="3 3" label="Modéré" />
            <ReferenceLine y={150} stroke="#FF0000" strokeDasharray="3 3" label="Mauvais" />
          </>
        )}
        <Line type="monotone" dataKey="mesure" name="Mesures" stroke="#2563EB"
              strokeWidth={2} dot={false} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}
