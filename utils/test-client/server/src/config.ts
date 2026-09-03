export interface ProxyConfig {
  harnessUrl: string;
  /** Origin of `harnessUrl`, or null when it is not a usable http(s) URL. */
  harnessOrigin: string | null;
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

/**
 * Loopback hosts are always permitted — this proxy is a local dev tool.
 *
 * Maps the hostname as `URL` reports it to the canonical spelling used to
 * rebuild an origin, so the rebuilt value is a literal from this table rather
 * than a slice of the request.
 */
const LOOPBACK_HOSTS = new Map<string, string>([
  ['localhost', 'localhost'],
  ['127.0.0.1', '127.0.0.1'],
  ['[::1]', '[::1]'],
  ['::1', '[::1]'],
]);

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
    harnessOrigin: configured,
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

/**
 * Rebuild an origin from validated pieces.
 *
 * `scheme` is one of two literals, `host` comes from `LOOPBACK_HOSTS`, and the
 * port is re-serialized from an integer. No substring of the caller's input
 * survives into the result, which is what makes this a barrier rather than a
 * check whose verdict is discarded.
 */
function rebuildOrigin(parsed: URL, host: string): string {
  const scheme = parsed.protocol === 'https:' ? 'https' : 'http';
  const port = Number(parsed.port);
  const suffix = Number.isInteger(port) && port > 0 && port <= 65535 ? `:${port}` : '';
  return `${scheme}://${host}${suffix}`;
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
 *
 * Every non-null return is a string taken from configuration or rebuilt from
 * literals — the header is used to *select* a base, never to *build* one. That
 * distinction matters: an earlier version validated the header's origin and then
 * returned the raw header, which let a path ride along (`http://localhost:8086/x`
 * prefixed every upstream path) and left the request-forgery flow open.
 */
export function resolveHarnessUrl(
  config: ProxyConfig,
  headerValue: string | undefined,
): string | null {
  const trimmed = headerValue?.trim();
  if (!trimmed) return config.harnessUrl;

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  const origin = parsed.origin;

  // Naming the configured harness returns the configured URL verbatim, so an
  // operator-supplied base path (HARNESS_URL=http://host/base) is preserved.
  if (config.harnessOrigin !== null && origin === config.harnessOrigin) return config.harnessUrl;

  const allowlisted = config.allowedOrigins.find((entry) => entry === origin);
  if (allowlisted !== undefined) return allowlisted;

  // Loopback is always in scope, on any port.
  const loopback = LOOPBACK_HOSTS.get(parsed.hostname);
  if (loopback !== undefined) return rebuildOrigin(parsed, loopback);

  return null;
}
