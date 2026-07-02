import { request, type HttpResult } from './http';
import type { SimulationResponse } from '../state/types';

export const health = () => request<Record<string, unknown>>('GET', '/proxy/health');

export function createSimulation(
  spec: Record<string, unknown>,
  name: string | null,
  regenerate: boolean,
): Promise<HttpResult<SimulationResponse>> {
  const payload: Record<string, unknown> = { openapi_spec: spec, regenerate_skill: regenerate };
  if (name) payload.name = name;
  return request<SimulationResponse>('POST', '/proxy/simulation', payload);
}

export function setupSimulation(
  spec: Record<string, unknown>,
  name: string | null,
  regenerate: boolean,
): Promise<HttpResult<SimulationResponse>> {
  const payload: Record<string, unknown> = { openapi_spec: spec, regenerate_skill: regenerate };
  if (name) payload.name = name;
  return request<SimulationResponse>('POST', '/proxy/simulation/setup', payload);
}

export function startSimulation(
  name: string,
  mcpPort?: number | null,
): Promise<HttpResult<SimulationResponse>> {
  const payload: Record<string, unknown> = { name };
  if (mcpPort != null) payload.mcp_port = mcpPort;
  return request<SimulationResponse>('POST', '/proxy/simulation/start', payload);
}

export const getSimulation = () => request<SimulationResponse>('GET', '/proxy/simulation');
export const deleteSimulation = () => request<null>('DELETE', '/proxy/simulation');
export const resetSession = () =>
  request<Record<string, unknown>>('POST', '/proxy/simulation/reset');
export const getState = (threadId = 'default') =>
  request<Record<string, unknown>>(
    'GET',
    `/proxy/simulation/state?thread_id=${encodeURIComponent(threadId)}`,
  );
export const getSchema = () => request<Record<string, unknown>>('GET', '/proxy/simulation/schema');
export const getDatabase = () =>
  request<Record<string, unknown>>('GET', '/proxy/simulation/database');
export const putDatabase = (data: Record<string, unknown>) =>
  request<Record<string, unknown>>('PUT', '/proxy/simulation/database', data);
