import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../setup';
import { McpPage } from '@client/pages/McpPage';
import { setHarnessUrlGetter } from '@client/api/http';
import { useSimulationStore } from '@client/state/useSimulationStore';
import { MCP_TOOLS, READY_SIMULATION } from '../mocks/harness';

const ORIGIN = 'http://localhost:3000';
beforeEach(() => {
  setHarnessUrlGetter(() => 'http://localhost:8086');
  useSimulationStore.getState().clear();
});

describe('McpPage', () => {
  it('shows an empty state with no simulation', () => {
    render(<McpPage />);
    expect(screen.getByText(/create a simulation first/i)).toBeInTheDocument();
  });

  it('lists tools and calls one', async () => {
    const user = userEvent.setup();
    useSimulationStore.getState().setFromResponse(READY_SIMULATION);
    server.use(
      http.post(`${ORIGIN}/proxy/mcp/list-tools`, () => HttpResponse.json(MCP_TOOLS)),
      http.post(`${ORIGIN}/proxy/mcp/call-tool`, () =>
        HttpResponse.json({ content: '[]', isError: false }),
      ),
    );
    render(<McpPage />);
    await user.click(screen.getByRole('button', { name: /list tools/i }));
    expect(await screen.findByText('list_items')).toBeInTheDocument();
    // list_items has no params; submit calls the tool.
    await user.click(screen.getByRole('button', { name: /call tool/i }));
    expect(await screen.findByText(/"isError": false/)).toBeInTheDocument();
  });
});
