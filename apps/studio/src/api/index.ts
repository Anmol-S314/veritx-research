// Product API v1 endpoints. One module per resource family keeps components
// from scattering URLs.
import { del, get, patch, post, put } from './client';
import type {
  ArtifactChainView,
  CompareView,
  DesignViewV2,
  DraftView,
  EvidenceView,
  FabricPresetCatalogView,
  JobView,
  OptimizationView,
  ProjectView,
  QualificationView,
  ValidationCampaignsView,
  PreflightView,
  ServingConfigCatalogView,
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
  health: () => get<{ status: string; api: string }>('/health'),

  qualification: () => get<QualificationView>('/qualification'),
  capabilities: () =>
    get<Record<string, unknown>>('/capabilities'),
  validation: () => get<ValidationCampaignsView>('/validation'),
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

  evaluate: (revisionId: string, backend?: string) =>
    post<JobView>(`/revisions/${encodeURIComponent(revisionId)}/evaluate`, {
      backend: backend ?? null,
    }),
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
};

export * from './types';
export { ApiError } from './client';
