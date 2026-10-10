/** Renders whatever knob surface the server reports.
 *
 * There is deliberately NO field name, bound, default or legal-value list in
 * this file. It walks the inventory the engine introspects from its own
 * dataclasses, so a knob added to the model appears here with no UI change,
 * and a hand-written list can never drift from the parser. Legality is not
 * decided here either: out-of-range or impossible combinations surface as the
 * engine's own refusal on save/compile, which is shown verbatim.
 */
import { useMemo, type ReactElement } from 'react';
import { useAsync } from '../studio';
import { api } from '../api';
import type { KnobInventoryFamily, KnobInventoryField, KnobInventoryView } from '../api/types';

export type KnobField = KnobInventoryField;
export type KnobFamily = KnobInventoryFamily;
export type KnobInventory = KnobInventoryView;

/** Which draft block carries controls, by schema generation. */
export function controlsBlock(doc: Record<string, unknown>): 'noc_controls' | 'noc_config' | null {
  const v = Number(doc.schema_version ?? 0);
  if (v === 4) return 'noc_controls';
  if (v === 2 || v === 3) return 'noc_config';
  return null;
}

function readBlock(doc: Record<string, unknown>, key: string): Record<string, unknown> {
  const raw = doc[key];
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown> : {};
}

/** Field label: the server's name, humanised. No per-field dictionary. */
function label(name: string): string {
  return name.replace(/_/g, ' ').replace(/^./, (s) => s.toUpperCase());
}

function Field({ field, value, disabled, onChange, binds }: {
  field: KnobField;
  value: unknown;
  disabled: boolean;
  onChange: (v: unknown) => void;
  binds?: string;
}): ReactElement {
  const title = binds ? `binds to ${binds}` : undefined;
  const control = (() => {
    if (field.type === 'boolean') {
      return <input type="checkbox" checked={value === true} disabled={disabled}
        onChange={(e) => onChange(e.target.checked)} />;
    }
    if (field.type === 'enum' && field.values?.length) {
      return <select disabled={disabled}
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}>
        <option value="">—</option>
        {field.values.map((v) => <option key={v}>{v}</option>)}
      </select>;
    }
    if (field.type === 'enum_list' && field.values?.length) {
      const current = Array.isArray(value) ? value : [];
      return <select multiple disabled={disabled}
        value={current.map(String)}
        onChange={(e) => {
          const picked = [...e.target.selectedOptions].map((o) => o.value);
          onChange(picked.length ? picked : null);
        }}>
        {field.values.map((v) => <option key={v}>{v}</option>)}
      </select>;
    }
    if (field.type === 'object' || field.type === 'json' || field.type === 'list') {
      const text = value == null ? '' : JSON.stringify(value);
      return <textarea rows={3} disabled={disabled} value={text}
        placeholder={field.type === 'json' ? 'engine-defined structure' : ''}
        onChange={(e) => {
          if (e.target.value.trim() === '') { onChange(null); return; }
          try { onChange(JSON.parse(e.target.value)); }
          catch { /* keep the last valid value; the engine validates anyway */ }
        }} />;
    }
    if (field.type === 'string') {
      return <input type="text" disabled={disabled} value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)} />;
    }
    return <input type="number" disabled={disabled}
      value={value == null ? '' : String(value)}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />;
  })();
  return (
    <label className="field" key={field.name} title={title}>
      <span className="field-label">
        {label(field.name)}
        {field.required && <span className="muted"> (required)</span>}
        {binds && <span className="muted"> · {binds}</span>}
      </span>
      {control}
    </label>
  );
}

/** The full surface for one draft: every topology field of the declared
 *  family, then every control, grouped as the server reports them. */
export default function KnobEditor({ doc, onChange, readOnly = false, controlsOnly = false, excludeFields = [] }: {
  doc: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  readOnly?: boolean;
  controlsOnly?: boolean;
  excludeFields?: string[];
}): ReactElement {
  const inventory = useAsync<KnobInventoryView>(() => api.knobInventory(), []);
  const block = controlsBlock(doc);
  const topology = doc.topology as Record<string, unknown> | undefined;
  const familyKind = String(topology?.kind ?? '');
  const family = useMemo(
    () => inventory.result.state === 'ready'
      ? inventory.result.data.topology.find((f) => f.kind === familyKind) ?? null
      : null,
    [inventory.result, familyKind],
  );
  const params = (topology?.params ?? {}) as Record<string, unknown>;
  const writeCtl = (name: string, value: unknown): void => {
    if (!block) return;
    const next = { ...readBlock(doc, block) };
    if (value === null || value === '') delete next[name];
    else next[name] = value;
    onChange({ ...doc, [block]: next });
  };

  if (inventory.result.state === 'loading') {
    return <p className="muted" role="status">Reading the engine's knob surface…</p>;
  }
  if (inventory.result.state === 'error') {
    return (
      <div role="alert">
        <p className="t-bad">✗ knob inventory unreadable: {inventory.result.error.message}</p>
        <button className="btn btn-small" onClick={() => inventory.reload()}>Retry</button>
      </div>
    );
  }
  const data = inventory.result.data;
  const controls = data.controls.filter(field => !excludeFields.includes(field.name));
  const groups = [...new Set(controls.map((c) => c.group ?? 'other'))];
  const unknownFamily = familyKind !== '' && !family;

  return (
    <section className="topology-intent" aria-label="Design knobs">
      {data.not_covered.length > 0 && <p className="muted" role="note">
        Generic inventory excludes {data.not_covered.join(', ')}; those blocks use their dedicated editors or remain unsupported.
      </p>}
      {!controlsOnly && <details className="subtle">
        <summary>Engine field reference</summary>
        <p className="muted">{data.notes}</p>
      </details>}

      {!controlsOnly && family && (
        <div>
          <h4>{label(family.label)} topology</h4>
          <div className="form-grid">
            {family.fields.map((field) => {
              // The engine declares `params` sub-fields for structured
              // families; typed intents declare their own keys directly.
              const inParams = field.name in params;
              const value = inParams ? params[field.name]
                : topology ? topology[field.name] : undefined;
              const set = (v: unknown): void => {
                if (inParams) {
                  onChange({
                    ...doc,
                    topology: { ...(topology ?? {}), params: { ...params, [field.name]: v } },
                  });
                } else {
                  onChange({ ...doc, topology: { ...(topology ?? {}), [field.name]: v } });
                }
              };
              if (field.type === 'json') {
                return <Field key={field.name} field={field} value={value}
                  disabled={readOnly} onChange={set} />;
              }
              return <Field key={field.name} field={field} value={value}
                disabled={readOnly} onChange={set} />;
            })}
          </div>
        </div>
      )}
      {/* Every other family's knobs, named but read-only: a knob that is only
          reachable by already knowing to switch families is a hidden one.
          The names come from the same inventory, so nothing is restated. */}
      {!controlsOnly && data.topology.some((f) => f.kind !== familyKind) && (
        <details className="subtle">
          <summary>
            Other topologies — {data.topology.length - (family ? 1 : 0)} more, {label('topology')} controls
          </summary>
          <p className="muted">
            These are the engine's other topology families and every field each
            one accepts. Use the topology selector above to switch; the controls
            become editable then.
          </p>
          <div className="form-grid">
            {data.topology.filter((f) => f.kind !== familyKind).map((f) => (
              <div key={f.kind}>
                <div className="field-label">
                  {label(f.label)} <span className="muted">({f.kind})</span>
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {f.fields.map((field) => label(field.name)).join(' · ')}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
      {!controlsOnly && unknownFamily && (
        <p className="muted" role="note">
          Topology kind <code>{familyKind}</code> is not in the engine's knob
          inventory, so its fields are not rendered here. The engine still
          validates it on compile.
        </p>
      )}

      {!block && (
        <p className="muted">
          This draft's schema carries no control block, so fabric and router
          controls are not authorable.
        </p>
      )}
      {block && groups.map((group) => (
        <div key={group}>
          <h4>{label(group)}</h4>
          <div className="form-grid">
            {controls.filter((c) => (c.group ?? 'other') === group).map((field) => (
              <Field key={field.name} field={field}
                value={readBlock(doc, block)[field.name]}
                disabled={readOnly}
                binds={!controlsOnly && field.binds ? `${field.binds.field} · ${field.binds.source}` : undefined}
                onChange={(v) => writeCtl(field.name, v)} />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}