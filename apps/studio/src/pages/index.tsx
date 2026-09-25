import { useEffect, useState, type ReactElement } from 'react';
import {
  api,
  type JobView,
  type RunIntegrityView,
  type RunView,
  type RunVerifyView,
  type ValidationExperiment,
  type WorkloadLoweringView,
} from '../api';
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

/** Lowering inspector for one workload card: the real canonical chain
 * workload → collectives → logical-message flows, from the backend's
 * WorkloadLoweringView. Participant-level (rank-space) structure only;
 * physical traffic appears after lowering to a fabric, inside runs. */
function WorkloadLowering({ workloadId }: {
  workloadId: string;
}): ReactElement {
  const lowering = useAsync(
    () => api.workloadLowering(workloadId),
    [workloadId],
  );
  const [view, setView] = useState<'collectives' | 'flows'>('collectives');
  return (
    <details className="lowering-inspect">
      <summary>Inspect lowering chain</summary>
      <AsyncView result={lowering.result} reload={lowering.reload}>
        {(v: WorkloadLoweringView) => (
          <>
            <div className="kv">
              <span>message artifact</span>
              <Hash value={v.message_artifact_id} />
            </div>
            <div className="kv">
              <span>participants</span>
              <span>{v.participant_count} ranks · traffic class {v.traffic_class}</span>
            </div>
            <div className="segmented small" role="tablist" aria-label="Lowering detail">
              <button
                role="tab"
                aria-selected={view === 'collectives'}
                className={view === 'collectives' ? 'selected' : ''}
                onClick={() => setView('collectives')}
              >
                Collectives ({v.totals.collectives})
              </button>
              <button
                role="tab"
                aria-selected={view === 'flows'}
                className={view === 'flows' ? 'selected' : ''}
                onClick={() => setView('flows')}
              >
                Message flows ({v.totals.flows})
              </button>
            </div>
            {view === 'collectives' ? (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>collective</th><th>kind</th><th>algorithm</th>
                    <th>k</th><th>payload</th><th>steps</th>
                    <th>messages</th><th>msg bytes</th><th>aggregate</th>
                  </tr>
                </thead>
                <tbody>
                  {v.collectives.map((s) => (
                    <tr key={s.collective_id}>
                      <td><code>{s.collective_id}</code></td>
                      <td>{s.kind}</td>
                      <td className="muted">{s.algorithm}</td>
                      <td className="num">{s.k}</td>
                      <td className="num">{fmtNum(s.payload_bytes)} B</td>
                      <td className="num">{s.steps}</td>
                      <td className="num">{s.message_count}</td>
                      <td className="num">{fmtNum(s.message_bytes)} B</td>
                      <td className="num">{fmtNum(s.aggregate_payload)} B</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <>
                <p className="muted">
                  Per-step logical messages aggregated per source →
                  destination pair ({v.totals.messages} messages total,
                  conserved by construction). Rank space — physical
                  traffic exists only after lowering to a certified fabric,
                  inside a run.
                </p>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>operation</th><th>src</th><th>dst</th>
                      <th>class</th><th>messages</th><th>payload</th>
                    </tr>
                  </thead>
                  <tbody>
                    {v.flows.map((f, i) => (
                      <tr key={i}>
                        <td><code>{f.operation_id}</code></td>
                        <td className="num">{f.src_rank}</td>
                        <td className="num">{f.dst_rank}</td>
                        <td className="muted">{f.traffic_class}</td>
                        <td className="num">{f.message_count}</td>
                        <td className="num">{fmtNum(f.payload_bytes)} B</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </AsyncView>
    </details>
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
                    <WorkloadLowering workloadId={w.workload_id} />
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

// ── Trust: validation campaigns (UX11) ─────────────────────────────────

function CampaignDetail({ experiment }: {
  experiment: ValidationExperiment;
}): ReactElement {
  const fabric = experiment.fabric;
  return (
    <>
      <div className="kv">
        <span>what was tested</span>
        <span>{experiment.title ?? experiment.id}</span>
      </div>
      <div className="kv">
        <span>status</span>
        <span>
          <StatusBadge status={experiment.status ?? 'UNKNOWN'} />
        </span>
      </div>
      {fabric && (
        <div className="kv">
          <span>fabric</span>
          <span className="muted">
            {String(fabric.compute_tiles ?? '—')} tiles ·{' '}
            {String(fabric.link_width ?? '—')}b links ·{' '}
            {String(fabric.num_vcs ?? '—')} VC
          </span>
        </div>
      )}
      <table className="tbl">
        <thead>
          <tr>
            <th>check</th><th>authority</th><th>independence</th>
            <th>verdict</th><th>expected vs observed</th>
          </tr>
        </thead>
        <tbody>
          {experiment.checks.map((c, i) => (
            <tr key={i}>
              <td>{c.name ?? '—'}</td>
              <td className="muted">{c.authority_class ?? '—'}</td>
              <td className="muted">{c.independence ?? '—'}</td>
              <td><StatusBadge status={c.verdict ?? 'UNKNOWN'} /></td>
              <td className="muted">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {experiment.quarantined_findings.length > 0 && (
        <p className="bad">
          quarantined findings: {experiment.quarantined_findings.join(', ')}
        </p>
      )}
    </>
  );
}

function ValidationCampaigns(): ReactElement {
  const campaigns = useAsync(api.validation, []);
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <section className="card">
      <h3>Validation campaigns</h3>
      <AsyncView result={campaigns.result} reload={campaigns.reload}>
        {(data) => (
          <>
            <table className="live-table">
              <thead>
                <tr><th>experiment</th><th>workload</th><th>checks</th><th>result</th><th></th></tr>
              </thead>
              <tbody>
                {data.experiments.map((e) => (
                  <tr key={e.id}>
                    <td>{e.id}</td>
                    <td className="muted">{e.workload ?? '—'}</td>
                    <td className="muted">{e.checks.length}</td>
                    <td>
                      <StatusBadge status={e.status ?? 'UNKNOWN'} />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setOpenId(openId === e.id ? null : e.id)}
                      >
                        {openId === e.id ? 'Hide' : 'Inspect'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.experiments
              .filter((e) => e.id === openId)
              .map((e) => <CampaignDetail key={e.id} experiment={e} />)}
            <h4>Campaign ledgers</h4>
            <div className="campaign-ledgers">
              <details>
                <summary>
                  Mutation tests — {data.mutations.caught}/{data.mutations.total}{' '}
                  injected faults caught by the canonical gates
                </summary>
                <table className="tbl">
                  <thead>
                    <tr><th>mutation</th><th>caught</th><th>gate expected</th><th>what happened</th></tr>
                  </thead>
                  <tbody>
                    {data.mutations.mutations.map((m) => (
                      <tr key={m.name ?? ''}>
                        <td><code>{m.name}</code></td>
                        <td className={m.caught ? 'good' : 'bad'}>
                          {m.caught ? 'CAUGHT' : 'MISSED'}
                        </td>
                        <td className="muted">{m.expected}</td>
                        <td className="muted">{m.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
              <details>
                <summary>
                  Metamorphic checks — {data.metamorphic.passed}/{data.metamorphic.total}{' '}
                  invariants held (non-physical fields never move physics)
                </summary>
                <table className="tbl">
                  <thead>
                    <tr><th>probe</th><th>invariant</th><th>result</th><th>observed</th></tr>
                  </thead>
                  <tbody>
                    {data.metamorphic.probes.map((p) => (
                      <tr key={p.name ?? ''}>
                        <td><code>{p.name}</code></td>
                        <td className="muted">{p.invariant}</td>
                        <td className={p.passed ? 'good' : 'bad'}>
                          {p.passed ? 'HELD' : 'VIOLATED'}
                        </td>
                        <td className="muted">{JSON.stringify(p.observations)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
              <details>
                <summary>
                  Engine gates —{' '}
                  {data.engines.engines.map((e) => `${e.name} ${e.passed ? 'PASS' : 'FAIL'}`).join(' · ')}
                </summary>
                {data.engines.engines.map((e) => (
                  <div key={e.name ?? ''}>
                    <h4>{e.name} — {e.detail}</h4>
                    <table className="tbl">
                      <tbody>
                        {e.checks.map((c, i) => (
                          <tr key={i}>
                            <td><code>{c.name}</code></td>
                            <td className={c.passed ? 'good' : 'bad'}>
                              {c.passed ? 'PASS' : 'FAIL'}
                            </td>
                            <td className="muted">{c.detail}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </details>
              <details>
                <summary>
                  Intervention study — schedule causality{' '}
                  {data.intervention.supported ? 'SUPPORTED' : 'NOT SUPPORTED'}
                </summary>
                {data.intervention.problems.length > 0 && (
                  <p className="bad">{data.intervention.problems.join('; ')}</p>
                )}
                <table className="tbl">
                  <thead>
                    <tr>
                      {data.intervention.rows.length > 0 &&
                        Object.keys(data.intervention.rows[0]).map((k) => (
                          <th key={k}>{k}</th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.intervention.rows.map((row, i) => (
                      <tr key={i}>
                        {Object.values(row).map((v, j) => (
                          <td key={j} className={j === 0 ? 'muted' : 'num'}>
                            {String(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </div>
            <h4>Other campaigns (prose authority — linked, not parsed)</h4>
            <ul className="muted">
              {data.prose_campaigns.map((c) => (
                <li key={c.document}><code>{c.document}</code></li>
              ))}
              <li>
                <code>{data.findings_document}</code> — defects validation
                found, how each was detected, and the regression that now
                prevents recurrence
              </li>
            </ul>
          </>
        )}
      </AsyncView>
    </section>
  );
}

/** Capabilities registry (§36): rendered directly from the backend's
 * machine-readable registry — backend support, workload kinds, wave-E
 * timing semantics and deferred work. Nothing here is hand-copied prose.
 * Rendered as raw key/value tables: the registry is the authority and its
 * exact vocabulary matters more than a re-worded summary. */
function CapabilitiesSection({ capabilities }: {
  capabilities: ReturnType<typeof useAsync<Record<string, unknown>>>;
}): ReactElement {
  return (
    <section className="card">
      <h3>Capabilities</h3>
      <AsyncView result={capabilities.result} reload={capabilities.reload}>
        {(reg) => (
          <>
            <table className="live-table">
              <thead>
                <tr><th>backend</th><th>lowering</th><th>execution</th><th>route evidence</th><th>semantics version</th></tr>
              </thead>
              <tbody>
                {Object.entries(reg.backends as Record<string, Record<string, unknown>>).map(([name, b]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{String(b.lowering ?? '—')}</td>
                    <td className={
                      b.execution === 'SUPPORTED' ? 'good'
                        : b.execution === 'BLOCKED' || b.execution === 'UNSUPPORTED' ? 'bad'
                          : 'muted'}>
                      {String(b.execution ?? '—')}
                    </td>
                    <td className="muted">{String(b.route_evidence ?? '—')}</td>
                    <td className="muted"><code>{String(b.semantics_version ?? '—')}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="cap-block">
              <h4>Workload kinds</h4>
              <table className="tbl">
                <tbody>
                  {Object.entries(reg.workload_kinds as Record<string, Record<string, unknown>> ?? {}).map(([kind, info]) => (
                    <tr key={kind}>
                      <td>{kind}</td>
                      <td className="muted">
                        semantic provenance {String(info.semantic_provenance ?? '—')}
                        {info.execution ? ` · execution ${String(info.execution)}` : ''}
                        {info.wave_d_chain ? ` · wave-D chain ${String(info.wave_d_chain)}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details>
              <summary>Timing semantics (wave-E) and deferred capabilities</summary>
              <pre className="evidence">{JSON.stringify({
                wave_e: reg.wave_e,
                deferred: reg.deferred,
              }, null, 2)}</pre>
            </details>
          </>
        )}
      </AsyncView>
    </section>
  );
}

export function Trust(): ReactElement {
  const qual = useAsync(api.qualification, []);
  const capabilities = useAsync(api.capabilities, []);
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
      <CapabilitiesSection capabilities={capabilities} />
      <ValidationCampaigns />
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

// ── Execution integrity panels (UX7) ───────────────────────────────────

/** Counter cell: measured values as-is; an absent counter is NOT AVAILABLE,
 * never 0 (§18/§59). */
function IntegrityCounter({ counter }: {
  counter: RunIntegrityView['packet_conservation']['declared'];
}): ReactElement {
  if (counter.availability === 'NOT_AVAILABLE') {
    return <span className="muted">NOT AVAILABLE</span>;
  }
  return <span>{fmtNum(counter.value)}</span>;
}

function ConservationTable({ title, rows, verdict }: {
  title: string;
  rows: { label: string; counter: RunIntegrityView['packet_conservation']['declared'] }[];
  verdict: string;
}): ReactElement {
  return (
    <>
      <h4>{title}</h4>
      <table className="tbl">
        <tbody>
          {rows.map(({ label, counter }) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="num"><IntegrityCounter counter={counter} /></td>
            </tr>
          ))}
          <tr>
            <td>verdict</td>
            <td className="num"><StatusBadge status={verdict} /></td>
          </tr>
        </tbody>
      </table>
    </>
  );
}

function ExecutionIntegrity({ runId }: { runId: string }): ReactElement {
  const integrity = useAsync(() => api.integrity(runId), [runId]);
  return (
    <section className="card">
      <h3>Execution integrity</h3>
      <AsyncView result={integrity.result} reload={integrity.reload}>
        {(v: RunIntegrityView) => (
          <>
            <ConservationTable
              title="Packet conservation"
              verdict={v.packet_conservation.verdict}
              rows={[
                { label: 'declared', counter: v.packet_conservation.declared },
                { label: 'loaded', counter: v.packet_conservation.loaded },
                { label: 'injected', counter: v.packet_conservation.injected },
                { label: 'delivered', counter: v.packet_conservation.delivered },
              ]}
            />
            <ConservationTable
              title="Flit conservation"
              verdict={v.flit_conservation.verdict}
              rows={[
                { label: 'declared', counter: v.flit_conservation.declared },
                { label: 'injected', counter: v.flit_conservation.injected },
                { label: 'accepted', counter: v.flit_conservation.accepted },
              ]}
            />
            <h4>Route realization</h4>
            <div className="kv">
              <span>status</span>
              <span>{v.route_realization.status}</span>
            </div>
            <div className="kv">
              <span>scope</span>
              <span className="muted">{v.route_realization.scope}</span>
            </div>
            <div className="kv">
              <span>full path</span>
              <span className="muted">not claimed — first-hop scope only</span>
            </div>
            <div className="kv">
              <span>realized digest</span>
              <Hash value={v.route_realization.realized_digest} />
            </div>
            {v.evidence_id && (
              <div className="kv">
                <span>evidence</span>
                <Hash value={v.evidence_id} />
              </div>
            )}
          </>
        )}
      </AsyncView>
    </section>
  );
}

function BundleActions({ run }: { run: RunView }): ReactElement {
  const [verify, setVerify] = useState<RunVerifyView | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const poll = async (jobId: string): Promise<void> => {
    for (;;) {
      const current = await api.job(jobId);
      setJob(current);
      if (['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(current.state)) {
        return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
  };

  const act = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h3>Bundle</h3>
      <div className="kv"><span>bundle identity</span><Hash value={run.bundle_id} /></div>
      <div className="head-actions">
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => act(async () => {
            setVerify(null);
            setVerify(await api.verifyRun(run.run_id));
          })}
        >
          Verify bundle
        </button>
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => act(async () => {
            setJob(null);
            const submitted = await api.reproduceRun(run.run_id);
            void poll(submitted.job_id);
          })}
        >
          Reproduce
        </button>
      </div>
      {verify && (
        <div className="kv">
          <span>integrity</span>
          <span>
            ✓ VERIFIED · {verify.files_checked} files checked
          </span>
        </div>
      )}
      {job && (
        <div className="kv">
          <span>reproduction</span>
          <span>
            {job.state === 'COMPLETED'
              ? `SCIENTIFICALLY REPRODUCED (${job.result?.outcome ?? 'ok'})`
              : job.state === 'REFUSED' || job.state === 'FAILED'
                ? `refused: ${job.error_message ?? job.error_code}`
                : job.state.toLowerCase()}
          </span>
        </div>
      )}
      {error && <p className="bad">{error}</p>}
    </section>
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
                  <thead><tr><th>class</th><th>QoS</th><th>binding</th><th>verdict</th><th>required</th><th>measured</th><th>authority</th><th>reason</th></tr></thead>
                  <tbody>
                    {r.requirements.entries.map((e, i) => (
                      <tr key={i}>
                        <td>{e.traffic_class ?? 'fabric'}</td>
                        <td className="muted">{e.qos_class ?? '—'}</td>
                        <td className="muted">{e.binding ? 'binding' : 'advisory'}</td>
                        <td><StatusBadge status={e.verdict} /></td>
                        <td>{e.required == null ? '—' : fmtNum(e.required)}</td>
                        <td>{e.measured == null ? '—' : fmtNum(e.measured)}</td>
                        <td className="muted">{e.metric_authority}</td>
                        <td className="muted">{e.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
            <ExecutionIntegrity runId={r.run_id} />
            <BundleActions run={r} />
            <TrustDrawer run={r} />
          </>
        )}
      </AsyncView>
    </div>
  );
}
