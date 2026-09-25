import { useEffect, useState, type ReactElement } from 'react';
import { api, type JobView, type OptimizationView, type RevisionView } from '../api';
import {
  AsyncView, ContextHeader, ErrorBox, JobProgress, Stepper, useAsync,
  useJobPoll, useStudio,
} from '../studio';
import { Hash, StatusBadge, fmtNum } from '../components/badges';
import OptimizeView from '../components/OptimizeView';
import { navigate } from '../router';

const WIDTH_CHOICES = [32, 64, 128];

export function Optimize({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const [widths, setWidths] = useState<number[]>([32, 64, 128]);
  const [ceiling, setCeiling] = useState(1000);
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

  const start = async (): Promise<void> => {
    const currentId = project.result.state === 'ready'
      ? project.result.data.active_revision_id
      : null;
    if (!currentId || widths.length === 0) return;
    setError(null);
    setOptimizationId(null);
    try {
      const submitted = await api.optimize(currentId, {
        domain: [{ name: 'link_width', values: widths }],
        objectives: [{ metric: 'completion_cycles', direction: 'MIN' }],
        constraints: [
          { metric: 'completion_cycles', op: '<=', threshold: ceiling },
        ],
        method: 'grid',
        selection: 'min_first_objective',
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
            <ContextHeader project={p} />
            <Stepper project={p} current="decide" />
            <h2>Optimize</h2>
            <section className="card">
              <h3>Study definition</h3>
              <p className="muted">
                Base revision {active?.display_name ?? '—'} (immutable). Three
                authorities stay separate: product requirements, optimization
                constraints, measured objectives.
              </p>
              <div className="form-row">
                <label>
                  Link width domain
                  <span className="check-row">
                    {WIDTH_CHOICES.map((w) => (
                      <label className="check" key={w}>
                        <input
                          type="checkbox"
                          checked={widths.includes(w)}
                          onChange={(e) =>
                            setWidths((prev) => e.target.checked
                              ? [...prev, w].sort((a, b) => a - b)
                              : prev.filter((x) => x !== w))
                          }
                        />
                        {w}b
                      </label>
                    ))}
                  </span>
                </label>
                <label>
                  Constraint · completion_cycles ≤
                  <input type="number" value={ceiling} onChange={(e) => setCeiling(Number(e.target.value))} />
                </label>
              </div>
              <div className="form-row">
                <button className="btn btn-primary" disabled={!active || running} onClick={start}>
                  {running ? 'Optimizing…' : 'Launch optimization'}
                </button>
              </div>
              {error && <ErrorBox error={error} />}
              <JobProgress job={job} />
            </section>
            {optimizationId && opt.result.state === 'ready' && (
              <StudyResult optimization={opt.result.data} baseRevision={baseRevision} />
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
}: {
  optimization: OptimizationView;
  baseRevision: RevisionView | undefined;
}): ReactElement {
  return (
    <div className="page">
      <section className="card">
        <h3>Study {optimization.optimization_id}</h3>
        <div className="kv"><span>base revision</span><span>{optimization.base_revision_id}</span></div>
        <div className="kv"><span>result class</span><span>{optimization.study.result_class}</span></div>
        <div className="kv"><span>selected candidate</span><span>{optimization.selected_candidate_id ?? '—'}</span></div>
        <div className="kv"><span>pareto members</span><span>{optimization.study.pareto_ids.length}</span></div>
        <div className="kv"><span>metric registry</span><Hash value={optimization.study.metric_registry_id} /></div>
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
                      ? <button className="link" onClick={() => navigate(`/runs/${c.run_id}`)}>{c.run_id}</button>
                      : <span className="muted">not persisted as a run</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <OptimizeView optimization={optimization.study} design={baseRevision?.design ?? null} />
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
            <ContextHeader project={p} />
            <Stepper project={p} current="decide" />
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
                            <td className="muted">{row.comparable ? 'comparable' : 'not comparable'}</td>
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
