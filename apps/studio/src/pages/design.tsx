import { useRef, useState, type ReactElement } from 'react';
import { api, type JobView, type ProjectView } from '../api';
import { navigate } from '../router';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync,
  useJobPoll, useStudio,
} from '../studio';
import { Hash, StatusBadge } from '../components/badges';
import DesignViewV2Editor, {
  READINESS_LABEL,
} from '../components/DesignViewV2Editor';
import DesignReviewV2 from '../components/DesignReviewV2';
import CompileResultViewPanel from '../components/CompileResultView';
import EvaluateView from '../components/EvaluateView';

export function Design({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const view = useAsync(
    () => api.design(projectId, { presentation: 'edit' }),
    [projectId],
  );
  const draft = useAsync(() => api.draft(projectId), [projectId]);
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [sectionId, setSectionId] = useState('system');

  const reloadAll = (): void => {
    project.reload();
    view.reload();
    draft.reload();
    refreshProjects();
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {() => (
        <AsyncView result={view.result} reload={view.reload}>
          {(v) => (
            <AsyncView result={draft.result} reload={draft.reload}>
              {(d) => {
                // The canonical draft document is the thing being edited.
                // DesignViewV2 owns the structure, labels, exposure,
                // findings and readiness (Gate 7 §51).
                const base = (doc
                  ?? (d.request ?? {})) as Record<string, unknown>;
                const dirty = JSON.stringify(base)
                  !== JSON.stringify(d.request ?? {});
                const save = async (): Promise<void> => {
                  setSaving(true);
                  setError(null);
                  try {
                    await api.putDraft(projectId, base);
                    setDoc(null);
                    reloadAll();
                  } catch (err) {
                    setError(err instanceof Error ? err : new Error(String(err)));
                  } finally {
                    setSaving(false);
                  }
                };
                return (
                  <div className="page">
                    <div className="page-head">
                      <div>
                        <h2>Design intent</h2>
                        <p className="muted">
                          Edit accepted intent; the compiler owns every derived
                          value. Sections, disclosure depth and findings come
                          from the backend projection.
                        </p>
                      </div>
                      <div className="head-actions">
                        <Link className="btn" to={`/projects/${projectId}/review`}>
                          Review Design →
                        </Link>
                      </div>
                    </div>

                    <div className={`readiness readiness-${v.readiness.toLowerCase()}`}>
                      {READINESS_LABEL[v.readiness]}
                    </div>

                    <DesignViewV2Editor
                      view={v}
                      doc={base}
                      onDocChange={setDoc}
                      onGoToSection={(owner) => setSectionId(owner)}
                      sectionId={sectionId}
                      onSectionChange={setSectionId}
                    />

                    <div className="form-row">
                      <button className="btn" disabled={saving || !dirty}
                              onClick={save}>
                        {saving ? 'Saving…' : 'Save draft'}
                      </button>
                      {dirty && <span className="stale">UNCOMPILED CHANGES</span>}
                    </div>
                    {error && <ErrorBox error={error} />}
                    <p className="muted">
                      Compiling happens from Review, which binds the compile to
                      the snapshot you reviewed.
                    </p>
                  </div>
                );
              }}
            </AsyncView>
          )}
        </AsyncView>
      )}
    </AsyncView>
  );
}

export function Review({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const view = useAsync(
    () => api.design(projectId, { presentation: 'review' }),
    [projectId],
  );
  const draft = useAsync(() => api.draft(projectId), [projectId]);
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [sectionId, setSectionId] = useState('system');

  const reloadAll = (): void => {
    project.reload();
    view.reload();
    draft.reload();
    refreshProjects();
  };

  const compile = async (): Promise<void> => {
    const snapshot = view.result.state === 'ready'
      ? view.result.data.draft_identity.draft_design_hash : null;
    setCompiling(true);
    setError(null);
    try {
      // The reviewed snapshot binds the compile: a mismatch is refused as
      // STALE_REVIEW rather than certifying unseen content (REV-D2).
      await api.compile(projectId, snapshot);
      reloadAll();
      navigate(`/projects/${projectId}/compile`);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      reloadAll();
    } finally {
      setCompiling(false);
    }
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {() => (
        <AsyncView result={view.result} reload={view.reload}>
          {(v) => (
            <AsyncView result={draft.result} reload={draft.reload}>
              {(d) => (
                <div className="page">
                  <DesignReviewV2
                    view={v}
                    doc={(d.request ?? {}) as Record<string, unknown>}
                    compiling={compiling}
                    onCompile={compile}
                    onBack={() => navigate(`/projects/${projectId}/design`)}
                    onRefresh={reloadAll}
                    onGoToSection={(owner) => setSectionId(owner)}
                    sectionId={sectionId}
                    onSectionChange={setSectionId}
                  />
                  {error && <ErrorBox error={error} />}
                </div>
              )}
            </AsyncView>
          )}
        </AsyncView>
      )}
    </AsyncView>
  );
}

// ── Compile (02) / Verify (03) ───────────────────────────────────────

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
  const project = useAsync(() => api.project(projectId), [projectId]);

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const { active, refused } = useActiveRefused(p);
        return (
          <div className="page">
            <div className="page-head">
              <div>
                <h2>Compile result</h2>
                <p className="muted">
                  Seven inspector groups over one compiled revision. The
                  payload is frozen at certification time — nothing here is
                  re-derived from the request.
                </p>
              </div>
              <div className="head-actions">
                <Link className="btn" to={`/projects/${projectId}/design`}>
                  Edit design
                </Link>
                {active && (
                  <Link className="btn" to={`/projects/${projectId}/review`}>
                    Review design
                  </Link>
                )}
              </div>
            </div>

            {p.draft.dirty && (
              <div className="verdict-banner verdict-unsupported" role="status">
                <span className="verdict-text">
                  <strong>Draft has uncompiled changes.</strong> The
                  artifacts below belong to{' '}
                  {active?.display_name ?? 'an earlier revision'}; compile
                  from Review to materialize the edited intent.
                </span>
              </div>
            )}
            {refused && (
              <div className="verdict-banner verdict-unsupported" role="alert">
                <StatusBadge status={refused.compilation_status} />
                <span className="verdict-text">
                  <strong>
                    Fabric not materialized · attempt {refused.display_name}.
                  </strong>{' '}
                  {refused.error ?? 'Compilation refused.'} No topology,
                  routing, VC assignment or certificate exists for this
                  attempt.
                  {active
                    ? ` The certified revision ${active.display_name} remains active.`
                    : ''}
                </span>
              </div>
            )}

            {active && active.compilation.status === 'COMPILED' ? (
              <CompileResultSection revisionId={active.revision_id} />
            ) : active ? (
              <div className={`verdict-banner verdict-${(active.compilation.status ?? '').toLowerCase()}`}>
                <StatusBadge status={active.compilation.status} />
                <span className="verdict-text">
                  {active.compilation.error ?? 'Refused.'}
                </span>
              </div>
            ) : (
              <p className="muted">
                No compiled revision yet. Compile from Review — the reviewed
                snapshot binds the compile, so unseen content is never
                certified.
              </p>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

/** The CompileResultView payload, fetched per revision. A revision that
 * never compiled has no inspectors. */
function CompileResultSection({ revisionId }: {
  revisionId: string;
}): ReactElement {
  const result = useAsync(
    () => api.compileResult(revisionId), [revisionId]);
  return (
    <AsyncView result={result.result} reload={result.reload}>
      {(view) => (
        <CompileResultViewPanel result={view} revisionId={revisionId} />
      )}
    </AsyncView>
  );
}

export function Verify({ projectId }: { projectId: string }): ReactElement {
  // Verification is the certificate inside the Compile Result — the same
  // projection, not a second model of it (Gate 8 §50: not one page per
  // artifact). `/verify` stays a live deep link into that surface.
  const project = useAsync(() => api.project(projectId), [projectId]);
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const { active } = useActiveRefused(p);
        if (!active || active.compilation.status !== 'COMPILED') {
          return (
            <div className="page">
              <h2>Verification certificate</h2>
              <p className="muted">
                No certificate exists. A certificate is issued only for a
                compiled revision, and a failed proof is not a fabric.
              </p>
              <Link className="btn" to={`/projects/${projectId}/review`}>
                Review design
              </Link>
            </div>
          );
        }
        return (
          <div className="page">
            <div className="page-head">
              <div>
                <h2>Verification certificate</h2>
                <p className="muted">
                  Every claim carries its own scope and method. The four
                  product claims are a subset of the obligations the
                  verifier issued — both are shown.
                </p>
              </div>
              <div className="head-actions">
                <Link className="btn"
                      to={`/projects/${projectId}/simulate`}>
                  Evaluate workload
                </Link>
              </div>
            </div>
            <CompileResultSection revisionId={active.revision_id} />
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
