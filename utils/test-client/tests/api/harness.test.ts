import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../setup';
import { setHarnessUrlGetter, ApiError } from '@client/api/http';
import * as harness from '@client/api/harness';
import { READY_SIMULATION, PENDING_SIMULATION, HEALTH_OK, SCHEMA } from '../mocks/harness';

const ORIGIN = 'http://localhost:3000';

beforeEach(() => setHarnessUrlGetter(() => 'http://localhost:8086'));

describe('harness api', () => {
  it('health() returns parsed data, status, and a duration', async () => {
    server.use(http.get(`${ORIGIN}/proxy/health`, () => HttpResponse.json(HEALTH_OK)));
    const res = await harness.health();
    expect(res.data).toEqual(HEALTH_OK);
    expect(res.status).toBe(200);
    expect(res.durationMs).toBeGreaterThanOrEqual(0);
  });

  it('createSimulation posts the spec/name/regenerate and returns 202', async () => {
    let received: unknown;
    server.use(
      http.post(`${ORIGIN}/proxy/simulation`, async ({ request }) => {
        received = await request.json();
        return HttpResponse.json(PENDING_SIMULATION, { status: 202 });
      }),
    );
    const res = await harness.createSimulation({ openapi: '3.0.0' }, 'demo', true);
    expect(res.status).toBe(202);
    expect(received).toEqual({
      openapi_spec: { openapi: '3.0.0' },
      name: 'demo',
      regenerate_skill: true,
    });
  });

  it('omits name when not provided', async () => {
    let received: Record<string, unknown> = {};
    server.use(
      http.post(`${ORIGIN}/proxy/simulation`, async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(PENDING_SIMULATION, { status: 202 });
      }),
    );
    await harness.createSimulation({}, null, false);
    expect('name' in received).toBe(false);
  });

  it('setupSimulation posts to /simulation/setup with spec/name/regenerate', async () => {
    let received: unknown;
    server.use(
      http.post(`${ORIGIN}/proxy/simulation/setup`, async ({ request }) => {
        received = await request.json();
        return HttpResponse.json(PENDING_SIMULATION, { status: 202 });
      }),
    );
    const res = await harness.setupSimulation({ openapi: '3.0.0' }, 'demo', true);
    expect(res.status).toBe(202);
    expect(received).toEqual({
      openapi_spec: { openapi: '3.0.0' },
      name: 'demo',
      regenerate_skill: true,
    });
  });

  it('startSimulation posts to /simulation/start with name and mcp_port', async () => {
    let received: unknown;
    server.use(
      http.post(`${ORIGIN}/proxy/simulation/start`, async ({ request }) => {
        received = await request.json();
        return HttpResponse.json(PENDING_SIMULATION, { status: 202 });
      }),
    );
    await harness.startSimulation('demo-api', 9000);
    expect(received).toEqual({ name: 'demo-api', mcp_port: 9000 });
  });

  it('startSimulation omits mcp_port when not provided', async () => {
    let received: Record<string, unknown> = {};
    server.use(
      http.post(`${ORIGIN}/proxy/simulation/start`, async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(PENDING_SIMULATION, { status: 202 });
      }),
    );
    await harness.startSimulation('demo-api');
    expect(received).toEqual({ name: 'demo-api' });
    expect('mcp_port' in received).toBe(false);
  });

  it('getSimulation/getSchema forward and parse', async () => {
    server.use(
      http.get(`${ORIGIN}/proxy/simulation`, () => HttpResponse.json(READY_SIMULATION)),
      http.get(`${ORIGIN}/proxy/simulation/schema`, () => HttpResponse.json(SCHEMA)),
    );
    expect((await harness.getSimulation()).data).toEqual(READY_SIMULATION);
    expect((await harness.getSchema()).data).toEqual(SCHEMA);
  });

  it('getState passes thread_id as a query param', async () => {
    let url = '';
    server.use(
      http.get(`${ORIGIN}/proxy/simulation/state`, ({ request }) => {
        url = request.url;
        return HttpResponse.json({ ok: true });
      }),
    );
    await harness.getState('abc');
    expect(url).toContain('thread_id=abc');
  });

  it('deleteSimulation tolerates a 204 empty body', async () => {
    server.use(
      http.delete(`${ORIGIN}/proxy/simulation`, () => new HttpResponse(null, { status: 204 })),
    );
    const res = await harness.deleteSimulation();
    expect(res.status).toBe(204);
    expect(res.data).toBeNull();
  });

  it('throws ApiError carrying status and body on non-2xx', async () => {
    server.use(
      http.get(`${ORIGIN}/proxy/simulation`, () =>
        HttpResponse.json(
          { error: 'harness_error', upstreamStatus: 410, body: { reason: 'session_expired' } },
          { status: 410 },
        ),
      ),
    );
    await expect(harness.getSimulation()).rejects.toMatchObject({
      name: 'ApiError',
      status: 410,
      body: {
        error: 'harness_error',
        upstreamStatus: 410,
        body: { reason: 'session_expired' },
      },
    });
  });

  it('attaches the X-Harness-Url header from the registered getter', async () => {
    setHarnessUrlGetter(() => 'http://custom:9');
    let header: string | null = null;
    server.use(
      http.get(`${ORIGIN}/proxy/health`, ({ request }) => {
        header = request.headers.get('x-harness-url');
        return HttpResponse.json(HEALTH_OK);
      }),
    );
    await harness.health();
    expect(header).toBe('http://custom:9');
  });
});

// Reference ApiError so the import is exercised even if the matcher path changes.
void ApiError;
