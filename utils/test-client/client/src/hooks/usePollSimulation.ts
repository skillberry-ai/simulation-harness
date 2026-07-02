import { useEffect, useRef } from 'react';
import { getSimulation } from '../api/harness';
import type { SimulationResponse } from '../state/types';

const sleep = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(t);
        resolve();
      },
      { once: true },
    );
  });

export async function pollUntilTerminal(
  opts: {
    intervalMs?: number;
    deadlineMs?: number;
    signal?: AbortSignal;
    /** Statuses that end polling. Defaults to the running-simulation terminals. */
    until?: string[];
  } = {},
): Promise<SimulationResponse | null> {
  const intervalMs = opts.intervalMs ?? 500;
  const deadlineMs = opts.deadlineMs ?? 180000;
  const until = opts.until ?? ['ready', 'failed'];
  // Date.now() (not performance.now()) so Vitest fake timers can drive the deadline.
  const start = Date.now();
  while (Date.now() - start < deadlineMs) {
    if (opts.signal?.aborted) return null;
    const res = await getSimulation();
    if (until.includes(res.data.status)) return res.data;
    await sleep(intervalMs, opts.signal);
  }
  return null;
}

export function usePollSimulation() {
  const ref = useRef<AbortController | null>(null);
  useEffect(() => () => ref.current?.abort(), []);
  return (overrides?: { intervalMs?: number; deadlineMs?: number; until?: string[] }) => {
    ref.current?.abort();
    ref.current = new AbortController();
    return pollUntilTerminal({ ...overrides, signal: ref.current.signal });
  };
}
