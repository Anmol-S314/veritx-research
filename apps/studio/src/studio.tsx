// Studio shell primitives: mode detection, active-project state, async/job
// hooks and the persistent context header. React renders the gateway's
// explicit flow state; it never infers a stage from a missing field.
//
// The linear 01…05 WorkflowBar was removed (STUDIO-WIREFRAMES.md §144/§181):
// navigation follows the scientific object lifecycle (Design · Evaluate ·
// Serve · Optimize · History · Capability), not one global pipeline.
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
  /** Last project the user had open. Survives global routes (/runs,
   * /trust) and reloads so the shell never silently drops context. */
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
      /* storage unavailable — context stays session-only */
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
        if (TERMINAL.has(next.state)) {
          onTerminal?.(next);
          return;
        }
      } catch {
        /* keep polling through transient errors */
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

// ── shared UI ─────────────────────────────────────────────────────────────

/** A real anchor: native link semantics, keyboard/middle-click and deep
 * linking, with client-side navigation for plain left clicks. */
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

export function JobProgress({ job }: { job: JobView | null }): ReactElement | null {
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
    </div>
  );
}

/** Human product language for the gateway's flow actions. The API keeps
 * its stable enum values; the primary UI never shows them raw. */
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

export function ContextHeader({ project }: { project: ProjectView }): ReactElement {
  const active = project.revisions.find(
    (r) => r.revision_id === project.active_revision_id,
  );
  // Scoped to the active revision by the gateway: a run from an older
  // revision — or a newer refused attempt, which has no runs — must never
  // render beside the current revision's name.
  const latestRun = project.latest_active_run
    ?? [...project.runs]
      .reverse()
      .find((r) => r.revision_id === project.active_revision_id);
  const latestName = latestRun
    ? (project.revisions.find((r) => r.revision_id === latestRun.revision_id)
      ?.display_name ?? null)
    : null;
  return (
    <div className="context-header">
      <div>
        <span className="ctx-key">Project</span>
        <span className="ctx-val">{project.project.name}</span>
      </div>
      <div>
        <span className="ctx-key">Revision</span>
        <span className="ctx-val">
          {active
            ? `${active.display_name} · ${active.compilation_status.toLowerCase()}`
            : 'none'}
          {project.draft.dirty && <span className="stale"> · DRAFT UNCOMPILED</span>}
        </span>
      </div>
      <div>
        <span className="ctx-key">Workload</span>
        <span className="ctx-val">{project.draft.workload_id ?? '—'}</span>
      </div>
      <div>
        <span className="ctx-key">Latest run</span>
        <span className="ctx-val">
          {latestRun
            ? `${latestRun.qualification ?? latestRun.status} · ${
                latestRun.completion_cycles ?? '—'
              } cycles${latestName ? ` · ${latestName}` : ''}`
            : 'none'}
        </span>
      </div>
      <div>
        <span className="ctx-key">Next</span>
        <span className="ctx-val next-action">
          {nextActionLabel(project.flow.next_action)}
        </span>
      </div>
    </div>
  );
}
