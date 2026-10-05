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
  EnergyAuthorityListView,
  HardwareProfileCatalogView,
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
  TrafficMatrixView,
  WorkloadCatalogView,
} from './types';
import type { TopologyView } from '../types';

export const api = {
  health: () => get<HealthView>('/health'),

  qualification: () => get<QualificationView>('/qualification'),
  capabilities: () =>
    get<Record<string, unknown>>('/capabilities'),
  federationBackends: () =>
    get<FederationBackendsView>('/federation/backends'),
  validation: () => get<ValidationCampaignsView>('/validation'),
  useCandidate: (optimizationId: string, candidateId: string) =>
    post<DraftView>(
      `/optimizations/${encodeURIComponent(optimizationId)}`
      + `/candidates/${encodeURIComponent(candidateId)}/use`,
      {},
    ),
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
  design: (projectId: string, params?: {
    presentation?: 'edit' | 'review';
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

  compileResult: (revisionId: string) =>
    get<CompileResultView>(
      `/revisions/${encodeURIComponent(revisionId)}/compile-result`,
    ),

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
    const body = typeof opts === 'string'
      ? { backend: opts }
      : {
        backend: opts?.backend ?? null,
        questions: opts?.questions ?? null,
      };
    return post<JobView>(
      `/revisions/${encodeURIComponent(revisionId)}/evaluate`, body);
  },
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
  trafficMatrix: (runId: string) =>
    get<TrafficMatrixView>(`/runs/${encodeURIComponent(runId)}/traffic-matrix`),
  evidence: (runId: string) =>
    get<EvidenceView>(`/runs/${encodeURIComponent(runId)}/evidence`),
  integrity: (runId: string) =>
    get<RunIntegrityView>(`/runs/${encodeURIComponent(runId)}/integrity`),
  preflight: (revisionId: string) =>
    get<PreflightView>(`/revisions/${encodeURIComponent(revisionId)}/preflight`),

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
      cluster_config?: string;
      dataset?: string;
      timeout_s?: number;
      profile_overrides?: Record<string, number | string>;
    },
  ) =>
    post<JobView>(`/projects/${encodeURIComponent(projectId)}/serving`,
      body ?? {}),
  serving: (servingId: string) =>
    get<ServingView>(`/serving/${encodeURIComponent(servingId)}`),

  synthesisEngines: () =>
    get<{
      engines: {
        engine: string;
        label: string;
        scope: string;
        completeness: string;
        optimality: string;
      }[];
      canonical_vocabulary: string[];
    }>(
      '/synthesis/engines',
    ),
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
  energyAuthoritiesVnext: () =>
    get<EnergyAuthorityListView>('/energy/authorities'),
  hardwareProfiles: () =>
    get<HardwareProfileCatalogView>('/catalog/hardware-profiles'),
  servingBinding: (projectId: string) =>
    get<{ contract_version: 1; project_id: string; binding: unknown | null }>(
      `/projects/${encodeURIComponent(projectId)}/serving-binding`),
  bindServing: (projectId: string, body: {
    cluster_config?: string; dataset?: string; num_reqs?: number;
    timeout_s?: number; profile_overrides?: Record<string, unknown>;
  }) =>
    post<{ contract_version: 1; project_id: string; binding: unknown }>(
      `/projects/${encodeURIComponent(projectId)}/serving-binding`, body),
  clearServingBinding: (projectId: string) =>
    del<{ contract_version: 1; project_id: string; binding: null }>(
      `/projects/${encodeURIComponent(projectId)}/serving-binding`),
  implementationStatus: () =>
    get<ImplementationStatusView>('/implementation/status'),
};

export * from './types';
export { ApiError } from './client';
