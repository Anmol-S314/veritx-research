// Synthesize page (§22–24): topology synthesis as a first-class
// EXPLORE workflow. Five methods with honest claims, a problem form
// (base topology, traffic authority, constraints, per-method params),
// the exact CLI invocation where a CLI verb exists, local study drafts,
// and imported-graph inspection with base-vs-generated visual diff.
//
// What this page NEVER does: execute a synthesis engine, invent a
// generator score, or call a candidate verified/measured. Execution
// happens through the canonical pipeline (CLI today, gateway synthesis
// endpoint when it lands); inspection here is proposal-level only.
import { useState, type ReactElement } from 'react';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync, useJobPoll, useStudio,
} from '../studio';
import { api, type JobView, type SynthesisResultView } from '../api';
import { fmtNum, StatusBadge } from '../components/badges';
import { EpistemicChip, ScientificValue } from '../components/ScientificValue';
import {
  METHODS, ROUTES, cliCommand, methodById,
} from '../components/Synthesis/methods';
import {
  degreeOf, isConnected, meshLinks, parseLinks, serializeLinks,
  type Edge,
} from '../components/Synthesis/graph';
import { TopologyGraph } from '../components/Synthesis/TopologyGraph';
import {
  listCandidates, listStudies, saveCandidate, saveStudy,
} from '../components/Synthesis/store';

function defaultsOf(methodId: string): Record<string, string | number> {
  const m = methodById(methodId);
  const out: Record<string, string | number> = {};
  for (const p of m.params) out[p.name] = p.def;
  return out;
}

export function Synthesize({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  void refreshProjects;
  const project = useAsync(() => api.project(projectId), [projectId]);

  const [methodId, setMethodId] = useState('rho');
  const method = methodById(methodId);
  const [values, setValues] = useState<Record<string, string | number>>(
    () => defaultsOf('rho'),
  );
  const [base, setBase] = useState<'mesh' | 'explicit' | 'previous-candidate'>('mesh');
  const [traffic, setTraffic] = useState('current-workload');
  const [trafficRef, setTrafficRef] = useState('');
  const [maxEdges, setMaxEdges] = useState(120);
  const [studyName, setStudyName] = useState('');
  const [importText, setImportText] = useState('');
  const [importScore, setImportScore] = useState('');
  const [importSeed, setImportSeed] = useState('');
  const [importErrors, setImportErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [studyTick, setStudyTick] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [synthesisId, setSynthesisId] = useState<string | null>(null);
  const [liveState, setLiveState] = useState<'idle' | 'unavailable'>('idle');

  const onTerminal = (job: JobView): void => {
    const sid = (job.result as { synthesis_id?: string } | undefined)?.synthesis_id;
    if (sid) setSynthesisId(sid);
  };
  const job = useJobPoll(jobId, onTerminal);
  const live = useAsync(
    () => (synthesisId
      ? api.synthesis(synthesisId)
      : Promise.reject(new Error('no synthesis'))),
    [synthesisId],
  );

  /** Launch through the gateway synthesis endpoint where wired.
   * A 404/503 means the backend route has not landed yet: the page
   * records the maturity state and keeps the local draft + CLI path
   * instead of substituting anything. */
  const launchLive = async (): Promise<void> => {
    setError(null);
    setNotice(null);
    try {
      const submitted = await api.synthesisSubmit({
        method: method.id,
        base_topology: base,
        nodes,
        traffic,
        traffic_ref: trafficRef || null,
        constraints: { max_edges: maxEdges, radix: Number(values.radix ?? 4) },
        params: { ...values },
      });
      setSynthesisId(null);
      setJobId(submitted.job_id);
    } catch (err) {
      setLiveState('unavailable');
      setNotice(
        'Gateway synthesis endpoint not wired yet (RESEARCH maturity) — '
        + 'study draft saved locally and the exact CLI invocation is above. '
        + `Gateway said: ${(err instanceof Error ? err.message : String(err))}`,
      );
    }
  };

  const pickMethod = (id: string): void => {
    setMethodId(id);
    setValues(defaultsOf(id));
    setNotice(null);
  };

  const setParam = (name: string, v: string | number): void => {
    setValues((prev) => ({ ...prev, [name]: v }));
  };

  const nodes = Number(values.nodes ?? 16) || 16;
  const k = Number(values.k ?? Math.round(Math.sqrt(nodes))) || 4;
  const baseLinks: Edge[] = base === 'mesh' && k * k === nodes ? meshLinks(k) : [];
  const cli = cliCommand(
    method,
    values,
    traffic === 'current-workload' ? '<active-revision-traffic>' : (trafficRef || '<trace>'),
  );

  const save = (): void => {
    setError(null);
    try {
      const row = saveStudy({
        name: studyName || `${method.label} study`,
        method: method.id,
        base,
        baseNodes: nodes,
        baseK: k,
        traffic: traffic === 'current-workload' ? 'current-workload' : trafficRef,
        constraints: { max_edges: maxEdges, radix: Number(values.radix ?? 4) },
        params: { ...values },
        cli,
        cliNote: method.cliNote,
      });
      setNotice(`Study draft saved locally (${row.id}). Execution runs through the canonical pipeline — this draft is authoring, not science.`);
      setStudyTick((t) => t + 1);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  const importGraph = (): void => {
    setError(null);
    setImportErrors([]);
    const { links, errors } = parseLinks(importText);
    if (errors.length > 0) {
      setImportErrors(errors);
      return;
    }
    if (links.length === 0) {
      setImportErrors(['no links parsed — paste u-v pairs, one per line']);
      return;
    }
    const top = Math.max(...links.flat());
    if (top >= nodes) {
      setImportErrors([`highest node id ${top} ≥ node count ${nodes} — nodes address 0…${nodes - 1}`]);
      return;
    }
    try {
      const studies = listStudies();
      const studyId = studies.length > 0 ? studies[studies.length - 1].id : saveStudy({
        name: `${method.label} study`,
        method: method.id,
        base,
        baseNodes: nodes,
        baseK: k,
        traffic: traffic === 'current-workload' ? 'current-workload' : trafficRef,
        constraints: { max_edges: maxEdges },
        params: { ...values },
        cli,
        cliNote: method.cliNote,
      }).id;
      const score = importScore.trim() === '' ? null : Number(importScore);
      if (score != null && !Number.isFinite(score)) {
        setImportErrors(['generator score must be a finite number or empty']);
        return;
      }
      const seed = importSeed.trim() === '' ? null : Number(importSeed);
      saveCandidate({
        studyId,
        label: `imported ${method.id} graph`,
        method: method.id,
        nodes,
        links,
        generatorObjective: score,
        generatorNote: 'Imported generator score (proposal screening only — never measured performance).',
        seed: seed != null && Number.isFinite(seed) ? seed : null,
        backendCandidateId: null,
        backendOptimizationId: null,
        compileState: 'NOT_COMPILED',
        verifyState: 'NOT_VERIFIED',
      });
      setNotice(`Imported ${links.length} links into the latest study draft. Inspect below and in Candidates — compile/verify/backend states are NOT_YET until the canonical pipeline runs.`);
      setStudyTick((t) => t + 1);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  const studies = listStudies();
  void studyTick;
  const localCands = listCandidates();
  const latest = localCands.length > 0 ? localCands[localCands.length - 1] : null;
  const latestDeg = latest ? degreeOf(latest.nodes, latest.links) : [];
  const latestMaxDeg = latestDeg.length > 0 ? Math.max(...latestDeg) : 0;

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {() => (
        <div className="page">
          <h2>Synthesize</h2>
          <p className="muted">
            Topology synthesis over candidate graph producers — a candidate
            graph only. Certificates, qualified performance, routing proof,
            Pareto membership and recommendations come from the ordinary
            compile → verify → evaluate pipeline, never from a generator.
            See also <Link to={ROUTES.candidates(projectId)}>Candidates</Link>.
          </p>

          <section className="card">
            <h3>Method — what each claims</h3>
            <div className="method-grid">
              {METHODS.map((m) => (
                <button
                  key={m.id}
                  className={`method-card${m.id === methodId ? ' active' : ''}`}
                  onClick={() => pickMethod(m.id)}
                  aria-pressed={m.id === methodId}
                >
                  <b>{m.label}</b>
                  <span className="muted">{m.tagline}</span>
                  <span className="muted">completeness: <b>{m.completeness}</b></span>
                  <span className="muted">engine: {m.engine} · {m.solverStatus}</span>
                </button>
              ))}
            </div>
            <p className="muted">{method.claim}</p>
            <p className="muted">{method.completenessNote}</p>
          </section>

          <section className="card">
            <h3>Synthesis problem</h3>
            <div className="form-row">
              <label>Base topology
                <select value={base} onChange={(e) => setBase(e.target.value as 'mesh' | 'explicit' | 'previous-candidate')}>
                  <option value="mesh">Mesh (k×k seed)</option>
                  <option value="explicit">Explicit topology (imported graph)</option>
                  <option value="previous-candidate">Previous candidate</option>
                </select>
              </label>
              <label>Traffic authority
                <select value={traffic} onChange={(e) => setTraffic(e.target.value)}>
                  <option value="current-workload">Current workload</option>
                  <option value="traffic-matrix">Traffic matrix file</option>
                  <option value="scenario">Selected scenario</option>
                </select>
              </label>
              {traffic !== 'current-workload' && (
                <label>Traffic reference
                  <input value={trafficRef} onChange={(e) => setTrafficRef(e.target.value)} placeholder="path or scenario id" />
                </label>
              )}
            </div>
            <div className="form-row">
              <label>Edge budget (max links)
                <input type="number" value={maxEdges} onChange={(e) => setMaxEdges(Number(e.target.value) || 0)} />
              </label>
              <span className="muted">Constraints enforced by the adapter: node count, radix, edge budget, max link length, connectivity, layout, express policy.</span>
            </div>
            <h4>{method.label} parameters</h4>
            <div className="form-grid">
              {method.params.map((p) => (
                <label key={p.name}>{p.label}
                  {p.kind === 'select' ? (
                    <select value={String(values[p.name] ?? p.def)} onChange={(e) => setParam(p.name, e.target.value)}>
                      {(p.options ?? []).map((o) => (
                        <option key={String(o)} value={String(o)}>{String(o)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="number"
                      value={values[p.name] as number ?? p.def}
                      min={p.min}
                      max={p.max}
                      step={p.kind === 'float' ? 0.1 : 1}
                      onChange={(e) => setParam(p.name, Number(e.target.value))}
                    />
                  )}
                  <small className="muted">{p.help}</small>
                </label>
              ))}
            </div>
          </section>

          <section className="card">
            <h3>Execution — canonical pipeline, never in-browser</h3>
            {cli ? (
              <>
                <p className="muted">Exact CLI invocation for this problem:</p>
                <pre className="cli">{cli.join(' ')}</pre>
              </>
            ) : (
              <p className="muted">{method.cliNote}</p>
            )}
            <div className="form-row">
              <label>Study name
                <input value={studyName} onChange={(e) => setStudyName(e.target.value)} placeholder={`${method.label} study`} />
              </label>
              <button className="btn btn-primary" onClick={launchLive}>Launch synthesis</button>
              <button className="btn" onClick={save}>Save study draft</button>
            </div>
            <JobProgress job={job} />
            {liveState === 'unavailable' && (
              <p className="muted">Live synthesis maturity: RESEARCH — gateway route pending. Nothing below is substituted for a backend result.</p>
            )}
            {synthesisId && live.result.state === 'ready' && (
              <LiveSynthesisResult result={live.result.data} projectId={projectId} />
            )}
            <p className="muted">
              Studio never executes a synthesis engine and never invents a
              generator score. Run the command above (or the canonical
              adapter), then import the resulting graph for inspection.
            </p>
            {studies.length > 0 && (
              <p className="muted">{studies.length} local study draft{studies.length === 1 ? '' : 's'} (authoring aids — not science).</p>
            )}
          </section>

          <section className="card">
            <h3>Import generated graph</h3>
            <p className="muted">
              Paste the generated link list (u-v pairs, one per line) from the
              synthesis run output. A disconnected import is kept for
              inspection but can never be promoted.
            </p>
            <textarea
              rows={6}
              cols={30}
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder={'0-1\n0-4\n1-2\n…'}
              aria-label="Generated link list"
            />
            <div className="form-row">
              <label>Generator score (optional)
                <input value={importScore} onChange={(e) => setImportScore(e.target.value)} placeholder="traffic-weighted hops" />
              </label>
              <label>Seed (optional)
                <input value={importSeed} onChange={(e) => setImportSeed(e.target.value)} placeholder="7" />
              </label>
              <button className="btn" onClick={importGraph}>Import for inspection</button>
            </div>
            {importErrors.length > 0 && (
              <ul className="bad">{importErrors.map((e, i) => <li key={i}>{e}</li>)}</ul>
            )}
          </section>

          {latest && (
            <section className="card">
              <h3>Latest import — base vs generated</h3>
              <TopologyGraph
                base={baseLinks.length > 0 ? baseLinks : latest.links}
                candidate={baseLinks.length > 0 ? latest.links : null}
                nodes={latest.nodes}
                k={k}
                title={baseLinks.length > 0 ? 'base mesh vs imported graph' : 'imported graph (no mesh base at this size)'}
              />
              <div className="kv"><span>links</span><span>{fmtNum(latest.links.length)}</span></div>
              <div className="kv"><span>max degree / radix</span><span>{latestMaxDeg}</span></div>
              <div className="kv">
                <span>connectivity</span>
                <span>{isConnected(latest.nodes, latest.links) ? <StatusBadge status="CONNECTED" /> : <StatusBadge status="DISCONNECTED — promotion refused" />}</span>
              </div>
              {latest.generatorObjective != null && (
                <ScientificValue
                  value={latest.generatorObjective}
                  unit="weighted hops"
                  epistemic="MODELLED"
                  source="imported generator score"
                  qualification="NOT QUALIFIED — screening only, never measured performance"
                />
              )}
              <div className="kv"><span>compile state</span><span><StatusBadge status="NOT_COMPILED" /> <EpistemicChip value={null} /></span></div>
              <div className="kv"><span>verification state</span><span><StatusBadge status="NOT_VERIFIED" /></span></div>
              <div className="kv"><span>backend result</span><span><StatusBadge status="NOT_YET_RUN" /></span></div>
              <p className="muted">
                Generator objective above is the analytical screening score.
                Measured product objectives exist only after compile → verify →
                qualified backend execution. Full record in{' '}
                <Link to={ROUTES.candidates(projectId)}>Candidates</Link>.
              </p>
            </section>
          )}

          {notice && <p className="good">{notice}</p>}
          {error && <ErrorBox error={error} />}
          {baseLinks.length > 0 && (
            <details className="card">
              <summary>Base mesh link list ({baseLinks.length} links)</summary>
              <pre className="cli">{serializeLinks(baseLinks)}</pre>
            </details>
          )}
        </div>
      )}
    </AsyncView>
  );
}

/** Live synthesis result (§24): generator objective and measured
 * product objectives are SEPARATE fields. A candidate is never called
 * verified because the generator likes it. */
function LiveSynthesisResult({
  result, projectId,
}: {
  result: SynthesisResultView;
  projectId: string;
}): ReactElement {
  return (
    <section className="card">
      <h3>Synthesis {result.synthesis_id} — {result.method}</h3>
      <div className="kv"><span>generated</span><span>{fmtNum(result.generated_count)}</span></div>
      <div className="kv"><span>evaluated</span><span>{fmtNum(result.evaluated_count)}</span></div>
      {result.completeness && (
        <div className="kv">
          <span>search completeness</span>
          <span>{result.completeness.kind} — {result.completeness.wording} (evaluated {fmtNum(result.completeness.evaluated)}{result.completeness.declared != null ? ` of ${fmtNum(result.completeness.declared)} declared` : ''})</span>
        </div>
      )}
      <table className="live-table">
        <thead>
          <tr>
            <th>candidate</th><th>solver</th><th>generator objective</th>
            <th>measured product objective</th><th>compile / verify</th>
          </tr>
        </thead>
        <tbody>
          {result.candidates.map((c) => (
            <tr key={c.candidate_id}>
              <td>
                <Link to={ROUTES.candidateDetail(projectId, c.candidate_id)}>{c.candidate_id}</Link>
              </td>
              <td className="muted">{c.solver_status}</td>
              <td>
                {c.generator_objective_value != null ? (
                  <ScientificValue
                    value={c.generator_objective_value}
                    unit={c.generator_objective_name ?? 'generator score'}
                    epistemic="MODELLED"
                    source={`${c.method} generator`}
                    qualification="NOT QUALIFIED — screening only"
                  />
                ) : <span className="muted">—</span>}
              </td>
              <td>
                {c.measured_cycles != null ? (
                  <ScientificValue
                    value={c.measured_cycles}
                    unit="cycles"
                    epistemic="SIMULATED"
                    source={c.measured_backend ?? 'backend'}
                    qualification="see evidence"
                  />
                ) : <span className="muted">not yet measured</span>}
              </td>
              <td className="muted">
                {c.compile_status ?? 'NOT_COMPILED'} / {c.verification_status ?? 'NOT_VERIFIED'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
