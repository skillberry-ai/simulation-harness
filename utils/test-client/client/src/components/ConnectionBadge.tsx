import { Label } from '@patternfly/react-core';

export function ConnectionBadge({
  connected,
  lastHealthMs,
  error,
}: {
  connected: boolean;
  lastHealthMs: number | null;
  error: string | null;
}) {
  if (connected)
    return <Label color="green">{`Connected · ${Math.round(lastHealthMs ?? 0)}ms`}</Label>;
  if (error) return <Label color="red">Failed</Label>;
  return <Label color="grey">Unknown</Label>;
}
