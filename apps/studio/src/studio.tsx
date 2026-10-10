import {
  createContext, useContext, useEffect, useState,
  type ReactElement, type ReactNode,
} from 'react';
import { api, ApiError, type JobView, type ProjectView } from './api';
import { navigate } from './router';

export type Mode = 'checking' | 'live' | 'offline';

interface StudioContextValue {
  mode: Mode;
  projects: ProjectView[];
  projectsError: string | null;
  refreshProjects: () => void;
  activeProjectId: string;
  setActiveProjectId: (projectId: string) => void;
}

const StudioContext = createContext<StudioContextValue | null>(null);

const ACTIVE_PROJECT_KEY = 'veritx.active-project';

function readStoredProject(): string {
  try {
    return window.localStorage.getItem(ACTIVE_PROJECT_KEY) ?? '';
  } catch {
    return '';
  }
}

export function StudioProvider({ children }: { children: ReactNode }): ReactElement {
  const [mode, setMode] = useState<Mode>('checking');
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [activeProjectId, setActiveProjectIdState] = useState<string>(
    readStoredProject,
  );

  const setActiveProjectId = (projectId: string): void => {
    setActiveProjectIdState((current) =>
      current === projectId ? current : projectId);
    try {
      if (projectId) {
        window.localStorage.setItem(ACTIVE_PROJECT_KEY, projectId);
      } else {
        window.localStorage.removeItem(ACTIVE_PROJECT_KEY);
      }
    } catch {
    }
  };

  useEffect(() => {
    let alive = true;
    api
      .health()
      .then(() => alive && setMode('live'))
      .catch(() => alive && setMode('offline'));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (mode !== 'live') return;
    let alive = true;
    api
      .listProjects()
      .then((r) => {
        if (!alive) return;
        setProjects(r.projects);
        setProjectsError(null);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setProjectsError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [mode, nonce]);

  const value: StudioContextValue = {
    mode,
    projects,
    projectsError,
    refreshProjects: () => setNonce((n) => n + 1),
    activeProjectId,
    setActiveProjectId,
  };
  return <StudioContext.Provider value={value}>{children}</StudioContext.Provider>;
}

export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext);
  if (!ctx) throw new Error('useStudio must be used inside StudioProvider');
  return ctx;
}

export type Async<T> =
  | { state: 'loading' }
  | { state: 'error'; error: ApiError | Error }
  | { state: 'ready'; data: T };

export function useAsync<T>(
  fn: () => Promise<T>,
  deps: unknown[],
): { result: Async<T>; reload: () => void } {
  const [result, setResult] = useState<Async<T>>({ state: 'loading' });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setResult({ state: 'loading' });
    fn()
      .then((data) => alive && setResult({ state: 'ready', data }))
      .catch((error: unknown) => {
        if (!alive) return;
        setResult({
          state: 'error',
          error: error instanceof Error ? error : new Error(String(error)),
        });
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { result, reload: () => setNonce((n) => n + 1) };
}

const TERMINAL = new Set(['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED']);

export function useJobPoll(
  jobId: string | null,
  onTerminal?: (job: JobView) => void,
  onError?: (error: Error | null) => void,
): JobView | null {
  const [job, setJob] = useState<JobView | null>(null);
  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async (): Promise<void> => {
      try {
        const next = await api.job(jobId);
        if (!alive) return;
        setJob(next);
        onError?.(null);
        if (TERMINAL.has(next.state)) {
          onTerminal?.(next);
          return;
        }
      } catch (error) {
        if (!alive) return;
        onError?.(error instanceof Error ? error : new Error(String(error)));
      }
      timer = setTimeout(tick, 1000);
    };
    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);
  return job;
}

export function Link({
  to, className, children, title, ariaLabel,
}: {
  to: string;
  className?: string;
  children: ReactNode;
  title?: string;
  ariaLabel?: string;
}): ReactElement {
  return (
    <a
      href={to}
      className={className}
      title={title}
      aria-label={ariaLabel}
      onClick={(e) => {
        if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey
            || e.altKey || e.button !== 0) {
          return;
        }
        e.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}

export function ErrorBox({ error, onRetry }: {
  error: Error;
  onRetry?: () => void;
}): ReactElement {
  const apiError = error instanceof ApiError ? error : null;
  return (
    <div className="error-box" role="alert">
      <div className="error-cat">
        <strong>{apiError ? apiError.code : 'ERROR'}</strong>
        {apiError && <span className="muted"> · HTTP {apiError.status}</span>}
      </div>
      <p>{error.message}</p>
      {apiError?.requestId && (
        <p className="muted">request id: {apiError.requestId}</p>
      )}
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function AsyncView<T>({
  result,
  reload,
  children,
}: {
  result: Async<T>;
  reload: () => void;
  children: (data: T) => ReactNode;
}): ReactElement {
  if (result.state === 'loading') {
    return <p className="muted" role="status" aria-live="polite">loading…</p>;
  }
  if (result.state === 'error') {
    return <ErrorBox error={result.error} onRetry={reload} />;
  }
  return <>{children(result.data)}</>;
}

export function PageShell({ title, lede, actions, children }: {
  title: string;
  lede?: string;
  actions?: ReactNode;
  children: ReactNode;
}): ReactElement {
  return (
    <div className="page">
      <div className="page-head">
        <div className="page-head-text">
          <h2 className="page-title">{title}</h2>
          {lede && <p className="page-lede">{lede}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </div>
      <div className="page-stack">{children}</div>
    </div>
  );
}

export function JobProgress({ job }: { job: JobView | null }): ReactElement | null {
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  if (!job) return null;
  const done = TERMINAL.has(job.state);
  return (
    <div className={`job-progress job-${job.state.toLowerCase()}`}
         role="status" aria-live="polite">
      <span className="job-state">{job.state}</span>
      <span className="muted">job {job.job_id}</span>
      {job.error_code && (
        <span className="bad">
          {job.error_code}: {job.error_message}
        </span>
      )}
      {!done && <span className="spinner" aria-label="working" />}
      {job.cancellable && !done && (
        <button className="btn" disabled={cancelling || job.state === 'CANCELLING'}
          onClick={async () => {
            setCancelling(true);
            setCancelError(null);
            try { await api.cancelJob(job.job_id); }
            catch (err) { setCancelError(err instanceof Error ? err.message : String(err)); }
            finally { setCancelling(false); }
          }}>
          {cancelling || job.state === 'CANCELLING' ? 'Cancelling…' : 'Cancel job'}
        </button>
      )}
      {cancelError && <span role="alert">{cancelError} · Retry cancellation.</span>}
    </div>
  );
}

export function nextActionLabel(action: string): string {
  switch (action) {
    case 'COMPILE':
      return 'Compile design';
    case 'EDIT_DRAFT':
      return 'Fix design';
    case 'INSPECT_VERIFY':
      return 'Inspect verification';
    case 'RUN_EVALUATION':
      return 'Run simulation';
    case 'COMPARE_OR_OPTIMIZE':
      return 'Compare / optimize';
    case 'WAIT':
      return 'View progress';
    default:
      return 'Open design';
  }
}

export function simulationCapabilityReason(
  domain: string | null | undefined,
  reason: string | null | undefined,
): string {
  const detail = (reason ?? '').replace(/^UNSUPPORTED:\s*/, '');
  switch (domain) {
    case 'intent_lowering':
      return 'Intent → executable workload lowering is not yet qualified.'
        + (detail ? ` ${detail}` : '');
    case 'backend_profile':
      return 'The certified execution profile cannot represent this '
        + 'exact fabric.'
        + (detail ? ` ${detail}` : '');
    case 'compile':
      return detail || 'The design did not compile.';
    default:
      return detail || 'Simulation is not supported for this design.';
  }
}
export function ContextHeader({ project }: { project: ProjectView }): ReactElement {
  const pid = project.project.project_id;
  const active = project.revisions.find(
    (r) => r.revision_id === project.active_revision_id,
  );
  const evaluation = project.latest_static_evaluation
    ?? project.latest_active_run;
  const study = project.latest_optimization_study;
  const revisionText = active
    ? `${active.display_name} · ${active.compilation_status}`
    : 'no compiled revision';
  const evaluationText = evaluation
    ? `Network completion · ${evaluation.backend ?? 'backend —'} · ${
        evaluation.completion_cycles ?? '—'
      } cycles · SIMULATED · qualification ${
        evaluation.qualification ?? '—'} · run ${
        evaluation.status ?? '—'}`
    : 'none';
  const studyText = study
    ? `${study.candidate_count} candidates · selected ${
        study.selected_candidate_id ?? '—'}`
    : 'none';
  return (
    <div className="context-header">
      <div>
        <span className="ctx-key">Project</span>
        <span className="ctx-val" title={project.project.name}>
          {project.project.name}
        </span>
      </div>
      <div>
        <span className="ctx-key">Revision</span>
        <span className="ctx-val" title={revisionText}>
          {revisionText}
          {project.draft.dirty && (
            <span className="stale"> · UNCOMPILED CHANGES</span>
          )}
        </span>
      </div>
      <div>
        <span className="ctx-key">Latest analysis</span>
        <span className="ctx-val" title={evaluationText}>
          {evaluationText}
        </span>
      </div>
      <div>
        <span className="ctx-key">Latest optimization</span>
        <span className="ctx-val" title={studyText}>
          {studyText}
        </span>
      </div>
      <details className="ctx-history">
        <summary className="ctx-key">History</summary>
        <div className="ctx-history-body">
          <div>
            <b>Revisions</b>
            <ul>
              {project.revisions.map((r) => (
                <li key={r.revision_id}>
                  <Link to={`/projects/${pid}/compile`}>
                    {r.display_name} · {r.compilation_status}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <b>Runs</b>
            <ul>
              {project.runs.map((r) => (
                <li key={r.run_id}>
                  <Link to={`/runs/${r.run_id}`}>
                    {r.display_name ?? r.run_id} · {r.backend ?? '—'} · ${
                      r.status ?? '—'}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <b>Studies</b>
            <ul>
              {project.optimizations.map((o) => (
                <li key={o.optimization_id}>
                  <Link to={`/projects/${pid}/optimize`}>
                    {o.optimization_id.slice(0, 8)} · {o.candidate_count} candidates
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </details>
    </div>
  );
}

