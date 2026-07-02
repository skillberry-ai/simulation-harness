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
      data: { name: 'x', status: 'pending', created_at: 't', mcp_url: null },
      status: 200,
      durationMs: 1,
    });
    spy.mockResolvedValueOnce({
      data: { name: 'x', status: 'ready', created_at: 't', mcp_url: 'e' },
      status: 200,
      durationMs: 1,
    });
    const promise = pollUntilTerminal({ intervalMs: 500, deadlineMs: 180000 });
    await vi.advanceTimersByTimeAsync(600);
    const result = await promise;
    expect(result?.status).toBe('ready');
  });

  it('stops at "generated" when until targets the setup terminal', async () => {
    const spy = vi.spyOn(harness, 'getSimulation');
    spy.mockResolvedValueOnce({
      data: { name: 'x', status: 'pending', created_at: 't', mcp_url: null },
      status: 200,
      durationMs: 1,
    });
    spy.mockResolvedValueOnce({
      data: { name: 'x', status: 'generated', created_at: 't', mcp_url: null },
      status: 200,
      durationMs: 1,
    });
    const promise = pollUntilTerminal({
      intervalMs: 500,
      deadlineMs: 180000,
      until: ['generated', 'failed'],
    });
    await vi.advanceTimersByTimeAsync(600);
    expect((await promise)?.status).toBe('generated');
  });

  it('does not stop at "generated" under the default terminals', async () => {
    const spy = vi.spyOn(harness, 'getSimulation');
    spy.mockResolvedValue({
      data: { name: 'x', status: 'generated', created_at: 't', mcp_url: null },
      status: 200,
      durationMs: 1,
    });
    const promise = pollUntilTerminal({ intervalMs: 500, deadlineMs: 1000 });
    await vi.advanceTimersByTimeAsync(2000);
    expect(await promise).toBeNull();
  });

  it('returns null when the deadline elapses', async () => {
    vi.spyOn(harness, 'getSimulation').mockResolvedValue({
      data: { name: 'x', status: 'pending', created_at: 't', mcp_url: null },
      status: 200,
      durationMs: 1,
    });
    const promise = pollUntilTerminal({ intervalMs: 500, deadlineMs: 1000 });
    await vi.advanceTimersByTimeAsync(2000);
    expect(await promise).toBeNull();
  });
});
