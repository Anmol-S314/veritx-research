import { useState, type ReactElement } from 'react';
import {
  api,
  type JobView,
  type ServingSummary,
  type ServingView,
} from '../api';
import {
  AsyncView, ErrorBox, JobProgress, WorkflowBar, useAsync, useJobPoll,
} from '../studio';
import { Hash, StatusBadge, fmtNum } from '../components/badges';

/**
 * Serving workspace. Submits canonical serving experiments (the
 * qualified ASTRA/BookSim serve path) and inspects their evidence at its
 * actual qualification level. Qualification honesty is structural here:
 * the header states the domain grades (scheduling/TP/DP/EP/multi-instance
 * QUALIFIED per SERVING-QUALIFICATION.md; absolute latency PARTIAL —
 * declared model only), and per-request TTFT/completion values are
 * labelled model-internal. Nothing here claims hardware latency.
 */

function RequestMetricsTable({ document }: {
  document: Record<string, unknown>;
}): ReactElement {
  // request_metrics rows are [request_id, ttft_cycles, completion_cycles]
  const rows = (document['request_metrics'] as
    | [string, number | null, number | null][]
    | undefined) ?? [];
  if (rows.length === 0) {
    return (
      <p className="muted">
        The evidence document carries no per-request metrics.
      </p>
    );
  }
  return (
    <>
      <p className="muted">
        Model-internal values under the certified linear service profile —
        exact within the declared model, NOT calibrated hardware latency
        (SERVING_ABSOLUTE_LATENCY: PARTIAL).
      </p>
      <table className="tbl">
        <thead>
          <tr><th>request</th><th>TTFT (cycles)</th><th>completion (cycles)</th></tr>
        </thead>
        <tbody>
          {rows.map(([id, ttft, completion], i) => (
            <tr key={i}>
              <td><code>{id}</code></td>
              <td className="num">{ttft == null ? '—' : fmtNum(ttft)}</td>
              <td className="num">{completion == null ? '—' : fmtNum(completion)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function ServingDetail({ servingId }: { servingId: string }): ReactElement {
  const serving = useAsync(() => api.serving(servingId), [servingId]);
  return (
    <AsyncView result={serving.result} reload={serving.reload}>
      {(s: ServingView) => (
        <section className="card">
          <h3>
            Experiment {s.serving_id} <StatusBadge status={s.state} />
          </h3>
          {s.error && <p className="bad">refused: {s.error}</p>}
          {s.evidence ? (
            <>
              <div className="kv">
                <span>requests</span>
                <span>
                  {fmtNum(s.evidence.request_count)} / {fmtNum(s.evidence.requests_expected)} retired
                </span>
              </div>
              <div className="kv">
                <span>rounds</span>
                <span>{fmtNum(s.evidence.rounds)}</span>
              </div>
              <div className="kv">
                <span>machine identity</span>
                <code>{s.evidence.machine_id}</code>
              </div>
              <div className="kv">
                <span>namespace identity</span>
                <code>{s.evidence.namespace_id}</code>
              </div>
              <div className="kv">
                <span>evidence ids</span>
                <span className="artifact-list">
                  {s.evidence.evidence_ids.map((id) => (
                    <Hash key={id} value={id} />
                  ))}
                </span>
              </div>
              {s.evidence.document && (
                <>
                  <h4>Per-request metrics</h4>
                  <RequestMetricsTable document={s.evidence.document} />
                  <details>
                    <summary>Raw evidence document</summary>
                    <pre className="evidence">
                      {JSON.stringify(s.evidence.document, null, 2)}
                    </pre>
                  </details>
                </>
              )}
            </>
          ) : s.state !== 'COMPLETED' ? (
            <p className="muted">
              No evidence yet — the experiment is {s.state?.toLowerCase()}.
            </p>
          ) : (
            <p className="muted">No evidence document was recorded.</p>
          )}
        </section>
      )}
    </AsyncView>
  );
}

export function Serving({ projectId }: { projectId: string }): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  const experiments = useAsync(() => api.servingList(projectId), [projectId]);
  const [numReqs, setNumReqs] = useState(8);
  const [jobId, setJobId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const onTerminal = (job: JobView): void => {
    experiments.reload();
    const sid = job.result?.serving_id ?? null;
    if (sid) setActiveId(sid);
  };
  const job = useJobPoll(jobId, onTerminal);

  const submit = async (): Promise<void> => {
    setError(null);
    try {
      const submitted = await api.servingSubmit(projectId, {
        num_reqs: numReqs,
      });
      setJobId(submitted.job_id);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => (
        <div className="page">
          <WorkflowBar project={p} current="serving" />
          <h2>Serving</h2>

          <section className="card">
            <h3>Qualification scope</h3>
            <p className="muted">
              Certified serving domains: scheduling, TP, DP, EP,
              multi-instance liveness and TTFT (model-internal) — QUALIFIED.
              Absolute hardware latency: PARTIAL — exact under the declared
              linear service profile, not calibrated to real hardware. The
              certified path is the canonical serving loop over the
              ASTRA/BookSim boundary; no result here overrides Trust.
            </p>
          </section>

          <div className="overview-grid">
            <section className="card">
              <h3>Namespace discipline</h3>
              <table className="tbl">
                <tbody>
                  <tr><td>serving instance</td><td className="muted">scheduler object</td></tr>
                  <tr><td>rank</td><td className="muted">collective participant</td></tr>
                  <tr><td>endpoint</td><td className="muted">physical attachment</td></tr>
                  <tr><td>router</td><td className="muted">fabric node</td></tr>
                  <tr><td>BookSim node</td><td className="muted">backend-internal</td></tr>
                </tbody>
              </table>
              <p className="muted">
                These identifiers are never interchangeable: a serving
                instance owns several ranks; a rank binds to exactly one
                endpoint; endpoints seat on routers. The evidence identities
                below name each layer explicitly.
              </p>
            </section>
            <section className="card">
              <h3>Ownership boundary</h3>
              <table className="tbl">
                <tbody>
                  <tr><td>arrivals / queues</td><td className="muted">LLMServingSim</td></tr>
                  <tr><td>batching / prefill / decode</td><td className="muted">LLMServingSim</td></tr>
                  <tr><td>scheduling semantics</td><td className="muted">LLMServingSim</td></tr>
                  <tr><td>physical fabric / routing / VC</td><td className="muted">SROTA canonical compiler</td></tr>
                  <tr><td>rank → endpoint binding</td><td className="muted">SROTA</td></tr>
                  <tr><td>network execution + evidence</td><td className="muted">SROTA (ASTRA → BookSim)</td></tr>
                </tbody>
              </table>
              <p className="muted">
                Static evaluation and request-driven serving are different
                abstractions: a Studio EP declaration is never translated
                into serving dispatch/combine semantics in the browser —
                serving semantics are returned by the serving backend.
              </p>
            </section>
          </div>

          <section className="card">
            <h3>New serving experiment</h3>
            <p className="muted">
              Runs the canonical serve path on the tracked cluster config
              and request trace (instances, TP/EP groups and service
              semantics come from the vendored authority — not this form).
            </p>
            <div className="form-row">
              <label>
                Requests
                <input
                  type="number"
                  min={1}
                  value={numReqs}
                  onChange={(e) =>
                    setNumReqs(Math.max(1, Number(e.target.value) || 1))}
                />
              </label>
              <button className="btn btn-primary" onClick={submit}>
                Submit serving experiment
              </button>
            </div>
            {error && <ErrorBox error={error} />}
            <JobProgress job={job} />
          </section>

          <section className="card">
            <h3>Experiments</h3>
            <AsyncView result={experiments.result} reload={experiments.reload}>
              {(data) => data.experiments.length === 0 ? (
                <p className="muted">No serving experiments yet.</p>
              ) : (
                <table className="live-table">
                  <thead>
                    <tr>
                      <th>experiment</th><th>state</th><th>workload</th>
                      <th>requests</th><th>rounds</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.experiments.map((e: ServingSummary) => (
                      <tr key={e.serving_id ?? ''}>
                        <td><code>{e.serving_id}</code></td>
                        <td><StatusBadge status={e.state ?? 'UNKNOWN'} /></td>
                        <td className="muted">{e.workload_id ?? '—'}</td>
                        <td className="num">
                          {e.request_count == null ? '—' : fmtNum(e.request_count)}
                        </td>
                        <td className="num">
                          {e.rounds == null ? '—' : fmtNum(e.rounds)}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn"
                            onClick={() => setActiveId(e.serving_id)}
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </AsyncView>
          </section>

          {activeId && <ServingDetail servingId={activeId} />}
        </div>
      )}
    </AsyncView>
  );
}

// Local shim removed: serving experiments do not change project flow
// state, so the studio context is not needed on this page.
