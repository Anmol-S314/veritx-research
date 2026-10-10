import { useEffect, useState, type ReactElement } from 'react';
import { editableDocument } from '../canonicalDraft';
import { parseExactJson } from '../strictJson';

const DECLARATIONS = {
  agent_intents: 'Group-index bindings; transaction_policy and transaction_clock_domain are explicit. interface_role currently refuses at ATTACHMENT.',
  clock_sources: 'Explicit id, kind (PLL/XTAL/EXTERNAL/DIVIDER) and exact integer frequency_hz.',
  clock_domains: 'Explicit id, source_id, frequency_hz and divider_num/divider_den; full-root validation checks exact ratios.',
  crossings: 'Explicit directed clocks, signal_kind and mechanism. ASYNC_FIFO requires explicit dimensions, pointer encoding and synchronizer stages; no mechanism is inferred.',
  access_policy: 'Existing AccessPolicyArtifact declaration with exact rules; permissions RW/RO/WO/DENY, address space GLOBAL/LOCAL. Apply removes this edited policy’s computed policy_hash; save recomputes it. Not firewall hardware.',
  sideband_interfaces: 'Explicit endpoints, direction and protocol records. Structural support is not sideband execution.',
  sideband_connections: 'Explicit interface references. Sideband execution is outside the abstract experiment envelope.',
  reset_channels: 'Explicit reset declarations are retained; compilation currently refuses at COMPOSE.',
  power_domains: 'Explicit power declarations are retained; compilation currently refuses at COMPOSE.',
} as const;

function Declaration({ field, guidance, doc, onChange, readOnly }: {
  field: keyof typeof DECLARATIONS; guidance: string; doc: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void; readOnly?: boolean;
}): ReactElement {
  const serialized = JSON.stringify(doc[field], null, 2) ?? '';
  const [text, setText] = useState(serialized);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setText(serialized); setError(null); }, [serialized]);
  const apply = (): void => {
    try {
      const value = parseExactJson(text);
      if (field === 'access_policy' ? value !== null && (typeof value !== 'object' || Array.isArray(value)) : !Array.isArray(value))
        throw new Error(field === 'access_policy' ? 'Declare an access policy object or null' : 'Declare a JSON list');
      const declaration = field === 'access_policy' && value !== null ? { ...value as Record<string, unknown> } : value;
      // Editing this declaration invalidates its computed envelope, not other extensions.
      if (field === 'access_policy' && declaration !== null) delete (declaration as Record<string, unknown>).policy_hash;
      onChange(editableDocument({ ...doc, [field]: declaration }));
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  };
  return <details className="subtle">
    <summary>{field.replace(/_/g, ' ')} · declaration JSON</summary>
    <p className="muted">{guidance}</p>
    <label className="field"><span className="field-label">{field}</span>
      <textarea aria-label={field} rows={8} value={text} readOnly={readOnly} onChange={e => setText(e.target.value)} />
    </label>
    {!readOnly && <button type="button" className="btn btn-small" disabled={text === serialized} onClick={apply}>Apply {field} declaration</button>}
    {error && <p className="bad" role="alert">{error}. Correct the JSON declaration and apply again.</p>}
  </details>;
}

export default function V5Declarations({ doc, onChange, readOnly }: {
  doc: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void; readOnly?: boolean;
}): ReactElement {
  return <section aria-label="V5 declarations">
    <h3>V5 declarations</h3>
    <p className="muted">No defaults or request mapping are inferred. Apply edits locally, then save to validate the full root,
      including references, enums and exact integers. See docs/INTENT-V5-CONTRACT.md and the addressed_memory_v5.json example.
      Declaration validation does not certify compilation, native simulation or hardware.</p>
    {(Object.keys(DECLARATIONS) as (keyof typeof DECLARATIONS)[]).map(field =>
      <Declaration key={field} field={field} guidance={DECLARATIONS[field]} doc={doc} onChange={onChange} readOnly={readOnly} />)}
    <details className="subtle"><summary>Migration provenance · read-only</summary><pre>{JSON.stringify(doc.migration_provenance, null, 2)}</pre></details>
  </section>;
}
