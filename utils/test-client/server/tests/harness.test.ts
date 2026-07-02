import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest';
import express from 'express';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { loadConfig } from '../src/config';
import { createHarnessRouter } from '../src/harness';
import { harnessHandlers, READY_SIMULATION } from '../../tests/mocks/harness';

const config = loadConfig({ HARNESS_URL: 'http://harness.test' });
const msw = setupServer(...harnessHandlers('http://harness.test'));

function makeApp() {
  const app = express();
  app.use(express.json());
  app.use('/proxy', createHarnessRouter(config));
  return app;
}

beforeAll(() =>
  msw.listen({
    onUnhandledRequest: (request, print) => {
      // The test issues a real loopback request to the Express app; only the
      // upstream harness fetch should be matched by handlers.
      if (new URL(request.url).hostname === '127.0.0.1') return;
      print.error();
    },
  }),
);
afterEach(() => msw.resetHandlers());
afterAll(() => msw.close());

async function call(
  app: express.Express,
  method: string,
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
) {
  const { default: request } = await import('node:http');
  return await new Promise<{ status: number; json: unknown }>((resolve, reject) => {
    const server = app.listen(0, () => {
      const port = (server.address() as { port: number }).port;
      const data = body ? JSON.stringify(body) : undefined;
      const req = request.request(
        {
          host: '127.0.0.1',
          port,
          path,
          method,
          headers: { 'content-type': 'application/json', ...headers },
        },
        (r) => {
          let buf = '';
          r.on('data', (c) => (buf += c));
          r.on('end', () => {
            server.close();
            resolve({ status: r.statusCode!, json: buf ? JSON.parse(buf) : null });
          });
        },
      );
      req.on('error', (e) => {
        server.close();
        reject(e);
      });
      if (data) req.write(data);
      req.end();
    });
  });
}

describe('harness router', () => {
  it('GET /proxy/simulation forwards and returns the body', async () => {
    const res = await call(makeApp(), 'GET', '/proxy/simulation');
    expect(res.status).toBe(200);
    expect(res.json).toEqual(READY_SIMULATION);
  });

  it('POST /proxy/simulation forwards body and mirrors the 202', async () => {
    const res = await call(makeApp(), 'POST', '/proxy/simulation', { openapi_spec: {} });
    expect(res.status).toBe(202);
  });

  it('POST /proxy/simulation/setup forwards to the upstream setup endpoint', async () => {
    let hit = false;
    msw.use(
      http.post('http://harness.test/api/v1/simulation/setup', async ({ request }) => {
        hit = true;
        expect(await request.json()).toEqual({ openapi_spec: {} });
        return HttpResponse.json({ name: 'x', status: 'pending' }, { status: 202 });
      }),
    );
    const res = await call(makeApp(), 'POST', '/proxy/simulation/setup', { openapi_spec: {} });
    expect(res.status).toBe(202);
    expect(hit).toBe(true);
  });

  it('POST /proxy/simulation/start forwards to the upstream start endpoint', async () => {
    let hit = false;
    msw.use(
      http.post('http://harness.test/api/v1/simulation/start', async ({ request }) => {
        hit = true;
        expect(await request.json()).toEqual({ name: 'demo' });
        return HttpResponse.json({ name: 'demo', status: 'pending' }, { status: 202 });
      }),
    );
    const res = await call(makeApp(), 'POST', '/proxy/simulation/start', { name: 'demo' });
    expect(res.status).toBe(202);
    expect(hit).toBe(true);
  });

  it('mirrors a 404 from start (no baked artifacts) as harness_error', async () => {
    msw.use(
      http.post('http://harness.test/api/v1/simulation/start', () =>
        HttpResponse.json({ detail: 'no artifacts', missing: ['db.json'] }, { status: 404 }),
      ),
    );
    const res = await call(makeApp(), 'POST', '/proxy/simulation/start', { name: 'ghost' });
    expect(res.status).toBe(404);
    expect((res.json as { error: string }).error).toBe('harness_error');
  });

  it('honors the X-Harness-Url header override', async () => {
    msw.use(
      http.get('http://override.test/api/v1/simulation', () =>
        HttpResponse.json({ name: 'overridden' }),
      ),
    );
    const res = await call(makeApp(), 'GET', '/proxy/simulation', undefined, {
      'x-harness-url': 'http://override.test',
    });
    expect((res.json as { name: string }).name).toBe('overridden');
  });

  it('mirrors upstream non-2xx as harness_error', async () => {
    msw.use(
      http.get('http://harness.test/api/v1/simulation', () =>
        HttpResponse.json({ reason: 'session_expired' }, { status: 410 }),
      ),
    );
    const res = await call(makeApp(), 'GET', '/proxy/simulation');
    expect(res.status).toBe(410);
    expect(res.json).toEqual({
      error: 'harness_error',
      upstreamStatus: 410,
      body: { reason: 'session_expired' },
    });
  });
});
