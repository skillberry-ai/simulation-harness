import { describe, it, expect } from 'vitest';
import express from 'express';
import { loadConfig } from '../src/config';
import { createProxyRateLimit } from '../src/index';

/** Drives the limiter directly through a throwaway app on an ephemeral port. */
async function hit(app: express.Express, times: number): Promise<number[]> {
  const { default: http } = await import('node:http');
  const server = app.listen(0);
  await new Promise((r) => server.once('listening', r));
  const { port } = server.address() as { port: number };

  const statuses: number[] = [];
  for (let i = 0; i < times; i += 1) {
    statuses.push(
      await new Promise<number>((resolve, reject) => {
        const req = http.request(
          { host: '127.0.0.1', port, path: '/proxy/x', method: 'GET' },
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
