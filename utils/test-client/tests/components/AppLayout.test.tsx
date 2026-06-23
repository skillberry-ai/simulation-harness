import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { AppLayout } from '@client/components/AppLayout';
import { useConnectionStore } from '@client/state/useConnectionStore';

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: <AppLayout />,
        children: [{ path: 'connection', element: <div>Connection content</div> }],
      },
    ],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

beforeEach(() =>
  useConnectionStore.setState({
    harnessUrl: 'http://localhost:8086',
    connected: false,
    lastHealthMs: null,
    connectionError: null,
  }),
);

describe('AppLayout', () => {
  it('renders nav links and the harness URL field', () => {
    renderAt('/connection');
    expect(screen.getByRole('link', { name: /connection/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /api/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /mcp/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /history/i })).toBeInTheDocument();
    expect(screen.getByDisplayValue('http://localhost:8086')).toBeInTheDocument();
  });

  it('renders the active page via Outlet', () => {
    renderAt('/connection');
    expect(screen.getByText('Connection content')).toBeInTheDocument();
  });

  it('shows the Unknown connection badge initially', () => {
    renderAt('/connection');
    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });
});
