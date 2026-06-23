import { Router, type Request, type Response } from 'express';
import type { ProxyConfig } from './config.js';
import { resolveHarnessUrl } from './config.js';
import { sendUpstreamError, sendUnreachable } from './errors.js';

interface Forward {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  /** Path on the harness, may include a query string suffix from req. */
  upstreamPath: (req: Request) => string;
  hasBody?: boolean;
}

async function forward(
  config: ProxyConfig,
  spec: Forward,
  req: Request,
  res: Response,
): Promise<void> {
  const base = resolveHarnessUrl(config, req.header('x-harness-url'));
  const url = `${base}${spec.upstreamPath(req)}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.restTimeoutMs);
  try {
    const upstream = await fetch(url, {
      method: spec.method,
      headers: { 'content-type': 'application/json' },
      body: spec.hasBody ? JSON.stringify(req.body) : undefined,
      signal: controller.signal,
    });
    const text = await upstream.text();
    const parsed = text ? JSON.parse(text) : null;
    if (upstream.ok) {
      res.status(upstream.status).json(parsed);
    } else {
      sendUpstreamError(res, upstream.status, parsed);
    }
  } catch (err) {
    sendUnreachable(res, err instanceof Error ? err.message : String(err));
  } finally {
    clearTimeout(timer);
  }
}

export function createHarnessRouter(config: ProxyConfig): Router {
  const router = Router();
  const f = (spec: Forward) => (req: Request, res: Response) => forward(config, spec, req, res);

  router.get('/health', f({ method: 'GET', upstreamPath: () => '/health' }));
  router.post(
    '/simulation',
    f({ method: 'POST', upstreamPath: () => '/api/v1/simulation', hasBody: true }),
  );
  router.get('/simulation', f({ method: 'GET', upstreamPath: () => '/api/v1/simulation' }));
  router.delete('/simulation', f({ method: 'DELETE', upstreamPath: () => '/api/v1/simulation' }));
  router.post(
    '/simulation/reset',
    f({ method: 'POST', upstreamPath: () => '/api/v1/simulation/reset' }),
  );
  router.get(
    '/simulation/state',
    f({
      method: 'GET',
      upstreamPath: (req) =>
        `/api/v1/simulation/state?thread_id=${encodeURIComponent(String(req.query.thread_id ?? 'default'))}`,
    }),
  );
  router.get(
    '/simulation/schema',
    f({ method: 'GET', upstreamPath: () => '/api/v1/simulation/schema' }),
  );
  router.get(
    '/simulation/database',
    f({ method: 'GET', upstreamPath: () => '/api/v1/simulation/database' }),
  );
  router.put(
    '/simulation/database',
    f({ method: 'PUT', upstreamPath: () => '/api/v1/simulation/database', hasBody: true }),
  );

  return router;
}
