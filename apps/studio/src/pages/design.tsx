import { useState, type ReactElement } from 'react';
import { api, type ProjectView } from '../api';
import { navigate } from '../router';
import {
  AsyncView, ErrorBox, Link, useAsync, useStudio,
} from '../studio';
import { StatusBadge } from '../components/badges';
import DesignViewV2Editor, {
  READINESS_LABEL, WORKBENCH_GROUPS, GROUP_LABELS, sectionGroup, groupForOwner,
  type WorkbenchGroup,
} from '../components/DesignViewV2Editor';
import ScenarioStack from '../components/ScenarioStack';
import DesignReviewV2 from '../components/DesignReviewV2';
import CompileResultViewPanel from '../components/CompileResultView';

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
      {(p) => (
        <AsyncView result={view.result} reload={view.reload}>
          {(v) => (
            <AsyncView result={draft.result} reload={draft.reload}>
              {(d) => {
                const base = (doc
                  ?? (d.request ?? {})) as Record<string, unknown>;
                const dirty = JSON.stringify(base)
                  !== JSON.stringify(d.request ?? {});
                const goToGroup = (group: WorkbenchGroup): void => {
                  const target = v.sections.find(
                    (s) => sectionGroup(s) === group) ?? v.sections[0];
                  if (target) setSectionId(target.id);
                };
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
                const goToOwner = (owner: string): void => {
                  const group = groupForOwner(owner);
                  const target = v.sections.find(
                    (s) => sectionGroup(s) === group) ?? v.sections[0];
                  if (target) setSectionId(target.id);
                };
                const activeGroup = (() => {
                  const current = v.sections.find((s) => s.id === sectionId);
                  return current ? sectionGroup(current) : 'system';
                })();
                return (
                  <div className="page">
                    <style>{`.action-sticky{position:sticky;bottom:0;background:var(--bg);padding:12px 0;z-index:5}`}</style>
                    <div className="page-head">
                      <div>
                        <h2>Design intent</h2>
                        <p className="muted">
                          Three layers: intent you author, what it means for
                          analysis, and what the compiler derived — never mixed.
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

                    <ScenarioStack
                      projectId={projectId}
                      doc={base}
                      workloadId={p.draft.workload_id ?? null}
                      activeRevisionId={p.active_revision_id}
                      onEditGroup={goToGroup}
                    />

                    <h3 className="advanced-intent-head">Advanced system intent</h3>
                    <p className="muted">
                      Every field the schema accepts — memory addressing,
                      clock and power domains, interfaces, physical
                      hierarchy, custom metadata.
                    </p>
                    <nav className="workbench-groups" aria-label="Design workbench groups">
                      {WORKBENCH_GROUPS.map((group) => {
                        const count = v.sections.filter(
                          (s) => sectionGroup(s) === group).length;
                        if (count === 0) return null;
                        return (
                          <button
                            key={group}
                            className={`workbench-group${group === activeGroup ? ' active' : ''}`}
                            aria-current={group === activeGroup ? 'true' : undefined}
                            onClick={() => {
                              const first = v.sections.find(
                                (s) => sectionGroup(s) === group);
                              if (first) setSectionId(first.id);
                            }}
                          >
                            {GROUP_LABELS[group]}
                            <span className="muted"> · {count}</span>
                          </button>
                        );
                      })}
                    </nav>

                    <DesignViewV2Editor
                      view={v}
                      doc={base}
                      onDocChange={setDoc}
                      onGoToSection={goToOwner}
                      sectionId={sectionId}
                      onSectionChange={setSectionId}
                      projectId={projectId}
                    />

                    <footer className="review-actions action-sticky">
                      <button className="btn" disabled={saving || !dirty}
                              onClick={save}>
                        {saving ? 'Saving…' : 'Save draft'}
                      </button>
                      {dirty
                        ? <span className="stale">UNCOMPILED CHANGES</span>
                        : <span className="muted">No unsaved changes.</span>}
                    </footer>
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
              {(d) => {
                const goToOwner = (owner: string): void => {
                  const group = groupForOwner(owner);
                  const target = v.sections.find(
                    (s) => sectionGroup(s) === group) ?? v.sections[0];
                  if (target) setSectionId(target.id);
                };
                return (
                <div className="page">
                  <DesignReviewV2
                    view={v}
                    doc={(d.request ?? {}) as Record<string, unknown>}
                    compiling={compiling}
                    onCompile={compile}
                    onBack={() => navigate(`/projects/${projectId}/design`)}
                    onRefresh={reloadAll}
                    onGoToSection={goToOwner}
                    sectionId={sectionId}
                    onSectionChange={setSectionId}
                  />
                  {error && <ErrorBox error={error} />}
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
                  Seven inspectors over one compiled revision, frozen at
                  certification time.
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
              <CompileResultSection projectId={projectId}
                                    revisionId={active.revision_id} />
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

function CompileResultSection({ projectId, revisionId, variant }: {
  projectId: string;
  revisionId: string;
  variant?: 'compile' | 'verify';
}): ReactElement {
  const result = useAsync(
    () => api.compileResult(revisionId), [revisionId]);
  return (
    <AsyncView result={result.result} reload={result.reload}>
      {(view) => (
        <CompileResultViewPanel result={view} revisionId={revisionId}
                                projectId={projectId} variant={variant} />
      )}
    </AsyncView>
  );
}

export function Verify({ projectId }: { projectId: string }): ReactElement {
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
                  Four product claims over the obligations the verifier
                  issued — both shown.
                </p>
              </div>
              <div className="head-actions">
                <Link className="btn"
                      to={`/projects/${projectId}/simulate`}>
                  Evaluate workload
                </Link>
              </div>
            </div>
            <CompileResultSection projectId={projectId}
                                    revisionId={active.revision_id}
                                    variant="verify" />
          </div>
        );
      }}
    </AsyncView>
  );
}

