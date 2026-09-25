import { useMemo, useState, type ReactElement } from 'react';
import type {
  Candidate,
  CandidatePresentation,
  CandidateProductRequirements,
  ConstraintVerdict,
  DesignView,
  ObjectiveAvailability,
  OptimizationStudyView,
  PresentationEntry,
  PresentationMap,
  StudyConstraint,
  StudyObjective,
} from '../types';
import { Empty, Hash, StatusBadge, fmtNum, humanize } from './badges';
import presentationJson from '../presentation.json';

// Presentation is keyed ONLY by the engine's explicit contract values
// (src/presentation.json). Nothing here infers a state from an absent
// value: an unknown state renders as UNKNOWN, never as a passing style.
const presentation = presentationJson as unknown as CandidatePresentation;

function entry(
  map: PresentationMap,
  state: string | null | undefined,
  fallback = 'NOT CARRIED',
): PresentationEntry {
  if (state && map[state]) return map[state];
  return { class: 'unknown', label: state ? `UNKNOWN (${state})` : fallback };
}

function productState(req: CandidateProductRequirements): string {
  if (req.satisfied === true) return 'PASS';
  if (req.satisfied === false) return 'FAIL';
  return 'UNBOUND';
}

function paretoState(c: Candidate): string {
  if (c.pareto_member) return 'MEMBER';
  if (c.pareto_eligible) return 'ELIGIBLE';
  return 'INELIGIBLE';
}

interface Rollup {
  cls: string;
  text: string;
  title: string;
}

/** Table rollup of the tri-state verdicts (display only; the detail pane
 * shows each metric's authoritative verdict). */
function constraintRollup(verdicts: Record<string, ConstraintVerdict>): Rollup {
  const rows = Object.entries(verdicts);
  if (rows.length === 0) {
    return { cls: 'muted', text: 'none declared', title: 'This study declares no hard constraints.' };
  }
  const count = (v: ConstraintVerdict): number => rows.filter(([, x]) => x === v).length;
  const satisfied = count('SATISFIED');
  const violated = count('VIOLATED');
  const unmeasurable = count('UNMEASURABLE');
  const cls = violated > 0 ? 'bad' : unmeasurable > 0 ? 'warn' : 'ok';
  return {
    cls,
    text: `${satisfied}✓ ${violated}✗ ${unmeasurable}?`,
    title: rows.map(([m, v]) => `${m}: ${v}`).join('\n'),
  };
}

function objectiveCell(
  c: Candidate,
  metric: string,
): ReactElement {
  const availability: ObjectiveAvailability | undefined = c.objective_availability[metric];
  const value = c.objective_values[metric];
  if (availability === 'MEASURED' && typeof value === 'number') {
    return <span className="num">{fmtNum(value)}</span>;
  }
  if (availability === 'MEASURED') {
    return <span className="obj-state warn">MEASURED (NO VALUE)</span>;
  }
  const e = entry(presentation.objectiveState, availability, 'NO STATE');
  return (
    <span className={`obj-state ${e.class}`} title={`objective availability: ${availability ?? 'absent'}`}>
      {e.label}
    </span>
  );
}

function paretoPlot(
  candidates: Candidate[],
  objectives: StudyObjective[],
  selectedId: string | null,
  onSelect: (id: string) => void,
): ReactElement {
  const W = 340;
  const H = 230;
  const PAD = 40;
  const [ox, oy] = objectives.map((o) => o.metric);
  // Only candidates whose BOTH objectives are explicitly measured are
  // plotted; unmeasured objectives are never coerced to 0.
  const plottable = candidates.filter(
    (c) =>
      c.objective_availability[ox] === 'MEASURED' &&
      c.objective_availability[oy] === 'MEASURED' &&
      typeof c.objective_values[ox] === 'number' &&
      typeof c.objective_values[oy] === 'number',
  );
  const excluded = candidates.filter((c) => !plottable.includes(c));
  if (plottable.length < 2) {
    return (
      <p className="muted">
        Fewer than two candidates carry measured values for both objectives —
        no frontier is drawn. Never coerced from unmeasured objectives.
      </p>
    );
  }
  const xs = plottable.map((c) => c.objective_values[ox]);
  const ys = plottable.map((c) => c.objective_values[oy]);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const sx = (v: number): number =>
    PAD + ((v - x0) / Math.max(1e-9, x1 - x0)) * (W - PAD * 2);
  const sy = (v: number): number =>
    H - PAD - ((v - y0) / Math.max(1e-9, y1 - y0)) * (H - PAD * 2);

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="pareto" role="img" aria-label="Pareto frontier">
        <line x1={PAD} y1={H - PAD} x2={W - 8} y2={H - PAD} className="ax" />
        <line x1={PAD} y1={H - PAD} x2={PAD} y2={8} className="ax" />
        <text x={W - 8} y={H - PAD + 16} textAnchor="end" className="ax-label">
          {humanize(ox)} {objectives[0].direction}
        </text>
        <text x={10} y={14} className="ax-label">
          {humanize(oy)} {objectives[1].direction}
        </text>
        {plottable.map((c) => {
          const cx = sx(c.objective_values[ox]);
          const cy = sy(c.objective_values[oy]);
          const sel = c.candidate_id === selectedId;
          const cls = c.pareto_member
            ? 'pt-pareto'
            : c.pareto_eligible
              ? 'pt-eligible'
              : 'pt-ineligible';
          return (
            <g key={c.candidate_id} onClick={() => onSelect(c.candidate_id)} className="pt">
              {sel && <circle cx={cx} cy={cy} r={11} className="pt-ring" />}
              <circle cx={cx} cy={cy} r={6} className={cls}>
                <title>
                  {c.candidate_id}: {humanize(ox)}={fmtNum(c.objective_values[ox])},{' '}
                  {humanize(oy)}={fmtNum(c.objective_values[oy])}
                  {c.pareto_member ? ' (Pareto member)' : c.pareto_eligible ? ' (eligible)' : ' (ineligible)'}
                </title>
              </circle>
              <text x={cx} y={cy - 10} textAnchor="middle" className="pt-label">
                {c.candidate_id}
              </text>
            </g>
          );
        })}
      </svg>
      {excluded.length > 0 && (
        <p className="muted">
          Not plotted (objective UNMEASURABLE):{' '}
          {excluded.map((c) => c.candidate_id).join(', ')}.
        </p>
      )}
    </div>
  );
}

function VerdictChip({ map, state }: { map: PresentationMap; state: string | null | undefined }): ReactElement {
  const e = entry(map, state);
  return <span className={`verdict-chip ${e.class}`}>{e.label}</span>;
}

/** One certified objective: rank the measured candidates instead of
 * pretending a frontier exists. Nothing is drawn from an unmeasured
 * objective — those candidates are listed as excluded. */
function objectiveRanking(
  candidates: Candidate[],
  objective: StudyObjective,
  selectedId: string | null,
  onSelect: (id: string) => void,
): ReactElement {
  const metric = objective.metric;
  const measured = candidates
    .filter(
      (c) =>
        c.objective_availability[metric] === 'MEASURED' &&
        typeof c.objective_values[metric] === 'number',
    )
    .map((c) => ({ c, value: c.objective_values[metric] as number }));
  const excluded = candidates.filter(
    (c) => !measured.some((m) => m.c.candidate_id === c.candidate_id),
  );
  if (measured.length === 0) {
    return (
      <p className="muted">
        No candidate carries a measured value for {humanize(metric)}, so
        nothing is ranked. Unmeasured objectives are never coerced to a
        number.
      </p>
    );
  }
  const sorted = [...measured].sort((a, b) =>
    objective.direction === 'MIN' ? a.value - b.value : b.value - a.value,
  );
  const max = Math.max(...measured.map((m) => m.value)) || 1;
  const short = (id: string): string => id.replace(/^cand_/, '').slice(0, 10);
  return (
    <div className="rank-chart" role="list">
      <p className="muted">
        Single certified objective — a ranking of measured values, not a
        Pareto frontier. Best {humanize(metric)} first; the engine selects
        under its declared policy.
      </p>
      {sorted.map(({ c, value }, index) => (
        <button
          key={c.candidate_id}
          role="listitem"
          type="button"
          className={`rank-row${c.candidate_id === selectedId ? ' sel' : ''}${c.pareto_member ? ' pt' : ''}`}
          onClick={() => onSelect(c.candidate_id)}
          title={`${c.candidate_id} · ${humanize(metric)} = ${fmtNum(value)}${c.pareto_member ? ' · Pareto member' : ''}`}
        >
          <span className="rank-pos">{index + 1}</span>
          <code className="rank-id">{short(c.candidate_id)}</code>
          <span
            className="rank-bar"
            style={{ width: `${Math.max(2, (value / max) * 100)}%` }}
          />
          <span className="rank-val num">{fmtNum(value)}</span>
        </button>
      ))}
      {excluded.length > 0 && (
        <p className="muted">
          Not ranked (no measured value):{' '}
          {excluded.map((c) => c.candidate_id).join(', ')}.
        </p>
      )}
    </div>
  );
}

/** Optimization study: the engine's three authorities, rendered apart. */
export default function OptimizeView({
  optimization,
  design,
}: {
  optimization: OptimizationStudyView | null;
  design: DesignView | null;
}): ReactElement {
  const initial = optimization?.selected_candidate_id ?? optimization?.candidates[0]?.candidate_id ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(initial);

  const selected: Candidate | null = useMemo(
    () =>
      optimization?.candidates.find((c) => c.candidate_id === (selectedId ?? initial)) ??
      null,
    [optimization, selectedId, initial],
  );

  if (!optimization) {
    return (
      <Empty
        title="No optimization study"
        body={
          'Launch a study from the Optimize page to see candidates, '
          + 'constraint verdicts and the measured ranking of the domain.'
        }
      />
    );
  }

  const def = optimization.definition;
  const objectives = def.objectives;
  const constraints = def.constraints;
  const baseGuided = design?.noc_guided as Record<string, number | string | boolean | null> | undefined;
  const certified = optimization.result_class === 'CERTIFIED_PRODUCT';

  return (
    <div>
      <div className="card">
        <h3>
          Study definition · <code>{def.method}</code> ·{' '}
          <code>{def.selection}</code>
        </h3>
        <div className="kv">
          <span>result class</span>
          <span
            className={`result-class ${certified ? 'result-certified' : 'result-analytic'}`}
            title={
              certified
                ? 'Produced by Optimizer.optimize_certified — the only certified entry point.'
                : 'Analytic/research result (optimize_with_port) — can never contain certified Pareto.'
            }
          >
            {optimization.result_class}
          </span>
        </div>
        <div className="kv">
          <span>metric registry</span>
          <span>
            {optimization.metric_registry_id ? (
              <>
                <Hash value={optimization.metric_registry_id} /> ·{' '}
                <code>{optimization.metric_registry_version}</code>
              </>
            ) : (
              <em>none — analytic results bind no certified registry</em>
            )}
          </span>
        </div>
        <div className="kv">
          <span>optimization result</span>
          <Hash value={optimization.optimization_result_id} />
        </div>
        <div className="kv">
          <span>definition</span>
          <Hash value={def.definition_id} />
        </div>
        <div className="kv">
          <span>objectives</span>
          <span>
            {objectives
              .map((o: StudyObjective) => `${o.metric} (${o.direction})`)
              .join(' · ') || '—'}
          </span>
        </div>
        <div className="kv">
          <span>constraints</span>
          <span>
            {constraints
              .map((c: StudyConstraint) => `${c.metric} ${c.op} ${c.threshold}`)
              .join(' · ') || '— (none declared)'}
          </span>
        </div>
        <div className="kv">
          <span>budget / seed</span>
          <span>
            {JSON.stringify(def.budget ?? {})} · seed {String(def.seed ?? '—')}
          </span>
        </div>
        <div className="kv">
          <span>search domain (GUIDED only)</span>
          <span>
            <code>{JSON.stringify(def.domain ?? {})}</code>
          </span>
        </div>
        <div className="kv">
          <span>base design</span>
          <Hash value={optimization.base_design_hash} />
        </div>
      </div>

      <div className="opt-grid">
        <div className="card">
          <h3>Candidates ({optimization.candidates.length})</h3>
          <table className="tbl">
            <thead>
              <tr>
                <th>Candidate</th>
                {objectives.map((o) => (
                  <th key={o.metric}>
                    {humanize(o.metric)} ({o.direction})
                  </th>
                ))}
                <th>Compilation</th>
                <th>Evaluation</th>
                <th>Requirements</th>
                <th>Constraints</th>
                <th>Pareto</th>
              </tr>
            </thead>
            <tbody>
              {optimization.candidates.map((c) => {
                const rollup = constraintRollup(c.constraint_verdicts);
                const pe = entry(presentation.pareto, paretoState(c));
                return (
                  <tr
                    key={c.candidate_id}
                    className={c.candidate_id === selected?.candidate_id ? 'sel' : ''}
                    onClick={() => setSelectedId(c.candidate_id)}
                  >
                    <td>
                      <code>{c.candidate_id}</code>
                      {c.candidate_id === optimization.selected_candidate_id && (
                        <span className="selected-tag">selected</span>
                      )}
                    </td>
                    {objectives.map((o) => (
                      <td key={o.metric}>{objectiveCell(c, o.metric)}</td>
                    ))}
                    <td>
                      <VerdictChip map={presentation.compilationStatus} state={c.compilation_status} />
                    </td>
                    <td>
                      <VerdictChip map={presentation.evaluationStatus} state={c.evaluation_status} />
                    </td>
                    <td>
                      <VerdictChip map={presentation.productRequirements} state={productState(c.product_requirements)} />
                    </td>
                    <td>
                      <span className={`verdict-chip ${rollup.cls}`} title={rollup.title}>
                        {rollup.text}
                      </span>
                    </td>
                    <td>
                      <span className={`pareto-tag ${pe.class}`} title={c.eligibility_reason ?? 'Pareto-eligible'}>
                        {pe.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <h4>
            {objectives.length >= 2
              ? 'Pareto frontier'
              : objectives.length === 1
                ? 'Measured ranking'
                : 'Objectives'}
          </h4>
          {objectives.length >= 2 ? (
            paretoPlot(optimization.candidates, objectives, selected?.candidate_id ?? null, setSelectedId)
          ) : objectives.length === 1 ? (
            objectiveRanking(optimization.candidates, objectives[0], selected?.candidate_id ?? null, setSelectedId)
          ) : (
            <p className="muted">This study declares no objective.</p>
          )}
          <p className="muted">
            Pareto set (engine): {optimization.pareto_ids.join(', ') || '—'}
          </p>
        </div>

        <div className="card">
          <h3>Candidate comparison</h3>
          {!selected && <p className="muted">Select a candidate.</p>}
          {selected && (
            <div>
              <div className="kv">
                <span>candidate</span>
                <code>{selected.candidate_id}</code>
              </div>
              <div className="badge-row">
                <span className="badge-label">compilation</span>
                <VerdictChip map={presentation.compilationStatus} state={selected.compilation_status} />
                <span className="badge-label">evaluation</span>
                <VerdictChip map={presentation.evaluationStatus} state={selected.evaluation_status} />
                <span className="badge-label">requirements</span>
                <VerdictChip map={presentation.productRequirements} state={productState(selected.product_requirements)} />
                <span className="badge-label">eligibility</span>
                <VerdictChip map={presentation.eligibility} state={selected.pareto_eligible ? 'ELIGIBLE' : 'INELIGIBLE'} />
                <span className="badge-label">pareto</span>
                <VerdictChip map={presentation.pareto} state={paretoState(selected)} />
              </div>
              <div className="kv">
                <span>evaluation authority</span>
                <code>{selected.evaluation_authority ?? '—'}</code>
              </div>

              {selected.evaluation_reason && (
                <div className="reason-block">
                  <strong>Evaluation reason:</strong> {selected.evaluation_reason}
                </div>
              )}
              {selected.eligibility_reason && (
                <div className="reason-block reason-ineligible">
                  <strong>Optimization-ineligible:</strong> {selected.eligibility_reason}
                </div>
              )}

              <h4>GUIDED decisions (patch vs base)</h4>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Knob</th>
                    <th>Base</th>
                    <th>Candidate</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(selected.guided_patch).map(([k, v]) => (
                    <tr key={k}>
                      <td>
                        <code>{k}</code>
                      </td>
                      <td className="num">{fmtNum(baseGuided?.[k] ?? null)}</td>
                      <td className="num changed">{fmtNum(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h4>Measured objectives (availability is explicit)</h4>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Objective</th>
                    <th>Value</th>
                    <th>Availability</th>
                  </tr>
                </thead>
                <tbody>
                  {objectives.map((o) => (
                    <tr key={o.metric}>
                      <td>
                        {humanize(o.metric)} ({o.direction})
                      </td>
                      <td>{objectiveCell(selected, o.metric)}</td>
                      <td>
                        <VerdictChip
                          map={presentation.objectiveState}
                          state={selected.objective_availability[o.metric]}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <h4>Optimization constraints (three-state, never boolean)</h4>
              {constraints.length === 0 ? (
                <p className="muted">
                  This study declares no hard constraints; no verdict is invented.
                </p>
              ) : (
                <table className="tbl">
                  <tbody>
                    {constraints.map((c) => (
                      <tr key={c.metric}>
                        <td>
                          <code>
                            {c.metric} {c.op} {c.threshold}
                          </code>
                        </td>
                        <td>
                          <VerdictChip
                            map={presentation.constraintVerdict}
                            state={selected.constraint_verdicts[c.metric]}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h4>Product requirements (the RequirementReport authority)</h4>
              {selected.product_requirements.satisfied === null ? (
                <p className="muted">
                  No RequirementReport is bound to this candidate —
                  unmeasurable, never a pass.
                </p>
              ) : (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Class</th>
                      <th>Verdict</th>
                      <th>Required</th>
                      <th>Measured</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.product_requirements.verdicts.map((v) => (
                      <tr key={v.requirement_index} title={v.reason}>
                        <td>{v.requirement_index}</td>
                        <td>
                          <code>{v.traffic_class ?? v.qos_class ?? '—'}</code>
                        </td>
                        <td>
                          <StatusBadge status={v.verdict} />
                        </td>
                        <td className="num">{fmtNum(v.required)}</td>
                        <td className="num">{fmtNum(v.measured)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h4>Evaluation provenance</h4>
              <div className="kv">
                <span>performance result</span>
                <code>{selected.evaluation_ids.performance_result_id ?? '—'}</code>
              </div>
              <div className="kv">
                <span>requirement report</span>
                <code>{selected.evaluation_ids.requirement_report_id ?? '—'}</code>
              </div>

              <h4>LOCKED consequences (recompiled, never searched)</h4>
              <pre className="evidence">
                {JSON.stringify(selected.locked_consequences ?? {}, null, 2)}
              </pre>

              {selected.pareto_member &&
                optimization.selected_candidate_id === selected.candidate_id &&
                optimization.selection_rationale && (
                  <div className="rationale">
                    <strong>Selection rationale:</strong> {optimization.selection_rationale}
                  </div>
                )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
