import { useState } from 'react';
import { parse as parseYaml } from 'yaml';
import { CodeEditor, Language } from '@patternfly/react-code-editor';
import {
  FormSelect,
  FormSelectOption,
  Button,
  Split,
  SplitItem,
  HelperText,
  HelperTextItem,
} from '@patternfly/react-core';
import { EXAMPLES } from '../examples';

export function parseSpec(
  text: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  if (!text.trim()) return { ok: false, error: 'empty' };
  try {
    const value = parseYaml(text);
    if (value && typeof value === 'object')
      return { ok: true, value: value as Record<string, unknown> };
    return { ok: false, error: 'not an object' };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'invalid' };
  }
}

const isTest = import.meta.env?.MODE === 'test';

export function OpenApiEditor({
  value,
  onChange,
  onParsed,
}: {
  value: string;
  onChange: (text: string) => void;
  onParsed: (spec: Record<string, unknown> | null) => void;
}) {
  const [selected, setSelected] = useState('');
  const names = Object.keys(EXAMPLES).sort();

  const handleChange = (text: string) => {
    onChange(text);
    const parsed = parseSpec(text);
    onParsed(parsed.ok ? parsed.value : null);
  };

  const parsed = parseSpec(value);

  return (
    <div>
      <Split hasGutter>
        <SplitItem isFilled>
          <FormSelect
            value={selected}
            onChange={(_e, v) => setSelected(v)}
            aria-label="Select example spec"
          >
            <FormSelectOption value="" label="Choose an example…" />
            {names.map((n) => (
              <FormSelectOption key={n} value={n} label={n} />
            ))}
          </FormSelect>
        </SplitItem>
        <SplitItem>
          <Button
            variant="secondary"
            isDisabled={!selected}
            onClick={() => handleChange(EXAMPLES[selected])}
          >
            Load example
          </Button>
        </SplitItem>
      </Split>
      {isTest ? (
        <textarea
          aria-label="OpenAPI spec"
          value={value}
          onChange={(e) => handleChange(e.target.value)}
        />
      ) : (
        <CodeEditor
          code={value}
          language={Language.yaml}
          onChange={handleChange}
          height="300px"
          isLineNumbersVisible
        />
      )}
      <HelperText>
        <HelperTextItem variant={value && parsed.ok ? 'success' : value ? 'error' : 'default'}>
          {!value
            ? 'Paste or load an OpenAPI spec (YAML or JSON)'
            : parsed.ok
              ? 'Valid spec'
              : `Invalid: ${parsed.error}`}
        </HelperTextItem>
      </HelperText>
    </div>
  );
}
