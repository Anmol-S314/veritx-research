import { useEffect, useState, type ReactElement } from 'react';
import { api, type JobView, type ProjectView, type RevisionView } from '../api';
import {
  AsyncView, ContextHeader, ErrorBox, JobProgress, Stepper, useAsync,
  useJobPoll, useStudio,
} from '../studio';
import { Hash, StatusBadge } from '../components/badges';
import DesignEditor from '../components/DesignEditor';
import VerifyView from '../components/VerifyView';
import EvaluateView from '../components/EvaluateView';
import { navigate } from '../router';
import { clone, getPath, setPath } from '../util';

// ── Draft editing (canonical request doc) ─────────────────────────────────

const DRAFT_FIELDS: { path: string; label: string; kind: 'number' | 'text' }[] = [
  { path: 'workload.tp', label: 'TP', kind: 'number' },
  { path: 'workload.pp', label: 'PP', kind: 'number' },
  { path: 'workload.ep', label: 'EP', kind: 'number' },
  { path: 'workload.dp', label: 'DP', kind: 'number' },
  { path: 'noc_config.link_width', label: 'Link width (b)', kind: 'number' },
  { path: 'noc_config.concentration', label: 'Concentration', kind: 'number' },
  { path: 'noc_config.topology_family', label: 'Topology family', kind: 'text' },
  { path: 'requirements.0.latency_ceiling_cycles', label: 'Latency ceiling (cycles)', kind: 'number' },
];

function DraftEditor({
  projectId,
  project,
  onChanged,
}: {
  projectId: string;
  project: ProjectView;
  onChanged: () => void;
}): ReactElement {
  const draft = useAsync(() => api.draft(projectId), [projectId]);
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (draft.result.state === 'ready') {
      setDoc(clone(draft.result.data.request ?? {}));
      setDirty(false);
    }
  }, [draft.result]);

  const edit = (path: string, raw: string, kind: 'number' | 'text'): void => {
    if (!doc) return;
    const next = clone(doc);
    const value = kind === 'number'
      ? (raw === '' ? null : Number(raw))
      : raw;
    setPath(next, path, value);
    setDoc(next);
    setDirty(true);
  };

  const save = async (): Promise<void> => {
    if (!doc) return;
    setBusy(true);
    setError(null);
    try {
      await api.putDraft(projectId, doc);
      setDirty(false);
      draft.reload();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };

  const compile = async (): Promise<void> => {
    if (!doc) return;
    setBusy(true);
    setError(null);
    try {
      if (dirty) await api.putDraft(projectId, doc);
      await api.compile(projectId);
      setDirty(false);
      draft.reload();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h3>Draft (live edits)</h3>
      {draft.result.state === 'error' && (
        <ErrorBox error={draft.result.error} onRetry={draft.reload} />
      )}
      {doc && (
        <>
          <div className="form-row">
            {DRAFT_FIELDS.map((f) => {
              const value = getPath(doc, f.path);
              return (
                <label key={f.path}>
                  {f.label}
                  <input
                    type={f.kind}
                    value={value === null || value === undefined ? '' : String(value)}
                    onChange={(e) => edit(f.path, e.target.value, f.kind)}
                  />
                </label>
              );
            })}
          </div>
          <div className="form-row">
            <button className="btn" disabled={busy || !dirty} onClick={save}>
              Save draft
            </button>
            <button className="btn btn-primary" disabled={busy} onClick={compile}>
              {busy ? 'Compiling…' : 'Compile design'}
            </button>
            {project.draft.dirty && <span className="stale">UNCOMPILED CHANGES</span>}
          </div>
          {error && <ErrorBox error={error} />}
          <p className="muted">
            Edits here update the immutable revision inputs. Compiling creates a
            new immutable DesignRevision; the previous revision is never mutated.
          </p>
        </>
      )}
    </section>
  );
}

export function Design({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const reloadAll = (): void => {
    project.reload();
    refreshProjects();
  };
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const active = p.active_revision;
        return (
          <div className="page">
            <ContextHeader project={p} />
            <Stepper project={p} current="design" />
            <h2>Design</h2>
            <DraftEditor projectId={projectId} project={p} onChanged={reloadAll} />
            {active ? (
              <RevisionDesign revision={active} dirty={p.draft.dirty} />
            ) : (
              <p className="muted">
                Compile the draft to materialise a DesignView and LOCKED derived
                properties.
              </p>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

function RevisionDesign({ revision, dirty }: {
  revision: RevisionView;
  dirty: boolean;
}): ReactElement {
  return (
    <div>
      {dirty && (
        <div className="dirty-banner">
          <span>
            Showing <strong>FROM REVISION {revision.display_name}</strong>. The
            draft has uncompiled changes; these LOCKED values belong to the
            previous revision.
          </span>
        </div>
      )}
      <DesignEditor design={revision.design} live />
    </div>
  );
}

// ── Compile & Verify ──────────────────────────────────────────────────────

export function CompileVerify({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const compile = async (): Promise<void> => {
    setCompiling(true);
    setError(null);
    try {
      await api.compile(projectId);
      project.reload();
      refreshProjects();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setCompiling(false);
    }
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const active = p.active_revision;
        const obs = active?.compilation.obligations ?? [];
        return (
          <div className="page">
            <ContextHeader project={p} />
            <Stepper project={p} current="compile" />
            <h2>Compile &amp; Verify</h2>
            <div className="form-row">
              <button className="btn btn-primary" disabled={compiling} onClick={compile}>
                {compiling ? 'Compiling…' : 'Compile draft'}
              </button>
              {p.draft.dirty && <span className="stale">DRAFT HAS UNCOMPILED CHANGES</span>}
            </div>
            {error && <ErrorBox error={error} />}
            {active ? (
              <>
                <div className={`verdict-banner verdict-${(active.compilation.status ?? '').toLowerCase()}`}>
                  <StatusBadge status={active.compilation.status} />
                  <span className="verdict-text">
                    {active.compilation.status === 'COMPILED'
                      ? `Certificate ${active.certificate?.overall ?? '—'} — ${
                          obs.filter((o) => o.status === 'PASS').length
                        }/${obs.length} obligations PASS.`
                      : active.compilation.error ?? 'Refused.'}
                  </span>
                </div>
                <section className="card">
                  <h3>Fabric summary</h3>
                  <div className="kv"><span>revision</span><span>{active.display_name}</span></div>
                  <div className="kv"><span>topology</span><span>{String(active.design.noc_guided.topology_family ?? '—')}</span></div>
                  <div className="kv"><span>link width</span><span>{String(active.design.noc_guided.link_width ?? '—')} bits</span></div>
                  <div className="kv"><span>routing</span><span>{active.design.locked_derived?.routing ?? '—'}</span></div>
                  <div className="kv"><span>VC count</span><span>{active.design.locked_derived?.vc_count ?? '—'}</span></div>
                  <div className="kv"><span>design_hash</span><Hash value={active.design_hash} /></div>
                  <details>
                    <summary>Evidence identities</summary>
                    <div className="kv"><span>resolved_fabric_hash</span><Hash value={active.compilation.resolved_fabric_hash} /></div>
                    <div className="kv"><span>certificate_id</span><Hash value={active.compilation.certificate_id} /></div>
                    {active.compilation.artifact_hashes && Object.entries(active.compilation.artifact_hashes).map(([k, v]) => (
                      <div className="kv" key={k}><span>{k}</span><Hash value={v} /></div>
                    ))}
                  </details>
                </section>
                <h3>Verification obligations</h3>
                <VerifyView compilation={active.compilation} />
              </>
            ) : (
              <p className="muted">No compiled revision yet.</p>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

// ── Simulate ──────────────────────────────────────────────────────────────

export function Simulate({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);

  const [jobId, setJobId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const onTerminal = (job: JobView): void => {
    setRunId(job.result?.run_id ?? null);
    project.reload();
    refreshProjects();
  };
  const job = useJobPoll(jobId, onTerminal);

  const run = useAsync(
    () => (runId ? api.run(runId) : Promise.reject(new Error('no run'))),
    [runId],
  );

  const start = async (): Promise<void> => {
    const currentId = project.result.state === 'ready'
      ? project.result.data.active_revision_id
      : null;
    if (!currentId) return;
    setError(null);
    setRunId(null);
    try {
      const submitted = await api.evaluate(currentId);
      setJobId(submitted.job_id);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const current = p.active_revision;
        const running = job !== null && !['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state);
        return (
          <div className="page">
            <ContextHeader project={p} />
            <Stepper project={p} current="simulate" />
            <h2>Simulate</h2>
            <section className="card">
              <h3>Run configuration</h3>
              <div className="kv"><span>revision</span><span>{current?.display_name ?? '—'}</span></div>
              <div className="kv"><span>workload</span><span>{p.draft.workload_id ?? '—'}</span></div>
              <div className="kv"><span>backend</span><span>Embedded BookSim (qualified)</span></div>
              <div className="kv"><span>certificate</span><span>{current?.certificate?.overall ?? '—'}</span></div>
              <div className="kv"><span>expected run type</span><span>network execution + authenticated evidence</span></div>
              <div className="form-row">
                <button
                  className="btn btn-primary"
                  disabled={!current || current.certificate?.overall !== 'PASS' || running}
                  onClick={start}
                >
                  {running ? 'Running…' : 'Run Simulation'}
                </button>
                {p.draft.dirty && <span className="stale">DRAFT HAS UNCOMPILED CHANGES — compile first</span>}
              </div>
              {error && <ErrorBox error={error} />}
              <JobProgress job={job} />
            </section>
            {job?.state === 'REFUSED' && (
              <ErrorBox error={new Error(job.error_message ?? 'evaluation refused')} />
            )}
            {runId && run.result.state === 'ready' && (
              <>
                <section className="card">
                  <h3>
                    Result{' '}
                    <StatusBadge status={run.result.data.status ?? 'UNKNOWN'} />{' '}
                    {run.result.data.qualification ?? ''}
                  </h3>
                  <div className="kv"><span>run</span>
                    <button className="link" onClick={() => navigate(`/runs/${runId}`)}>
                      {run.result.data.display_name ?? runId}
                    </button>
                  </div>
                  <div className="kv"><span>run bundle</span><Hash value={run.result.data.bundle_id} /></div>
                </section>
                <EvaluateView
                  evaluation={run.result.data.evaluation}
                  requirements={run.result.data.requirements}
                  fixtureId={runId}
                  live
                />
              </>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}
