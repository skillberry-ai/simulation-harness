import { runApi } from './useApi';
import * as mcp from '../api/mcp';
import { useNotifications } from '../notifications/useNotifications';
import type { McpTool } from '../state/types';

export function useMcp() {
  const runListTools = () =>
    runApi<McpTool[]>({ method: 'POST', endpoint: '/proxy/mcp/list-tools', call: mcp.listTools });

  const runCallTool = async (name: string, args: Record<string, unknown>) => {
    const result = await runApi<{ content: string; isError: boolean }>({
      method: 'POST',
      endpoint: '/proxy/mcp/call-tool',
      requestData: { name, arguments: args },
      call: () => mcp.callTool(name, args),
    });
    if (result?.isError) {
      useNotifications.getState().notify('danger', result.content || 'Tool returned an error');
    }
    return result;
  };

  return { runListTools, runCallTool };
}
