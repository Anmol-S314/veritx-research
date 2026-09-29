// *
// Rationale: docs/decisions/studio.md
import { useState, type ReactElement } from 'react';
import { api, type JobView } from '../api';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync, useJobPoll,
} from '../studio';
import { Hash, StatusBadge, fmtNum, humanize } from './badges';
import { ScientificValue, SimulatedTimeNote } from './ScientificValue';
import FederatedEvaluationView from './FederatedEvaluationView';

function questionOf(r: {
  analyses: { question: string }[] | null;
  backend: string | null;
}): string {
  const qs = Array.from(new Set((r.analyses ?? []).map((a) => a.question)));
  if (qs.length === 1) return qs[0];
  if (qs.length > 1) return `${qs.length} questions`;
  return r.backend ?? 'evaluation';
}

export default function RunDetailView({ runId }: {
  runId: string;
}): ReactElement {
  const run = useAsync(() => api.run(runId), [runId]);
  const integrity = useAsync(() => api.integrity(runId), [runId]);
  const [reproJob, setReproJob] = useState<JobView | null>(null);
  const [reproError, setReproError] = useState<string | null>(null);
  const [reproBusy, setReproBusy] = useState(false);
  const reproPolled = useJobPoll(reproJob?.job_id ?? null);
  const repro = reproPolled ?? reproJob;

  const submitReproduction = async (): Promise<void> => {
    setReproBusy(true);
    setReproError(null);
    try {
      setReproJob(await api.reproduceRun(runId));
    } catch (e) {
      setReproError(e instanceof Error ? e.message : String(e));
    } finally {
      setReproBusy(false);
    }
  };

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
              <h3>{questionOf(r)} · {r.backend ?? 'no backend'} · {r.revision_id}</h3>
              <p className="muted">{r.display_name ?? r.run_id}</p>
              <div className="kv"><span>status</span><StatusBadge status={r.status ?? 'UNKNOWN'} /></div>
              {r.qualification_basis && (
                <div className="kv">
                  <span>qualification basis</span>
                  <span className="muted">{r.qualification_basis}</span>
                </div>
              )}
              {r.evaluation?.network_traffic_window && (
                <div className="kv">
                  <span>completion</span>
                  <ScientificValue
                    value={r.evaluation.network_traffic_window.window_cycles}
                    unit="cycles"
                    epistemic="SIMULATED"
                    source={r.backend}
                    fidelity={r.evaluation.fidelity_warning}
                    qualification={r.qualification_basis}
                  />
                </div>
              )}
              {r.evaluation?.network_traffic_window?.cycles_only && (
                <p className="muted"><SimulatedTimeNote /></p>
              )}
              {r.reason && <p className="bad">{r.reason}</p>}
            </section>

            <section className="card">
              <h3>Producer</h3>
              {r.producer ? (
                <>
                  <div className="kv"><span>executing backend</span><span>{r.producer.backend}</span></div>
                  <div className="kv"><span>producer identity</span><span className="mono">{r.producer.producer_identity}</span></div>
                  <div className="kv"><span>config hash</span><Hash value={r.producer.config_hash} /></div>
                  <div className="kv"><span>input hash</span><Hash value={r.producer.input_hash} /></div>
                </>
              ) : (
                <p className="muted">No producer identity recorded for this run.</p>
              )}
            </section>

            {r.evaluation?.metrics && (
              <section className="card">
                <h3>Normalized results</h3>
                <table className="live-table">
                  <thead><tr><th>metric</th><th>value</th></tr></thead>
                  <tbody>
                    {Object.entries(r.evaluation.metrics).map(([k, v]) => (
                      <tr key={k}>
                        <td>{humanize(k)}</td>
                        <td>
                          <ScientificValue value={v} unit={null}
                            epistemic="SIMULATED" source={r.backend}
                            qualification={r.qualification_basis} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {r.evaluation.fidelity_warning && (
                  <p className="muted">Fidelity: {r.evaluation.fidelity_warning}</p>
                )}
              </section>
            )}

            {r.analyses && r.analyses.length > 0 && (
              <section className="card">
                <h3>Native summary · per-question analyses</h3>
                <table className="live-table">
                  <thead><tr><th>question</th><th>backend</th><th>status</th><th>fidelity</th><th>qualification</th><th>native evidence</th></tr></thead>
                  <tbody>
                    {r.analyses.map((a) => (
                      <tr key={a.question}>
                        <td>{humanize(a.question)} <span className="muted">· {a.question}</span></td>
                        <td className="muted">{a.backend_id ?? '—'}</td>
                        <td><StatusBadge status={a.status} /></td>
                        <td className="muted">{a.model_fidelity ?? '—'}</td>
                        <td className="muted">{a.qualification ?? '—'}</td>
                        <td className="muted">{a.native_evidence_id ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {r.analyses.some((a) => (a.limitations ?? []).length > 0) && (
                  <ul className="muted">
                    {r.analyses.flatMap((a) => (a.limitations ?? []).map((l) => (
                      <li key={`${a.question}:${l}`}>{humanize(a.question)}: {l}</li>
                    )))}
                  </ul>
                )}
              </section>
            )}

            <section className="card">
              <h3>Artifact inputs</h3>
              <div className="kv"><span>revision</span><span>{r.revision_id}</span></div>
              <div className="kv"><span>design hash</span><Hash value={r.design_hash} /></div>
              <div className="kv"><span>workload</span><span>{r.evaluation?.workload_id ?? '—'}</span></div>
              {r.evaluation?.performance_result_id && (
                <div className="kv"><span>performance result</span><Hash value={r.evaluation.performance_result_id} /></div>
              )}
              <div className="kv"><span>bundle</span><Hash value={r.bundle_id} /></div>
            </section>

            <section className="card">
              <h3>Evidence</h3>
              {r.evidence ? (
                <>
                  <div className="kv"><span>evidence id</span><Hash value={r.evidence.evidence_id} /></div>
                  <div className="kv"><span>raw evidence digest</span><Hash value={r.evidence.raw_evidence_digest} /></div>
                  <div className="kv"><span>stats digest</span><Hash value={r.evidence.stats_digest} /></div>
                  <div className="kv"><span>run bundle</span><Hash value={r.evidence.run_bundle} /></div>
                  <div className="head-actions">
                    <Link className="btn" to={`/runs/${r.run_id}`}>Open evidence chain</Link>
                  </div>
                </>
              ) : (
                <p className="muted">No evidence identity recorded for this run.</p>
              )}
            </section>

            <section className="card">
              <h3>Integrity</h3>
              <AsyncView result={integrity.result} reload={integrity.reload}>
                {(iv) => (
                  <>
                    <div className="kv">
                      <span>packet conservation</span>
                      <span>{iv.packet_conservation
                        ? `${iv.packet_conservation.verdict} · declared ${fmtNum(iv.packet_conservation.declared.value)} / delivered ${fmtNum(iv.packet_conservation.delivered.value)}`
                        : 'NOT MEASURED'}</span>
                    </div>
                    <div className="kv">
                      <span>flit conservation</span>
                      <span>{iv.flit_conservation
                        ? `${iv.flit_conservation.verdict} · injected ${fmtNum(iv.flit_conservation.injected.value)} / accepted ${fmtNum(iv.flit_conservation.accepted.value)}`
                        : 'NOT MEASURED'}</span>
                    </div>
                    <div className="kv">
                      <span>route realization</span>
                      <span>{iv.route_realization
                        ? `${iv.route_realization.status} · ${iv.route_realization.scope} · full path never claimed`
                        : 'NOT OBSERVED'}</span>
                    </div>
                  </>
                )}
              </AsyncView>
            </section>

            {r.analyses && r.analyses.length > 0 && (
              <section className="card">
                <h3>Analyses · federated</h3>
                <FederatedEvaluationView
                  runId={r.run_id}
                  analyses={r.analyses}
                  evaluation={r.evaluation}
                  requirements={r.requirements}
                />
              </section>
            )}

            <section className="card">
              <h3>Reproduction</h3>
              <p className="muted">
                Reproduction re-executes the recorded inputs on the recorded
                producer and compares native evidence — a divergence is
                reported, never hidden.
              </p>
              <div className="head-actions">
                <button className="btn" onClick={submitReproduction} disabled={reproBusy}>
                  {reproBusy ? 'Submitting…' : 'Reproduce this run'}
                </button>
              </div>
              {reproError && <ErrorBox error={new Error(reproError)} onRetry={submitReproduction} />}
              {repro && (
                <>
                  <div className="kv"><span>job</span><span className="mono">{repro.job_id}</span></div>
                  <div className="kv"><span>state</span><StatusBadge status={repro.state} /></div>
                  {repro.result?.outcome && (
                    <div className="kv"><span>outcome</span><StatusBadge status={repro.result.outcome} /></div>
                  )}
                  {repro.error_message && <p className="bad">{repro.error_message}</p>}
                  <JobProgress job={repro} />
                </>
              )}
            </section>
          </>
        )}
      </AsyncView>
    </div>
  );
}
