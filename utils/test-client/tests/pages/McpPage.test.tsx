import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, delay } from 'msw';
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

  it('clears the previous result when a new tool call starts', async () => {
    const user = userEvent.setup();
    useSimulationStore.getState().setFromResponse(READY_SIMULATION);
    let call = 0;
    server.use(
      http.post(`${ORIGIN}/proxy/mcp/list-tools`, () => HttpResponse.json(MCP_TOOLS)),
      http.post(`${ORIGIN}/proxy/mcp/call-tool`, async () => {
        call += 1;
        if (call === 1) {
          return HttpResponse.json({ content: 'FIRST_RESULT', isError: false });
        }
        // Delay the second response so we can observe the cleared state.
        await delay(50);
        return HttpResponse.json({ content: 'SECOND_RESULT', isError: false });
      }),
    );
    render(<McpPage />);
    await user.click(screen.getByRole('button', { name: /list tools/i }));
    expect(await screen.findByText('list_items')).toBeInTheDocument();

    // First call shows a result.
    await user.click(screen.getByRole('button', { name: /call tool/i }));
    expect(await screen.findByText(/FIRST_RESULT/)).toBeInTheDocument();

    // Second call: the old result must be gone before the new one arrives.
    await user.click(screen.getByRole('button', { name: /call tool/i }));
    expect(screen.queryByText(/FIRST_RESULT/)).not.toBeInTheDocument();
    expect(await screen.findByText(/SECOND_RESULT/)).toBeInTheDocument();
  });
});
