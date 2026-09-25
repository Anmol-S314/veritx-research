import { useEffect, useState, type ReactElement } from 'react';
import { api, type RunView } from '../api';
import {
  AsyncView, Link, WorkflowBar, useAsync, useStudio,
} from '../studio';
import { Hash, StatusBadge, fmtNum, humanize } from '../components/badges';
import { navigate } from '../router';

function nextActionTarget(action: string): { label: string; section: string } {
  switch (action) {
    case 'COMPILE':
      return { label: 'Compile design', section: 'design' };
    case 'EDIT_DRAFT':
      return { label: 'Fix design', section: 'design' };
    case 'INSPECT_VERIFY':
      return { label: 'Inspect verification', section: 'compile' };
    case 'RUN_EVALUATION':
      return { label: 'Run simulation', section: 'simulate' };
    case 'COMPARE_OR_OPTIMIZE':
      return { label: 'Compare / optimize', section: 'decide' };
    case 'WAIT':
      return { label: 'View progress', section: 'simulate' };
    default:
      return { label: 'Open design', section: 'design' };
  }
}

export function ProjectPicker(): ReactElement {
  const { projects, projectsError, refreshProjects } = useStudio();
  const [name, setName] = useState('');
  const [nameTouched, setNameTouched] = useState(false);
  const [workloadId, setWorkloadId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const catalog = useAsync(api.workloadCatalog, []);

  useEffect(() => {
    if (catalog.result.state === 'ready' && !workloadId) {
      setWorkloadId(catalog.result.data.workloads[0]?.workload_id ?? '');
    }
  }, [catalog.result, workloadId]);

  // The project name defaults to the selected workload so the header
  // never pairs a project with an unrelated workload. Typing a name
  // keeps it; switching workload re-derives it until then.
  const pickWorkload = (nextId: string): void => {
    setWorkloadId(nextId);
    if (nameTouched || catalog.result.state !== 'ready') return;
    const entry = catalog.result.data.workloads.find(
      (w) => w.workload_id === nextId,
    );
    if (entry) {
      setName(`${entry.display_name.split('·')[0].trim()} Study`);
    }
  };

  const create = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject(
        name.trim() || 'New Interconnect Study',
        workloadId || undefined,
      );
      refreshProjects();
      navigate(`/projects/${project.project.project_id}/workload`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const rename = async (projectId: string,
                        currentName: string): Promise<void> => {
    const next = window.prompt('Project name', currentName);
    if (next === null || !next.trim()) return;
    setError(null);
    try {
      await api.renameProject(projectId, next.trim());
      refreshProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const remove = async (projectId: string,
                        projectName: string): Promise<void> => {
    if (!window.confirm(
      `Delete project "${projectName}" and all its revisions, runs and `
      + 'optimization studies? This cannot be undone.')) {
      return;
    }
    setError(null);
    try {
      await api.deleteProject(projectId);
      refreshProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="page">
      <h2>Projects</h2>
      {projectsError && <p className="bad">{projectsError}</p>}
      {projects.length > 0 && (
        <ul className="project-list">
          {projects.map((p) => (
            <li className="project-row" key={p.project.project_id}>
              <Link
                className="project-item"
                to={`/projects/${p.project.project_id}/overview`}
              >
                <span className="project-name">{p.project.name}</span>
                <span className={`flow flow-${p.flow.state.toLowerCase()}`}>
                  {p.flow.state}
                </span>
                <span className="muted">
                  {p.revisions.length} revisions · {p.runs.length} runs
                </span>
              </Link>
              <div className="project-actions">
                <button
                  className="btn"
                  onClick={() => rename(p.project.project_id, p.project.name)}
                >
                  Rename
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => remove(p.project.project_id, p.project.name)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <section className="card">
        <h3>New project</h3>
        <div className="form-row">
          <label>
            Name
            <input
              value={name}
              placeholder="New Interconnect Study"
              onChange={(e) => {
                setName(e.target.value);
                setNameTouched(true);
              }}
            />
          </label>
          <label>
            Workload
            <AsyncView result={catalog.result} reload={catalog.reload}>
              {(data) => (
                <select
                  value={workloadId}
                  onChange={(e) => pickWorkload(e.target.value)}
                >
                  {data.workloads.map((w) => (
                    <option key={w.workload_id} value={w.workload_id}>
                      {w.display_name}
                    </option>
                  ))}
                </select>
              )}
            </AsyncView>
          </label>
          <button className="btn btn-primary" disabled={busy} onClick={create}>
            {busy ? 'Creating…' : 'Create project'}
          </button>
        </div>
        {error && <p className="bad">{error}</p>}
        <p className="muted">
          The chosen workload becomes the project draft; the Workload page can
          switch it at any time (the previous revision stays immutable).
        </p>
      </section>
    </div>
  );
}

export function Overview({ projectId }: { projectId: string }): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const active = p.revisions.find(
          (r) => r.revision_id === p.active_revision_id,
        );
        // Latest run scoped to the active revision: the gateway carries
        // it, with an in-list fallback for older payloads.
        const latest = p.latest_active_run
          ?? [...p.runs]
            .reverse()
            .find((r) => r.revision_id === p.active_revision_id);
        const attempt = p.latest_attempt;
        const refusedAttempt = attempt
          && attempt.revision_id !== p.active_revision_id
          && attempt.compilation_status !== 'COMPILED'
          ? attempt : null;
        return (
          <div className="page">
            <WorkflowBar project={p} current="overview" />
            <div className="overview-grid">
              <section className="card">
                <h3>Current certified fabric</h3>
                {active ? (
                  <>
                    <div className="kv"><span>revision</span><span>{active.display_name}</span></div>
                    <div className="kv"><span>compilation</span><StatusBadge status={active.compilation_status} /></div>
                    <div className="kv"><span>certificate</span><span>{active.certificate_overall ?? '—'}</span></div>
                    <div className="kv"><span>design identity</span><Hash value={active.design_hash} /></div>
                  </>
                ) : (
                  <p className="muted">No certified revision yet.</p>
                )}
              </section>
              <section className="card">
                <h3>Latest run · {active?.display_name ?? '—'}</h3>
                {latest ? (
                  <>
                    <div className="kv"><span>run</span>
                      <Link className="link" to={`/runs/${latest.run_id}`}>
                        {latest.display_name ?? latest.run_id}
                      </Link>
                    </div>
                    <div className="kv"><span>status</span><StatusBadge status={latest.status ?? 'UNKNOWN'} /></div>
                    <div className="kv"><span>completion</span><span>{fmtNum(latest.completion_cycles)} cycles</span></div>
                  </>
                ) : (
                  <p className="muted">No runs for this revision yet.</p>
                )}
              </section>
              <section className="card">
                <h3>Next action</h3>
                <p className="next-action-large">{p.flow.next_action}</p>
                <p className={p.flow.state === 'REFUSED' ? 'bad' : 'muted'}>
                  {p.flow.reason}
                </p>
                {(() => {
                  const target = nextActionTarget(p.flow.next_action);
                  return (
                    <Link
                      className="btn btn-primary"
                      to={`/projects/${projectId}/${target.section}`}
                    >
                      {target.label}
                    </Link>
                  );
                })()}
              </section>
            </div>
            {refusedAttempt && (
              <section className="card">
                <h3>New design refused</h3>
                <div className="kv"><span>attempt</span><span>{refusedAttempt.display_name} · {refusedAttempt.compilation_status.toLowerCase()}</span></div>
                <p className="bad">{refusedAttempt.error ?? 'Compilation refused.'}</p>
                <p className="muted">
                  {active
                    ? `The certified revision ${active.display_name} remains active.`
                    : 'No certified revision exists yet.'}
                </p>
                <Link className="btn" to={`/projects/${projectId}/design`}>
                  Fix design
                </Link>
              </section>
            )}
            {p.optimizations.length > 0 && (              <section className="card">
                <h3>Optimization studies</h3>
                <ul>
                  {p.optimizations.map((o) => (
                    <li key={o.optimization_id}>
                      <Link className="link" to={`/projects/${projectId}/optimize`}>
                        {o.optimization_id}
                      </Link>{' '}
                      · {o.candidate_count} candidates · {o.pareto_count} Pareto · selected {o.selected_candidate_id ?? '—'}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

export function Workload({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const catalog = useAsync(api.workloadCatalog, []);
  const project = useAsync(() => api.project(projectId), [projectId]);
  const select = async (workloadId: string): Promise<void> => {
    await api.selectWorkload(projectId, workloadId);
    project.reload();
    refreshProjects();
    navigate(`/projects/${projectId}/design`);
  };
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => (
        <div className="page">
          <WorkflowBar project={p} current="workload" />
          <h2>Workload</h2>
          <AsyncView result={catalog.result} reload={catalog.reload}>
            {(data) => (
              <div className="workload-cards">
                {data.workloads.map((w) => (
                  <section className="card" key={w.workload_id}>
                    <h3>{w.display_name}</h3>
                    <p className="muted">{w.description}</p>
                    <div className="kv"><span>model family</span><span>{w.model_family}</span></div>
                    <div className="kv"><span>model</span><span>{w.model_name ?? '—'}</span></div>
                    <div className="kv"><span>serving mode</span><span>{w.serving_mode ?? '—'}</span></div>
                    <div className="kv"><span>TP / PP / EP / DP</span>
                      <span>{w.parallelism.tp} / {w.parallelism.pp} / {w.parallelism.ep} / {w.parallelism.dp}</span>
                    </div>
                    <div className="kv"><span>agents</span>
                      <span>{w.agents.map((a) => `${a.count}× ${a.kind}`).join(', ')}</span>
                    </div>
                    <div className="kv"><span>NoC</span>
                      <span>{String(w.noc.topology_family ?? '—')} · link {String(w.noc.link_width ?? '—')}b · conc {String(w.noc.concentration ?? '—')}</span>
                    </div>
                    <div className="kv"><span>source</span><code>{w.source}</code></div>
                    <div className="kv"><span>content digest</span><Hash value={w.content_digest} /></div>
                    <h4>Collectives (declared)</h4>
                    <table className="tbl">
                      <thead><tr><th>kind</th><th>dimension</th><th>payload bytes</th><th>traffic class</th></tr></thead>
                      <tbody>
                        {w.collectives.map((c, i) => (
                          <tr key={i}><td>{c.kind}</td><td>{c.dimension}</td><td>{fmtNum(c.payload_bytes)}</td><td>{c.traffic_class ?? '—'}</td></tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="muted">
                      Logical communication volume is derived by the canonical
                      lowering, not the catalog; request-level editing lives in
                      the Draft (Design page).
                    </p>
                    <div className="form-row">
                      {p.draft.workload_id === w.workload_id ? (
                        <span className="current-badge">
                          In use by this project's draft
                        </span>
                      ) : (
                        <button
                          className="btn btn-primary"
                          onClick={() => select(w.workload_id)}
                        >
                          Use this workload
                        </button>
                      )}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </AsyncView>
        </div>
      )}
    </AsyncView>
  );
}

export function Trust(): ReactElement {
  const qual = useAsync(api.qualification, []);
  return (
    <div className="page">
      <h2>Trust · what VERITX currently trusts</h2>
      <AsyncView result={qual.result} reload={qual.reload}>
        {(data) => (
          <>
            <section className="card">
              <h3>Engine qualification</h3>
              <table className="live-table">
                <thead>
                  <tr><th>engine</th><th>role</th><th>integration</th><th>numerical</th><th>independence</th><th>limitations</th></tr>
                </thead>
                <tbody>
                  {Object.entries(data.engines).map(([name, e]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td className="muted">{e.role}</td>
                      <td>{e.integration}</td>
                      <td className={e.numerical === 'NOT_ESTABLISHED' ? 'bad' : 'good'}>{e.numerical}</td>
                      <td className="muted">{e.independence}</td>
                      <td className="muted">{e.limitations.join('; ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted">
                Source: docs/production/ENGINE-QUALIFICATION.json
                {data.validation_sha ? ` · validation ${data.validation_sha}` : ''}.
                ASTRA integration is QUALIFIED while its numerical timing stays
                NOT ESTABLISHED until the per-domain oracles close.
              </p>
            </section>
            <section className="card">
              <h3>Workload trust levels</h3>
              <ul className="muted">
                {Object.entries(data.workload_levels).map(([k, v]) => (
                  <li key={k}><strong>{k}</strong>: {v}</li>
                ))}
              </ul>
            </section>
          </>
        )}
      </AsyncView>
    </div>
  );
}

export function Runs(): ReactElement {
  const { activeProjectId } = useStudio();
  const [requested, setScope] = useState<'project' | 'all'>(
    activeProjectId ? 'project' : 'all',
  );
  // "This project" falls back to all runs when no project is open, so the
  // scope can never silently show an empty list for a missing project.
  const scope = requested === 'project' && !activeProjectId ? 'all' : requested;
  const runs = useAsync(
    () => (scope === 'project' && activeProjectId
      ? api.runs({ projectId: activeProjectId })
      : api.runs()),
    [scope, activeProjectId],
  );
  // Active revision for the historical tag: runs from older revisions
  // stay visible but are explicitly marked, never mixed silently.
  const project = useAsync(
    () => (scope === 'project' && activeProjectId
      ? api.project(activeProjectId)
      : Promise.reject(new Error('no project scope'))),
    [scope, activeProjectId],
  );
  const activeRev = project.result.state === 'ready'
    ? project.result.data.active_revision_id
    : null;
  return (
    <div className="page">
      <div className="page-head">
        <h2>Runs</h2>
        <div className="segmented small" role="tablist" aria-label="Run scope">
          <button
            role="tab"
            aria-selected={scope === 'project'}
            className={scope === 'project' ? 'selected' : ''}
            disabled={!activeProjectId}
            title={activeProjectId || 'no project open'}
            onClick={() => setScope('project')}
          >
            This project
          </button>
          <button
            role="tab"
            aria-selected={scope === 'all'}
            className={scope === 'all' ? 'selected' : ''}
            onClick={() => setScope('all')}
          >
            All projects
          </button>
        </div>
      </div>
      <AsyncView result={runs.result} reload={runs.reload}>
        {(data) =>
          data.runs.length === 0 ? (
            <p className="muted">
              {scope === 'project'
                ? 'No runs for this project yet.'
                : 'No runs yet.'}
            </p>
          ) : (
            <table className="live-table">
              <thead>
                <tr><th>run</th>{scope === 'all' && <th>project</th>}<th>revision</th><th>workload</th><th>backend</th><th>status</th><th>qualification</th><th>cycles</th></tr>
              </thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.run_id}>
                    <td>
                      <Link className="link" to={`/runs/${r.run_id}`}>
                        {r.display_name ?? r.run_id}
                      </Link>
                    </td>
                    {scope === 'all' && (
                      <td className="muted">{r.project_id}</td>
                    )}
                    <td className="muted">
                      {r.revision_id}
                      {scope === 'project' && activeRev
                        && r.revision_id !== activeRev && (
                        <span className="stale"> · historical</span>
                      )}
                    </td>
                    <td className="muted">{r.workload_id ?? '—'}</td>
                    <td className="muted">{r.backend ?? '—'}</td>
                    <td><StatusBadge status={r.status ?? 'UNKNOWN'} /></td>
                    <td>{r.qualification ?? '—'}</td>
                    <td>{fmtNum(r.completion_cycles)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </AsyncView>
    </div>
  );
}

function TrustDrawer({ run }: { run: RunView }): ReactElement {
  const evidence = useAsync(() => api.evidence(run.run_id), [run.run_id]);
  return (
    <section className="card trust-drawer">
      <h3>Why can I trust this?</h3>
      <div className="kv"><span>Measured by</span><span>{run.backend ?? '—'}</span></div>
      <div className="kv"><span>Qualification</span><span>{run.qualification ?? '—'}</span></div>
      <div className="kv"><span>Producer</span><Hash value={run.producer?.producer_identity} label="sha256" /></div>
      {run.requirements?.entries.map((e, i) => (
        <div className="kv" key={i}>
          <span>{e.traffic_class ?? 'fabric'} requirement</span>
          <span><StatusBadge status={e.verdict} /> {e.reason}</span>
        </div>
      ))}
      <div className="kv"><span>Evidence</span><Hash value={run.evidence?.evidence_id} /></div>
      <div className="kv"><span>Run bundle</span><Hash value={run.bundle_id} /></div>
      <AsyncView result={evidence.result} reload={evidence.reload}>
        {(ev) => (
          <>
            <h4>Evidence artifacts</h4>
            <ul className="artifact-list">
              {ev.artifacts.map((a) => (
                <li key={a.path}><code>{a.path}</code> <span className="muted">{a.size_bytes} B</span></li>
              ))}
            </ul>
            {Object.entries(ev.documents).map(([name, doc]) => (
              <details key={name}>
                <summary>{name}</summary>
                <pre className="evidence">{JSON.stringify(doc, null, 2)}</pre>
              </details>
            ))}
          </>
        )}
      </AsyncView>
    </section>
  );
}

export function RunDetail({ runId }: { runId: string }): ReactElement {
  const run = useAsync(() => api.run(runId), [runId]);
  return (
    <div className="page">
      <div className="page-head">
        <h2>Run detail</h2>
        <div className="head-actions">
          <Link className="btn" to="/runs">All runs</Link>
        </div>
      </div>
      <AsyncView result={run.result} reload={run.reload}>
        {(r) => (
          <>
            <section className="card">
              <h3>{r.display_name ?? r.run_id}</h3>
              <div className="head-actions">
                <Link
                  className="btn"
                  to={`/projects/${r.project_id}/overview`}
                >
                  Open project
                </Link>
              </div>
              <div className="kv"><span>status</span><StatusBadge status={r.status ?? 'UNKNOWN'} /></div>
              {r.qualification_basis && (
                <div className="kv">
                  <span>qualification basis</span>
                  <span className="muted">{r.qualification_basis}</span>
                </div>
              )}
              <div className="kv"><span>revision</span><span>{r.revision_id}</span></div>
              <div className="kv"><span>design_hash</span><Hash value={r.design_hash} /></div>
              <div className="kv"><span>workload</span><span>{r.evaluation?.workload_id ?? '—'}</span></div>
              <div className="kv"><span>backend</span><span>{r.backend ?? '—'}</span></div>
              <div className="kv"><span>producer revision</span><span>{r.backend ?? '—'}</span></div>
              <div className="kv"><span>bundle</span><Hash value={r.bundle_id} /></div>
              {r.reason && <p className="bad">{r.reason}</p>}
            </section>
            {r.evaluation && (
              <section className="card">
                <h3>Measured result</h3>
                {r.evaluation.network_traffic_window && (
                  <div className="kv"><span>completion window</span><span>{fmtNum(r.evaluation.network_traffic_window.window_cycles)} cycles {r.evaluation.network_traffic_window.cycles_only ? '(cycles only)' : ''}</span></div>
                )}
                {r.evaluation.metrics && (
                  <table className="live-table">
                    <thead><tr><th>metric</th><th>value</th></tr></thead>
                    <tbody>
                      {Object.entries(r.evaluation.metrics).map(([k, v]) => (
                        <tr key={k}><td>{humanize(k)}</td><td>{fmtNum(v)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {r.evaluation.fidelity_warning && (
                  <p className="muted">Fidelity: {r.evaluation.fidelity_warning}</p>
                )}
              </section>
            )}
            {r.requirements && (
              <section className="card">
                <h3>Requirements</h3>
                <table className="live-table">
                  <thead><tr><th>class</th><th>verdict</th><th>required</th><th>measured</th><th>authority</th></tr></thead>
                  <tbody>
                    {r.requirements.entries.map((e, i) => (
                      <tr key={i}>
                        <td>{e.traffic_class ?? 'fabric'}</td>
                        <td><StatusBadge status={e.verdict} /></td>
                        <td>{fmtNum(e.required)}</td>
                        <td>{fmtNum(e.measured)}</td>
                        <td className="muted">{e.metric_authority}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
            <TrustDrawer run={r} />
          </>
        )}
      </AsyncView>
    </div>
  );
}
