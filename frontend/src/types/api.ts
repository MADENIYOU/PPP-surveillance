// Types des réponses API — miroir des modèles Pydantic du backend (API_SPEC.md)

export interface ZoneAQI {
  zone_id: string;
  zone_name: string;
  lat_center: number;
  lon_center: number;
  timestamp: string | null;
  iqa: number | null;
  iqa_level: string | null;
  iqa_label_fr: string | null;
  iqa_color: string | null;
  pm25_ug_m3: number | null;
  pm10_ug_m3: number | null;
  no2_ppb: number | null;
  co_ppm: number | null;
  temperature_c: number | null;
  humidity_pct: number | null;
  dominant_pollutant: string | null;
  sensor_count: number;
  sensors_active: number;
  data_freshness_s: number | null;
  trend: 'increasing' | 'decreasing' | 'stable' | null;
}

export interface AqiCurrentResponse {
  zones: ZoneAQI[];
  meta: { generated_at: string; n_zones: number; n_zones_active: number };
}

export interface HistoryPoint {
  timestamp: string;
  iqa: number | null;
  pm25_mean: number | null;
  pm10_mean: number | null;
  no2_ppb_mean: number | null;
  co_ppm_mean: number | null;
  temperature_c: number | null;
  humidity_pct: number | null;
}

export interface AqiHistoryResponse {
  zone_id: string;
  resolution: string;
  start: string;
  end: string;
  data: HistoryPoint[];
}

export interface Sensor {
  sensor_id: string;
  zone_id: string;
  zone_name: string;
  lat: number;
  lon: number;
  status: string;
  last_seen: string | null;
  firmware: string | null;
  battery_pct: number | null;
  rssi_dbm: number | null;
  last_pm25: number | null;
  sim: boolean;
}

export interface SensorsResponse {
  sensors: Sensor[];
  meta: { total: number; active: number; inactive: number; generated_at: string };
}

export interface PredictionHorizon {
  target_at: string;
  pm25_pred: number;
  iqa_pred: number | null;
  ci_lower_95: number | null;
  ci_upper_95: number | null;
  trend: string | null;
}

export interface ZonePredictions {
  zone_id: string;
  predicted_at: string;
  model_used: string | null;
  horizons: Record<'h1' | 'h6' | 'h24', PredictionHorizon | undefined>;
}

export interface PredictionsResponse {
  predictions: ZonePredictions[];
  meta: { generated_at: string; model_version: string | null };
}

export interface Alert {
  id: number;
  zone_id: string;
  zone_name: string;
  type: string;
  gravite: 'info' | 'warning' | 'danger' | 'critical';
  message: string;
  created_at: string;
  active: boolean;
  sensor_id: string | null;
}

export interface AlertsResponse {
  alerts: Alert[];
  meta: { total_active: number; generated_at: string };
}

export interface KrigingResponse {
  metadata: {
    generated_at: string;
    age_minutes: number;
    pm25_min: number | null;
    pm25_max: number | null;
    rmse_loo: number | null;
  };
  geojson: GeoJSON.FeatureCollection;
}

export interface PublicReport {
  id: number;
  created_at: string;
  zone_id: string | null;
  lat_approx: number | null;
  lon_approx: number | null;
  type: string | null;
  description_excerpt: string;
  entities: string[];
  anomaly_correlated: boolean;
  upvotes: number;
}

export interface ReportsResponse {
  reports: PublicReport[];
  meta: { total: number; generated_at: string };
}

export interface ReportCreate {
  description: string;
  lat: number;
  lon: number;
  type: 'smoke' | 'dust' | 'odor' | 'chemical' | 'noise' | 'other';
  intensity: 'low' | 'medium' | 'high';
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: { id: string; role: string; zone_id: string | null };
}
