import { describe, it, expect } from 'vitest';
import { loadConfig, resolveHarnessUrl } from '../src/config';
import {
  sendUpstreamError,
  sendUnreachable,
  sendMcpError,
  sendForbiddenHarnessUrl,
} from '../src/errors';

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
      allowedOrigins: ['http://localhost:8086'],
      rateLimitWindowMs: 60_000,
      rateLimitMax: 600,
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

  it('rate limit settings come from env, falling back on invalid values', () => {
    expect(loadConfig({ RATE_LIMIT_WINDOW_MS: '1000', RATE_LIMIT_MAX: '5' })).toMatchObject({
      rateLimitWindowMs: 1000,
      rateLimitMax: 5,
    });
    expect(loadConfig({ RATE_LIMIT_WINDOW_MS: '0', RATE_LIMIT_MAX: 'abc' })).toMatchObject({
      rateLimitWindowMs: 60_000,
      rateLimitMax: 600,
    });
  });

  it('resolveHarnessUrl prefers a non-empty header, stripping the trailing slash', () => {
    const c = loadConfig({});
    expect(resolveHarnessUrl(c, 'http://127.0.0.1:1/')).toBe('http://127.0.0.1:1');
    expect(resolveHarnessUrl(c, '')).toBe('http://localhost:8086');
    expect(resolveHarnessUrl(c, undefined)).toBe('http://localhost:8086');
  });

  it('resolveHarnessUrl allows loopback on any port', () => {
    const c = loadConfig({});
    for (const url of ['http://localhost:9999', 'http://127.0.0.1:1234', 'http://[::1]:8086']) {
      expect(resolveHarnessUrl(c, url)).toBe(url);
    }
  });

  it('resolveHarnessUrl rejects a non-loopback origin that is not allowlisted', () => {
    const c = loadConfig({});
    expect(resolveHarnessUrl(c, 'http://evil.test')).toBeNull();
    expect(resolveHarnessUrl(c, 'http://169.254.169.254/latest/meta-data/')).toBeNull();
  });

  it('resolveHarnessUrl rejects non-http(s) schemes and unparseable input', () => {
    const c = loadConfig({});
    expect(resolveHarnessUrl(c, 'file:///etc/passwd')).toBeNull();
    expect(resolveHarnessUrl(c, 'gopher://evil.test')).toBeNull();
    expect(resolveHarnessUrl(c, 'not a url')).toBeNull();
    expect(resolveHarnessUrl(c, '///')).toBeNull();
  });

  it('HARNESS_URL_ALLOWLIST widens the permitted set', () => {
    const c = loadConfig({ HARNESS_URL_ALLOWLIST: 'http://a.test, https://b.test:8443' });
    expect(resolveHarnessUrl(c, 'http://a.test/')).toBe('http://a.test');
    expect(resolveHarnessUrl(c, 'https://b.test:8443')).toBe('https://b.test:8443');
    // A different port on an allowlisted host is a different origin, so still denied.
    expect(resolveHarnessUrl(c, 'http://a.test:9999')).toBeNull();
    expect(resolveHarnessUrl(c, 'http://c.test')).toBeNull();
  });

  it('the configured HARNESS_URL origin is permitted even when remote', () => {
    const c = loadConfig({ HARNESS_URL: 'https://harness.internal:8443' });
    expect(resolveHarnessUrl(c, 'https://harness.internal:8443/x')).toBe(
      'https://harness.internal:8443/x',
    );
    expect(resolveHarnessUrl(c, 'https://other.internal:8443')).toBeNull();
  });

  it('stripSlash-style trimming stays linear on pathological input', () => {
    const c = loadConfig({});
    // Guards the ReDoS fix: a regex-based trailing-slash trim backtracks
    // quadratically here. Anything but a prompt return is a regression.
    const hostile = 'http://127.0.0.1/' + '/'.repeat(200_000) + 'x';
    const start = performance.now();
    resolveHarnessUrl(c, hostile);
    expect(performance.now() - start).toBeLessThan(1000);
  });
});

describe('error helpers', () => {
  it('rejects a disallowed harness URL with 400', () => {
    const r = mockRes();
    sendForbiddenHarnessUrl(r as never);
    expect(r._res.statusCode).toBe(400);
    expect((r._res.body as { error: string }).error).toBe('harness_url_not_allowed');
  });

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
