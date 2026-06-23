import type { RequestRecord } from './state/types';

export function toExportJson(records: RequestRecord[]): string {
  return JSON.stringify(records, null, 2);
}

export function triggerDownload(filename: string, json: string): void {
  if (typeof document === 'undefined' || typeof URL.createObjectURL !== 'function') return;
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
