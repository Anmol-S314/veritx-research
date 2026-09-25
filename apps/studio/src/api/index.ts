// Product API v1 endpoints. One module per resource family keeps components
// from scattering URLs.
import { del, get, patch, post, put } from './client';
import type {
  ArtifactChainView,
  CompareView,
  DraftView,
  EvidenceView,
  FabricPresetCatalogView,
  JobView,
  OptimizationView,
  ProjectView,
  QualificationView,
  ValidationCampaignsView,
  PreflightView,
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
  compile: (projectId: string) =>
    post<RevisionView>(`/projects/${encodeURIComponent(projectId)}/compile`),

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
  servingSubmit: (
    projectId: string,
    body?: { num_reqs?: number; workload_id?: string },
  ) =>
    post<JobView>(`/projects/${encodeURIComponent(projectId)}/serving`,
      body ?? {}),
  serving: (servingId: string) =>
    get<ServingView>(`/serving/${encodeURIComponent(servingId)}`),
};

export * from './types';
export { ApiError } from './client';
