import { useEffect, useState, type ReactElement } from 'react';
import { api } from '../api';
import type { DesignView, Requirement } from '../types';
import { Hash, TierBadge } from './badges';
import { agentLabel } from './FabricCanvas';
import FabricView from './FabricView';
import { ErrorBox } from '../studio';
import { clone, setPath } from '../util';

// Engine enum values with presentation labels. The option value is the
// engine value; only the visible label is friendlier.

// model/compile_model.py::ModelFamily
const MODEL_FAMILIES: [string, string][] = [
  ['dense_transformer', 'Dense transformer'],
  ['mixture_of_experts', 'Mixture of experts'],
  ['diffusion', 'Diffusion'],
  ['cnn', 'CNN'],
  ['custom', 'Custom'],
];
// model/compile_model.py::ServingMode
const SERVING_MODES: [string, string][] = [
  ['prefill_heavy', 'Prefill heavy'],
  ['decode_heavy', 'Decode heavy'],
  ['mixed', 'Mixed'],
];
// model/compile_model.py::QoSClass
const QOS_CLASSES: [string, string][] = [
  ['latency_critical', 'Latency critical'],
  ['bandwidth', 'Bandwidth'],
  ['best_effort', 'Best effort'],
];
// model/compile_model.py::TopologyFamily (torus/gec/fat_tree are typed
// refusals on the P1A routing path — selectable, never silently downgraded).
const TOPO_OPTIONS: [string, string][] = [
  ['mesh', 'Mesh'],
  ['concentrated_mesh', 'Concentrated mesh'],
  ['torus', 'Torus — route-refused'],
  ['gec', 'GEC — refused'],
  ['fat_tree', 'Fat tree — refused'],
];
// model/router_behavior.py::_ARBITRATION_ALIASES
const ARB_OPTIONS: [string, string][] = [
  ['islip', 'iSLIP'],
  ['round_robin', 'Round robin'],
];

/** A DesignView-shaped preview derived from the draft request, so the
 * side view can draw intent without claiming it is certified. */
function previewFromRequest(req: Record<string, unknown>): DesignView {
  const w = (req.workload ?? {}) as Record<string, unknown>;
  const noc = (req.noc_config ?? {}) as Record<string, unknown>;
  const par = (k: string): number => {
    const v = Number(w[k]);
    return Number.isFinite(v) && v >= 1 ? Math.floor(v) : 1;
  };
  const num = (v: unknown): number | null => {
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return {
    contract_version: 1,
    design_hash: '',
    schema_version: Number(req.schema_version ?? 3),
    compiler_semantics_version: 0,
    workload: {
      model_family: String(w.model_family ?? ''),
      model_name: String(w.model_name ?? ''),
      parallelism: { tp: par('tp'), pp: par('pp'), ep: par('ep'), dp: par('dp') },
      serving_mode: String(w.serving_mode ?? 'mixed'),
    },
    requirements: (req.requirements ?? []) as Requirement[],
    agents: (req.agents ?? []) as DesignView['agents'],
    noc_guided: {
      topology_family: (noc.topology_family as string | null) ?? null,
      radix: num(noc.radix),
      concentration: num(noc.concentration),
      link_width: num(noc.link_width),
      rcu_enabled: (noc.rcu_enabled as boolean | null) ?? null,
      arbitration: (noc.arbitration as string | null) ?? null,
    },
    locked_derived: null,
  };
}

/**
 * The one editable Design Intent form. Edits here ARE the canonical
 * draft: saving writes the gateway draft, compiling certifies a new
 * immutable revision. There is no second editor; nothing here is
 * local-only.
 */
export default function DesignEditor({ projectId, request, draftDesignHash,
  draftDirty, activeDesign, activeDisplayName, certifiedRevisionId,
  latestRefusal, draftMatchesAttempt, onChanged }: {
  projectId: string;
  /** The gateway draft request document (canonical inputs). */
  request: Record<string, unknown>;
  draftDesignHash: string | null;
  /** Draft differs from the active revision. */
  draftDirty: boolean;
  /** The active revision's DesignView (read-only LOCKED source). */
  activeDesign: DesignView | null;
  activeDisplayName: string | null;
  /** Certified revision id to draw, or null when there is none. */
  certifiedRevisionId: string | null;
  /** Latest attempt when it was refused, else null. */
  latestRefusal: { display_name: string; error: string | null } | null;
  /** The draft still equals the refused attempt (fix, don't recompile). */
  draftMatchesAttempt: boolean;
  onChanged: () => void;
}): ReactElement {
  const [doc, setDoc] = useState<Record<string, unknown>>(() => clone(request));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setDoc(clone(request));
  }, [request]);

  const localDirty = JSON.stringify(doc) !== JSON.stringify(request);
  const showingPreview = localDirty || draftDirty;

  const edit = (path: string, value: unknown): void => {
    const next = clone(doc);
    setPath(next, path, value);
    setDoc(next);
  };

  const editNum = (path: string, raw: string, min: number | null): void => {
    if (raw === '') {
      edit(path, min === null ? null : min);
      return;
    }
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    edit(path, min === null ? n : Math.max(min, Math.floor(n)));
  };

  const save = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await api.putDraft(projectId, doc);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };

  const compile = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      if (localDirty) await api.putDraft(projectId, doc);
      await api.compile(projectId);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setBusy(false);
    }
  };

  const setReq = (idx: number, patch: Partial<Requirement>): void => {
    const next = clone(doc);
    const reqs = [...((next.requirements ?? []) as Requirement[])];
    reqs[idx] = { ...reqs[idx], ...patch };
    next.requirements = reqs;
    setDoc(next);
  };

  const addReq = (): void => {
    const next = clone(doc);
    next.requirements = [...((next.requirements ?? []) as Requirement[]), {
      traffic_class: 'new_class',
      qos_class: 'best_effort',
      latency_ceiling_cycles: null,
      bandwidth_floor_gbps: null,
      binding: false,
    }];
    setDoc(next);
  };

  const delReq = (idx: number): void => {
    const next = clone(doc);
    const reqs = [...((next.requirements ?? []) as Requirement[])];
    reqs.splice(idx, 1);
    next.requirements = reqs;
    setDoc(next);
  };

  const setAgent = (idx: number, count: number): void => {
    const next = clone(doc);
    const agents = [...((next.agents ?? []) as DesignView['agents'])];
    agents[idx] = { ...agents[idx], count: Math.max(1, count) };
    next.agents = agents;
    setDoc(next);
  };

  const w = (doc.workload ?? {}) as Record<string, unknown>;
  const noc = (doc.noc_config ?? {}) as Record<string, unknown>;
  const reqs = (doc.requirements ?? []) as Requirement[];
  const agents = (doc.agents ?? []) as DesignView['agents'];
  const locked = activeDesign?.locked_derived ?? null;
  const sideDesign = showingPreview || !activeDesign
    ? previewFromRequest(doc)
    : activeDesign;
  const sideRevisionId = showingPreview ? null : certifiedRevisionId;

  return (
    <div className="design-grid">
      <div className="design-main">
        {latestRefusal && draftMatchesAttempt && (
          <div className="verdict-banner verdict-unsupported" role="alert">
            <span className="verdict-text">
              <strong>
                New design refused · attempt {latestRefusal.display_name}.
              </strong>{' '}
              {latestRefusal.error ?? 'Compilation refused.'}{' '}
              {activeDisplayName
                ? `The certified revision ${activeDisplayName} remains active.`
                : 'No certified revision exists yet.'}{' '}
              Fix the design below — recompiling unchanged would refuse again.
            </span>
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
              <select
                value={String(w.model_family ?? '')}
                onChange={(e) => edit('workload.model_family', e.target.value)}
              >
                {MODEL_FAMILIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model name
              <input
                value={String(w.model_name ?? '')}
                onChange={(e) => edit('workload.model_name', e.target.value)}
              />
            </label>
            <label>
              Serving mode
              <select
                value={String(w.serving_mode ?? 'mixed')}
                onChange={(e) => edit('workload.serving_mode', e.target.value)}
              >
                {SERVING_MODES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-row">
            {(['tp', 'pp', 'ep', 'dp'] as const).map((k) => (
              <label key={k}>
                Parallelism · {k.toUpperCase()}
                <input
                  type="number"
                  min={1}
                  value={String(w[k] ?? 1)}
                  onChange={(e) => editNum(`workload.${k}`, e.target.value, 1)}
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
              {reqs.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input value={r.traffic_class ?? ''} onChange={(e) => setReq(i, { traffic_class: e.target.value || null })} />
                  </td>
                  <td>
                    <select value={r.qos_class} onChange={(e) => setReq(i, { qos_class: e.target.value })}>
                      {QOS_CLASSES.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
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
            {agents.map((a, i) => (
              <label key={`${a.kind}-${i}`}>
                {agentLabel(a.kind)} · count
                <input type="number" min={1} value={a.count} onChange={(e) => setAgent(i, Number(e.target.value) || 1)} />
              </label>
            ))}
          </div>
        </section>

        {/* E5 noc config */}
        <section className="card">
          <h3>E5 · NoC configuration</h3>
          <div className="form-row">
            <label>
              Topology family <TierBadge tier="GUIDED" />
              <select
                value={String(noc.topology_family ?? '')}
                onChange={(e) => edit('noc_config.topology_family', e.target.value || null)}
              >
                <option value="">—</option>
                {TOPO_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Radix <TierBadge tier="GUIDED" />
              <input
                type="number"
                value={noc.radix === null || noc.radix === undefined ? '' : String(noc.radix)}
                onChange={(e) => editNum('noc_config.radix', e.target.value, null)}
              />
            </label>
            <label>
              Concentration <TierBadge tier="GUIDED" />
              <input
                type="number"
                value={noc.concentration === null || noc.concentration === undefined ? '' : String(noc.concentration)}
                onChange={(e) => editNum('noc_config.concentration', e.target.value, null)}
              />
            </label>
            <label>
              Link width (b) <TierBadge tier="GUIDED" />
              <input
                type="number"
                value={noc.link_width === null || noc.link_width === undefined ? '' : String(noc.link_width)}
                onChange={(e) => editNum('noc_config.link_width', e.target.value, null)}
              />
            </label>
            <label>
              Arbitration <TierBadge tier="GUIDED" />
              <select
                value={String(noc.arbitration ?? '')}
                onChange={(e) => edit('noc_config.arbitration', e.target.value || null)}
              >
                <option value="">—</option>
                {ARB_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={noc.rcu_enabled === true}
                onChange={(e) => edit('noc_config.rcu_enabled', e.target.checked)}
              />
              RCU (in-network reduction) <TierBadge tier="GUIDED" />
            </label>
          </div>
          {noc.rcu_enabled === true && (
            <div className="rcu-refusal">
              <strong>Compiler refusal:</strong> <code>rcu_enabled=true</code> has
              no RCU realization in the current fabric — compiling refuses as
              UNSUPPORTED rather than silently dropping the intent.
            </div>
          )}

          <h4 className="locked-head">
            Derived properties <TierBadge tier="LOCKED" />
          </h4>
          {draftDirty && activeDisplayName && (
            <p className="muted">
              Showing LOCKED values from {activeDisplayName} — the draft has
              uncompiled changes.
            </p>
          )}
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
                  {(locked.turn_restrictions ?? []).join('; ') || '—'}{' '}
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
          <h3>Save &amp; compile</h3>
          <div className="form-row">
            <button className="btn" disabled={busy || !localDirty} onClick={save}>
              Save draft
            </button>
            <button className="btn btn-primary" disabled={busy} onClick={compile}>
              {busy ? 'Compiling…' : 'Compile design'}
            </button>
            {(localDirty || draftDirty) && (
              <span className="stale">UNCOMPILED CHANGES</span>
            )}
          </div>
          {error && <ErrorBox error={error} />}
          <p className="muted">
            Saving updates the draft; compiling certifies a new immutable
            revision. The previous revision is never mutated.
          </p>
        </section>

        <section className="card">
          <h3>Evidence · identity</h3>
          <div className="kv">
            <span>design identity</span>
            <Hash value={draftDesignHash} />
          </div>
          <div className="kv">
            <span>request schema</span>
            <span>v{String(doc.schema_version ?? activeDesign?.schema_version ?? '—')}</span>
          </div>
          <div className="kv">
            <span>compiler semantics</span>
            <span>{activeDesign ? `sem ${activeDesign.compiler_semantics_version}` : 'uncompiled'}</span>
          </div>
        </section>
      </div>

      <aside className="design-side">
        <section className="card">
          <h3>Topology / traffic view</h3>
          <p className="muted">
            {showingPreview || !activeDesign
              ? 'Draft preview from declared counts — compile to materialize the certified graph.'
              : `Certified fabric of ${activeDisplayName}.`}
          </p>
          <FabricView design={sideDesign} revisionId={sideRevisionId} />
        </section>
      </aside>
    </div>
  );
}
