import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

interface ConnectionState {
  harnessUrl: string;
  connected: boolean;
  lastHealthMs: number | null;
  connectionError: string | null;
  setHarnessUrl: (url: string) => void;
  setConnected: (ms: number) => void;
  setFailed: (error: string) => void;
  setUnknown: () => void;
}

export const useConnectionStore = create<ConnectionState>()(
  persist(
    (set) => ({
      harnessUrl: 'http://localhost:8086',
      connected: false,
      lastHealthMs: null,
      connectionError: null,
      setHarnessUrl: (harnessUrl) => set({ harnessUrl, connected: false, connectionError: null }),
      setConnected: (lastHealthMs) => set({ connected: true, lastHealthMs, connectionError: null }),
      setFailed: (connectionError) => set({ connected: false, connectionError }),
      setUnknown: () => set({ connected: false, connectionError: null, lastHealthMs: null }),
    }),
    {
      name: 'tc.connection',
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ harnessUrl: s.harnessUrl }),
    },
  ),
);
