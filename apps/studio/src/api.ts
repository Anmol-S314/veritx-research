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
  revision_id: string | null;
  design_hash: string;
  resolved_fabric_hash: string | null;
  design_view: DesignView;
  compilation_view: CompilationView;
  topology_hash?: string;
  attachment_hash?: string;
  mapping_hash?: string;
  route_hash?: string;
  resolved_route_hash?: string;
  vc_assignment_hash?: string;
  fabric_hash?: string;
  vc_count?: number;
}

export interface DesignView {
  contract_version: number;
  design_hash: string;
  schema_version?: number;
  compiler_semantics_version?: number;
  workload?: Record<string, unknown>;
  noc_guided?: Record<string, unknown>;
  locked_derived?: Record<string, unknown> | null;
}

export interface CompilationView {
  contract_version: number;
  status: 'COMPILED' | 'INVALID' | 'UNSUPPORTED';
  design_hash: string;
  error: string | null;
  resolved_fabric_hash?: string;
  certificate_id?: string;
  certificate_overall?: string;
  obligations?: Record<string, unknown>[];
  artifact_hashes?: Record<string, string>;
}

export interface RevisionSummary {
  revision_id: string;
}

export interface RevisionDetail {
  revision_id: string;
  design_hash: string;
  resolved_fabric_hash: string;
  intent: Record<string, unknown>;
  design_view: DesignView;
  compilation_view: CompilationView;
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
  // A v3 design document (engine-authored template, not user JSON).
  compileDesign: (request: Record<string, unknown>) =>
    postJson<CompileResult>('/compile', { request }),
  revisions: () => getJson<{ revisions: RevisionSummary[] }>('/revisions'),
  revision: (id: string) =>
    getJson<RevisionDetail>(`/revisions/${encodeURIComponent(id)}`),
  // Evaluate/optimize name an immutable revision; the gateway loads the
  // canonical request server-side.
  evaluate: (revisionId: string, patch: Record<string, unknown> = {}) =>
    postJson<Record<string, unknown>>('/evaluate', {
      revision_id: revisionId,
      patch,
    }),
  optimize: (
    revisionId: string,
    definition: Record<string, unknown>,
  ) =>
    postJson<Record<string, unknown>>('/optimize', {
      revision_id: revisionId,
      ...definition,
    }),
};
