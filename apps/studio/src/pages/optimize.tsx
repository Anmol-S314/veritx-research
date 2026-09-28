import { useEffect, useState, type ReactElement } from 'react';
import { api, type JobView, type OptimizationView, type RevisionView } from '../api';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync,
  useJobPoll, useStudio,
} from '../studio';
import { Hash, StatusBadge, fmtNum } from '../components/badges';
import OptimizeView from '../components/OptimizeView';
import OptimizationAnalysis from '../components/OptimizationAnalysis';
import DesignSpace from '../components/DesignSpace';
import StudyVerdict from '../StudyVerdict';

// NO hard-coded control list. Every parameter, and every value the UI offers,
// comes from GET /optimization/capabilities, which is derived from canonical
// backend authority (GUIDED_PARAMS, the certified metric registry, and a probe
// that measures whether a knob actually reaches executed semantics).
//
// `link_width` is the only qualified numeric domain whose value domain can be
// offered as a finite choice, and even that is not enumerated by the backend:
// it is a validated range. So the UI offers a small set of plausible values
// and states that they are UI choices, not a backend enumeration.

/** §17 objective groups, derived from metric names. The catalog stays the
authority (only listed metrics are selectable); grouping is a UI
convenience, never a new metric. */
function objectiveGroup(metric: string): string {
  const m = metric.toLowerCase();
  if (m.includes('ttft') || m.includes('serving') || m.includes('decode')) return 'Serving';
  if (m.includes('critical_path') || m.includes('request_latency')
      || m.includes('utilization') || m.includes('makespan')) {
    return m.includes('makespan') && !m.includes('request') ? 'System / Model' : 'Performance model';
  }
  if (m.includes('read_latency') || m.includes('write_latency')
      || m.includes('dram') || m.includes('memory')) return 'Memory';
  if (m.includes('exposed') || m.includes('per_rank') || m.includes('system')) return 'System';
  if (m.includes('energy') || m.includes('power')) return 'Energy / power';
  return 'Network';
}

/** Epistemic class derived from the metric name. Certified network metrics
ride authenticated backend evidence (SIMULATED); dependency-model metrics
are MODELLED and never measured. Unknown names state the producer only. */
function objectiveEpistemic(metric: string): string {
  const m = metric.toLowerCase();
  if (m.includes('critical_path') || m.includes('request_latency')
      || m.includes('utilization')) return 'MODELLED · UNCALIBRATED';
  if (m.includes('energy') || m.includes('power')) return 'fidelity-gated estimate';
  return 'SIMULATED · QUALIFIED';
}

function objectiveUnit(metric: string): string {
  if (metric.endsWith('_ns')) return 'ns';
  if (metric.endsWith('_cycles')) return 'cycles';
  if (metric === 'makespan' || metric === 'critical_path') return 's (model)';
  if (metric === 'resource_utilization_max') return 'fraction';
  if (metric === 'request_latency_mean') return 's (model)';
  return '';
}

/** §18: model-derived metrics answer the dependency model, not the fabric.
A fabric-only domain cannot causally move them. */
/** Group catalog metrics for the §17 selector. Order is fixed and
meaningful (Network → System → Memory → Performance → Serving →
Energy → Other); within a group, catalog order is preserved. */
function groupMetrics(
  metrics: { metric: string; producer_id?: string | null }[],
): { group: string; metric: string; producer_id?: string | null }[] {
  const order = ['Network', 'System', 'Memory', 'Performance model',
    'System / Model', 'Serving', 'Energy / power', 'Other'];
  return metrics
    .map((m) => ({
      group: objectiveGroup(m.metric),
      metric: m.metric,
      producer_id: m.producer_id,
    }))
    .sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group));
}

function effectivenessWarning(
  metric: string,
  domain: { name: string }[],
): string | null {
  const m = metric.toLowerCase();
  const modelMetric = m.includes('critical_path') || m.includes('request_latency')
    || m.includes('utilization');
  if (!modelMetric) return null;
  const fabricOnly = domain.length > 0
    && domain.every((d) => ['link_width', 'topology_family', 'concentration', 'radix']
      .includes(d.name));
  if (fabricOnly) {
    return `NO DIRECT EFFECT: ${metric} is a dependency-model metric — fabric knobs `
      + `(${domain.map((d) => d.name).join(', ')}) cannot causally move it under the `
      + 'current model. This study would measure no distinction.';
  }
  return null;
}

export function Optimize({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const caps = useAsync(() => api.optimizationCapabilities(), []);
  const [widths, setWidths] = useState<number[]>([32, 64, 128]);
  // One entry per searchable GUIDED parameter. Only parameters the capability
  // endpoint marks qualified can ever be written here.
  const [topologies, setTopologies] = useState<string[]>([]);
  const [concentrations, setConcentrations] = useState<number[]>([]);
  const [radixText, setRadixText] = useState<string>('');
  const [method, setMethod] = useState<string>('grid');
  const [adopting, setAdopting] = useState<boolean>(false);
  const [adoptedFrom, setAdoptedFrom] = useState<string | null>(null);
  const [seed, setSeed] = useState<number>(1);
  const [maxCandidates, setMaxCandidates] = useState<number>(0);
  const [ceilingOn, setCeilingOn] = useState(false);
  const [ceiling, setCeiling] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [optimizationId, setOptimizationId] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const onTerminal = (job: JobView): void => {
    setOptimizationId(job.result?.optimization_id ?? null);
    project.reload();
    refreshProjects();
  };
  const job = useJobPoll(jobId, onTerminal);
  const opt = useAsync(
    () => (optimizationId
      ? api.optimization(optimizationId)
      : Promise.reject(new Error('no optimization'))),
    [optimizationId],
  );

  const capabilityDoc = caps.result.state === 'ready' ? caps.result.data : null;
  // The authority on which dimensions may be searched. Nothing is offered
  // outside this set — see the capability probe, which MEASURES whether a knob
  // reaches executed semantics.
  const qualified = new Set(capabilityDoc?.qualified_parameters ?? []);
  // Federated objective selector: generated from the certified metric
  // catalog, never hardcoded. Each objective shows its semantic family and
  // answering producer beside it; independent families may be combined,
  // same-family metrics are one ranking, never a frontier.
  const certifiedMetrics = capabilityDoc?.certified_metrics ?? [];
  const families = capabilityDoc?.objective_semantic_families ?? {};
  const [objectiveMetric, setObjectiveMetric] = useState<string | null>(null);
  const [constraintMetric, setConstraintMetric] = useState<string>('completion_cycles');
  const activeObjective = objectiveMetric
    ?? certifiedMetrics[0]?.metric
    ?? Object.keys(families)[0]
    ?? 'completion_cycles';
  const activeFamily = families[activeObjective] ?? '—';
  const activeProducer = certifiedMetrics.find((m) => m.metric === activeObjective)?.producer_id ?? '—';
  const linkWidthQualified = qualified.has('link_width');
  const baseNoc = (project.result.state === 'ready'
    ? (project.result.data.active_revision?.design?.noc_guided ?? null)
    : null) as Record<string, unknown> | null;

  const parsedRadix = radixText
    .split(',')
    .map((t) => Number(t.trim()))
    .filter((n) => Number.isFinite(n) && Number.isInteger(n) && n > 0);

  // The DOMAIN, built only from qualified parameters the user enabled.
  // Canonical ordering is the backend's business; this is the declared set.
  const domain: { name: string; values: (string | number)[] }[] = [];
  if (linkWidthQualified && widths.length > 0) {
    domain.push({ name: 'link_width', values: widths });
  }
  if (qualified.has('topology_family') && topologies.length > 0) {
    domain.push({ name: 'topology_family', values: topologies });
  }
  if (qualified.has('concentration') && concentrations.length > 0) {
    domain.push({ name: 'concentration', values: concentrations });
  }
  if (qualified.has('radix') && parsedRadix.length > 0) {
    domain.push({ name: 'radix', values: parsedRadix });
  }
  // Raw Cartesian size, computed BEFORE launch so the user sees the cost.
  const candidateCount = domain.reduce((n, d) => n * d.values.length, 0);
  // §20 search strategy: one compilation per candidate, one backend analysis
  // per candidate per objective question. Shown before launch.
  const compilationCount = candidateCount;
  const analysisCount = candidateCount; // single objective, single question
  const effectWarning = effectivenessWarning(activeObjective, domain);
  const groupedObjectives = groupMetrics(certifiedMetrics);

  /** Adopt a studied candidate as the DRAFT, then send the user to Design.
   *
   *  The immutable base revision is NOT touched: `use_candidate` re-applies the
   *  candidate's GUIDED patch to the BASE REVISION's request, refuses if the
   *  resulting design hash differs from the study's, and writes only the
   *  draft. A new revision exists only after an explicit Compile.
   */
  const adopt = async (candidateId: string): Promise<void> => {
    if (!optimizationId) return;
    setAdopting(true);
    setError(null);
    try {
      const draft = await api.useCandidate(optimizationId, candidateId);
      setAdoptedFrom(
        `Derived from optimization ${optimizationId}, candidate ${candidateId}`
        + ` (draft is dirty: ${String((draft as { dirty?: boolean }).dirty)})`);
      project.reload();
      refreshProjects();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setAdopting(false);
    }
  };

  const start = async (): Promise<void> => {
    const currentId = project.result.state === 'ready'
      ? project.result.data.active_revision_id
      : null;
    if (!currentId || domain.length === 0) return;
    setError(null);
    setOptimizationId(null);
    try {
      const submitted = await api.optimize(currentId, {
        domain,
        // ONE semantic objective. completion_cycles/time/ns are the same
        // authenticated window in different units, so requesting two of them
        // would invent a trade-off. This is "minimize completion time",
        // expressed in the unit the certified registry measures it in.
        objectives: [{ metric: activeObjective, direction: 'MIN' }],
        // A hard constraint is opt-in: an arbitrary ceiling that no
        // measured candidate can meet makes the whole study ineligible,
        // which reads as a broken optimizer rather than a strict bound.
        constraints: ceilingOn && ceiling > 0
          ? [{ metric: constraintMetric, op: '<=', threshold: ceiling }]
          : [],
        method,
        selection: 'min_first_objective',
        // A seeded random study is only reproducible with an explicit seed;
        // the backend requires one, so it is never omitted.
        seed: method === 'random' ? seed : null,
        budget: maxCandidates > 0 ? { max_candidates: maxCandidates } : {},
      });
      setJobId(submitted.job_id);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const baseRevision = p.active_revision ?? undefined;
        const active = baseRevision;
        const running = job !== null && !['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state);
        return (
          <div className="page">
            <h2>Optimize</h2>
            <section className="card">
              <h3>Study definition</h3>
              <p className="muted">
                Base revision {active?.display_name ?? '—'} (immutable). Three
                authorities stay separate: product requirements, optimization
                constraints, measured objectives.
              </p>
              {!capabilityDoc && (
                <p className="muted">
                  Loading optimization capabilities from the backend…
                </p>
              )}
              {capabilityDoc && (
                <DesignSpace
                  caps={capabilityDoc}
                  base={baseNoc}
                  widths={widths} setWidths={setWidths}
                  topologies={topologies} setTopologies={setTopologies}
                  concentrations={concentrations}
                  setConcentrations={setConcentrations}
                  radixText={radixText} setRadixText={setRadixText}
                  method={method} setMethod={setMethod}
                  seed={seed} setSeed={setSeed}
                  maxCandidates={maxCandidates}
                  setMaxCandidates={setMaxCandidates}
                  candidateCount={candidateCount}
                />
              )}
              <div className="form-row">
                <label>
                  Objective — from the federated metric catalog, grouped by meaning
                  <select
                    value={activeObjective}
                    onChange={(e) => setObjectiveMetric(e.target.value)}
                    aria-label="Objective metric"
                  >
                    {certifiedMetrics.length === 0 && (
                      <option value={activeObjective}>{activeObjective}</option>
                    )}
                    {Array.from(new Set(groupedObjectives.map((g) => g.group))).map((grp) => (
                      <optgroup key={grp} label={grp}>
                        {groupedObjectives.filter((g) => g.group === grp).map((g) => (
                          <option key={g.metric} value={g.metric}>
                            {g.metric} — family {families[g.metric] ?? '—'} · {g.producer_id ?? '—'}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                  <small className="muted">
                    Producer: {activeProducer} · question family: {activeFamily} ·{' '}
                    {objectiveEpistemic(activeObjective)}
                    {objectiveUnit(activeObjective) ? ` · unit: ${objectiveUnit(activeObjective)}` : ''}.
                    Same-family metrics are one ranking, never a Pareto frontier.
                  </small>
                </label>
              </div>
              {effectWarning && (
                <p className="warn" role="alert">{effectWarning}</p>
              )}
              <div className="form-row">
                <label>
                  Hard constraint
                  <span className="check-row">
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={ceilingOn}
                        onChange={(e) => setCeilingOn(e.target.checked)}
                      />
                      <select
                        value={constraintMetric}
                        disabled={!ceilingOn}
                        onChange={(e) => setConstraintMetric(e.target.value)}
                        aria-label="Constraint metric"
                      >
                        {certifiedMetrics.length === 0 && (
                          <option value={constraintMetric}>{constraintMetric}</option>
                        )}
                        {Array.from(new Set(groupedObjectives.map((g) => g.group))).map((grp) => (
                          <optgroup key={grp} label={grp}>
                            {groupedObjectives.filter((g) => g.group === grp).map((g) => (
                              <option key={g.metric} value={g.metric}>
                                {g.metric}{objectiveUnit(g.metric) ? ` (${objectiveUnit(g.metric)})` : ''}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>{' '}
                      ≤
                    </label>
                    <input
                      type="number"
                      value={ceiling === 0 ? '' : ceiling}
                      placeholder="measured"
                      disabled={!ceilingOn}
                      onChange={(e) => setCeiling(Number(e.target.value) || 0)}
                    />
                  </span>
                  <small className="muted">
                    Optional, from the same metric catalog — never a hardcoded
                    ceiling. Every candidate that violates it is ineligible —
                    no Pareto set and no selection. Leave it off to rank the
                    measured candidates outright. Product requirements stay
                    separate (see the candidate table) — do not mix them.
                  </small>
                </label>
              </div>
              {candidateCount > 0 && (
                <p className="muted">
                  Before launch: {candidateCount} candidate architecture{candidateCount === 1 ? '' : 's'} ·{' '}
                  {compilationCount} compilations · {analysisCount} backend analys{analysisCount === 1 ? 'is' : 'es'} ({activeProducer}).
                  Each candidate compiles once; each required evaluation
                  question executes at most once.
                </p>
              )}
              <div className="form-row">
                <button className="btn btn-primary" disabled={!active || running || !!effectWarning} onClick={start}>
                  {running ? 'Optimizing…' : 'Launch study'}
                </button>
                {(() => {
                  const measured = [...p.runs]
                    .reverse()
                    .find((r) => typeof r.completion_cycles === 'number');
                  return measured ? (
                    <span className="muted">
                      last measured run: {fmtNum(measured.completion_cycles)}{' '}
                      cycles ({measured.display_name ?? measured.run_id})
                    </span>
                  ) : null;
                })()}
              </div>
              {adoptedFrom && (
                <p className="muted">
                  {adoptedFrom} — open{' '}
                  <Link to={`/p/${projectId}/design`}>Design</Link> to review,
                  then Compile to create the next immutable revision.
                </p>
              )}
              {error && <ErrorBox error={error} />}
              <JobProgress job={job} />
            </section>
            {optimizationId && opt.result.state === 'ready' && (
              <StudyResult
                optimization={opt.result.data}
                baseRevision={baseRevision}
                multiObjectiveAvailable={
                  capabilityDoc?.multi_objective_available ?? true}
                onUseCandidate={adopt}
                usingCandidate={adopting}
              />
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

function StudyResult({
  optimization,
  baseRevision,
  multiObjectiveAvailable,
  onUseCandidate,
  usingCandidate,
}: {
  optimization: OptimizationView;
  baseRevision: RevisionView | undefined;
  multiObjectiveAvailable: boolean;
  onUseCandidate: (candidateId: string) => Promise<void>;
  usingCandidate: boolean;
}): ReactElement {
  return (
    <div className="page">
      <StudyVerdict
        study={optimization.study}
        baseGuided={(baseRevision?.design?.noc_guided ?? null) as Record<string, unknown> | null}
        multiObjective={multiObjectiveAvailable}
      />
      <section className="card">
        <h3>Study {optimization.optimization_id}</h3>
        <div className="kv"><span>base revision</span><span>{optimization.base_revision_id}</span></div>
        <div className="kv"><span>result class</span><span>{optimization.study.result_class}</span></div>
        <div className="kv"><span>selected candidate</span><span>{optimization.selected_candidate_id ?? '—'}</span></div>
        <div className="kv"><span>{multiObjectiveAvailable ? 'pareto members' : 'top-ranked (single-objective ranking)'}</span><span>{multiObjectiveAvailable ? optimization.study.pareto_ids.length : '—'}</span></div>
        <div className="kv"><span>metric registry</span><Hash value={optimization.study.metric_registry_id} /></div>
        {optimization.study.selection_rationale && (
          <p className={optimization.selected_candidate_id ? 'muted' : 'warn'}>
            {optimization.study.selection_rationale}
          </p>
        )}
        {optimization.candidate_runs.length > 0 && (
          <p className="muted">
            {optimization.candidate_runs.length} candidates measured by{' '}
            {optimization.candidate_runs.find((c) => c.evaluation_authority)
              ?.evaluation_authority ?? 'the certified backend'}.
          </p>
        )}
      </section>
      {optimization.candidate_runs.some((c) => c.run_id) && (
        <section className="card">
          <h3>Candidate runs</h3>
          <table className="live-table">
            <thead><tr><th>candidate</th><th>performance result</th><th>run</th></tr></thead>
            <tbody>
              {optimization.candidate_runs.map((c) => (
                <tr key={c.candidate_id}>
                  <td>{c.candidate_id}</td>
                  <td><Hash value={c.performance_result_id} /></td>
                  <td>
                    {c.run_id
                      ? <Link className="link" to={`/runs/${c.run_id}`}>{c.run_id}</Link>
                      : <span className="muted">candidate execution — evidence in study</span>}
                    <div className="muted">{c.evidence_kind} · {c.evaluation_status ?? '—'}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {optimization.candidate_evidence_note && (
            <p className="muted">{optimization.candidate_evidence_note}</p>
          )}
        </section>
      )}
      <OptimizeView
        optimization={optimization.study}
        design={baseRevision?.design ?? null}
        multiObjectiveAvailable={multiObjectiveAvailable}
        onUseCandidate={onUseCandidate}
        usingCandidate={usingCandidate}
      />
      {optimization.study.result_class === 'CERTIFIED_PRODUCT' &&
        optimization.study.candidates.some(
          (c) => c.evaluation_status === 'EVALUATED',
        ) && (
          <OptimizationAnalysis optimization={optimization.study} />
        )}
    </div>
  );
}

export function Compare({ projectId }: { projectId: string }): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  const [a, setA] = useState<string>('');
  const [b, setB] = useState<string>('');
  const [pair, setPair] = useState<{ a: string; b: string } | null>(null);

  useEffect(() => {
    if (project.result.state === 'ready') {
      const evaluated = project.result.data.runs.filter((r) => r.status === 'EVALUATED');
      if (evaluated.length >= 2 && !a && !b) {
        setA(evaluated[evaluated.length - 2].run_id);
        setB(evaluated[evaluated.length - 1].run_id);
      }
    }
  }, [project.result, a, b]);

  const comparison = useAsync(
    () => (pair ? api.compare(pair.a, pair.b) : Promise.reject(new Error('pick two runs'))),
    [pair?.a, pair?.b],
  );

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const evaluated = p.runs.filter((r) => r.status === 'EVALUATED');
        return (
          <div className="page">
            <h2>Compare</h2>
            {evaluated.length < 2 ? (
              <p className="muted">Two evaluated runs are required to compare.</p>
            ) : (
              <>
                <section className="card">
                  <div className="form-row">
                    <label>Run A
                      <select value={a} onChange={(e) => setA(e.target.value)}>
                        {evaluated.map((r) => <option key={r.run_id} value={r.run_id}>{r.display_name ?? r.run_id}</option>)}
                      </select>
                    </label>
                    <label>Run B
                      <select value={b} onChange={(e) => setB(e.target.value)}>
                        {evaluated.map((r) => <option key={r.run_id} value={r.run_id}>{r.display_name ?? r.run_id}</option>)}
                      </select>
                    </label>
                    <button className="btn" onClick={() => setPair({ a, b })} disabled={!a || !b || a === b}>
                      Compare
                    </button>
                  </div>
                </section>
                {pair && comparison.result.state === 'ready' && (
                  <section className="card">
                    <h3>{comparison.result.data.a.display_name} vs {comparison.result.data.b.display_name}</h3>
                    <div className={`compat compat-${comparison.result.data.compatibility.compatible ? 'ok' : 'bad'}`}>
                      <strong>
                        {comparison.result.data.compatibility.compatible
                          ? 'Comparable scenario'
                          : 'NOT DIRECTLY COMPARABLE'}
                      </strong>
                      <ul className="muted">
                        <li>same workload: {String(comparison.result.data.compatibility.same_workload)}</li>
                        <li>same backend: {String(comparison.result.data.compatibility.same_backend)}</li>
                        <li>both qualified: {String(comparison.result.data.compatibility.both_qualified)}</li>
                        {comparison.result.data.compatibility.reasons.map((reason, i) => (
                          <li key={i} className="bad">{reason}</li>
                        ))}
                        <li>{comparison.result.data.compatibility.metric_units}</li>
                      </ul>
                    </div>
                    <table className="live-table">
                      <thead><tr><th>quantity</th><th>A</th><th>B</th><th>semantics</th></tr></thead>
                      <tbody>
                        <tr><td>topology</td><td>{String(comparison.result.data.a.noc?.topology_family ?? '—')}</td><td>{String(comparison.result.data.b.noc?.topology_family ?? '—')}</td><td className="muted">declared</td></tr>
                        <tr><td>link width</td><td>{String(comparison.result.data.a.noc?.link_width ?? '—')}</td><td>{String(comparison.result.data.b.noc?.link_width ?? '—')}</td><td className="muted">declared</td></tr>
                        <tr><td>VC count</td><td>{String(comparison.result.data.a.locked_derived?.vc_count ?? '—')}</td><td>{String(comparison.result.data.b.locked_derived?.vc_count ?? '—')}</td><td className="muted">derived</td></tr>
                        <tr><td>requirements</td><td><StatusBadge status={comparison.result.data.a.requirements_pass ? 'SATISFIED' : 'VIOLATED'} /></td><td><StatusBadge status={comparison.result.data.b.requirements_pass ? 'SATISFIED' : 'VIOLATED'} /></td><td className="muted">product</td></tr>
                        {comparison.result.data.rows.map((row) => (
                          <tr key={row.key}>
                            <td>{row.key}</td>
                            <td>{fmtNum(row.a)}</td>
                            <td>{fmtNum(row.b)}</td>
                            <td className="muted">
                              {row.verdict ?? (row.comparable ? 'comparable' : 'not comparable')}
                              {row.differs ? ` · differs: ${row.differs}` : ''}
                              {row.delta_b_minus_a != null ? ` · Δ ${fmtNum(row.delta_b_minus_a)}` : ''}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="muted">{comparison.result.data.note}</p>
                  </section>
                )}
                {pair && comparison.result.state === 'error' && (
                  <ErrorBox error={comparison.result.error} />
                )}
              </>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}
