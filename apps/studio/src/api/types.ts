import type {
  CompiledSystemArtifact,
  CompilationView,
  DesignView,
  EvaluationView,
  OptimizationStudyView,
  RequirementReport,
  TopologyView,
} from '../types';

export interface DraftGeometryView {
  contract_version: 1;
  compile_check_status: 'NOT_RUN';
  design_hash: string;
  topology: {
    family: string;
    routers: { router_id: number; coordinates: number[]; seat_capacity: number }[];
    channels: { channel_id: number; src_router: number; dst_router: number; width_bits: number }[];
    shared_links: { shared_link_id: number; src_router: number; taps: number[]; width_bits: number }[];
  };
  endpoints: { endpoint_id: number; router_id: number; group_index: number; instance_index: number; kind: string }[];
}

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

interface TrafficMatrixBase {
  contract_version: 2;
  run_id: string;
  revision_id: string | null;
  design_hash: string | null;
}

export interface TrafficMatrixUnavailableView extends TrafficMatrixBase {
  availability: 'NOT_AVAILABLE';
  reason: string;
  source: {
    trace: null;
    backend: null;
    declared_packets: number | null;
    note: string;
  };
}

export interface TrafficMatrixView extends TrafficMatrixBase {
  availability: 'MEASURED';
  source: {
    trace: string;
    backend: string;
    declared_packets: number | null;
    note: string;
  };
  nodes: number;
  packets: number;
  flits: number;
  distinct_pairs: number;
  classes: Record<string, number>;
  matrix: number[][];
  flit_matrix: number[][];
  pairs: { src: number; dst: number; packets: number; flits: number }[];
}

export type TrafficMatrixResponse =
  | TrafficMatrixUnavailableView
  | TrafficMatrixView;

/** Measured per-channel load from the sampled-counters artifact.
 * Served only when the run was executed with the sampler enabled;
 * otherwise the endpoint refuses with a typed code (NO_RUN,
 * NO_MEASURED, …), never an empty table. */
export interface SimLoadChannel {
  logical_channel_id: number;
  flits_total: number;
  cycles_sampled: number;
  utilization: number;
  peak_window_utilization: number;
  has_stalls: boolean;
}

export interface SimLoadView {
  run: string;
  source: 'measured';
  capacity_formula: string;
  link_capacity_flits_per_cycle: number;
  sample_period_cycles: number;
  num_windows: number;
  cycles_sampled: number;
  time_resets_observed: number;
  channels: SimLoadChannel[];
  provenance: Record<string, unknown>;
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
  analysis_backends?: {
    backend_id: string;
    question: string;
    status: string | null;
  }[] | null;
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
  latest_attempt_revision_id: string | null;
  latest_attempt: RevisionSummary | null;
  latest_active_run: RunSummary | null;
  latest_static_evaluation: RunSummary | null;
  latest_serving_experiment: {
    serving_id: string | null;
    state: string | null;
    created_at: string | null;
  } | null;
  latest_optimization_study: {
    optimization_id: string;
    base_revision_id: string;
    created_at: string;
    candidate_count: number;
    pareto_count: number;
    selected_candidate_id: string | null;
  } | null;
  active_evaluation: {
    supported: boolean;
    reason: string | null;
    domain: 'compile' | 'intent_lowering' | 'backend_profile' | null;
  } | null;
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
  | 'CANCELLED'
  | 'CANCELLING';

export interface JobView {
  contract_version: 1;
  job_id: string;
  project_id: string;
  kind: 'EVALUATION' | 'OPTIMIZATION' | string;
  revision_id: string | null;
  cancellable?: boolean;
  draft_design_hash?: string | null;
  state: JobState;
  submitted_at: string;
  updated_at: string;
  error_code: string | null;
  error_message: string | null;
  result: {
    run_id?: string;
    revision_id?: string;
    optimization_id?: string;
    serving_id?: string;
    outcome?: 'SCIENTIFICALLY_REPRODUCED' | 'DIVERGED';
    reproductions?: Record<string, {
      backend?: string | null;
      status?: string | null;
      outcome?: string | null;
      reason?: string | null;
    }> | null;
  } | null;
}

export interface AISearchCapabilities {
  contract_version: 1;
  configured: boolean;
  backend_present: boolean;
  model: string | null;
  reason: string | null;
  limits: { max_proposals: number; max_routers: number; max_channels: number;
    max_network_degree: number; max_seats: number; backend_timeout_s: number };
  max_model_output_tokens: number;
  job_timeout_s: number;
  objective: 'completion_cycles';
}

export interface AITopologyAttempt {
  attempt: number;
  candidate_id: string | null;
  topology: Record<string, unknown> | null;
  rationale: string | null;
  status: string;
  reason: string | null;
  compilation_status: string | null;
  objective_values: { completion_cycles?: number };
  adoptable: boolean;
  backend_profile: string | null;
  execution_fidelity: string | null;
  requirements_pass: boolean | null;
}

export interface AISearchView {
  contract_version: 1;
  job: JobView;
  model: string | null;
  base_design_hash: string;
  stale: boolean;
  attempts: AITopologyAttempt[];
}

export interface RunView extends RunSummary {
  contract_version: 1;
  qualification_basis: string | null;
  evaluation: EvaluationView | null;
  requirements: RequirementReport | null;
  evaluation_plan: EvaluationPlanView | null;
  analyses: FederatedAnalysisView[] | null;
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
  /** Server-computed freshness of this run against the design currently on
   *  screen. Computed by the gateway from three server-owned facts and never
   *  in a client, because a stale-result warning that can disagree with the
   *  server about staleness is worse than none. Absent when the run's owning
   *  project cannot be resolved, which the run view already refuses. */
  freshness?: RunFreshness | null;
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
  } | null;
  flit_conservation: {
    declared: IntegrityCounter;
    injected: IntegrityCounter;
    accepted: IntegrityCounter;
    verdict: 'CONSERVED' | 'VIOLATED' | 'NOT_MEASURED';
  } | null;
  route_realization: {
    status: 'OBSERVED' | 'NOT_OBSERVED';
    scope: string;
    full_path_claimed: false;
    realized_digest: string | null;
  } | null;
  evidence_id: string | null;
  analyses?: Record<string, Record<string, unknown>> | null;
}

export interface RunVerifyView {
  contract_version: 1;
  run_id: string;
  status: 'VERIFIED';
  bundle_id: string;
  file_count: number;
  files_checked: number;
}

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
  evaluation_supported: boolean;
  evaluation_note: string | null;
  evaluation_domain: 'compile' | 'intent_lowering' | 'backend_profile' | null;
}

export interface WorkloadCatalogView {
  contract_version: 1;
  workloads: WorkloadCatalogEntry[];
}

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

export interface LoweringOperationMemory {
  input_bytes: number | null;
  weight_bytes: number | null;
  output_bytes: number | null;
  input_loc: string | null;
  weight_loc: string | null;
  output_loc: string | null;
  duration_ns: number | null;
  batch_tag: string | null;
}

export interface LoweringOperation {
  operation_id: string;
  kind: string;
  deps: string[];
  owner: number | null;
  phase: string | null;
  step: number | null;
  label: string;
  memory?: LoweringOperationMemory;
  memory_bytes?: number;
}

export interface LoweringMemoryDemand {
  operation_count: number;
  compute_count: number;
  memory_demand_ops: number;
  total_operand_bytes: number;
  has_memory_demand: boolean;
}

export interface WorkloadLoweringView {
  contract_version: 1;
  workload_id: string;
  message_artifact_id: string;
  participant_count: number;
  traffic_class: string;
  collectives: LoweringSchedule[];
  flows: LoweringFlow[];
  operations: LoweringOperation[];
  memory_demand: LoweringMemoryDemand;
  totals: {
    collectives: number;
    messages: number;
    flows: number;
    payload_bytes: number;
  };
}

export interface KnobInventoryField {
  name: string;
  type: string;
  values?: string[];
  required: boolean;
  default: unknown;
  group?: string;
  binds?: { field: string; source: string };
}
export interface KnobInventoryFamily {
  kind: string;
  label: string;
  fields: KnobInventoryField[];
}
export interface KnobInventoryView {
  type: string;
  topology: KnobInventoryFamily[];
  controls: KnobInventoryField[];
  not_covered: string[];
  notes: string;
}

export interface ExecutionEvidenceCase {
  case_id: string;
  status: string | null;
  reason: string | null;
  stage: string | null;
  design_hash: string | null;
  certificate: string | null;
  knobs: Record<string, Record<string, unknown>>;
  routers?: number | null;
  channels?: number | null;
  analyses: Record<string, unknown>;
  seconds: number | null;
}
export interface ExecutionEvidenceCohort {
  cohort: string;
  cases: ExecutionEvidenceCase[];
  evaluated: number;
}
export interface ExecutionEvidenceView {
  type: string;
  cohorts: ExecutionEvidenceCohort[];
  case_count: number;
  notes: string;
}

export interface FabricPresetCatalogEntry {
  preset_id: string;
  name: string;
  description: string;
  /** Preset generation ("v2" guided-path, "v4" typed-topology). */
  generation?: string;
  family: string;
  topology: Record<string, unknown>;
  dependencies: { source: string; target: string; kind: string }[];
}

export interface FabricPresetCatalogView {
  contract_version: 1;
  presets: FabricPresetCatalogEntry[];
}

/** One shipped preset materialized to its certified graph shape.
 * Routers carry coordinates when the family places them; channels are
 * directed (one row per direction). */
export interface PresetGraphRouter {
  router_id: number;
  coordinates: number[];
  seat_capacity: number;
}

export interface PresetGraphChannel {
  channel_id: number;
  src_router: number;
  dst_router: number;
  width_bits: number;
  latency_cycles: number;
}

export interface PresetGraphEndpoint {
  endpoint_id: number;
  kind: string;
  group_index: number;
  instance_index: number;
  router_id: number;
  port_id: number;
}

export interface PresetGraphView {
  contract_version: 1;
  preset_id: string;
  generation: string;
  design_hash: string;
  topology_hash: string;
  family: string;
  routers: PresetGraphRouter[];
  channels: PresetGraphChannel[];
  endpoints: PresetGraphEndpoint[];
  counts: { routers: number; channels: number; seats: number; endpoints: number };
}

export interface CompareCompatibility {
  compatible: boolean;
  same_workload?: boolean;
  same_backend?: boolean;
  both_qualified?: boolean;
  metric_units?: string;
  reasons: string[];
}

/** One metric on one comparison row. `comparable` is the engine's own
 *  admissibility verdict; a false row still carries both values and the
 *  reason they cannot be compared, which is the useful part. */
export interface CompareRow {
  question: string;
  key: string;
  dimensions?: string | null;
  a: number | null;
  b: number | null;
  unit?: string | null;
  comparable: boolean;
  verdict?: string | null;
  differs?: string | null;
  delta_b_minus_a?: number | null;
  a_evidence?: string | null;
  b_evidence?: string | null;
  reason?: string | null;
}

export interface CompareView {
  contract_version: 1;
  a: CompareSide;
  b: CompareSide;
  compatibility: CompareCompatibility;
  rows: CompareRow[];
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

export interface ServingSummary {
  serving_id: string | null;
  state: string | null;
  workload_id: string | null;
  created_at: string | null;
  request_count: number | null;
  rounds: number | null;
  reusable: boolean | null;
}

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
  endpoint_completions: [number, number][];
  request_metrics: [string, number | null, number | null][];
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

export interface ServingTraceEntry {
  contract_version: 1;
  trace_id: string;
  display_name: string;
  description: string;
  source: string;
  content_digest: string;
  requests: number;
}

export interface ServingConfigCatalogView {
  contract_version: 1;
  configs: ServingConfigEntry[];
  traces: ServingTraceEntry[];
  default_config: string;
  default_trace: string;
}

export interface ServingExperimentFacets {
  models: string[];
  dense_or_moe: string;
  instances: number;
  multi_instance: boolean;
  tp_sizes: number[];
  ep_sizes: number[];
  dp_sizes: number[];
  prefill_decode_split: boolean;
  pd_types: string[];
  num_nodes: number;
  hardware: string[];
  markers: string[];
}

export interface ServingExperimentReadiness {
  model_configs: Record<string, boolean>;
  astra_binary_present: boolean;
  booksim_configured: boolean;
}

export interface ServingExperimentEntry {
  contract_version: 1;
  experiment_id: string;
  config_id: string;
  trace_id: string;
  display_name: string;
  facets: ServingExperimentFacets;
  config_source: string;
  config_digest: string | null;
  trace_source: string;
  trace_digest: string | null;
  trace_requests: number;
  readiness: ServingExperimentReadiness;
}

export interface ServingExperimentGap {
  model: string;
  source: string;
  reason: string;
}

export interface ServingExperimentCatalogView {
  contract_version: 1;
  default_config: string | null;
  default_trace: string | null;
  experiments: ServingExperimentEntry[];
  gaps: ServingExperimentGap[];
}

export interface ServingView {
  schema_version: 1;
  serving_id: string;
  project_id: string;
  state: string;
  workload_id: string | null;
  num_reqs: number | null;
  profile_overrides: Record<string, number | string> | null;
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

export interface RevisionDiffRow {
  field: string;
  before: unknown;
  after: unknown;
  kind: 'added' | 'removed' | 'changed';
  detail?: string | null;
}

export interface RevisionDiffView {
  contract_version: 1;
  revision_id: string;
  display_name: string | null;
  against_revision_id: string | null;
  against_display_name: string | null;
  has_basis: boolean;
  reason: string | null;
  design_changes: RevisionDiffRow[];
  derived_changes: RevisionDiffRow[];
  capability_changes: RevisionDiffRow[];
}

export interface PlannedAnalysisView {
  question: string;
  backend: string | null;
  support: string;
  readiness: string;
  qualification?: {
    numerical_qualification: string;
    calibration: string;
    basis: string;
  } | null;
  model_fidelity: string | null;
  qualification_profile: string | null;
  reason: string | null;
  limitations: string[];
}

export interface EvaluationPlanView {
  contract_version: 1;
  revision_id: string | null;
  design_hash: string;
  resolved_fabric_hash: string;
  workload_id: string;
  analyses: PlannedAnalysisView[];
}

export interface NormalizedMetricView {
  key: string;
  value: number | null;
  unit: string | null;
  source_metric_key: string | null;
  dimensions: unknown[][];
}

export interface FederatedAnalysisView {
  question: string;
  backend_id: string | null;
  status: string;
  model_fidelity: string | null;
  qualification: string | null;
  native_evidence_id: string | null;
  reason: string | null;
  native_summary: Record<string, unknown> | null;
  normalized_metrics: NormalizedMetricView[] | null;
  limitations: string[] | null;
}

export interface FederatedCapabilityView {
  question: string;
  support: string;
  fidelity: string;
  limitations: string[];
}

export interface FederationBackendView {
  backend_id: string;
  registered: boolean;
  /** Install-presence fact (binary present / extension built), never a
   *  runtime-readiness fact — the server serves no runtime probe. */
  install_present: boolean;
  install_detail: string;
  capabilities: FederatedCapabilityView[];
}

export interface FederationBackendsView {
  contract_version: 1;
  backends: FederationBackendView[];
}

export interface HealthView {
  status: string;
  api: string;
  backends: Record<string, {
    state: 'PRESENT' | 'ABSENT';
    binary_present: boolean;
    manifest_present: boolean;
  }>;
}

export type DesignReadiness =
  | 'READY'
  | 'INCOMPLETE'
  | 'INVALID'
  | 'PREFLIGHT_BLOCKED'
  | 'CAPABILITY_LIMITED_BUT_COMPILABLE'
  | 'VALIDATED_DECLARATION';

export type FindingClass =
  | 'BLOCKING_ERROR'
  | 'DOWNSTREAM_LIMITATION'
  | 'INFORMATION'
  | 'LEGACY_MIGRATION_NOTICE';

export type ReviewFreshness = 'CURRENT' | 'STALE';

export type EntrySemanticClass =
  | 'DECLARED'
  | 'DERIVED_PREVIEW'
  | 'METADATA'
  | 'CAPABILITY_CONSEQUENCE';

export interface DesignEntry {
  field: string;
  label: string;
  value: unknown;
  semantic_class: EntrySemanticClass;
  exposure_class: string;
  disclosure_depth: 'GUIDED' | 'EXPERT';
  source: 'SEMANTIC_DEFAULT' | 'RECOMMENDATION' | 'NONE' | null;
  active: boolean;
  capability_ref: string | null;
  ownership: {
    domain: string | null;
    canonical_field: string;
    scientific_name: string | null;
  };
}

export interface DesignSection {
  id: string;
  title: string;
  entries: DesignEntry[];
  advanced_active_count: number;
  blocking_count: number;
  limitation_count: number;
}

export interface DesignFinding {
  class: FindingClass;
  owner_domain: string;
  code: string;
  message: string;
  affected: string | null;
  blocking: boolean;
  remediation_owners: string[];
}

export interface DerivedSummary {
  id: string;
  label: string;
  value: unknown;
  kind: 'PRE_COMPILE_DERIVED_SUMMARY';
  semantic_class: 'DERIVED_PREVIEW';
}

export interface CapabilityConsequence {
  capability_id: string;
  choice: string;
  name: string | null;
  wiring: string;
  reason: string | null;
  limiting: string | null;
  claim_scope: string | null;
  stages: Record<string, string>;
  registry_version: string;
}

export interface DesignCompleteness {
  active_scientific_fields: string[];
  represented_fields: string[];
  non_active_fields: { field: string; reason: string }[];
  unrepresented_active_fields: string[];
  invariant_holds: boolean;
  law: string;
}

export interface ScientificDiffEntry {
  field: string;
  before: unknown;
  after: unknown;
  kind: 'added' | 'removed' | 'changed';
}

export interface DesignViewV2 {
  contract_version: 2;
  presentation: 'edit' | 'review';
  draft_identity: {
    project_id: string;
    draft_design_hash: string | null;
  };
  parent_revision_ref: { revision_id: string; label: string } | null;
  readiness: DesignReadiness;
  v5_scope?: {
    declarations: 'VALIDATED_DECLARATION'; compilation: 'NOT_RUN'; base_preview: 'BASE_ONLY';
    generic_evaluation: 'UNSUPPORTED'; native: 'UNQUALIFIED'; stage_limits: string;
    abstract_execution: 'EXPLICIT_INPUTS_REQUIRED_NOT_YET_CHECKED' | 'STRUCTURE_ONLY_EXECUTION_PREREQUISITES_MISSING';
  };
  compile_check_status?: 'NOT_RUN';
  sections: DesignSection[];
  derived_summaries: DerivedSummary[];
  validation_findings: DesignFinding[];
  capability_consequences: CapabilityConsequence[];
  completeness: DesignCompleteness;
  capability_semantics_version: string;
  registry_versions: {
    capability_semantics_version: string;
    capability_registry_version: number;
    exposure_registry_version: number;
  };
  scientific_diff?: ScientificDiffEntry[];
  review_freshness?: ReviewFreshness;
  review_snapshot?: {
    reviewed_draft_design_hash: string | null;
    current_draft_design_hash: string | null;
    bound_by: string[];
  };
  later_stage_claims?: {
    certificate: null;
    qualification: null;
    measurements: null;
    requirement_verdicts: null;
    note: string;
  };
}

export type ClaimStatus = 'PASS' | 'FAIL';

export type CdgAnalysisVerdict =
  | 'PASS' | 'FAIL' | 'UNSUPPORTED' | 'NOT_RUN';

export interface CertificateClaim {
  claim: string;
  scope: string;
  certificate_status: ClaimStatus;
  established: boolean;
  contributing_obligations: string[];
  contributing_statuses: Record<string, ClaimStatus>;
  aggregation: string;
  method: string | null;
  status?: ClaimStatus;
  analysis_verdict?: CdgAnalysisVerdict;
  detected_deadlock?: boolean;
  analysis_reason?: string | null;
}

export interface TechnicalObligation {
  obligation: string;
  meaning: string;
  status: ClaimStatus;
  method: string | null;
  evidence: Record<string, unknown>;
  failure_reason?: string | null;
}

export interface CdgCycleNode {
  channel_id: number | null;
  vc: number | null;
}

export interface CdgAnalysis {
  analysis_verdict: CdgAnalysisVerdict;
  cycle_witness: CdgCycleNode[];
  acyclic: boolean | null;
  unsupported_reason: string | null;
  sccs_gt_1: number | null;
  node_count: number | null;
  edge_count: number | null;
  cdg_route_classes: string[] | null;
  escape_vcs: number[] | null;
  vc_count: number | null;
  route_realization_scheme: string | null;
  detected_deadlock: boolean;
}

export interface CertificateObligation {
  obligation: string;
  status: ClaimStatus;
  method: string | null;
  evidence: Record<string, unknown>;
}

export interface CompileCertificate {
  claim_shape_version?: number;
  overall: ClaimStatus | null;
  certificate_id: string | null;
  claims: CertificateClaim[];
  obligations: CertificateObligation[];
  technical_only: TechnicalObligation[];
  deadlock_analysis: CdgAnalysis | null;
  vocabulary: {
    obligation_status: ClaimStatus[];
    cdg_analysis_verdict: CdgAnalysisVerdict[];
  };
  additional_obligations: CertificateObligation[];
  claim_count: number;
  obligation_count: number;
}

export interface CompileSummaryGroup {
  declared: {
    topology_family?: string | null;
    side_length?: number | null;
    concentration?: number | null;
    link_width?: number | null;
    arbitration?: string | null;
    parallelism?: { tp: number | null; pp: number | null;
                    ep: number | null; dp: number | null };
    agents?: { kind: string; count: number }[];
    requirements?: number;
  };
  derived: {
    routers?: number;
    channels?: number;
    seats?: number;
    endpoints?: number;
    vc_count?: number | null;
    routing_classes?: string[];
  };
  verified: CertificateClaim[];
  certificate_overall: ClaimStatus | null;
  compilation_status: string | null;
}

export interface MappingRow {
  rank: number | null;
  agent_kind: string | null;
  group_index: number | null;
  instance_index: number | null;
  endpoint_id: number | null;
  coordinates: { tp: number; pp: number; ep: number; dp: number } | null;
}

export interface MappingGroup {
  available: boolean;
  rows: MappingRow[];
  rank_count?: number;
  parallelism?: { tp: number; pp: number; ep: number; dp: number } | null;
  idle_agents?: {
    count: number;
    by_kind: Record<string, number>;
    mapped: number;
    attached: number;
  };
}

export type FabricDetailLevel = 'FULL' | 'ROUTERS_AND_LINKS' | 'AGGREGATE';

export interface FabricGroup {
  available: boolean;
  counts?: {
    routers: number; channels: number; seats: number;
    attached: number; unused_seats: number;
  };
  detail_level?: FabricDetailLevel;
  detail_thresholds?: { full_detail_max: number; router_detail_max: number };
  topology?: TopologyView | null;
}

export interface RouteEntry {
  routing_class: string;
  src: number;
  dst: number;
  channel_id: number;
}

export interface ChannelHop {
  channel_id: number;
  src_router: number;
  src_port: number;
  dst_router: number;
  dst_port: number;
}

export interface RouteObservation {
  available: boolean;
  scope: string;
  claim: string;
  limit: string;
  realized_digest: string | null;
  reason?: string;
  source?: string;
  realization?: string;
}

export interface RoutingGroup {
  available: boolean;
  routing_classes?: string[];
  default_class?: string | null;
  entry_count?: number;
  entries?: RouteEntry[];
  channel_hops?: ChannelHop[];
  observation?: RouteObservation;
  observation_note?: string;
}

export interface CanonicalRoute {
  routing_class: string;
  src: number;
  dst: number;
  routers: number[];
  hops: ChannelHop[];
  terminates: boolean;
  terminal: string | null;
  reason: string | null;
}

export interface DeadlockWitness {
  acyclic: boolean | null;
  sccs_gt_1: number | null;
  node_count: number | null;
  edge_count: number | null;
  cdg_route_classes: string[] | null;
  escape_vcs: number[] | null;
  vc_count: number | null;
  route_realization_scheme: string | null;
}

export interface ResourcesGroup {
  available: boolean;
  vc_count?: number | null;
  vc_ids?: number[];
  traffic_class_to_vcs?: [string, number[]][];
  vc_to_routing_class?: [number, string][];
  allowed_transitions?: number[][];
  transitions_are_identity?: boolean;
  escape_vcs?: number[];
  derivation?: string | null;
  arbitration?: Record<string, unknown>;
  deadlock?: { status: ClaimStatus; method?: string;
               witness?: DeadlockWitness; evidence?: Record<string, unknown> };
  editable?: boolean;
}

export interface AddressDecodeRow {
  name: string | null;
  base: number | null;
  size: number | null;
  target_agent_kind: string | null;
  target_agent_instance: number | null;
  target_endpoint_id: number | null;
  legacy_target_agent_group: number | null;
}

export interface AddressDecodeGroup {
  available: boolean;
  rows: AddressDecodeRow[];
  address_transform?: string | null;
  unmatched_address_policy?: string | null;
}

export interface ProvenanceGroup {
  revision_id: string | null;
  design_hash: string | null;
  compiler_semantics_version: number | null;
  resolved_fabric_hash: string | null;
  certificate_id: string | null;
  artifact_hashes: Record<string, string>;
  artifact_chain: ArtifactChainView | null;
}

export interface StagedCompileResult {
  contract_version: 1;
  available: false;
  staged: true;
  revision_id: string | null;
  display_name: string | null;
  design_hash: string | null;
  compilation_status: string;
  stopped_at_stage: string | null;
  produced_stages: string[];
  reason: string;
  staged_topology: (TopologyView & {
    staged: true;
    stopped_at_stage: string;
    produced_stages: string[];
  }) | null;
  unavailable_groups: string[];
  certificate: { available: false; reason: string };
  capability_consequences: CapabilityConsequence[];
}

export interface CertificateAbsence {
  available: false;
  reason: string;
}

export function hasClaims(
  certificate: CompileCertificate | CertificateAbsence | undefined,
): certificate is CompileCertificate {
  return !!certificate && 'claims' in certificate;
}

export interface ControlPlaneGroup {
  available: boolean;
  declared: boolean;
  scope: 'DECLARED_STRUCTURE_ONLY';
  reason?: string;
  claim?: string;
  subnet: {
    id: number;
    k: number;
    c: number;
    vcs: string[];
    vc_count: number;
    routing: string;
    routing_class: string;
    scope: 'DECLARED_STRUCTURE_ONLY';
    artifact: string;
    artifact_hash: string;
  } | null;
  class_to_subnet: {
    available: boolean;
    scope: 'DECLARED_STRUCTURE_ONLY';
    artifact: string;
    artifact_hash: string | null;
    rows: { traffic_class: string; subnet: number }[];
    reason?: string;
  } | null;
  editable: false;
}

export interface CompileResultView {
  contract_version: 1;
  available: boolean;
  staged?: boolean;
  stopped_at_stage?: string | null;
  produced_stages?: string[];
  staged_topology?: StagedCompileResult['staged_topology'];
  unavailable_groups?: string[];
  reason?: string;
  revision_id?: string | null;
  display_name?: string | null;
  compiled_at?: string | null;
  design_hash?: string | null;
  certificate?: CompileCertificate | CertificateAbsence;
  groups?: {
    summary: CompileSummaryGroup;
    mapping: MappingGroup;
    fabric: FabricGroup;
    routing: RoutingGroup;
    resources: ResourcesGroup;
    address_decode: AddressDecodeGroup;
    provenance: ProvenanceGroup;
    /** Optional for compatibility with compile-result views predating Plane C. */
    control_plane?: ControlPlaneGroup;
  };
  group_order?: string[];
  topology_hash?: string | null;
  capability_consequences?: CapabilityConsequence[];
  /** The compiled-system root. Its `children.legacy_control_plane` is the
   *  multi-plane fact: a hash when the fabric declared Plane C, null on a
   *  single-plane fabric. The view carries no Plane C timing or traffic. */
  compiled_system?: CompiledSystemArtifact;
  system_hash?: string;
}

export interface OptimizationParamCapability {
  name: string;
  field: string;
  kind: 'int' | 'bool' | 'str' | 'enum';
  expressible: boolean;
  compilable: boolean;
  effective: boolean;
  backend_executable: boolean;
  executable: boolean;
  qualified_for_certified_optimization: boolean;
  value_constraint: string;
  accepted_values: (string | number)[] | null;
  accepted_values_is_exhaustive: boolean;
  executable_values: (string | number)[] | null;
  value_source: string;
  reason: string | null;

}
export interface OptimizationCapabilities {
  schema_version: number;
  guided_parameters: OptimizationParamCapability[];
  search_methods: string[];
  selection_policies: string[];
  certified_metrics: { metric: string; producer_id?: string | null;
                       registry_id?: string; registry_version?: string }[];
  metric_registry_id: string;
  locked_parameters: { name: string; reason: string }[];
  qualified_parameters: string[];
  objective_semantic_families: Record<string, string>;
  independent_objective_families: string[];
  multi_objective_available: boolean;
  objective_note: string;
  unqualified_parameters: string[];
  effectiveness_basis: string;
  qualification_basis: string;
  multicast_note: string;
  not_measured: string[];
  not_measured_note: string;
}

export const MATURITY_LEVELS = [
  'AVAILABLE',
  'EXPERIMENTAL',
  'RESEARCH',
  'HISTORICAL',
  'BLOCKED',
  'NOT_APPLICABLE',
] as const;

export type MaturityLevel = (typeof MATURITY_LEVELS)[number];

export function isMaturityLevel(value: unknown): value is MaturityLevel {
  return (
    typeof value === 'string' &&
    (MATURITY_LEVELS as readonly string[]).includes(value)
  );
}

export interface StageLadder {
  intent: boolean;
  materialized: boolean | 'partial';
  verified: boolean | 'partial';
  projected: boolean | 'partial';
  executable: boolean | 'partial';
  qualified: boolean;
  product: boolean;
}

export interface SynthesisMethodView {
  method: 'milp' | 'sa' | 'bo' | 'rho' | 'grpo' | string;
  label: string;
  scope: string;
  optimality_claim: string;
  maturity: MaturityLevel;
}

export interface SynthesisCandidateResultView {
  candidate_id: string;
  method: string;
  solver_status: string;
  generator_objective_name: string | null;
  generator_objective_value: number | null;
  compile_status: string | null;
  verification_status: string | null;
  measured_cycles: number | null;
  measured_backend: string | null;
  evidence_id: string | null;
  requirements_state: string | null;
}

export interface SynthesisResultView {
  contract_version: 1;
  synthesis_id: string;
  method: string;
  base_topology: string | null;
  generated_count: number;
  evaluated_count: number;
  completeness: CompletenessView | null;
  candidates: SynthesisCandidateResultView[];
}

export interface CandidateLibraryEntry {
  candidate_id: string;
  origin: string;
  method: string | null;
  design_delta: string | null;
  network_cycles: number | null;
  system_cycles: number | null;
  memory_cycles: number | null;
  verification: string | null;
  status: string | null;
  pareto_member: boolean | null;
  adopted: boolean;
}

export interface CandidateLibraryView {
  contract_version: 1;
  entries: CandidateLibraryEntry[];
}

export interface CandidateDetailView {
  contract_version: 1;
  candidate: CandidateLibraryEntry;
  topology_hash: string | null;
  compile: string | null;
  verification: string | null;
  evidence_ids: string[];
  generator_provenance: Record<string, unknown> | null;
  promotion: {
    promoted: boolean;
    message: string | null;
  };
}

export interface CapabilityExplorerRow {
  capability_id: string;
  title: string;
  ladder: StageLadder;
  maturity: MaturityLevel;
  evidence: string | null;
}

export interface CapabilityExplorerView {
  contract_version: 1;
  rows: CapabilityExplorerRow[];
}

export interface CapabilityDetailView {
  contract_version: 1;
  capability_id: string;
  title: string;
  ladder: StageLadder;
  maturity: MaturityLevel;
  description: string | null;
  implementation: string[];
  historical_evidence: string[];
  missing_bridge: string | null;
}

export interface PerformanceMetricsView {
  contract_version: 1;
  makespan_s: number | null;
  critical_path_s: number | null;
  critical_path_note: string | null;
  request_latency: {
    mean_s: number | null;
    median_s: number | null;
    p95_s: number | null;
    max_s: number | null;
    sample_count: number | null;
  } | null;
  utilization: Record<string, number> | null;
  sensitivity: Record<string, unknown> | null;
  epistemic: 'MODELLED';
  predictive_validation: 'NOT_ESTABLISHED';
}

export interface HardwareProfileView {
  profile_id: string;
  display_name: string;
  hardware_id: string;
  device_kind: string;
  vendor_model: string;
  memory_capacity_bytes: number | null;
  memory_bandwidth_bytes_per_s: number | null;
  host_memory_bytes: number | null;
  host_bandwidth_bytes_per_s: number | null;
  link_bandwidth_bytes_per_s: number | null;
  link_latency_ns: number | null;
  provenance: string[];
  timing_source: {
    profiler_dir: string;
    model: string;
    variant: string;
    tp_degrees: number[];
    gpu: string;
    vllm_version: string | null;
    cuda_version: string | null;
    profiled_at: string | null;
    consumed_by: string;
    status: string;
  } | null;
  dispositions: [string, string][];
  consumers: string[];
}

export interface HardwareProfileCatalogView {
  contract_version: 1;
  note: string;
  profiles: HardwareProfileView[];
}

export interface EnergyAuthorityEntry {
  id: string;
  fidelity: string;
  units: string | null;
  inputs: string[];
  source: string;
  scope: string;
}

export interface EnergyAuthorityListView {
  authorities: EnergyAuthorityEntry[];
}

export interface EnergyAuthorityView {
  id: string;
  fidelity: string;
  unit: string | null;
  inputs: string[];
  source: string;
  scope: string;
  calibration: string | null;
}

export interface EnergyAuthoritiesView {
  contract_version: 1;
  authorities: EnergyAuthorityView[];
  mecs_native_power: {
    available: false;
    reason: string;
  };
}

export interface ImplementationStatusView {
  contract_version: 1;
  rtl: {
    build: string | null;
    simulation: string | null;
    oracle: string | null;
    design_identity: string | null;
    epistemic: 'RTL_SIMULATION';
  };
  uvm_sva: {
    generated: boolean;
    executed: boolean;
    passed: boolean | null;
    assertions: number | null;
    testbench: string | null;
  };
  cdc: {
    component: string | null;
    component_tests: string | null;
    system_qualification: 'NOT_ESTABLISHED';
  };
}

export interface ReuseInfoView {
  reused: boolean;
  reused_evidence_id: string | null;
  matched_design: boolean | null;
  matched_workload: boolean | null;
  matched_backend_config: boolean | null;
  matched_producer: boolean | null;
  matched_semantics: boolean | null;
}

export type CompletenessKind = 'EXHAUSTIVE' | 'BUDGETED' | 'UNBOUNDED';

export interface CompletenessView {
  kind: CompletenessKind;
  evaluated: number;
  declared: number | null;
  wording: string;
  may_claim_optimality: boolean;
}

export function completenessWording(
  kind: CompletenessKind,
  evaluated: number,
  declared: number | null,
): string {
  if (kind === 'EXHAUSTIVE') {
    return `Evaluated all ${evaluated} declared candidates.`;
  }
  if (kind === 'BUDGETED' && declared != null) {
    return `${evaluated} of ${declared} declared candidates evaluated — best observed among evaluated candidates.`;
  }
  return `${evaluated} generated graphs explored — heuristic search, no claim of global optimality.`;
}

export function tieVerdict(values: (number | null)[]): 'NO_DISTINCTION' | null {
  const measured = values.filter((v): v is number => v != null);
  if (measured.length < 2) return null;
  return measured.every((v) => v === measured[0]) ? 'NO_DISTINCTION' : null;
}

export function recommendationLabel(): string {
  return 'Recommended for further investigation (not a winner)';
}

export function formatEngineeringTime(
  seconds: number | null | undefined,
): { text: string; unit: string } {
  if (seconds == null || !Number.isFinite(seconds)) {
    return { text: '—', unit: 's' };
  }
  const abs = Math.abs(seconds);
  const table: [number, string][] = [
    [1, 's'],
    [1e-3, 'ms'],
    [1e-6, 'µs'],
    [1e-9, 'ns'],
  ];
  for (const [scale, unit] of table) {
    const v = seconds / scale;
    if (abs / scale >= 1 || unit === 'ns') {
      const rounded = Math.round(v * 100) / 100;
      const text = rounded === 0 && seconds !== 0
        ? v.toPrecision(2)
        : String(rounded);
      return { text, unit };
    }
  }
  return { text: String(seconds), unit: 's' };
}

/** ── Loom capability registry (Slice 1) ───────────────────────────────
 *
 * The ONE place a Loom client learns what the system can do. Served from
 * GET /loom/capabilities. The topology rows are PROBED server-side by
 * running the compiler, so a client must never infer capability from a
 * topology or model name.
 *
 * The client renders these strings and nothing else. It does not declare
 * them: a second authority in the client is how a UI starts offering
 * capabilities the compiler does not have.
 */

export type CapabilityStatus =
  | 'READY' | 'PARTIAL' | 'BLOCKED' | 'UNSUPPORTED' | 'NOT_IMPLEMENTED';

export interface CapabilityRow {
  id: string;
  status: CapabilityStatus;
  reason: string;
  required_inputs: string[];
  backend: string | null;
  qualification: string | null;
  evidence_refs: string[];
  /** Pipeline stage a family stopped at, in product vocabulary. */
  blocked_at: string | null;
}

export interface TopologyFamilyTruth {
  family: string;
  status: CapabilityStatus;
  stopped_at: string | null;
  qualification: string | null;
  reason: string;
}

export interface LoomCapabilityView {
  schema_version: 1;
  type: string;
  statuses: CapabilityStatus[];
  note: string;
  readiness_note: string;
  capabilities: CapabilityRow[];
  by_status: Partial<Record<CapabilityStatus, string[]>>;
  topology: {
    probed: boolean;
    stage_order?: string[];
    stage_meaning?: Record<string, string>;
    families?: TopologyFamilyTruth[];
  };
}

/** The provenance vocabulary. Origins are exactly four; freshness is
 *  independent of origin. */
export interface ValueProvenanceView {
  schema_version: 1;
  type: string;
  origins: string[];
  freshness: string[];
  artifact_kinds: string[];
  origin_meaning: Record<string, string>;
  freshness_meaning: Record<string, string>;
  origin_artifacts: Record<string, string[]>;
  rule: string;
}

/** Server-computed freshness for one run against the design on screen. */
export interface RunFreshness {
  state: 'CURRENT' | 'STALE' | 'FOREIGN_REVISION';
  meaning: string;
  run_revision_id: string | null;
  active_revision_id: string | null;
  draft_dirty: boolean;
  draft_design_hash: string | null;
  run_design_hash: string | null;
}
