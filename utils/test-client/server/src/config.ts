export interface ProxyConfig {
  harnessUrl: string;
  port: number;
  mcpTransport: 'sse' | 'streamable-http';
  restTimeoutMs: number;
}

const stripSlash = (u: string): string => u.replace(/\/+$/, '');

export function loadConfig(env: NodeJS.ProcessEnv): ProxyConfig {
  const transport = env.MCP_TRANSPORT === 'streamable-http' ? 'streamable-http' : 'sse';
  return {
    harnessUrl: stripSlash(env.HARNESS_URL?.trim() || 'http://localhost:8086'),
    port: env.PORT ? Number(env.PORT) : 3000,
    mcpTransport: transport,
    restTimeoutMs: 600000,
  };
}

export function resolveHarnessUrl(config: ProxyConfig, headerValue: string | undefined): string {
  const trimmed = headerValue?.trim();
  return trimmed ? stripSlash(trimmed) : config.harnessUrl;
}
