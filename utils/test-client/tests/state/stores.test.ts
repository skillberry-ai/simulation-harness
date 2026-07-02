import { describe, it, expect, beforeEach } from 'vitest';
import { useConnectionStore } from '@client/state/useConnectionStore';
import { useSimulationStore } from '@client/state/useSimulationStore';
import { useHistoryStore, HISTORY_CAP } from '@client/state/useHistoryStore';
import type { RequestRecord } from '@client/state/types';

function rec(id: string): RequestRecord {
  return {
    id,
    timestamp: '2026-06-22T00:00:00Z',
    method: 'GET',
    endpoint: '/x',
    requestData: null,
    responseStatus: 200,
    responseData: null,
    durationMs: 1,
    error: null,
  };
}

beforeEach(() => {
  localStorage.clear();
  useConnectionStore.setState({
    harnessUrl: 'http://localhost:8086',
    connected: false,
    lastHealthMs: null,
    connectionError: null,
  });
  useSimulationStore.getState().clear();
  useHistoryStore.getState().clear();
});

describe('connection store', () => {
  it('records a successful health check', () => {
    useConnectionStore.getState().setConnected(32);
    expect(useConnectionStore.getState()).toMatchObject({
      connected: true,
      lastHealthMs: 32,
      connectionError: null,
    });
  });
  it('records a failure', () => {
    useConnectionStore.getState().setFailed('refused');
    expect(useConnectionStore.getState()).toMatchObject({
      connected: false,
      connectionError: 'refused',
    });
  });
  it('persists harnessUrl to localStorage', () => {
    useConnectionStore.getState().setHarnessUrl('http://x:1');
    expect(localStorage.getItem('tc.connection')).toContain('http://x:1');
  });
});

describe('simulation store', () => {
  it('hydrates from a response and clears', () => {
    useSimulationStore
      .getState()
      .setFromResponse({ name: 'demo', status: 'ready', created_at: 't', mcp_url: 'e' });
    expect(useSimulationStore.getState()).toMatchObject({
      name: 'demo',
      status: 'ready',
      mcpEndpoint: 'e',
    });
    useSimulationStore.getState().clear();
    expect(useSimulationStore.getState().name).toBeNull();
    expect(useSimulationStore.getState().mcpToolsLoaded).toBe(false);
  });
});

describe('history store', () => {
  it('prepends newest-first', () => {
    useHistoryStore.getState().add(rec('a'));
    useHistoryStore.getState().add(rec('b'));
    expect(useHistoryStore.getState().records.map((r) => r.id)).toEqual(['b', 'a']);
  });
  it('caps at HISTORY_CAP newest records', () => {
    for (let i = 0; i < HISTORY_CAP + 10; i++) useHistoryStore.getState().add(rec(String(i)));
    const records = useHistoryStore.getState().records;
    expect(records).toHaveLength(HISTORY_CAP);
    expect(records[0].id).toBe(String(HISTORY_CAP + 9));
  });
});
