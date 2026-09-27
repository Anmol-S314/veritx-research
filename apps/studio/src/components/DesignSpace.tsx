import type { ReactElement } from 'react';
import type { OptimizationCapabilities } from '../api/types';

/** The design-space editor.
 *
 *  EVERY control here is justified by the capability response. A parameter or
 *  a value the backend does not mark qualified is never offered as something
 *  to search — that is the whole point of deriving capabilities from
 *  authority rather than keeping a list in the frontend.
 *
 *  Two honesty rules the UI must not break:
 *
 *  1. A validated NUMERIC RANGE is not an exhaustive backend enumeration. The
 *     chips below are UI choices on such a range, and the range constraint is
 *     shown next to them.
 *  2. `topology_family` IS exhaustively enumerable, so its choices come
 *     straight from the capability response — specifically from
 *     `executable_values` (the FULL certified chain), never from
 *     `accepted_values` (compile-accepted but possibly refused by the
 *     certified profile).
 */
export interface DesignSpaceProps {
  caps: OptimizationCapabilities;
  base: Record<string, unknown> | null;
  widths: number[];
  setWidths: (v: number[]) => void;
  topologies: string[];
  setTopologies: (v: string[]) => void;
  concentrations: number[];
  setConcentrations: (v: number[]) => void;
  radixText: string;
  setRadixText: (v: string) => void;
  method: string;
  setMethod: (v: string) => void;
  seed: number;
  setSeed: (v: number) => void;
  maxCandidates: number;
  setMaxCandidates: (v: number) => void;
  candidateCount: number;
}

/** UI choices for the numeric ranges. NOT backend enumerations. */
const RANGE_CHOICES: Record<string, number[]> = {
  link_width: [32, 64, 128],
  concentration: [1, 2, 4],
};

const HUMAN: Record<string, string> = {
  link_width: 'Link width',
  topology_family: 'Topology',
  concentration: 'Concentration',
  radix: 'Radix',
};

function toggle<T>(list: T[], value: T, on: boolean): T[] {
  const next = on ? [...list, value] : list.filter((x) => x !== value);
  return Array.from(new Set(next));
}

function Chips({ values, selected, onToggle, suffix }: {
  values: (string | number)[];
  selected: (string | number)[];
  onToggle: (v: string | number, on: boolean) => void;
  suffix?: string;
}): ReactElement {
  return (
    <span className="check-row">
      {values.map((v) => (
        <label className="check" key={String(v)}>
          <input
            type="checkbox"
            checked={selected.includes(v)}
            onChange={(e) => onToggle(v, e.target.checked)}
          />
          {String(v)}{suffix ?? ''}
        </label>
      ))}
    </span>
  );
}

export default function DesignSpace(p: DesignSpaceProps): ReactElement {
  const { caps, base } = p;
  const byName = Object.fromEntries(
    caps.guided_parameters.map((g) => [g.name, g]));
  const qualified = new Set(caps.qualified_parameters);
  const unqualified = caps.unqualified_parameters ?? [];
  const topoParam = byName.topology_family;
  // executable_values = what the FULL certified chain runs. accepted_values
  // may be wider (e.g. concentrated_mesh compiles but the certified profile
  // refuses it) — offering those as search choices would manufacture
  // candidates that deterministically fail at evaluation.
  const topoChoices = (topoParam?.executable_values
    ?? topoParam?.accepted_values ?? []).map(String);

  const current = (name: string): string => {
    const v = base?.[name];
    return v === undefined || v === null ? '—' : String(v);
  };

  const group = (
    name: string,
    children: ReactElement,
    extra?: string,
  ): ReactElement | null => {
    if (!qualified.has(name)) return null;
    const g = byName[name];
    return (
      <div className="form-row" key={name}>
        <label>
          {HUMAN[name] ?? name}
          <span className="muted"> — current: {current(name)}</span>
          {children}
          <small className="muted">
            {g?.accepted_values_is_exhaustive
              ? 'Backend-enumerated values.'
              : 'UI choices on a validated range — the backend does not '
                + 'enumerate this domain.'}
            {extra ? ` ${extra}` : ''}
          </small>
        </label>
      </div>
    );
  };

  return (
    <>
      <h4>Explore design space</h4>
      <p className="muted">
        {qualified.size} qualified dimension(s):{' '}
        {caps.qualified_parameters.join(', ') || 'none'}. Only these can enter a
        certified study.
      </p>

      {group('link_width',
        <Chips values={RANGE_CHOICES.link_width} selected={p.widths}
               suffix="b"
               onToggle={(v, on) =>
                 p.setWidths(toggle(p.widths, Number(v), on))} />)}

      {group('topology_family',
        <Chips values={topoChoices} selected={p.topologies}
               onToggle={(v, on) =>
                 p.setTopologies(toggle(p.topologies, String(v), on))} />,
        'These are the families the certified execution chain accepts ' +
        'end to end — not merely the ones that compile.')}

      {group('concentration',
        <Chips values={RANGE_CHOICES.concentration} selected={p.concentrations}
               onToggle={(v, on) =>
                 p.setConcentrations(toggle(p.concentrations, Number(v), on))} />)}

      {qualified.has('radix') && (
        <div className="form-row">
          <label>
            Radix
            <span className="muted"> — current: {current('radix')}</span>
            <input
              type="text"
              value={p.radixText}
              placeholder="e.g. 4, 5"
              onChange={(e) => p.setRadixText(e.target.value)}
            />
            <small className="muted">
              Comma-separated integers. Must seat every attached endpoint
              (k·k·concentration ≥ endpoints); an invalid choice is refused by
              the compiler rather than silently reshaped.
            </small>
          </label>
        </div>
      )}

      <h4>Search configuration</h4>
      <div className="form-row">
        <label>
          Method
          <select value={p.method}
                  onChange={(e) => p.setMethod(e.target.value)}>
            {caps.search_methods.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <small className="muted">
            {p.method === 'random'
              ? 'A seeded subsample of the canonical search space. The same '
                + 'seed and definition produce the same candidates.'
              : 'Exhaustive over the declared domain, in canonical order.'}
          </small>
        </label>
        {p.method === 'random' && (
          <label>
            Seed
            <input type="number" value={p.seed}
                   onChange={(e) => p.setSeed(Number(e.target.value) || 0)} />
            <small className="muted">
              Required: without it the study would not be reproducible.
            </small>
          </label>
        )}
        <label>
          Candidate budget
          <input type="number" min={0} value={p.maxCandidates || ''}
                 placeholder="exhaustive"
                 onChange={(e) =>
                   p.setMaxCandidates(Number(e.target.value) || 0)} />
          <small className="muted">
            {p.maxCandidates > 0
              ? `Truncates the study to the first ${p.maxCandidates} canonical `
                + 'candidates.'
              : 'Empty means exhaustive — no cap.'}
          </small>
        </label>
      </div>

      <div className="form-row">
        <strong>
          {p.candidateCount > 0
            ? `${p.candidateCount} candidate design`
              + `${p.candidateCount === 1 ? '' : 's'}`
            : 'No candidate designs selected'}
        </strong>
        <span className="muted">
          {p.candidateCount > 0 && (
            <> = {[...qualified].map((n) => {
              const count = n === 'link_width' ? p.widths.length
                : n === 'topology_family' ? p.topologies.length
                  : n === 'concentration' ? p.concentrations.length
                    : undefined;
              return count ? `${count} ${n}` : null;
            }).filter(Boolean).join(' × ')}</>
          )}
        </span>
        {p.candidateCount > 24 && (
          <span className="muted">
            Large search — consider a candidate budget.
          </span>
        )}
      </div>

      {unqualified.length > 0 && (
        <details className="card-details">
          <summary>Unavailable / not yet qualified ({unqualified.length})</summary>
          <table className="live-table">
            <thead>
              <tr><th>parameter</th><th>state</th><th>reason</th></tr>
            </thead>
            <tbody>
              {unqualified.map((n) => {
                const g = byName[n];
                return (
                  <tr key={n}>
                    <td>{HUMAN[n] ?? n}</td>
                    <td>
                      {g && !g.compilable
                        ? 'does not compile'
                        : g && !g.backend_executable
                          ? 'certified profile refuses it'
                          : 'no measured effect'}
                    </td>
                    <td className="muted">{g?.reason ?? '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted">{caps.multicast_note}</p>
        </details>
      )}

      <h4>Objective</h4>
      <p>
        <strong>Minimize completion time</strong>
      </p>
      <p className="muted">{caps.objective_note}</p>
      <p className="muted">
        VERITX certifies network completion performance for optimization.
        Only measured network completion was evaluated: this result does not
        establish an area, power, energy or implementation-cost advantage.
      </p>
    </>
  );
}
