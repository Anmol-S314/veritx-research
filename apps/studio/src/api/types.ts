// Linkage-contract types (product API v1). These envelope the frozen
// scientific views (DesignView, CompilationView, EvaluationView,
// RequirementReport, OptimizationStudyView) — they never duplicate their
// fields. See docs/product/STUDIO-FLOW-AUDIT.md.
import type {
  CompilationView,
  DesignView,
  EvaluationView,
  OptimizationStudyView,
  RequirementReport,
} from '../types';

export interface ProjectMeta {
  project_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface Flow {
  state: string;
  next_action: string;
  reason: string;
}

export interface DraftMeta {
  dirty: boolean;
  based_on_revision_id: string | null;
  workload_id: string | null;
  source: string | null;
  design_hash: string | null;
  updated_at: string | null;
}

export interface RevisionSummary {
  revision_id: string;
  display_name: string;
  created_at: string;
  design_hash: string;
  compilation_status: string;
  certificate_overall: string | null;
  error: string | null;
}

export interface RunSummary {
  run_id: string;
  display_name: string | null;
  project_id: string;
  revision_id: string;
  design_hash: string | null;
  backend: string | null;
  status: string | null;
  qualification: string | null;
  requirements_pass: boolean | null;
  started_at: string | null;
  completed_at: string | null;
  bundle_id: string | null;
  workload_id: string | null;
  completion_cycles: number | null;
}

export interface OptimizationSummary {
  optimization_id: string;
  base_revision_id: string;
  created_at: string;
  candidate_count: number;
  pareto_count: number;
  selected_candidate_id: string | null;
}

export interface ProjectView {
  contract_version: 1;
  project: ProjectMeta;
  active_revision_id: string | null;
  active_revision: RevisionView | null;
  /** Latest compile attempt (usable or refused). Never evaluated directly. */
  latest_attempt_revision_id: string | null;
  latest_attempt: RevisionSummary | null;
  /** Latest run scoped to the ACTIVE revision — never a newer attempt's. */
  latest_active_run: RunSummary | null;
  draft: DraftMeta;
  revisions: RevisionSummary[];
  runs: RunSummary[];
  optimizations: OptimizationSummary[];
  flow: Flow;
}

export interface Certificate {
  certificate_id: string;
  overall: 'PASS' | 'FAIL';
  obligations: { obligation: string; status: string; method: string; evidence: Record<string, unknown> }[];
}

export interface RevisionView {
  contract_version: 1;
  revision_id: string;
  display_name: string;
  project_id: string;
  created_at: string;
  design_hash: string;
  design: DesignView;
  compilation: CompilationView;
  certificate: Certificate | null;
}

export interface DraftView {
  contract_version: 1;
  project_id: string;
  workload_id: string | null;
  source: string | null;
  updated_at: string | null;
  design_hash: string | null;
  dirty: boolean;
  active_revision_id: string | null;
  latest_attempt_revision_id: string | null;
  request: Record<string, unknown> | null;
}

export type JobState =
  | 'QUEUED'
  | 'PREPARING'
  | 'RUNNING'
  | 'FINALIZING'
  | 'COMPLETED'
  | 'REFUSED'
  | 'FAILED'
  | 'CANCELLED';

export interface JobView {
  contract_version: 1;
  job_id: string;
  project_id: string;
  kind: 'EVALUATION' | 'OPTIMIZATION' | string;
  revision_id: string;
  state: JobState;
  submitted_at: string;
  updated_at: string;
  error_code: string | null;
  error_message: string | null;
  result: {
    run_id?: string;
    optimization_id?: string;
    /** SERVING jobs: the created experiment's id. */
    serving_id?: string;
    /** REPRODUCTION jobs: canonical scientific outcome label. */
    outcome?: 'SCIENTIFICALLY_REPRODUCED' | 'DIVERGED';
  } | null;
}

export interface RunView extends RunSummary {
  contract_version: 1;
  qualification_basis: string | null;
  evaluation: EvaluationView | null;
  requirements: RequirementReport | null;
  producer: {
    backend: string;
    producer_identity: string;
    config_hash: string;
    input_hash: string;
  } | null;
  evidence: {
    evidence_id: string;
    raw_evidence_digest: string;
    stats_digest: string | null;
    run_bundle: string | null;
  } | null;
  reason: string | null;
}

export interface EvidenceView {
  contract_version: 1;
  run_id: string;
  bundle_id: string | null;
  status: string | null;
  qualification: string | null;
  producer: RunView['producer'];
  evidence: RunView['evidence'];
  artifacts: { path: string; size_bytes: number }[];
  documents: Record<string, unknown>;
}

/** ExecutionIntegrityView: conservation + route realization, projected
 * from the authenticated evidence document. A counter the backend did not
 * emit is `NOT_AVAILABLE` with a null value — never zero. */
export interface IntegrityCounter {
  value: number | null;
  availability: 'MEASURED' | 'NOT_AVAILABLE';
}

export interface RunIntegrityView {
  contract_version: 1;
  run_id: string;
  packet_conservation: {
    declared: IntegrityCounter;
    loaded: IntegrityCounter;
    injected: IntegrityCounter;
    delivered: IntegrityCounter;
    verdict: 'CONSERVED' | 'VIOLATED' | 'NOT_MEASURED';
  };
  flit_conservation: {
    declared: IntegrityCounter;
    injected: IntegrityCounter;
    accepted: IntegrityCounter;
    verdict: 'CONSERVED' | 'VIOLATED' | 'NOT_MEASURED';
  };
  route_realization: {
    status: 'OBSERVED' | 'NOT_OBSERVED';
    scope: string;
    full_path_claimed: false;
    realized_digest: string | null;
  };
  evidence_id: string | null;
}

export interface RunVerifyView {
  contract_version: 1;
  run_id: string;
  status: 'VERIFIED';
  bundle_id: string;
  file_count: number;
  files_checked: number;
}

/** ArtifactChainView (v1): the canonical certified artifact DAG. Each
 * node is a real bundle artifact with its identity hash, its parent
 * artifacts and the obligations that proved it. Absent for a revision
 * that never compiled — no chain may be drawn around a refusal. */
export interface ArtifactChainNode {
  artifact: string;
  label: string;
  parents: string[];
  hash: string;
  proved_by: string[];
}

export interface ArtifactChainView {
  contract_version: 1;
  design_hash: string;
  certificate_id: string;
  nodes: ArtifactChainNode[];
}

/** PreflightView: the execution gate, evaluated before any run.
 * `ready` is the server's verdict; Studio never recomputes it. */
export interface PreflightGate {
  gate: string;
  state: string;
  reason: string | null;
  obligations_passed?: number | null;
  obligations_total?: number | null;
}

export interface PreflightView {
  contract_version: 1;
  revision_id: string;
  display_name: string | null;
  backend: string;
  backend_profile: string | null;
  network_clock_hz: number;
  expected_evidence_tier: string | null;
  route_observation_required: boolean;
  conservation_required: boolean;
  gates: PreflightGate[];
  ready: boolean;
  reason: string | null;
}

/** ValidationCampaignView (v1): machine-readable V01–V14 experiment
 * reports projected verbatim; prose campaigns are linked, never parsed. */
export interface ValidationCheck {
  name: string | null;
  authority_class: string | null;
  independence: string | null;
  verdict: string | null;
  detail: string | null;
  values: Record<string, unknown> | null;
  finding: string | null;
  quarantined: boolean;
}

export interface ValidationExperiment {
  id: string;
  title: string | null;
  status: string | null;
  passed: boolean;
  workload: string | null;
  profile_id: string | null;
  fabric: Record<string, unknown> | null;
  authority: Record<string, unknown> | null;
  veritx: Record<string, unknown> | null;
  sweep: Record<string, unknown> | null;
  quarantined_findings: unknown[];
  checks: ValidationCheck[];
}

export interface MutationRecord {
  name: string | null;
  caught: boolean;
  expected: string | null;
  detail: string | null;
}

export interface MetamorphicProbe {
  name: string | null;
  invariant: string | null;
  passed: boolean;
  detail: string | null;
  observations: Record<string, unknown>;
}

export interface EngineGateCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface EngineGate {
  name: string | null;
  passed: boolean;
  detail: string | null;
  checks: EngineGateCheck[];
}

export interface ValidationCampaignsView {
  contract_version: 1;
  experiments: ValidationExperiment[];
  mutations: {
    kind: string;
    document: string;
    caught: number;
    total: number;
    mutations: MutationRecord[];
  };
  metamorphic: {
    kind: string;
    document: string;
    passed: number;
    total: number;
    probes: MetamorphicProbe[];
  };
  engines: {
    kind: string;
    document: string;
    engines: EngineGate[];
  };
  intervention: {
    kind: string;
    document: string;
    supported: boolean;
    problems: unknown[];
    rows: Record<string, unknown>[];
  };
  prose_campaigns: { document: string }[];
  findings_document: string;
}

export interface OptimizationView {
  contract_version: 1;
  optimization_id: string;
  project_id: string;
  base_revision_id: string;
  created_at: string;
  study: OptimizationStudyView;
  candidate_runs: {
    candidate_id: string;
    performance_result_id: string | null;
    requirement_report_id: string | null;
    run_id: string | null;
    evidence_kind: 'product-run' | 'optimization-candidate' | string;
    evaluation_status: string | null;
    evaluation_authority: string | null;
  }[];
  candidate_evidence_note: string | null;
  selected_candidate_id: string | null;
}

export interface EngineQualification {
  role: string;
  integration: string;
  numerical: string;
  independence: string;
  qualified_domains: string[];
  limitations: string[];
}

export interface QualificationView {
  contract_version: 1;
  validation_sha: string | null;
  engines: Record<string, EngineQualification>;
  workload_levels: Record<string, string>;
}

export interface WorkloadCatalogEntry {
  workload_id: string;
  display_name: string;
  description: string;
  source: string;
  content_digest: string;
  model_family: string;
  model_name: string | null;
  serving_mode: string | null;
  parallelism: { tp: number; pp: number; ep: number; dp: number };
  collectives: {
    kind: string;
    dimension: string;
    payload_bytes: number;
    traffic_class: string | null;
  }[];
  agents: { kind: string; count: number }[];
  noc: Record<string, unknown>;
  request: Record<string, unknown>;
}

export interface WorkloadCatalogView {
  contract_version: 1;
  workloads: WorkloadCatalogEntry[];
}

/** WorkloadLoweringView (v1): the canonical workload → collectives →
 * logical-messages chain, projected from LogicalMessageArtifactV2.
 * Flows aggregate per-step messages per (collective, src, dst, class);
 * the aggregation conserves the artifact's message count. */
export interface LoweringSchedule {
  collective_id: string;
  kind: string;
  algorithm: string;
  k: number;
  payload_bytes: number;
  steps: number;
  message_count: number;
  message_bytes: number;
  per_rank_sent: number;
  aggregate_payload: number;
}

export interface LoweringFlow {
  operation_id: string;
  src_rank: number;
  dst_rank: number;
  traffic_class: string;
  message_count: number;
  payload_bytes: number;
  max_step: number;
}

export interface WorkloadLoweringView {
  contract_version: 1;
  workload_id: string;
  message_artifact_id: string;
  participant_count: number;
  traffic_class: string;
  collectives: LoweringSchedule[];
  flows: LoweringFlow[];
  totals: {
    collectives: number;
    messages: number;
    flows: number;
    payload_bytes: number;
  };
}

export interface FabricPresetCatalogView {
  contract_version: 1;
  presets: { preset_id: string; name: string; description: string }[];
}

export interface CompareCompatibility {
  compatible: boolean;
  same_workload: boolean;
  same_backend: boolean;
  both_qualified: boolean;
  metric_units: string;
  reasons: string[];
}

export interface CompareView {
  contract_version: 1;
  a: CompareSide;
  b: CompareSide;
  compatibility: CompareCompatibility;
  rows: { key: string; a: number | null; b: number | null; comparable: boolean }[];
  note: string;
}

export interface CompareSide {
  run_id: string;
  display_name: string | null;
  revision_id: string;
  design_hash: string | null;
  backend: string | null;
  status: string | null;
  qualification: string | null;
  workload_id: string | null;
  noc: Record<string, unknown> | null;
  locked_derived: Record<string, unknown> | null;
  requirements_pass: boolean | null;
}

/** ServingExperiment resource (v1): one canonical serve run — submitted
 * as a Job, stored with its CanonicalServingEvidence verbatim. A refused
 * experiment keeps its exact refusal reason; nothing is upgraded. */
export interface ServingSummary {
  serving_id: string | null;
  state: string | null;
  workload_id: string | null;
  created_at: string | null;
  request_count: number | null;
  rounds: number | null;
  reusable: boolean | null;
}

/** CanonicalServingEvidence document (v1), returned verbatim by the
 * canonical serve path (srota/CanonicalServingEvidence). Cycles are
 * model-internal under the declared linear service profile. No time-domain
 * conversion authority is attached, so values are never compared across
 * SERVING_LOGICAL_CYCLE / MODEL_SERVICE_CYCLE / NETWORK_BOOKSIM_CYCLE. */
export interface CanonicalServingEvidence {
  type: string;
  schema_version: number;
  evidence_id: string;
  execution_mode: string;
  network_evidence_tier: string;
  expansion_authority: string;
  instance_count: number;
  served_instances: number[];
  instances_with_completions: number[];
  every_instance_served: boolean;
  /** [instance, completion_cycles] */
  endpoint_completions: [number, number][];
  /** [request_id, ttft_cycles, completion_cycles] */
  request_metrics: [string, number | null, number | null][];
  /** Per-round injection payload. Currently emitted all-null by the
   * canonical path; treat as unavailable rather than empty. */
  autonomous_injection_packets: unknown[];
  backend_evidence_ids: string[];
  backend_id: string;
  serving_binding_id: string;
  participant_mapping_id: string;
  machine_id: string;
  namespace_id: string;
  serving_config_id: string;
  standalone_config_sha256: string;
  embedded_fabric_abi_version: string;
  astra_source_revision: string;
  astra_binary_sha256: string;
  astra_binary_size: number;
  workload_id: string;
  reusable: boolean;
  request_count: number;
  rounds: number;
}

/** One selectable cluster service-semantics config. Geometry is read from
 * the document by the gateway so the UI can describe a choice without
 * interpreting it. */
export interface ServingConfigEntry {
  contract_version: 1;
  config_id: string;
  display_name: string;
  description: string;
  source: string;
  content_digest: string;
  geometry: {
    num_nodes: number;
    instances: number;
    tp_sizes: number[];
    ep_sizes: number[];
    pp_sizes: number[];
    pd_types: string[];
    models: string[];
    hardware: string[];
    link_bw: number[] | number | null;
    link_latency: number[] | number | null;
  };
}

/** One selectable JSONL request trace. */
export interface ServingTraceEntry {
  contract_version: 1;
  trace_id: string;
  display_name: string;
  description: string;
  source: string;
  content_digest: string;
  requests: number;
}

/** Inputs the canonical serve path can be pointed at, plus the tracked
 * defaults. The gateway lists these; it does not interpret them. */
export interface ServingConfigCatalogView {
  contract_version: 1;
  configs: ServingConfigEntry[];
  traces: ServingTraceEntry[];
  default_config: string;
  default_trace: string;
}

export interface ServingView {
  schema_version: 1;
  serving_id: string;
  project_id: string;
  state: string;
  workload_id: string | null;
  num_reqs: number | null;
  /** Declared service-profile overrides that produced this run. */
  profile_overrides: Record<string, number | string> | null;
  /** Wall-clock budget applied to the canonical run, seconds. */
  timeout_s: number | null;
  error: string | null;
  evidence: {
    request_count: number;
    requests_expected: number;
    rounds: number;
    machine_id: string;
    namespace_id: string;
    evidence_ids: string[];
    document: CanonicalServingEvidence | null;
  } | null;
  created_at: string | null;
}
