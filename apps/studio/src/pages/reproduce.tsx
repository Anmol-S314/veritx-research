import { useState, type ReactElement } from 'react';
import {
  api,
  type JobView,
  type RunSummary,
} from '../api';
import { AsyncView, Link, useAsync } from '../studio';
import { Hash, StatusBadge } from '../components/badges';

const REPRODUCIBLE_BACKENDS = ['BookSim', 'ASTRA', 'Ramulator', 'Serving'];

function backendReproducibility(backend: string | null | undefined): string {
  if (!backend) return 'NOT AVAILABLE — no producer on this run';
  const upper = backend.toUpperCase();
  if (upper.includes('SERVING')) {
    return 'REPLAYABLE — deterministic replay where the serving harness supports it';
  }
  if (REPRODUCIBLE_BACKENDS.some((b) => upper.includes(b.toUpperCase()))) {
    return 'AVAILABLE — archived inputs required below';
  }
  return 'NOT AVAILABLE — no reproduction contract for this producer';
}

function outcomeBadge(job: JobView | null): ReactElement {
  if (!job) return <span className="muted">not attempted</span>;
  if (job.state === 'COMPLETED' && job.result?.outcome === 'DIVERGED') {
    return <StatusBadge status="DIVERGED" />;
  }
  if (job.state === 'COMPLETED') return <StatusBadge status="REPRODUCED" />;
  if (job.state === 'REFUSED') return <StatusBadge status="REFUSED" />;
  if (job.state === 'FAILED') return <StatusBadge status="FAILED" />;
  return <StatusBadge status={job.state} />;
}

function ReproduceCard({ run }: { run: RunSummary }): ReactElement {
  const [job, setJob] = useState<JobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const launch = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const submitted = await api.reproduceRun(run.run_id);
      for (;;) {
        const current = await api.job(submitted.job_id);
        setJob(current);
        if (['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(current.state)) {
          return;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const reproductions = job?.result?.reproductions;
  return (
    <section className="card">
      <div className="page-head">
        <h3>
          <Link className="link" to={`/runs/${run.run_id}`}>
            {run.display_name ?? run.run_id}
          </Link>{' '}
          <StatusBadge status={run.status ?? 'UNKNOWN'} />
        </h3>
        <div className="head-actions">
          <button type="button" className="btn" disabled={busy} onClick={() => void launch()}>
            Run reproduction
          </button>
        </div>
      </div>
      <div className="kv">
        <span>producer</span>
        <span className="muted">{run.backend ?? '—'}</span>
      </div>
      <div className="kv">
        <span>reproducibility</span>
        <span className="muted">{backendReproducibility(run.backend)}</span>
      </div>
      <div className="kv">
        <span>required archived inputs</span>
        <span className="muted">
          design {run.design_hash ? 'bound' : 'MISSING'} · bundle{' '}
          {run.bundle_id ? 'bound' : 'MISSING'} — reproduction without
          archived inputs is REFUSED, never approximated.
        </span>
      </div>
      <div className="kv">
        <span>bundle identity</span>
        <Hash value={run.bundle_id} />
      </div>
      <div className="kv">
        <span>outcome</span>
        {outcomeBadge(job)}
      </div>
      {job && job.state !== 'COMPLETED' && (job.error_message ?? job.error_code) && (
        <p className="muted">
          {job.state === 'REFUSED' ? 'refused: ' : 'failure: '}
          {job.error_message ?? job.error_code}
        </p>
      )}
      {reproductions && (
        <>
          <h4>Per-analysis comparison</h4>
          <table className="tbl">
            <thead>
              <tr><th>question</th><th>backend</th><th>outcome</th><th>reason</th></tr>
            </thead>
            <tbody>
              {Object.entries(reproductions).map(([question, r]) => (
                <tr key={question}>
                  <td><code>{question}</code></td>
                  <td className="muted">{r.backend ?? '—'}</td>
                  <td>
                    {r.outcome
                      ? <StatusBadge status={r.outcome} />
                      : <span className="muted">{r.status ?? '—'}</span>}
                  </td>
                  <td className="muted">{r.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            Original vs reproduced native evidence is compared by digest —
            match or divergence, never a silent archival failure.
          </p>
        </>
      )}
      {error && <p className="bad">{error}</p>}
    </section>
  );
}

export function Reproduce({ projectId }: { projectId: string }): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => (
        <div className="page">
          <div className="page-head">
            <div>
              <h2>Reproduce</h2>
              <p className="muted">
                Re-run archived executions and compare native evidence.
                Every analysis reports its own outcome — a backend that
                cannot rerun here says so explicitly.
              </p>
            </div>
            <div className="head-actions">
              <Link className="btn" to="/runs">All runs</Link>
            </div>
          </div>
          {p.runs.length === 0 ? (
            <p className="muted">
              No runs yet — reproductions appear after an evaluation.
            </p>
          ) : (
            <div className="stack-lg">
              {[...p.runs].reverse().map((r) => (
                <ReproduceCard key={r.run_id} run={r} />
              ))}
            </div>
          )}
        </div>
      )}
    </AsyncView>
  );
}
