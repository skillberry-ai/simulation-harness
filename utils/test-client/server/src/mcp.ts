import { Router, type Request, type Response } from 'express';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import type { ProxyConfig } from './config.js';
import { resolveHarnessUrl } from './config.js';
import { sendMcpError } from './errors.js';

export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

type Transport = 'sse' | 'streamable-http';

async function connectClient(harnessUrl: string, transport: Transport): Promise<Client> {
  const client = new Client({ name: 'test-client-proxy', version: '1.0.0' }, { capabilities: {} });
  const endpoint =
    transport === 'sse' ? new URL(`${harnessUrl}/mcp/sse`) : new URL(`${harnessUrl}/mcp`);
  const t =
    transport === 'sse'
      ? new SSEClientTransport(endpoint)
      : new StreamableHTTPClientTransport(endpoint);
  await client.connect(t);
  return client;
}

export async function listTools(harnessUrl: string, transport: Transport): Promise<McpTool[]> {
  const client = await connectClient(harnessUrl, transport);
  try {
    const result = await client.listTools();
    return result.tools.map((t) => ({
      name: t.name,
      description: t.description ?? '',
      inputSchema: (t.inputSchema ?? {}) as Record<string, unknown>,
    }));
  } finally {
    await client.close();
  }
}

export async function callTool(
  harnessUrl: string,
  transport: Transport,
  name: string,
  args: Record<string, unknown>,
): Promise<{ content: string; isError: boolean }> {
  const client = await connectClient(harnessUrl, transport);
  try {
    const result = await client.callTool({ name, arguments: args });
    const blocks = Array.isArray(result.content) ? result.content : [];
    const content = blocks
      .filter((b): b is { type: 'text'; text: string } => b.type === 'text')
      .map((b) => b.text)
      .join('\n');
    return { content, isError: Boolean(result.isError) };
  } finally {
    await client.close();
  }
}

export function createMcpRouter(
  config: ProxyConfig,
  deps: { listTools?: typeof listTools; callTool?: typeof callTool } = {},
): Router {
  const doList = deps.listTools ?? listTools;
  const doCall = deps.callTool ?? callTool;
  const router = Router();

  router.post('/mcp/list-tools', async (req: Request, res: Response) => {
    const base = resolveHarnessUrl(config, req.header('x-harness-url'));
    try {
      res.json(await doList(base, config.mcpTransport));
    } catch (err) {
      sendMcpError(res, err instanceof Error ? err.message : String(err));
    }
  });

  router.post('/mcp/call-tool', async (req: Request, res: Response) => {
    const base = resolveHarnessUrl(config, req.header('x-harness-url'));
    const { name, arguments: args } = req.body as {
      name: string;
      arguments?: Record<string, unknown>;
    };
    try {
      res.json(await doCall(base, config.mcpTransport, name, args ?? {}));
    } catch (err) {
      sendMcpError(res, err instanceof Error ? err.message : String(err));
    }
  });

  return router;
}
