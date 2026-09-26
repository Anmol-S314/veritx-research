import { useState, type ReactElement } from 'react';
import {
  api,
  type CanonicalServingEvidence,
  type JobView,
  type ServingSummary,
  type ServingView,
} from '../api';
import {
  AsyncView, ErrorBox, JobProgress, useAsync, useJobPoll,
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

/** Declared CertifiedServiceProfile fields a user may override. Keys must
 * match the gateway's certified field set; a blank field keeps the declared
 * default. These are declared profile inputs, not measurements. */
const PROFILE_FIELDS: {
  key: string;
  label: string;
  kind: 'int' | 'enum';
  options?: string[];
}[] = [
  { key: 'routing_policy', label: 'Routing policy', kind: 'enum',
    options: ['RR', 'LOAD', 'RAND'] },
  { key: 'max_num_seqs', label: 'Max sequences', kind: 'int' },
  { key: 'max_num_batched_tokens', label: 'Max batched tokens', kind: 'int' },
  { key: 'block_size', label: 'Block size', kind: 'int' },
  { key: 'fp_bits', label: 'FP bits', kind: 'int' },
  { key: 'collective_bytes_per_rank', label: 'Collective bytes/rank', kind: 'int' },
  { key: 'ep_size', label: 'Expert parallel size', kind: 'int' },
];

function RequestMetricsTable({ document }: {
  document: CanonicalServingEvidence;
}): ReactElement {
  const rows = document.request_metrics ?? [];
  if (rows.length === 0) {
    return (
      <p className="muted">
        The evidence document carries no per-request metrics.
      </p>
    );
  }
  const pct = (p: number): [number, number] => {
    const pick = (idx: 1 | 2): number => {
      const vals = rows
        .map((r) => r[idx])
        .filter((v): v is number => typeof v === 'number')
        .sort((a, b) => a - b);
      if (vals.length === 0) return NaN;
      const i = Math.min(vals.length - 1, Math.ceil((p / 100) * vals.length) - 1);
      return vals[Math.max(0, i)];
    };
    return [pick(1), pick(2)];
  };
  const [ttft50, comp50] = pct(50);
  const [ttft99, comp99] = pct(99);
  const fmt = (n: number): string => (Number.isFinite(n) ? fmtNum(n) : '—');
  return (
    <>
      <p className="muted">
        Model-internal values under the certified linear service profile —
        exact within the declared model, NOT calibrated hardware latency
        (SERVING_ABSOLUTE_LATENCY: PARTIAL). Percentiles are over the declared
        population: {rows.length}/{document.request_count} retired.
      </p>
      <div className="kv">
        <span>TTFT p50 / p99</span>
        <span>
          {fmt(ttft50)} / {fmt(ttft99)} cycles
        </span>
      </div>
      <div className="kv">
        <span>completion p50 / p99</span>
        <span>
          {fmt(comp50)} / {fmt(comp99)} cycles
        </span>
      </div>
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

/** Presentation-only short form of an identity. The full value stays in the
 * title and the copy control; never used as a scientific identity. */
function shortId(value: string): string {
  return value.length > 14 ? `…${value.slice(-6)}` : value;
}

function Identity({ label, value }: {
  label: string;
  value: string | null | undefined;
}): ReactElement {
  if (!value) {
    return (
      <div className="kv">
        <span>{label}</span>
        <span className="muted">—</span>
      </div>
    );
  }
  return (
    <div className="kv">
      <span>{label}</span>
      <span title={value}>
        <code>{shortId(value)}</code>
        <button
          type="button"
          className="btn"
          style={{ marginLeft: 8 }}
          onClick={() => {
            void navigator.clipboard?.writeText(value);
          }}
        >
          Copy
        </button>
      </span>
    </div>
  );
}

function RunSummary({ document }: {
  document: CanonicalServingEvidence;
}): ReactElement {
  return (
    <section className="card">
      <h3>Run summary</h3>
      <div className="kv">
        <span>execution mode</span>
        <span>{document.execution_mode}</span>
      </div>
      <div className="kv">
        <span>network evidence tier</span>
        <span>{document.network_evidence_tier}</span>
      </div>
      <div className="kv">
        <span>expansion authority</span>
        <span>{document.expansion_authority}</span>
      </div>
      <div className="kv">
        <span>instances</span>
        <span>{fmtNum(document.instance_count)}</span>
      </div>
      <div className="kv">
        <span>every instance served</span>
        <span>{document.every_instance_served ? 'yes' : 'no'}</span>
      </div>
      <div className="kv">
        <span>reusable</span>
        <span>
          {document.reusable
            ? 'yes — eligible for replay / regression'
            : 'no'}
        </span>
      </div>
      <div className="kv">
        <span>workload</span>
        <span>{document.workload_id}</span>
      </div>
    </section>
  );
}

function InstanceParticipation({ document }: {
  document: CanonicalServingEvidence;
}): ReactElement {
  const instances = Array.from({ length: document.instance_count }, (_, i) => i);
  const completion = new Map(document.endpoint_completions.map(([i, c]) => [i, c]));
  return (
    <section className="card">
      <h3>Instance and endpoint participation</h3>
      <table className="tbl">
        <thead>
          <tr>
            <th>instance</th><th>served</th><th>completed</th>
            <th>completion (cycles)</th>
          </tr>
        </thead>
        <tbody>
          {instances.map((i) => {
            const c = completion.get(i);
            return (
              <tr key={i}>
                <td>{i}</td>
                <td>{document.served_instances.includes(i) ? 'yes' : 'no'}</td>
                <td>
                  {document.instances_with_completions.includes(i) ? 'yes' : 'no'}
                </td>
                <td className="num">{c == null ? '—' : fmtNum(c)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted">
        Participation is returned per instance by the canonical path; this page
        computes no serving semantics.
      </p>
    </section>
  );
}

function Provenance({ document }: {
  document: CanonicalServingEvidence;
}): ReactElement {
  return (
    <section className="card">
      <h3>Provenance</h3>
      <div className="kv">
        <span>VERITX source revision</span>
        <span>
          <code>{document.astra_source_revision}</code>
        </span>
      </div>
      <div className="kv">
        <span>ASTRA binary</span>
        <span>{fmtNum(document.astra_binary_size)} bytes</span>
      </div>
      <Identity label="ASTRA binary digest" value={document.astra_binary_sha256} />
      <Identity
        label="standalone config digest"
        value={document.standalone_config_sha256}
      />
      <div className="kv">
        <span>fabric ABI</span>
        <span>{document.embedded_fabric_abi_version}</span>
      </div>
      <div className="kv">
        <span>serving config</span>
        <span>{document.serving_config_id}</span>
      </div>
      <Identity label="backend identity" value={document.backend_id} />
    </section>
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
                <span>timeout</span>
                <span>{s.timeout_s == null ? '—' : `${s.timeout_s} s`}</span>
              </div>
              <div className="kv">
                <span>declared profile overrides</span>
                <span>
                  {s.profile_overrides &&
                  Object.keys(s.profile_overrides).length > 0
                    ? Object.entries(s.profile_overrides)
                        .map(([k, v]) => `${k}=${String(v)}`)
                        .join(' · ')
                    : 'certified declared defaults'}
                </span>
              </div>
              <Identity label="machine identity" value={s.evidence.machine_id} />
              <Identity label="namespace identity" value={s.evidence.namespace_id} />
              <details>
                <summary>
                  Evidence identities ({s.evidence.evidence_ids.length}) — hashes,
                  power-user view
                </summary>
                <span className="artifact-list">
                  {s.evidence.evidence_ids.map((id) => (
                    <Hash key={id} value={id} />
                  ))}
                </span>
              </details>
              {s.evidence.document && (
                <>
                  <RunSummary document={s.evidence.document} />
                  <InstanceParticipation document={s.evidence.document} />
                  <Provenance document={s.evidence.document} />
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
  const catalog = useAsync(() => api.servingConfigs(), []);
  const [numReqs, setNumReqs] = useState(8);
  const [clusterConfig, setClusterConfig] = useState<string | null>(null);
  const [dataset, setDataset] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [timeoutS, setTimeoutS] = useState('');
  const [advanced, setAdvanced] = useState<Record<string, string>>({});

  // Defaults come from the gateway, not from hardcoded repo paths.
  const catalogData =
    catalog.result.state === 'ready' ? catalog.result.data : null;
  const clusterConfigValue =
    clusterConfig ?? catalogData?.default_config ?? null;
  const datasetValue = dataset ?? catalogData?.default_trace ?? null;

  const onTerminal = (job: JobView): void => {
    experiments.reload();
    const sid = job.result?.serving_id ?? null;
    if (sid) setActiveId(sid);
  };
  const job = useJobPoll(jobId, onTerminal);

  const submit = async (): Promise<void> => {
    setError(null);
    try {
      const profileOverrides: Record<string, number | string> = {};
      for (const f of PROFILE_FIELDS) {
        const raw = advanced[f.key];
        if (raw === undefined || raw.trim() === '') continue;
        profileOverrides[f.key] = f.kind === 'int' ? Number(raw) : raw;
      }
      const submitted = await api.servingSubmit(projectId, {
        num_reqs: numReqs,
        cluster_config: clusterConfigValue ?? undefined,
        dataset: datasetValue ?? undefined,
        timeout_s: timeoutS.trim() === '' ? undefined : Number(timeoutS),
        profile_overrides:
          Object.keys(profileOverrides).length > 0
            ? profileOverrides
            : undefined,
      });
      setJobId(submitted.job_id);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {() => (
        <div className="page">
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
              Inputs are listed by the gateway; the canonical loader validates
              their contents. Cluster service semantics, TP/EP groups and the
              request trace come from the vendored authority — not this form.
            </p>
            <AsyncView result={catalog.result} reload={catalog.reload}>
              {(catData) => {
                const entry = catData.configs.find(
                  (c) => c.source === clusterConfigValue,
                );
                return (
                  <>
                    <div className="form-row">
                      <label>
                        Cluster config
                        <select
                          value={clusterConfigValue ?? ''}
                          onChange={(e) => setClusterConfig(e.target.value)}
                        >
                          {catData.configs.map((c) => (
                            <option key={c.config_id} value={c.source}>
                              {c.display_name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Request trace
                        <select
                          value={datasetValue ?? ''}
                          onChange={(e) => setDataset(e.target.value)}
                        >
                          {catData.traces.map((t) => (
                            <option key={t.trace_id} value={t.source}>
                              {t.display_name} ({t.requests} requests)
                            </option>
                          ))}
                        </select>
                      </label>
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
                    {entry && (
                      <div className="kv">
                        <span>resolved geometry</span>
                        <span>
                          {entry.geometry.num_nodes} node(s) ·{' '}
                          {entry.geometry.instances} instance(s) · TP{' '}
                          {entry.geometry.tp_sizes.join('/') || '—'} · EP{' '}
                          {entry.geometry.ep_sizes.join('/') || '—'}
                          {entry.geometry.pd_types.length
                            ? ` · PD ${entry.geometry.pd_types.join('/')}`
                            : ''}
                        </span>
                      </div>
                    )}
                    {entry && (
                      <div className="kv">
                        <span>model / hardware</span>
                        <span>
                          {entry.geometry.models.join(', ') || '—'} ·{' '}
                          {entry.geometry.hardware.join(', ') || '—'}
                        </span>
                      </div>
                    )}
                    <details className="advanced">
                      <summary>
                        Advanced — timeout and declared service profile
                      </summary>
                      <div className="form-row">
                        <label>
                          Timeout (s)
                          <input
                            type="number"
                            min={1}
                            max={3600}
                            placeholder="canonical default"
                            value={timeoutS}
                            onChange={(e) => setTimeoutS(e.target.value)}
                          />
                        </label>
                        {PROFILE_FIELDS.map((f) => (
                          <label key={f.key}>
                            {f.label}
                            {f.kind === 'enum' ? (
                              <select
                                value={advanced[f.key] ?? ''}
                                onChange={(e) =>
                                  setAdvanced((a) => ({
                                    ...a,
                                    [f.key]: e.target.value,
                                  }))}
                              >
                                <option value="">declared default</option>
                                {f.options?.map((o) => (
                                  <option key={o} value={o}>
                                    {o}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <input
                                type="number"
                                min={1}
                                placeholder="declared default"
                                value={advanced[f.key] ?? ''}
                                onChange={(e) =>
                                  setAdvanced((a) => ({
                                    ...a,
                                    [f.key]: e.target.value,
                                  }))}
                              />
                            )}
                          </label>
                        ))}
                      </div>
                      <p className="muted">
                        Blank keeps the certified declared default. These are
                        declared profile inputs, not measurements, and they bind
                        into the run identity. Unknown keys are refused by the
                        gateway before the job starts.
                      </p>
                    </details>
                  </>
                );
              }}
            </AsyncView>
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
                      <th>requests</th><th>rounds</th><th>reusable</th><th></th>
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
                          {e.reusable == null
                            ? '—'
                            : e.reusable
                              ? 'yes'
                              : 'no'}
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
