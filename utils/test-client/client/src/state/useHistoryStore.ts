import { create } from 'zustand';
import type { RequestRecord } from './types';

export const HISTORY_CAP = 200;

interface HistoryState {
  records: RequestRecord[];
  add: (record: RequestRecord) => void;
  clear: () => void;
}

export const useHistoryStore = create<HistoryState>()((set) => ({
  records: [],
  add: (record) => set((s) => ({ records: [record, ...s.records].slice(0, HISTORY_CAP) })),
  clear: () => set({ records: [] }),
}));
