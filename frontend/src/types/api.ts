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

// Pipeline types
export interface WorkerStatus {
  status: 'running' | 'stopped' | 'degraded';
  uptime_s: number;
  messages_ingested?: number;
  messages_calibrated?: number;
  anomalies_detected?: number;
  alerts_generated?: number;
  last_message_at?: string;
  last_calibration_at?: string;
}

export interface FlowStatus {
  status: 'healthy' | 'degraded' | 'idle' | 'error';
  last_run?: string;
  zones_processed?: number;
  zones_with_predictions?: number;
  reports_processed?: number;
  models_updated?: string[];
  metrics?: Record<string, number>;
}

export interface PipelineStatus {
  workers: {
    ingestion: WorkerStatus;
    calibration: WorkerStatus;
    anomaly_detector: WorkerStatus;
  };
  flows: {
    feature_engineering: FlowStatus;
    predictions: FlowStatus;
    kriging: FlowStatus;
    nlp_pipeline: FlowStatus;
    monitoring: FlowStatus;
    retraining: FlowStatus;
  };
  infrastructure: {
    postgres: { status: string; pool_size?: number };
    influxdb: { status: string };
    redis: { status: string };
    mosquitto: { status: string; messages_since_start?: number };
  };
}

export interface PipelineMetrics {
  messages_ingested_total: number;
  messages_calibrated_total: number;
  anomalies_detected_total: number;
  alerts_generated_total: number;
  predictions_generated_total: number;
  kriging_coverage_pct: number;
  data_freshness_min: number;
  feature_store_rows_today: number;
  generated_at: string;
}

export interface ModelInfo {
  name: string;
  type: string;
  version: string;
  last_trained: string;
  mae?: number;
  val_rmse?: number;
  contamination?: number;
  status: 'active' | 'training' | 'archived';
}

export interface PipelineModels {
  models: ModelInfo[];
}

export interface AnomalyRecord {
  id: number;
  zone_id: string;
  type: string;
  pollutant: string;
  severity: 'info' | 'warning' | 'danger' | 'critical';
  value: number;
  threshold: number;
  detected_at: string;
  sensor_id: string;
}

export interface DataFlowSnapshot {
  ingestion_rate: Array<{ time: string; rate: number }>;
  per_zone: Array<{ zone: string; count: number }>;
  calibration_rate: number;
  anomaly_distribution: Array<{ type: string; count: number }>;
}

// Worker detail types
export interface IngestionWorkerDetail {
  worker: string;
  generated_at: string;
  messages_per_min: Array<{ minute: string; count: number }>;
  dead_letter_count: number;
  dead_letter_entries: Array<{ sensor_id: string; timestamp: string; reason: string }>;
  mqtt_status: Array<{ sensor_id: string; mqtt_reconnects: number; status: string; last_seen: string | null }>;
  total_mqtt_reconnects: number;
  stale_pct: number;
  per_sensor: Array<{ sensor_id: string; zone_id: string; messages_received: number; last_message: string | null }>;
  buffer_utilization_pct: number;
}

export interface CalibrationWorkerDetail {
  worker: string;
  generated_at: string;
  success_rate_pct: number;
  model_info?: {
    name: string;
    version: string;
    last_trained: string | null;
    features_used: string[];
    r2?: number;
    rmse?: number;
  };
  kalman_effectiveness: {
    avg_kalman_gain: number | null;
    uncertainty_reduction_pct: number | null;
  };
  per_pollutant_mae: Array<{ pollutant: string; avg_r2: number; calibrations: number }>;
  fallback_count: number;
  fallback_pct: number;
  active_sensors: Array<{ sensor_id: string; zone_id: string; last_calibrated: string; calibrations_count: number }>;
}

export interface AnomalyDetectorDetail {
  worker: string;
  generated_at: string;
  detection_rate: Array<{ hour: string; count: number }>;
  level_distribution: Array<{ level: string; count: number }>;
  model_health: {
    mean_anomaly_score: number | null;
    contamination_rate: number | null;
  };
  listen_status: { active_listeners: number; channel: string };
  per_zone_heatmap: Array<{ zone_id: string; anomaly_count: number; avg_score: number | null; max_score: number | null }>;
  structural_violations: Array<{
    id: number; zone_id: string; pollutant: string; detected_value: number;
    detected_at: string; sensor_id: string; severity: string; type: string;
  }>;
}

export type WorkerDetail = IngestionWorkerDetail | CalibrationWorkerDetail | AnomalyDetectorDetail;

// Flow detail types
export interface FeatureEngineeringDetail {
  flow: string;
  generated_at: string;
  last_run: string | null;
  total_feature_rows: number;
  feature_coverage_pct: number;
  per_zone_completeness: Array<{ zone_id: string; feature_count: number; non_null_features: number; completeness_pct: number }>;
  latest_features: Array<{ zone_id: string; timestamp: string | null; features: Record<string, unknown> }>;
  feature_importance?: unknown;
}

export interface PredictionsDetail {
  flow: string;
  generated_at: string;
  last_run: string | null;
  total_predictions: number;
  horizon_metrics: Array<{ horizon: string; rmse: number | null; predictions: number }>;
  per_zone_summary: Array<{ zone_id: string; prediction_count: number; last_prediction: string | null; avg_predicted: number | null }>;
  active_model?: { name: string; version: string; last_trained: string | null; metrics: Record<string, unknown> };
  predicted_vs_actual: Array<{ predicted: number; actual: number }>;
}

export interface KrigingDetail {
  flow: string;
  generated_at: string;
  last_run: string | null;
  zones_with_kriging: number;
  total_zones: number;
  coverage_pct: number;
  total_grid_points: number;
  grid_bbox: { lat: number[]; lon: number[] };
  rmse_loo: number | null;
  per_zone_quality: Array<{ zone_id: string; grid_cells: number; avg_value: number | null; stddev: number | null }>;
}

export interface NlpPipelineDetail {
  flow: string;
  generated_at: string;
  last_run: string | null;
  reports_processed: number;
  top_entities: Array<{ type: string; value: string; count: number }>;
  urgency_distribution: Array<{ urgency: string; count: number }>;
  correlation_success_rate_pct: number;
  embedding_metrics: { total_embeddings: number };
}

export interface MonitoringDetail {
  flow: string;
  generated_at: string;
  last_run: string | null;
  metrics_timeseries: Array<{ computed_at: string; metrics: Record<string, unknown> }>;
  latency_p95: Array<{ computed_at: string; p95_latency_ms: number }>;
  coverage_over_time: Array<{ computed_at: string; coverage_pct: number }>;
}

export interface RetrainingDetail {
  flow: string;
  generated_at: string;
  model_versions: Array<{ name: string; type: string; version: string; training_end: string | null; metrics: Record<string, unknown>; is_active: boolean }>;
  last_retraining: Array<{ name: string; type: string; version: string; training_end: string | null; mae?: number; rmse?: number; r2?: number; data_points?: number }>;
  next_retraining_at: string | null;
  archived_versions: Array<{ name: string; type: string; version: string; training_end: string | null; metrics: Record<string, unknown> }>;
}

export type FlowDetail = FeatureEngineeringDetail | PredictionsDetail | KrigingDetail | NlpPipelineDetail | MonitoringDetail | RetrainingDetail;

export interface AnomalySearchResult {
  id: number;
  zone_id: string;
  zone_name: string;
  pollutant: string;
  detected_value: number;
  threshold: number;
  anomaly_score: number | null;
  severity: 'info' | 'warning' | 'danger' | 'critical';
  type: string;
  duration_minutes: number | null;
  detected_at: string;
  sensor_id: string | null;
  handled: boolean;
  alert_id: number | null;
  alert_message: string | null;
}

export interface AnomaliesSearchResponse {
  anomalies: AnomalySearchResult[];
  pagination: { page: number; page_size: number; total_count: number; total_pages: number };
  generated_at: string;
}

export interface AnomalySummary {
  total_today: number;
  by_severity: { info: number; warning: number; danger: number; critical: number };
  most_affected_zone: string | null;
  most_affected_pollutant: string | null;
}

export interface AlertDetail extends Alert {
  resolved_at: string | null;
  acknowledged_at: string | null;
  statut_envoi: string | null;
  canal_envoi: string[] | null;
  sent_at: string | null;
  pollutant: string | null;
  anomaly_id: number | null;
  detected_value: number | null;
  anomaly_score: number | null;
}

export interface AlertsDetailResponse {
  alerts: AlertDetail[];
  pagination: { page: number; page_size: number; total_count: number; total_pages: number };
  generated_at: string;
}

export interface AlertStats {
  total_active: number;
  resolved_today: number;
  avg_response_minutes: number | null;
  daily_counts: Array<{ date: string; info: number; warning: number; danger: number; critical: number }>;
}

export interface ModelVersion {
  version: string;
  is_active: boolean;
  training_end: string | null;
  metrics: Record<string, unknown>;
}

export interface ModelDetail {
  name: string;
  type: string;
  current_version: string;
  is_active: boolean;
  description: string | null;
  created_at: string | null;
  training_metadata: {
    training_start: string | null;
    training_end: string | null;
    data_window_start: string | null;
    data_window_end: string | null;
  };
  hyperparams: Record<string, unknown>;
  performance: Record<string, unknown>;
  file_path: string | null;
  version_history: ModelVersion[];
  generated_at: string;
}

export interface ModelsListResponse {
  models: ModelInfo[];
  generated_at: string;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  service: string;
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
  message: string;
  raw?: Record<string, unknown>;
}

export interface PipelineLogsResponse {
  logs: LogEntry[];
  meta: { total: number; offset: number; limit: number; generated_at: string };
}

export interface SensorDetail extends Sensor {
  pm25_history: Array<{ timestamp: string; value: number }>;
  calibration_coefficients: Record<string, number> | null;
  messages_today: number;
}

export interface SensorsDetailResponse {
  sensors: SensorDetail[];
  meta: {
    total: number;
    active: number;
    inactive: number;
    avg_battery: number | null;
    avg_rssi: number | null;
    generated_at: string;
  };
}

export interface CalibrationRecord {
  id: number;
  sensor_id: string;
  zone_id: string;
  calibrated_at: string;
  old_coefficients: Record<string, number> | null;
  new_coefficients: Record<string, number>;
  pollutant?: string | null;
  r2_score: number;
}

export interface CalibrationResponse {
  records: CalibrationRecord[];
  meta: { total: number; generated_at: string };
}

export interface CalibrationDriftPoint {
  sensor_id: string;
  zone_id: string;
  timestamp: string;
  drift_pct: number;
}

export interface CalibrationDriftResponse {
  drifts: CalibrationDriftPoint[];
  meta: { generated_at: string };
}
