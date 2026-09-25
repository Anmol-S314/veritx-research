// Product API v1 endpoints. One module per resource family keeps components
// from scattering URLs.
import { get, post, put } from './client';
import type {
  CompareView,
  DraftView,
  EvidenceView,
  FabricPresetCatalogView,
  JobView,
  OptimizationView,
  ProjectView,
  QualificationView,
  RevisionView,
  RunSummary,
  RunView,
  WorkloadCatalogView,
} from './types';

export const api = {
  health: () => get<{ status: string; api: string }>('/health'),

  qualification: () => get<QualificationView>('/qualification'),
  workloadCatalog: () => get<WorkloadCatalogView>('/catalog/workloads'),
  fabricPresets: () =>
    get<FabricPresetCatalogView>('/catalog/fabric-presets'),

  listProjects: () =>
    get<{ contract_version: 1; projects: ProjectView[] }>('/projects'),
  createProject: (name: string, workloadId?: string) =>
    post<ProjectView>('/projects', { name, workload_id: workloadId ?? null }),
  project: (projectId: string) =>
    get<ProjectView>(`/projects/${encodeURIComponent(projectId)}`),

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

  optimization: (optimizationId: string) =>
    get<OptimizationView>(
      `/optimizations/${encodeURIComponent(optimizationId)}`,
    ),

  compare: (a: string, b: string) =>
    get<CompareView>(`/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
};

export * from './types';
export { ApiError } from './client';
