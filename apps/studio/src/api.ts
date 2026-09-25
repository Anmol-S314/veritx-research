// Live gateway client. In development Vite proxies `/gw` to the FastAPI
// gateway (see vite.config.ts). In a deployed build the gateway must be
// reverse-proxied at the same prefix, or VITE_GATEWAY_URL set to its origin.
//
// No fabricated data lives here: a failed call throws and the UI shows the
// refusal, never a placeholder number.

const BASE = (import.meta.env.VITE_GATEWAY_URL as string | undefined) ?? '/gw';

export interface EngineQualification {
  role: string;
  integration: string;
  numerical: string;
  independence: string;
  limitations: string[];
}

export interface QualificationView {
  engines: Record<string, EngineQualification>;
  workload_levels: Record<string, string>;
}

export interface RunSummary {
  run_id: string;
  status: 'VERIFIED' | 'INVALID' | 'UNVERIFIED';
  bundle_id?: string;
  file_count?: number;
  reason?: string;
}

export interface WorkloadEntry {
  id: string;
  kind: string;
  name?: string;
  title?: string;
}

export interface CompileResult {
  intent_id: string;
  design_hash: string;
  resolved_fabric_hash: string;
  topology_hash: string;
  attachment_hash: string;
  mapping_hash: string;
  route_hash: string;
  resolved_route_hash: string;
  vc_assignment_hash: string;
  fabric_hash: string;
  vc_count: number;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const doc = await resp.json();
      if (doc && typeof doc.detail === 'string') detail = doc.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  health: () => getJson<{ status: string }>('/health'),
  qualification: () => getJson<QualificationView>('/qualification'),
  workloads: () => getJson<{ workloads: WorkloadEntry[] }>('/workloads'),
  runs: () => getJson<{ runs: RunSummary[] }>('/runs'),
  run: (id: string) =>
    getJson<Record<string, unknown>>(`/runs/${encodeURIComponent(id)}`),
  evidence: (id: string) =>
    getJson<Record<string, unknown>>(
      `/runs/${encodeURIComponent(id)}/evidence`,
    ),
  compile: (preset: string, policy = 'baseline_deterministic_v2') =>
    postJson<CompileResult>('/compile', { preset, policy }),
};
