// Contract-mirror types for the five frozen views in contracts/srota/v1/.
// Studio consumes these views only — never engine internals.

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
  bandwidth_floor_gbps: number | null;
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
  rcu_enabled: boolean | null;
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

export interface Candidate {
  candidate_id: string;
  guided_patch: Record<string, number | string | boolean>;
  locked_consequences?: Record<string, unknown>;
  evaluation_ids: {
    design_hash: string;
    performance_result_id?: string | null;
  };
  objective_values: Record<string, number>;
  constraint_verdicts: Record<string, boolean>;
  pareto_member: boolean;
}

export interface OptimizationStudyView {
  contract_version: 1;
  base_design_hash: string;
  definition: {
    objectives: string[];
    constraints?: string[];
    method: string;
    budget?: Record<string, unknown>;
    seed?: number | string | null;
    domain?: Record<string, unknown>;
  };
  candidates: Candidate[];
  pareto_ids: string[];
  selected_candidate_id?: string | null;
  selection_rationale?: string | null;
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
