import type { ReactElement } from 'react';
import type {
  EvaluationPlanView,
  FederatedAnalysisView,
  NormalizedMetricView,
  PlannedAnalysisView,
} from '../api/types';
import type { EvaluationView, RequirementReport } from '../types';
import { Hash, StatusBadge, humanize } from './badges';
import {
  EpistemicChip,
  ScientificValue,
  backendLabel,
  questionLabel,
} from './ScientificValue';
import EvaluateView from './EvaluateView';

// Federated evaluation rendering (P5). Every value is server truth:
// the plan rows adjudicated by EvaluationPlanner and the per-analysis
// records persisted by the federated evaluator. React derives nothing —
// no support/readiness computation, no metric fabrication, no
// cross-backend equivalence assumption.

function scalar(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'string' || typeof value === 'number'
    || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

// ── Evaluation plan ──────────────────────────────────────────────────

// ── Question-first federation (§11) ─────────────────────────────────────
// Canonical engineering-question order. Unknown questions sort last,
// never dropped: every server row renders exactly once.
const QUESTION_ORDER = [
  'NETWORK_COMPLETION',
  'SYSTEM_MAKESPAN',
  'COMMUNICATION_EXPOSURE',
  'PER_RANK_COMPLETION',
  'DRAM_TIMING',
  'SERVING_TTFT',
  'SERVING_COMPLETION',
];

export function sortQuestions<T>(rows: T[], pick: (r: T) => string): T[] {
  return [...rows].sort((a, b) => {
    const ia = QUESTION_ORDER.indexOf(pick(a));
    const ib = QUESTION_ORDER.indexOf(pick(b));
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });
}

/** Epistemic class follows the adjudicated fidelity, never the backend
 * name: Wave-E/analytical model outputs are MODELLED, never MEASURED. */
export function epistemicFor(analysis: {
  status: string;
  model_fidelity: string | null;
}): string | null {
  if (analysis.status !== 'EVALUATED') return null;
  const f = (analysis.model_fidelity ?? '').toLowerCase();
  if (f.includes('wave-e') || f.includes('analytical') || f.includes('model')) {
    return 'MODELLED';
  }
  return 'SIMULATED';
}

/** Execution policy banner: AUTO (planner chooses the qualified producer
 * per question) is the default; a pinned backend is Expert policy. */
export function ExecutionPolicyBanner({ policy }: {
  policy?: { mode: 'AUTO' } | { mode: 'PINNED'; backend: string } | null;
}): ReactElement {
  if (policy?.mode === 'PINNED') {
    return (
      <p className="muted">
        Execution policy: <strong>Expert pin</strong> — backend{' '}
        <code>{policy.backend}</code> pinned by the user. Readiness below is
        still the planner&apos;s verdict for that pin, never assumed.
      </p>
    );
  }
  return (
    <p className="muted">
      Execution policy: <strong>AUTO</strong> — the planner chooses the
      qualified producer per question. Manual backend pinning is Expert
      execution policy.
    </p>
  );
}

function PlanRow({ row }: { row: PlannedAnalysisView }): ReactElement {
  return (
    <>
      <td><code title={questionLabel(row.question)}>{row.question}</code><br /><span className="muted">{questionLabel(row.question)}</span></td>
      <td className="muted">{row.backend ? (<><span>{backendLabel(row.backend)}</span> <code>{row.backend}</code></>) : '—'}</td>
      <td className="muted">{row.support}</td>
      <td><StatusBadge status={row.readiness} /></td>
      <td className="muted">{row.model_fidelity ?? '—'}</td>
      <td className="muted">{row.qualification_profile ?? '—'}</td>
      <td className="muted">{row.reason ?? '—'}</td>
      <td className="muted">
        {row.limitations.length === 0 ? '—' : row.limitations.join('; ')}
      </td>
    </>
  );
}

/** The server's adjudicated plan. `selected`/`onToggle` exist so the
 * caller can offer checkboxes — enabled only for READY rows. */
export function EvaluationPlanTable({ plan, selected, onToggle, executionPolicy }: {
  plan: EvaluationPlanView;
  selected?: Set<string> | null;
  onToggle?: ((question: string) => void) | null;
  executionPolicy?: { mode: 'AUTO' } | { mode: 'PINNED'; backend: string } | null;
}): ReactElement {
  const selectable = selected != null && onToggle != null;
  const rows = sortQuestions(plan.analyses, (r) => r.question);
  return (
    <div>
      <div className="kv"><span>workload</span><span>{plan.workload_id}</span></div>
      <div className="kv"><span>design</span><Hash value={plan.design_hash} /></div>
      <div className="kv"><span>resolved fabric</span>
        <Hash value={plan.resolved_fabric_hash} />
      </div>
      <ExecutionPolicyBanner policy={executionPolicy ?? { mode: 'AUTO' }} />
      <table className="live-table">
        <thead>
          <tr>
            {selectable && <th>run</th>}
            <th>question</th><th>backend</th><th>support</th><th>readiness</th>
            <th>fidelity</th><th>qualification</th><th>reason</th>
            <th>limitations</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const ready = row.readiness === 'READY';
            return (
              <tr key={row.question}>
                {selectable && (
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${row.question}`}
                      checked={selected.has(row.question)}
                      // Only READY rows are runnable; anything else is
                      // disabled, never silently runnable.
                      disabled={!ready}
                      title={ready ? row.question
                        : `${row.question}: ${row.reason ?? row.readiness}`}
                      onChange={() => onToggle(row.question)}
                    />
                  </td>
                )}
                <PlanRow row={row} />
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Normalized metrics ───────────────────────────────────────────────

function MetricsTable({ metrics, analysis }: {
  metrics: NormalizedMetricView[] | null;
  analysis: FederatedAnalysisView;
}): ReactElement {
  if (!metrics || metrics.length === 0) {
    return (
      <p className="muted">
        No normalized metrics carried — nothing shown, nothing zero-filled.
      </p>
    );
  }
  // Metric-level epistemics ride the analysis envelope: the backend that
  // executed the question, at the fidelity and qualification the planner
  // adjudicated. Wave-E/analytical model outputs render MODELLED, never
  // MEASURED. A metric without an executed analysis is never rendered
  // as a bare number.
  const epistemic = epistemicFor(analysis);
  return (
    <table className="tbl">
      <thead>
        <tr><th>metric</th><th>value</th><th>unit</th><th>dimensions</th></tr>
      </thead>
      <tbody>
        {metrics.map((m) => (
          <tr key={m.key}>
            <td title={m.source_metric_key ?? ''}>{humanize(m.key)}</td>
            <td>
              <ScientificValue
                value={m.value}
                unit={m.unit}
                epistemic={epistemic}
                source={backendLabel(analysis.backend_id)}
                fidelity={analysis.model_fidelity}
                qualification={analysis.qualification}
              />
            </td>
            <td className="muted">{m.unit ?? '—'}</td>
            <td className="muted">
              {m.dimensions.length === 0
                ? '—'
                : m.dimensions.map((d) => `[${d.join(', ')}]`).join(' ')}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NativeSummary({ summary }: {
  summary: Record<string, unknown> | null;
}): ReactElement {
  if (!summary) return <p className="muted">No native summary carried.</p>;
  const entries = Object.entries(summary);
  if (entries.length === 0) {
    return <p className="muted">No native summary carried.</p>;
  }
  return (
    <>
      {entries.map(([k, v]) => (
        <div className="kv" key={k}>
          <span>{humanize(k)}</span>
          <span className="muted">{scalar(v)}</span>
        </div>
      ))}
    </>
  );
}

function PerRankTable({ summary }: {
  summary: Record<string, unknown> | null;
}): ReactElement | null {
  const pairs = summary?.['rank_to_endpoint'];
  if (!Array.isArray(pairs) || pairs.length === 0) return null;
  return (
    <>
      <h4>Per-rank completion (rank → endpoint)</h4>
      <table className="tbl">
        <thead><tr><th>rank</th><th>endpoint</th></tr></thead>
        <tbody>
          {pairs.map((pair, i) => (
            <tr key={i}>
              <td className="num">{scalar((pair as unknown[])[0])}</td>
              <td className="num">{scalar((pair as unknown[])[1])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ── Per-analysis cards ───────────────────────────────────────────────

/** Headline metric: the first normalized metric, labelled with the
 * analysis envelope. Never merged across questions — one card, one
 * question, one backend. */
function HeadlineMetric({ analysis }: { analysis: FederatedAnalysisView }): ReactElement | null {
  const first = analysis.normalized_metrics?.[0];
  if (!first || analysis.status !== 'EVALUATED') return null;
  return (
    <p>
      <ScientificValue
        value={first.value}
        unit={first.unit}
        epistemic={epistemicFor(analysis)}
        source={analysis.backend_id ? backendLabel(analysis.backend_id) : null}
        fidelity={analysis.model_fidelity}
        qualification={analysis.qualification}
      />{' '}
      <span className="muted" title={first.source_metric_key ?? ''}>
        ({humanize(first.key)})
      </span>
    </p>
  );
}

export function AnalysisCard({ analysis, evaluation, requirements, actions }: {
  analysis: FederatedAnalysisView;
  /** The legacy network view — bound only to NETWORK_COMPLETION. */
  evaluation: EvaluationView | null;
  requirements: RequirementReport | null;
  actions?: {
    onInspectEvidence?: ((analysis: FederatedAnalysisView) => void) | null;
    onReproduce?: ((analysis: FederatedAnalysisView) => void) | null;
    onCompare?: ((analysis: FederatedAnalysisView) => void) | null;
  } | null;
}): ReactElement {
  const evaluated = analysis.status === 'EVALUATED';
  const isServing = analysis.question.startsWith('SERVING');
  return (
    <section className="card">
      <h3>
        {questionLabel(analysis.question)}{' '}
        <code className="muted" title="canonical evaluation question">{analysis.question}</code>{' '}
        <StatusBadge status={analysis.status} />{' '}
        {analysis.status === 'EVALUATED' && <EpistemicChip value={epistemicFor(analysis)} />}
      </h3>
      <HeadlineMetric analysis={analysis} />
      {isServing && (
        <p className="muted">
          Serving detail (TTFT distribution, per-request table) lives in the
          Serving workspace — this card carries only the federated envelope.
        </p>
      )}
      <div className="kv"><span>backend</span>
        <span>{backendLabel(analysis.backend_id)}{' '}<code>{analysis.backend_id ?? '—'}</code></span>
      </div>
      <div className="kv"><span>fidelity</span>
        <span className="muted">{analysis.model_fidelity ?? '—'}</span>
      </div>
      <div className="kv"><span>qualification</span>
        <span className="muted">{analysis.qualification ?? '—'}</span>
      </div>
      <div className="kv"><span>native evidence</span>
        <Hash value={analysis.native_evidence_id} />
      </div>
      {!evaluated && (
        <p className={analysis.status.includes('UNSUPPORTED')
          || analysis.status.includes('UNAVAILABLE') ? 'muted' : 'bad'}>
          {analysis.reason ?? `${analysis.status} — no metrics carried.`}
          <span className="no-metrics-note"> No metrics present; none invented.</span>
        </p>
      )}
      {evaluated && (
        <>
          <h4>Normalized metrics</h4>
          <MetricsTable metrics={analysis.normalized_metrics} analysis={analysis} />
          <h4>Native summary</h4>
          <NativeSummary summary={analysis.native_summary} />
          <PerRankTable summary={analysis.native_summary} />
          {analysis.limitations && analysis.limitations.length > 0 && (
            <p className="muted">
              Limitations: {analysis.limitations.join('; ')}
            </p>
          )}
          {actions && (actions.onInspectEvidence || actions.onReproduce || actions.onCompare) && (
            <p>
              {actions.onInspectEvidence && (
                <button className="btn" onClick={() => actions.onInspectEvidence?.(analysis)}>
                  Inspect evidence
                </button>
              )}{' '}
              {actions.onReproduce && (
                <button className="btn" onClick={() => actions.onReproduce?.(analysis)}>
                  Reproduce
                </button>
              )}{' '}
              {actions.onCompare && (
                <button className="btn" onClick={() => actions.onCompare?.(analysis)}>
                  Compare
                </button>
              )}
            </p>
          )}
        </>
      )}
      {analysis.question === 'NETWORK_COMPLETION' && (evaluation || requirements) && (
        <EvaluateView
          evaluation={evaluation}
          requirements={requirements}
          fixtureId={analysis.native_evidence_id ?? analysis.question}
          live
        />
      )}
    </section>
  );
}

/** All analyses of one federated run. The NETWORK_COMPLETION analysis
 * keeps the existing network window + RequirementReport rendering;
 * ASTRA analyses show makespan/exposure/per-rank + namespace/tier;
 * Ramulator analyses show drain counters/row stats + profile facts.
 * Serving evidence stays on the Serving page. */
export default function FederatedEvaluationView({ runId, analyses, evaluation, requirements, actions }: {
  runId: string;
  analyses: FederatedAnalysisView[] | null;
  evaluation: EvaluationView | null;
  requirements: RequirementReport | null;
  actions?: {
    onInspectEvidence?: ((analysis: FederatedAnalysisView) => void) | null;
    onReproduce?: ((analysis: FederatedAnalysisView) => void) | null;
    onCompare?: ((analysis: FederatedAnalysisView) => void) | null;
  } | null;
}): ReactElement {
  if (!analyses || analyses.length === 0) {
    // Legacy single-backend runs carry no federated record: the
    // historical network rendering is the whole result.
    return (
      <EvaluateView
        evaluation={evaluation}
        requirements={requirements}
        fixtureId={runId}
        live
      />
    );
  }
  const ordered = sortQuestions(analyses, (a) => a.question);
  const evaluated = ordered.filter((a) => a.status === 'EVALUATED').length;
  const blocked = ordered.length - evaluated;
  return (
    <div>
      <p className="muted">
        <strong>{ordered.length} {ordered.length === 1 ? 'analysis' : 'analyses'} requested</strong>{' '}—{' '}
        {evaluated} evaluated · {blocked} blocked/failed. Each card is one
        engineering question answered by its own backend; times across cards
        are never merged into one total.
      </p>
      {ordered.map((a) => (
        <AnalysisCard
          key={a.question}
          analysis={a}
          evaluation={evaluation}
          requirements={requirements}
          actions={actions}
        />
      ))}
    </div>
  );
}
