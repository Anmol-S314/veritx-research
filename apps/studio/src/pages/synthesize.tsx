// Synthesize page: topology synthesis as a decision workflow.
// Rationale: docs/decisions/studio.md
import {
  useEffect, useMemo, useRef, useState, type ReactElement,
} from 'react';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync, useJobPoll,
} from '../studio';
import {
  api,
  type JobView,
  type WorkloadCatalogEntry,
  type WorkloadLoweringView,
} from '../api';
import { get, post } from '../api/client';
import { fmtNum } from '../components/badges';
import { ScientificValue } from '../components/ScientificValue';
import { cliCommand, methodById } from '../components/Synthesis/methods';
import {
  degreeOf, diffGraphs, meshLinks, type Edge,
} from '../components/Synthesis/graph';
import { TopologyGraph } from '../components/Synthesis/TopologyGraph';
import { ROUTES } from '../components/Synthesis/methods';

const TERMINAL = new Set(['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED']);

/** Parse a pasted NxN demand matrix. Strict: square, finite,
 * non-negative, zero diagonal, dimension == nodes. Any violation is a
 * typed refusal string — never a silent fallback. */
function parseTrafficMatrix(
  text: string, nodes: number,
): { rows: number[][]; errors: string[] } {
  const lines = text.split('\n').map((l) => l.trim()).filter((l) => l.length > 0);
  if (lines.length === 0) return { rows: [], errors: ['traffic matrix is empty — paste an explicit NxN demand matrix'] };
  if (lines.length !== nodes) {
    return { rows: [], errors: [`traffic has ${lines.length} rows but the problem declares ${nodes} nodes`] };
  }
  const rows: number[][] = [];
  for (let i = 0; i < lines.length; i++) {
    const cells = lines[i].split(/[\s,;]+/).filter((c) => c.length > 0);
    if (cells.length !== nodes) {
      return { rows: [], errors: [`row ${i} has ${cells.length} values, expected ${nodes}`] };
    }
    const row = cells.map(Number);
    if (row.some((v) => !Number.isFinite(v))) {
      return { rows: [], errors: [`row ${i} contains a non-finite value`] };
    }
    if (row.some((v) => v < 0)) {
      return { rows: [], errors: [`row ${i} contains a negative demand`] };
    }
    rows.push(row);
  }
  for (let i = 0; i < nodes; i++) {
    if (rows[i][i] !== 0) {
      return { rows: [], errors: [`diagonal must be zero (row ${i} has ${rows[i][i]})`] };
    }
  }
  return { rows, errors: [] };
}

function shortId(id: string | null | undefined): string {
  if (!id) return '—';
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

/** Aggregate the canonical workload lowering into an NxN demand matrix
 * (payload bytes per src → dst rank). The matrix is derived and
 * inspectable — never pasted. Throws a refusal when a rank falls
 * outside the declared node count. */
function buildWorkloadMatrix(
  lowering: WorkloadLoweringView, nodes: number,
): { rows: number[][]; totalBytes: number; pairs: number } {
  const rows = Array.from({ length: nodes }, () => new Array<number>(nodes).fill(0));
  let pairs = 0;
  for (const f of lowering.flows) {
    if (f.src_rank >= nodes || f.dst_rank >= nodes) {
      throw new Error(
        `workload rank ${Math.max(f.src_rank, f.dst_rank)} exceeds the node count ${nodes} — `
        + 'raise the node count under Advanced settings or import a matrix',
      );
    }
    if (f.src_rank === f.dst_rank) continue;
    if (rows[f.src_rank][f.dst_rank] === 0) pairs += 1;
    rows[f.src_rank][f.dst_rank] += f.payload_bytes;
  }
  const totalBytes = rows.flat().reduce((a, b) => a + b, 0);
  return { rows, totalBytes, pairs };
}

/** All-pairs hop counts by BFS. Unreachable pairs stay Infinity. */
function hopField(nodes: number, links: Edge[]): number[][] {
  const adj: number[][] = Array.from({ length: nodes }, () => []);
  for (const [u, v] of links) {
    if (u < nodes && v < nodes) {
      adj[u].push(v);
      adj[v].push(u);
    }
  }
  return adj.map((_, s) => {
    const dist = new Array<number>(nodes).fill(Infinity);
    dist[s] = 0;
    const queue = [s];
    while (queue.length > 0) {
      const cur = queue.shift() as number;
      for (const nxt of adj[cur]) {
        if (dist[nxt] === Infinity) {
          dist[nxt] = dist[cur] + 1;
          queue.push(nxt);
        }
      }
    }
    return dist;
  });
}

function avgHops(field: number[][]): number | null {
  let sum = 0;
  let count = 0;
  for (let i = 0; i < field.length; i++) {
    for (let j = 0; j < field.length; j++) {
      if (i !== j && Number.isFinite(field[i][j])) {
        sum += field[i][j];
        count += 1;
      }
    }
  }
  return count > 0 ? sum / count : null;
}

/** The four gateway engines with product names. `bo_gp` is deliberately
 * NOT called Bayesian optimization: the default surrogate is
 * seeded-random, not a qualified GP. The engine string sent on the wire
 * is unchanged — only the product label is honest. */
const UI_METHODS = [
  {
    id: 'rho',
    engine: 'rho_iterative',
    label: 'Rolling Horizon',
    blurb: 'Good general-purpose topology search. Deterministic with seed.',
  },
  {
    id: 'milp',
    engine: 'milp_tmcf',
    label: 'Exact MILP',
    blurb: 'Small problems only. Optimal only when the solver proves it.',
  },
  {
    id: 'grpo',
    engine: 'grpo_group',
    label: 'GRPO-style search',
    blurb: 'Group-relative exploration. A selection discipline, not a trained policy.',
  },
  {
    id: 'bo',
    engine: 'bo_gp',
    label: 'Parameterized budgeted search',
    blurb: 'Budgeted exploration of generator parameters. Seeded-random unless a qualified GP is configured.',
  },
] as const;

function engineOf(methodId: string): string {
  const found = UI_METHODS.find((m) => m.id === methodId);
  if (!found) throw new Error(`unknown synthesis method ${methodId}`);
  return found.engine;
}

function methodLabel(methodId: string): string {
  return UI_METHODS.find((m) => m.id === methodId)?.label ?? methodId;
}

/** Method params rendered under Advanced. Problem-level controls
 * (nodes, layout, radix, link length, edge budget, seed, objective)
 * live on the primary surface or in shared advanced fields instead. */
const SHARED_PARAMS = new Set([
  'nodes', 'k', 'radix', 'max_len', 'max_edges', 'seed', 'objective',
]);

interface GatewayEngine {
  engine: string;
  label: string;
  scope: string;
  completeness: string;
  optimality: string;
}

interface PreviousSynthesis {
  synthesis_id: string;
  engine?: string;
  created_at?: string;
}

/** The live synthesis record, read from the gateway's own fields.
 * Measured performance and verification are NOT here: the record
 * screens on the generator objective, and measurement happens after
 * promote → compile → evaluate. */
interface LiveSynthesis {
  synthesis_id: string;
  engine: string;
  seed: number | null;
  solver_status: string | null;
  generator_name: string | null;
  generator_value: number | null;
  completeness_kind: string | null;
  completeness_wording: string | null;
  candidate_id: string | null;
  link_count: number | null;
  max_degree: number | null;
  base_revision_id: string | null;
  traffic_id: string | null;
  def_nodes: number | null;
  def_k: number | null;
  links: Edge[] | null;
}

function normalizeSynthesisRecord(rec: Record<string, unknown>): LiveSynthesis {
  const gen = (rec.generator_objective ?? {}) as Record<string, unknown>;
  const comp = (rec.completeness ?? {}) as Record<string, unknown>;
  const cand = (rec.candidate ?? {}) as Record<string, unknown>;
  const def = (rec.definition ?? {}) as Record<string, unknown>;
  const traffic = (rec.traffic ?? {}) as Record<string, unknown>;
  const rawLinks = (cand.links ?? []) as unknown;
  const links: Edge[] | null = Array.isArray(rawLinks)
    && rawLinks.every((e) => Array.isArray(e) && e.length >= 2)
    ? (rawLinks as number[][]).map((e) => [e[0], e[1]] as Edge)
    : null;
  const deg = links ? degreeOf(
    typeof cand.nodes === 'number' ? cand.nodes : links.flat().length,
    links,
  ) : [];
  return {
    synthesis_id: String(rec.synthesis_id ?? ''),
    engine: String(rec.engine ?? ''),
    seed: typeof rec.seed === 'number' ? rec.seed : null,
    solver_status: typeof rec.solver_status === 'string'
      ? rec.solver_status
      : (typeof cand.status === 'string' ? cand.status : null),
    generator_name: typeof gen.name === 'string' ? gen.name : null,
    generator_value: typeof gen.value === 'number' ? gen.value : null,
    completeness_kind: typeof comp.kind === 'string' ? comp.kind : null,
    completeness_wording: typeof comp.claim === 'string'
      ? comp.claim
      : (typeof rec.completeness_claim === 'string' ? rec.completeness_claim : null),
    candidate_id: typeof rec.candidate_id === 'string'
      ? rec.candidate_id
      : (typeof cand.candidate_id === 'string' ? cand.candidate_id : null),
    link_count: typeof rec.link_count === 'number'
      ? rec.link_count
      : (links ? links.length : null),
    max_degree: typeof rec.max_degree === 'number'
      ? rec.max_degree
      : (deg.length > 0 ? Math.max(...deg) : null),
    base_revision_id: typeof rec.base_revision_id === 'string'
      ? rec.base_revision_id
      : null,
    traffic_id: typeof traffic.traffic_id === 'string' ? traffic.traffic_id : null,
    def_nodes: typeof def.nodes === 'number' ? def.nodes : null,
    def_k: typeof def.k === 'number' ? def.k : null,
    links,
  };
}

function defaultsOf(methodId: string): Record<string, string | number> {
  const m = methodById(methodId === 'bo' ? 'bo' : methodId);
  const out: Record<string, string | number> = {};
  for (const p of m.params) out[p.name] = p.def;
  return out;
}

function fmtElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

/** Tiny inspectable heatmap of the submitted demand matrix. */
function TrafficHeatmap({ values }: { values: number[][] }): ReactElement {
  const n = values.length;
  const max = Math.max(1, ...values.flat());
  const size = Math.min(220, Math.max(120, n * 3));
  const cell = size / n;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`Traffic demand heatmap over ${n} endpoints`}
      style={{ border: '1px solid var(--border)' }}
    >
      {values.map((row, i) => row.map((v, j) => (
        <rect
          key={`${i}-${j}`}
          x={j * cell}
          y={i * cell}
          width={cell + 0.5}
          height={cell + 0.5}
          fill="var(--accent)"
          opacity={v <= 0 ? 0.04 : 0.15 + 0.85 * (Math.log1p(v) / Math.log1p(max))}
        />
      )))}
    </svg>
  );
}

export function Synthesize({ projectId }: { projectId: string }): ReactElement {
  const project = useAsync(() => api.project(projectId), [projectId]);
  const catalog = useAsync(api.workloadCatalog, []);

  const [methodId, setMethodId] = useState('rho');
  const [values, setValues] = useState<Record<string, string | number>>(
    () => defaultsOf('rho'),
  );
  // Problem-level controls — every one enters the live request.
  const [nodes, setNodes] = useState(64);
  const [k, setK] = useState(8);
  const [maxEdges, setMaxEdges] = useState(120);
  const [radix, setRadix] = useState(4);
  const [maxLen, setMaxLen] = useState(2.0);
  const [seed, setSeed] = useState(7);
  const [objective, setObjective] = useState('geodesic');
  const [bandwidth, setBandwidth] = useState(32);
  const [latency, setLatency] = useState(1.0);
  // Traffic: derived from the current workload by default; manual paste
  // lives under Advanced.
  const [trafficMode, setTrafficMode] = useState<'workload' | 'import'>('workload');
  const [importText, setImportText] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submittedAt, setSubmittedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [synthesisId, setSynthesisId] = useState<string | null>(null);
  const [synthesesTick, setSynthesesTick] = useState(0);

  const workloadId = project.result.state === 'ready'
    ? project.result.data.draft.workload_id ?? null
    : null;
  const activeRevisionId = project.result.state === 'ready'
    ? project.result.data.active_revision_id
    : null;

  const lowering = useAsync(
    () => (workloadId
      ? api.workloadLowering(workloadId)
      : Promise.reject(new Error('no workload selected'))),
    [workloadId],
  );
  const engines = useAsync(
    () => get<{ engines?: GatewayEngine[] }>('/synthesis/engines')
      .catch(() => ({ engines: undefined as GatewayEngine[] | undefined })),
    [],
  );
  const previous = useAsync(
    (): Promise<{ syntheses?: PreviousSynthesis[] }> => get<{ syntheses?: PreviousSynthesis[] }>(
      `/projects/${encodeURIComponent(projectId)}/syntheses`,
    ).catch(() => ({ syntheses: [] as PreviousSynthesis[] })),
    [projectId, synthesesTick],
  );

  const onTerminal = (job: JobView): void => {
    const sid = (job.result as { synthesis_id?: string } | undefined)?.synthesis_id;
    if (sid) {
      setSynthesisId(sid);
      setSynthesesTick((t) => t + 1);
    }
  };
  const job = useJobPoll(jobId, onTerminal);
  const jobRunning = jobId != null
    && (job == null || !TERMINAL.has(job.state));

  useEffect(() => {
    if (!jobRunning) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [jobRunning]);

  // Default the problem size from the workload's participant count when
  // it forms a square grid. The user can still change it under Advanced.
  const autoSized = useRef(false);
  useEffect(() => {
    if (autoSized.current || lowering.result.state !== 'ready') return;
    const n = lowering.result.data.participant_count;
    const side = Math.round(Math.sqrt(n));
    if (side * side === n && n >= 4) {
      setNodes(n);
      setK(side);
      autoSized.current = true;
    }
  }, [lowering.result]);

  const live = useAsync(
    () => (synthesisId
      ? get<Record<string, unknown>>(
        `/syntheses/${encodeURIComponent(synthesisId)}`).then(normalizeSynthesisRecord)
      : Promise.reject(new Error('no synthesis'))),
    [synthesisId],
  );

  const method = methodById(methodId);
  const engineScopes = useMemo(() => {
    const out = new Map<string, GatewayEngine>();
    if (engines.result.state === 'ready' && engines.result.data.engines) {
      for (const e of engines.result.data.engines) out.set(e.engine, e);
    }
    return out;
  }, [engines.result]);

  const workloadEntry: WorkloadCatalogEntry | null = useMemo(() => {
    if (catalog.result.state !== 'ready' || !workloadId) return null;
    return catalog.result.data.workloads.find(
      (w) => w.workload_id === workloadId,
    ) ?? null;
  }, [catalog.result, workloadId]);
  const workloadName = workloadEntry?.display_name ?? workloadId ?? '—';
  const workloadParallel = workloadEntry
    ? `TP${workloadEntry.parallelism.tp} / PP${workloadEntry.parallelism.pp} / `
      + `EP${workloadEntry.parallelism.ep} / DP${workloadEntry.parallelism.dp}`
    : null;

  const derivedMatrix = useMemo(() => {
    if (trafficMode !== 'workload') return null;
    if (lowering.result.state !== 'ready') return null;
    try {
      return buildWorkloadMatrix(lowering.result.data, nodes);
    } catch {
      return null;
    }
  }, [trafficMode, lowering.result, nodes]);

  const baseLinks: Edge[] = k * k === nodes ? meshLinks(k) : [];
  const baseDeg = baseLinks.length > 0 ? degreeOf(nodes, baseLinks) : [];
  const baseMaxDeg = baseDeg.length > 0 ? Math.max(...baseDeg) : null;

  const pickMethod = (id: string): void => {
    setMethodId(id);
    setValues(defaultsOf(id));
    setNotice(null);
  };

  const setParam = (name: string, v: string | number): void => {
    setValues((prev) => ({ ...prev, [name]: v }));
  };

  /** Submit the defined problem through the canonical gateway route.
   * Every primary control enters the request; anything that does not
   * is not offered on this page. */
  const launchLive = async (): Promise<void> => {
    setError(null);
    setNotice(null);
    if (!activeRevisionId) {
      setError(new Error('No active revision — compile a revision before submitting a synthesis problem.'));
      return;
    }
    if (k * k !== nodes) {
      setError(new Error(`Grid layout requires nodes == k×k; got nodes=${nodes}, k=${k}.`));
      return;
    }
    let matrix: number[][];
    let trafficMeta: Record<string, unknown>;
    if (trafficMode === 'workload') {
      if (lowering.result.state !== 'ready') {
        setError(new Error('Workload traffic is still loading — wait for the workload card before running.'));
        return;
      }
      try {
        const built = buildWorkloadMatrix(lowering.result.data, nodes);
        matrix = built.rows;
      } catch (err) {
        setError(err instanceof Error ? err : new Error(String(err)));
        return;
      }
      trafficMeta = {
        source_artifact_id: lowering.result.data.message_artifact_id,
        namespace: 'rank',
        dimension: nodes,
        values: matrix,
        unit: 'bytes',
        aggregation: 'sum_over_workload',
      };
    } else {
      const parsed = parseTrafficMatrix(importText, nodes);
      if (parsed.errors.length > 0) {
        setError(new Error(`Traffic matrix refused: ${parsed.errors[0]}`));
        return;
      }
      matrix = parsed.rows;
      trafficMeta = {
        source_artifact_id: 'studio:synthesize:imported',
        namespace: 'rank',
        dimension: nodes,
        values: matrix,
        unit: 'messages',
        aggregation: 'sum_over_window',
      };
    }
    const definition: Record<string, unknown> = {
      nodes,
      layout: 'grid',
      k,
      radix,
      max_len: maxLen,
      bandwidth_GBs: bandwidth,
      latency_ns: latency,
      objective,
      execution_policy: {
        timeout_s: Number(values.timeout_s ?? 120) || 120,
        max_nodes: Number(values.max_nodes ?? 20) || 20,
      },
    };
    const body: Record<string, unknown> = {
      engine: engineOf(methodId),
      definition,
      traffic: trafficMeta,
      seed,
      steps: Number(values.steps ?? 50) || 50,
      horizon: Number(values.horizon ?? 5) || 5,
      branch: Number(values.branch ?? 5) || 5,
      group: Number(values.group ?? 4) || 4,
      iters: Number(values.iters ?? 50) || 50,
      max_edges: maxEdges,
    };
    try {
      const submitted = await post<JobView>(
        `/revisions/${encodeURIComponent(activeRevisionId)}/synthesize`, body);
      setSynthesisId(null);
      setJobId(submitted.job_id);
      setSubmittedAt(Date.now());
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  const cli = cliCommand(
    method,
    { ...values, nodes, k, seed, max_edges: maxEdges },
    trafficMode === 'workload'
      ? (lowering.result.state === 'ready'
        ? lowering.result.data.message_artifact_id
        : '<workload-traffic>')
      : '<imported-matrix>',
  );

  const advancedParams = method.params.filter((p) => !SHARED_PARAMS.has(p.name));

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {() => (
        <div className="page">
          <h2>Synthesize</h2>
          <p className="muted">
            Find a better fabric for this workload.
          </p>

          <section className="card" aria-label="Workload">
            <h3>Workload</h3>
            {!workloadId ? (
              <div className="empty-state">
                <p className="muted">
                  This project has no workload yet — synthesis optimizes a
                  topology for a specific workload, never in the abstract.
                </p>
                <div className="empty-actions">
                  <Link className="btn btn-primary" to={`/projects/${projectId}/workload`}>
                    Choose workload
                  </Link>
                </div>
              </div>
            ) : (
              <AsyncView result={lowering.result} reload={lowering.reload}>
                {(low) => (
                  <>
                    <div className="kv"><span>workload</span><span>{workloadName}</span></div>
                    {workloadParallel && (
                      <div className="kv"><span>parallelism</span><span className="num">{workloadParallel}</span></div>
                    )}
                    <div className="kv">
                      <span>traffic source</span>
                      <span>measured workload traffic · {fmtNum(low.totals.messages)} messages ·{' '}
                        {low.participant_count} endpoints
                      </span>
                    </div>
                    {low.participant_count !== nodes && (
                      <p className="muted">
                        Traffic covers {low.participant_count} endpoints but
                        the problem declares {nodes} nodes. Match them under
                        Advanced settings, or import a matrix.
                      </p>
                    )}
                    <details className="subtle">
                      <summary>
                        Inspect traffic ({fmtNum(derivedMatrix?.pairs ?? 0)} active pairs ·{' '}
                        {fmtNum(derivedMatrix?.totalBytes ?? 0)} bytes)
                      </summary>
                      {derivedMatrix ? (
                        <div style={{ marginTop: 8 }}>
                          <TrafficHeatmap values={derivedMatrix.rows} />
                          <p className="muted">
                            Derived from {shortId(low.message_artifact_id)} ·
                            rank space · zero diagonal. This is the matrix
                            the request sends — inspectable, not pasted.
                          </p>
                        </div>
                      ) : (
                        <p className="muted">
                          The derived matrix does not fit {nodes} nodes.
                          Adjust the problem size under Advanced settings.
                        </p>
                      )}
                    </details>
                  </>
                )}
              </AsyncView>
            )}
          </section>

          <section className="card" aria-label="Baseline">
            <h3>Baseline</h3>
            {baseLinks.length > 0 ? (
              <>
                <div className="kv"><span>seed topology</span>
                  <span>Mesh {k}×{k} · {baseLinks.length} links
                    {baseMaxDeg != null ? ` · max degree ${baseMaxDeg}` : ''}
                  </span>
                </div>
                <p className="muted">
                  The search starts here, and the candidate is compared
                  against it. Not a control — the seed is the mesh by
                  construction.
                </p>
                <div className="baseline-mini">
                  <TopologyGraph
                    base={baseLinks}
                    candidate={null}
                    nodes={nodes}
                    k={k}
                    title={`mesh ${k}×${k} baseline`}
                  />
                </div>
              </>
            ) : (
              <p className="muted">
                The mesh seed needs nodes == k×k — fix the problem size
                under Advanced settings.
              </p>
            )}
          </section>

          <section className="card" aria-label="Constraints">
            <h3>Constraints</h3>
            <div className="form-row">
              <label>Max links
                <input
                  type="number"
                  value={maxEdges}
                  min={1}
                  onChange={(e) => setMaxEdges(Number(e.target.value) || 0)}
                />
              </label>
              <label>Max radix
                <input
                  type="number"
                  value={radix}
                  min={2}
                  onChange={(e) => setRadix(Number(e.target.value) || 0)}
                />
              </label>
              <label>Max link length (pitches)
                <input
                  type="number"
                  value={maxLen}
                  min={0.5}
                  step={0.5}
                  onChange={(e) => setMaxLen(Number(e.target.value) || 0)}
                />
              </label>
            </div>
            <p className="muted">
              Fewer links is the link objective — set the budget here.
              Measured completion is compared after promote → compile →
              evaluate, never from a generator score.
            </p>
          </section>

          <section className="card" aria-label="Search method">
            <h3>Search method</h3>
            <div className="form-row" role="radiogroup" aria-label="Search method">
              <label>Method
                <select value={methodId} onChange={(e) => pickMethod(e.target.value)}>
                  {UI_METHODS.map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
              </label>
            </div>
            <p className="muted">
              <strong>{methodLabel(methodId)}</strong> —{' '}
              {UI_METHODS.find((m) => m.id === methodId)?.blurb}
            </p>
            <details className="subtle">
              <summary>Details</summary>
              <div className="kv"><span>engine</span><span><code>{engineOf(methodId)}</code></span></div>
              <div className="kv"><span>completeness</span>
                <span>{engineScopes.get(engineOf(methodId))?.completeness ?? 'UNBOUNDED'}</span>
              </div>
              <div className="kv"><span>optimality claim</span>
                <span className="muted">
                  {engineScopes.get(engineOf(methodId))?.optimality
                    ?? 'best observed among evaluated candidates — none'}
                </span>
              </div>
              {methodId === 'milp' && (
                <p className="muted">
                  Above the exact-solve node cap the heuristic branch runs;
                  the executed branch is recorded as provenance. A TIME_LIMIT
                  incumbent is feasible, never optimal.
                </p>
              )}
              <p className="muted">Other methods:</p>
              <ul className="muted">
                {UI_METHODS.filter((m) => m.id !== methodId).map((m) => (
                  <li key={m.id}>
                    <button type="button" className="link" onClick={() => pickMethod(m.id)}>
                      {m.label}
                    </button>{' '}— {m.blurb}
                  </li>
                ))}
              </ul>
            </details>
          </section>

          <details className="card">
            <summary><strong>Advanced settings</strong></summary>
            <div className="form-row" style={{ marginTop: 8 }}>
              <label>Nodes
                <input type="number" value={nodes} min={2}
                       onChange={(e) => setNodes(Number(e.target.value) || 0)} />
              </label>
              <label>Grid side k
                <input type="number" value={k} min={2}
                       onChange={(e) => setK(Number(e.target.value) || 0)} />
              </label>
              <label>Seed
                <input type="number" value={seed} min={0}
                       onChange={(e) => setSeed(Number(e.target.value) || 0)} />
              </label>
              <label>Generator objective
                <select value={objective} onChange={(e) => setObjective(e.target.value)}>
                  <option value="geodesic">geodesic</option>
                  <option value="priced_geodesic">priced_geodesic</option>
                </select>
              </label>
              <label>Link bandwidth (GB/s)
                <input type="number" value={bandwidth} min={0.1}
                       onChange={(e) => setBandwidth(Number(e.target.value) || 32)} />
              </label>
              <label>Link latency (ns)
                <input type="number" value={latency} min={0.1} step={0.1}
                       onChange={(e) => setLatency(Number(e.target.value) || 1.0)} />
              </label>
            </div>
            <h4>Traffic source</h4>
            <div className="form-row" role="radiogroup" aria-label="Traffic source">
              <label className="check">
                <input
                  type="radio"
                  name="traffic-mode"
                  checked={trafficMode === 'workload'}
                  onChange={() => setTrafficMode('workload')}
                />
                Current workload (derived)
              </label>
              <label className="check">
                <input
                  type="radio"
                  name="traffic-mode"
                  checked={trafficMode === 'import'}
                  onChange={() => setTrafficMode('import')}
                />
                Import traffic matrix
              </label>
            </div>
            {trafficMode === 'import' && (
              <textarea
                rows={6}
                cols={40}
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                placeholder={'0 12 0 …\n…'}
                aria-label="Traffic demand matrix"
              />
            )}
            {advancedParams.length > 0 && (
              <>
                <h4>{methodLabel(methodId)} budget</h4>
                <div className="form-row">
                  {advancedParams.map((prm) => (
                    <label key={prm.name}>{prm.label}
                      {prm.kind === 'select' ? (
                        <select
                          value={String(values[prm.name] ?? prm.def)}
                          onChange={(e) => setParam(prm.name, e.target.value)}
                        >
                          {(prm.options ?? []).map((o) => (
                            <option key={String(o)} value={String(o)}>{String(o)}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="number"
                          value={(values[prm.name] as number) ?? prm.def}
                          min={prm.min}
                          max={prm.max}
                          step={prm.kind === 'float' ? 0.1 : 1}
                          onChange={(e) => setParam(prm.name, Number(e.target.value))}
                        />
                      )}
                      <small className="muted">{prm.help}</small>
                    </label>
                  ))}
                </div>
              </>
            )}
            <p className="muted">
              Generator objectives are analytical screening scores, never
              measured performance.
            </p>
          </details>

          <section className="card" aria-label="Run synthesis">
            <div className="form-row">
              <button
                className="btn btn-primary"
                onClick={launchLive}
                disabled={!activeRevisionId || jobRunning}
              >
                {jobRunning ? 'Synthesizing…' : 'Run synthesis'}
              </button>
              {!activeRevisionId && (
                <span className="muted">
                  Compile a revision first — synthesis submits against it.
                </span>
              )}
            </div>
            {jobRunning && (
              <div className="kv"><span>elapsed</span>
                <span className="num">
                  {submittedAt ? fmtElapsed(now - submittedAt) : '—'}
                </span>
              </div>
            )}
            <JobProgress job={job} />
            {job && TERMINAL.has(job.state) && !synthesisId && (
              <ErrorBox
                error={new Error(
                  job.error_message
                    ? `${job.error_code ?? job.state}: ${job.error_message}`
                    : `Synthesis ${job.state.toLowerCase()} with no result.`,
                )}
              />
            )}
            {synthesisId && live.result.state === 'ready' && (
              <LiveSynthesisResult
                result={live.result.data}
                projectId={projectId}
                workloadName={workloadName}
                workloadParallel={workloadParallel}
                matrix={derivedMatrix?.rows ?? null}
              />
            )}
            {synthesisId && live.result.state === 'error' && (
              <ErrorBox error={live.result.error} onRetry={live.reload} />
            )}
          </section>

          {previous.result.state === 'ready'
            && (previous.result.data.syntheses ?? []).length > 0 && (
            <section className="card" aria-label="Previous syntheses">
              <h3>Previous syntheses</h3>
              <ul className="decision-list">
                {(previous.result.data.syntheses ?? []).map((s) => (
                  <li key={s.synthesis_id}>
                    <button
                      type="button"
                      className="link"
                      onClick={() => {
                        setSynthesisId(s.synthesis_id);
                        setJobId(null);
                      }}
                    >
                      {shortId(s.synthesis_id)}
                    </button>
                    <span className="muted">
                      {methodLabel(
                        UI_METHODS.find((m) => m.engine === s.engine)?.id ?? '',
                      ) || s.engine}
                    </span>
                    {s.created_at && (
                      <span className="when">
                        {String(s.created_at).slice(0, 16).replace('T', ' ')}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <details className="card">
            <summary><strong>Developer / reproduce</strong></summary>
            {cli ? (
              <>
                <p className="muted">Equivalent command for this problem:</p>
                <pre className="cli">{cli.join(' ')}</pre>
              </>
            ) : (
              <p className="muted">{method.cliNote}</p>
            )}
            <p className="muted">
              Import an external graph instead under{' '}
              <Link to={ROUTES.candidates(projectId)}>Candidates → Import</Link>.
            </p>
          </details>

          {notice && <p className="good">{notice}</p>}
          {error && <ErrorBox error={error} />}
        </div>
      )}
    </AsyncView>
  );
}

/** Completed synthesis, read from the gateway record. Generator and
 * measured product objectives stay separate: measured numbers and
 * verification exist only after promote → compile → evaluate. */
function LiveSynthesisResult({
  result, projectId, workloadName, workloadParallel, matrix,
}: {
  result: LiveSynthesis;
  projectId: string;
  workloadName: string;
  workloadParallel: string | null;
  matrix: number[][] | null;
}): ReactElement {
  const candLinks = result.links;
  // The baseline is rebuilt from the RECORD's problem size, not the
  // form state: a result viewed later must compare against the mesh it
  // actually started from. Missing dimensions mean no baseline graph —
  // never a guessed one.
  const grid = result.def_nodes != null && result.def_k != null
    && result.def_k * result.def_k === result.def_nodes
    ? { nodes: result.def_nodes, k: result.def_k }
    : null;
  const rBase: Edge[] = grid ? meshLinks(grid.k) : [];
  const diff = candLinks && rBase.length > 0
    ? diffGraphs(rBase, candLinks)
    : null;
  const baseField = grid ? hopField(grid.nodes, rBase) : null;
  const candField = candLinks && grid ? hopField(grid.nodes, candLinks) : null;
  const baseAvg = baseField ? avgHops(baseField) : null;
  const candAvg = candField ? avgHops(candField) : null;
  // Hot pairs only when the inspected matrix matches the record's
  // problem size — otherwise the hop comparison is meaningless.
  const hotPairs = matrix && grid && matrix.length === grid.nodes
    && baseField && candField
    ? matrix.flatMap((row, i) => row.map((v, j) => ({ i, j, v })))
      .filter((c) => c.v > 0 && c.i !== c.j)
      .sort((a, b) => b.v - a.v)
      .slice(0, 30)
      .map((c) => ({
        ...c,
        base: baseField[c.i][c.j],
        cand: candField[c.i][c.j],
      }))
      .filter((c) => Number.isFinite(c.cand) && c.cand < c.base)
      .slice(0, 5)
    : [];

  return (
    <section className="card" aria-label="Synthesis result" style={{ marginTop: 12 }}>
      <h3>Results</h3>
      <p className="muted">
        Optimized for <strong>{workloadName}</strong>
        {workloadParallel ? ` · ${workloadParallel}` : ''}. Do not assume
        this topology is optimal for other workloads.
      </p>
      <table className="live-table">
        <thead>
          <tr><th></th><th>Baseline</th><th>{shortId(result.candidate_id)}</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>Links</td>
            <td className="num">{rBase.length > 0 ? fmtNum(rBase.length) : '—'}</td>
            <td className="num">{result.link_count != null ? fmtNum(result.link_count) : '—'}</td>
          </tr>
          <tr>
            <td>Avg hops (estimate)</td>
            <td className="num">{baseAvg != null ? baseAvg.toFixed(1) : '—'}</td>
            <td className="num">{candAvg != null ? candAvg.toFixed(1) : '—'}</td>
          </tr>
          <tr>
            <td>Max degree</td>
            <td className="num">
              {rBase.length > 0 && grid
                ? Math.max(...degreeOf(grid.nodes, rBase)) : '—'}
            </td>
            <td className="num">{result.max_degree ?? '—'}</td>
          </tr>
          <tr>
            <td>Generator estimate</td>
            <td className="muted">—</td>
            <td>
              {result.generator_value != null ? (
                <ScientificValue
                  value={result.generator_value}
                  unit={result.generator_name ?? 'generator score'}
                  epistemic="MODELLED"
                  source={`${result.engine} generator`}
                  qualification="NOT QUALIFIED — screening only"
                />
              ) : <span className="muted">—</span>}
            </td>
          </tr>
          <tr>
            <td>Measured</td>
            <td className="muted">—</td>
            <td className="muted">not yet measured</td>
          </tr>
          <tr>
            <td>Verified</td>
            <td className="muted">—</td>
            <td className="muted">NOT VERIFIED</td>
          </tr>
        </tbody>
      </table>
      <p className="muted">
        Generator scores guide search; measured backend results decide
        comparisons. Measurement happens after promote → compile →
        evaluate.
      </p>

      {candLinks && grid && (
        <>
          <TopologyGraph
            base={rBase}
            candidate={candLinks}
            nodes={grid.nodes}
            k={grid.k}
            title={`mesh ${grid.k}×${grid.k} baseline vs candidate`}
          />
          {diff && (
            <p className="muted">
              +{diff.added.length} links · −{diff.removed.length} links
            </p>
          )}
          {hotPairs.length > 0 && (
            <>
              <h4>Hot traffic pairs improved (estimate)</h4>
              <ul className="decision-list">
                {hotPairs.map((c) => (
                  <li key={`${c.i}-${c.j}`}>
                    <span className="num">{c.i}→{c.j}</span>
                    <span className="muted">
                      {c.base} hops → {c.cand}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      <details className="subtle">
        <summary>Technical details</summary>
        <div className="kv"><span>engine</span><span><code>{result.engine}</code></span></div>
        <div className="kv"><span>seed</span><span className="num">{result.seed ?? '—'}</span></div>
        <div className="kv"><span>solver</span><span>{result.solver_status ?? '—'}</span></div>
        <div className="kv"><span>completeness</span>
          <span>{result.completeness_kind ?? '—'}
            {result.completeness_wording ? ` — ${result.completeness_wording}` : ''}
          </span>
        </div>
        <div className="kv"><span>traffic</span>
          <span><code title={result.traffic_id ?? ''}>{shortId(result.traffic_id)}</code></span>
        </div>
        <div className="kv"><span>nodes</span><span className="num">{result.def_nodes ?? '—'}</span></div>
      </details>

      <div className="empty-actions" style={{ marginTop: 8 }}>
        {result.candidate_id && (
          <Link
            className="btn btn-primary"
            to={ROUTES.candidateDetail(projectId, result.candidate_id)}
          >
            Open in Candidates
          </Link>
        )}
      </div>
      <p className="muted">
        The candidate was saved to the library automatically — evaluate,
        compare and promote it from Candidates.
      </p>
    </section>
  );
}
