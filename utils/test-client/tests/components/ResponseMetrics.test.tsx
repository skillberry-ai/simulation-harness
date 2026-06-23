import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ResponseMetrics } from '@client/components/ResponseMetrics';

describe('ResponseMetrics', () => {
  it('shows status, duration, and success', () => {
    render(<ResponseMetrics status={200} durationMs={12.4} success />);
    expect(screen.getByText('200')).toBeInTheDocument();
    expect(screen.getByText(/12.4\s*ms/)).toBeInTheDocument();
    expect(screen.getByText(/yes/i)).toBeInTheDocument();
  });
  it('reflects failure', () => {
    render(<ResponseMetrics status={500} durationMs={1} success={false} />);
    expect(screen.getByText(/no/i)).toBeInTheDocument();
  });
});
