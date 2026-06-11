import { useEffect, useMemo, useState } from 'react';

import { Header } from '../components/ui/Header';
import { LiveIndicator } from '../components/ui/LiveIndicator';
import { Spinner } from '../components/ui/Spinner';
import { useSensorDetail, useSensors } from '../hooks/useApi';
import { formatRelative } from '../lib/dateUtils';
import { pm25ToHexColor } from '../lib/iqaUtils';
import type { Sensor, SensorDetail } from '../types/api';

type SortKey = 'zone_id' | 'status' | 'battery_pct' | 'rssi_dbm' | 'last_seen';
type SortDir = 'asc' | 'desc';

function statusColor(status: string): string {
  if (status === 'active') return 'bg-green-500';
  if (status === 'inactive') return 'bg-yellow-500';
  return 'bg-red-500';
}

function statusText(status: string): string {
  if (status === 'active') return 'Active';
  if (status === 'inactive') return 'Late';
  return 'Offline';
}

function batteryColor(pct: number | null): string {
  if (pct == null) return 'text-slate-500';
  if (pct >= 70) return 'text-green-400';
  if (pct >= 30) return 'text-yellow-400';
  return 'text-red-400';
}

function rssiSignalBars(dbm: number | null): { bars: number; color: string } {
  if (dbm == null) return { bars: 0, color: 'text-slate-500' };
  if (dbm >= -50) return { bars: 5, color: 'text-green-400' };
  if (dbm >= -60) return { bars: 4, color: 'text-green-400' };
  if (dbm >= -70) return { bars: 3, color: 'text-yellow-400' };
  if (dbm >= -80) return { bars: 2, color: 'text-orange-400' };
  return { bars: 1, color: 'text-red-400' };
}

function batteryIcon(pct: number | null) {
  const w = 16;
  const h = 8;
  const fill = pct == null ? 'transparent' : pct >= 70 ? '#4ade80' : pct >= 30 ? '#facc15' : '#f87171';
  const fillW = pct == null ? 0 : Math.max(1, (pct / 100) * (w - 4));
  return (
    <svg width={w + 3} height={h + 2} viewBox={`0 0 ${w + 3} ${h + 2}`} className="inline-block shrink-0">
      <rect x="0" y="0" width={w} height={h} rx="1.5" fill="none" stroke="#64748b" strokeWidth="1" />
      <rect x={1.5} y={1.5} width={fillW - 1} height={h - 3} rx="0.5" fill={fill} />
      <rect x={w} y={h / 2 - 1} width="2" height="2" rx="0.5" fill="#64748b" />
    </svg>
  );
}

function Sparkline({ data }: { data: Array<{ timestamp: string; value: number }> }) {
  if (data.length < 2) {
    return <div className="h-8 w-full" />;
  }
  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 80;
  const h = 28;
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / range) * h}`)
    .join(' ');
  return (
    <svg width={w} height={h} className="inline-block shrink-0">
      <polyline points={points} fill="none" stroke="#22c55e" strokeWidth="1.5" />
    </svg>
  );
}

type FilterState = {
  zoneId: string;
  status: string;
  minBattery: number;
  minRssi: number;
  search: string;
};

export function SensorGridPage() {
  const { data: sensorsData, isLoading: sensorsLoading, isError: sensorsError } = useSensors();
  const { data: detailData, isLoading: detailLoading } = useSensorDetail();

  const [filter, setFilter] = useState<FilterState>({
    zoneId: '',
    status: '',
    minBattery: 0,
    minRssi: -120,
    search: '',
  });
  const [sortKey, setSortKey] = useState<SortKey>('zone_id');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [modalSensor, setModalSensor] = useState<SensorDetail | null>(null);
  const [refreshCountdown, setRefreshCountdown] = useState(30);

  useEffect(() => {
    const id = setInterval(() => {
      setRefreshCountdown((c) => (c <= 1 ? 30 : c - 1));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const sensors: Sensor[] = sensorsData?.sensors ?? [];
  const detailMap = useMemo(() => {
    const map = new Map<string, SensorDetail>();
    if (detailData?.sensors) {
      for (const s of detailData.sensors) map.set(s.sensor_id, s);
    }
    return map;
  }, [detailData]);

  const zones = useMemo(() => [...new Set(sensors.map((s) => s.zone_id))].sort(), [sensors]);

  const filteredSensors = useMemo(() => {
    return sensors
      .filter((s) => {
        if (filter.zoneId && s.zone_id !== filter.zoneId) return false;
        if (filter.status && s.status !== filter.status) return false;
        if ((s.battery_pct ?? 0) < filter.minBattery) return false;
        if ((s.rssi_dbm ?? -200) < filter.minRssi) return false;
        if (filter.search) {
          const q = filter.search.toLowerCase();
          if (!s.sensor_id.toLowerCase().includes(q) && !s.zone_name.toLowerCase().includes(q)) return false;
        }
        return true;
      })
      .sort((a, b) => {
        const dirMul = sortDir === 'asc' ? 1 : -1;
        if (sortKey === 'zone_id') return a.zone_id.localeCompare(b.zone_id) * dirMul;
        if (sortKey === 'status') return a.status.localeCompare(b.status) * dirMul;
        if (sortKey === 'battery_pct') return ((a.battery_pct ?? 0) - (b.battery_pct ?? 0)) * dirMul;
        if (sortKey === 'rssi_dbm') return ((a.rssi_dbm ?? -200) - (b.rssi_dbm ?? -200)) * dirMul;
        if (sortKey === 'last_seen') {
          const aT = a.last_seen ? new Date(a.last_seen).getTime() : 0;
          const bT = b.last_seen ? new Date(b.last_seen).getTime() : 0;
          return (aT - bT) * dirMul;
        }
        return 0;
      });
  }, [sensors, filter, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredSensors.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredSensors.map((s) => s.sensor_id)));
    }
  };

  const avgBattery =
    sensors.length > 0
      ? Math.round(sensors.reduce((sum, s) => sum + (s.battery_pct ?? 0), 0) / sensors.length)
      : null;
  const avgRssi =
    sensors.length > 0
      ? Math.round(sensors.reduce((sum, s) => sum + (s.rssi_dbm ?? 0), 0) / sensors.length)
      : null;
  const activeCount = sensors.filter((s) => s.status === 'active').length;
  const inactiveCount = sensors.filter((s) => s.status === 'inactive').length;
  const offlineCount = sensors.filter((s) => s.status === 'offline').length;

  const isLoading = sensorsLoading || detailLoading;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <Header live={<LiveIndicator lastUpdate={sensorsData?.meta.generated_at ?? null} />} />

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-white">Sensor Grid</h1>
          <button
            className="rounded bg-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-600"
            onClick={() => setRefreshCountdown(30)}
          >
            Refresh ({refreshCountdown}s)
          </button>
        </div>

        {/* Summary Bar */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <SummaryChip label="Total" value={sensors.length} />
          <SummaryChip label="Active" value={activeCount} color="text-green-400" />
          <SummaryChip label="Inactive" value={inactiveCount} color="text-yellow-400" />
          <SummaryChip label="Offline" value={offlineCount} color="text-red-400" />
          <SummaryChip label="Avg Battery" value={avgBattery != null ? `${avgBattery}%` : '—'} color="text-blue-400" />
          <SummaryChip label="Avg RSSI" value={avgRssi != null ? `${avgRssi} dBm` : '—'} color="text-purple-400" />
        </div>

        {/* Filter Bar */}
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-700 bg-slate-800 p-3">
          <FilterField label="Zone">
            <select
              className="rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={filter.zoneId}
              onChange={(e) => setFilter((f) => ({ ...f, zoneId: e.target.value }))}
            >
              <option value="">All Zones</option>
              {zones.map((z) => (
                <option key={z} value={z}>{z}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Status">
            <select
              className="rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={filter.status}
              onChange={(e) => setFilter((f) => ({ ...f, status: e.target.value }))}
            >
              <option value="">All</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="offline">Offline</option>
            </select>
          </FilterField>
          <FilterField label="Min Battery %">
            <input
              type="number"
              min="0"
              max="100"
              className="w-16 rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={filter.minBattery}
              onChange={(e) => setFilter((f) => ({ ...f, minBattery: Number(e.target.value) }))}
            />
          </FilterField>
          <FilterField label="Min RSSI">
            <input
              type="number"
              min="-120"
              max="0"
              className="w-16 rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={filter.minRssi}
              onChange={(e) => setFilter((f) => ({ ...f, minRssi: Number(e.target.value) }))}
            />
          </FilterField>
          <FilterField label="Search">
            <input
              type="text"
              placeholder="Sensor ID or zone…"
              className="rounded border border-slate-600 bg-slate-900 px-2 py-1.5 text-xs text-slate-200"
              value={filter.search}
              onChange={(e) => setFilter((f) => ({ ...f, search: e.target.value }))}
            />
          </FilterField>
          <button
            className="rounded bg-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-600"
            onClick={() =>
              setFilter({ zoneId: '', status: '', minBattery: 0, minRssi: -120, search: '' })
            }
          >
            Clear
          </button>
          {selectedIds.size > 0 && (
            <span className="ml-auto rounded bg-blue-600 px-3 py-1.5 text-xs text-white">
              {selectedIds.size} selected
            </span>
          )}
        </div>

        {/* Sort Controls */}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">Sort by:</span>
          {(['zone_id', 'status', 'battery_pct', 'rssi_dbm', 'last_seen'] as SortKey[]).map(
            (key) => (
              <button
                key={key}
                className={`rounded px-2 py-0.5 capitalize ${
                  sortKey === key ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-300'
                }`}
                onClick={() => handleSort(key)}
              >
                {key.replace(/_/g, ' ')}
                {sortKey === key && (sortDir === 'asc' ? ' ↑' : ' ↓')}
              </button>
            ),
          )}
        </div>

        {/* Loading / Error / Empty */}
        {isLoading && <Spinner label="Chargement des capteurs…" />}
        {sensorsError && (
          <p className="rounded-lg border border-red-800 bg-red-900/30 p-3 text-sm text-red-400">
            Impossible de charger les capteurs.
          </p>
        )}
        {!isLoading && !sensorsError && filteredSensors.length === 0 && (
          <p className="rounded-lg border border-slate-700 bg-slate-800 p-6 text-center text-sm text-slate-500">
            Aucun capteur trouvé.
          </p>
        )}

        {/* Sensor Grid */}
        {!isLoading && filteredSensors.length > 0 && (
          <>
            <div className="mb-2 flex items-center gap-2">
              <input
                type="checkbox"
                checked={selectedIds.size === filteredSensors.length && filteredSensors.length > 0}
                onChange={toggleSelectAll}
                className="rounded"
              />
              <span className="text-xs text-slate-500">Select all</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filteredSensors.map((sensor) => {
                const detail = detailMap.get(sensor.sensor_id);
                const selected = selectedIds.has(sensor.sensor_id);
                const rssi = rssiSignalBars(sensor.rssi_dbm);
                return (
                  <div
                    key={sensor.sensor_id}
                    className={`cursor-pointer rounded-xl border bg-slate-800 p-4 transition-colors hover:border-slate-500 ${
                      selected ? 'border-blue-500 bg-blue-500/10' : 'border-slate-700'
                    }`}
                    onClick={() => {
                      if (detail) setModalSensor(detail);
                    }}
                  >
                    <div className="mb-2 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={selected}
                            className="rounded"
                            onClick={(e) => e.stopPropagation()}
                            onChange={() => toggleSelect(sensor.sensor_id)}
                          />
                        </div>
                        <span className={`h-2.5 w-2.5 rounded-full ${statusColor(sensor.status)}`} />
                        <span className="text-sm font-medium text-white">{sensor.sensor_id}</span>
                      </div>
                      <span className="text-[10px] font-medium uppercase text-slate-500">
                        {sensor.zone_id}
                      </span>
                    </div>

                    <div className="mb-2 flex items-center gap-3 text-xs text-slate-400">
                      <span>{statusText(sensor.status)}</span>
                      <span className={`flex items-center gap-0.5 ${batteryColor(sensor.battery_pct)}`}>
                        {batteryIcon(sensor.battery_pct)}
                        {sensor.battery_pct != null ? `${sensor.battery_pct}%` : '—'}
                      </span>
                      <span className={`flex items-center gap-0.5 ${rssi.color}`}>
                        {Array.from({ length: 5 }).map((_, i) => (
                          <span
                            key={i}
                            className={`inline-block w-1 rounded ${
                              i < rssi.bars ? 'bg-current h-' + (3 + i) : 'bg-slate-700 h-1'
                            }`}
                            style={{ height: i < rssi.bars ? 2 + i * 1.5 : 2 }}
                          />
                        ))}
                        {sensor.rssi_dbm != null ? `${sensor.rssi_dbm} dBm` : '—'}
                      </span>
                    </div>

                    {/* PM2.5 Sparkline */}
                    <div className="mb-2 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {sensor.last_pm25 != null && (
                          <span
                            className="rounded px-1.5 py-0.5 text-xs font-bold text-white"
                            style={{ backgroundColor: pm25ToHexColor(sensor.last_pm25) }}
                          >
                            {sensor.last_pm25.toFixed(1)} µg/m³
                          </span>
                        )}
                      </div>
                      {detail && detail.pm25_history && detail.pm25_history.length > 0 && (
                        <Sparkline data={detail.pm25_history} />
                      )}
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-slate-500">
                      <span>{sensor.last_seen ? formatRelative(sensor.last_seen) : 'Never'}</span>
                      {sensor.firmware && <span>FW {sensor.firmware}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* Sensor Detail Modal */}
        {modalSensor && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
            onClick={() => setModalSensor(null)}
          >
            <div
              className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-bold text-white">{modalSensor.sensor_id}</h2>
                <button
                  className="text-slate-400 hover:text-white"
                  onClick={() => setModalSensor(null)}
                >
                  ✕
                </button>
              </div>
              <div className="space-y-3 text-sm">
                <DetailRow label="Zone" value={modalSensor.zone_name} />
                <DetailRow label="Status" value={statusText(modalSensor.status)}>
                  <span className={`inline-block h-2.5 w-2.5 rounded-full ${statusColor(modalSensor.status)}`} />
                </DetailRow>
                <DetailRow label="Last Seen" value={formatRelative(modalSensor.last_seen)} />
                <DetailRow label="Coordinates" value={`${modalSensor.lat.toFixed(4)}, ${modalSensor.lon.toFixed(4)}`} />
                <DetailRow label="Battery" value={modalSensor.battery_pct != null ? `${modalSensor.battery_pct}%` : '—'} />
                <DetailRow label="RSSI" value={modalSensor.rssi_dbm != null ? `${modalSensor.rssi_dbm} dBm` : '—'} />
                <DetailRow label="Firmware" value={modalSensor.firmware ?? '—'} />
                <DetailRow label="Last PM2.5" value={modalSensor.last_pm25 != null ? `${modalSensor.last_pm25.toFixed(1)} µg/m³` : '—'} />
                <DetailRow label="Messages Today" value={`${modalSensor.messages_today}`} />
                <DetailRow label="SIM" value={modalSensor.sim ? 'Yes' : 'No'} />
                {modalSensor.calibration_coefficients && (
                  <div className="rounded border border-slate-700 bg-slate-800/50 p-3">
                    <p className="mb-1 text-xs font-medium text-slate-400">Calibration Coefficients</p>
                    {Object.entries(modalSensor.calibration_coefficients).map(([k, v]) => (
                      <div key={k} className="flex justify-between text-xs">
                        <span className="text-slate-400">{k}</span>
                        <span className="font-mono text-slate-300">{Number(v).toFixed(4)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function SummaryChip({
  label,
  value,
  color = 'text-slate-300',
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-center">
      <p className={`text-lg font-bold ${color}`}>{value}</p>
      <p className="text-[10px] uppercase text-slate-500">{label}</p>
    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] uppercase text-slate-500">{label}</span>
      {children}
    </div>
  );
}

function DetailRow({
  label,
  value,
  children,
}: {
  label: string;
  value: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-400">{label}</span>
      <span className="flex items-center gap-2 font-medium text-white">
        {children}
        {value}
      </span>
    </div>
  );
}
