import { describe, it, expect, beforeEach } from 'vitest';
import { runApi, composeErrorMessage } from '@client/hooks/useApi';
import { ApiError } from '@client/api/http';
import { useHistoryStore } from '@client/state/useHistoryStore';
import { useNotifications } from '@client/notifications/useNotifications';

beforeEach(() => {
  useHistoryStore.getState().clear();
  useNotifications.setState({ notices: [] });
});

describe('runApi', () => {
  it('records success and returns data', async () => {
    const data = await runApi({
      method: 'GET',
      endpoint: '/proxy/health',
      call: async () => ({ data: { status: 'ok' }, status: 200, durationMs: 5 }),
    });
    expect(data).toEqual({ status: 'ok' });
    const rec = useHistoryStore.getState().records[0];
    expect(rec).toMatchObject({
      method: 'GET',
      endpoint: '/proxy/health',
      responseStatus: 200,
      error: null,
    });
  });

  it('records failure, toasts, and returns null', async () => {
    const result = await runApi({
      method: 'GET',
      endpoint: '/proxy/simulation',
      call: async () => {
        throw new ApiError(
          410,
          { error: 'harness_error', upstreamStatus: 410, body: { reason: 'session_expired' } },
          'harness_error',
        );
      },
    });
    expect(result).toBeNull();
    expect(useHistoryStore.getState().records[0].error).toContain('session_expired');
    expect(useNotifications.getState().notices[0].variant).toBe('danger');
  });

  it('composeErrorMessage surfaces the MCP reason code', () => {
    const err = new ApiError(
      410,
      { error: 'harness_error', body: { reason: 'session_expired' } },
      'harness_error',
    );
    expect(composeErrorMessage(err)).toContain('session_expired');
  });
});
