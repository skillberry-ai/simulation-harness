import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JsonViewer } from '@client/components/JsonViewer';

describe('JsonViewer', () => {
  it('renders the title and serialized JSON', () => {
    render(<JsonViewer data={{ a: 1 }} title="Result" defaultExpanded />);
    expect(screen.getByText('Result')).toBeInTheDocument();
    expect(screen.getByText(/"a": 1/)).toBeInTheDocument();
  });
});
