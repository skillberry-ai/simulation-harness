import { useState } from 'react';
import {
  Card,
  CardHeader,
  CardTitle,
  CardExpandableContent,
  CardBody,
  Form,
  FormGroup,
  TextInput,
  Checkbox,
  Button,
  Progress,
  Stack,
  StackItem,
} from '@patternfly/react-core';
import { OpenApiEditor } from '../components/OpenApiEditor';
import { JsonViewer } from '../components/JsonViewer';
import { runApi, nextRecordId } from '../hooks/useApi';
import { usePollSimulation } from '../hooks/usePollSimulation';
import { useSimulationStore } from '../state/useSimulationStore';
import { useHistoryStore } from '../state/useHistoryStore';
import { useNotifications } from '../notifications/useNotifications';
import { ApiError } from '../api/http';
import * as harness from '../api/harness';
import type { SimulationResponse } from '../state/types';

const isTest = import.meta.env?.MODE === 'test';

function OperationCard({
  title,
  children,
  defaultExpanded = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <Card isExpanded={expanded}>
      <CardHeader onExpand={() => setExpanded((v) => !v)}>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardExpandableContent>
        <CardBody>{children}</CardBody>
      </CardExpandableContent>
    </Card>
  );
}

export function ApiPage({
  pollOptions,
}: {
  pollOptions?: { intervalMs?: number; deadlineMs?: number };
}) {
  const sim = useSimulationStore();
  const poll = usePollSimulation();

  const [specText, setSpecText] = useState('');
  const [spec, setSpec] = useState<Record<string, unknown> | null>(null);
  const [name, setName] = useState('');
  const [regenerate, setRegenerate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createResult, setCreateResult] = useState<SimulationResponse | null>(null);

  const [dbText, setDbText] = useState('');
  const [opResult, setOpResult] = useState<Record<string, { data: unknown } | null>>({});

  const create = async () => {
    if (!spec) return;
    setCreating(true);
    setCreateResult(null);
    const res = await runApi<SimulationResponse>({
      method: 'POST',
      endpoint: '/proxy/simulation',
      requestData: { openapi_spec: spec, name: name || null, regenerate_skill: regenerate },
      call: () => harness.createSimulation(spec, name || null, regenerate),
    });
    let final = res;
    if (res && res.status === 'pending') {
      final = await poll(pollOptions);
    }
    setCreating(false);
    if (!final) {
      useNotifications
        .getState()
        .notify('warning', 'Simulation did not reach a terminal state in time');
      return;
    }
    setCreateResult(final);
    if (final.status === 'failed') {
      const err = final.error;
      useNotifications
        .getState()
        .notify(
          'danger',
          `Simulation creation failed: ${err?.code ?? 'unknown'} — ${err?.message ?? ''}`,
        );
    } else {
      sim.setFromResponse(final);
    }
  };

  const runOp =
    (
      key: string,
      method: string,
      endpoint: string,
      call: () => Promise<{ data: unknown; status: number; durationMs: number }>,
      after?: (data: unknown) => void,
    ) =>
    async () => {
      const data = await runApi({ method, endpoint, call });
      if (data !== null) {
        setOpResult((prev) => ({ ...prev, [key]: { data } }));
        after?.(data);
      } else {
        setOpResult((prev) => ({ ...prev, [key]: null }));
      }
    };

  const deleteSim = async () => {
    try {
      const res = await harness.deleteSimulation();
      useHistoryStore.getState().add({
        id: nextRecordId(),
        timestamp: new Date().toISOString(),
        method: 'DELETE',
        endpoint: '/proxy/simulation',
        requestData: null,
        responseStatus: res.status,
        responseData: res.data,
        durationMs: res.durationMs,
        error: null,
      });
      sim.clear();
      useNotifications.getState().notify('success', 'Simulation deleted');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      useHistoryStore.getState().add({
        id: nextRecordId(),
        timestamp: new Date().toISOString(),
        method: 'DELETE',
        endpoint: '/proxy/simulation',
        requestData: null,
        responseStatus: e instanceof ApiError ? e.status : 0,
        responseData: e instanceof ApiError ? e.body : null,
        durationMs: 0,
        error: message,
      });
      useNotifications.getState().notify('danger', `Delete failed: ${message}`);
    }
  };

  return (
    <Stack hasGutter>
      <StackItem>
        <OperationCard title="1. Create simulation">
          <Form>
            <OpenApiEditor value={specText} onChange={setSpecText} onParsed={setSpec} />
            <FormGroup label="Simulation name (optional)" fieldId="sim-name">
              <TextInput
                id="sim-name"
                value={name}
                onChange={(_e, v) => setName(v)}
                placeholder="Defaults to spec info.title"
              />
            </FormGroup>
            <Checkbox
              id="regenerate"
              label="Regenerate skill if exists"
              isChecked={regenerate}
              onChange={(_e, v) => setRegenerate(v)}
            />
            <Button variant="primary" isDisabled={!spec || creating} onClick={create}>
              Create simulation
            </Button>
            {creating && (
              <Progress
                aria-label="Creating simulation"
                title="Waiting for simulation to become ready…"
              />
            )}
            {createResult && <JsonViewer data={createResult} title="Simulation" />}
          </Form>
        </OperationCard>
      </StackItem>

      <StackItem>
        <OperationCard title="2. Get simulation status">
          <Button
            onClick={runOp('get', 'GET', '/proxy/simulation', harness.getSimulation, (d) =>
              sim.setFromResponse(d as SimulationResponse),
            )}
          >
            Get simulation
          </Button>
          {opResult.get && <JsonViewer data={opResult.get.data} title="Simulation status" />}
        </OperationCard>
      </StackItem>

      <StackItem>
        <OperationCard title="3. Reset session">
          <Button
            onClick={runOp('reset', 'POST', '/proxy/simulation/reset', harness.resetSession, () =>
              useNotifications.getState().notify('success', 'Session reset'),
            )}
          >
            Reset session
          </Button>
          {opResult.reset && <JsonViewer data={opResult.reset.data} title="Reset response" />}
        </OperationCard>
      </StackItem>

      <StackItem>
        <OperationCard title="4. Get simulation state">
          <Button
            onClick={runOp('state', 'GET', '/proxy/simulation/state', () => harness.getState())}
          >
            Get simulation state
          </Button>
          {opResult.state && <JsonViewer data={opResult.state.data} title="Simulation state" />}
        </OperationCard>
      </StackItem>

      <StackItem>
        <OperationCard title="5. Get database schema">
          <Button onClick={runOp('schema', 'GET', '/proxy/simulation/schema', harness.getSchema)}>
            Get schema
          </Button>
          {opResult.schema && <JsonViewer data={opResult.schema.data} title="Database schema" />}
        </OperationCard>
      </StackItem>

      <StackItem>
        <OperationCard title="6. Get database">
          <Button onClick={runOp('db', 'GET', '/proxy/simulation/database', harness.getDatabase)}>
            Get database
          </Button>
          {opResult.db && <JsonViewer data={opResult.db.data} title="Database contents" />}
        </OperationCard>
      </StackItem>

      <StackItem>
        <OperationCard title="7. Replace database">
          <Form>
            <FormGroup label="New database JSON" fieldId="db-json">
              <textarea
                aria-label="New database JSON"
                value={dbText}
                onChange={(e) => setDbText(e.target.value)}
                rows={isTest ? undefined : 8}
                style={isTest ? undefined : { width: '100%' }}
              />
            </FormGroup>
            <Button
              variant="primary"
              isDisabled={!dbText.trim()}
              onClick={async () => {
                let payload: Record<string, unknown>;
                try {
                  payload = JSON.parse(dbText);
                } catch (e) {
                  useNotifications
                    .getState()
                    .notify(
                      'danger',
                      `Invalid JSON: ${e instanceof Error ? e.message : 'parse error'}`,
                    );
                  return;
                }
                const data = await runApi({
                  method: 'PUT',
                  endpoint: '/proxy/simulation/database',
                  requestData: payload,
                  call: () => harness.putDatabase(payload),
                });
                if (data !== null)
                  useNotifications
                    .getState()
                    .notify('success', 'Database replaced and simulation reset');
              }}
            >
              Replace database
            </Button>
          </Form>
        </OperationCard>
      </StackItem>

      <StackItem>
        <OperationCard title="8. Delete simulation">
          <Button variant="danger" onClick={deleteSim}>
            Delete simulation
          </Button>
        </OperationCard>
      </StackItem>
    </Stack>
  );
}
