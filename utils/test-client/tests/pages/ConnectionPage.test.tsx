import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '../setup';
import { ConnectionPage } from '@client/pages/ConnectionPage';
import { setHarnessUrlGetter } from '@client/api/http';
import { useConnectionStore } from '@client/state/useConnectionStore';
import { HEALTH_OK } from '../mocks/harness';

const ORIGIN = 'http://localhost:3000';
beforeEach(() => {
  setHarnessUrlGetter(() => 'http://localhost:8086');
  useConnectionStore.setState({
    harnessUrl: 'http://localhost:8086',
    connected: false,
    lastHealthMs: null,
    connectionError: null,
  });
});

describe('ConnectionPage', () => {
  it('runs a health check and shows metrics + response', async () => {
    server.use(http.get(`${ORIGIN}/proxy/health`, () => HttpResponse.json(HEALTH_OK)));
    render(<ConnectionPage />);
    await userEvent.click(screen.getByRole('button', { name: /run health check/i }));
    expect(await screen.findByText('200')).toBeInTheDocument();
    expect(screen.getByText(/"status": "ok"/)).toBeInTheDocument();
    expect(useConnectionStore.getState().connected).toBe(true);
  });

  it('surfaces the current harness URL', () => {
    render(<ConnectionPage />);
    expect(screen.getByText('http://localhost:8086')).toBeInTheDocument();
  });
});
