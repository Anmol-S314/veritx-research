// Gateway client. Mutations are explicit domain operations; errors are never treated as success.
import { desktopGatewayBase } from './desktop';
const BASE = desktopGatewayBase ?? (import.meta.env.VITE_GATEWAY_URL as string | undefined) ?? '/gw';
const API = `${BASE}/api/v1`;

export type GatewayHealth = { status: string; api: string; features?: Record<string, boolean>; backends: Record<string, { state: string; binary_present: boolean }> };
export type ProjectSummary = { project_id: string; name: string; created_at: string; updated_at: string };
export type RevisionSummary = {
  revision_id: string;
  display_name: string;
  created_at?: string | null;
  design_hash?: string | null;
  compilation_status?: string | null;
  certificate_overall?: string | null;
  error?: string | null;
  design?: Record<string, unknown>;
};
export type RunSummary = {
  run_id: string;
  display_name?: string | null;
  revision_id: string;
  backend?: string | null;
  status: string;
  qualification?: string | null;
  requirements_pass?: boolean | null;
  started_at?: string | null;
  completed_at?: string | null;
  bundle_id?: string | null;
  completion_cycles?: number | null;
  analysis_backends?: { backend_id?: string | null; question?: string | null; status?: string | null }[];
};
export type RevisionDiffRow = { field: string; before: unknown; after: unknown; kind: string; detail?: string | null };
export type RevisionDiff = {
  revision_id: string;
  display_name?: string | null;
  against_revision_id?: string | null;
  against_display_name?: string | null;
  has_basis: boolean;
  reason?: string | null;
  design_changes?: RevisionDiffRow[];
  derived_changes?: RevisionDiffRow[];
  capability_changes?: RevisionDiffRow[];
};
/** A refusal recorded when a revision was compiled, whose capability has since
 *  been requalified. Kept beside the live verdict so history stays readable. */
export type SupersededRefusal = { recorded_support?: string; recorded_reason?: string | null; re_derived_at?: string; meaning?: string };
export type ProjectEntry = { project: ProjectSummary; active_revision_id: string | null; active_revision: RevisionSummary | null; runs?: RunSummary[]; active_evaluation?: { support?: string; readiness?: string; reason?: string | null; superseded_refusal?: SupersededRefusal | null } | null };
export type OptimizationSummary = {  optimization_id: string;
  base_revision_id?: string;
  created_at?: string;
  candidate_count?: number;
  pareto_count?: number;
  selected_candidate_id?: string | null;
};

export type OptimizationObjective = { metric: string; direction: 'MIN' | 'MAX' | string; question?: string; backend_id?: string | null };

export type OptimizationDefinition = {
  domain?: { name: string; values: (number | string | boolean)[] }[] | Record<string, (number | string | boolean)[]>;
  objectives?: OptimizationObjective[];
  constraints?: { metric?: string; op?: string; threshold?: number }[];
  method?: string;
  budget?: Record<string, unknown>;
  seed?: number | null;
  selection?: string;
};

export type OptimizationStudyCandidate = {
  candidate_id: string;
  guided_patch?: Record<string, unknown>;
  objective_values?: Record<string, number>;
  objective_availability?: Record<string, string>;
  evaluation_status?: string;
  evaluation_authority?: string;
  compilation_status?: string;
  eligibility_reason?: string | null;
  evaluation_reason?: string | null;
  pareto_eligible?: boolean;
  pareto_member?: boolean;
  constraint_verdicts?: Record<string, unknown>;
  product_requirements?: {
    satisfied?: boolean;
    verdicts?: {
      traffic_class?: string;
      qos_class?: string;
      verdict?: string;
      measured?: number | null;
      required?: number | null;
      binding?: boolean;
      reason?: string;
    }[];
  };
  locked_consequences?: Record<string, unknown>;
};

export type OptimizationView = {
  contract_version?: number;
  optimization_id: string;
  project_id?: string;
  base_revision_id?: string;
  created_at?: string;
  definition?: OptimizationDefinition;
  study?: {
    contract_version?: number;
    definition?: OptimizationDefinition;
    candidates?: OptimizationStudyCandidate[];
    pareto_ids?: string[];
    selected_candidate_id?: string | null;
    selection_rationale?: string | null;
    completeness?: Record<string, unknown> | null;
  };
  candidate_runs?: unknown[];
  candidate_evidence_note?: string;
  selected_candidate_id?: string | null;
};

export type ProjectDetail = ProjectEntry & {
  revisions?: RevisionSummary[];
  draft?: { workload_id?: string; source?: string; updated_at?: string };
  optimizations?: OptimizationSummary[];
  latest_optimization_study?: OptimizationSummary | null;
};
export type RunMetrics = { completion_cycles?: number | null; delivered_packets?: number | null; flits_injected?: number | null; flits_accepted?: number | null; injected_trace_packets?: number | null; loaded_trace_packets?: number | null; packet_latency_avg?: number | null; flit_latency_avg?: number | null; sample_window_cycles?: number | null; [key: string]: number | null | undefined };
export type RequirementEntry = { requirement_index?: number; traffic_class?: string; qos_class?: string; verdict?: string; required?: number | string | null; measured?: number | null; binding?: boolean; reason?: string | null; metric_authority?: string; performance_result_id?: string | null };
export type RunDetail = {
  run_id: string; display_name?: string; project_id: string; revision_id: string;
  backend?: string; status: string; qualification?: string; qualification_basis?: string; requirements_pass?: boolean;
  started_at?: string; completed_at?: string; bundle_id?: string | null;
  evaluation?: { metrics?: RunMetrics; fidelity_warning?: string; status?: string; workload_id?: string; evidence?: Record<string, string>; reason?: string | null; network_traffic_window?: { window_cycles?: number; wall_time_ns?: number } } | null;
  requirements?: { entries?: RequirementEntry[] } | null;
  evidence?: { evidence_id?: string } | null;
  analyses?: { backend_id?: string; question?: string; status?: string; qualification?: string; model_fidelity?: string; limitations?: string[]; native_summary?: Record<string, unknown>; normalized_metrics?: { key?: string; value?: number | null; unit?: string | null; dimensions?: string[] }[] }[];
  evaluation_plan?: { analyses?: { backend?: string; limitations?: string[] }[] } | null;
  reason?: string | null;
};
export type TrafficMatrix = {
  run_id: string; revision_id?: string; availability: string; source?: { trace?: string; backend?: string; declared_packets?: number };
  nodes: number; packets?: number; flits?: number; distinct_pairs?: number; classes?: Record<string, number>;
  matrix?: number[][]; flit_matrix?: number[][]; pairs?: { src: number; dst: number; packets: number; flits: number }[];
  class_matrices?: Record<string, { packets?: number; flits?: number; distinct_pairs?: number; matrix?: number[][]; flit_matrix?: number[][]; pairs?: { src: number; dst: number; packets: number; flits: number }[] }>;
};
export type RunIntegrity = {
  run_id: string;
  packet_conservation?: { declared?: { value: number | null; availability: string }; loaded?: { value: number | null; availability: string }; injected?: { value: number | null; availability: string }; delivered?: { value: number | null; availability: string } };
  flit_conservation?: { declared?: { value: number | null; availability: string }; injected?: { value: number | null; availability: string }; accepted?: { value: number | null; availability: string }; delivered?: { value: number | null; availability: string } };
  route_realization?: { status?: string; scope?: string; full_path_claimed?: boolean };
  evidence_id?: string;
  analyses?: Record<string, { backend?: string; status?: string; kind?: string; packets?: number; flits?: number }>;
};
export type RunArtifacts = { run_id: string; bundle: { algorithm?: string; bundle_id?: string; file_count?: number; schema_version?: number; files?: Record<string, string> } | null };
export type CanonicalRoute = {
  routing_class: string; src: number; dst: number; routers: number[];
  hops: { channel_id: number; src_router: number; src_port: number; dst_router: number; dst_port: number }[];
  terminates: boolean; terminal?: string | null; reason?: string | null;
};
export type SimLoad = {
  run: string; source: string; capacity_formula?: string; link_capacity_flits_per_cycle?: number;
  sample_period_cycles?: number; num_windows?: number; cycles_sampled?: number; time_resets_observed?: number;
  channels?: {
    logical_channel_id: number;
    flits_total: number;
    cycles_sampled: number;
    utilization: number;
    peak_window_utilization: number;
    has_stalls?: boolean;
    has_split?: boolean;
    queue_cycles_total?: number;
    arb_wait_cycles_total?: number;
    tx_flits_total?: number;
    per_hop_latency_mean_cycles?: number;
    mean_queued_flits_per_output?: number;
    peak_queued_flits?: number;
    peak_arb_wait_cycles?: number;
    peak_per_hop_latency_cycles?: number;
  }[];
};
export type SimSeriesChannel = {
  logical_channel_id: number | string;
  flits_per_window: number[];
  window_cycles: number[];
  stalls_per_window?: number[] | null;
  queue_cycles_per_window?: number[] | null;
  arb_wait_cycles_per_window?: number[] | null;
  tx_flits_per_window?: number[] | null;
  tx_busy_cycles_per_window?: number[] | null;
  occupancy_flit_cycles_per_window?: number[] | null;
  queue_max_per_window?: number[] | null;
  arb_max_per_window?: number[] | null;
  latency_max_per_window?: number[] | null;
  occupancy_max_per_window?: number[] | null;
};
export type SimSeries = {
  run?: string; source: string; schema_version?: string;
  sample_period_cycles?: number; num_windows?: number; cycles_sampled?: number;
  time_resets_observed?: number; capacity_formula?: string; link_capacity_flits_per_cycle?: number;
  channels: SimSeriesChannel[];
};
export type SimLinkBreakdown = {
  source: string; queue_cycles: number; arb_wait_cycles: number; tx_flits: number;
  tx_busy_cycles?: number | null; per_hop_latency_mean_cycles?: number | null;
  mean_queued_flits_per_output?: number | null; peak_queued_flits?: number | null;
  peak_arb_wait_cycles?: number | null; peak_per_hop_latency_cycles?: number | null;
};
export type SimLink = {
  run: string; source: string; logical_channel_id: number | string; utilization: number;
  total_flits: number; stalls_total?: number | null; breakdown: SimLinkBreakdown | null;
  breakdown_absence?: string | null; capacity_formula?: string; sample_period_cycles?: number;
  num_windows?: number; cycles_sampled?: number; time_resets_observed?: number;
};
export type LoomTopologyFamily = {
  family: string; status: string; stopped_at?: string | null;
  qualification?: string | null; reason?: string | null;
};
export type LoomCapabilities = {
  schema_version?: number; statuses?: string[]; note?: string;
  topology?: { probed?: boolean; families?: LoomTopologyFamily[] };
};
export type LoomOrigin = {
  schema_version?: number; type?: string; origins?: string[]; freshness?: string[];
  artifact_kinds?: string[]; origin_meaning?: Record<string, string>;
  freshness_meaning?: Record<string, string>;
};
export type GeneratedReport = {
  report_id: string; title: string; kind: string; media_type: string;
  size_bytes: number; modified_at?: string; source_path: string;
};
export type KnobInventory = {
  type?: string;
  topology?: { kind: string; label?: string; fields?: { name: string; required?: boolean; default?: unknown; type?: string }[] }[];
  controls?: { name: string; required?: boolean; default?: unknown; type?: string; group?: string }[];
  backend?: Record<string, unknown> | string | null;
  not_covered?: string[];
  notes?: string[];
};

export type EvaluationPlanRow = {
  question?: string; backend?: string | null; support?: string; readiness?: string;
  qualification?: { numerical_qualification?: string; calibration?: string; basis?: string; model_fidelity?: string } | null;
  model_fidelity?: string | null; limitations?: string[]; reason?: string | null; blocking_reasons?: string[] | null;
};
export type EvaluationPlan = { contract_version?: number; revision_id: string; workload_id?: string; analyses?: EvaluationPlanRow[] };
export type Job = {
  contract_version?: number; job_id: string; project_id: string; kind: string; revision_id?: string | null;
  state: string; submitted_at?: string; updated_at?: string; error_code?: string | null; error_message?: string | null;
  result?: { run_id?: string } | null; cancellable?: boolean;
};
export type JobLog = {
  contract_version: number; job_id: string; project_id: string; kind: string; state: string;
  source: string; terminal: boolean; available: boolean; offset: number; next_offset: number;
  size: number; eof: boolean; truncated: boolean; text: string; note?: string | null;
};
export type Obligation = {
  obligation_id: string; category: string; title: string; question: string; scope: string;
  state: 'OPEN' | 'RESOLVED' | 'NOT_APPLICABLE' | string; blocking: boolean;
  evidence: Record<string, any>; next_action: string; sources: string[];
};
export type Obligations = {
  contract_version: number; source: string; project_id: string; revision_id: string | null;
  run_id: string | null; generated_at: string; counts: { OPEN?: number; RESOLVED?: number; NOT_APPLICABLE?: number; blocking_open?: number };
  obligations: Obligation[]; note: string;
};
export type ComparisonRow = {
  key: string; question?: string; dimensions?: string | null; a: number | null; b: number | null;
  unit?: string | null; definition_id?: string | null; comparable: boolean; verdict: string;
  differs?: string | null; delta_b_minus_a?: number | null; reason?: string | null;
  a_evidence?: string | null; b_evidence?: string | null;
};
export type Comparison = {
  contract_version: number;
  a: Record<string, any>; b: Record<string, any>;
  compatibility: {
    compatible: boolean; same_workload?: boolean; same_backend?: boolean; both_qualified?: boolean;
    backend_configuration_state?: string; measurement_window_state?: string;
    same_backend_configuration?: boolean | null; same_measurement_window?: boolean | null;
    metric_definitions_complete?: boolean; metric_definition_issues?: { metric: string; issue: string; detail: string }[];
    metadata_complete?: boolean; metadata_warnings?: string[]; reasons?: string[];
    a_measurement_window_cycles?: number | null; b_measurement_window_cycles?: number | null;
  };
  rows: ComparisonRow[]; note: string;
};

export type SharedLink = {
  shared_link_id: number;
  src_router: number;
  taps: number[];
  width_bits: number;
  latency_cycles: number;
};

export type Topology = {
  family: string;
  counts: Record<string, number>;
  routers: { router_id: number; coordinates: number[]; seat_capacity?: number }[];
  channels: { channel_id?: number; src_router: number; dst_router: number; src_port: number; dst_port: number; width_bits: number; latency_cycles: number }[];
  shared_links?: SharedLink[];
  planes?: string[];
  island_columns?: number[];
  endpoints: { endpoint_id: number; router_id: number; kind: string; port_id: number }[];
};

export type FloorplanDerived = {
  scope: string;
  topology_hash: string;
  die: { width_um: number; height_um: number; area_um2: number };
  routers: { count: number; area_um2: number; utilization: number };
  keepouts: { count: number; area_um2: number };
  links: {
    channels: number;
    length_um: { min: number | null; mean: number | null; max: number | null };
    delay_ps: { min: number | null; mean: number | null; max: number | null };
  };
  wire: { ps_per_mm: number; fixed_ps: number };
};

export type FloorplanView = {
  contract_version: number;
  declared: boolean;
  stale?: boolean;
  revision_id: string | null;
  topology_hash: string | null;
  reason?: string;
  bound_topology_hash?: string;
  floorplan: {
    die_width_um: number;
    die_height_um: number;
    routers: { router_id: number; x_um: number; y_um: number; width_um: number; height_um: number }[];
    keepouts: { keepout_id: string; x_um: number; y_um: number; width_um: number; height_um: number }[];
    wire: { ps_per_mm: number; fixed_ps: number };
  } | null;
  derived: FloorplanDerived | null;
};

export type GridFloorplanRequest = {
  mode: 'grid';
  grid: {
    origin_x_um: number; origin_y_um: number;
    pitch_x_um: number; pitch_y_um: number;
    router_width_um: number; router_height_um: number;
    margin_um: number;
    wire: { ps_per_mm: number; fixed_ps: number };
  };
};

export type ControlPlaneGroup = {
  available?: boolean;
  declared?: boolean;
  scope?: string;
  claim?: string;
  reason?: string;
  subnet?: {
    id: number;
    k: number;
    c: number;
    vcs: string[];
    vc_count: number;
    routing: string;
    routing_class: string;
    scope: string;
    artifact: string;
  } | null;
  class_to_subnet?: {
    available?: boolean;
    rows?: { traffic_class: string; subnet: number }[];
    reason?: string;
  } | null;
  editable?: boolean;
};

/** Derived router behavior, one artifact for the whole fabric. */
export type RouterArbitration = {
  allocator_iterations?: number;
  flow_control?: string;
  input_buffer_depth_flits_per_vc?: number;
  input_vc_packet_policy?: string;
  output_stage_depth_flits_per_vc?: number;
  switch_allocator?: string;
  vc_allocator?: string;
};

export type DeadlockProof = {
  status?: string;
  method?: string;
  witness?: {
    acyclic?: boolean;
    sccs_gt_1?: number;
    node_count?: number;
    edge_count?: number;
    cdg_route_classes?: string[];
    escape_vcs?: number[];
    vc_count?: number;
    route_realization_scheme?: string;
  } | null;
  evidence?: Record<string, unknown> | null;
};

export type ParallelCoordinates = { tp: number; dp: number; ep: number; pp: number };

export type MappingRow = {
  rank: number;
  endpoint_id: number;
  agent_kind: string;
  group_index: number;
  instance_index: number;
  coordinates: ParallelCoordinates;
};

export type MappingGroup = {
  available?: boolean;
  parallelism?: ParallelCoordinates;
  rank_count?: number;
  rows?: MappingRow[];
  idle_agents?: { count?: number; mapped?: number; attached?: number; by_kind?: Record<string, number> };
};

export type CompileResources = {
  available?: boolean;
  arbitration?: RouterArbitration | null;
  deadlock?: DeadlockProof | null;
  vc_count?: number;
  vc_ids?: number[];
  escape_vcs?: number[];
  traffic_class_to_vcs?: [string, number[]][];
  vc_to_routing_class?: [number, string][];
  derivation?: string;
  editable?: boolean;
};

export type CompileResult = {
  available?: boolean;
  revision_id?: string;
  certificate?: {
    overall?: string;
    obligations?: { obligation?: string; status?: string; method?: string; meaning?: string }[];
    [key: string]: unknown;
  } | null;
  groups?: { resources?: CompileResources; mapping?: MappingGroup; control_plane?: ControlPlaneGroup; [key: string]: unknown } | null;
  [key: string]: unknown;
};


export class GatewayHttpError extends Error {
  status: number;
  detail: string;
  constructor(status: number, statusText: string, detail: string) {
    super(`${status} ${statusText}${detail ? ` — ${detail}` : ''}`);
    this.status = status;
    this.detail = detail;
  }
}

function errorDetail(text: string): string {
  try {
    const value = JSON.parse(text);
    // A 500 whose detail is only "the runner produced no ablation.json" hides the
    // reason in stderr, and the reason was four separate packaging faults. Append
    // the first error line the server captured so the next failure is readable
    // from the UI instead of needing a rebuild to diagnose.
    if (typeof value.detail === 'string') {
      const captured = [value.stderr, value.stdout].find((entry: unknown) => typeof entry === 'string' && entry.trim());
      if (typeof captured === 'string') {
        // Prefer the line that names the fault. The last line is usually the
        // PyInstaller footer ("Failed to execute script"), which says nothing.
        const lines = captured.split('\n').filter((entry: string) => entry.trim());
        const fault = [...lines].reverse().find((entry: string) =>
          /^\s*(?:[A-Za-z_.]*(?:Error|Exception)\b)/.test(entry)) ?? lines[lines.length - 1] ?? '';
        return `${value.detail.slice(0, 240)} — ${fault.trim().slice(0, 300)}`;
      }
      return value.detail.slice(0, 500);
    }
    if (typeof value.message === 'string') return value.message.slice(0, 500);
    if (typeof value.error?.message === 'string') return value.error.message.slice(0, 500);
    if (Array.isArray(value.detail)) return value.detail.map((entry: any) => `${(entry.loc ?? []).join('.')}: ${entry.msg ?? 'Invalid value'}`).join('; ').slice(0, 500);
    return '';
  } catch { return text.slice(0, 300); }
}

async function postJson<T>(path: string, body: unknown, timeoutMs = 60000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API}${path}`, {
      method: 'POST', signal: controller.signal,
      headers: { accept: 'application/json', 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    const text = await response.text();
    const detail = errorDetail(text);
    if (!response.ok) throw new GatewayHttpError(response.status, response.statusText, detail);
    return (text ? JSON.parse(text) : {}) as T;
  } finally {
    clearTimeout(timer);
  }
}

async function sendJson<T>(method: 'PUT' | 'PATCH' | 'DELETE', path: string, body: unknown, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API}${path}`, {
      method, signal: controller.signal,
      headers: { accept: 'application/json', 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    if (!response.ok) throw new GatewayHttpError(response.status, response.statusText, errorDetail(text));
    return (text ? JSON.parse(text) : {}) as T;
  } finally {
    clearTimeout(timer);
  }
}

async function getJson<T>(path: string, timeoutMs = 8000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API}${path}`, { signal: controller.signal, headers: { accept: 'application/json' } });
    if (!response.ok) throw new GatewayHttpError(response.status, response.statusText, errorDetail(await response.text()));
    return await response.json() as T;
  } finally {
    clearTimeout(timer);
  }
}

export type AblationCatalog = {
  simulators?: { booksim?: boolean; booksim_power_audited?: boolean };
  workloads: { workload_id: string; label?: string; nodes: number; events?: number; trace_sha256?: string; active_nodes?: number }[];
  topologies: { topology_id: string; family?: string; label?: string; nodes?: number; note?: string; support?: string }[];
  defaults: { packet_size?: number; vc_buf_size?: number; use_noc_latency?: number; seed?: number };
  knob_dimensions?: Record<string, { values?: number[]; source?: string; scope?: string }>;
  override_exclusions: string[]; max_overrides: number; scope?: string;
};

export type AblationRequest = {
  workloads: string[];
  topologies: string[];
  packet_size?: number;
  vc_buf_size?: number;
  use_noc_latency?: number;
  jobs?: number;
  seed?: number;
  trace_packet_size?: number;
  time_scale?: number;
  burst_window?: number;
  rank_stride?: number;
  rank_offset?: number;
  overrides?: Record<string, string>;
};

export type AblationRunResult = {
  schema: string;
  out: string;
  command?: string[];
  duration_seconds: number;
  returncode: number;
  failed_cells: number;
  document: Record<string, unknown>;
  stdout?: string;
};

export const gateway = {
  base: API,
  health: () => getJson<GatewayHealth>('/health'),
  projects: () => getJson<{ projects: ProjectEntry[] }>('/projects').then(d => d.projects),
  project: (id: string) => getJson<ProjectDetail>(`/projects/${id}`),
  projectDraft: async (id: string) => {
    const { design_hash, ...rest } = await getJson<{ request?: Record<string, unknown>; workload_id?: string | null; source?: string; dirty?: boolean; design_hash?: string; updated_at?: string }>(`/projects/${id}/draft`);
    return { ...rest, revisionToken: design_hash };
  },
  topology: (revisionId: string) => getJson<Topology>(`/revisions/${revisionId}/topology`),
  compileResult: (revisionId: string) => getJson<CompileResult>(`/revisions/${revisionId}/compile-result`, 30000),
  revisionDiff: (revisionId: string, against?: string | null) => {
    const query = against ? `?against=${encodeURIComponent(against)}` : '';
    return getJson<RevisionDiff>(`/revisions/${encodeURIComponent(revisionId)}/diff${query}`, 30000);
  },
  run: (runId: string) => getJson<RunDetail>(`/runs/${runId}`),
  verifyRun: (runId: string) => postJson<{ status: string; bundle_id: string; file_count: number; files_checked: number }>(`/runs/${encodeURIComponent(runId)}/verify`, {}),
  runMatrix: (runId: string) => getJson<TrafficMatrix>(`/runs/${runId}/traffic-matrix`),
  runIntegrity: (runId: string) => getJson<RunIntegrity>(`/runs/${runId}/integrity`),
  runArtifacts: (runId: string) => getJson<RunArtifacts>(`/runs/${runId}/artifacts`),
  route: (revisionId: string, params: { routingClass?: string; src?: number; dst?: number }) => {
    const query = new URLSearchParams();
    if (params.routingClass) query.set('routing_class', params.routingClass);
    if (params.src !== undefined) query.set('src', String(params.src));
    if (params.dst !== undefined) query.set('dst', String(params.dst));
    return getJson<CanonicalRoute>(`/revisions/${revisionId}/route?${query.toString()}`, 15000);
  },
  simLoad: (runId: string) => getJson<SimLoad>(`/loom/simulation/load?run=${encodeURIComponent(runId)}&source=measured`, 15000),
  simSeries: (runId: string) => getJson<SimSeries>(`/loom/simulation/series?run=${encodeURIComponent(runId)}`, 20000),
  simLink: (runId: string, channel: string | number) => getJson<SimLink>(`/loom/simulation/link?run=${encodeURIComponent(runId)}&channel=${encodeURIComponent(String(channel))}`, 20000),
  loomCapabilities: () => getJson<LoomCapabilities>('/loom/capabilities', 30000),
  loomOrigin: () => getJson<LoomOrigin>('/loom/origin', 15000),
  topologySweep: () => getJson<import('./analysisCurves').SweepEvidence>('/analysis/topology-sweep', 15000),
  reports: () => getJson<{ reports?: GeneratedReport[] }>('/reports', 15000),
  reportUrl: (reportId: string) => `${API}/reports/${encodeURIComponent(reportId)}`,
  knobInventory: () => getJson<KnobInventory>('/catalog/knob-inventory', 15000),
  ablationCatalog: () => getJson<AblationCatalog>('/ablations/catalog', 15000),
  runAblation: (body: AblationRequest) => postJson<AblationRunResult>('/ablations', body, 630000),
  evaluationPlan: (revisionId: string) => getJson<EvaluationPlan>(`/revisions/${revisionId}/evaluation-plan`),
  evaluate: (revisionId: string, body: { backend?: string | null; questions?: string[] | null }) =>
    postJson<Job>(`/revisions/${revisionId}/evaluate`, body),
  job: (jobId: string) => getJson<Job>(`/jobs/${jobId}`),
  jobLog: (jobId: string, offset = 0, maxBytes = 65536) => getJson<JobLog>(`/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&max_bytes=${maxBytes}`),
  jobLogEventsUrl: (jobId: string) => `${API}/jobs/${encodeURIComponent(jobId)}/log/events`,
  obligations: (projectId: string) => getJson<Obligations>(`/projects/${encodeURIComponent(projectId)}/obligations`),
  compare: (a: string, b: string) => getJson<Comparison>(`/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`, 30000),
  projectJobs: (projectId: string, kind: string) => getJson<{ jobs?: Job[] }>(`/projects/${projectId}/jobs?kind=${encodeURIComponent(kind)}`),
  createProject: (name: string, workloadId?: string | null) => postJson<ProjectDetail>('/projects', { name, workload_id: workloadId ?? null }),
  createProjectFromPreset: (presetId: string, name?: string | null) => postJson<ProjectDetail>('/projects/from-preset', { preset_id: presetId, name: name ?? null }),
  renameProject: (id: string, name: string) => sendJson<ProjectDetail>('PATCH', `/projects/${id}`, { name }),
  deleteProject: (id: string) => sendJson<{ deleted?: boolean; project_id: string }>('DELETE', `/projects/${id}`, undefined),
  floorplan: (id: string) => getJson<FloorplanView>(`/projects/${id}/floorplan`),
  putFloorplan: (id: string, body: GridFloorplanRequest) => sendJson<FloorplanView>('PUT', `/projects/${id}/floorplan`, body),
  deleteFloorplan: (id: string) => sendJson<FloorplanView>('DELETE', `/projects/${id}/floorplan`, undefined),
  selectWorkload: (id: string, workloadId: string) => postJson<Record<string, unknown>>(`/projects/${id}/workload`, { workload_id: workloadId }),
  compileProject: async (id: string, revisionToken?: string) => {
    const { design_hash, ...result } = await postJson<{ revision_id?: string; design_hash?: string; certificate?: { overall?: string }; compilation?: { status?: string; error?: string | null } }>(`/projects/${id}/compile`, revisionToken ? { expected_draft_design_hash: revisionToken } : {}, 180000);
    if (result.compilation?.status !== 'COMPILED') throw new Error(result.compilation?.error ?? `Compilation ${result.compilation?.status ?? 'did not report success'}`);
    return { ...result, revisionToken: design_hash };
  },
  putDraft: async (id: string, request: Record<string, unknown>, revisionToken?: string) => {
    const { design_hash, ...rest } = await sendJson<{ request?: Record<string, unknown>; design_hash?: string; dirty?: boolean }>('PUT', `/projects/${id}/draft`, { request, expected_draft_design_hash: revisionToken });
    return { ...rest, revisionToken: design_hash };
  },
  draftHistory: (id: string) => getJson<Record<string, any>>(`/projects/${encodeURIComponent(id)}/draft-history`),
  restoreDraft: (id: string, snapshot: string, revisionToken: string) => postJson<Record<string, any>>(`/projects/${encodeURIComponent(id)}/draft-history/${encodeURIComponent(snapshot)}/restore`, { expected_draft_design_hash: revisionToken }),
  adoptOptimization: (id: string, candidateId: string, revisionToken: string) => postJson<Record<string, any>>(`/optimizations/${encodeURIComponent(id)}/candidates/${encodeURIComponent(candidateId)}/use`, { expected_draft_design_hash: revisionToken }),
  artifactUrl: (id: string, path: string) => `${API}/runs/${encodeURIComponent(id)}/artifact?path=${encodeURIComponent(path)}`,
  jobEventsUrl: (id: string) => `${API}/jobs/${encodeURIComponent(id)}/events`,
  topologyPreview: (id: string, request: Record<string, unknown>, topology: Record<string, unknown>) =>
    postJson<{ request?: Record<string, unknown> }>(`/projects/${id}/topology-preview`, { request, topology }),
  presets: () => getJson<{ presets?: { preset_id: string; name?: string; family?: string; generation?: string; description?: string }[] }>('/catalog/fabric-presets').then(d => d.presets ?? []),
  workloads: () => getJson<{ workloads?: { workload_id: string; display_name?: string; model_family?: string }[] }>('/catalog/workloads').then(d => d.workloads ?? []),
  capabilities: () => getJson<Record<string, any>>('/capabilities'),
  capabilityGaps: () => getJson<Record<string, any>>('/catalog/capability-gaps'),
  revisionArtifacts: (id: string) => getJson<Record<string, any>>(`/revisions/${encodeURIComponent(id)}/artifacts`),
  runEvidence: (id: string) => getJson<Record<string, any>>(`/runs/${encodeURIComponent(id)}/evidence`),
  optimizationCapabilities: () => getJson<Record<string, any>>('/optimization/capabilities', 30000),
  optimize: (revisionId: string, body: Record<string, unknown>) => postJson<Record<string, any>>(`/revisions/${encodeURIComponent(revisionId)}/optimize`, body),
  optimization: (id: string) => getJson<OptimizationView>(`/optimizations/${encodeURIComponent(id)}`),
  agentCapabilities: () => getJson<Record<string, any>>('/agents/capabilities'),
  setAgentConfig: (body: { baseUrl: string; model: string; apiKey?: string }) => postJson<Record<string, any>>('/agents/config', { base_url: body.baseUrl, model: body.model, api_key: body.apiKey || null }),
  agentChat: (id: string, body: { message: string; history: { role: string; content: string }[]; allowModel: boolean; includeDraft: boolean; revisionToken?: string; context?: unknown }) => postJson<Record<string, any>>(`/projects/${encodeURIComponent(id)}/agent/chat`, { message: body.message, history: body.history, allow_model: body.allowModel, include_draft: body.includeDraft, expected_draft_design_hash: body.revisionToken, context: body.context }, 45000),
  translateWorkload: async (id: string, body: { message: string; allowModel: boolean; revisionToken: string }) => {
    const { base_design_hash, ...result } = await postJson<Record<string, any>>(`/projects/${encodeURIComponent(id)}/agent/workload-proposals`, { message: body.message, allow_model: body.allowModel, expected_draft_design_hash: body.revisionToken }, 45000);
    return { ...result, baseRevisionToken: base_design_hash };
  },
  adoptWorkload: (id: string, proposal: string, revisionToken: string) => postJson<Record<string, any>>(`/projects/${encodeURIComponent(id)}/agent/workload-proposals/${encodeURIComponent(proposal)}/adopt`, { expected_draft_design_hash: revisionToken }),
  aiCapabilities: () => getJson<Record<string, any>>('/ai-topology-search/capabilities'),
  aiSearch: (projectId: string, revisionToken: string) => postJson<Job>(`/projects/${encodeURIComponent(projectId)}/ai-topology-search`, { expected_draft_design_hash: revisionToken }),
  aiSearchResult: (projectId: string, jobId: string) => getJson<Record<string, any>>(`/projects/${encodeURIComponent(projectId)}/ai-topology-search/${encodeURIComponent(jobId)}`),
  adoptAI: (projectId: string, jobId: string, candidateId: string, revisionToken: string) => postJson<Record<string, any>>(`/projects/${encodeURIComponent(projectId)}/ai-topology-search/${encodeURIComponent(jobId)}/candidates/${encodeURIComponent(candidateId)}/adopt`, { expected_draft_design_hash: revisionToken }),
  cancelJob: (jobId: string) => postJson<Job>(`/jobs/${jobId}/cancel`, {}),
};

export const GATEWAY_START = 'PYTHONPATH=tracks/t3-topology/dse VERITX_BOOKSIM_BIN=third_party/booksim2/src/booksim python3 -m uvicorn veritx_dse.gateway.app:app --host 127.0.0.1 --port 8099';

export function gatewayReason(error: unknown) {
  if (error instanceof GatewayHttpError) return error.detail ? `Gateway refused (${error.status}): ${error.detail}` : `Gateway refused with ${error.status}.`;
  if (error instanceof DOMException && error.name === 'AbortError') return 'The gateway did not answer within the client timeout.';
  const message = error instanceof Error ? error.message : 'The gateway could not be reached.';
  // The dev/preview proxy answers 5xx when the target socket is closed, so the raw status would
  // misreport a gateway that was simply never started.
  if (/^5\d\d /.test(message)) return `The /gw proxy could not reach the gateway (proxy returned ${message.trim()}).`;
  if (/Failed to fetch|NetworkError|ECONNREFUSED/i.test(message)) return 'No connection could be made to the gateway.';
  return message;
}
