import { useState } from 'react';
import {
  EmptyState,
  EmptyStateBody,
  FormSelect,
  FormSelectOption,
  Button,
  Card,
  CardTitle,
  CardBody,
  Stack,
  StackItem,
} from '@patternfly/react-core';
import { useMcp } from '../hooks/useMcp';
import { useSimulationStore } from '../state/useSimulationStore';
import { ToolForm } from '../components/ToolForm';
import { JsonViewer } from '../components/JsonViewer';

export function McpPage() {
  const sim = useSimulationStore();
  const { runListTools, runCallTool } = useMcp();
  const [selected, setSelected] = useState('');
  const [result, setResult] = useState<{ content: string; isError: boolean } | null>(null);

  if (!sim.name) {
    return (
      <EmptyState titleText="No active simulation" headingLevel="h4">
        <EmptyStateBody>Create a simulation first to test MCP tools.</EmptyStateBody>
      </EmptyState>
    );
  }

  const tools = sim.mcpTools;
  const selectedTool = tools.find((t) => t.name === selected) ?? tools[0];

  return (
    <Stack hasGutter>
      <StackItem>
        <Card>
          <CardTitle>Tools</CardTitle>
          <CardBody>
            <Button
              onClick={async () => {
                const list = await runListTools();
                if (list) {
                  sim.setTools(list);
                  setSelected(list[0]?.name ?? '');
                }
              }}
            >
              List tools
            </Button>
          </CardBody>
        </Card>
      </StackItem>

      {sim.mcpToolsLoaded && tools.length > 0 && selectedTool && (
        <StackItem>
          <Card>
            <CardTitle>Call tool</CardTitle>
            <CardBody>
              <Stack hasGutter>
                <StackItem>
                  <FormSelect
                    value={selectedTool.name}
                    onChange={(_e, v) => setSelected(v)}
                    aria-label="Select tool"
                  >
                    {tools.map((t) => (
                      <FormSelectOption key={t.name} value={t.name} label={t.name} />
                    ))}
                  </FormSelect>
                </StackItem>
                <StackItem>
                  <ToolForm
                    key={selectedTool.name}
                    tool={selectedTool}
                    onSubmit={async (args) => {
                      const res = await runCallTool(selectedTool.name, args);
                      setResult(res ?? null);
                    }}
                  />
                </StackItem>
                {result && (
                  <StackItem>
                    <JsonViewer data={result} title="Tool result" />
                  </StackItem>
                )}
              </Stack>
            </CardBody>
          </Card>
        </StackItem>
      )}
    </Stack>
  );
}
