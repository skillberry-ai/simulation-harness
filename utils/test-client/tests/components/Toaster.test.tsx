import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Toaster } from '@client/notifications/Toaster';
import { useNotifications } from '@client/notifications/useNotifications';

beforeEach(() => useNotifications.setState({ notices: [] }));

describe('Toaster', () => {
  it('renders a pushed notice and dismisses it', async () => {
    render(<Toaster />);
    useNotifications.getState().notify('danger', 'Something failed');
    expect(await screen.findByText('Something failed')).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/close/i));
    expect(screen.queryByText('Something failed')).not.toBeInTheDocument();
  });

  it('assigns distinct ids to successive notices', () => {
    useNotifications.getState().notify('success', 'a');
    useNotifications.getState().notify('success', 'b');
    const ids = useNotifications.getState().notices.map((n) => n.id);
    expect(new Set(ids).size).toBe(2);
  });
});
