import express from 'express';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import { loadConfig, type ProxyConfig } from './config.js';
import { createHarnessRouter } from './harness.js';
import { createMcpRouter } from './mcp.js';

export function createApp(config: ProxyConfig): express.Express {
  const app = express();
  app.use(express.json({ limit: '10mb' }));
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
