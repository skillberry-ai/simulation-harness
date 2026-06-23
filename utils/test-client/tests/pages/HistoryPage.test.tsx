import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HistoryPage } from '@client/pages/HistoryPage';
import { toExportJson } from '@client/history-export';
import { useHistoryStore } from '@client/state/useHistoryStore';
import type { RequestRecord } from '@client/state/types';

function rec(over: Partial<RequestRecord> = {}): RequestRecord {
  return {
    id: 'r1',
    timestamp: '2026-06-22T10:00:00Z',
    method: 'GET',
    endpoint: '/proxy/simulation',
    requestData: null,
    responseStatus: 200,
    responseData: { ok: true },
    durationMs: 12,
    error: null,
    ...over,
  };
}

beforeEach(() => useHistoryStore.getState().clear());

describe('toExportJson', () => {
  it('serializes records as pretty JSON', () => {
    expect(toExportJson([rec()])).toContain('"endpoint": "/proxy/simulation"');
  });
});

describe('HistoryPage', () => {
  it('shows the empty state with no records', () => {
    render(<HistoryPage />);
    expect(screen.getByText(/no requests yet/i)).toBeInTheDocument();
  });

  it('renders rows and clears them', async () => {
    const user = userEvent.setup();
    useHistoryStore.getState().add(rec());
    render(<HistoryPage />);
    expect(screen.getByText('/proxy/simulation')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /clear/i }));
    expect(screen.getByText(/no requests yet/i)).toBeInTheDocument();
  });
});
