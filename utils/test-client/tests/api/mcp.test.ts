import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../setup';
import { setHarnessUrlGetter } from '@client/api/http';
import * as mcp from '@client/api/mcp';
import { MCP_TOOLS } from '../mocks/harness';

const ORIGIN = 'http://localhost:3000';
beforeEach(() => setHarnessUrlGetter(() => 'http://localhost:8086'));

describe('mcp api', () => {
  it('listTools returns the tool array', async () => {
    server.use(http.post(`${ORIGIN}/proxy/mcp/list-tools`, () => HttpResponse.json(MCP_TOOLS)));
    const res = await mcp.listTools();
    expect(res.data).toEqual(MCP_TOOLS);
  });

  it('callTool posts name+arguments and returns content/isError', async () => {
    let body: unknown;
    server.use(
      http.post(`${ORIGIN}/proxy/mcp/call-tool`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ content: 'ok', isError: false });
      }),
    );
    const res = await mcp.callTool('list_items', { a: 1 });
    expect(body).toEqual({ name: 'list_items', arguments: { a: 1 } });
    expect(res.data).toEqual({ content: 'ok', isError: false });
  });

  it('surfaces an isError result without throwing', async () => {
    server.use(
      http.post(`${ORIGIN}/proxy/mcp/call-tool`, () =>
        HttpResponse.json({ content: 'tool failed', isError: true }),
      ),
    );
    const res = await mcp.callTool('boom', {});
    expect(res.data.isError).toBe(true);
  });
});
