import { AlertGroup, Alert, AlertActionCloseButton } from '@patternfly/react-core';
import { useNotifications } from './useNotifications';

export function Toaster() {
  const notices = useNotifications((s) => s.notices);
  const dismiss = useNotifications((s) => s.dismiss);
  return (
    <AlertGroup isToast isLiveRegion>
      {notices.map((n) => (
        <Alert
          key={n.id}
          variant={n.variant}
          title={n.title}
          actionClose={<AlertActionCloseButton onClose={() => dismiss(n.id)} />}
        />
      ))}
    </AlertGroup>
  );
}
