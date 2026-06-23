import { ApiError, type HttpResult } from '../api/http';
import { useHistoryStore } from '../state/useHistoryStore';
import { useNotifications } from '../notifications/useNotifications';
import type { RequestRecord } from '../state/types';

let recordCounter = 0;
export const nextRecordId = (): string => `r${++recordCounter}`;

export function composeErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { error?: string; body?: { reason?: string } } | null;
    const base = body?.error ?? err.message;
    const reason = body?.body?.reason;
    return reason ? `${base}: ${reason}` : base;
  }
  return err instanceof Error ? err.message : String(err);
}

function pushRecord(partial: Omit<RequestRecord, 'id' | 'timestamp'>): void {
  useHistoryStore.getState().add({
    id: nextRecordId(),
    timestamp: new Date().toISOString(),
    ...partial,
  });
}

export async function runApi<T>(opts: {
  method: string;
  endpoint: string;
  requestData?: unknown;
  call: () => Promise<HttpResult<T>>;
}): Promise<T | null> {
  try {
    const res = await opts.call();
    pushRecord({
      method: opts.method,
      endpoint: opts.endpoint,
      requestData: opts.requestData ?? null,
      responseStatus: res.status,
      responseData: res.data as unknown,
      durationMs: res.durationMs,
      error: null,
    });
    return res.data;
  } catch (err) {
    const message = composeErrorMessage(err);
    pushRecord({
      method: opts.method,
      endpoint: opts.endpoint,
      requestData: opts.requestData ?? null,
      responseStatus: err instanceof ApiError ? err.status : 0,
      responseData: err instanceof ApiError ? err.body : null,
      durationMs: 0,
      error: message,
    });
    useNotifications.getState().notify('danger', message);
    return null;
  }
}

export function useApi() {
  return { runApi };
}
