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

import { formatDateTime } from '../../lib/dateUtils';
import { getUnit } from '../../lib/iqaUtils';
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
  data: HistoryPoint[];
  predictions?: PredictionHorizon[];
  pollutant: Pollutant;
}

export function TimeSeriesChart({ data, predictions = [], pollutant }: TimeSeriesChartProps) {
  const field = FIELD_BY_POLLUTANT[pollutant];
  const chartData: Record<string, unknown>[] = data.map((p) => ({
    t: p.timestamp,
    mesure: p[field],
  }));
  // Points de prédiction PM2.5 ajoutés en fin de série (pointillés)
  if (pollutant === 'pm25') {
    for (const h of predictions) {
      chartData.push({ t: h.target_at, prediction: h.pm25_pred });
    }
  }

  return (
    <ResponsiveContainer width="100%" height={320}>
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
        <Line type="monotone" dataKey="prediction" name="Prédiction LSTM" stroke="#F97316"
              strokeWidth={1.5} strokeDasharray="5 5" connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}
