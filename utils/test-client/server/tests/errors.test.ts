import { describe, it, expect } from 'vitest';
import { loadConfig, resolveHarnessUrl } from '../src/config';
import { sendUpstreamError, sendUnreachable, sendMcpError } from '../src/errors';

function mockRes() {
  const res = { statusCode: 0, body: undefined as unknown };
  return {
    status(code: number) {
      res.statusCode = code;
      return this;
    },
    json(b: unknown) {
      res.body = b;
      return this;
    },
    _res: res,
  };
}

describe('config', () => {
  it('applies defaults when env is empty', () => {
    const c = loadConfig({});
    expect(c).toEqual({
      harnessUrl: 'http://localhost:8086',
      port: 3000,
      mcpTransport: 'sse',
      restTimeoutMs: 600000,
    });
  });

  it('reads overrides from env', () => {
    const c = loadConfig({
      HARNESS_URL: 'http://h:9/',
      PORT: '4000',
      MCP_TRANSPORT: 'streamable-http',
    });
    expect(c.harnessUrl).toBe('http://h:9');
    expect(c.port).toBe(4000);
    expect(c.mcpTransport).toBe('streamable-http');
  });

  it('resolveHarnessUrl prefers a non-empty header, stripping the trailing slash', () => {
    const c = loadConfig({});
    expect(resolveHarnessUrl(c, 'http://other:1/')).toBe('http://other:1');
    expect(resolveHarnessUrl(c, '')).toBe('http://localhost:8086');
    expect(resolveHarnessUrl(c, undefined)).toBe('http://localhost:8086');
  });
});

describe('error helpers', () => {
  it('mirrors upstream status with harness_error shape', () => {
    const r = mockRes();
    sendUpstreamError(r as never, 410, { reason: 'session_expired' });
    expect(r._res.statusCode).toBe(410);
    expect(r._res.body).toEqual({
      error: 'harness_error',
      upstreamStatus: 410,
      body: { reason: 'session_expired' },
    });
  });
  it('maps unreachable to 502', () => {
    const r = mockRes();
    sendUnreachable(r as never, 'ECONNREFUSED');
    expect(r._res.statusCode).toBe(502);
    expect(r._res.body).toEqual({ error: 'upstream_unreachable', message: 'ECONNREFUSED' });
  });
  it('maps mcp error to 502', () => {
    const r = mockRes();
    sendMcpError(r as never, 'boom');
    expect(r._res.statusCode).toBe(502);
    expect(r._res.body).toEqual({ error: 'mcp_error', message: 'boom' });
  });
});
