export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface SimulationResponse {
  name: string;
  status: 'pending' | 'ready' | 'failed';
  created_at: string;
  mcp_endpoint: string | null;
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
