import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OpenApiEditor, parseSpec } from '@client/components/OpenApiEditor';

describe('parseSpec', () => {
  it('parses JSON', () => {
    expect(parseSpec('{"openapi":"3.0.0"}')).toEqual({ ok: true, value: { openapi: '3.0.0' } });
  });
  it('parses YAML', () => {
    expect(parseSpec('openapi: 3.0.0')).toEqual({ ok: true, value: { openapi: '3.0.0' } });
  });
  it('reports invalid input', () => {
    const r = parseSpec('{ broken: ');
    expect(r.ok).toBe(false);
  });
});

describe('OpenApiEditor', () => {
  it('calls onParsed with the parsed object on valid input', async () => {
    const onParsed = vi.fn();
    const onChange = vi.fn();
    render(<OpenApiEditor value="" onChange={onChange} onParsed={onParsed} />);
    // The CodeEditor renders a textarea in test mode; type valid JSON.
    const editor = screen.getByRole('textbox');
    // Type YAML (no braces) since userEvent.type treats `{`/`[` as special key sequences.
    await userEvent.type(editor, 'openapi: 3.0.0');
    expect(onChange).toHaveBeenCalled();
    expect(onParsed).toHaveBeenCalled();
  });
});
