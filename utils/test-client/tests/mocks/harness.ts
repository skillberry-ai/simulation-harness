import { http, HttpResponse } from 'msw';

export const HEALTH_OK = { status: 'ok' };
export const READY_SIMULATION = {
  name: 'demo-api',
  status: 'ready',
  created_at: '2026-06-22T10:00:00+00:00',
  mcp_url: 'http://localhost:8086/mcp/sse',
};
export const PENDING_SIMULATION = { ...READY_SIMULATION, status: 'pending', mcp_url: null };
export const GENERATED_SIMULATION = { ...READY_SIMULATION, status: 'generated', mcp_url: null };
export const FAILED_SIMULATION = {
  ...READY_SIMULATION,
  status: 'failed',
  error: { code: 'skill_generation_failed', message: 'boom' },
};
export const MCP_TOOLS = [
  {
    name: 'list_items',
    description: 'List items',
    inputSchema: { type: 'object', properties: {}, required: [] },
  },
  {
    name: 'create_item',
    description: 'Create an item',
    inputSchema: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'Item title' },
        qty: { type: 'integer', description: 'Quantity' },
        active: { type: 'boolean' },
      },
      required: ['title'],
    },
  },
];
export const SCHEMA = { type: 'object', properties: { items: { type: 'array' } } };
export const DATABASE = { items: [{ id: 1, title: 'a' }] };

/** MSW handlers for the UPSTREAM harness surface (used by server tests). */
export function harnessHandlers(baseUrl: string) {
  const u = (p: string) => `${baseUrl}${p}`;
  return [
    http.get(u('/health'), () => HttpResponse.json(HEALTH_OK)),
    http.post(u('/api/v1/simulation'), () =>
      HttpResponse.json(PENDING_SIMULATION, { status: 202 }),
    ),
    http.post(u('/api/v1/simulation/setup'), () =>
      HttpResponse.json(PENDING_SIMULATION, { status: 202 }),
    ),
    http.post(u('/api/v1/simulation/start'), () =>
      HttpResponse.json(PENDING_SIMULATION, { status: 202 }),
    ),
    http.get(u('/api/v1/simulation'), () => HttpResponse.json(READY_SIMULATION)),
    http.delete(u('/api/v1/simulation'), () => new HttpResponse(null, { status: 204 })),
    http.post(u('/api/v1/simulation/reset'), () => HttpResponse.json({ message: 'reset' })),
    http.get(u('/api/v1/simulation/state'), () => HttpResponse.json({ thread_id: 'default' })),
    http.get(u('/api/v1/simulation/schema'), () => HttpResponse.json(SCHEMA)),
    http.get(u('/api/v1/simulation/database'), () => HttpResponse.json(DATABASE)),
    http.put(u('/api/v1/simulation/database'), () => HttpResponse.json({ message: 'replaced' })),
  ];
}
