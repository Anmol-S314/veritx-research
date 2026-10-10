import { useEffect, useState, type ReactElement } from 'react';
import { api, type AISearchView, type AITopologyAttempt } from '../api';
import { AsyncView, ErrorBox, JobProgress, useAsync } from '../studio';
import { jobActive } from '../hooks/useCompileJob';
import { StatusBadge } from './badges';

export function AITopologyResults({ view, saved, busy, onAdopt }: {
  view: AISearchView; saved: boolean; busy: boolean;
  onAdopt: (candidate: AITopologyAttempt) => void;
}): ReactElement {
  return <>
    <p className="muted">Snapshot <code title={view.base_design_hash}>{view.base_design_hash.slice(0, 20)}…</code>
      {' · '}{view.model ?? 'model pending'}</p>
    {view.stale && <p className="stale" role="status">The saved draft changed. These results belong to the earlier snapshot; start a new search to adopt.</p>}
    <ol className="ai-topology-attempts">
      {view.attempts.map((row) => <li key={row.attempt}>
        <div className="row">
          <strong>Proposal {row.attempt}</strong> <StatusBadge status={row.status} />
          {row.objective_values.completion_cycles !== undefined
            ? <span>Network completion: <span className="mono">{row.objective_values.completion_cycles.toLocaleString()} cycles</span>
              {' · '}{row.execution_fidelity} · requirements {row.requirements_pass ? 'satisfied' : 'not satisfied'}</span>
            : <span className="muted">No verified measurement</span>}
        </div>
        {row.reason && <p>{row.reason}</p>}
        {row.topology && <details className="subtle">
          <summary>Topology and rationale</summary>
          <p>{row.rationale}</p>
          <pre>{JSON.stringify(row.topology, null, 2)}</pre>
          {row.backend_profile && <p className="muted">Backend profile: <code>{row.backend_profile}</code></p>}
        </details>}
        {row.adoptable && <button className="btn" disabled={busy || !saved || view.stale}
          aria-label={`Use proposal ${row.attempt} topology in draft`} onClick={() => onAdopt(row)}>
          Use topology in draft
        </button>}
      </li>)}
    </ol>
  </>;
}

function SearchPanel({ projectId, draftHash, saved, onAdopted }: {
  projectId: string; draftHash: string | null; saved: boolean; onAdopted: () => void;
}): ReactElement {
  const caps = useAsync(api.aiSearchCapabilities, []);
  const history = useAsync(() => api.projectJobs(projectId, 'AI_SEARCH'), [projectId]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [view, setView] = useState<AISearchView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!jobId && history.result.state === 'ready') {
      setJobId(history.result.data.jobs[0]?.job_id ?? null);
    }
  }, [history.result, jobId]);
  useEffect(() => {
    if (!jobId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async (): Promise<void> => {
      try {
        const next = await api.aiSearch(projectId, jobId);
        if (!live) return;
        setView(next);
        setError(null);
        if (!jobActive(next.job)) return;
      } catch (err) {
        if (!live) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      }
      timer = setTimeout(tick, 1000);
    };
    void tick();
    return () => { live = false; if (timer) clearTimeout(timer); };
  }, [projectId, jobId, nonce, draftHash]);
  const start = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      if (!draftHash) throw new Error('Save a valid draft before starting AI search.');
      const job = await api.startAISearch(projectId, draftHash);
      setView(null);
      setJobId(job.job_id);
    } catch (err) { setError(err instanceof Error ? err : new Error(String(err))); }
    finally { setBusy(false); }
  };
  const adopt = async (row: AITopologyAttempt): Promise<void> => {
    if (!view || !row.candidate_id) return;
    setBusy(true);
    setError(null);
    try {
      await api.adoptAITopology(projectId, view.job.job_id, row.candidate_id, view.base_design_hash);
      onAdopted();
      setNonce(n => n + 1);
    } catch (err) { setError(err instanceof Error ? err : new Error(String(err))); }
    finally { setBusy(false); }
  };
  return <AsyncView result={caps.result} reload={caps.reload}>{c => <>
    <p>Send the saved design to {c.model ?? 'the configured model'} for up to {c.limits.max_proposals} topology proposals.
      Independent compile checks and simulation judge them; nothing is adopted automatically.</p>
    <p className="muted">At most {c.limits.max_routers} routers / {c.limits.max_seats} seats,
      {' '}{c.limits.max_channels} directed channels, degree {c.limits.max_network_degree}.
      {' '}{c.max_model_output_tokens.toLocaleString()} output tokens per proposal;
      {' '}{c.job_timeout_s}-second job deadline. Network completion only, not model runtime, area or power.</p>
    {!c.configured && <p role="status">{c.reason}</p>}
    {!c.backend_present && <p role="status">BookSim is missing. Configure VERITX_BOOKSIM_BIN on the server.</p>}
    {!saved && <p className="stale">Save changes before starting a search or adopting a topology.</p>}
    <button className="btn" disabled={!saved || !draftHash || !c.configured || !c.backend_present || busy
      || history.result.state !== 'ready' || (!!jobId && !view) || jobActive(view?.job ?? null)} onClick={() => void start()}>
      {busy ? 'Working…' : 'Start AI topology search'}
    </button>
    <JobProgress job={view?.job ?? null} />
    {jobId && !view && <p role="status">Loading search…</p>}
    {view && <AITopologyResults view={view} saved={saved} busy={busy} onAdopt={row => void adopt(row)} />}
    {history.result.state === 'error' && <ErrorBox error={history.result.error} onRetry={history.reload} />}
    {error && <ErrorBox error={error} onRetry={() => setNonce(n => n + 1)} />}
  </>}</AsyncView>;
}

export default function AITopologySearch(props: {
  projectId: string; draftHash: string | null; saved: boolean; onAdopted: () => void;
}): ReactElement {
  const [open, setOpen] = useState(false);
  return <details className="subtle ai-topology-search" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>AI topology search</summary>
    {open && <SearchPanel {...props} />}
  </details>;
}
