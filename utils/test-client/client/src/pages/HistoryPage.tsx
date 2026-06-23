import { useState } from 'react';
import { Table, Thead, Tbody, Tr, Th, Td, ExpandableRowContent } from '@patternfly/react-table';
import {
  Toolbar,
  ToolbarContent,
  ToolbarItem,
  Button,
  EmptyState,
  EmptyStateBody,
  Label,
} from '@patternfly/react-core';
import { useHistoryStore } from '../state/useHistoryStore';
import { toExportJson, triggerDownload } from '../history-export';
import { JsonViewer } from '../components/JsonViewer';

export function HistoryPage() {
  const records = useHistoryStore((s) => s.records);
  const clear = useHistoryStore((s) => s.clear);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  if (records.length === 0) {
    return (
      <EmptyState titleText="No requests yet" headingLevel="h4">
        <EmptyStateBody>Run an API or MCP call to populate the history.</EmptyStateBody>
      </EmptyState>
    );
  }

  return (
    <>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>{`Total requests: ${records.length}`}</ToolbarItem>
          <ToolbarItem>
            <Button variant="secondary" onClick={clear}>
              Clear
            </Button>
          </ToolbarItem>
          <ToolbarItem>
            <Button
              variant="secondary"
              onClick={() => triggerDownload('history.json', toExportJson(records))}
            >
              Export JSON
            </Button>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>
      <Table aria-label="Request history">
        <Thead>
          <Tr>
            <Th screenReaderText="Expand" />
            <Th>Time</Th>
            <Th>Method</Th>
            <Th>Endpoint</Th>
            <Th>Status</Th>
            <Th>Duration</Th>
            <Th>Success</Th>
          </Tr>
        </Thead>
        {records.map((r, rowIndex) => (
          <Tbody key={r.id} isExpanded={!!expanded[r.id]}>
            <Tr>
              <Td
                expand={{
                  rowIndex,
                  isExpanded: !!expanded[r.id],
                  onToggle: () => setExpanded((p) => ({ ...p, [r.id]: !p[r.id] })),
                }}
              />
              <Td>{new Date(r.timestamp).toLocaleTimeString()}</Td>
              <Td>{r.method}</Td>
              <Td>{r.endpoint}</Td>
              <Td>{r.responseStatus}</Td>
              <Td>{`${Math.round(r.durationMs)}ms`}</Td>
              <Td>{r.error ? <Label color="red">No</Label> : <Label color="green">Yes</Label>}</Td>
            </Tr>
            <Tr isExpanded={!!expanded[r.id]}>
              <Td />
              <Td colSpan={6}>
                <ExpandableRowContent>
                  <JsonViewer
                    data={{ request: r.requestData, response: r.responseData, error: r.error }}
                    title="Detail"
                    defaultExpanded
                  />
                </ExpandableRowContent>
              </Td>
            </Tr>
          </Tbody>
        ))}
      </Table>
    </>
  );
}
