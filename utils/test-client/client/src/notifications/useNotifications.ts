import { create } from 'zustand';

export interface Notice {
  id: number;
  variant: 'success' | 'danger' | 'info' | 'warning';
  title: string;
}

let counter = 0;

interface NotificationState {
  notices: Notice[];
  notify: (variant: Notice['variant'], title: string) => void;
  dismiss: (id: number) => void;
}

export const useNotifications = create<NotificationState>()((set) => ({
  notices: [],
  notify: (variant, title) =>
    set((s) => ({ notices: [...s.notices, { id: ++counter, variant, title }] })),
  dismiss: (id) => set((s) => ({ notices: s.notices.filter((n) => n.id !== id) })),
}));
