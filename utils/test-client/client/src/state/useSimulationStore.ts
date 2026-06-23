import { create } from 'zustand';
import type { McpTool, SimulationResponse } from './types';

interface SimulationState {
  name: string | null;
  status: string | null;
  createdAt: string | null;
  mcpEndpoint: string | null;
  mcpTools: McpTool[];
  mcpToolsLoaded: boolean;
  setFromResponse: (r: SimulationResponse) => void;
  setTools: (tools: McpTool[]) => void;
  clear: () => void;
}

const EMPTY = {
  name: null,
  status: null,
  createdAt: null,
  mcpEndpoint: null,
  mcpTools: [] as McpTool[],
  mcpToolsLoaded: false,
};

export const useSimulationStore = create<SimulationState>()((set) => ({
  ...EMPTY,
  setFromResponse: (r) =>
    set({ name: r.name, status: r.status, createdAt: r.created_at, mcpEndpoint: r.mcp_endpoint }),
  setTools: (mcpTools) => set({ mcpTools, mcpToolsLoaded: true }),
  clear: () => set({ ...EMPTY }),
}));
