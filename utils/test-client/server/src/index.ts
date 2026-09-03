import express from 'express';
import rateLimit from 'express-rate-limit';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import { loadConfig, type ProxyConfig } from './config.js';
import { createHarnessRouter } from './harness.js';
import { createMcpRouter } from './mcp.js';

/** Bounds runaway or scripted traffic against the proxy routes. */
export function createProxyRateLimit(config: ProxyConfig) {
  return rateLimit({
    windowMs: config.rateLimitWindowMs,
    limit: config.rateLimitMax,
    standardHeaders: 'draft-7',
    legacyHeaders: false,
    message: { error: 'rate_limited', message: 'Too many proxy requests; slow down.' },
  });
}

export function createApp(config: ProxyConfig): express.Express {
  const app = express();
  app.use(express.json({ limit: '10mb' }));
  app.use('/proxy', createProxyRateLimit(config));
  app.use('/proxy', createHarnessRouter(config));
  app.use('/proxy', createMcpRouter(config));

  const distDir = path.resolve(fileURLToPath(new URL('../../client/dist', import.meta.url)));
  if (fs.existsSync(distDir)) {
    app.use(express.static(distDir));
    app.get('*', (_req, res) => res.sendFile(path.join(distDir, 'index.html')));
  }
  return app;
}

export function start(): void {
  const config = loadConfig(process.env);
  const app = createApp(config);
  app.listen(config.port, () => {
    // eslint-disable-next-line no-console
    console.log(
      `test-client proxy on :${config.port} → ${config.harnessUrl} (mcp: ${config.mcpTransport})`,
    );
  });
}

const isMain = process.argv[1] === fileURLToPath(import.meta.url);
if (isMain) start();
