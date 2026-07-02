export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface SimulationResponse {
  name: string;
  status: 'pending' | 'generating_skill' | 'generated' | 'initializing' | 'ready' | 'failed';
  created_at: string;
  mcp_url: string | null;
  error?: { code: string; message: string };
}

export interface RequestRecord {
  id: string;
  timestamp: string;
  method: string;
  endpoint: string;
  requestData: unknown | null;
  responseStatus: number;
  responseData: unknown | null;
  durationMs: number;
  error: string | null;
}
