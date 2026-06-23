import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../setup';
import { ApiPage } from '@client/pages/ApiPage';
import { setHarnessUrlGetter } from '@client/api/http';
import { useSimulationStore } from '@client/state/useSimulationStore';
import { useHistoryStore } from '@client/state/useHistoryStore';
import { PENDING_SIMULATION, READY_SIMULATION, FAILED_SIMULATION } from '../mocks/harness';

const ORIGIN = 'http://localhost:3000';

beforeEach(() => {
  setHarnessUrlGetter(() => 'http://localhost:8086');
  useSimulationStore.getState().clear();
  useHistoryStore.getState().clear();
});
afterEach(() => vi.useRealTimers());

async function fillSpecAndCreate(user: ReturnType<typeof userEvent.setup>) {
  await user.type(
    screen.getByLabelText(/openapi spec/i),
    'openapi: 3.0.0\ninfo:\n  title: demo-api',
  );
  await user.click(screen.getByRole('button', { name: /create simulation/i }));
}

describe('ApiPage create flow', () => {
  it('polls a pending creation to ready and updates the store', async () => {
    const user = userEvent.setup();
    let getCount = 0;
    server.use(
      http.post(`${ORIGIN}/proxy/simulation`, () =>
        HttpResponse.json(PENDING_SIMULATION, { status: 202 }),
      ),
      http.get(`${ORIGIN}/proxy/simulation`, () => {
        getCount += 1;
        return HttpResponse.json(getCount >= 2 ? READY_SIMULATION : PENDING_SIMULATION);
      }),
    );
    render(<ApiPage pollOptions={{ intervalMs: 20, deadlineMs: 2000 }} />);
    await fillSpecAndCreate(user);
    // Wait on the store (the spec text itself contains "demo-api", so a text query
    // would match the editor input before the poll resolves).
    await vi.waitFor(() => expect(useSimulationStore.getState().status).toBe('ready'), {
      timeout: 5000,
    });
  });

  it('shows a danger toast when creation fails', async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`${ORIGIN}/proxy/simulation`, () =>
        HttpResponse.json(PENDING_SIMULATION, { status: 202 }),
      ),
      http.get(`${ORIGIN}/proxy/simulation`, () => HttpResponse.json(FAILED_SIMULATION)),
    );
    render(<ApiPage pollOptions={{ intervalMs: 20, deadlineMs: 2000 }} />);
    await fillSpecAndCreate(user);
    expect(
      await screen.findByText(/skill_generation_failed/i, {}, { timeout: 5000 }),
    ).toBeInTheDocument();
    expect(useSimulationStore.getState().status).not.toBe('ready');
  });
});

describe('ApiPage individual operations', () => {
  it('get-state records a request', async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${ORIGIN}/proxy/simulation/state`, () =>
        HttpResponse.json({ thread_id: 'default' }),
      ),
    );
    render(<ApiPage />);
    // Expand the "Get simulation state" card and click its button.
    await user.click(screen.getByRole('button', { name: /get simulation state/i }));
    expect(await screen.findByText(/"thread_id": "default"/)).toBeInTheDocument();
    expect(
      useHistoryStore.getState().records.some((r) => r.endpoint.includes('/simulation/state')),
    ).toBe(true);
  });

  it('delete clears the simulation store', async () => {
    const user = userEvent.setup();
    useSimulationStore.getState().setFromResponse(READY_SIMULATION);
    server.use(
      http.delete(`${ORIGIN}/proxy/simulation`, () => new HttpResponse(null, { status: 204 })),
    );
    render(<ApiPage />);
    await user.click(screen.getByRole('button', { name: /delete simulation/i }));
    await vi.waitFor(() => expect(useSimulationStore.getState().name).toBeNull());
  });
});
