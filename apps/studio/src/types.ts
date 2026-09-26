// Contract-mirror types for the frozen product views. The
// OptimizationStudyView is contract v2 (contracts/srota/v2/); the other
// four views are v1 (contracts/srota/v1/). Studio consumes these views
// only — never engine internals.

export interface Parallelism {
  tp: number;
  pp: number;
  ep: number;
  dp: number;
}

export interface WorkloadSourceRef {
  content_digest: string;
  format: string;
  size_bytes?: number;
}

export interface Workload {
  model_family: string;
  model_name?: string;
  parallelism: Parallelism;
  serving_mode?: string;
  workload_source_ref?: WorkloadSourceRef;
}

export interface Requirement {
  traffic_class: string | null;
  qos_class: string;
  latency_ceiling_cycles: number | null;
  /** REMOVED_V4 (exposure-registry: RequirementV3.bandwidth_floor_gbps).
   * Retained in the frozen DesignView v1 contract for compatibility; no
   * Studio control writes it and no Studio surface renders it. */
  bandwidth_floor_gbps?: number | null;
  binding: boolean;
}

export interface AgentSpec {
  kind: string;
  count: number;
}

export interface NocGuided {
  topology_family: string | null;
  radix: number | null;
  concentration: number | null;
  link_width: number | null;
  /** REMOVED_V4 (exposure-registry: NocConfig.rcu_enabled). Present in the
   * frozen DesignView v1 contract; never authored or rendered by Studio. */
  rcu_enabled?: boolean | null;
  arbitration: string | null;
}

export interface LockedDerived {
  routing: string;
  vc_count: number;
  turn_restrictions: string[];
  certificate_overall: 'PASS' | 'FAIL';
}

export interface DesignView {
  contract_version: 1;
  design_hash: string;
  schema_version: number;
  compiler_semantics_version: number;
  workload: Workload;
  requirements: Requirement[];
  agents: AgentSpec[];
  noc_guided: NocGuided;
  locked_derived?: LockedDerived | null;
}

// ── TopologyView (contracts/srota/v1) ──────────────────────────────────────
// The materialized fabric graph a revision was certified against:
// routers with seats, directed channels, agent endpoints. The
// topology_family string in DesignView is intent metadata; this view is
// the artifact the certificate proved and the only graph we draw.

export interface TopologyRouter {
  router_id: number;
  coordinates: number[];
  seat_capacity: number;
}

export interface TopologyChannel {
  channel_id: number;
  src_router: number;
  src_port: number;
  dst_router: number;
  dst_port: number;
  width_bits: number;
  latency_cycles: number;
  route_weight?: number;
  physical_link_id?: number | null;
}

export interface TopologyPhysicalLink {
  physical_link_id: number;
  channel_ids: number[];
  length_mm?: number | null;
}

export interface TopologyEndpoint {
  endpoint_id: number;
  kind: string;
  group_index: number;
  instance_index: number;
  router_id: number;
  port_id: number;
}

export interface TopologyView {
  contract_version: 1;
  revision_id: string | null;
  design_hash: string;
  topology_hash: string;
  attachment_hash: string;
  family: 'mesh' | 'torus' | 'ring' | 'concentrated_mesh';
  routers: TopologyRouter[];
  channels: TopologyChannel[];
  physical_links: TopologyPhysicalLink[];
  endpoints: TopologyEndpoint[];
  counts: { routers: number; channels: number; seats: number; endpoints: number };
}

export type ObligationStatus = 'PASS' | 'FAIL';

export interface Obligation {
  obligation: string;
  status: ObligationStatus;
  method: string;
  evidence: Record<string, unknown>;
}

export type CompilationStatus = 'COMPILED' | 'INVALID' | 'UNSUPPORTED';

export interface CompilationView {
  contract_version: 1;
  status: CompilationStatus;
  design_hash: string;
  compiler_semantics_version: number;
  resolved_fabric_hash?: string;
  certificate_id?: string;
  certificate_overall?: 'PASS' | 'FAIL';
  obligations?: Obligation[];
  artifact_hashes?: Record<string, string>;
  error?: string | null;
}

export interface BackendProducer {
  backend: string;
  producer_identity: string;
  config_hash: string;
  input_hash: string;
}

export type EvaluationStatus =
  | 'EVALUATED'
  | 'BACKEND_UNAVAILABLE'
  | 'UNSUPPORTED'
  | 'FAILED';

export interface NetworkTrafficWindow {
  window_cycles: number;
  wall_time_ns: number | null;
  cycles_only: boolean;
}

export interface EvaluationView {
  contract_version: 1;
  status: EvaluationStatus;
  design_hash: string;
  resolved_fabric_hash: string;
  workload_id: string;
  message_artifact_id?: string;
  physical_traffic_id?: string;
  backend_producer?: BackendProducer | null;
  evidence?: { raw_evidence_digest: string; stats_digest: string } | null;
  performance_result_id?: string | null;
  network_traffic_window?: NetworkTrafficWindow | null;
  metrics?: Record<string, number> | null;
  fidelity_warning?: string | null;
  reason?: string | null;
}

export type RequirementVerdict =
  | 'SATISFIED'
  | 'VIOLATED'
  | 'UNMEASURABLE'
  | 'NOT_APPLICABLE';

export interface RequirementEntry {
  requirement_index: number;
  traffic_class: string | null;
  qos_class: string | null;
  verdict: RequirementVerdict;
  binding?: boolean;
  required?: number | string | null;
  measured?: number | string | null;
  metric_authority: string;
  performance_result_id: string;
  reason: string;
}

export interface RequirementReport {
  contract_version: 1;
  design_hash: string;
  performance_result_id: string;
  entries: RequirementEntry[];
}

// ── OptimizationStudyView v2 (contracts/srota/v2) ──────────────────────────
// Three independent authorities are never merged by the engine:
//   product requirements   -> product_requirements (satisfied | null)
//   optimization constraints -> constraint_verdicts (SATISFIED|VIOLATED|UNMEASURABLE)
//   measured objectives    -> objective_values + objective_availability
// Studio renders these fields as-is; it never infers a state from an
// absent value.

export type ConstraintVerdict = 'SATISFIED' | 'VIOLATED' | 'UNMEASURABLE';
export type ObjectiveAvailability = 'MEASURED' | 'UNMEASURABLE';
export type CandidateCompilationStatus = 'COMPILED' | 'INVALID' | 'UNSUPPORTED';
export type CandidateEvaluationStatus =
  | 'EVALUATED'
  | 'COMPILE_FAILED'
  | 'INVALID'
  | 'UNSUPPORTED'
  | 'BACKEND_UNAVAILABLE'
  | 'FAILED';
export type EvaluationAuthority = 'certified-backend' | 'analytic-fake' | null;

export interface StudyObjective {
  metric: string;
  direction: 'MIN' | 'MAX';
}

export interface StudyConstraint {
  metric: string;
  op: '<=' | '>=';
  threshold: number;
}

export interface CandidateProductRequirements {
  satisfied: boolean | null;
  verdicts: RequirementEntry[];
}

export interface CandidateEvaluationIds {
  design_hash: string;
  performance_result_id: string | null;
  requirement_report_id: string | null;
}

export interface Candidate {
  candidate_id: string;
  guided_patch: Record<string, number | string | boolean>;
  locked_consequences?: Record<string, unknown>;
  evaluation_ids: CandidateEvaluationIds;
  product_requirements: CandidateProductRequirements;
  objective_values: Record<string, number>;
  objective_availability: Record<string, ObjectiveAvailability>;
  constraint_verdicts: Record<string, ConstraintVerdict>;
  evaluation_authority: EvaluationAuthority;
  compilation_status: CandidateCompilationStatus;
  evaluation_status: CandidateEvaluationStatus;
  evaluation_reason: string | null;
  eligibility_reason: string | null;
  pareto_eligible: boolean;
  pareto_member: boolean;
}

export interface StudyDefinition {
  definition_id: string;
  objectives: StudyObjective[];
  constraints: StudyConstraint[];
  method: 'grid' | 'enumeration' | 'random';
  selection: 'min_first_objective' | 'lexicographic' | 'none';
  budget: Record<string, unknown>;
  seed?: number | string | null;
  domain?: Record<string, unknown>;
}

export interface OptimizationStudyView {
  contract_version: 2;
  result_class: 'CERTIFIED_PRODUCT' | 'ANALYTIC_RESEARCH';
  metric_registry_id: string | null;
  metric_registry_version: string | null;
  optimization_result_id: string;
  base_design_hash: string;
  definition: StudyDefinition;
  candidates: Candidate[];
  pareto_ids: string[];
  selected_candidate_id?: string | null;
  selection_rationale?: string | null;
}

// Presentation policy keyed ONLY by the engine's explicit contract values
// (src/presentation.json is the single source; a test proves every state
// maps to a distinct rendering and that none is inferred).
export interface PresentationEntry {
  class: string;
  label: string;
}

export type PresentationMap = Record<string, PresentationEntry>;

export interface CandidatePresentation {
  constraintVerdict: PresentationMap;
  objectiveState: PresentationMap;
  compilationStatus: PresentationMap;
  evaluationStatus: PresentationMap;
  productRequirements: PresentationMap;
  eligibility: PresentationMap;
  pareto: PresentationMap;
}

export interface FixtureBundle {
  fixture_id: string;
  title: string;
  description: string;
  design: DesignView | null;
  compilation: CompilationView | null;
  evaluation: EvaluationView | null;
  requirements: RequirementReport | null;
  optimization: OptimizationStudyView | null;
}
