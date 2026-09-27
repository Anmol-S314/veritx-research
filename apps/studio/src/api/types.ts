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
  /** Whether the active revision's intent can actually be simulated.
   * `domain` names the first gate that refuses: "compile",
   * "intent_lowering", or "backend_profile". */
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
  result: { run_id?: string; optimization_id?: string } | null;
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
  /** False when the workload certifies but cannot be simulated
   * (no proven intent→collective mapping); reason carries the refusal. */
  evaluation_supported: boolean;
  evaluation_note: string | null;
  evaluation_domain: 'compile' | 'intent_lowering' | 'backend_profile' | null;
}

export interface WorkloadCatalogView {
  contract_version: 1;
  workloads: WorkloadCatalogEntry[];
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

/** GET /api/v1/optimization/capabilities — derived from backend authority.
 *  Nothing here is hand-maintained in the frontend. A parameter may be
 *  `expressible` yet NOT `qualified_for_certified_optimization` (e.g.
 *  `arbitration` compiles but leaves every projection input identical, so the
 *  certified backend would execute byte-identical work). Unqualified
 *  parameters must be hidden or disabled, never silently searched. */
export interface OptimizationParamCapability {
  name: string;
  field: string;
  kind: 'int' | 'bool' | 'str' | 'enum';
  expressible: boolean;
  compilable: boolean;
  executable: boolean;
  effective: boolean;
  qualified_for_certified_optimization: boolean;
  value_constraint: string;
  /** null means "a validated range, NOT an enumerated list". Never read this
   *  as "all values supported" — check `accepted_values_is_exhaustive`. */
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
  /** Certified metric -> semantic objective family. `completion_cycles`,
   *  `completion_time` and `completion_ns` are the SAME authenticated window in
   *  different units, so they are ONE family and a study over them must render
   *  a RANKING, never a Pareto frontier. */
  objective_semantic_families: Record<string, string>;
  independent_objective_families: string[];
  multi_objective_available: boolean;
  objective_note: string;
  unqualified_parameters: string[];
  effectiveness_basis: string;
  multicast_note: string;
  not_measured: string[];
  not_measured_note: string;
}
