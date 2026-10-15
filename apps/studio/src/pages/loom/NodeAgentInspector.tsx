/** Per-node agent, port and address-window editor (tracker M2-15 / M2-16 / M2-19).
 *
 *  Agents are authored endpoint intent: an initiator, target or bidirectional
 *  agent with a protocol, capability tags, ports and (for targets) address
 *  windows. Every edit is one `set_agents` command, so it is undoable, and the
 *  canonical project validator owns the rules (protocol/width/window ranges and
 *  overlaps). This view never infers a vendor part or an execution result.
 *
 *  Every mutation reads the CURRENT store document by id, so several edits in
 *  one tick (e.g. two rapid "add window" clicks) compose instead of overwriting.
 */
import type { ReactElement } from 'react';
import {
  validateProject,
  type AgentCapability,
  type AgentPort,
  type AgentRole,
  type ProjectAgent,
} from '../../graph/project';
import type { GraphStore } from '../../graph/store';

const ROLES: AgentRole[] = ['initiator', 'target', 'bidirectional'];
const CAPABILITIES: AgentCapability[] = ['read', 'write', 'atomic', 'coherent', 'streaming'];
type Window = NonNullable<AgentPort['addressWindows']>[number];
const NEW_WINDOW: Window = { base: '0x0', size: '0x1000', permissions: ['read', 'write'] };

/** The next window base, placed after every existing window so a new window
 *  never overlaps one already authored (the validator refuses overlaps). */
export function nextWindowBase(windows: readonly Window[]): string {
  let end = 0n;
  for (const window of windows) {
    try {
      const stop = BigInt(window.base) + BigInt(window.size);
      if (stop > end) end = stop;
    } catch { /* a malformed window is reported by the validator, not here */ }
  }
  return `0x${end.toString(16)}`;
}

export function NodeAgentInspector({ store, nodeId }: { store: GraphStore; nodeId: string }): ReactElement {
  const agents = (store.doc.agents ?? []).filter((agent) => agent.nodeId === nodeId);

  const mutate = (change: (mine: ProjectAgent[]) => ProjectAgent[]): void => {
    const current = store.current().agents ?? [];
    const others = current.filter((agent) => agent.nodeId !== nodeId);
    const merged = [...others, ...change(current.filter((agent) => agent.nodeId === nodeId))];
    store.run({ type: 'set_agents', agents: merged.length > 0 ? merged : undefined });
  };
  const patchAgent = (agentId: string, patch: Partial<ProjectAgent>): void =>
    mutate((mine) => mine.map((agent) => (agent.id === agentId ? { ...agent, ...patch } : agent)));
  const patchPort = (agentId: string, portId: string, change: (port: AgentPort) => Partial<AgentPort>): void =>
    mutate((mine) => mine.map((agent) => (agent.id !== agentId ? agent : {
      ...agent,
      ports: agent.ports.map((port) => (port.id !== portId ? port : { ...port, ...change(port) })),
    })));

  const nextAgentId = (): string => {
    const used = new Set((store.current().agents ?? []).map((agent) => agent.id));
    let n = 1;
    while (used.has(`agent-${n}`)) n += 1;
    return `agent-${n}`;
  };
  const nextPortId = (agent: ProjectAgent): string => {
    const used = new Set(agent.ports.map((port) => port.id));
    let n = 1;
    while (used.has(`p${n}`)) n += 1;
    return `p${n}`;
  };
  const agentIssues = validateProject(store.doc).filter((issue) => issue.path.startsWith('$.agents'));

  return (
    <fieldset aria-label="Node agents" style={{ marginTop: 8 }}>
      <legend>Agents &amp; ports</legend>
      <button type="button" className="btn btn-small" onClick={() => mutate((mine) => [...mine, {
        id: nextAgentId(), nodeId, role: 'initiator', protocol: 'AXI4', capabilities: ['read', 'write'], ports: [],
      }])}>+ Agent</button>
      {agents.length === 0 && <p className="muted" style={{ fontSize: 12 }}>No authored agents on this node.</p>}
      {agents.map((agent) => (
        <div key={agent.id} style={{ borderTop: '1px solid var(--border)', paddingTop: 4, marginTop: 4 }}>
          <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <code>{agent.id}</code>
            <label>role
              <select aria-label={`agent role ${agent.id}`} value={agent.role}
                onChange={(e) => patchAgent(agent.id, { role: e.target.value as AgentRole })}>
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label>protocol
              <input aria-label={`agent protocol ${agent.id}`} defaultValue={agent.protocol} key={`${agent.id}-proto-${agent.protocol}`}
                onBlur={(e) => { const value = e.target.value.trim(); if (value && value !== agent.protocol) patchAgent(agent.id, { protocol: value }); }} />
            </label>
            <button type="button" className="btn btn-small" aria-label={`delete agent ${agent.id}`}
              onClick={() => mutate((mine) => mine.filter((a) => a.id !== agent.id))}>delete</button>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            {CAPABILITIES.map((capability) => (
              <label key={capability} style={{ fontSize: 12 }}>
                <input type="checkbox" aria-label={`agent capability ${capability} ${agent.id}`}
                  checked={agent.capabilities.includes(capability)}
                  onChange={(e) => patchAgent(agent.id, {
                    capabilities: e.target.checked
                      ? [...agent.capabilities, capability]
                      : agent.capabilities.filter((c) => c !== capability),
                  })} /> {capability}
              </label>
            ))}
          </div>
          <button type="button" className="btn btn-small" aria-label={`add port to ${agent.id}`}
            onClick={() => mutate((mine) => mine.map((a) => a.id !== agent.id ? a : {
              ...a,
              ports: [...a.ports, { id: nextPortId(a), role: a.role, protocol: a.protocol, dataWidth: 256, capabilities: ['read', 'write'] }],
            }))}>+ Port</button>
          {agent.ports.map((port) => (
            <div key={port.id} style={{ marginLeft: 8, marginTop: 4 }}>
              <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <code>{port.id}</code>
                <label>role
                  <select aria-label={`port role ${agent.id} ${port.id}`} value={port.role}
                    onChange={(e) => patchPort(agent.id, port.id, () => ({ role: e.target.value as AgentRole }))}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </label>
                <label>protocol
                  <input aria-label={`port protocol ${agent.id} ${port.id}`} defaultValue={port.protocol} key={`${agent.id}-${port.id}-proto-${port.protocol}`}
                    onBlur={(e) => { const value = e.target.value.trim(); if (value && value !== port.protocol) patchPort(agent.id, port.id, () => ({ protocol: value })); }} />
                </label>
                <label>data width
                  <input aria-label={`port data width ${agent.id} ${port.id}`} type="number" min={1} defaultValue={port.dataWidth} key={`${agent.id}-${port.id}-dw-${port.dataWidth}`}
                    onBlur={(e) => { const value = Math.max(1, Number(e.target.value) | 0); if (value !== port.dataWidth) patchPort(agent.id, port.id, () => ({ dataWidth: value })); }} />
                </label>
                <label>address width
                  <input aria-label={`port address width ${agent.id} ${port.id}`} type="number" min={1} defaultValue={port.addressWidth ?? ''} key={`${agent.id}-${port.id}-aw-${port.addressWidth ?? ''}`}
                    onBlur={(e) => patchPort(agent.id, port.id, () => ({ addressWidth: e.target.value.trim() === '' ? null : Math.max(1, Number(e.target.value) | 0) }))} />
                </label>
                <button type="button" className="btn btn-small" aria-label={`delete port ${agent.id} ${port.id}`}
                  onClick={() => patchAgent(agent.id, { ports: agent.ports.filter((p) => p.id !== port.id) })}>delete</button>
              </div>
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <button type="button" className="btn btn-small" aria-label={`add window ${agent.id} ${port.id}`}
                  onClick={() => patchPort(agent.id, port.id, (p) => ({
                    addressWindows: [...(p.addressWindows ?? []), { ...NEW_WINDOW, base: nextWindowBase(p.addressWindows ?? []), permissions: [...NEW_WINDOW.permissions] }],
                  }))}>+ Address window</button>
                {(port.addressWindows ?? []).map((window, windowIndex) => {
                  const patchWindow = (patch: Partial<Window>): void => patchPort(agent.id, port.id,
                    (p) => ({ addressWindows: (p.addressWindows ?? []).map((w, i) => (i === windowIndex ? { ...w, ...patch } : w)) }));
                  return (
                    <span className="row" key={`${port.id}-w${windowIndex}`} style={{ gap: 4, alignItems: 'center' }}>
                      <label>base
                        <input aria-label={`window base ${agent.id} ${port.id} ${windowIndex}`} defaultValue={window.base} key={`${agent.id}-${port.id}-w${windowIndex}-b-${window.base}`}
                          onBlur={(e) => { const value = e.target.value.trim(); if (value && value !== window.base) patchWindow({ base: value }); }} />
                      </label>
                      <label>size
                        <input aria-label={`window size ${agent.id} ${port.id} ${windowIndex}`} defaultValue={window.size} key={`${agent.id}-${port.id}-w${windowIndex}-s-${window.size}`}
                          onBlur={(e) => { const value = e.target.value.trim(); if (value && value !== window.size) patchWindow({ size: value }); }} />
                      </label>
                      {(['read', 'write'] as const).map((permission) => (
                        <label key={permission} style={{ fontSize: 12 }}>
                          <input type="checkbox" aria-label={`window ${permission} ${agent.id} ${port.id} ${windowIndex}`}
                            checked={window.permissions.includes(permission)}
                            onChange={(e) => patchWindow({
                              permissions: e.target.checked
                                ? [...window.permissions, permission]
                                : window.permissions.filter((p) => p !== permission),
                            })} /> {permission}
                        </label>
                      ))}
                      <button type="button" className="btn btn-small" aria-label={`delete window ${agent.id} ${port.id} ${windowIndex}`}
                        onClick={() => patchPort(agent.id, port.id,
                          (p) => ({ addressWindows: (p.addressWindows ?? []).filter((_, i) => i !== windowIndex) }))}>x</button>
                    </span>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      ))}
      {agentIssues.length > 0 && (
        <ul className="t-warn" role="status" aria-label="Agent validation issues" data-testid="agent-issues" style={{ fontSize: 12, margin: '4px 0 0', paddingLeft: 16 }}>
          {agentIssues.map((issue, i) => <li key={`${issue.path}-${i}`}>{issue.message}</li>)}
        </ul>
      )}
    </fieldset>
  );
}
