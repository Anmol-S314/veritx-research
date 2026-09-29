// Product API v1 endpoints. One module per resource family keeps components
// from scattering URLs.
import { del, get, patch, post, put } from './client';
import type {
  ArtifactChainView,
  CandidateDetailView,
  CandidateLibraryView,
  CanonicalRoute,
  CapabilityDetailView,
  CapabilityExplorerView,
  CompareView,
  CompileResultView,
  DesignViewV2,
  DraftView,
  EnergyAuthoritiesView,
  EvaluationPlanView,
  EvidenceView,
  FederationBackendsView,
  HealthView,
  FabricPresetCatalogView,
  ImplementationStatusView,
  JobView,
  OptimizationCapabilities,
  OptimizationView,
  PerformanceMetricsView,
  ProjectView,
  QualificationView,
  SynthesisMethodView,
  SynthesisResultView,
  ValidationCampaignsView,
  PreflightView,
  RevisionDiffView,
  ServingConfigCatalogView,
  ServingExperimentCatalogView,
  ServingSummary,
  ServingView,
  WorkloadLoweringView,
  RunIntegrityView,
  RunVerifyView,
  RevisionView,
  RunSummary,
  RunView,
  WorkloadCatalogView,
} from './types';
import type { TopologyView } from '../types';

export const api = {
  health: () => get<HealthView>('/health'),

  qualification: () => get<QualificationView>('/qualification'),
  capabilities: () =>
    get<Record<string, unknown>>('/capabilities'),
  /** Per-backend federation truth: registration + install facts.
   * Readiness lives on the evaluation plan, never here. */
  federationBackends: () =>
    get<FederationBackendsView>('/federation/backends'),
  validation: () => get<ValidationCampaignsView>('/validation'),
  /** Adopt a studied candidate as the DRAFT. The immutable base revision is
   *  NOT mutated: the user must compile explicitly before a new revision
   *  exists. */
  useCandidate: (optimizationId: string, candidateId: string) =>
    post<DraftView>(
      `/optimizations/${encodeURIComponent(optimizationId)}`
      + `/candidates/${encodeURIComponent(candidateId)}/use`,
      {},
    ),
  /** What VERITX can actually optimize, from canonical backend authority. */
  optimizationCapabilities: () =>
    get<OptimizationCapabilities>('/optimization/capabilities'),
  workloadCatalog: () => get<WorkloadCatalogView>('/catalog/workloads'),
  workloadLowering: (workloadId: string) =>
    get<WorkloadLoweringView>(
      `/workloads/${encodeURIComponent(workloadId)}/lowering`,
    ),
  fabricPresets: () =>
    get<FabricPresetCatalogView>('/catalog/fabric-presets'),

  listProjects: () =>
    get<{ contract_version: 1; projects: ProjectView[] }>('/projects'),
  createProject: (name: string, workloadId?: string) =>
    post<ProjectView>('/projects', { name, workload_id: workloadId ?? null }),
  project: (projectId: string) =>
    get<ProjectView>(`/projects/${encodeURIComponent(projectId)}`),
  renameProject: (projectId: string, name: string) =>
    patch<ProjectView>(`/projects/${encodeURIComponent(projectId)}`, { name }),
  deleteProject: (projectId: string) =>
    del<{ contract_version: 1; deleted: boolean; project_id: string }>(
      `/projects/${encodeURIComponent(projectId)}`,
    ),

  draft: (projectId: string) =>
    get<DraftView>(`/projects/${encodeURIComponent(projectId)}/draft`),
  putDraft: (projectId: string, request: Record<string, unknown>) =>
    put<DraftView>(`/projects/${encodeURIComponent(projectId)}/draft`, {
      request,
    }),
  selectWorkload: (projectId: string, workloadId: string) =>
    post<DraftView>(
      `/projects/${encodeURIComponent(projectId)}/workload`,
      { workload_id: workloadId },
    ),
  /** DesignViewV2. `presentation: 'review'` is the pre-compile boundary —
   * the same projection, not a second model (Gate 7 §51.1). */
  design: (projectId: string, params?: {
    presentation?: 'edit' | 'review';
    /** Ask whether this reviewed snapshot is still current. */
    reviewSnapshotHash?: string | null;
  }) => {
    const q = new URLSearchParams();
    if (params?.presentation) q.set('presentation', params.presentation);
    if (params?.reviewSnapshotHash) {
      q.set('review_snapshot_hash', params.reviewSnapshotHash);
    }
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return get<DesignViewV2>(
      `/projects/${encodeURIComponent(projectId)}/design${suffix}`,
    );
  },
  /** Compile the draft. `expectedDraftDesignHash` is the reviewed snapshot;
   * a mismatch is refused as STALE_REVIEW (Gate 7 §4, REV-D2). */
  compile: (projectId: string, expectedDraftDesignHash?: string | null) =>
    post<RevisionView>(
      `/projects/${encodeURIComponent(projectId)}/compile`,
      expectedDraftDesignHash
        ? { expected_draft_design_hash: expectedDraftDesignHash }
        : {},
    ),

  revision: (revisionId: string) =>
    get<RevisionView>(`/revisions/${encodeURIComponent(revisionId)}`),

  topology: (revisionId: string) =>
    get<TopologyView>(`/revisions/${encodeURIComponent(revisionId)}/topology`),

  artifactChain: (revisionId: string) =>
    get<ArtifactChainView>(
      `/revisions/${encodeURIComponent(revisionId)}/artifacts`,
    ),

  /** CompileResultView — the seven inspector groups (Gate 8 §50), frozen
   * at certification time. Read-only: an inspector never edits. */
  compileResult: (revisionId: string) =>
    get<CompileResultView>(
      `/revisions/${encodeURIComponent(revisionId)}/compile-result`,
    ),

  /** The canonical DERIVED EXPECTED route for one (class, src, dst).
   * Gate 8 §58: this is the expected state; a runtime observation is a
   * separate fact with its own scope. */
  route: (revisionId: string, params?: {
    routingClass?: string | null; src?: number | null; dst?: number | null;
  }) => {
    const q = new URLSearchParams();
    if (params?.routingClass) q.set('routing_class', params.routingClass);
    if (params?.src != null) q.set('src', String(params.src));
    if (params?.dst != null) q.set('dst', String(params.dst));
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return get<CanonicalRoute>(
      `/revisions/${encodeURIComponent(revisionId)}/route${suffix}`,
    );
  },

  evaluate: (
    revisionId: string,
    opts?: { backend?: string | null; questions?: string[] | null } | string | null,
  ) => {
    // Compat: a bare string is the historical backend-only argument.
    const body = typeof opts === 'string'
      ? { backend: opts }
      : {
        backend: opts?.backend ?? null,
        questions: opts?.questions ?? null,
      };
    return post<JobView>(
      `/revisions/${encodeURIComponent(revisionId)}/evaluate`, body);
  },
  /** EvaluationPlanView — what this revision can run, per question.
   * Pure adjudication: the server plans, Studio renders. `backend` pins
   * one explicit backend and triggers a fresh server plan — never an
   * assumed local equivalence. */
  evaluationPlan: (
    revisionId: string,
    opts?: { questions?: string[] | null; backend?: string | null },
  ) => {
    const q = new URLSearchParams();
    if (opts?.questions && opts.questions.length > 0) {
      q.set('questions', opts.questions.join(','));
    }
    if (opts?.backend) q.set('backend', opts.backend);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return get<EvaluationPlanView>(
      `/revisions/${encodeURIComponent(revisionId)}/evaluation-plan${suffix}`,
    );
  },
  optimize: (revisionId: string, body: Record<string, unknown>) =>
    post<JobView>(`/revisions/${encodeURIComponent(revisionId)}/optimize`, body),

  job: (jobId: string) =>
    get<JobView>(`/jobs/${encodeURIComponent(jobId)}`),

  runs: (params?: { projectId?: string; revisionId?: string }) => {
    const q = new URLSearchParams();
    if (params?.projectId) q.set('project_id', params.projectId);
    if (params?.revisionId) q.set('revision_id', params.revisionId);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return get<{ contract_version: 1; runs: RunSummary[] }>(`/runs${suffix}`);
  },
  run: (runId: string) =>
    get<RunView>(`/runs/${encodeURIComponent(runId)}`),
  evidence: (runId: string) =>
    get<EvidenceView>(`/runs/${encodeURIComponent(runId)}/evidence`),
  integrity: (runId: string) =>
    get<RunIntegrityView>(`/runs/${encodeURIComponent(runId)}/integrity`),
  preflight: (revisionId: string) =>
    get<PreflightView>(`/revisions/${encodeURIComponent(revisionId)}/preflight`),

  /** RevisionDiffView — DESIGN / DERIVED / CAPABILITY changes against the
   * predecessor (or an explicit `against` revision of the same project).
   * The backend compares frozen payloads; React infers nothing. */
  revisionDiff: (revisionId: string, against?: string) => {
    const q = against ? `?against=${encodeURIComponent(against)}` : '';
    return get<RevisionDiffView>(
      `/revisions/${encodeURIComponent(revisionId)}/diff${q}`);
  },
  verifyRun: (runId: string) =>
    post<RunVerifyView>(`/runs/${encodeURIComponent(runId)}/verify`),
  reproduceRun: (runId: string) =>
    post<JobView>(`/runs/${encodeURIComponent(runId)}/reproduce`),

  optimization: (optimizationId: string) =>
    get<OptimizationView>(
      `/optimizations/${encodeURIComponent(optimizationId)}`,
    ),

  compare: (a: string, b: string) =>
    get<CompareView>(`/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),

  servingList: (projectId: string) =>
    get<{ contract_version: 1; experiments: ServingSummary[] }>(
      `/projects/${encodeURIComponent(projectId)}/serving`,
    ),
  servingConfigs: () =>
    get<ServingConfigCatalogView>('/catalog/serving-configs'),
  servingExperiments: () =>
    get<ServingExperimentCatalogView>('/catalog/serving-experiments'),
  servingSubmit: (
    projectId: string,
    body?: {
      num_reqs?: number;
      workload_id?: string;
      /** Repo-relative or absolute path to a cluster config. */
      cluster_config?: string;
      /** Repo-relative or absolute path to a JSONL request trace. */
      dataset?: string;
      /** Wall-clock budget for the canonical run, seconds (1..3600). */
      timeout_s?: number;
      /** Declared service-profile overrides; keys validated server-side. */
      profile_overrides?: Record<string, number | string>;
    },
  ) =>
    post<JobView>(`/projects/${encodeURIComponent(projectId)}/serving`,
      body ?? {}),
  serving: (servingId: string) =>
    get<ServingView>(`/serving/${encodeURIComponent(servingId)}`),

  // ── Studio vNext surfaces (product API v1) ─────────────────────────
  // Where the backend has not wired a route yet the gateway answers 404
  // (or 503 when the producer is absent). Callers MUST surface the
  // capability maturity state — RESEARCH / HISTORICAL / BLOCKED — and
  // MUST NOT substitute an offline fixture for a live project (§45).
  synthesisMethods: () =>
    get<{ contract_version: 1; methods: SynthesisMethodView[] }>(
      '/synthesis/methods',
    ),
  synthesisSubmit: (body: Record<string, unknown>) =>
    post<JobView>('/synthesis', body),
  synthesis: (synthesisId: string) =>
    get<SynthesisResultView>(
      `/synthesis/${encodeURIComponent(synthesisId)}`,
    ),
  synthesisPromote: (synthesisId: string, candidateId: string) =>
    post<DraftView>(
      `/synthesis/${encodeURIComponent(synthesisId)}`
      + `/candidates/${encodeURIComponent(candidateId)}/promote`,
      {},
    ),
  candidates: (params?: { study?: string; method?: string }) => {
    const q = new URLSearchParams();
    if (params?.study) q.set('study', params.study);
    if (params?.method) q.set('method', params.method);
    const suffix = q.toString() ? `?${q.toString()}` : '';
    return get<CandidateLibraryView>(`/candidates${suffix}`);
  },
  candidate: (candidateId: string) =>
    get<CandidateDetailView>(
      `/candidates/${encodeURIComponent(candidateId)}`,
    ),
  capabilitiesExplorer: () =>
    get<CapabilityExplorerView>('/capabilities/explorer'),
  capabilityDetail: (capabilityId: string) =>
    get<CapabilityDetailView>(
      `/capabilities/${encodeURIComponent(capabilityId)}`,
    ),
  performance: (revisionId: string) =>
    get<PerformanceMetricsView>(
      `/revisions/${encodeURIComponent(revisionId)}/performance`,
    ),
  energyAuthorities: () =>
    get<EnergyAuthoritiesView>('/implementation/energy'),
  implementationStatus: () =>
    get<ImplementationStatusView>('/implementation/status'),
};

export * from './types';
export { ApiError } from './client';
