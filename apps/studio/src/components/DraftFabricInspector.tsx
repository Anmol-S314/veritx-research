import { useState, type ReactElement } from 'react';
import { api } from '../api';
import type { DesignView } from '../types';
import type { FabricSelection } from './FabricInspector';
import type { FabricModel } from '../fabricLayout';

/** PRD §4.4 tier model. Only GUIDED fields are editable here; the LOCKED set is
 *  engine-derived and is listed as evidence, never as a control. */
const GUIDED: { key: keyof DesignView['noc_guided']; label: string; hint: string }[] = [
  { key: 'topology_family', label: 'Topology family', hint: 'mesh / fat_tree / torus / gec' },
  { key: 'radix', label: 'Side length', hint: 'grid width for the mesh' },
  { key: 'concentration', label: 'Concentration', hint: 'tiles per router' },
  { key: 'link_width', label: 'Link width (bits)', hint: 'per directed channel' },
  { key: 'arbitration', label: 'Arbitration', hint: 'high-level preference' },
  { key: 'rcu_enabled', label: 'RCU (in-network reduction)', hint: 'enable + scope all-reduce' },
];

function Row({ label, value }: { label: string; value: ReactElement | string }): ReactElement {
  return (
    <div className="kv">
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}

export default function DraftFabricInspector({
  projectId, design, model, selection, onClose,
}: {
  projectId: string;
  design: DesignView;
  model: FabricModel;
  selection: FabricSelection;
  onClose: () => void;
}): ReactElement {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (selection.kind !== 'router') {
    return (
      <div className="fabric-inspector" role="region" aria-label="Draft fabric inspector">
        <p className="muted">
          Select a router on the canvas to see what produced it.
        </p>
        <button className="btn" onClick={onClose}>Close</button>
      </div>
    );
  }

  const node = model.nodes.find((n) => n.id === selection.routerId);
  if (!node) {
    return (
      <div className="fabric-inspector" role="region" aria-label="Draft fabric inspector">
        <p className="muted">That router is not in the draft preview.</p>
        <button className="btn" onClick={onClose}>Close</button>
      </div>
    );
  }

  const incident = model.edges.filter((e) => e.a === node.id || e.b === node.id);
  const widths = [...new Set(incident.map((e) => e.widthBits))];

  const update = async (key: keyof DesignView['noc_guided'], value: unknown): Promise<void> => {
    setSaving(true);
    setError(null);
    try {
      const draft = await api.draft(projectId);
      const request = { ...(draft as unknown as { request: Record<string, unknown> }).request };
      const noc = { ...(request.noc_config as Record<string, unknown>) };
      noc[key] = value;
      request.noc_config = noc;
      await api.putDraft(projectId, request as Record<string, unknown>);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const g = design.noc_guided;

  return (
    <div className="fabric-inspector" role="region" aria-label="Draft fabric inspector">
      <div className="panel-heading">
        Router R{node.row},{node.col}
        <button className="btn" onClick={onClose} aria-label="Close inspector">✕</button>
      </div>

      <Row label="position" value={<code>[{node.col}, {node.row}]</code>} />
      <Row label="seats" value={String(node.seats)} />
      <Row label="incident links" value={String(incident.length)} />
      <Row label="link widths" value={widths.length ? widths.join(', ') + 'b' : '—'} />
      <Row label="family" value={model.family ?? '—'} />
      <Row label="shape" value={model.shape} />

      <h4>GUIDED — edits the draft</h4>
      <p className="muted">
        These are the inputs that produced this router. A change rewrites the
        draft; the certified graph only moves after a compile.
      </p>
      {GUIDED.map((f) => (
        <div className="kv" key={String(f.key)}>
          <label htmlFor={`guided-${String(f.key)}`}>{f.label}</label>
          {f.key === 'rcu_enabled' ? (
            <input
              id={`guided-${String(f.key)}`}
              type="checkbox"
              checked={g.rcu_enabled === true}
              disabled={saving}
              onChange={(e) => void update('rcu_enabled', e.target.checked)}
            />
          ) : (
            <input
              id={`guided-${String(f.key)}`}
              type="text"
              defaultValue={g[f.key] === null || g[f.key] === undefined ? '' : String(g[f.key])}
              placeholder="engine default"
              title={f.hint}
              disabled={saving}
              onBlur={(e) => {
                const raw = e.target.value.trim();
                const num = f.key === 'topology_family' || f.key === 'arbitration' ? raw : Number(raw);
                if (raw === '') void update(f.key, null);
                else if (Number.isNaN(num)) void update(f.key, raw);
                else void update(f.key, num);
              }}
            />
          )}
        </div>
      ))}

      {error && <p className="muted" role="alert">Not saved: {error}</p>}
      {saving && <p className="muted" role="status">saving…</p>}

      <h4>LOCKED — engine-derived</h4>
      <table className="tbl">
        <tbody>
          <tr><td>routing</td><td><code>{design.locked_derived?.routing ?? '—'}</code></td></tr>
          <tr><td>VC count</td><td><code>{design.locked_derived?.vc_count ?? '—'}</code></td></tr>
          <tr>
            <td>turn restrictions</td>
            <td><code>{(design.locked_derived?.turn_restrictions ?? []).join(' ') || '—'}</code></td>
          </tr>
        </tbody>
      </table>
      <p className="muted">
        Routing, turn restrictions and the VC map are derived by the engine and
        carry no override (PRD §4.4). No endpoint is seated on a draft router:
        attachment is decided at compile time.
      </p>
    </div>
  );
}