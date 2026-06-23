export interface HttpResult<T> {
  data: T;
  status: number;
  durationMs: number;
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

let harnessUrlGetter: () => string = () => 'http://localhost:8086';
export function setHarnessUrlGetter(fn: () => string): void {
  harnessUrlGetter = fn;
}

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<HttpResult<T>> {
  const start = performance.now();
  const res = await fetch(path, {
    method,
    headers: {
      'content-type': 'application/json',
      'x-harness-url': harnessUrlGetter(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const durationMs = performance.now() - start;
  const text = await res.text();
  const parsed = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const message =
      (parsed &&
        typeof parsed === 'object' &&
        'error' in parsed &&
        String((parsed as { error: unknown }).error)) ||
      `HTTP ${res.status}`;
    throw new ApiError(res.status, parsed, message);
  }
  return { data: parsed as T, status: res.status, durationMs };
}
