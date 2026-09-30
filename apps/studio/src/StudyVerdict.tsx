import type { ReactElement } from 'react';
import type { Candidate, OptimizationStudyView } from './types';
import { fmtNum } from './components/badges';
import { candidateLabel } from './labels';

export default function StudyVerdict({
  study,
  baseGuided,
  multiObjective = true,
}: {
  study: OptimizationStudyView;
  baseGuided: Record<string, unknown> | null;
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
  const tied = ranked.length > 1
    && ranked.every((r) => r.v === ranked[0].v);
  const widthGroups = widthReturns(study, ranked, baseGuided);
  const completeness = studyCompleteness(study);

  return (
    <section className="card verdict">
      <p className="verdict-kicker">Highest measured value (not a winner)</p>
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
      {tied && (
        <p className="warn" role="note">
          NO DISTINCTION UNDER THIS OBJECTIVE — every measured candidate
          reads the same value. Nothing here is superior; the engine
          selection is arbitrary among ties.
        </p>
      )}
      {best && !tied && (
        <p className="muted">
          Recommended for further investigation. A faster
          network is not a better chip (see limits below).
        </p>
      )}
      {widthGroups && (
        <div>
          <span className="verdict-label">Observed returns by link width</span>
          <table className="tbl">
            <thead><tr><th>width</th><th>best measured</th><th>n</th><th>Δ vs previous</th></tr></thead>
            <tbody>
              {widthGroups.map((g, i) => {
                const prevBest = i > 0 ? widthGroups[i - 1].best : null;
                const d = prevBest !== null ? g.best - prevBest : null;
                const p = d !== null && prevBest !== null && prevBest !== 0
                  ? (d / prevBest) * 100
                  : null;
                return (
                  <tr key={g.width}>
                    <td className="num">{g.width}b</td>
                    <td className="num">{fmtNum(g.best)} {unit(metric)}</td>
                    <td className="num">{g.n}</td>
                    <td className="num">
                      {d === null ? '—' : `${d > 0 ? '+' : ''}${fmtNum(d)}${p === null ? '' : ` (${p > 0 ? '+' : ''}${p.toFixed(1)}%)`}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <span className="muted">Measured returns within this study only — diminishing or not, they establish nothing beyond this objective.</span>
        </div>
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
                + (pct === null ? '' : ` (${pct > 0 ? '+' : ''}${Math.abs(pct) < 0.05 && pct !== 0 ? '<0.1' : pct.toFixed(1)}%)`)}
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
        {best?.c.verdict != null && (
          <div>
            <span className="verdict-label">Engine verdict</span>
            <strong>{best.c.verdict}</strong>
            <span className="muted">
              {best.c.differs ? `differs: ${best.c.differs}` : 'comparable'}
              {best.c.delta_b_minus_a != null
                ? ` · Δ(b−a) ${fmtNum(best.c.delta_b_minus_a)}` : ''}
            </span>
          </div>
        )}
        {(best?.c.evaluation_support != null
          || best?.c.evaluation_readiness != null) && (
          <div>
            <span className="verdict-label">Capability truth</span>
            <strong>
              {[best?.c.evaluation_support, best?.c.evaluation_readiness]
                .filter((v) => v != null).join(' · ') || '—'}
            </strong>
            <span className="muted">server support × readiness</span>
          </div>
        )}
      </div>

      {study.definition.objectives.length > 1 && (
        <p className="muted">
          {study.definition.objectives.length} objectives declared — see the
          candidate table below for the{multiObjective ? ' frontier' : ' ranking'}.
        </p>
      )}

      <p className="muted">
        <strong>Search completeness.</strong> {completeness}
      </p>
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

function widthReturns(
  study: OptimizationStudyView,
  ranked: { c: Candidate; v: number }[],
  baseGuided: Record<string, unknown> | null,
): { width: string; best: number; n: number }[] | null {
  const domain = study.definition.domain as Record<string, unknown[]> | undefined;
  const widths = domain?.link_width;
  if (!Array.isArray(widths) || widths.length < 2) return null;
  const byWidth = new Map<string, number[]>();
  for (const { c, v } of ranked) {
    const w = c.guided_patch?.link_width ?? baseGuided?.link_width ?? null;
    if (w === null || w === undefined) return null;
    const key = String(w);
    const arr = byWidth.get(key) ?? [];
    arr.push(v);
    byWidth.set(key, arr);
  }
  if (byWidth.size < 2) return null;
  return [...byWidth.entries()]
    .map(([width, vs]) => ({
      width,
      best: Math.min(...vs),
      n: vs.length,
    }))
    .sort((a, b) => Number(a.width) - Number(b.width));
}

function studyCompleteness(study: OptimizationStudyView): string {
  const budget = study.definition.budget as Record<string, unknown> | undefined;
  const capped = budget
    && (typeof budget.max_candidates === 'number' || typeof budget.max_evaluations === 'number');
  if ((study.definition.method === 'grid' || study.definition.method === 'enumeration') && !capped) {
    return `EXHAUSTIVE — all ${study.candidates.length} declared candidates evaluated over this finite domain.`;
  }
  if (study.definition.method === 'random') {
    return `BUDGETED (seeded random, seed ${String(study.definition.seed ?? '—')}) — best observed among ${study.candidates.length} evaluated candidates; no global optimality claim.`;
  }
  return `BUDGETED — best observed among ${study.candidates.length} evaluated candidates; no global optimality claim.`;
}

function unit(metric: string): string {
  if (metric.endsWith('_ns')) return 'ns';
  if (metric.endsWith('_cycles') || metric === 'makespan'
      || metric === 'critical_path') return 'cycles';
  return '—';
}
