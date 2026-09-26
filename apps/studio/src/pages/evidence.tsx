import { useState, type ReactElement } from 'react';
import {
  api,
  type JobView,
  type RunIntegrityView,
  type RunView,
  type RunVerifyView,
  type ValidationExperiment,
} from '../api';
import {
  AsyncView, Link, useAsync,
} from '../studio';
import { Hash, StatusBadge, fmtNum, humanize } from '../components/badges';

// ── 07 · Evidence: the RunBundle as a first-class inspector ────────────

/** The canonical evidence chain of one run: design → compiler artifacts →
 * lowering → producer → evidence → result. Rendered from the RunView's
 * recorded identities only — the chain is the record, not an inference. */
function RunBundleChain({ run }: { run: RunView }): ReactElement {
  const nodes: { type: string; label: string; hash: string | null | undefined }[] = [
    { type: 'revision', label: 'Design', hash: run.design_hash },
    {
      type: 'lowering',
      label: 'Physical traffic',
      hash: run.evaluation?.physical_traffic_id,
    },
    { type: 'producer', label: run.backend ?? 'backend', hash: run.producer?.producer_identity },
    { type: 'input', label: 'Input', hash: run.producer?.input_hash },
    { type: 'config', label: 'Config', hash: run.producer?.config_hash },
    { type: 'evidence', label: 'Scientific evidence', hash: run.evidence?.raw_evidence_digest },
    { type: 'stats', label: 'Stats digest', hash: run.evidence?.stats_digest },
    { type: 'result', label: 'Performance', hash: run.evaluation?.performance_result_id },
  ];
  const present = nodes.filter((n) => n.hash);
  return (
    <div className="artifact-chain-wrap">
      <div className="artifact-chain">
        {present.map((n, i) => (
          <div key={n.type}>
            <div className="artifact">
              <span className="type">{n.type}</span>
              <strong>{n.label}</strong>
              <Hash value={n.hash} />
            </div>
            {i < present.length - 1 && <span className="arrow-inline">→</span>}
          </div>
        ))}
      </div>
      {present.length < nodes.length && (
        <p className="muted">
          {nodes.length - present.length} chain link(s) not carried by this
          run's record — shown only when the backend supplies them.
        </p>
      )}
    </div>
  );
}

function ExecutionChecks({ runId }: { runId: string }): ReactElement {
  const integrity = useAsync(() => api.integrity(runId), [runId]);
  return (
    <AsyncView result={integrity.result} reload={integrity.reload}>
      {(v: RunIntegrityView) => (
        <>
          <table className="tbl">
            <tbody>
              <tr>
                <td>packet conservation</td>
                <td><StatusBadge status={v.packet_conservation.verdict} /></td>
              </tr>
              <tr>
                <td>flit conservation</td>
                <td><StatusBadge status={v.flit_conservation.verdict} /></td>
              </tr>
              <tr>
                <td>route realization</td>
                <td>
                  <StatusBadge status={v.route_realization.status} />
                  <span className="muted"> · {v.route_realization.scope}</span>
                </td>
              </tr>
            </tbody>
          </table>
          <p className="muted">
            First-hop realization does not imply complete per-packet path
            observation — the exact observation level is stated, never a
            generic "routing verified" badge.
          </p>
        </>
      )}
    </AsyncView>
  );
}

function EvidenceRunCard({ run }: { run: RunView }): ReactElement {
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
      <div className="page-head">
        <h3>
          <Link className="link" to={`/runs/${run.run_id}`}>
            {run.display_name ?? run.run_id}
          </Link>{' '}
          <StatusBadge status={run.status ?? 'UNKNOWN'} />
          {run.qualification ? ` · ${run.qualification}` : ''}
        </h3>
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
      </div>
      <RunBundleChain run={run} />
      <div className="overview-grid">
        <div>
          <h4>Execution checks</h4>
          <ExecutionChecks runId={run.run_id} />
        </div>
        <div>
          <h4>Bundle integrity</h4>
          <div className="kv"><span>bundle identity</span><Hash value={run.bundle_id} /></div>
          {verify && (
            <div className="kv">
              <span>verify</span>
              <span>✓ VERIFIED · {verify.files_checked} files checked</span>
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
        </div>
      </div>
      {run.evaluation?.metrics && (
        <details>
          <summary>Measured metrics</summary>
          <table className="tbl">
            <tbody>
              {Object.entries(run.evaluation.metrics).map(([k, v]) => (
                <tr key={k}>
                  <td>{humanize(k)}</td>
                  <td className="num">{fmtNum(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {error && <p className="bad">{error}</p>}
    </section>
  );
}

export function Evidence({ projectId }: { projectId: string }): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => (
        <div className="page">
          <div className="page-head">
            <div>
              <h2>Evidence &amp; reproduction</h2>
              <p className="muted">
                Make every result traceable to the exact thing that produced
                it. The RunBundle is the audit surface: design, revision,
                backend inputs, producer, evidence, metrics and requirement
                report. Every trusted read verifies the bundle first.
              </p>
            </div>
            <div className="head-actions">
              <Link className="btn" to="/runs">All runs</Link>
            </div>
          </div>
          {p.runs.length === 0 ? (
            <p className="muted">
              No runs yet — evidence appears after an evaluation on the
              Evaluate page.
            </p>
          ) : (
            <div className="stack-lg">
              {[...p.runs].reverse().map((r) => (
                <EvidenceRunCard key={r.run_id} run={r as RunView} />
              ))}
            </div>
          )}
        </div>
      )}
    </AsyncView>
  );
}

// ── 09 · Validation lab ────────────────────────────────────────────────

/** Scope-aware backend matrix: what each backend is for, its current
 * qualification, and what must never be claimed for it. Wording follows
 * the handoff table; statuses come from the qualification authority. */
const BACKEND_MATRIX: {
  name: string;
  role: string;
  qualification: string;
  cls: string;
  evidence: string;
  doNotClaim: string;
}[] = [
  {
    name: 'BookSim',
    role: 'canonical network execution',
    qualification: 'QUALIFIED',
    cls: 'good',
    evidence: 'producer + input + stats identity',
    doNotClaim: 'full physical timing prediction',
  },
  {
    name: 'ASTRA-Sim',
    role: 'distributed-system projection',
    qualification: 'INTEGRATED',
    cls: 'info',
    evidence: 'machine/workload + nested backend identity',
    doNotClaim: 'hardware latency truth',
  },
  {
    name: 'Ramulator',
    role: 'memory analysis',
    qualification: 'BOUNDED',
    cls: 'warn',
    evidence: 'structured memory evidence (16/16 battery)',
    doNotClaim: 'universal network+DRAM coupling',
  },
  {
    name: 'RTL',
    role: 'independent correspondence',
    qualification: 'BOUNDED',
    cls: 'warn',
    evidence: 'trace correspondence on qualified cases',
    doNotClaim: 'all arbitrary fabrics verified',
  },
];

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

function Campaigns(): ReactElement {
  const campaigns = useAsync(api.validation, []);
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <section className="card">
      <h3>Validation campaigns (V01–V14)</h3>
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
                    <td><StatusBadge status={e.status ?? 'UNKNOWN'} /></td>
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
                invariants held
              </summary>
              <table className="tbl">
                <thead>
                  <tr><th>probe</th><th>invariant</th><th>result</th></tr>
                </thead>
                <tbody>
                  {data.metamorphic.probes.map((p) => (
                    <tr key={p.name ?? ''}>
                      <td><code>{p.name}</code></td>
                      <td className="muted">{p.invariant}</td>
                      <td className={p.passed ? 'good' : 'bad'}>
                        {p.passed ? 'HELD' : 'VIOLATED'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
            <details>
              <summary>
                Engine gates —{' '}
                {data.engines.engines
                  .map((e) => `${e.name} ${e.passed ? 'PASS' : 'FAIL'}`)
                  .join(' · ')}
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
                Intervention study — schedule causality
              </summary>
              {data.intervention.problems.length > 0 && (
                <ul className="bad">
                  {data.intervention.problems.map((problem, index) => (
                    <li key={index}>{String(problem)}</li>
                  ))}
                </ul>
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
            <h4>Prose campaigns (linked, not parsed)</h4>
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

export function ValidationLab({ projectId }: { projectId: string }): ReactElement {
  const qual = useAsync(api.qualification, []);
  const project = useAsync(() => api.project(projectId), [projectId]);
  return (
    <AsyncView result={project.result} reload={project.reload}>
      {() => (
        <div className="page">
          <div className="page-head">
            <div>
              <h2>Validation lab</h2>
              <p className="muted">
                Bounded independent evidence. Backends carry different
                scopes — the scope is shown next to every result. Never
                turn "backend executes" into "accurate hardware latency
                prediction".
              </p>
            </div>
            <div className="head-actions">
              <Link className="btn" to="/trust">Full Trust page</Link>
            </div>
          </div>
          <section className="card">
            <h3>Backend / validation matrix</h3>
            <table className="live-table">
              <thead>
                <tr>
                  <th>backend</th><th>primary role</th><th>current qualification</th>
                  <th>identity / evidence</th><th>do not claim</th>
                </tr>
              </thead>
              <tbody>
                {BACKEND_MATRIX.map((b) => (
                  <tr key={b.name}>
                    <td>{b.name}</td>
                    <td className="muted">{b.role}</td>
                    <td><span className={b.cls}>{b.qualification}</span></td>
                    <td className="muted">{b.evidence}</td>
                    <td className="muted">{b.doNotClaim}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <AsyncView result={qual.result} reload={qual.reload}>
            {(data) => (
              <section className="card">
                <h3>Engine qualification (machine-readable authority)</h3>
                <table className="live-table">
                  <thead>
                    <tr>
                      <th>engine</th><th>role</th><th>integration</th>
                      <th>numerical</th><th>limitations</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.engines).map(([name, e]) => (
                      <tr key={name}>
                        <td>{name}</td>
                        <td className="muted">{e.role}</td>
                        <td>{e.integration}</td>
                        <td className={e.numerical === 'NOT_ESTABLISHED' ? 'bad' : 'good'}>
                          {e.numerical}
                        </td>
                        <td className="muted">{e.limitations.join('; ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted">
                  Source: docs/production/ENGINE-QUALIFICATION.json
                  {data.validation_sha ? ` · validation ${data.validation_sha}` : ''}.
                </p>
              </section>
            )}
          </AsyncView>
          <Campaigns />
        </div>
      )}
    </AsyncView>
  );
}
