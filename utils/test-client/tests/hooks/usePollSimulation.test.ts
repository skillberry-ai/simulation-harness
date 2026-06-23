import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { pollUntilTerminal } from '@client/hooks/usePollSimulation';
import * as harness from '@client/api/harness';

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('pollUntilTerminal', () => {
  it('resolves when status becomes ready', async () => {
    const spy = vi.spyOn(harness, 'getSimulation');
    spy.mockResolvedValueOnce({
      data: { name: 'x', status: 'pending', created_at: 't', mcp_endpoint: null },
      status: 200,
      durationMs: 1,
    });
    spy.mockResolvedValueOnce({
      data: { name: 'x', status: 'ready', created_at: 't', mcp_endpoint: 'e' },
      status: 200,
      durationMs: 1,
    });
    const promise = pollUntilTerminal({ intervalMs: 500, deadlineMs: 180000 });
    await vi.advanceTimersByTimeAsync(600);
    const result = await promise;
    expect(result?.status).toBe('ready');
  });

  it('returns null when the deadline elapses', async () => {
    vi.spyOn(harness, 'getSimulation').mockResolvedValue({
      data: { name: 'x', status: 'pending', created_at: 't', mcp_endpoint: null },
      status: 200,
      durationMs: 1,
    });
    const promise = pollUntilTerminal({ intervalMs: 500, deadlineMs: 1000 });
    await vi.advanceTimersByTimeAsync(2000);
    expect(await promise).toBeNull();
  });
});
