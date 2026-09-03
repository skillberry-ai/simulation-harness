export interface ProxyConfig {
  harnessUrl: string;
  port: number;
  mcpTransport: 'sse' | 'streamable-http';
  restTimeoutMs: number;
  /** Origins the `x-harness-url` header is permitted to target. */
  allowedOrigins: readonly string[];
  rateLimitWindowMs: number;
  rateLimitMax: number;
}

/**
 * Trim trailing slashes without a regex.
 *
 * A `/\/+$/` pattern backtracks quadratically on inputs like `'/'.repeat(n) + 'x'`,
 * so scan from the end instead — linear, no backtracking.
 */
const stripSlash = (u: string): string => {
  let end = u.length;
  while (end > 0 && u.charCodeAt(end - 1) === 47 /* '/' */) end -= 1;
  return u.slice(0, end);
};

/** Loopback origins are always permitted — this proxy is a local dev tool. */
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);

/**
 * Normalize a URL to a bare origin, or return null if it is not a usable
 * http(s) URL. Rejecting non-http(s) schemes keeps `file:`, `gopher:` and
 * friends out of `fetch()`.
 */
function toOrigin(value: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  return parsed.origin;
}

function positiveInt(raw: string | undefined, fallback: number): number {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : fallback;
}

function parseAllowlist(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(',')
    .map((entry) => toOrigin(entry.trim()))
    .filter((origin): origin is string => origin !== null);
}

export function loadConfig(env: NodeJS.ProcessEnv): ProxyConfig {
  const transport = env.MCP_TRANSPORT === 'streamable-http' ? 'streamable-http' : 'sse';
  const harnessUrl = stripSlash(env.HARNESS_URL?.trim() || 'http://localhost:8086');
  const configured = toOrigin(harnessUrl);

  return {
    harnessUrl,
    port: env.PORT ? Number(env.PORT) : 3000,
    mcpTransport: transport,
    restTimeoutMs: 600000,
    allowedOrigins: [
      ...(configured ? [configured] : []),
      ...parseAllowlist(env.HARNESS_URL_ALLOWLIST),
    ],
    // Generous by default: this proxies a harness whose own REST timeout is 10
    // minutes, so a tight limit would trip during ordinary interactive use. The
    // point is to bound runaway or scripted traffic.
    rateLimitWindowMs: positiveInt(env.RATE_LIMIT_WINDOW_MS, 60_000),
    rateLimitMax: positiveInt(env.RATE_LIMIT_MAX, 600),
  };
}

function isAllowedOrigin(config: ProxyConfig, origin: string): boolean {
  if (config.allowedOrigins.includes(origin)) return true;
  // Loopback is always in scope, on any port.
  try {
    return LOOPBACK_HOSTS.has(new URL(origin).hostname);
  } catch {
    return false;
  }
}

/**
 * Resolve the harness base URL for a request.
 *
 * The `x-harness-url` header is a real feature — the UI exposes a user-editable
 * harness URL and sends it on every request — but it is attacker-controllable,
 * so the target is constrained to loopback plus any origin the operator opted
 * into via `HARNESS_URL_ALLOWLIST`. Returns null when the header names a
 * disallowed or unparseable target, so callers can reject rather than silently
 * proxying somewhere unintended.
 */
export function resolveHarnessUrl(
  config: ProxyConfig,
  headerValue: string | undefined,
): string | null {
  const trimmed = headerValue?.trim();
  if (!trimmed) return config.harnessUrl;

  const origin = toOrigin(trimmed);
  if (origin === null) return null;
  if (!isAllowedOrigin(config, origin)) return null;

  return stripSlash(trimmed);
}
