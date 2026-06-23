import { request, type HttpResult } from './http';
import type { McpTool } from '../state/types';

export const listTools = (): Promise<HttpResult<McpTool[]>> =>
  request<McpTool[]>('POST', '/proxy/mcp/list-tools', {});

export const callTool = (
  name: string,
  args: Record<string, unknown>,
): Promise<HttpResult<{ content: string; isError: boolean }>> =>
  request<{ content: string; isError: boolean }>('POST', '/proxy/mcp/call-tool', {
    name,
    arguments: args,
  });
