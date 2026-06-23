import { Label } from '@patternfly/react-core';

export function SimulationBadge({ name, status }: { name: string | null; status: string | null }) {
  if (!name) return null;
  return <Label color="blue">{`${name} · ${status ?? 'unknown'}`}</Label>;
}
