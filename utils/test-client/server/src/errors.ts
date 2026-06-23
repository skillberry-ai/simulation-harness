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
