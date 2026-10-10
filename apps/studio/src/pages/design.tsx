import { useState, type ReactElement } from 'react';
import { api, type ProjectView } from '../api';
import {
  compileResultGroupSegment, navigate, type CompileResultGroup,
} from '../router';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync, useStudio,
} from '../studio';
import { StatusBadge } from '../components/badges';
import DesignViewV2Editor, {
  READINESS_LABEL, sectionGroup, groupForOwner,
  type WorkbenchGroup,
} from '../components/DesignViewV2Editor';
import ScenarioStack from '../components/ScenarioStack';
import DesignReviewV2 from '../components/DesignReviewV2';
import CompileResultViewPanel from '../components/CompileResultView';
import AITopologySearch from '../components/AITopologySearch';
import { useCompileJob } from '../hooks/useCompileJob';
import DesignCanvas from '../components/DesignCanvas';
import ExecutionEvidence from '../components/ExecutionEvidence';

export function Design({ projectId }: { projectId: string }): ReactElement {
  return <DesignEditor key={projectId} projectId={projectId} />;
}

function DesignEditor({ projectId }: { projectId: string }): ReactElement {
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
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [agentIndex, setAgentIndex] = useState(0);

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
                    setDoc(current => current && JSON.stringify(current) !== JSON.stringify(base) ? current : null);
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
                return (
                  <div className="page">
                    <style>{`.action-sticky{position:sticky;bottom:0;background:var(--bg);padding:12px 0;z-index:5}`}</style>
                    <div className="page-head">
                      <div>
                        <h2>Design workspace</h2>
                        <p className="muted">Select an object to edit its settings. Save, review, then compile.</p>
                      </div>
                    </div>

                    <div className={`readiness readiness-${dirty ? 'incomplete' : v.readiness.toLowerCase()}`}>
                      {dirty ? 'Unsaved intent · save to validate · compile checks pending' : READINESS_LABEL[v.readiness]}
                    </div>

                    <div className="design-workspace">
                    <DesignCanvas projectId={projectId} doc={base} onChange={setDoc}
                      onInspect={(group, index) => { if (index !== undefined) setAgentIndex(index); goToGroup(group); }} />
                    <aside className="design-workspace-inspector" aria-label="Design inspector">
                    <DesignViewV2Editor
                      view={v}
                      doc={base}
                      onDocChange={setDoc}
                      selectedAgent={agentIndex}
                      onSelectAgent={setAgentIndex}
                      onGoToSection={goToOwner}
                      sectionId={sectionId}
                      onSectionChange={setSectionId}
                      projectId={projectId}
                    />
                    </aside>
                    </div>

                    <details className="subtle design-analysis-preview" onToggle={event => setTechnicalOpen(event.currentTarget.open)}>
                      <summary>Analysis, execution evidence, and search</summary>
                      {technicalOpen && <>
                    <ExecutionEvidence doc={base} />
                    <AITopologySearch projectId={projectId}
                      draftHash={v.draft_identity.draft_design_hash} saved={!dirty && !saving}
                      onAdopted={() => { setDoc(null); reloadAll(); }} />

                      <ScenarioStack
                        projectId={projectId}
                        doc={base}
                        workloadId={p.draft.workload_id ?? null}
                        activeRevisionId={p.active_revision_id}
                        onEditGroup={goToGroup}
                      />
                      </>}
                    </details>

                    <footer className="review-actions action-sticky">
                      {dirty ? (
                        <button className="btn btn-primary" disabled={saving} onClick={save}>
                          {saving ? 'Saving…' : 'Save draft'}
                        </button>
                      ) : (
                        <Link className="btn btn-primary" to={`/projects/${projectId}/review`}>
                          Review design
                        </Link>
                      )}
                      <span className={dirty ? 'stale' : 'muted'}>
                        {dirty ? 'Unsaved changes' : 'Draft saved · review before compile'}
                      </span>
                    </footer>
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

export function Review({ projectId }: { projectId: string }): ReactElement {
  return <ReviewEditor key={projectId} projectId={projectId} />;
}

function ReviewEditor({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const view = useAsync(
    () => api.design(projectId, { presentation: 'review' }),
    [projectId],
  );
  const draft = useAsync(() => api.draft(projectId), [projectId]);
  const [error, setError] = useState<Error | null>(null);
  const compileJob = useCompileJob(projectId, (job) => {
    reloadAll();
    if (job.state === 'COMPLETED' && job.result?.revision_id) {
      navigate(`/projects/${projectId}/compile`);
    }
  });
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
    setError(null);
    if (!snapshot) { setError(new Error('Wait for Review to load, then retry.')); return; }
    await compileJob.submit(snapshot);
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
                    compiling={compileJob.active}
                    onCompile={compile}
                    onBack={() => navigate(`/projects/${projectId}/design`)}
                    onRefresh={reloadAll}
                    onGoToSection={goToOwner}
                    sectionId={sectionId}
                    onSectionChange={setSectionId}
                  />
                  <JobProgress job={compileJob.job} />
                  {compileJob.error && <ErrorBox error={compileJob.error} onRetry={compileJob.retry} />}
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

export function RevisionCompileGroup({ revisionId, group }: {
  revisionId: string;
  group: CompileResultGroup;
}): ReactElement {
  const revision = useAsync(() => api.revision(revisionId), [revisionId]);
  return (
    <AsyncView result={revision.result} reload={revision.reload}>
      {(r) => (
        <div className="page">
          <div className="page-head">
            <div>
              <h2>{r.display_name}</h2>
              <p className="muted">Revision {r.revision_id}</p>
            </div>
            <div className="head-actions">
              <Link className="btn" to={`/projects/${r.project_id}/compile`}>
                Compile console
              </Link>
            </div>
          </div>
          <CompileResultSection projectId={r.project_id} revisionId={revisionId}
            activeGroup={group} onGroupChange={(selected) => {
              const segment = compileResultGroupSegment(selected);
              if (segment) {
                navigate(`/revisions/${encodeURIComponent(revisionId)}/${segment}`);
              }
            }} />
        </div>
      )}
    </AsyncView>
  );
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
              </div>
              <div className="head-actions">
                <Link className="btn" to={`/projects/${projectId}/design`}>
                  Edit design
                </Link>
              </div>
            </div>

            {p.draft.dirty && (
              <div className="verdict-banner verdict-unsupported" role="status">
                <span className="verdict-text">
                  Draft changed; showing {active?.display_name ?? 'the previous revision'}.{' '}
                  <Link className="link" to={`/projects/${projectId}/review`}>Review draft changes</Link>
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
                revisionId={active.revision_id} onGroupChange={(group) => {
                  const segment = compileResultGroupSegment(group);
                  if (segment) {
                    navigate(`/revisions/${encodeURIComponent(active.revision_id)}/${segment}`);
                  }
                }} />
            ) : active ? (
              <div className={`verdict-banner verdict-${(active.compilation.status ?? '').toLowerCase()}`}>
                <StatusBadge status={active.compilation.status} />
                <span className="verdict-text">
                  {active.compilation.error ?? 'Refused.'}
                </span>
              </div>
            ) : (
              <p className="muted">
                No compiled revision yet.{' '}
                <Link className="link" to={`/projects/${projectId}/review`}>Review and compile the draft</Link>
              </p>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

function CompileResultSection({ projectId, revisionId, variant, activeGroup,
  onGroupChange }: {
  projectId: string;
  revisionId: string;
  variant?: 'compile' | 'verify';
  activeGroup?: CompileResultGroup;
  onGroupChange?: (group: string) => void;
}): ReactElement {
  const result = useAsync(
    () => api.compileResult(revisionId), [revisionId]);
  return (
    <AsyncView result={result.result} reload={result.reload}>
      {(view) => (
        <CompileResultViewPanel result={view} revisionId={revisionId}
          projectId={projectId} variant={variant} activeGroup={activeGroup}
          onGroupChange={onGroupChange} />
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

