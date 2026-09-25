import { useMemo, useState, type ReactElement } from 'react';
import type {
  Candidate,
  OptimizationStudyView,
  StudyDefinition,
} from '../types';
import { Hash, humanize } from './badges';

/**
 * Optimization analysis (Stage-2 surface 3): design-space coverage,
 * outcome distribution and candidate lineage. Every cell is derived from
 * fields the optimizer already emits in OptimizationStudyView v2 —
 * `definition.domain`, `guided_patch`, statuses, availability and
 * identity fields. Nothing is recomputed or inferred: the Pareto set,
 * selection and verdicts remain the backend's, shown here only from the
 * candidate's own records. No sensitivity analysis: the optimizer emits
 * no canonical sensitivity authority, so none is drawn.
 */

interface KnobColumn {
  name: string;
  values: (number | string | boolean)[];
}

/** The search domain, restricted to knobs at least one candidate actually
 * patched. A declared dimension with no candidate record is still shown,
 * marked as unexplored — absence is stated, never hidden. */
function domainColumns(
  def: StudyDefinition,
): KnobColumn[] {
  const declared = (def.domain ?? {}) as Record<string, unknown[]>;
  return Object.entries(declared).map(([name, values]) => ({
    name,
    values: values as (number | string | boolean)[],
  }));
}

function outcomeOf(c: Candidate): {
  key: string;
  label: string;
  cls: string;
} {
  if (c.compilation_status !== 'COMPILED') {
    return { key: 'compile-refused', label: 'compile refused', cls: 'bad' };
  }
  if (c.evaluation_status !== 'EVALUATED') {
    return { key: 'eval-failed', label: 'evaluation failed', cls: 'bad' };
  }
  if (!c.pareto_eligible) {
    return { key: 'ineligible', label: 'evaluated · ineligible', cls: 'warn' };
  }
  if (c.pareto_member) {
    return { key: 'pareto', label: 'Pareto member', cls: 'good' };
  }
  return { key: 'eligible', label: 'evaluated · eligible', cls: 'muted' };
}

export default function OptimizationAnalysis({
  optimization,
}: {
  optimization: OptimizationStudyView;
}): ReactElement {
  const { candidates, definition: def } = optimization;
  const [openKnob, setOpenKnob] = useState<string | null>(null);

  const knobs = useMemo(
    () => domainColumns(def),
    [def],
  );

  // Coverage matrix rows: one per declared domain point, with the
  // candidates whose patch assigns that value. Grid methods enumerate
  // every point; a point with no candidate means the budget or eligibility
  // cut it — shown, never papered over.
  const selectedKnob = knobs.find((k) => k.name === openKnob) ?? null;

  const outcomeCounts = useMemo(() => {
    const counts = new Map<string, { label: string; cls: string; n: number }>();
    for (const c of candidates) {
      const o = outcomeOf(c);
      const cur = counts.get(o.key);
      if (cur) cur.n += 1;
      else counts.set(o.key, { label: o.label, cls: o.cls, n: 1 });
    }
    return [...counts.entries()];
  }, [candidates]);

  const measured = candidates.filter(
    (c) =>
      c.evaluation_status === 'EVALUATED' &&
      Object.values(c.objective_availability).some((a) => a === 'MEASURED'),
  ).length;

  return (
    <div className="page">
      <section className="card">
        <h3>Study analysis</h3>
        <div className="kv">
          <span>study identity</span>
          <Hash value={optimization.optimization_result_id} label="result" />
        </div>
        <div className="kv">
          <span>definition identity</span>
          <Hash value={def.definition_id} label="definition" />
        </div>
        <div className="kv">
          <span>base design</span>
          <Hash value={optimization.base_design_hash} />
        </div>
        <div className="kv">
          <span>method / selection</span>
          <span>
            {def.method} · {def.selection}
          </span>
        </div>
        <div className="kv">
          <span>seed</span>
          <span>{String(def.seed ?? '—')}</span>
        </div>
        <div className="kv">
          <span>metric registry</span>
          <Hash value={optimization.metric_registry_id ?? undefined} />
        </div>
      </section>

      <section className="card">
        <h3>Outcome distribution</h3>
        <p className="muted">
          {candidates.length} candidates declared · {measured} carry at least
          one measured objective. Failed and ineligible candidates stay
          counted here — they are part of the study record, never dropped.
        </p>
        <table className="tbl">
          <tbody>
            {outcomeCounts.map(([key, o]) => (
              <tr key={key}>
                <td className={o.cls}>{o.label}</td>
                <td className="num">{o.n}</td>
              </tr>
            ))}
            {outcomeCounts.length === 0 && (
              <tr>
                <td className="muted">no candidate records</td>
                <td className="num">0</td>
              </tr>
            )}
          </tbody>
        </table>
        <p className="muted">
          Pareto set and selection are the engine's decisions, listed above;
          this distribution only counts the recorded outcomes.
        </p>
      </section>

      <section className="card">
        <h3>Design-space coverage</h3>
        <p className="muted">
          Declared GUIDED domain vs the patches candidates actually carry.
          Click a knob to see which candidates took each value.
        </p>
        {knobs.length === 0 ? (
          <p className="muted">
            This study declares no search domain (the engine records none),
            so there is no design space to cover.
          </p>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>knob</th>
                <th>declared values</th>
                <th>covered</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {knobs.map((k) => {
                const covered = new Set(
                  candidates.map((c) => c.guided_patch[k.name]),
                );
                return (
                  <tr key={k.name}>
                    <td>
                      <code>{humanize(k.name)}</code>
                    </td>
                    <td className="muted">
                      {k.values.map((v) => String(v)).join(', ')}
                    </td>
                    <td className="num">
                      {covered.size} / {k.values.length}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn"
                        onClick={() =>
                          setOpenKnob(openKnob === k.name ? null : k.name)
                        }
                      >
                        {openKnob === k.name ? 'Hide' : 'Inspect'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {selectedKnob && (
          <table className="tbl">
            <thead>
              <tr>
                <th>value</th>
                <th>candidates</th>
                <th>outcomes</th>
              </tr>
            </thead>
            <tbody>
              {selectedKnob.values.map((v) => {
                const taken = candidates.filter(
                  (c) => c.guided_patch[selectedKnob.name] === v,
                );
                return (
                  <tr key={String(v)}>
                    <td className="num">{String(v)}</td>
                    <td className="muted">
                      {taken.map((c) => c.candidate_id).join(', ') || '—'}
                    </td>
                    <td className="muted">
                      {taken.map((c) => outcomeOf(c).label).join(', ') || 'not explored'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h3>Candidate lineage</h3>
        <table className="live-table">
          <thead>
            <tr>
              <th>candidate</th>
              <th>patch</th>
              <th>design identity</th>
              <th>performance result</th>
              <th>requirement report</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.candidate_id}>
                <td>
                  <code>{c.candidate_id}</code>
                </td>
                <td className="muted">
                  {Object.entries(c.guided_patch)
                    .map(([k, v]) => `${k}=${String(v)}`)
                    .join(', ') || '—'}
                </td>
                <td>
                  <Hash value={c.evaluation_ids.design_hash} />
                </td>
                <td>
                  <code>{c.evaluation_ids.performance_result_id ?? '—'}</code>
                </td>
                <td>
                  <code>{c.evaluation_ids.requirement_report_id ?? '—'}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">
          Each candidate's design identity ties its patch to an immutable
          compilation; performance and requirement ids are the canonical
          evidence records behind the numbers above.
        </p>
      </section>
    </div>
  );
}
