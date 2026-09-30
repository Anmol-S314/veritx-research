import type { ReactElement } from 'react';
import type { OptimizationCapabilities } from '../api/types';

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
  extraSelections: Record<string, (string | number)[]>;
  setExtraSelection: (name: string, v: (string | number)[]) => void;
  extraTexts: Record<string, string>;
  setExtraText: (name: string, v: string) => void;
  method: string;
  setMethod: (v: string) => void;
  seed: number;
  setSeed: (v: number) => void;
  maxCandidates: number;
  setMaxCandidates: (v: number) => void;
  candidateCount: number;
}

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

const DIMENSION_GROUPS: { title: string; dims: string[]; note: string }[] = [
  {
    title: 'Parallelism',
    dims: ['tp', 'pp', 'ep', 'dp'],
    note: 'TP / PP / EP / DP search dimensions — pending qualification.',
  },
  {
    title: 'Fabric',
    dims: ['link_width', 'topology_family', 'concentration', 'radix'],
    note: 'Qualified fabric dimensions from the capability authority.',
  },
  {
    title: 'Placement',
    dims: ['placement_compute', 'placement_controller', 'placement_nic'],
    note: 'Placement search through canonical artifacts — pending.',
  },
  {
    title: 'Advanced',
    dims: ['arbitration'],
    note: 'Only parameters proven effective and qualified appear here.',
  },
];

const DERIVED_NEVER_KNOBS = ['vc_count', 'vc_map', 'route_table'];

function GenericDimensions({ caps, base, extraSelections, setExtraSelection,
  extraTexts, setExtraText }: {
  caps: DesignSpaceProps['caps'];
  base: Record<string, unknown> | null;
  extraSelections: Record<string, (string | number)[]>;
  setExtraSelection: (name: string, v: (string | number)[]) => void;
  extraTexts: Record<string, string>;
  setExtraText: (name: string, v: string) => void;
}): ReactElement | null {
  const CORE = new Set(['link_width', 'topology_family', 'concentration', 'radix']);
  const qualified = new Set(caps.qualified_parameters);
  const rows = caps.guided_parameters.filter(
    (g) => qualified.has(g.name) && !CORE.has(g.name));
  if (rows.length === 0) return null;
  const current = (name: string): string => {
    const v = base?.[name];
    return v === undefined || v === null ? '—' : String(v);
  };
  return (
    <fieldset>
      <legend>Further qualified dimensions</legend>
      <p className="muted">
        Qualified by the backend probe (effective and executable through the
        certified chain) — live knobs, not pending disclosures.
      </p>
      {rows.map((g) => {
        const choices = g.executable_values ?? g.accepted_values ?? null;
        const selected = extraSelections[g.name] ?? [];
        return (
          <div className="form-row" key={g.name}>
            <label>
              {HUMAN[g.name] ?? g.name}
              <span className="muted"> — current: {current(g.name)}</span>{' '}
              <span className="muted">({g.kind}{g.value_constraint ? ` · ${g.value_constraint}` : ''})</span>
              {(g.kind === 'enum' || g.kind === 'str' || g.kind === 'bool') && choices ? (
                <Chips
                  values={choices} selected={selected}
                  onToggle={(v, on) => setExtraSelection(
                    g.name, toggle(selected, v as string | number, on))}
                />
              ) : g.kind === 'bool' ? (
                <select
                  value={selected.length ? String(selected[0]) : ''}
                  onChange={(e) => setExtraSelection(
                    g.name, e.target.value === '' ? [] : [e.target.value])}
                  aria-label={g.name}
                >
                  <option value="">—</option>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : (
                <input
                  type="text"
                  value={extraTexts[g.name] ?? ''}
                  placeholder="comma-separated values"
                  onChange={(e) => setExtraText(g.name, e.target.value)}
                  aria-label={g.name}
                />
              )}
              <small className="muted">
                {g.reason ?? 'Backend-qualified dimension.'}{' '}
                {choices && !g.accepted_values_is_exhaustive
                  ? 'UI choices on a validated range.' : ''}
              </small>
            </label>
          </div>
        );
      })}
    </fieldset>
  );
}

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

  const pendingDims = (names: string[]): string[] =>
    names.filter((n) => !qualified.has(n));

  return (
    <>
      <h4>What do you want VERITX to vary?</h4>
      <p className="muted">
        {qualified.size} qualified dimension(s):{' '}
        {caps.qualified_parameters.join(', ') || 'none'}. Only these can enter a
        certified study. {DERIVED_NEVER_KNOBS.join(', ')} are compiler-derived
        correctness state — never search knobs.
      </p>

      {DIMENSION_GROUPS.filter((g) => g.title !== 'Fabric').map((g) => {
        const pending = pendingDims(g.dims);
        const live = g.dims.filter((n) => qualified.has(n));
        return (
          <details className="card-details" key={g.title}>
            <summary>
              {g.title} — {pending.length === 0 ? 'qualified' : 'pending qualification'}
            </summary>
            <p className="muted">{g.note}</p>
            {live.length > 0 && (
              <p className="muted">Qualified in this group: {live.join(', ')}.</p>
            )}
            {pending.length > 0 && (
              <p className="muted">
                Pending: {pending.join(', ')} — visible with truthful
                maturity state, not offered as study knobs until qualified.
              </p>
            )}
          </details>
        );
      })}

      <fieldset>
        <legend>Fabric — qualified dimensions</legend>
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
      </fieldset>

      <GenericDimensions
        caps={caps} base={base}
        extraSelections={p.extraSelections}
        setExtraSelection={p.setExtraSelection}
        extraTexts={p.extraTexts} setExtraText={p.setExtraText}
      />

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
                    : (p.extraSelections[n]?.length ?? 0) > 0
                      ? p.extraSelections[n].length : undefined;
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

      <details className="card-details">
        <summary>Objective effectiveness — why these rules</summary>
        <h4>Objective effectiveness</h4>
        <p className="muted">{caps.objective_note}</p>
        <p className="muted" title={caps.effectiveness_basis}>
          Effectiveness basis: {caps.effectiveness_basis || 'measured through the certified chain'}
        </p>
        {caps.not_measured.length > 0 && (
          <p className="muted">
            Not measured in any certified study: {caps.not_measured.join(', ')}.{' '}
            {caps.not_measured_note}
          </p>
        )}
        <p className="muted">
          Objectives are selected below from the federated metric catalog.
          A fabric knob (e.g. link width) has no direct effect on a
          dependency-model metric (e.g. critical path) — meaningless
          combinations warn before launch.
        </p>
      </details>
    </>
  );
}
