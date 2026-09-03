import type { Response } from 'express';

export function sendUpstreamError(res: Response, upstreamStatus: number, body: unknown): void {
  res.status(upstreamStatus).json({ error: 'harness_error', upstreamStatus, body });
}

export function sendUnreachable(res: Response, message: string): void {
  res.status(502).json({ error: 'upstream_unreachable', message });
}

export function sendMcpError(res: Response, message: string): void {
  res.status(502).json({ error: 'mcp_error', message });
}

export function sendForbiddenHarnessUrl(res: Response): void {
  res.status(400).json({
    error: 'harness_url_not_allowed',
    message:
      'The x-harness-url header must be an http(s) URL targeting loopback or an origin listed in HARNESS_URL_ALLOWLIST.',
  });
}
