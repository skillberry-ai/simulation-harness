import { describe, it, expect } from 'vitest';
import express from 'express';
import { loadConfig } from '../src/config';
import { createMcpRouter } from '../src/mcp';
import { MCP_TOOLS } from '../../tests/mocks/harness';

const config = loadConfig({});

function makeApp(deps: Parameters<typeof createMcpRouter>[1]) {
  const app = express();
  app.use(express.json());
  app.use('/proxy', createMcpRouter(config, deps));
  return app;
}

async function call(app: express.Express, path: string, body: unknown) {
  const http = await import('node:http');
  return await new Promise<{ status: number; json: unknown }>((resolve, reject) => {
    const server = app.listen(0, () => {
      const port = (server.address() as { port: number }).port;
      const data = JSON.stringify(body);
      const req = http.request(
        {
          host: '127.0.0.1',
          port,
          path,
          method: 'POST',
          headers: { 'content-type': 'application/json' },
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
      req.write(data);
      req.end();
    });
  });
}

describe('mcp router', () => {
  it('list-tools returns the stubbed tools', async () => {
    const app = makeApp({
      listTools: async () => MCP_TOOLS,
      callTool: async () => ({ content: '', isError: false }),
    });
    const res = await call(app, '/proxy/mcp/list-tools', {});
    expect(res.status).toBe(200);
    expect(res.json).toEqual(MCP_TOOLS);
  });

  it('call-tool returns content and isError', async () => {
    const app = makeApp({
      listTools: async () => [],
      callTool: async (_u, _t, name, args) => ({
        content: `${name}:${JSON.stringify(args)}`,
        isError: false,
      }),
    });
    const res = await call(app, '/proxy/mcp/call-tool', {
      name: 'list_items',
      arguments: { a: 1 },
    });
    expect(res.json).toEqual({ content: 'list_items:{"a":1}', isError: false });
  });

  it('maps SDK exceptions to 502 mcp_error', async () => {
    const app = makeApp({
      listTools: async () => {
        throw new Error('transport down');
      },
      callTool: async () => ({ content: '', isError: false }),
    });
    const res = await call(app, '/proxy/mcp/list-tools', {});
    expect(res.status).toBe(502);
    expect(res.json).toEqual({ error: 'mcp_error', message: 'transport down' });
  });
});
