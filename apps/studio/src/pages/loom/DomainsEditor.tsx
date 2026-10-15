/** Domain authoring editor (tracker M3-11/M3-12 domain editors, M2-20 assign
 *  with inherit/override).
 *
 *  Declares the project's clock, reset and power domains and assigns them at
 *  two levels: a node default (the node's clock/resetDomain/powerDomain field)
 *  and an optional per-port override. A port field left unset INHERITS the node
 *  default; a set field OVERRIDES it. Every edit is one undoable command, and
 *  the canonical validator owns the rules — this editor reports its findings.
 *
 *  It reads and writes the LOCAL authoring graph only. There is no clock tree,
 *  no frequency closure and no UPF/power-intent artifact behind these values.
 */
import { useState, type ReactElement } from 'react';
import {
  validateProject, type ClockDomainV1, type DomainsConfigV1, type GraphNode,
  type PowerDomainV1, type ResetDomainV1,
} from '../../graph/project';
import {
  assignmentFieldOf, emptyDomains, listOf, nextDomainId, nodeFieldOf,
  nodeReferences, removeDomain, upsertDomain, setAssignmentField, assignmentOf,
  type DomainEntry, type DomainKind,
} from '../../graph/domains';
import type { GraphCommand } from '../../graph/history';
import type { GraphStore } from '../../graph/store';

const KIND_LABEL: Record<DomainKind, string> = { clocks: 'Clock', resets: 'Reset', powers: 'Power' };
const POLARITY = ['active_low', 'active_high'] as const;

export function DomainsEditor({ store }: { store: GraphStore }): ReactElement {
  const doc = store.doc;
  const domains: DomainsConfigV1 = doc.domains ?? emptyDomains();
  const [pickedNode, setPickedNode] = useState<string>(doc.nodes[0]?.id ?? '');
  const current = doc.nodes.find((node) => node.id === pickedNode) ?? doc.nodes[0] ?? null;
  const nodeId = current?.id ?? '';
  const agents = (doc.agents ?? []).filter((agent) => agent.nodeId === nodeId);
  const issues = validateProject(doc).filter((issue) => issue.path.startsWith('$.domains'));

  const write = (next: DomainsConfigV1): void => { store.run({ type: 'set_domains', domains: next }); };

  const addDomain = (kind: DomainKind): void => {
    const id = nextDomainId(kind, listOf(domains, kind).map((domain) => domain.id));
    const entry = (kind === 'clocks'
      ? { id, frequencyHz: null, source: null }
      : kind === 'resets'
        ? { id, polarity: 'active_low', asynchronous: true, clockDomainId: undefined }
        : { id, nominalVoltageV: null, canPowerOff: false }) as DomainEntry;
    write(upsertDomain(domains, kind, entry));
  };
  const patchDomain = (kind: DomainKind, id: string, patch: Record<string, unknown>): void => {
    const found = listOf(domains, kind).find((domain) => domain.id === id);
    if (!found) return;
    write(upsertDomain(domains, kind, { ...found, ...patch } as DomainEntry));
  };
  const removeDomainById = (kind: DomainKind, id: string): void => {
    const commands: GraphCommand[] = [{ type: 'set_domains', domains: removeDomain(domains, kind, id) }];
    const refs = nodeReferences(doc, kind, id);
    if (refs.length > 0) {
      const field = nodeFieldOf(kind);
      commands.push({
        type: 'update_nodes',
        updates: refs.map((ref) => ({ id: ref, patch: { [field]: null } as Partial<GraphNode> })),
      });
    }
    store.run(commands.length === 1 ? commands[0] : { type: 'batch', commands });
  };
  const setNodeField = (field: 'clock' | 'resetDomain' | 'powerDomain', value: string): void => {
    if (!current) return;
    store.run({ type: 'update_node', id: current.id, patch: { [field]: value.trim() || null } as Partial<GraphNode> });
  };
  const setOverride = (portId: string, kind: DomainKind, value: string): void => {
    if (!current) return;
    write(setAssignmentField(domains, current.id, portId, assignmentFieldOf(kind), value || undefined));
  };

  const domainSelect = (kind: DomainKind, value: string | null | undefined, onChange: (value: string) => void, label: string): ReactElement => (
    <select aria-label={label} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
      <option value="">inherit / unset</option>
      {listOf(domains, kind).map((domain) => <option key={domain.id} value={domain.id}>{domain.id}</option>)}
    </select>
  );

  const list = (kind: DomainKind): ReactElement => {
    const entries = listOf(domains, kind);
    return (
      <fieldset aria-label={`${KIND_LABEL[kind]} domains`} style={{ margin: '4px 0' }}>
        <legend>{KIND_LABEL[kind]} domains</legend>
        <button type="button" className="btn btn-small" onClick={() => addDomain(kind)}>+ {KIND_LABEL[kind].toLowerCase()} domain</button>
        {entries.length === 0 && <p className="muted" style={{ fontSize: 12 }}>None declared.</p>}
        {entries.map((domain) => (
          <div className="row" key={domain.id} style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
            <code>{domain.id}</code>
            {kind === 'clocks' && <>
              <label>frequency (Hz)
                <input aria-label={`clock frequency ${domain.id}`} type="number" min={1} defaultValue={(domain as ClockDomainV1).frequencyHz ?? ''}
                  key={`${domain.id}-f-${(domain as ClockDomainV1).frequencyHz ?? ''}`}
                  onBlur={(e) => patchDomain('clocks', domain.id, { frequencyHz: e.target.value.trim() === '' ? null : Math.max(1, Number(e.target.value) || 1) })} />
              </label>
              <label>source
                <input aria-label={`clock source ${domain.id}`} defaultValue={(domain as ClockDomainV1).source ?? ''}
                  key={`${domain.id}-s-${(domain as ClockDomainV1).source ?? ''}`}
                  onBlur={(e) => patchDomain('clocks', domain.id, { source: e.target.value.trim() || null })} />
              </label>
            </>}
            {kind === 'resets' && <>
              <label>polarity
                <select aria-label={`reset polarity ${domain.id}`} value={(domain as ResetDomainV1).polarity ?? 'active_low'}
                  onChange={(e) => patchDomain('resets', domain.id, { polarity: e.target.value })}>
                  {POLARITY.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </label>
              <label style={{ fontSize: 12 }}>
                <input type="checkbox" aria-label={`reset asynchronous ${domain.id}`} checked={(domain as ResetDomainV1).asynchronous ?? false}
                  onChange={(e) => patchDomain('resets', domain.id, { asynchronous: e.target.checked })} /> asynchronous
              </label>
              <label>clock domain
                <select aria-label={`reset clock domain ${domain.id}`} value={(domain as ResetDomainV1).clockDomainId ?? ''}
                  onChange={(e) => patchDomain('resets', domain.id, { clockDomainId: e.target.value || undefined })}>
                  <option value="">unset</option>
                  {domains.clocks.map((clock) => <option key={clock.id} value={clock.id}>{clock.id}</option>)}
                </select>
              </label>
            </>}
            {kind === 'powers' && <>
              <label>voltage (V)
                <input aria-label={`power voltage ${domain.id}`} type="number" min={0.01} step={0.01} defaultValue={(domain as PowerDomainV1).nominalVoltageV ?? ''}
                  key={`${domain.id}-v-${(domain as PowerDomainV1).nominalVoltageV ?? ''}`}
                  onBlur={(e) => patchDomain('powers', domain.id, { nominalVoltageV: e.target.value.trim() === '' ? null : Math.max(0.01, Number(e.target.value) || 0.01) })} />
              </label>
              <label style={{ fontSize: 12 }}>
                <input type="checkbox" aria-label={`power can power off ${domain.id}`} checked={(domain as PowerDomainV1).canPowerOff ?? false}
                  onChange={(e) => patchDomain('powers', domain.id, { canPowerOff: e.target.checked })} /> can power off
              </label>
            </>}
            <button type="button" className="btn btn-small" aria-label={`remove ${KIND_LABEL[kind].toLowerCase()} domain ${domain.id}`}
              onClick={() => removeDomainById(kind, domain.id)}>remove</button>
          </div>
        ))}
      </fieldset>
    );
  };

  if (doc.nodes.length === 0) {
    return <p className="muted">Add a node before assigning domains.</p>;
  }

  return (
    <div>
      {list('clocks')}
      {list('resets')}
      {list('powers')}

      <fieldset aria-label="Node domain assignment" style={{ margin: '4px 0' }}>
        <legend>Node assignment</legend>
        <label>node
          <select aria-label="domain node" value={nodeId} onChange={(e) => setPickedNode(e.target.value)}>
            {doc.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
          </select>
        </label>
        {current && (
          <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
            <label>clock {domainSelect('clocks', current.clock, (v) => setNodeField('clock', v), 'node clock domain')}</label>
            <label>reset {domainSelect('resets', current.resetDomain, (v) => setNodeField('resetDomain', v), 'node reset domain')}</label>
            <label>power {domainSelect('powers', current.powerDomain, (v) => setNodeField('powerDomain', v), 'node power domain')}</label>
          </div>
        )}
        <p className="muted" style={{ fontSize: 12 }}>
          Node defaults apply to every port that does not override them.
        </p>
      </fieldset>

      <fieldset aria-label="Port domain overrides" style={{ margin: '4px 0' }}>
        <legend>Port overrides</legend>
        {agents.length === 0 && <p className="muted" style={{ fontSize: 12 }}>This node has no authored agent ports.</p>}
        {agents.map((agent) => (
          <div key={agent.id} style={{ marginTop: 4 }}>
            <code>{agent.id}</code>
            {agent.ports.map((port) => {
              const override = assignmentOf(domains, nodeId, port.id);
              return (
                <div className="row" key={port.id} style={{ gap: 8, flexWrap: 'wrap', marginLeft: 8, alignItems: 'center' }}>
                  <code>{port.id}</code>
                  <label>clock {domainSelect('clocks', override?.clockDomainId, (v) => setOverride(port.id, 'clocks', v), `port ${port.id} clock domain`)}</label>
                  <label>reset {domainSelect('resets', override?.resetDomainId, (v) => setOverride(port.id, 'resets', v), `port ${port.id} reset domain`)}</label>
                  <label>power {domainSelect('powers', override?.powerDomainId, (v) => setOverride(port.id, 'powers', v), `port ${port.id} power domain`)}</label>
                  {!override && <span className="muted" style={{ fontSize: 12 }}>inherits node</span>}
                </div>
              );
            })}
          </div>
        ))}
        <p className="muted" style={{ fontSize: 12 }}>
          A cleared field means inherit; the port takes the node default. Setting
          any field records an override.
        </p>
      </fieldset>

      {issues.length > 0 && (
        <ul className="t-warn" role="status" aria-label="Domain validation issues" data-testid="domain-issues" style={{ fontSize: 12, margin: 0, paddingLeft: 16 }}>
          {issues.map((issue, i) => <li key={`${issue.path}-${i}`}>{issue.path} — {issue.message}</li>)}
        </ul>
      )}
      <p className="muted" style={{ fontSize: 12 }}>
        Declares authored intent only. No clock tree, frequency closure or power
        intent (UPF) is modeled here.
      </p>
    </div>
  );
}
