import { useState } from 'react';
import {
  ExpandableSection,
  CodeBlock,
  CodeBlockCode,
  CodeBlockAction,
  ClipboardCopyButton,
} from '@patternfly/react-core';

export function JsonViewer({
  data,
  title = 'Response',
  defaultExpanded = true,
}: {
  data: unknown;
  title?: string;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(data, null, 2);

  const copy = () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      void navigator.clipboard.writeText(text);
    }
    setCopied(true);
  };

  const actions = (
    <CodeBlockAction>
      <ClipboardCopyButton
        id={`copy-${title}`}
        aria-label="Copy to clipboard"
        onClick={copy}
        exitDelay={copied ? 1500 : 600}
        onTooltipHidden={() => setCopied(false)}
      >
        {copied ? 'Copied' : 'Copy'}
      </ClipboardCopyButton>
    </CodeBlockAction>
  );

  return (
    <ExpandableSection
      toggleText={title}
      isExpanded={expanded}
      onToggle={(_e, v) => setExpanded(v)}
    >
      <CodeBlock actions={actions}>
        <CodeBlockCode>{text}</CodeBlockCode>
      </CodeBlock>
    </ExpandableSection>
  );
}
