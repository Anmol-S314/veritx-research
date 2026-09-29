// *
// Rationale: docs/decisions/studio.md
import { useEffect, useState, type ReactElement } from 'react';
import {
  api,
  type CompareView as CompareData,
  type OptimizationSummary,
  type RevisionSummary,
  type RunSummary,
} from '../api';
import { AsyncView, Link, useAsync } from '../studio';
import { Hash, StatusBadge, fmtNum, humanize } from './badges';
import { ScientificValue } from './ScientificValue';

type Mode = 'run' | 'revision' | 'candidate' | 'candidate-revision';

const MODES: { id: Mode; label: string }[] = [
  { id: 'run', label: 'Run ↔ Run' },
  { id: 'revision', label: 'Revision ↔ Revision' },
  { id: 'candidate', label: 'Candidate ↔ Candidate' },
  { id: 'candidate-revision', label: 'Candidate ↔ Revision' },
];

function runLabel(r: RunSummary): string {
  return r.display_name ?? r.run_id;
}

/** Field-level topology diff between two declared `noc` records. */
function TopologyDiff({ a, b }: {
  a: Record<string, unknown> | null;
  b: Record<string, unknown> | null;
}): ReactElement {
  const keys = Array.from(new Set([
    ...Object.keys(a ?? {}),
    ...Object.keys(b ?? {}),
  ])).sort();
  if (keys.length === 0) {
    return <p className="muted">No declared topology fields on either side.</p>;
  }
  return (
    <table className="live-table">
      <thead><tr><th>field</th><th>A</th><th>B</th><th>diff</th></tr></thead>
      <tbody>
        {keys.map((k) => {
          const va = a?.[k];
          const vb = b?.[k];
          const same = JSON.stringify(va) === JSON.stringify(vb);
          return (
            <tr key={k} className={same ? '' : 'differs'}>
              <td>{humanize(k)}</td>
              <td>{va == null ? '—' : String(va)}</td>
              <td>{vb == null ? '—' : String(vb)}</td>
              <td className="muted">{same ? 'same' : 'DIFFERS'}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function recordRows(rec: Record<string, unknown> | null): [string, unknown][] {
  if (!rec) return [];
  return Object.keys(rec).sort().map((k) => [k, rec[k]]);
}

export default function CompareView({ projectId }: {
  projectId: string;
}): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  const [mode, setMode] = useState<Mode>('run');
  const [tab, setTab] = useState<
    'design' | 'structure' | 'performance' | 'requirements' | 'verification' | 'evidence'
  >('performance');
  // Run↔Run selections.
  const [runA, setRunA] = useState('');
  const [runB, setRunB] = useState('');
  // Revision↔Revision selections.
  const [revA, setRevA] = useState('');
  const [revB, setRevB] = useState('');
  const [revRunA, setRevRunA] = useState('');
  const [revRunB, setRevRunB] = useState('');
  // Candidate selections (optimization → candidate run).
  const [optA, setOptA] = useState('');
  const [optB, setOptB] = useState('');
  const [candRunA, setCandRunA] = useState('');
  const [candRunB, setCandRunB] = useState('');
  const [pair, setPair] = useState<{ a: string; b: string } | null>(null);

  const revRunsA = useAsync(
    () => (revA ? api.runs({ revisionId: revA }) : Promise.reject(new Error('pick a revision'))),
    [revA],
  );
  const revRunsB = useAsync(
    () => (revB ? api.runs({ revisionId: revB }) : Promise.reject(new Error('pick a revision'))),
    [revB],
  );
  const candA = useAsync(
    () => (optA ? api.optimization(optA) : Promise.reject(new Error('pick a study'))),
    [optA],
  );
  const candB = useAsync(
    () => (optB ? api.optimization(optB) : Promise.reject(new Error('pick a study'))),
    [optB],
  );
  const comparison = useAsync(
    () => (pair ? api.compare(pair.a, pair.b) : Promise.reject(new Error('pick two runs'))),
    [pair?.a, pair?.b],
  );

  useEffect(() => {
    if (project.result.state === 'ready' && !runA && !runB) {
      const evaluated = project.result.data.runs.filter((r) => r.status === 'EVALUATED');
      if (evaluated.length >= 2) {
        setRunA(evaluated[evaluated.length - 2].run_id);
        setRunB(evaluated[evaluated.length - 1].run_id);
      }
    }
  }, [project.result, runA, runB]);

  const launchLabel =
    mode === 'run' ? (!runA || !runB || runA === runB)
    : mode === 'revision' ? (!revRunA || !revRunB || revRunA === revRunB)
    : mode === 'candidate' ? (!candRunA || !candRunB || candRunA === candRunB)
    : (!candRunA || !revRunB || candRunA === revRunB);

  const launch = (): void => {
    if (mode === 'run') setPair({ a: runA, b: runB });
    else if (mode === 'revision') setPair({ a: revRunA, b: revRunB });
    else if (mode === 'candidate') setPair({ a: candRunA, b: candRunB });
    else setPair({ a: candRunA, b: revRunB });
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const evaluated = p.runs.filter((r) => r.status === 'EVALUATED');
        const revisions: RevisionSummary[] = p.revisions;
        const optimizations: OptimizationSummary[] = p.optimizations;
        const runOptions = (rs: RunSummary[]): RunSummary[] =>
          rs.filter((r) => r.status === 'EVALUATED');
        return (
          <div className="page">
            <div className="page-head">
              <h2>Compare</h2>
            </div>
            <div className="segmented" role="tablist" aria-label="Compare mode">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  role="tab"
                  aria-selected={mode === m.id}
                  className={mode === m.id ? 'selected' : ''}
                  onClick={() => { setMode(m.id); setPair(null); }}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {mode === 'run' && (
              evaluated.length < 2 ? (
                <p className="muted">Two evaluated runs are required to compare.</p>
              ) : (
                <section className="card">
                  <div className="form-row">
                    <label>Run A
                      <select value={runA} onChange={(e) => setRunA(e.target.value)}>
                        {evaluated.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>)}
                      </select>
                    </label>
                    <label>Run B
                      <select value={runB} onChange={(e) => setRunB(e.target.value)}>
                        {evaluated.map((r) => <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>)}
                      </select>
                    </label>
                  </div>
                </section>
              )
            )}

            {mode === 'revision' && (
              <section className="card">
                <div className="form-row">
                  <label>Revision A
                    <select value={revA} onChange={(e) => { setRevA(e.target.value); setRevRunA(''); }}>
                      <option value="">—</option>
                      {revisions.map((r) => <option key={r.revision_id} value={r.revision_id}>{r.display_name}</option>)}
                    </select>
                  </label>
                  <label>Revision B
                    <select value={revB} onChange={(e) => { setRevB(e.target.value); setRevRunB(''); }}>
                      <option value="">—</option>
                      {revisions.map((r) => <option key={r.revision_id} value={r.revision_id}>{r.display_name}</option>)}
                    </select>
                  </label>
                </div>
                <div className="form-row">
                  <label>Run of A
                    <select value={revRunA} onChange={(e) => setRevRunA(e.target.value)} disabled={!revA}>
                      <option value="">—</option>
                      {revRunsA.result.state === 'ready' && runOptions(revRunsA.result.data.runs).map((r) => (
                        <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>
                      ))}
                    </select>
                  </label>
                  <label>Run of B
                    <select value={revRunB} onChange={(e) => setRevRunB(e.target.value)} disabled={!revB}>
                      <option value="">—</option>
                      {revRunsB.result.state === 'ready' && runOptions(revRunsB.result.data.runs).map((r) => (
                        <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <p className="muted">Revisions compare through one evaluated run each — the runs carry the evidence, never the revision metadata alone.</p>
              </section>
            )}

            {(mode === 'candidate' || mode === 'candidate-revision') && (
              optimizations.length === 0 ? (
                <p className="muted">No optimization studies in this project yet — candidates appear here after a study evaluates them.</p>
              ) : (
                <section className="card">
                  <div className="form-row">
                    <label>Study A
                      <select value={optA} onChange={(e) => { setOptA(e.target.value); setCandRunA(''); }}>
                        <option value="">—</option>
                        {optimizations.map((o) => (
                          <option key={o.optimization_id} value={o.optimization_id}>
                            {o.optimization_id} · {o.candidate_count} candidates
                          </option>
                        ))}
                      </select>
                    </label>
                    {mode === 'candidate' && (
                      <label>Study B
                        <select value={optB} onChange={(e) => { setOptB(e.target.value); setCandRunB(''); }}>
                          <option value="">—</option>
                          {optimizations.map((o) => (
                            <option key={o.optimization_id} value={o.optimization_id}>
                              {o.optimization_id} · {o.candidate_count} candidates
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>
                  <div className="form-row">
                    <label>Candidate run A
                      <select value={candRunA} onChange={(e) => setCandRunA(e.target.value)} disabled={!optA}>
                        <option value="">—</option>
                        {candA.result.state === 'ready' && candA.result.data.candidate_runs
                          .filter((c) => c.run_id).map((c) => (
                            <option key={c.candidate_id} value={c.run_id ?? ''}>
                              {c.candidate_id} ({c.evaluation_status ?? '?'})
                            </option>
                          ))}
                      </select>
                    </label>
                    {mode === 'candidate' ? (
                      <label>Candidate run B
                        <select value={candRunB} onChange={(e) => setCandRunB(e.target.value)} disabled={!optB}>
                          <option value="">—</option>
                          {candB.result.state === 'ready' && candB.result.data.candidate_runs
                            .filter((c) => c.run_id).map((c) => (
                              <option key={c.candidate_id} value={c.run_id ?? ''}>
                                {c.candidate_id} ({c.evaluation_status ?? '?'})
                              </option>
                            ))}
                        </select>
                      </label>
                    ) : (
                      <label>Revision run B
                        <select value={revRunB} onChange={(e) => setRevRunB(e.target.value)}>
                          <option value="">—</option>
                          {runOptions(evaluated).map((r) => (
                            <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>
                  <p className="muted">Only candidates with an executed run can be compared — generator scores are never comparison inputs.</p>
                </section>
              )
            )}

            <div className="head-actions">
              <button className="btn" onClick={launch} disabled={launchLabel}>
                Compare
              </button>
            </div>

            {pair && comparison.result.state === 'ready' && (
              <CompareResult data={comparison.result.data} tab={tab} onTab={setTab} />
            )}
            {pair && comparison.result.state === 'error' && (
              <p className="bad">Compare failed: {comparison.result.error.message}</p>
            )}
          </div>
        );
      }}
    </AsyncView>
  );
}

function CompareResult({ data, tab, onTab }: {
  data: CompareData;
  tab: 'design' | 'structure' | 'performance' | 'requirements' | 'verification' | 'evidence';
  onTab: (t: 'design' | 'structure' | 'performance' | 'requirements' | 'verification' | 'evidence') => void;
}): ReactElement {
  const compat = data.compatibility;
  return (
    <section className="card">
      <h3>{data.a.display_name ?? data.a.run_id} vs {data.b.display_name ?? data.b.run_id}</h3>
      {!compat.compatible && (
        <div className="compat compat-bad" role="alert">
          <strong>MODEL DIFFERENCE — not directly comparable.</strong>
          <ul className="muted">
            <li>same workload: {String(compat.same_workload)}</li>
            <li>same backend: {String(compat.same_backend)}</li>
            <li>both qualified: {String(compat.both_qualified)}</li>
            {compat.reasons.map((reason, i) => (
              <li key={i} className="bad">{reason}</li>
            ))}
            <li>{compat.metric_units}</li>
          </ul>
          <p className="muted">Performance rows below are shown only where the server marks them comparable — no fake deltas are emitted.</p>
        </div>
      )}
      {compat.compatible && (
        <p className="muted">
          Comparable scenario · same workload {String(compat.same_workload)} ·
          same backend {String(compat.same_backend)} ·
          both qualified {String(compat.both_qualified)} · {compat.metric_units}
        </p>
      )}
      <div className="segmented small" role="tablist" aria-label="Compare sections">
        {(['design', 'structure', 'performance', 'requirements', 'verification', 'evidence'] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t}
            className={tab === t ? 'selected' : ''} onClick={() => onTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'design' && (
        <table className="live-table">
          <thead><tr><th>design fact</th><th>A</th><th>B</th><th>class</th></tr></thead>
          <tbody>
            <tr><td>topology</td><td>{String(data.a.noc?.topology_family ?? '—')}</td><td>{String(data.b.noc?.topology_family ?? '—')}</td><td className="muted">DECLARED</td></tr>
            <tr><td>link width</td><td>{String(data.a.noc?.link_width ?? '—')}</td><td>{String(data.b.noc?.link_width ?? '—')}</td><td className="muted">DECLARED</td></tr>
            <tr><td>workload</td><td>{data.a.workload_id ?? '—'}</td><td>{data.b.workload_id ?? '—'}</td><td className="muted">DECLARED</td></tr>
            <tr><td>backend</td><td>{data.a.backend ?? '—'}</td><td>{data.b.backend ?? '—'}</td><td className="muted">execution</td></tr>
            {recordRows(data.a.noc).filter(([k]) => k !== 'topology_family' && k !== 'link_width').map(([k, v]) => (
              <tr key={k}><td>{humanize(k)}</td><td>{String(v ?? '—')}</td><td>{String(data.b.noc?.[k] ?? '—')}</td><td className="muted">DECLARED</td></tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === 'structure' && (
        <>
          <h4>Topology diff (declared fields)</h4>
          <TopologyDiff a={data.a.noc} b={data.b.noc} />
          <h4>Derived structure (compiler-owned, never edited here)</h4>
          <table className="live-table">
            <thead><tr><th>derived fact</th><th>A</th><th>B</th><th>diff</th></tr></thead>
            <tbody>
              {Array.from(new Set([
                ...Object.keys(data.a.locked_derived ?? {}),
                ...Object.keys(data.b.locked_derived ?? {}),
              ])).sort().map((k) => {
                const va = data.a.locked_derived?.[k];
                const vb = data.b.locked_derived?.[k];
                const same = JSON.stringify(va) === JSON.stringify(vb);
                return (
                  <tr key={k} className={same ? '' : 'differs'}>
                    <td>{humanize(k)}</td>
                    <td>{va == null ? '—' : String(va)}</td>
                    <td>{vb == null ? '—' : String(vb)}</td>
                    <td className="muted">DERIVED · {same ? 'same' : 'DIFFERS'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted">Graph-level topology diff (added/removed links, degree) lives in the topology inspector; this table compares the declared intent fields.</p>
        </>
      )}

      {tab === 'performance' && (
        <table className="live-table">
          <thead><tr><th>metric</th><th>A</th><th>B</th><th>semantics</th></tr></thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <td>{humanize(row.key)}</td>
                <td>
                  {row.a == null ? '—' : (
                    <ScientificValue value={row.a} unit={null} epistemic="SIMULATED"
                      source={data.a.backend} qualification={data.a.qualification} />
                  )}
                </td>
                <td>
                  {row.b == null ? '—' : (
                    <ScientificValue value={row.b} unit={null} epistemic="SIMULATED"
                      source={data.b.backend} qualification={data.b.qualification} />
                  )}
                </td>
                <td className="muted">
                  {row.comparable ? 'comparable' : 'MODEL DIFFERENCE'}
                  {row.verdict ? ` · ${row.verdict}` : ''}
                  {row.differs ? ` · differs: ${row.differs}` : ''}
                  {row.comparable && row.delta_b_minus_a != null ? ` · Δ ${fmtNum(row.delta_b_minus_a)}` : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === 'requirements' && (
        <table className="live-table">
          <thead><tr><th>side</th><th>requirements</th></tr></thead>
          <tbody>
            <tr>
              <td>{data.a.display_name ?? data.a.run_id}</td>
              <td><StatusBadge status={data.a.requirements_pass ? 'SATISFIED' : 'VIOLATED'} /></td>
            </tr>
            <tr>
              <td>{data.b.display_name ?? data.b.run_id}</td>
              <td><StatusBadge status={data.b.requirements_pass ? 'SATISFIED' : 'VIOLATED'} /></td>
            </tr>
          </tbody>
        </table>
      )}

      {tab === 'verification' && (
        <table className="live-table">
          <thead><tr><th>side</th><th>status</th><th>qualification</th><th>revision</th></tr></thead>
          <tbody>
            {[data.a, data.b].map((s) => (
              <tr key={s.run_id}>
                <td><Link className="link" to={`/runs/${s.run_id}`}>{s.display_name ?? s.run_id}</Link></td>
                <td><StatusBadge status={s.status ?? 'UNKNOWN'} /></td>
                <td className="muted">{s.qualification ?? '—'}</td>
                <td className="muted">{s.revision_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === 'evidence' && (
        <table className="live-table">
          <thead><tr><th>side</th><th>run</th><th>design hash</th><th>bundle</th></tr></thead>
          <tbody>
            {[data.a, data.b].map((s) => (
              <tr key={s.run_id}>
                <td>{s.display_name ?? s.run_id}</td>
                <td><Link className="link" to={`/runs/${s.run_id}`}>open run</Link></td>
                <td><Hash value={s.design_hash} /></td>
                <td className="muted">{s.run_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">{data.note}</p>
    </section>
  );
}
