import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToolForm } from '@client/components/ToolForm';
import { MCP_TOOLS } from '../mocks/harness';

const createItem = MCP_TOOLS.find((t) => t.name === 'create_item')!;
const listItems = MCP_TOOLS.find((t) => t.name === 'list_items')!;

describe('ToolForm', () => {
  it('submits empty args for a no-parameter tool', async () => {
    const onSubmit = vi.fn();
    render(<ToolForm tool={listItems} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole('button', { name: /call tool/i }));
    expect(onSubmit).toHaveBeenCalledWith({});
  });

  it('blocks submit when a required field is empty', async () => {
    const onSubmit = vi.fn();
    render(<ToolForm tool={createItem} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole('button', { name: /call tool/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('omits untouched optional fields and includes required ones', async () => {
    const onSubmit = vi.fn();
    render(<ToolForm tool={createItem} onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText(/title/i), 'Widget');
    await userEvent.click(screen.getByRole('button', { name: /call tool/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const args = onSubmit.mock.calls[0][0];
    expect(args).toMatchObject({ title: 'Widget' });
    expect('qty' in args).toBe(false);
    expect('active' in args).toBe(false);
  });
});
