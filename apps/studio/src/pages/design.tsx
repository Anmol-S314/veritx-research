import { useRef, useState, type ReactElement } from 'react';
import { api, type JobView, type ProjectView } from '../api';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync,
  useJobPoll, useStudio,
} from '../studio';
import { Hash, StatusBadge } from '../components/badges';
import ArtifactChain from '../components/ArtifactChain';
import DesignEditor from '../components/DesignEditor';
import VerifyView from '../components/VerifyView';
import EvaluateView from '../components/EvaluateView';

export function Design({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const draft = useAsync(() => api.draft(projectId), [projectId]);
  const reloadAll = (): void => {
    project.reload();
    draft.reload();
    refreshProjects();
  };
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p: ProjectView) => (
        <AsyncView result={draft.result} reload={draft.reload}>
          {(d) => {
            const active = p.active_revision;
            const attempt = p.latest_attempt;
            const refused = attempt
              && attempt.revision_id !== p.active_revision_id
              && attempt.compilation_status !== 'COMPILED'
              ? attempt : null;
            return (
              <div className="page">
                <div className="page-head">
                  <div>
                    <h2>Design intent</h2>
                    <p className="muted">
                      Edit the guided inputs; the compiler owns the derived
                      fabric. Changes mark the revision dirty until a new
                      compile returns.
                    </p>
                  </div>
                  <div className="head-actions">
                    <Link
                      className="btn"
                      to={`/projects/${projectId}/workload`}
                    >
                      Declared workload catalog
                    </Link>
                  </div>
                </div>
                <DesignEditor
                  projectId={projectId}
                  request={(d.request ?? {}) as Record<string, unknown>}
                  draftDesignHash={d.design_hash}
                  draftDirty={p.draft.dirty}
                  activeDesign={active?.design ?? null}
                  activeDisplayName={active?.display_name ?? null}
                  certifiedRevisionId={
                    active && active.compilation.status === 'COMPILED'
                      ? active.revision_id : null
                  }
                  latestRefusal={refused}
                  draftMatchesAttempt={Boolean(
                    refused && d.design_hash === refused.design_hash)}
                  onChanged={reloadAll}
                />
              </div>
            );
          }}
        </AsyncView>
      )}
    </AsyncView>
  );
}

// ── Compile (02) / Verify (03) ───────────────────────────────────────

/** Fetches the revision's canonical artifact chain (§14). A 409 (never
 * compiled) renders as an explicit absence, not an empty chain. */
function ArtifactChainSection({ revisionId }: {
  revisionId: string;
}): ReactElement {
  const chain = useAsync(() => api.artifactChain(revisionId), [revisionId]);
  return (
    <section className="card">
      <h3>Artifact chain</h3>
      {chain.result.state === 'ready' ? (
        <ArtifactChain chain={chain.result.data} />
      ) : chain.result.state === 'error' ? (
        <p className="muted">
          No artifact chain is available for this revision: it never compiled,
          so no canonical artifacts exist.
        </p>
      ) : (
        <p className="muted">Loading…</p>
      )}
    </section>
  );
}

/** Shared state banner: the active revision's compilation verdict plus the
 * newer refused attempt, if any. Both Compile and Verify read it. */
function useActiveRefused(p: ProjectView): {
  active: ProjectView['active_revision'];
  refused: ProjectView['latest_attempt'];
} {
  const active = p.active_revision;
  const attempt = p.latest_attempt;
  const refused = attempt
    && attempt.revision_id !== p.active_revision_id
    && attempt.compilation_status !== 'COMPILED'
    ? attempt : null;
  return { active, refused };
}

/** 02 · Compile: the linked artifact graph the compiler derived. */
export function Compile({ projectId }: { projectId: string }): ReactElement {
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
        const { active, refused } = useActiveRefused(p);
        return (
          <div className="page">
            <div className="page-head">
              <div>
                <h2>Canonical compilation</h2>
                <p className="muted">
                  The product is the linked artifact graph, not a simulator
                  config. Identity and derived semantics come from the
                  CompilationView — never recomputed here.
                </p>
              </div>
              <div className="head-actions">
                <Link
                  className="btn"
                  to={`/projects/${projectId}/design`}
                >
                  Edit intent
                </Link>
                <button
                  className="btn btn-primary"
                  disabled={compiling}
                  onClick={compile}
                >
                  {compiling ? 'Compiling…' : 'Compile revision'}
                </button>
                {active && (
                  <Link
                    className="btn btn-primary"
                    to={`/projects/${projectId}/verify`}
                  >
                    Verify fabric
                  </Link>
                )}
              </div>
            </div>
            {p.draft.dirty && (
              <div className="verdict-banner verdict-unsupported" role="status">
                <span className="verdict-text">
                  <strong>Draft has uncompiled changes.</strong> The materialized
                  artifacts below belong to {active?.display_name ?? 'an earlier revision'};
                  compile to materialize the edited intent.
                </span>
              </div>
            )}
            {error && <ErrorBox error={error} />}
            {refused && (
              <div className="verdict-banner verdict-unsupported" role="alert">
                <StatusBadge status={refused.compilation_status} />
                <span className="verdict-text">
                  <strong>Fabric not materialized · attempt {refused.display_name}.</strong>{' '}
                  {refused.error ?? 'Compilation refused.'} No topology,
                  routing, VC assignment or certificate exists for this
                  attempt.
                  {active
                    ? ` The certified revision ${active.display_name} remains active.`
                    : ''}
                </span>
              </div>
            )}
            {active ? (
              <>
                <div className={`verdict-banner verdict-${(active.compilation.status ?? '').toLowerCase()}`}>
                  <StatusBadge status={active.compilation.status} />
                  <span className="verdict-text">
                    {active.compilation.status === 'COMPILED'
                      ? `Compiled — design ${active.display_name}.`
                      : active.compilation.error ?? 'Refused.'}
                  </span>
                </div>
                <ArtifactChainSection revisionId={active.revision_id} />
                <div className="overview-grid">
                  <section className="card">
                    <h3>Identity</h3>
                    <div className="kv"><span>design identity</span><Hash value={active.design_hash} /></div>
                    <div className="kv"><span>compiler semantics</span>
                      <span>v{active.design.schema_version ?? '—'}</span>
                    </div>
                    <div className="kv"><span>resolved fabric</span>
                      <Hash value={active.compilation.resolved_fabric_hash} />
                    </div>
                    <div className="kv"><span>certificate identity</span>
                      <Hash value={active.compilation.certificate_id} />
                    </div>
                  </section>
                  <section className="card">
                    <h3>Derived network semantics</h3>
                    <div className="kv"><span>routing</span>
                      <span>{active.design.locked_derived?.routing ?? '—'} · compiler-owned</span>
                    </div>
                    <div className="kv"><span>VC count</span>
                      <span>{active.design.locked_derived?.vc_count ?? '—'} · derived</span>
                    </div>
                    <div className="kv"><span>topology family</span>
                      <span>{String(active.design.noc_guided.topology_family ?? '—')}</span>
                    </div>
                    <div className="kv"><span>link width</span>
                      <span>{String(active.design.noc_guided.link_width ?? '—')} bits</span>
                    </div>
                  </section>
                </div>
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

/** 03 · Verify: the certificate, obligation by obligation. */
export function Verify({ projectId }: { projectId: string }): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const { active, refused } = useActiveRefused(p);
        const obs = active?.compilation.obligations ?? [];
        return (
          <div className="page">
            <div className="page-head">
              <div>
                <h2>Verification certificate</h2>
                <p className="muted">
                  Prove the fabric before asking it for performance. Every
                  obligation carries its own method and evidence; a failed
                  gate closes downstream claims.
                </p>
              </div>
              <div className="head-actions">
                <Link
                  className={`btn ${active?.certificate?.overall === 'PASS'
                    ? 'btn-primary' : ''}`}
                  to={`/projects/${projectId}/simulate`}
                >
                  Evaluate workload
                </Link>
              </div>
            </div>
            {refused && (
              <div className="verdict-banner verdict-unsupported" role="alert">
                <StatusBadge status={refused.compilation_status} />
                <span className="verdict-text">
                  <strong>No certificate · attempt {refused.display_name} was
                  refused.</strong> {refused.error ?? ''}
                </span>
              </div>
            )}
            {active ? (
              <>
                <div className="overview-grid">
                  <section className="card">
                    <h3>Certificate</h3>
                    <p className="next-action-large">
                      {active.certificate?.overall ?? '—'}
                    </p>
                    <div className="kv"><span>identity</span>
                      <Hash value={active.compilation.certificate_id} />
                    </div>
                  </section>
                  <section className="card">
                    <h3>Obligations</h3>
                    <p className="next-action-large">
                      {obs.filter((o) => o.status === 'PASS').length} / {obs.length}
                    </p>
                    <p className="muted">required gates satisfied</p>
                  </section>
                  <section className="card">
                    <h3>Deadlock analysis</h3>
                    <p className="next-action-large">
                      {obs.find((o) => o.obligation === 'DEADLOCK_FREE')?.status
                        ?? '—'}
                    </p>
                    <p className="muted">channel-VC dependency graph</p>
                  </section>
                </div>
                <h3>Certificate obligations</h3>
                <VerifyView compilation={active.compilation} />
              </>
            ) : (
              <p className="muted">No compiled revision to verify yet.</p>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

// ── Simulate ──────────────────────────────────────────────────────────────

function PreflightPanel({ revisionId, onReady }: {
  revisionId: string;
  onReady?: (ready: boolean) => void;
}): ReactElement {
  const preflight = useAsync(() => api.preflight(revisionId), [revisionId]);
  const reported = useRef(false);
  return (
    <AsyncView result={preflight.result} reload={preflight.reload}>
      {(pf) => {
        if (!reported.current) {
          reported.current = true;
          onReady?.(pf.ready);
        }
        return (
          <>
            <h3>{pf.ready ? 'Ready to run' : 'Cannot run'}</h3>
            <div className="kv"><span>revision</span>
              <span>{pf.display_name ?? pf.revision_id}</span>
            </div>
            <div className="kv"><span>backend</span><span>{pf.backend}</span></div>
            {pf.backend_profile && (
              <div className="kv"><span>profile</span><span>{pf.backend_profile}</span></div>
            )}
            <div className="kv"><span>producer</span>
              <span>{pf.gates.find((g) => g.gate === 'producer_qualification')?.state ?? '—'}</span>
            </div>
            <div className="kv"><span>network clock</span>
              <span>{(pf.network_clock_hz / 1e6).toFixed(0)} GHz</span>
            </div>
            {pf.ready && pf.expected_evidence_tier && (
              <div className="kv"><span>expected evidence</span>
                <span className="muted">{pf.expected_evidence_tier}</span>
              </div>
            )}
            <div className="kv"><span>route observation</span>
              <span>{pf.route_observation_required ? 'required' : '—'}</span>
            </div>
            <div className="kv"><span>conservation</span>
              <span>{pf.conservation_required ? 'required' : '—'}</span>
            </div>
            {pf.gates.filter((g) => g.reason).map((g) => (
              <div className="blocker" key={g.gate} role="status">
                <strong>{g.gate}: {g.state}</strong>
                <p className="bad">{g.reason}</p>
              </div>
            ))}
          </>
        );
      }}
    </AsyncView>
  );
}

export function Simulate({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const [preflightReady, setPreflightReady] = useState<boolean | null>(null);

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
        const blocker = (() => {
          if (!current) {
            return {
              text: 'No compiled revision exists yet.',
              section: 'design', label: 'Go to Design',
            };
          }
          if (current.compilation.status !== 'COMPILED') {
            return {
              text: current.compilation.error
                ?? 'Compilation was refused for this revision.',
              section: 'design', label: 'Fix design and compile',
            };
          }
          if (current.certificate?.overall !== 'PASS') {
            return {
              text: 'The verification certificate is not PASS.',
              section: 'compile', label: 'Inspect verification',
            };
          }
          if (p.draft.dirty) {
            return {
              text: `The draft has uncompiled changes. The active revision is ${current.display_name}; compile to evaluate the new intent.`,
              section: 'design', label: 'Recompile draft',
            };
          }
          return null;
        })();
        const canRun = Boolean(current)
          && current!.compilation.status === 'COMPILED'
          && current!.certificate?.overall === 'PASS'
          && !p.draft.dirty && !running
          // The server's preflight verdict is the final gate; the local
          // checks only decide whether a preflight can exist at all.
          && preflightReady !== false;
        return (
          <div className="page">
            <h2>Evaluate</h2>
            <p className="muted flow-lede">
              Lower declared communication, execute it, then judge
              requirements. Execution evidence and requirement authority
              remain separate from this UI.
            </p>
            <div className="flow-rail">
              <div className="flow-node"><span className="n">01</span><b>Declared workload</b><small>collectives + dependencies</small></div>
              <div className="flow-node"><span className="n">02</span><b>Logical messages</b><small>participant semantics</small></div>
              <div className="flow-node"><span className="n">03</span><b>Physical traffic</b><small>rank → endpoint bound</small></div>
              <div className="flow-node"><span className="n">04</span><b>Qualified backend</b><small>pinned producer identity</small></div>
              <div className="flow-node"><span className="n">05</span><b>Evidence + report</b><small>metrics + requirements</small></div>
            </div>
            <section className="card">
              {current && !p.draft.dirty ? (
                <PreflightPanel
                  revisionId={current.revision_id}
                  onReady={setPreflightReady}
                />
              ) : (
                <h3>Run configuration</h3>
              )}
              {!current && (
                <div className="kv"><span>revision</span><span>—</span></div>
              )}
              <div className="kv"><span>workload</span><span>{p.draft.workload_id ?? '—'}</span></div>
              <div className="form-row">
                <button
                  className="btn btn-primary"
                  disabled={!canRun}
                  onClick={start}
                >
                  {running ? 'Running…' : 'Run Simulation'}
                </button>
              </div>
              {blocker && (
                <div className="blocker" role="status">
                  <strong>Cannot run yet</strong>
                  <p className={
                    current && current.compilation.status !== 'COMPILED'
                      ? 'bad' : 'muted'
                  }>
                    {blocker.text}
                  </p>
                  <Link
                    className="btn"
                    to={`/projects/${p.project.project_id}/${blocker.section}`}
                  >
                    {blocker.label}
                  </Link>
                </div>
              )}
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
                    <Link className="link" to={`/runs/${runId}`}>
                      {run.result.data.display_name ?? runId}
                    </Link>
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
