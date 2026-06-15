// État global minimal (FRONTEND_SPEC.md §4.3) — Zustand
import { create } from 'zustand';

export type HistoryPeriod = '24h' | '7j' | '30j';

export interface Zone { id: string; name: string; path?: string }

interface AppStore {
  zones: Zone[];
  setZones: (z: Zone[]) => void;
  activeZone: string | null;
  setActiveZone: (id: string | null) => void;
  historyPeriod: HistoryPeriod;
  setHistoryPeriod: (p: HistoryPeriod) => void;
}

export const useAppStore = create<AppStore>((set) => ({
  zones: [],
  setZones: (zones) => set({ zones }),
  activeZone: null,
  setActiveZone: (activeZone) => set({ activeZone }),
  historyPeriod: '24h',
  setHistoryPeriod: (historyPeriod) => set({ historyPeriod }),
}));
