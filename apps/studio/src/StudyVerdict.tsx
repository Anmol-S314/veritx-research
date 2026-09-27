import type { ReactElement } from 'react';
import type { Candidate, OptimizationStudyView } from './types';
import { fmtNum } from './components/badges';
import { candidateLabel } from './labels';

/** The FIRST thing the result page says: what did VERITX learn?
 *
 *  The previous header led with `Study <optimization_id>`, a Pareto member
 *  count and a metric-registry hash. Those are provenance, not an answer, and
 *  a reader had to reconstruct the finding from a candidate table. This states
 *  the finding, the change from the current revision, and the LIMIT of what
 *  was measured — the last of which is as important as the result itself,
 *  because a faster network is not a better chip.
 *
 *  Every identity is preserved, one disclosure below, in Engineering details.
 */
export default function StudyVerdict({
  study,
  baseGuided,
  multiObjective = true,
}: {
  study: OptimizationStudyView;
  baseGuided: Record<string, unknown> | null;
  /** Same gate OptimizeView uses: a single semantic objective family is a
   *  RANKING, not a frontier — the wording must not promise a trade-off. */
  multiObjective?: boolean;
}): ReactElement {
  const objectives = study.definition.objectives ?? [];
  const objective = objectives[0];
  const metric = objective?.metric ?? 'completion_cycles';
  const dir = objective?.direction ?? 'MIN';

  const measured = (c: Candidate): number | null =>
    c.objective_availability?.[metric] === 'MEASURED'
      && typeof c.objective_values?.[metric] === 'number'
      ? c.objective_values[metric]
      : null;

  const base =
    study.candidates.find(
      (c) => Object.keys(c.guided_patch ?? {}).length === 0,
    ) ?? null;

  // "Best measured" is the best MEASURED value under the declared direction.
  // An unmeasurable candidate is never coerced to zero to compete here.
  const ranked = study.candidates
    .map((c) => ({ c, v: measured(c) }))
    .filter((r): r is { c: Candidate; v: number } => r.v !== null)
    .sort((a, b) => (dir === 'MIN' ? a.v - b.v : b.v - a.v));

  const best = ranked[0] ?? null;
  const baseValue = base ? measured(base) : null;
  const delta =
    best && baseValue !== null ? best.v - baseValue : null;
  const pct =
    delta !== null && baseValue !== null && baseValue !== 0
      ? (delta / baseValue) * 100
      : null;

  const counts = {
    planned: study.candidates.length,
    compiled: study.candidates.filter(
      (c) => c.compilation_status === 'COMPILED',
    ).length,
    evaluated: study.candidates.filter(
      (c) => c.evaluation_status === 'EVALUATED',
    ).length,
    measured: ranked.length,
    failed: study.candidates.filter(
      (c) =>
        c.compilation_status !== 'COMPILED'
        || c.evaluation_status === 'FAILED'
        || c.evaluation_status === 'COMPILE_FAILED',
    ).length,
    unmeasurable: study.candidates.filter(
      (c) => measured(c) === null,
    ).length,
  };

  const reqState = best?.c.product_requirements?.satisfied;
  const better = delta === null ? null : dir === 'MIN' ? delta < 0 : delta > 0;

  return (
    <section className="card verdict">
      <p className="verdict-kicker">Best measured design</p>
      {best ? (
        <h3 className="verdict-headline">
          {candidateLabel(best.c, baseGuided)}
        </h3>
      ) : (
        <h3 className="verdict-headline muted">
          No candidate produced a measured value
        </h3>
      )}
      {best && (
        <p className="verdict-value">
          {fmtNum(best.v)} <span className="muted">{unit(metric)}</span>
        </p>
      )}

      <div className="verdict-grid">
        <div>
          <span className="verdict-label">Current revision</span>
          <strong>
            {base ? candidateLabel(base, baseGuided) : '—'}
          </strong>
          <span className="muted">
            {baseValue !== null ? `${fmtNum(baseValue)} ${unit(metric)}` : 'not measured in this study'}
          </span>
        </div>
        <div>
          <span className="verdict-label">
            Measured {better === false ? 'change' : 'improvement'}
          </span>
          <strong className={better ? 'good' : better === false ? 'bad' : ''}>
            {delta === null
              ? '—'
              : `${delta > 0 ? '+' : ''}${fmtNum(delta)} ${unit(metric)}`
                + (pct === null ? '' : ` (${pct > 0 ? '+' : ''}${pct.toFixed(1)}%)`)}
          </strong>
          <span className="muted">
            {delta === null
              ? 'no comparable base measurement'
              : better
                ? dir === 'MIN'
                  ? 'faster completion'
                  : 'better under the declared direction'
                : 'not an improvement under the declared direction'}
          </span>
        </div>
        <div>
          <span className="verdict-label">Requirements</span>
          <strong>
            {reqState === true ? 'SATISFIED'
              : reqState === false ? 'VIOLATED' : 'UNBOUND'}
          </strong>
          <span className="muted">product requirement report</span>
        </div>
        <div>
          <span className="verdict-label">Study</span>
          <strong>
            {counts.measured} measured · {counts.planned} planned
          </strong>
          <span className="muted">
            {counts.compiled} compiled · {counts.failed} failed
            {counts.unmeasurable > 0
              ? ` · ${counts.unmeasurable} unmeasurable` : ''}
          </span>
        </div>
      </div>

      {study.definition.objectives.length > 1 && (
        <p className="muted">
          {study.definition.objectives.length} objectives declared — see the
          candidate table below for the{multiObjective ? ' frontier' : ' ranking'}.
        </p>
      )}

      <p className="verdict-limit">
        <strong>What this does not establish.</strong> Only network completion
        performance was measured. Area, power, energy and implementation cost
        were not evaluated, so this result does not show a better overall
        hardware design — only a faster fabric under this study&apos;s design
        space.
      </p>
      {counts.failed > 0 && (
        <p className="muted">
          {counts.failed} candidate{counts.failed === 1 ? '' : 's'} failed and
          remain part of the study record; they are listed below rather than
          dropped.
        </p>
      )}
    </section>
  );
}

function unit(metric: string): string {
  if (metric.endsWith('_ns')) return 'ns';
  if (metric.endsWith('_cycles') || metric === 'makespan'
      || metric === 'critical_path') return 'cycles';
  return '';
}
