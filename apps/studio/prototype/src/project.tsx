import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { gateway, gatewayReason, type GatewayHealth, type Job, type ProjectDetail, type ProjectEntry, type RunArtifacts, type RunDetail, type RunIntegrity, type Topology, type TrafficMatrix } from './gateway';

// Gateway documents stay separate from editable fixture state. Only selection IDs are
// retained in sessionStorage; pending responses never overwrite a newer selection.
export type DeclaredAgent = { kind: string; count: number; data_width?: number; addr_width?: number; protocol?: string; clock_domain?: string | null; power_domain?: string | null };
export type DeclaredCollective = { kind?: string; dimension?: string; payload_bytes?: number; traffic_class?: string; source_rank?: number | null };
export type DeclaredStage = { stage_id: string; owner: number; duration_ns: number; input_bytes?: number; output_bytes?: number; weight_bytes?: number; input_loc?: string; output_loc?: string; weight_loc?: string };
export type DeclaredRequirement = { traffic_class?: string; qos_class?: string; binding?: boolean; latency_ceiling_cycles?: number | null; bandwidth_floor_gbps?: number | null };
export type DraftRequest = {
  schema_version?: number;
  compiler_semantics_version?: number;
  topology?: { kind?: string; side_length?: number; concentration?: number; grid_side_length?: number } | null;
  agents?: DeclaredAgent[];
  physical?: { clock_freq_mhz?: number; data_width?: number; num_power_domains?: number; process_node_nm?: number; [key: string]: unknown } | null;
  noc_config?: { topology_family?: string | null; concentration?: number | null; link_width?: number | null; radix?: number | null } | null;
  noc_controls?: { link_width?: number | null; arbitration?: string | null; output_formats?: string[]; rcu_enabled?: boolean | null; obfuscation_level?: number | null } | null;
  address_map?: { ranges?: { name?: string; base?: string | number; size_bytes?: number; target?: string }[] } | null;
  requirements?: DeclaredRequirement[];
  workload?: { model_name?: string; model_family?: string; serving_mode?: string; tp?: number; dp?: number; ep?: number; pp?: number; workload_source_ref?: string | null; collectives?: DeclaredCollective[] } | null;
  compute?: { source?: string; stages?: DeclaredStage[] } | null;
  dependencies?: unknown[];
};

export type DraftMeta = { dirty?: boolean; design_hash?: string; workload_id?: string | null; updated_at?: string };

export type LoadedProject = {
  detail: ProjectDetail;
  request: DraftRequest | null;
  draftMeta: DraftMeta | null;
  topology: Topology | null;
  topologyError: string;
};

type ProjectState =
  | { phase: 'idle' }
  | { phase: 'loading'; projectId: string }
  | { phase: 'loaded'; data: LoadedProject }
  | { phase: 'error'; projectId: string; reason: string };

export type LoadedRun = {
  detail: RunDetail;
  matrix: TrafficMatrix | null;
  integrity: RunIntegrity | null;
  artifacts: RunArtifacts | null;
  gaps: string[];
};

export type EvaluationJobState = { job: Job | null; error: string | null };

export type RunState =
  | { phase: 'idle' }
  | { phase: 'loading'; runId: string }
  | { phase: 'loaded'; data: LoadedRun }
  | { phase: 'error'; runId: string; reason: string };

type Context = {
  health: GatewayHealth | null;
  projects: ProjectEntry[];
  listError: string;
  listPhase: 'idle' | 'checking' | 'ready' | 'offline';
  project: ProjectState;
  run: RunState;
  refreshList: () => void;
  load: (projectId: string) => void;
  loadRun: (runId: string) => void;
  reload: () => void;
  evaluationJob: EvaluationJobState;
  trackEvaluation: (jobId: string) => void;
  cancelEvaluation: () => void;
  clearEvaluation: () => void;
  clear: () => void;
};

const ProjectContext = createContext<Context | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<GatewayHealth | null>(null);
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [listError, setListError] = useState('');
  const [listPhase, setListPhase] = useState<Context['listPhase']>('idle');
  const [project, setProject] = useState<ProjectState>({ phase: 'idle' });
  const [run, setRun] = useState<RunState>({ phase: 'idle' });
  const [evaluationJob, setEvaluationJob] = useState<EvaluationJobState>({ job: null, error: null });
  const pollRef = useRef<number | null>(null);
  const projectEpoch = useRef(0), runEpoch = useRef(0), jobEpoch = useRef(0);
  const activeProject = useRef<string | null>(null);
  const preferredRun = useRef<string | null>(null);
  const [tick, setTick] = useState(0);
  const remember = (projectId: string | null, runId: string | null = null) => {
    try { if (projectId) sessionStorage.setItem('srota-gateway-selection:v1', JSON.stringify({ projectId, runId })); else sessionStorage.removeItem('srota-gateway-selection:v1'); } catch { /* Session recovery is optional. */ }
  };

  useEffect(() => {
    let live = true;
    setListPhase('checking'); setListError('');
    (async () => {
      try {
        const [h, list] = await Promise.all([gateway.health(), gateway.projects()]);
        if (!live) return;
        setHealth(h); setProjects(list); setListPhase('ready');
      } catch (error) {
        if (!live) return;
        setListPhase('offline'); setListError(gatewayReason(error));
      }
    })();
    return () => { live = false; };
  }, [tick]);

  const loadRun = useCallback((runId: string) => {
    const ticket = ++runEpoch.current, projectTicket = projectEpoch.current;
    const current = () => ticket === runEpoch.current && projectTicket === projectEpoch.current;
    setRun({ phase: 'loading', runId });
    (async () => {
      const gaps: string[] = [];
      const settle = async <T,>(label: string, call: Promise<T>): Promise<T | null> => {
        try { return await call; } catch (error) { gaps.push(`${label}: ${gatewayReason(error)}`); return null; }
      };
      const detail = await settle('run detail', gateway.run(runId));
      if (!current()) return;
      if (!detail) { setRun({ phase: 'error', runId, reason: gaps[0] ?? 'Run detail unavailable.' }); return; }
      if (detail.project_id !== activeProject.current) { setRun({ phase: 'error', runId, reason: 'Run belongs to another project.' }); return; }
      const [matrix, integrity, artifacts] = await Promise.all([
        settle('traffic matrix', gateway.runMatrix(runId)),
        settle('integrity', gateway.runIntegrity(runId)),
        settle('artifacts', gateway.runArtifacts(runId)),
      ]);
      if (!current()) return;
      remember(activeProject.current, runId);
      setRun({ phase: 'loaded', data: { detail, matrix, integrity, artifacts, gaps } });
    })();
  }, []);

  const stopPolling = useCallback(() => {
    ++jobEpoch.current;
    if (pollRef.current !== null) { window.clearTimeout(pollRef.current); pollRef.current = null; }
  }, []);

  const trackEvaluation = useCallback((jobId: string) => {
    stopPolling();
    const ticket = jobEpoch.current, projectId = activeProject.current;
    const current = () => ticket === jobEpoch.current && activeProject.current === projectId;
    setEvaluationJob({ job: null, error: null });
    const tick = async () => {
      try {
        const job = await gateway.job(jobId);
        if (!current()) return;
        if (job.project_id !== projectId) throw new Error('Job belongs to another project.');
        setEvaluationJob({ job, error: null });
        if (['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state)) {
          stopPolling();
          if (job.state === 'COMPLETED' && job.result?.run_id) {
            preferredRun.current = job.result.run_id;
            reloadRef.current?.();
          }
        } else { pollRef.current = window.setTimeout(tick, 2000); }
      } catch (error) {
        if (!current()) return;
        stopPolling();
        setEvaluationJob(current => ({ job: current.job, error: gatewayReason(error) }));
      }
    };
    void tick();
  }, [stopPolling]);

  const load = useCallback((projectId: string) => {
    const ticket = ++projectEpoch.current;
    const switching = activeProject.current !== projectId;
    ++runEpoch.current;
    activeProject.current = projectId;
    stopPolling();
    if (switching) setEvaluationJob({ job: null, error: null });
    remember(projectId);
    const current = () => ticket === projectEpoch.current;
    setProject({ phase: 'loading', projectId });
    setRun({ phase: 'idle' });
    (async () => {
      try {
        const [detail, draft] = await Promise.all([
          gateway.project(projectId),
          gateway.projectDraft(projectId).catch(() => null),
        ]);
        if (!current()) return;
        let topology: Topology | null = null;
        let topologyError = '';
        if (detail.active_revision_id) {
          try { topology = await gateway.topology(detail.active_revision_id); }
          catch (error) { topologyError = gatewayReason(error); }
        } else {
          topologyError = 'This project has no active revision, so no topology exists to render.';
        }
        if (!current()) return;
        setProject({ phase: 'loaded', data: { detail, request: (draft?.request ?? null) as DraftRequest | null, draftMeta: draft ? { dirty: draft.dirty, design_hash: draft.design_hash, workload_id: draft.workload_id, updated_at: draft.updated_at } : null, topology, topologyError } });
        // Default to the newest run that actually carries a backend evaluation; a bundle-only
        // record (compile step) would open as an almost-empty page and look like a failure.
        const newest = [...(detail.runs ?? [])].sort((a, b) => String(a.completed_at ?? '').localeCompare(String(b.completed_at ?? '')));
        const evaluable = newest.filter(r => r.bundle_id && r.backend && r.requirements_pass !== null && r.requirements_pass !== undefined);
        const withBackend = newest.filter(r => r.backend);
        const preferred = newest.find(r => r.run_id === preferredRun.current);
        preferredRun.current = null;
        const first = preferred ?? evaluable[evaluable.length - 1] ?? withBackend[withBackend.length - 1] ?? newest[newest.length - 1];
        if (first) loadRun(first.run_id);
        gateway.projectJobs(projectId, 'EVALUATION').then(result => {
          if (!current()) return;
          const active = (result.jobs ?? []).find(job => !['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state));
          if (active) trackEvaluation(active.job_id);
        }).catch(() => { /* A job-list read failure must not discard the loaded project. */ });
      } catch (error) {
        if (current()) setProject({ phase: 'error', projectId, reason: gatewayReason(error) });
      }
    })();
  }, [loadRun, stopPolling, trackEvaluation]);

  const reloadRef = useRef<null | (() => void)>(null);
  reloadRef.current = () => { if (project.phase === 'loaded') load(project.data.detail.project.project_id); };

  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem('srota-gateway-selection:v1') ?? 'null');
      if (saved && typeof saved.projectId === 'string') {
        preferredRun.current = typeof saved.runId === 'string' ? saved.runId : null;
        load(saved.projectId);
      }
    } catch { /* Invalid recovery data does not block the workspace. */ }
    return () => { ++projectEpoch.current; ++runEpoch.current; stopPolling(); };
  }, [load, stopPolling]);

  const value = useMemo<Context>(() => ({
    health, projects, listError, listPhase, project, run,
    refreshList: () => setTick(t => t + 1),
    load,
    loadRun,
    reload: () => { if (project.phase === 'loaded') load(project.data.detail.project.project_id); },
    evaluationJob,
    trackEvaluation,
    cancelEvaluation: () => {
      const jobId = evaluationJob.job?.job_id;
      if (!jobId) return;
      const ticket = jobEpoch.current;
      gateway.cancelJob(jobId)
        .then(job => { if (ticket !== jobEpoch.current) return; stopPolling(); setEvaluationJob({ job, error: null }); if (!['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state)) trackEvaluation(jobId); })
        .catch(error => { if (ticket === jobEpoch.current) setEvaluationJob(current => ({ job: current.job, error: gatewayReason(error) })); });
    },
    clearEvaluation: () => { stopPolling(); setEvaluationJob({ job: null, error: null }); },
    clear: () => { ++projectEpoch.current; ++runEpoch.current; activeProject.current = null; preferredRun.current = null; remember(null); setProject({ phase: 'idle' }); setRun({ phase: 'idle' }); stopPolling(); setEvaluationJob({ job: null, error: null }); },
  }), [health, projects, listError, listPhase, project, run, load, loadRun, evaluationJob, trackEvaluation, stopPolling]);

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject() {
  const context = useContext(ProjectContext);
  if (!context) throw new Error('useProject must be used inside ProjectProvider');
  return context;
}

export function useLoadedRun(): LoadedRun | null {
  const { run } = useProject();
  return run.phase === 'loaded' ? run.data : null;
}

// Convenience for views that only care about a successfully loaded project.
export function useLoadedProject(): LoadedProject | null {
  const { project } = useProject();
  return project.phase === 'loaded' ? project.data : null;
}
