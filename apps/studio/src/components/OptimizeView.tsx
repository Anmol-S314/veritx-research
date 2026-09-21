import { useMemo, useState, type ReactElement } from 'react';
import type { Candidate, DesignView, OptimizationStudyView } from '../types';
import { Empty, Hash, fmtNum, humanize } from './badges';

function paretoPlot(
  candidates: Candidate[],
  objectives: string[],
  selectedId: string | null,
  onSelect: (id: string) => void,
): ReactElement {
  const W = 340;
  const H = 230;
  const PAD = 40;
  const [ox, oy] = objectives;
  const xs = candidates.map((c) => c.objective_values[ox] ?? 0);
  const ys = candidates.map((c) => c.objective_values[oy] ?? 0);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const sx = (v: number): number =>
    PAD + ((v - x0) / Math.max(1e-9, x1 - x0)) * (W - PAD * 2);
  const sy = (v: number): number =>
    H - PAD - ((v - y0) / Math.max(1e-9, y1 - y0)) * (H - PAD * 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="pareto" role="img" aria-label="Pareto frontier">
      <line x1={PAD} y1={H - PAD} x2={W - 8} y2={H - PAD} className="ax" />
      <line x1={PAD} y1={H - PAD} x2={PAD} y2={8} className="ax" />
      <text x={W - 8} y={H - PAD + 16} textAnchor="end" className="ax-label">
        {humanize(ox)} ↓
      </text>
      <text x={10} y={14} className="ax-label">
        {humanize(oy)} ↓
      </text>
      {candidates.map((c) => {
        const cx = sx(c.objective_values[ox] ?? 0);
        const cy = sy(c.objective_values[oy] ?? 0);
        const sel = c.candidate_id === selectedId;
        return (
          <g key={c.candidate_id} onClick={() => onSelect(c.candidate_id)} className="pt">
            {sel && <circle cx={cx} cy={cy} r={11} className="pt-ring" />}
            <circle
              cx={cx}
              cy={cy}
              r={6}
              className={c.pareto_member ? 'pt-pareto' : 'pt-dom'}
            >
              <title>
                {c.candidate_id}: {humanize(ox)}={fmtNum(c.objective_values[ox])},{' '}
                {humanize(oy)}={fmtNum(c.objective_values[oy])}
                {c.pareto_member ? ' (Pareto)' : ''}
              </title>
            </circle>
            <text x={cx} y={cy - 10} textAnchor="middle" className="pt-label">
              {c.candidate_id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Optimization study: candidates, verdicts, Pareto frontier, comparison. */
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
        body="This fixture carries no OptimizationStudyView. Open the optimization-study fixture to explore candidates, constraint verdicts, and the Pareto frontier."
      />
    );
  }

  const def = optimization.definition;
  const objectives = def.objectives;
  const baseGuided = design?.noc_guided as Record<string, number | string | boolean | null> | undefined;

  return (
    <div>
      <div className="card">
        <h3>
          Study definition · <code>{def.method}</code>
        </h3>
        <div className="kv">
          <span>objectives</span>
          <span>{objectives.map(humanize).join(' · ')}</span>
        </div>
        <div className="kv">
          <span>constraints</span>
          <span>{(def.constraints ?? []).join(' · ') || '—'}</span>
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
                  <th key={o}>{humanize(o)}</th>
                ))}
                <th>Constraints</th>
                <th>Pareto</th>
              </tr>
            </thead>
            <tbody>
              {optimization.candidates.map((c) => {
                const verdicts = Object.entries(c.constraint_verdicts);
                const allOk = verdicts.every(([, v]) => v);
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
                      <td key={o} className="num">
                        {fmtNum(c.objective_values[o])}
                      </td>
                    ))}
                    <td>
                      <span className={`verdict-chip ${allOk ? 'ok' : 'bad'}`}>
                        {verdicts.filter(([, v]) => v).length}/{verdicts.length}
                      </span>
                    </td>
                    <td>{c.pareto_member ? '●' : '○'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <h4>Pareto frontier</h4>
          {objectives.length >= 2 ? (
            paretoPlot(optimization.candidates, objectives, selected?.candidate_id ?? null, setSelectedId)
          ) : (
            <p className="muted">Need ≥2 objectives for a frontier plot.</p>
          )}
          <p className="muted">Pareto set: {optimization.pareto_ids.join(', ') || '—'}</p>
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

              <h4>LOCKED consequences (recompiled, never searched)</h4>
              <pre className="evidence">
                {JSON.stringify(selected.locked_consequences ?? {}, null, 2)}
              </pre>

              <h4>Performance</h4>
              <table className="tbl">
                <tbody>
                  {Object.entries(selected.objective_values).map(([k, v]) => (
                    <tr key={k}>
                      <td>{humanize(k)}</td>
                      <td className="num">{fmtNum(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="kv">
                <span>performance result</span>
                <code>{selected.evaluation_ids.performance_result_id ?? '—'}</code>
              </div>

              <h4>Requirements (constraint verdicts)</h4>
              <table className="tbl">
                <tbody>
                  {Object.entries(selected.constraint_verdicts).map(([k, v]) => (
                    <tr key={k}>
                      <td>{humanize(k)}</td>
                      <td>
                        <span className={`verdict-chip ${v ? 'ok' : 'bad'}`}>
                          {v ? 'PASS' : 'FAIL'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {optimization.selected_candidate_id === selected.candidate_id &&
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
