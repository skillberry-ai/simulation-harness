import {
  DescriptionList,
  DescriptionListGroup,
  DescriptionListTerm,
  DescriptionListDescription,
  Label,
} from '@patternfly/react-core';

export function ResponseMetrics({
  status,
  durationMs,
  success,
}: {
  status: number;
  durationMs: number;
  success: boolean;
}) {
  return (
    <DescriptionList isHorizontal isCompact>
      <DescriptionListGroup>
        <DescriptionListTerm>Status</DescriptionListTerm>
        <DescriptionListDescription>
          <Label color={success ? 'green' : 'red'}>{status}</Label>
        </DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>Duration</DescriptionListTerm>
        <DescriptionListDescription>{durationMs.toFixed(1)} ms</DescriptionListDescription>
      </DescriptionListGroup>
      <DescriptionListGroup>
        <DescriptionListTerm>Success</DescriptionListTerm>
        <DescriptionListDescription>{success ? 'Yes' : 'No'}</DescriptionListDescription>
      </DescriptionListGroup>
    </DescriptionList>
  );
}
