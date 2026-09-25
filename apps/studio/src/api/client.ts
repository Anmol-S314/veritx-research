// One typed HTTP client. No component issues raw fetch(); no Python model
// crosses this boundary. A failed call throws ApiError and the UI shows the
// typed failure — never a placeholder number.

const BASE = (import.meta.env.VITE_GATEWAY_URL as string | undefined) ?? '/gw';
const API = `${BASE}/api/v1`;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly operation: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string,
              operation = '', requestId: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.operation = operation;
    this.requestId = requestId;
  }

  get isUnavailable(): boolean {
    return this.status === 503;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API}${path}`, init);
  } catch (err) {
    throw new ApiError(0, 'GATEWAY_UNREACHABLE',
      err instanceof Error ? err.message : String(err));
  }
  if (!resp.ok) {
    let code = `HTTP_${resp.status}`;
    let message = `${resp.status} ${resp.statusText}`;
    let operation = '';
    let requestId: string | null = null;
    try {
      const body = await resp.json();
      if (body && typeof body === 'object') {
        if (typeof body.code === 'string') code = body.code;
        if (typeof body.message === 'string') message = body.message;
        if (typeof body.detail === 'string') message = body.detail;
        if (typeof body.operation === 'string') operation = body.operation;
        if (typeof body.request_id === 'string') requestId = body.request_id;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, code, message, operation, requestId);
  }
  return (await resp.json()) as T;
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const GATEWAY_API_BASE = API;
