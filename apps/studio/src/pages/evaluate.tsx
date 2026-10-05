import { useEffect, useRef, useState, type ReactElement } from 'react';
import {
  AsyncView, ErrorBox, JobProgress, Link, useAsync,
  useJobPoll, useStudio, simulationCapabilityReason,
} from '../studio';
import { api } from '../api';
import type {
  EvaluationPlanView, FederatedAnalysisView, JobView,
  NormalizedMetricView, PlannedAnalysisView, RunView,
} from '../api/types';
import type { RequirementEntry } from '../types';
import { Hash, shortHash, StatusBadge } from '../components/badges';
import { backendLabel } from '../components/ScientificValue';
import {
  EvaluationPlanTable, sortQuestions,
} from '../components/FederatedEvaluationView';
import { dramConsequence } from '../components/ScenarioStack';

interface QuestionGroup {
  id: 'network' | 'schedule' | 'memory' | 'serving';
  title: string;
  question: string;
  questions: string[];
}

const GROUPS: QuestionGroup[] = [
  {
    id: 'network',
    title: 'Network',
    question: 'How long does physical traffic take to complete?',
    questions: ['NETWORK_COMPLETION'],
  },
  {
    id: 'schedule',
    title: 'Distributed schedule',
    question: 'How long does collective execution take under this mapping?',
    questions: ['SYSTEM_MAKESPAN', 'COMMUNICATION_EXPOSURE', 'PER_RANK_COMPLETION'],
  },
  {
    id: 'memory',
    title: 'Memory',
    question: 'What DRAM timing does this workload produce?',
    questions: ['DRAM_TIMING'],
  },
  {
    id: 'serving',
    title: 'Serving',
    question: 'What are request TTFT and completion under serving load?',
    questions: ['SERVING_TTFT', 'SERVING_COMPLETION'],
  },
];

type GroupState =
  | { kind: 'ready'; rows: PlannedAnalysisView[] }
  | { kind: 'blocked'; cause: string; backend: string }
  | { kind: 'unconfigured' };

function groupState(
  group: QuestionGroup, plan: EvaluationPlanView | null,
): GroupState {
  if (!plan) return { kind: 'unconfigured' };
  const rows = group.questions
    .map((q) => plan.analyses.find((a) => a.question === q))
    .filter((r): r is PlannedAnalysisView => r != null);
  if (rows.length === 0) return { kind: 'unconfigured' };
  const bad = rows.find((r) => r.readiness !== 'READY');
  if (!bad) return { kind: 'ready', rows };
  const detail = bad.reason ?? bad.readiness ?? 'blocked';
  const cause = group.id === 'memory' && /resolvable memory demand|no placement|memory-issuing/i.test(detail)
    ? 'No resolvable memory demand'
    : detail.length > 90 ? `${detail.slice(0, 90)}…` : detail;
  return { kind: 'blocked', cause, backend: bad.backend ?? '—' };
}

function fmtCycles(value: number): string {
  return Math.round(value).toLocaleString('en-US');
}

function fmtValue(value: number): string {
  if (!Number.isFinite(value)) return '—';
  if (Math.abs(value - Math.round(value)) < 1e-9) {
    return Math.round(value).toLocaleString('en-US');
  }
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
}

function metricByKey(
  analysis: FederatedAnalysisView, key: string,
): NormalizedMetricView | null {
  return (analysis.normalized_metrics ?? []).find((m) => m.key === key) ?? null;
}

function headlineMetric(analysis: FederatedAnalysisView): NormalizedMetricView | null {
  return (analysis.normalized_metrics ?? [])[0] ?? null;
}

function metricUnit(m: NormalizedMetricView): string {
  if (m.unit) return m.unit;
  return m.key.endsWith('_cycles') ? 'cycles' : '';
}

function findAnalysis(
  analyses: FederatedAnalysisView[], question: string,
): FederatedAnalysisView | null {
  return analyses.find((a) => a.question === question) ?? null;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function CoveragePill({ label, state }: {
  label: string;
  state: string;
}): ReactElement {
  const cls = state === 'READY' ? 'good' : state === 'BLOCKED' ? 'bad' : 'muted';
  return (
    <span className="coverage-pill">
      <span className={cls}>{state === 'READY' ? '✓' : state === 'BLOCKED' ? '!' : '○'}</span>{' '}
      {label} · {state}
    </span>
  );
}

function ContextStrip({ projectId, revisionLabel, certificate, plan }: {
  projectId: string;
  revisionLabel: string;
  certificate: string | null;
  plan: EvaluationPlanView | null;
}): ReactElement {
  const draft = useAsync(() => api.draft(projectId), [projectId]);
  const doc = draft.result.state === 'ready'
    ? (draft.result.data.request ?? {}) as Record<string, unknown>
    : {};
  const workload = (doc['workload'] ?? {}) as Record<string, unknown>;
  const noc = (doc['noc_config'] ?? {}) as Record<string, unknown>;
  const tp = num(workload['tp']);
  const servingRows = (plan?.analyses ?? []).filter((a) => a.question.startsWith('SERVING'));
  const netState = plan?.analyses.find((a) => a.question === 'NETWORK_COMPLETION')?.readiness;
  const schedState = plan?.analyses.find((a) => a.question === 'SYSTEM_MAKESPAN')?.readiness;
  const memState = plan?.analyses.find((a) => a.question === 'DRAM_TIMING')?.readiness;
  return (
    <section className="card eval-context" aria-label="Evaluation context">
      <div className="context-line">
        <span className="context-rev">{revisionLabel}</span>
        <span className="muted">·</span>
        <span>{certificate ? `certificate ${certificate}` : 'certificate —'}</span>
      </div>
      <div className="context-line muted">
        {str(workload['model_name']) ?? 'workload'}
        {tp != null ? ` · TP${tp}` : ''} · {str(noc['topology_family']) ?? 'fabric'}
        {num(noc['link_width']) != null ? ` · ${noc['link_width']}-bit` : ''}
      </div>
      <div className="coverage-pills" aria-label="Model coverage">
        <CoveragePill label="Network" state={netState ?? 'NOT CONFIGURED'} />
        <CoveragePill label="Schedule" state={schedState ?? 'NOT CONFIGURED'} />
        <CoveragePill label="Memory" state={memState ?? 'NOT CONFIGURED'} />
        <CoveragePill label="Compute" state="DECLARED ONLY" />
        <CoveragePill
          label="Serving"
          state={servingRows.length === 0
            ? 'NOT CONFIGURED'
            : servingRows.every((r) => r.readiness === 'READY') ? 'READY' : 'BLOCKED'}
        />
      </div>
    </section>
  );
}

function QuestionCard({ projectId, group, plan, selected, onToggle }: {
  projectId: string;
  group: QuestionGroup;
  plan: EvaluationPlanView | null;
  selected: Set<string>;
  onToggle: (group: QuestionGroup) => void;
}): ReactElement {
  const state = groupState(group, plan);
  const backend = state.kind === 'ready'
    ? [...new Set(state.rows.map((r) => r.backend).filter((b) => b != null))].join(' + ')
    : state.kind === 'blocked' ? state.backend : null;
  const backendName = backend
    ?.split(' + ').map((b) => backendLabel(b)).join(' + ') ?? backend;
  const checked = state.kind === 'ready'
    && state.rows.every((r) => selected.has(r.question));
  return (
    <section className="card question-card" aria-label={group.title}>
      <h3>{group.title}</h3>
      <p>{group.question}</p>
      {state.kind === 'ready' && (
        <>
          <p className="muted">{backendName}</p>
          <label className="question-select">
            <input
              type="checkbox"
              checked={checked}
              onChange={() => onToggle(group)}
              aria-label={`Select ${group.title}`}
            />
            {checked ? 'Selected ✓' : 'Select'}
          </label>
        </>
      )}
      {state.kind === 'blocked' && (
        <>
          <p><span className="model-pill model-blocked">BLOCKED</span></p>
          {group.id === 'memory' ? (
            <>
              <p className="muted">{dramConsequence(state.cause)}</p>
              <div className="empty-actions">
                {/carry no placement|issue_node|memory-issuing/i.test(state.cause) ? (
                  <Link className="btn btn-small" to={`/projects/${projectId}/design`}>
                    Configure memory mapping →
                  </Link>
                ) : (
                  <Link className="btn btn-small" to={`/projects/${projectId}/compile`}>
                    Inspect execution →
                  </Link>
                )}
              </div>
            </>
          ) : (
            <>
              <p className="muted">{state.cause}</p>
              <div className="empty-actions">
                {group.id === 'serving' ? (
                  <Link className="btn btn-small" to={`/projects/${projectId}/serving`}>
                    Bind experiment →
                  </Link>
                ) : null}
              </div>
            </>
          )}
        </>
      )}
      {state.kind === 'unconfigured' && (
        <>
          <p><span className="model-pill model-not-configured">NOT CONFIGURED</span></p>
          <div className="empty-actions">
            {group.id === 'serving' ? (
              <Link className="btn btn-small" to={`/projects/${projectId}/serving`}>
                Configure experiment →
              </Link>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

function groupDisplayTitle(question: string): string {
  if (question === 'SYSTEM_MAKESPAN') return 'Distributed schedule';
  if (question === 'NETWORK_COMPLETION') return 'Network completion';
  if (question === 'COMMUNICATION_EXPOSURE') return 'Collective cost (no overlap)';
  if (question === 'PER_RANK_COMPLETION') return 'Per-rank completion';
  if (question === 'DRAM_TIMING') return 'Memory timing';
  if (question === 'SERVING_TTFT') return 'Serving TTFT';
  if (question === 'SERVING_COMPLETION') return 'Serving completion';
  return question;
}

function PlanSummary({ plan, selected, backend, onRun, running, canRun }: {
  plan: EvaluationPlanView | null;
  selected: Set<string>;
  backend: string | null;
  onRun: () => void;
  running: boolean;
  canRun: boolean;
}): ReactElement {
  const rows = sortQuestions(
    (plan?.analyses ?? []).filter((a) => selected.has(a.question)),
    (r) => r.question,
  );
  if (rows.length === 0) return <></>;
  const grouped: {
    title: string; backend: string; detail: string | null;
    numerical: string | null; calibration: string | null;
  }[] = [];
  for (const g of GROUPS) {
    const inGroup = rows.filter((r) => g.questions.includes(r.question));
    if (inGroup.length === 0) continue;
    const backends = [...new Set(inGroup.map((r) => r.backend).filter((b) => b != null))];
    const qual = inGroup.map((r) => r.qualification).find((q) => q != null) ?? null;
    grouped.push({
      numerical: qual?.numerical_qualification ?? null,
      calibration: qual?.calibration ?? null,
      title: g.id === 'schedule' ? 'Distributed schedule'
        : g.id === 'network' ? 'Network completion'
        : g.id === 'memory' ? 'Memory timing' : 'Serving',
      backend: backends.map((b) => backendLabel(b as string)).join(' + '),
      detail: inGroup.length > 1
        ? inGroup.map((r) => groupDisplayTitle(r.question))
          .filter((t) => t.toLowerCase() !== (
            g.id === 'schedule' ? 'distributed schedule'
              : g.id === 'network' ? 'network completion'
                : g.id === 'memory' ? 'memory timing' : 'serving'))
          .join(' · ').toLowerCase() || null
        : null,
    });
  }
  return (
    <section className="card" aria-label="Evaluation plan">
      <h3>Evaluation plan</h3>
      <p className="muted">{rows.length} {rows.length === 1 ? 'analysis' : 'analyses'} will run</p>
      {grouped.map((g) => (
        <div className="kv" key={g.title}>
          <span>{g.title}{g.detail ? <span className="muted"> · {g.detail}</span> : null}</span>
          <span className="muted">
            {g.backend || '—'}
            {g.numerical ? ` · numerical ${g.numerical.toLowerCase()}` : ''}
            {g.calibration ? ` · calibration ${g.calibration.toLowerCase().replace('_', ' ')}` : ''}
          </span>
        </div>
      ))}
      <p className="muted">
        Execution policy: <strong>Automatic</strong> — the qualified backend is
        selected per analysis
        {backend ? ` (pinned: ${backend})` : ''}. Readiness means the backend
        can run; it does not imply numerical qualification or calibration —
        those are stated per row above.
      </p>
      <div className="form-row">
        <button className="btn btn-primary" disabled={!canRun} onClick={onRun}>
          {running ? 'Running…' : `Run ${rows.length} ${rows.length === 1 ? 'analysis' : 'analyses'}`}
        </button>
      </div>
    </section>
  );
}

function AnswerCard({ title, value, unit, backend, qualification }: {
  title: string;
  value: string;
  unit: string;
  backend: string;
  qualification: string | null;
}): ReactElement {
  return (
    <section className="card answer-card" aria-label={title}>
      <h3>{title}</h3>
      <p className="answer-value">{value}{unit ? <span className="muted"> {unit}</span> : null}</p>
      <p className="muted">{backend}</p>
      {qualification && <p><span className="model-pill model-detailed">{qualification}</span></p>}
    </section>
  );
}

function ExecutionView({ bars }: {
  bars: { label: string; value: number }[];
}): ReactElement | null {
  if (bars.length === 0) return null;
  const max = Math.max(...bars.map((b) => b.value));
  return (
    <section className="card" aria-label="Execution view">
      <h3>Execution view</h3>
      <div className="exec-axis" aria-hidden="true">
        <span>0</span>
        <span>{fmtCycles(max)} cycles</span>
      </div>
      {bars.map((b) => (
        <div className="exec-bar-row" key={b.label}>
          <span className="exec-bar-label">{b.label}</span>
          <div className="exec-bar-track">
            <div
              className="exec-bar-fill"
              style={{ width: `${Math.max(2, (b.value / max) * 100)}%` }}
            />
          </div>
          <span className="exec-bar-value num">{fmtCycles(b.value)}</span>
        </div>
      ))}
      <p className="muted">
        Durations share a cycle axis for comparison — they are not additive
        phases and are never summed into an end-to-end runtime.
      </p>
    </section>
  );
}

function NetworkTab({ analysis }: { analysis: FederatedAnalysisView }): ReactElement {
  const get = (key: string): number | null => {
    const m = metricByKey(analysis, key);
    return m ? num(m.value) : null;
  };
  const rows: [string, number | null][] = [
    ['Completion', get('completion_cycles')],
    ['Delivered packets', get('delivered_packets')],
    ['Injected packets', get('injected_trace_packets')],
    ['Flits injected', get('flits_injected')],
    ['Flits accepted', get('flits_accepted')],
    ['Packet latency avg', get('packet_latency_avg')],
    ['Flit latency avg', get('flit_latency_avg')],
    ['Simulation window', get('sample_window_cycles')],
  ];
  return (
    <div>
      {rows.filter(([, v]) => v != null).map(([label, v]) => (
        <div className="kv" key={label}>
          <span>{label}</span><span className="num">{fmtValue(v as number)}</span>
        </div>
      ))}
      {(analysis.limitations ?? []).length > 0 && (
        <p className="muted">Limitations: {(analysis.limitations ?? []).join('; ')}</p>
      )}
    </div>
  );
}

function ScheduleTab({ analyses }: { analyses: FederatedAnalysisView[] }): ReactElement {
  const makespan = findAnalysis(analyses, 'SYSTEM_MAKESPAN');
  const exposure = findAnalysis(analyses, 'COMMUNICATION_EXPOSURE');
  const perRank = findAnalysis(analyses, 'PER_RANK_COMPLETION');
  const makespanVal = makespan ? num(metricByKey(makespan, 'system_makespan_cycles')?.value) : null;
  const exposureVal = exposure
    ? num(metricByKey(exposure, 'communication_exposure_cycles')?.value) : null;
  const rankEndpoints = new Map<number, number>();
  const pairs = perRank?.native_summary?.['rank_to_endpoint'];
  if (Array.isArray(pairs)) {
    for (const pair of pairs) {
      const arr = pair as unknown[];
      if (typeof arr[0] === 'number' && typeof arr[1] === 'number') {
        rankEndpoints.set(arr[0], arr[1]);
      }
    }
  }
  const rankMetrics = (perRank?.normalized_metrics ?? [])
    .filter((m) => m.key === 'completion_cycles' && m.dimensions.length > 0);
  return (
    <div>
      <h4>Collective schedule makespan</h4>
      {makespanVal != null && (
        <p className="answer-value">{fmtCycles(makespanVal)} <span className="muted">cycles</span></p>
      )}
      <div className="kv"><span>Communication exposure</span>
        <span className="num">{exposureVal != null ? `${fmtCycles(exposureVal)} cycles` : '—'}</span>
      </div>
      <div className="kv"><span>Ranks</span>
        <span className="num">{rankMetrics.length > 0 ? rankMetrics.length : '—'}</span>
      </div>
      {rankMetrics.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Rank</th><th>Endpoint</th><th>Completion (cycles)</th></tr></thead>
          <tbody>
            {rankMetrics.map((m, i) => {
              const dim = m.dimensions[0]?.[1];
              const rank = dim != null && dim !== '' ? Number(dim) : i;
              return (
                <tr key={i}>
                  <td className="num">{rank}</td>
                  <td className="num">{rankEndpoints.get(rank) ?? '—'}</td>
                  <td className="num">{fmtCycles(num(m.value) ?? 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {((makespan?.limitations ?? []).length > 0) && (
        <p className="muted">Limitations: {(makespan?.limitations ?? []).join('; ')}</p>
      )}
    </div>
  );
}

function RequirementsTab({ entries }: { entries: RequirementEntry[] | null }): ReactElement {
  if (!entries || entries.length === 0) {
    return <p className="muted">No requirement verdicts carried by this run.</p>;
  }
  return (
    <div>
      {entries.map((e) => (
        <div className="kv" key={e.requirement_index}>
          <span>
            <StatusBadge status={e.verdict} />{' '}
            {e.qos_class?.replace(/_/g, ' ') ?? `Requirement ${e.requirement_index}`}
            {e.binding ? ' · binding' : ''}
          </span>
          <span className="muted" title={e.reason}>
            {e.measured != null ? `${e.measured}` : '—'}
            {e.required != null ? ` ≤ ${e.required}` : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

function EvidenceTab({ projectId, runId, run }: {
  projectId: string;
  runId: string;
  run: {
    design_hash: string | null; bundle_id: string | null;
    workload: string | null; backend: string | null;
    producer: {
      backend: string; producer_identity: string;
      config_hash: string; input_hash: string;
    } | null;
    analyses: { label: string; backend: string; evidence: string | null }[];
  };
}): ReactElement {
  const merged: { label: string; backend: string; evidence: string | null }[] = [];
  for (const a of run.analyses) {
    const prior = merged.find((m) => m.backend === a.backend && m.evidence === a.evidence);
    if (prior && a.evidence) {
      prior.label = `${prior.label} · ${a.label}`;
    } else {
      merged.push({ ...a });
    }
  }
  return (
    <div>
      <h4>Execution provenance</h4>
      <div className="kv"><span>Design</span><Hash value={run.design_hash} /></div>
      <div className="kv"><span>Workload</span><span className="muted">{run.workload ?? '—'}</span></div>
      <div className="kv"><span>Run bundle</span><Hash value={run.bundle_id} /></div>
      {run.producer && (
        <>
          <div className="kv"><span>Producer</span><span>{run.producer.backend}</span></div>
          <div className="kv"><span>Producer identity</span><Hash value={run.producer.producer_identity} /></div>
          <div className="kv"><span>Config</span><Hash value={run.producer.config_hash} /></div>
          <div className="kv"><span>Input</span><Hash value={run.producer.input_hash} /></div>
        </>
      )}
      {merged.map((a) => (
        <div className="kv" key={a.label}>
          <span>{a.label}</span>
          <span className="muted">
            {a.backend}{a.evidence ? ` · ${shortHash(a.evidence)}` : ''}
          </span>
        </div>
      ))}
      <div className="empty-actions">
        <Link className="btn btn-small" to={`/runs/${runId}`}>Open run →</Link>
        <Link className="btn btn-small" to={`/projects/${projectId}/reproduce`}>Reproduce run →</Link>
        <Link className="btn btn-small" to={`/projects/${projectId}/evidence`}>Open evidence graph →</Link>
      </div>
    </div>
  );
}

function BlockedAnalysis({ projectId, analysis }: {
  projectId: string;
  analysis: FederatedAnalysisView;
}): ReactElement {
  const raw = analysis.reason ?? `${analysis.status} — no metrics carried.`;
  const consequence = analysis.question === 'DRAM_TIMING'
    && /resolvable memory demand|no placement|memory-issuing/i.test(raw)
    ? dramConsequence(raw)
    : 'This analysis did not produce metrics — see the diagnostic.';
  return (
    <div className="blocked-analysis">
      <p>
        <span className="model-pill model-blocked">{analysis.status}</span>{' '}
        <strong>{analysis.question}</strong>
      </p>
      <p>{consequence}</p>
      {analysis.question === 'DRAM_TIMING' && (
        <div className="empty-actions">
          <Link className="btn btn-small" to={`/projects/${projectId}/design`}>
            Resolve memory mapping
          </Link>
        </div>
      )}
      <details className="subtle">
        <summary>Technical diagnostic</summary>
        <p className="muted model-diagnostic">{raw}</p>
      </details>
    </div>
  );
}

type ResultTab = 'summary' | 'network' | 'schedule' | 'requirements' | 'evidence';

export default function Evaluate({ projectId }: { projectId: string }): ReactElement {
  const { refreshProjects } = useStudio();
  const project = useAsync(() => api.project(projectId), [projectId]);
  const [backend, setBackend] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [tab, setTab] = useState<ResultTab>('summary');

  const revisionId = project.result.state === 'ready'
    ? project.result.data.active_revision_id
    : null;

  const planAsync = useAsync(
    () => (revisionId
      ? api.evaluationPlan(revisionId, backend ? { backend } : undefined)
      : Promise.reject(new Error('no revision'))),
    [revisionId, backend],
  );
  const plan: EvaluationPlanView | null =
    planAsync.result.state === 'ready' ? planAsync.result.data : null;

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const stamped = useRef<string>('');
  const stamp = plan
    ? `${backend ?? 'all'}|${plan.analyses.map(
      (a) => `${a.question}:${a.readiness}`).sort().join(',')}` : '';
  useEffect(() => {
    if (!plan || stamped.current === stamp) return;
    stamped.current = stamp;
    const ready = plan.analyses
      .filter((a) => a.readiness === 'READY')
      .map((a) => a.question);
    setSelected(new Set(ready));
  });

  const backends: string[] = plan
    ? [...new Set(plan.analyses
      .map((a) => a.backend)
      .filter((b): b is string => b != null))]
    : [];

  const toggleGroup = (group: QuestionGroup): void => {
    if (!plan) return;
    const st = groupState(group, plan);
    if (st.kind !== 'ready') return;
    const next = new Set(selected);
    if (st.rows.every((r) => next.has(r.question))) {
      for (const r of st.rows) next.delete(r.question);
    } else {
      for (const r of st.rows) next.add(r.question);
    }
    setSelected(next);
  };

  const onTerminal = (job: JobView): void => {
    setRunId(job.result?.run_id ?? null);
    project.reload();
    refreshProjects();
  };
  const job = useJobPoll(jobId, onTerminal);
  const running = job !== null
    && !['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state);

  const run = useAsync(
    () => (runId ? api.run(runId) : Promise.reject(new Error('no run'))),
    [runId],
  );
  const runData: RunView | null =
    runId != null && run.result.state === 'ready' ? run.result.data : null;

  const start = async (): Promise<void> => {
    if (!revisionId) return;
    setError(null);
    setRunId(null);
    try {
      const submitted = await api.evaluate(revisionId, {
        questions: selected.size > 0 ? [...selected] : null,
        backend,
      });
      setJobId(submitted.job_id);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  return (
    <AsyncView result={project.result} reload={project.reload}>
      {(p) => {
        const current = p.active_revision;
        const blocker = (() => {
          if (!current) {
            return { text: 'No compiled revision exists yet.', section: 'design', label: 'Go to Design' };
          }
          if (current.compilation.status !== 'COMPILED') {
            return {
              text: current.compilation.error ?? 'Compilation was refused for this revision.',
              section: 'design', label: 'Fix design and compile',
            };
          }
          if (current.certificate?.overall !== 'PASS') {
            return {
              text: 'The verification certificate is not PASS.',
              section: 'compile', label: 'Inspect verification',
            };
          }
          if (p.active_evaluation && !p.active_evaluation.supported) {
            return {
              text: simulationCapabilityReason(p.active_evaluation.domain, p.active_evaluation.reason)
                + ' The fabric is certified; it just cannot be executed by this backend.',
              section: 'design', label: 'Edit design',
            };
          }
          if (p.draft.dirty) {
            return {
              text: `The draft has uncompiled changes. The active revision is ${current.display_name}; compile to evaluate the new intent.`,
              section: 'design', label: 'Recompile draft',
            };
          }
          return null;
        })();

        const canRun = Boolean(current)
          && current!.compilation.status === 'COMPILED'
          && current!.certificate?.overall === 'PASS'
          && (p.active_evaluation?.supported ?? true)
          && !p.draft.dirty && !running && !blocker
          && selected.size > 0;

        return (
          <div className="page">
            <div className="page-head">
              <div>
                <h2>Evaluate</h2>
                <p className="muted">
                  Answer engineering questions about the current design using the
                  qualified models available for this revision.
                </p>
              </div>
              {runData && (
                <div className="head-actions">
                  <button type="button" className="btn btn-small" onClick={() => {
                    setJobId(null); setRunId(null); setError(null); setTab('summary');
                  }}>
                    Run another evaluation
                  </button>
                </div>
              )}
            </div>

            {runData
              ? (
                <ResultState
                  projectId={projectId}
                  run={runData}
                  tab={tab}
                  setTab={setTab}
                />
              )
              : (
                <>
                  {current && (
                    <ContextStrip
                      projectId={projectId}
                      revisionLabel={`${p.project.name} · ${current.display_name}`}
                      certificate={current.certificate?.overall ?? null}
                      plan={plan}
                    />
                  )}
                  {blocker ? (
                    <section className="card" role="status">
                      <h3>Cannot run yet</h3>
                      <p className="muted">{blocker.text}</p>
                      <Link className="btn" to={`/projects/${projectId}/${blocker.section}`}>
                        {blocker.label}
                      </Link>
                    </section>
                  ) : (
                    <>
                      <h3 className="eval-section-head">What do you want to learn?</h3>
                      <div className="question-grid">
                        {GROUPS.map((g) => (
                          <QuestionCard
                            key={g.id}
                            projectId={projectId}
                            group={g}
                            plan={plan}
                            selected={selected}
                            onToggle={toggleGroup}
                          />
                        ))}
                      </div>
                      <PlanSummary
                        plan={plan}
                        selected={selected}
                        backend={backend}
                        onRun={start}
                        running={running}
                        canRun={canRun}
                      />
                      {error && <ErrorBox error={error} />}
                      <JobProgress job={job} />
                      {job?.state === 'REFUSED' && (
                        <ErrorBox error={new Error(job.error_message ?? 'evaluation refused')} />
                      )}
                      <details className="card subtle" aria-label="Expert execution policy">
                        <summary>
                          Expert execution policy · inspect inputs and backend selection
                        </summary>
                        <div className="form-row">
                          <label>
                            Backend pin
                            <select
                              aria-label="Backend pin"
                              value={backend ?? 'all'}
                              onChange={(e) => setBackend(
                                e.target.value === 'all' ? null : e.target.value)}
                            >
                              <option value="all">Automatic — qualified backend per analysis</option>
                              {backends.map((b) => (
                                <option key={b} value={b}>{b}</option>
                              ))}
                            </select>
                          </label>
                          <span className="muted">
                            Pinning fetches a fresh server plan — backends are never assumed equivalent.
                          </span>
                        </div>
                        {plan && <EvaluationPlanTable plan={plan} />}
                      </details>
                    </>
                  )}
                </>
              )}
          </div>
        );
      }}
    </AsyncView>
  );
}

function ResultState({ projectId, run, tab, setTab }: {
  projectId: string;
  run: RunView;
  tab: ResultTab;
  setTab: (t: ResultTab) => void;
}): ReactElement {
  const analyses = run.analyses ?? [];
  const evaluated = analyses.filter((a) => a.status === 'EVALUATED');
  const blocked = analyses.filter((a) => a.status !== 'EVALUATED');

  const net = findAnalysis(evaluated, 'NETWORK_COMPLETION');
  const sched = findAnalysis(evaluated, 'SYSTEM_MAKESPAN');
  const netHead = net ? (metricByKey(net, 'completion_cycles') ?? headlineMetric(net)) : null;
  const schedHead = sched
    ? (metricByKey(sched, 'system_makespan_cycles') ?? headlineMetric(sched))
    : null;

  const qualified = run.qualification === 'QUALIFIED';
  const notEstablished: string[] = [
    'End-to-end model runtime',
    'Hardware-predicted compute time',
  ];
  if (!findAnalysis(evaluated, 'DRAM_TIMING')) notEstablished.push('DRAM timing');
  if (!evaluated.some((a) => a.question.startsWith('SERVING'))) {
    notEstablished.push('Serving TTFT / completion');
  }

  const bars: { label: string; value: number }[] = [];
  if (netHead && num(netHead.value) != null) {
    bars.push({ label: 'Network', value: num(netHead.value) as number });
  }
  if (schedHead && num(schedHead.value) != null) {
    bars.push({ label: 'Distributed schedule', value: num(schedHead.value) as number });
  }

  const tabs: { id: ResultTab; label: string; show: boolean }[] = [
    { id: 'summary', label: 'Summary', show: true },
    { id: 'network', label: 'Network', show: net != null },
    { id: 'schedule', label: 'Schedule', show: sched != null },
    {
      id: 'requirements', label: 'Requirements',
      show: (run.requirements?.entries ?? []).length > 0,
    },
    { id: 'evidence', label: 'Evidence', show: true },
  ];

  return (
    <div>
      <section className="card result-head" aria-label="Evaluation result">
        <h3>
          Evaluation complete{' '}
          <StatusBadge status={run.status ?? 'UNKNOWN'} />
        </h3>
        <p className="muted">
          {evaluated.length} / {analyses.length} selected{' '}
          {analyses.length === 1 ? 'analysis' : 'analyses'} completed
          {qualified ? ' · qualified evidence available' : ''}
        </p>
        <p className="muted">Run · {run.display_name ?? run.run_id}</p>
      </section>

      {tab === 'summary' && (
        <>
          <div className="answer-grid">
            {net && netHead && (
              <AnswerCard
                title="Network completion"
                value={fmtCycles(num(netHead.value) ?? 0)}
                unit={metricUnit(netHead)}
                backend={backendLabel(net.backend_id)}
                qualification={net.qualification}
              />
            )}
            {sched && schedHead && (
              <AnswerCard
                title="Distributed schedule"
                value={fmtCycles(num(schedHead.value) ?? 0)}
                unit={metricUnit(schedHead)}
                backend={`${backendLabel(sched.backend_id)} + ${backendLabel('BOOKSIM_STANDALONE')}`}
                qualification={sched.qualification}
              />
            )}
          </div>
          <section className="card" aria-label="What these results mean">
            <h3>What these results mean</h3>
            {netHead && (
              <p>
                <strong>Network.</strong> Physical traffic completed in{' '}
                {fmtCycles(num(netHead.value) ?? 0)} network cycles.
              </p>
            )}
            {schedHead && (
              <p>
                <strong>Distributed schedule.</strong> The qualified collective
                schedule completed in {fmtCycles(num(schedHead.value) ?? 0)} cycles.
              </p>
            )}
            <p className="muted">
              <strong>Not established by this run.</strong>{' '}
              {notEstablished.join(' · ')}.
            </p>
          </section>
          <ExecutionView bars={bars} />
          {blocked.length > 0 && (
            <section className="card" aria-label="Blocked analyses">
              <h3>Blocked</h3>
              {blocked.map((a) => (
                <BlockedAnalysis key={a.question} projectId={projectId} analysis={a} />
              ))}
            </section>
          )}
        </>
      )}

      <nav className="result-tabs" aria-label="Result views">
        {tabs.filter((t) => t.show).map((t) => (
          <button
            key={t.id}
            className={`result-tab${tab === t.id ? ' active' : ''}`}
            aria-current={tab === t.id ? 'true' : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'network' && net && <section className="card"><NetworkTab analysis={net} /></section>}
      {tab === 'schedule' && sched && (
        <section className="card"><ScheduleTab analyses={evaluated} /></section>
      )}
      {tab === 'requirements' && (
        <section className="card">
          <RequirementsTab entries={run.requirements?.entries ?? null} />
        </section>
      )}
      {tab === 'evidence' && (
        <section className="card">
          <EvidenceTab
            projectId={projectId}
            runId={run.run_id}
            run={{
              design_hash: run.design_hash,
              bundle_id: run.bundle_id,
              workload: run.evaluation?.workload_id ?? null,
              backend: run.backend,
              producer: run.producer,
              analyses: evaluated.map((a) => ({
                label: a.question === 'NETWORK_COMPLETION'
                  ? 'Network'
                  : a.question === 'SYSTEM_MAKESPAN'
                    ? 'Distributed schedule'
                    : a.question === 'COMMUNICATION_EXPOSURE'
                      ? 'Collective cost (no overlap)'
                      : a.question === 'PER_RANK_COMPLETION'
                        ? 'Per-rank completion'
                        : a.question,
                backend: backendLabel(a.backend_id),
                evidence: a.native_evidence_id,
              })),
            }}
          />
        </section>
      )}
    </div>
  );
}
