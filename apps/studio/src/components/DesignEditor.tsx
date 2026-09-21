import { useEffect, useState, type ReactElement } from 'react';
import type { DesignView, Requirement } from '../types';
import { Hash, TierBadge } from './badges';
import FabricCanvas from './FabricCanvas';

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

const KIND_OPTIONS = ['compute', 'hbm', 'nic', 'peripheral', 'ucie'];
const TOPO_OPTIONS = ['MESH', 'C_MESH', 'TORUS', 'RING'];
const ARB_OPTIONS = ['round_robin', 'priority', 'age_based'];

/**
 * E1–E5 design editor. GUIDED/FREE knobs are editable; LOCKED properties are
 * rendered read-only. Edits are local-only (fixture mode: no engine
 * connectivity, so nothing recompiles) and flagged dirty with a reset path.
 */
export default function DesignEditor({ design }: { design: DesignView }): ReactElement {
  const [draft, setDraft] = useState<DesignView>(() => clone(design));
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setDraft(clone(design));
    setDirty(false);
  }, [design]);

  const touch = (next: DesignView): void => {
    setDraft(next);
    setDirty(JSON.stringify(next) !== JSON.stringify(design));
  };

  const setGuided = <K extends keyof DesignView['noc_guided']>(
    key: K,
    value: DesignView['noc_guided'][K],
  ): void => {
    const next = clone(draft);
    next.noc_guided[key] = value;
    touch(next);
  };

  const setReq = (idx: number, patch: Partial<Requirement>): void => {
    const next = clone(draft);
    next.requirements[idx] = { ...next.requirements[idx], ...patch };
    touch(next);
  };

  const addReq = (): void => {
    const next = clone(draft);
    next.requirements.push({
      traffic_class: 'new_class',
      qos_class: 'best_effort',
      latency_ceiling_cycles: null,
      bandwidth_floor_gbps: null,
      binding: false,
    });
    touch(next);
  };

  const delReq = (idx: number): void => {
    const next = clone(draft);
    next.requirements.splice(idx, 1);
    touch(next);
  };

  const setAgent = (idx: number, count: number): void => {
    const next = clone(draft);
    next.agents[idx] = { ...next.agents[idx], count: Math.max(1, count) };
    touch(next);
  };

  const locked = draft.locked_derived;
  const g = draft.noc_guided;
  const w = draft.workload;

  return (
    <div className="design-grid">
      <div className="design-main">
        {dirty && (
          <div className="dirty-banner">
            <span>
              <strong>Modified locally — recompile required.</strong> Fixture mode has no
              engine connectivity, so edits do not recompile and LOCKED values are
              stale until a real compile runs.
            </span>
            <button
              className="btn"
              onClick={() => {
                setDraft(clone(design));
                setDirty(false);
              }}
            >
              Reset to fixture
            </button>
          </div>
        )}

        {/* E1 workload */}
        <section className="card">
          <h3>
            E1 · Workload <TierBadge tier="GUIDED" />
          </h3>
          <div className="form-row">
            <label>
              Model family
              <input
                value={w.model_family}
                onChange={(e) => touch({ ...clone(draft), workload: { ...w, model_family: e.target.value } })}
              />
            </label>
            <label>
              Model name
              <input
                value={w.model_name ?? ''}
                onChange={(e) => touch({ ...clone(draft), workload: { ...w, model_name: e.target.value } })}
              />
            </label>
            <label>
              Serving mode
              <input
                value={w.serving_mode ?? ''}
                onChange={(e) => touch({ ...clone(draft), workload: { ...w, serving_mode: e.target.value } })}
              />
            </label>
          </div>
          <div className="form-row">
            {(['tp', 'pp', 'ep', 'dp'] as const).map((k) => (
              <label key={k}>
                Parallelism · {k.toUpperCase()}
                <input
                  type="number"
                  min={1}
                  value={w.parallelism[k]}
                  onChange={(e) => {
                    const next = clone(draft);
                    next.workload.parallelism[k] = Math.max(1, Number(e.target.value) || 1);
                    touch(next);
                  }}
                />
              </label>
            ))}
          </div>
        </section>

        {/* E2 requirements */}
        <section className="card">
          <h3>
            E2 · Requirements <TierBadge tier="GUIDED" />
          </h3>
          <table className="tbl">
            <thead>
              <tr>
                <th>Traffic class</th>
                <th>QoS class</th>
                <th>Latency ceiling (cycles)</th>
                <th>Bandwidth floor (Gbps)</th>
                <th>Binding</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {draft.requirements.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input value={r.traffic_class ?? ''} onChange={(e) => setReq(i, { traffic_class: e.target.value || null })} />
                  </td>
                  <td>
                    <input value={r.qos_class} onChange={(e) => setReq(i, { qos_class: e.target.value })} />
                  </td>
                  <td>
                    <input
                      type="number"
                      value={r.latency_ceiling_cycles ?? ''}
                      placeholder="—"
                      onChange={(e) =>
                        setReq(i, { latency_ceiling_cycles: e.target.value === '' ? null : Number(e.target.value) })
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      value={r.bandwidth_floor_gbps ?? ''}
                      placeholder="—"
                      onChange={(e) =>
                        setReq(i, { bandwidth_floor_gbps: e.target.value === '' ? null : Number(e.target.value) })
                      }
                    />
                  </td>
                  <td>
                    <input type="checkbox" checked={r.binding} onChange={(e) => setReq(i, { binding: e.target.checked })} />
                  </td>
                  <td>
                    <button className="btn btn-danger" onClick={() => delReq(i)} aria-label={`Delete requirement ${i}`}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button className="btn" onClick={addReq}>
            + Add requirement
          </button>
        </section>

        {/* E3 agents */}
        <section className="card">
          <h3>
            E3 · Agents <TierBadge tier="GUIDED" />
          </h3>
          <div className="form-row">
            {draft.agents.map((a, i) => (
              <label key={`${a.kind}-${i}`}>
                {KIND_OPTIONS.includes(a.kind) ? a.kind : `kind: ${a.kind}`} · count
                <input type="number" min={1} value={a.count} onChange={(e) => setAgent(i, Number(e.target.value) || 1)} />
              </label>
            ))}
          </div>
        </section>

        {/* E4 dependencies */}
        <section className="card">
          <h3>
            E4 · Dependencies <TierBadge tier="GUIDED" />
          </h3>
          <p className="muted">
            The frozen contract carries no DependencyGraph view (v2 class names are ad
            hoc), so this panel derives the dependency-relevant signal from E2: binding
            requirements order traffic-class admission, and the compiler derives VCs
            from the resolved route — never from Studio input.
          </p>
          <ul className="dep-list">
            {draft.requirements
              .filter((r) => r.binding)
              .map((r, i) => (
                <li key={i}>
                  <code>{r.traffic_class ?? '—'}</code> ({r.qos_class}) must be admitted
                  by the VC map before spawn — unknown class is a typed refusal, never
                  silent VC0.
                </li>
              ))}
            {draft.requirements.filter((r) => r.binding).length === 0 && (
              <li className="muted">No binding requirements — nothing gates spawn.</li>
            )}
          </ul>
        </section>

        {/* E5 noc config */}
        <section className="card">
          <h3>E5 · NoC configuration</h3>
          <div className="form-row">
            <label>
              Topology family <TierBadge tier="GUIDED" />
              <select
                value={g.topology_family ?? ''}
                onChange={(e) => setGuided('topology_family', e.target.value || null)}
              >
                <option value="">—</option>
                {TOPO_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Radix <TierBadge tier="GUIDED" />
              <input
                type="number"
                value={g.radix ?? ''}
                onChange={(e) => setGuided('radix', e.target.value === '' ? null : Number(e.target.value))}
              />
            </label>
            <label>
              Concentration <TierBadge tier="GUIDED" />
              <input
                type="number"
                value={g.concentration ?? ''}
                onChange={(e) => setGuided('concentration', e.target.value === '' ? null : Number(e.target.value))}
              />
            </label>
            <label>
              Link width <TierBadge tier="GUIDED" />
              <input
                type="number"
                value={g.link_width ?? ''}
                onChange={(e) => setGuided('link_width', e.target.value === '' ? null : Number(e.target.value))}
              />
            </label>
            <label>
              Arbitration <TierBadge tier="GUIDED" />
              <select
                value={g.arbitration ?? ''}
                onChange={(e) => setGuided('arbitration', e.target.value || null)}
              >
                <option value="">—</option>
                {ARB_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={g.rcu_enabled ?? false}
                onChange={(e) => setGuided('rcu_enabled', e.target.checked)}
              />
              RCU (in-network reduction) <TierBadge tier="GUIDED" />
            </label>
          </div>

          <h4 className="locked-head">
            Derived properties <TierBadge tier="LOCKED" />
          </h4>
          {locked ? (
            <div className="locked-grid">
              <div>
                <span className="k">Routing</span>
                <span className="v">
                  {locked.routing} <span className="lock" title="Derived by engine — no override">🔒 Derived</span>
                </span>
              </div>
              <div>
                <span className="k">VC count</span>
                <span className="v">
                  {locked.vc_count} <span className="lock" title="Bound to resolved route — no override">🔒 Derived</span>
                </span>
              </div>
              <div>
                <span className="k">Turn restrictions</span>
                <span className="v">
                  {locked.turn_restrictions.join('; ')}{' '}
                  <span className="lock" title="Compiler-derived — no override">🔒 Derived</span>
                </span>
              </div>
              <div>
                <span className="k">Certificate</span>
                <span className="v">{locked.certificate_overall}</span>
              </div>
            </div>
          ) : (
            <p className="muted">Not compiled — no LOCKED values exist for this design.</p>
          )}
        </section>

        <section className="card">
          <h3>Design identity</h3>
          <div className="kv">
            <span>design_hash</span>
            <Hash value={draft.design_hash} />
          </div>
          <div className="kv">
            <span>schema / semantics</span>
            <span>
              v{draft.schema_version} · compiler sem {draft.compiler_semantics_version}
            </span>
          </div>
        </section>
      </div>

      <aside className="design-side">
        <section className="card">
          <h3>Fabric canvas</h3>
          <FabricCanvas design={draft} />
        </section>
      </aside>
    </div>
  );
}
