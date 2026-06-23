import Form from '@rjsf/core';
import validator from '@rjsf/validator-ajv8';
import type { RJSFSchema } from '@rjsf/utils';
import { Button } from '@patternfly/react-core';
import type { McpTool } from '../state/types';

export function ToolForm({
  tool,
  onSubmit,
}: {
  tool: McpTool;
  onSubmit: (args: Record<string, unknown>) => void;
}) {
  const schema = (tool.inputSchema ?? { type: 'object', properties: {} }) as RJSFSchema;
  return (
    <Form
      schema={schema}
      validator={validator}
      onSubmit={({ formData }) => onSubmit((formData ?? {}) as Record<string, unknown>)}
      showErrorList={false}
    >
      <Button type="submit" variant="primary">
        Call tool
      </Button>
    </Form>
  );
}
