import { useEffect, useState, type ReactElement } from 'react';
import { baseDocument, editableDocument, withBaseDocument } from '../canonicalDraft';
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

type ClockSourceRow = { id: string; kind: string; frequency_hz: number };
type ClockDomainRow = { id: string; source_id: string; frequency_hz: number; divider_num?: number; divider_den?: number };
type AgentRow = Record<string, unknown> & { clock_domain?: string | null };
const records = (value: unknown): Record<string, unknown>[] => Array.isArray(value)
  ? value.filter((row): row is Record<string, unknown> => row !== null && typeof row === 'object' && !Array.isArray(row)) : [];

function ClockDomainEditor({ doc, onChange, readOnly }: {
  doc: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void; readOnly?: boolean;
}): ReactElement {
  const sources = records(doc.clock_sources) as unknown as ClockSourceRow[];
  const domains = records(doc.clock_domains) as unknown as ClockDomainRow[];
  const base = baseDocument(doc);
  const agents = records(base.agents) as AgentRow[];
  const [sourceId, setSourceId] = useState('');
  const [sourceKind, setSourceKind] = useState<'PLL' | 'XTAL' | 'EXTERNAL' | 'DIVIDER'>('PLL');
  const [sourceHz, setSourceHz] = useState('');
  const [domainId, setDomainId] = useState('');
  const [domainSource, setDomainSource] = useState('');
  const [domainHz, setDomainHz] = useState('');
  const [dividerNum, setDividerNum] = useState('1');
  const [dividerDen, setDividerDen] = useState('1');
  const [editingDomain, setEditingDomain] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const updateRoot = (patch: Record<string, unknown>): void => onChange(editableDocument({ ...doc, ...patch }));
  const updateAgents = (nextAgents: AgentRow[]): void => onChange(editableDocument(withBaseDocument(doc, { ...base, agents: nextAgents })));
  const sourceFrequency = Number(sourceHz);
  const canAddSource = !readOnly && sourceId.trim() !== '' && !sources.some((source) => source.id === sourceId.trim())
    && Number.isSafeInteger(sourceFrequency) && sourceFrequency > 0;
  const domainFrequency = Number(domainHz);
  const numerator = Number(dividerNum);
  const denominator = Number(dividerDen);
  const referencedSource = sources.find((source) => source.id === domainSource);
  const numeratorProduct = referencedSource ? referencedSource.frequency_hz * denominator : NaN;
  const validRatio = Number.isSafeInteger(numeratorProduct) && Number.isSafeInteger(numerator) && numerator > 0
    && Number.isSafeInteger(denominator) && denominator > 0 && numeratorProduct % numerator === 0
    && numeratorProduct / numerator === domainFrequency;
  const canSaveDomain = !readOnly && domainId.trim() !== ''
    && (editingDomain === domainId.trim() || !domains.some((domain) => domain.id === domainId.trim()))
    && referencedSource !== undefined && Number.isSafeInteger(domainFrequency) && domainFrequency > 0 && validRatio;
  const saveDomain = (): void => {
    if (!canSaveDomain) return;
    const row: ClockDomainRow = { id: domainId.trim(), source_id: domainSource, frequency_hz: domainFrequency, divider_num: numerator, divider_den: denominator };
    const next = editingDomain
      ? domains.map((domain) => domain.id === editingDomain ? row : domain)
      : [...domains, row];
    updateRoot({ clock_domains: next });
    setEditingDomain(null); setDomainId(''); setDomainHz(''); setDividerNum('1'); setDividerDen('1');
    setMessage(`Saved clock domain ${row.id}.`);
  };
  const assignedReferences = (id: string): string[] => [
    ...agents.flatMap((agent, index) => agent.clock_domain === id ? [`agent group ${index}`] : []),
    ...records(doc.agent_intents).flatMap((intent, index) => intent.transaction_clock_domain === id ? [`agent intent ${index}`] : []),
    ...records(doc.crossings).flatMap((crossing, index) => crossing.src_clock === id || crossing.dst_clock === id ? [`crossing ${index}`] : []),
  ];
  return <details className="subtle" open>
    <summary>Clock-domain editor · local declarations and assignments</summary>
    <p className="muted">Creates explicit clock sources/domains and assigns base agent groups by domain ID. Exact frequency/divider ratios and safe deletion are checked locally; save still validates the full V5 root. No clock tree or timing execution is implied.</p>
    <fieldset disabled={readOnly}>
      <legend>Clock sources</legend>
      {sources.map((source) => {
        const usedBy = domains.filter((domain) => domain.source_id === source.id).map((domain) => domain.id);
        return <div className="row" key={source.id}>
          <code>{source.id}</code><span>{source.kind} · {source.frequency_hz} Hz</span>
          <button type="button" className="btn btn-small" disabled={usedBy.length > 0} aria-label={`delete clock source ${source.id}`} onClick={() => {
            updateRoot({ clock_sources: sources.filter((row) => row.id !== source.id) });
            setMessage(`Deleted clock source ${source.id}.`);
          }}>Delete source</button>
          {usedBy.length > 0 && <span className="muted">In use by domains: {usedBy.join(', ')}</span>}
        </div>;
      })}
      <div className="row">
        <label>Source ID <input aria-label="new clock source id" value={sourceId} onChange={(event) => setSourceId(event.target.value)} /></label>
        <label>Source kind <select aria-label="new clock source kind" value={sourceKind} onChange={(event) => setSourceKind(event.target.value as typeof sourceKind)}>
          {['PLL', 'XTAL', 'EXTERNAL', 'DIVIDER'].map((kind) => <option key={kind}>{kind}</option>)}
        </select></label>
        <label>Source frequency (Hz) <input aria-label="new clock source frequency" type="number" min={1} step={1} value={sourceHz} onChange={(event) => setSourceHz(event.target.value)} /></label>
        <button type="button" className="btn btn-small" disabled={!canAddSource} onClick={() => {
          updateRoot({ clock_sources: [...sources, { id: sourceId.trim(), kind: sourceKind, frequency_hz: sourceFrequency }] });
          setMessage(`Created clock source ${sourceId.trim()}.`); setSourceId(''); setSourceHz('');
        }}>Add clock source</button>
      </div>
    </fieldset>
    <fieldset disabled={readOnly}>
      <legend>Clock domains</legend>
      {domains.map((domain) => {
        const references = assignedReferences(domain.id);
        return <div className="row" key={domain.id}>
          <code>{domain.id}</code><span>{domain.frequency_hz} Hz · source {domain.source_id} · ÷{domain.divider_num ?? 1}/{domain.divider_den ?? 1}</span>
          <button type="button" className="btn btn-small" disabled={references.length > 0} aria-label={`delete clock domain ${domain.id}`} onClick={() => {
            updateRoot({ clock_domains: domains.filter((row) => row.id !== domain.id) });
            if (editingDomain === domain.id) setEditingDomain(null);
            setMessage(`Deleted clock domain ${domain.id}.`);
          }}>Delete domain</button>
          {references.length > 0 && <span className="muted">In use by {references.join(', ')}</span>}
          <button type="button" className="btn btn-small" onClick={() => {
            setEditingDomain(domain.id); setDomainId(domain.id); setDomainSource(domain.source_id);
            setDomainHz(String(domain.frequency_hz)); setDividerNum(String(domain.divider_num ?? 1)); setDividerDen(String(domain.divider_den ?? 1));
          }}>Edit metadata</button>
        </div>;
      })}
      <div className="row">
        <label>Domain ID <input aria-label="clock domain id" value={domainId} disabled={editingDomain !== null} onChange={(event) => setDomainId(event.target.value)} /></label>
        <label>Source <select aria-label="clock domain source" value={domainSource} onChange={(event) => setDomainSource(event.target.value)}>
          <option value="">Choose source</option>{sources.map((source) => <option key={source.id} value={source.id}>{source.id}</option>)}
        </select></label>
        <label>Frequency (Hz) <input aria-label="clock domain frequency" type="number" min={1} step={1} value={domainHz} onChange={(event) => setDomainHz(event.target.value)} /></label>
        <label>Divider numerator <input aria-label="clock divider numerator" type="number" min={1} step={1} value={dividerNum} onChange={(event) => setDividerNum(event.target.value)} /></label>
        <label>Divider denominator <input aria-label="clock divider denominator" type="number" min={1} step={1} value={dividerDen} onChange={(event) => setDividerDen(event.target.value)} /></label>
        <button type="button" className="btn btn-small" disabled={!canSaveDomain} onClick={saveDomain}>{editingDomain ? 'Save clock domain' : 'Add clock domain'}</button>
        {editingDomain && <button type="button" className="btn btn-small" onClick={() => { setEditingDomain(null); setDomainId(''); }}>Cancel edit</button>}
      </div>
    </fieldset>
    <fieldset disabled={readOnly}>
      <legend>Agent clock-domain assignments</legend>
      {agents.map((agent, index) => {
        const current = typeof agent.clock_domain === 'string' ? agent.clock_domain : '';
        return <label key={index} className="field">{String(agent.kind ?? `agent group ${index}`)} group {index}
          <select aria-label={`clock assignment group ${index}`} value={current} onChange={(event) => {
            const nextAgents = [...agents];
            nextAgents[index] = { ...agent, clock_domain: event.target.value || null };
            updateAgents(nextAgents);
          }}>
            <option value="">Unassigned</option>
            {current && !domains.some((domain) => domain.id === current) && <option value={current}>{current} (undeclared)</option>}
            {domains.map((domain) => <option key={domain.id} value={domain.id}>{domain.id}</option>)}
          </select>
        </label>;
      })}
      {agents.length === 0 && <p className="muted">No base agent groups to assign.</p>}
    </fieldset>
    {message && <p role="status">{message}</p>}
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
    <ClockDomainEditor doc={doc} onChange={onChange} readOnly={readOnly} />
    {(Object.keys(DECLARATIONS) as (keyof typeof DECLARATIONS)[]).map(field =>
      <Declaration key={field} field={field} guidance={DECLARATIONS[field]} doc={doc} onChange={onChange} readOnly={readOnly} />)}
    <details className="subtle"><summary>Migration provenance · read-only</summary><pre>{JSON.stringify(doc.migration_provenance, null, 2)}</pre></details>
  </section>;
}
