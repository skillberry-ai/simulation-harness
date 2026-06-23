import { useState } from 'react';
import {
  Card,
  CardTitle,
  CardBody,
  Button,
  Stack,
  StackItem,
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
} from '@patternfly/react-core';
import { health } from '../api/harness';
import { useConnectionStore } from '../state/useConnectionStore';
import { useNotifications } from '../notifications/useNotifications';
import { ResponseMetrics } from '../components/ResponseMetrics';
import { JsonViewer } from '../components/JsonViewer';

export function ConnectionPage() {
  const { harnessUrl, connected, lastHealthMs, setConnected, setFailed } = useConnectionStore();
  const [result, setResult] = useState<{
    status: number;
    durationMs: number;
    data: unknown;
  } | null>(null);

  const run = async () => {
    try {
      const res = await health();
      setConnected(res.durationMs);
      setResult({ status: res.status, durationMs: res.durationMs, data: res.data });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setFailed(message);
      useNotifications.getState().notify('danger', `Health check failed: ${message}`);
      setResult(null);
    }
  };

  return (
    <Stack hasGutter>
      <StackItem>
        <Card>
          <CardTitle>Configuration</CardTitle>
          <CardBody>
            <DescriptionList isHorizontal isCompact>
              <DescriptionListGroup>
                <DescriptionListTerm>Harness URL</DescriptionListTerm>
                <DescriptionListDescription>{harnessUrl}</DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Connected</DescriptionListTerm>
                <DescriptionListDescription>{connected ? 'Yes' : 'No'}</DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Last health</DescriptionListTerm>
                <DescriptionListDescription>
                  {lastHealthMs == null ? '—' : `${Math.round(lastHealthMs)} ms`}
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>
          </CardBody>
        </Card>
      </StackItem>
      <StackItem>
        <Card>
          <CardTitle>Quick test</CardTitle>
          <CardBody>
            <Stack hasGutter>
              <StackItem>
                <Button onClick={run}>Run health check</Button>
              </StackItem>
              {result && (
                <>
                  <StackItem>
                    <ResponseMetrics
                      status={result.status}
                      durationMs={result.durationMs}
                      success
                    />
                  </StackItem>
                  <StackItem>
                    <JsonViewer data={result.data} title="Health check response" />
                  </StackItem>
                </>
              )}
            </Stack>
          </CardBody>
        </Card>
      </StackItem>
    </Stack>
  );
}
