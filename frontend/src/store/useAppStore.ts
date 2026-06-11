// État global minimal (FRONTEND_SPEC.md §4.3) — Zustand
import { create } from 'zustand';

export type HistoryPeriod = '24h' | '7j' | '30j';

interface AppStore {
  selectedZoneId: string | null;
  setSelectedZone: (zoneId: string | null) => void;
  historyPeriod: HistoryPeriod;
  setHistoryPeriod: (p: HistoryPeriod) => void;
}

export const useAppStore = create<AppStore>((set) => ({
  selectedZoneId: null,
  setSelectedZone: (zoneId) => set({ selectedZoneId: zoneId }),
  historyPeriod: '24h',
  setHistoryPeriod: (historyPeriod) => set({ historyPeriod }),
}));
