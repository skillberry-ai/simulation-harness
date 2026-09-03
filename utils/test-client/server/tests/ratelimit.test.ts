import { describe, it, expect } from 'vitest';
import express from 'express';
import { loadConfig } from '../src/config';
import { createProxyRateLimit, createStaticRateLimit } from '../src/index';

/** Drives the limiter directly through a throwaway app on an ephemeral port. */
async function hit(app: express.Express, times: number, reqPath = '/proxy/x'): Promise<number[]> {
  const { default: http } = await import('node:http');
  const server = app.listen(0);
  await new Promise((r) => server.once('listening', r));
  const { port } = server.address() as { port: number };

  const statuses: number[] = [];
  for (let i = 0; i < times; i += 1) {
    statuses.push(
      await new Promise<number>((resolve, reject) => {
        const req = http.request(
          { host: '127.0.0.1', port, path: reqPath, method: 'GET' },
          (res) => {
            res.resume();
            res.once('end', () => resolve(res.statusCode ?? 0));
          },
        );
        req.once('error', reject);
        req.end();
      }),
    );
  }
  await new Promise((r) => server.close(r));
  return statuses;
}

function appWithLimit(max: number): express.Express {
  const app = express();
  app.use('/proxy', createProxyRateLimit(loadConfig({ RATE_LIMIT_MAX: String(max) })));
  app.get('/proxy/x', (_req, res) => {
    res.json({ ok: true });
  });
  return app;
}

describe('proxy rate limiting', () => {
  it('allows requests up to the limit and returns 429 past it', async () => {
    const statuses = await hit(appWithLimit(3), 5);
    expect(statuses).toEqual([200, 200, 200, 429, 429]);
  });

  it('does not limit below the threshold', async () => {
    const statuses = await hit(appWithLimit(10), 5);
    expect(statuses.every((s) => s === 200)).toBe(true);
  });
});

/**
 * Mirrors the static/SPA half of `createApp`: an unpathed limiter ahead of the
 * filesystem handlers. Guards the fix for the missing-rate-limiting alert —
 * previously the only limiter was mounted at `/proxy`, leaving `express.static`
 * and the `*` fallback (both of which read from disk) unmetered.
 */
function appWithStaticLimit(max: number): express.Express {
  const app = express();
  app.use('/proxy', createProxyRateLimit(loadConfig({ RATE_LIMIT_MAX: '1000' })));
  app.use(createStaticRateLimit(loadConfig({ RATE_LIMIT_MAX: String(max) })));
  app.get('*', (_req, res) => {
    res.json({ ok: true });
  });
  return app;
}

describe('static and SPA-fallback rate limiting', () => {
  it('meters the SPA fallback route', async () => {
    const statuses = await hit(appWithStaticLimit(3), 5, '/some/deep/route');
    expect(statuses).toEqual([200, 200, 200, 429, 429]);
  });

  it('meters the site root', async () => {
    const statuses = await hit(appWithStaticLimit(2), 4, '/');
    expect(statuses).toEqual([200, 200, 429, 429]);
  });

  it('keeps a counter independent of the proxy limiter', async () => {
    // Spending the static budget must not lock out /proxy, and vice versa.
    const app = appWithStaticLimit(2);
    expect(await hit(app, 3, '/')).toEqual([200, 200, 429]);
  });
});
