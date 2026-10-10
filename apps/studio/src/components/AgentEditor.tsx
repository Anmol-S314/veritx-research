import { useState, type ReactElement } from 'react';
import { agentLabel } from './FabricCanvas';

/** The closed AgentKind vocabulary in model/compile_model.py, not IP templates. */
export const AGENT_KINDS = ['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port'] as const;
const DESCRIPTIONS: Record<string, string> = {
  compute_tile: 'A compute endpoint. Workload parallelism selects active participants separately; this is not a GPU/NPU performance model.',
  hbm_controller: 'A memory-controller endpoint. HBM capacity, banks, channels, and DRAM timing are not properties of this agent record.',
  nic: 'A network-interface endpoint. External link speed and NIC processing performance are not modeled by this agent record.',
  peripheral: 'A peripheral endpoint. Its device-specific behavior is not supplied by choosing this role.',
  ucie_port: 'A die-to-die endpoint. Choosing UCIe does not implement or qualify a UCIe protocol or PHY.',
};
const NUMERIC = [
  { key: 'data_width', label: 'Data width (bits)', value: 256, help: 'Declared interface payload width. This does not change fabric link width.' },
  { key: 'addr_width', label: 'Address width (bits)', value: 64, help: 'Declared address width. Configure decoded regions in the address map separately.' },
];

export default function AgentEditor({ doc, onChange, readOnly = false, selectedAgent, onSelectAgent, immutableGroups = false }: {
  doc: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  readOnly?: boolean;
  immutableGroups?: boolean;
  selectedAgent?: number;
  onSelectAgent?: (index: number) => void;
}): ReactElement {
  const agents = Array.isArray(doc.agents) ? doc.agents as Record<string, unknown>[] : [];
  const [selected, setSelected] = useState(0);
  const [newKind, setNewKind] = useState<string>('compute_tile');
  const choose = (value: number): void => { setSelected(value); onSelectAgent?.(value); };
  const index = Math.min(selectedAgent ?? selected, Math.max(0, agents.length - 1));
  const agent = agents[index];
  const kind = String(agent?.kind ?? '');
  const protocol = String(agent?.protocol ?? 'AXI');
  const protocols = ['AXI', 'CHI', 'APB', 'streaming', 'custom'];
  const knownKind = AGENT_KINDS.some(value => value === kind);
  const set = (key: string, value: unknown): void => onChange({
    ...doc, agents: agents.map((row, i) => i === index ? { ...row, [key]: value } : row),
  });
  const addressMap = (doc.address_map ?? {}) as Record<string, unknown>;
  const ranges = Array.isArray(addressMap.ranges) ? addressMap.ranges as Record<string, unknown>[] : [];
  const referenced = ranges.some(range => typeof range.target_agent_idx === 'number' && range.target_agent_idx >= index);
  const remove = (): void => {
    onChange({ ...doc, agents: agents.filter((_, i) => i !== index) });
    choose(Math.max(0, index - 1));
  };

  return <section className="agent-editor" aria-label="Agent properties">
    {agents.length > 0 && <label className="field">
      <span className="field-label">Agent group</span>
      <select aria-label="Agent group" value={index} onChange={e => choose(Number(e.target.value))}>
        {agents.map((row, i) => <option key={i} value={i}>Group {i + 1} · {agentLabel(String(row.kind))} × {String(row.count ?? '—')}</option>)}
      </select>
    </label>}
    {agent ? <>
      <div className="form-grid">
        <label className="field">
          <span className="field-label">Agent type</span>
          <select aria-label="Agent type" value={kind} disabled={readOnly} onChange={e => set('kind', e.target.value)}>
            {!knownKind && <option value={kind}>Unsupported existing kind: {kind || 'not set'}</option>}
            {AGENT_KINDS.map(value => <option key={value} value={value}>{agentLabel(value)}</option>)}
          </select>
          <small className="muted">{DESCRIPTIONS[kind] ?? 'Choose a supported agent type. Existing intent has not been replaced.'}</small>
        </label>
        <label className="field">
          <span className="field-label">Instance count</span>
          <input aria-label="Instance count" type="number" min={1} step={1} disabled={readOnly} value={agent.count == null ? '' : String(agent.count)}
            onChange={e => set('count', e.target.value === '' ? null : Number(e.target.value))} />
          <small className="muted">Attached endpoints in this group. Topology capacity and workload parallelism are not resized automatically.</small>
        </label>
      </div>
      <p className="muted">These properties apply to all {String(agent.count ?? '—')} instances in this group. {immutableGroups ? 'V5 group bindings remain fixed; this editor changes group properties only.' : 'Add a separate group of the same type for different settings.'}</p>
      <details className="subtle">
        <summary>Interface properties · {protocol} · {String(agent.data_width ?? 256)}-bit data / {String(agent.addr_width ?? 64)}-bit address</summary>
        <div className="form-grid">
          {NUMERIC.map(field => <label className="field" key={field.key}>
            <span className="field-label">{field.label}</span>
            <input aria-label={field.label} type="number" min={8} step={1} disabled={readOnly}
              value={agent[field.key] === null ? '' : String(agent[field.key] ?? field.value)}
              onChange={e => set(field.key, e.target.value === '' ? null : Number(e.target.value))} />
            <small className="muted">{field.help}</small>
          </label>)}
          <label className="field">
            <span className="field-label">Interface protocol</span>
            <select aria-label="Interface protocol" value={protocols.includes(protocol) ? protocol : '__custom'} disabled={readOnly}
              onChange={e => { if (e.target.value !== '__custom') set('protocol', e.target.value); }}>
              {protocols.map(value => <option key={value} value={value}>{value}</option>)}
              {!protocols.includes(protocol) && <option value="__custom">Custom: {protocol}</option>}
            </select>
          </label>
          {(protocol === 'custom' || !protocols.includes(protocol)) && <label className="field">
            <span className="field-label">Custom protocol label</span>
            <input value={protocol} disabled={readOnly} onChange={e => set('protocol', e.target.value)} />
          </label>}
        </div>
        <p className="muted">These interface declarations are editable design intent. AXI/CHI/APB labels do not establish transaction simulation or protocol compliance.</p>
      </details>
      <details className="subtle">
        <summary>Clock and power domains{agent.clock_domain || agent.power_domain ? ` · ${[agent.clock_domain, agent.power_domain].filter(Boolean).join(' / ')}` : ''}</summary>
        <div className="form-grid">
          {(['clock_domain', 'power_domain'] as const).map(key => <label className="field" key={key}>
            <span className="field-label">{key === 'clock_domain' ? 'Clock domain' : 'Power domain'}</span>
            <input value={agent[key] == null ? '' : String(agent[key])} disabled={readOnly} placeholder="Unspecified"
              onChange={e => set(key, e.target.value === '' ? null : e.target.value)} />
          </label>)}
        </div>
        <p className="muted">Domain labels are intent, not CDC, power gating, isolation, or level-shifting implementation. Compile checks the exact domain configuration.</p>
      </details>
      <details className="subtle">
        <summary>What cannot be tuned here?</summary>
        <p className="muted">Per-instance credits, outstanding transactions, ordering rules, compute throughput, memory capacity/timings, and PPA are not supported agent properties. Router buffers and timing belong to Fabric; address regions belong to the address map.</p>
      </details>
      {!readOnly && <>
        <button type="button" className="btn btn-small btn-danger" disabled={referenced || immutableGroups} onClick={remove}>Remove agent group</button>
        {referenced && <p className="muted">Remove or reassign affected address regions first. Group indexes are not remapped automatically.</p>}
      </>}
    </> : <p className="muted">No agents declared. Choose an agent type to add.</p>}
    {immutableGroups && <p className="muted">V5 group indexes are immutable here. Base edits never add, remove or remap extension bindings.</p>}
    {!readOnly && !immutableGroups && <div className="agent-editor-add">
      <label className="field"><span className="field-label">Agent type to add</span>
        <select aria-label="Agent type to add" value={newKind} onChange={e => setNewKind(e.target.value)}>
          {AGENT_KINDS.map(value => <option key={value} value={value}>{agentLabel(value)}</option>)}
        </select>
      </label>
      <button type="button" className="btn btn-small" onClick={() => {
        onChange({ ...doc, agents: [...agents, { kind: newKind, count: 1, data_width: 256, addr_width: 64,
          protocol: 'AXI', clock_domain: null, power_domain: null }] });
        choose(agents.length);
      }}>Add agent group</button>
    </div>}
  </section>;
}
