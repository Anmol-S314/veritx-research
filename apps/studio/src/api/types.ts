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
