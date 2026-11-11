import { useEffect, useMemo, useState } from 'react';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { gateway, gatewayReason } from './gateway';
import {
  accessMatrix, addressCoverage, agentsFromRequest, agentsToRequest, autoMapWindows,
  emptyWindow, exactMatches, exactOrZero, formatBytes, formatHex, formatHexBig, hasUnsavedAgentMap, parseAddressBigInt, parseSizeBigInt,
  targetCoverage, validateWindows, windowsFromRequest, windowsToRequest,
  type AddressWindow, type AgentGroup,
} from './agentMap';
import { buildFabricAnalysis, decodeGroup } from './fabricAnalysis';
import { Assumptions, Badge, Button, Dialog, Empty, Field, Icon, Inspector, Notice, PageLink, Properties, Section } from './ui';

const PROTOCOLS = ['AXI', 'AXI4', 'AXI5', 'CHI.E', 'CHI.B', 'TileLink-UH', 'UCIe', 'Srota Native Stream'];
const TARGET_KINDS = ['hbm_controller', 'ucie_port', 'peripheral', 'nic'];
type Tab = 'agents' | 'windows' | 'matrix' | 'controls';
type Busy = 'validate' | 'save' | 'compile' | null;

const clone = <T,>(value: T): T => structuredClone(value);
type AgentMapSnapshot = { agents: AgentGroup[]; windows: AddressWindow[] };

const bigintReplacer = (_key: string, value: unknown): unknown =>
  typeof value === 'bigint' ? { __bigint: value.toString(10) } : value;

const bigintReviver = (_key: string, value: unknown): unknown =>
  value && typeof value === 'object' && typeof (value as { __bigint?: unknown }).__bigint === 'string'
    ? BigInt((value as { __bigint: string }).__bigint)
    : value;

function readAgentMapSnapshot(data: LoadedProject, key: string): AgentMapSnapshot {
  try {
    const stored = sessionStorage.getItem(key);
    if (stored) {
      const snapshot = JSON.parse(stored, bigintReviver) as Partial<AgentMapSnapshot>;
      if (Array.isArray(snapshot.agents) && Array.isArray(snapshot.windows)) {
        const windows = snapshot.windows.map(raw => ({
          ...raw,
          base: exactOrZero(raw.base, parseAddressBigInt),
          size: exactOrZero(raw.size, parseSizeBigInt),
          interleaveBytes: raw.interleaveBytes === null || raw.interleaveBytes === undefined
            ? null : exactOrZero(raw.interleaveBytes, parseSizeBigInt),
        }));
        return { agents: snapshot.agents, windows };
      }
    }
  } catch { /* A malformed or unavailable session snapshot falls back to the server draft. */ }
  const agents = agentsFromRequest(data.request);
  return { agents, windows: windowsFromRequest(data.request, agents) };
}

function HexInput({ value, onCommit, label }: { value: bigint; onCommit: (value: bigint) => void; label: string }) {
  const [text, setText] = useState(() => formatHexBig(value));
  useEffect(() => { setText(formatHexBig(value)); }, [value]);
  return <input aria-label={label} className="mono" value={text} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') (event.target as HTMLInputElement).blur(); }} onBlur={() => {
    const parsed = parseAddressBigInt(text);
    if (parsed === null) setText(formatHexBig(value));
    else onCommit(parsed);
  }} />;
}

function SizeInput({ value, onCommit, label }: { value: bigint; onCommit: (value: bigint) => void; label: string }) {
  const [text, setText] = useState(() => value.toString(10));
  useEffect(() => { setText(value.toString(10)); }, [value]);
  return <input aria-label={label} title={formatBytes(value)} value={text} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') (event.target as HTMLInputElement).blur(); }} onBlur={() => {
    const parsed = parseSizeBigInt(text);
    if (parsed === null || parsed <= 0n) setText(value.toString(10));
    else onCommit(parsed);
  }} />;
}

export function AgentFabricMap({ data, notify }: { data: LoadedProject; notify?: (message: string) => void }) {
  const { reload } = useProject();
  const snapshotKey = `srota-agent-map:v1:${data.detail.project.project_id}:${data.draftMeta?.revisionToken ?? 'no-token'}`;
  const [tab, setTab] = useState<Tab>('windows');
  const [agents, setAgents] = useState<AgentGroup[]>(() => readAgentMapSnapshot(data, snapshotKey).agents);
  const [windows, setWindows] = useState<AddressWindow[]>(() => readAgentMapSnapshot(data, snapshotKey).windows);
  const [selectedWindow, setSelectedWindow] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<number | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [autoOpen, setAutoOpen] = useState(false);
  const [autoBase, setAutoBase] = useState('0x1000_0000');
  const [autoSize, setAutoSize] = useState('256 MiB');
  const [autoKinds, setAutoKinds] = useState<string[]>(['hbm_controller', 'ucie_port']);
  const [matrixFocus, setMatrixFocus] = useState<number | null>(null);

  useEffect(() => {
    const snapshot = readAgentMapSnapshot(data, snapshotKey);
    setAgents(snapshot.agents);
    setWindows(snapshot.windows);
    setSelectedWindow(null);
    setSelectedAgent(null);
    setMatrixFocus(null);
    setError('');
    setNotice('');
    // The revision token is the server's identity for the draft snapshot.
  }, [snapshotKey, data.request]);

  useEffect(() => {
    try {
      if (hasUnsavedAgentMap(agents, windows, data.request)) sessionStorage.setItem(snapshotKey, JSON.stringify({ agents, windows }, bigintReplacer));
      else sessionStorage.removeItem(snapshotKey);
    } catch { /* Session persistence is best-effort; the editor remains usable. */ }
  }, [snapshotKey, data.request, agents, windows]);

  const issues = useMemo(() => validateWindows(windows, agents), [windows, agents]);
  const blocking = issues.filter(issue => issue.severity === 'error');
  const coverage = useMemo(() => addressCoverage(windows), [windows]);
  const targets = useMemo(() => targetCoverage(agents, windows), [agents, windows]);
  const matrix = useMemo(() => accessMatrix(agents, windows), [agents, windows]);
  const dirty = hasUnsavedAgentMap(agents, windows, data.request);
  const savedDraftPendingCompile = data.draftMeta?.dirty === true;
  const decode = decodeGroup(data.compileResult);
  const analysis = useMemo(() => buildFabricAnalysis({
    ...(data.request ?? {}),
    agents: agentsToRequest(agents),
    address_map: { ranges: windowsToRequest(windows) },
  }, data.topology, data.compileResult), [data.request, data.topology, data.compileResult, agents, windows]);
  const targetWindows = matrixFocus === null ? [] : windows.filter(window => window.targetAgentIdx === matrixFocus);
  const selected = windows.find(window => window.id === selectedWindow) ?? null;
  const selectedIndex = selected ? windows.findIndex(window => window.id === selected.id) : -1;
  const selectedLabel = selected ? (selected.name.trim() || `window ${selectedIndex + 1}`) : '';
  const windowIssues = selected ? issues.filter(issue => issue.window === selectedLabel) : [];
  const autoSizeBytes = parseSizeBigInt(autoSize);
  const autoBaseValue = parseAddressBigInt(autoBase);
  const autoValid = autoBaseValue !== null && autoSizeBytes !== null && autoSizeBytes > 0n && autoKinds.length > 0;
  const autoProposal = useMemo(() => autoValid && autoBaseValue !== null && autoSizeBytes !== null
    ? autoMapWindows(agents, { base: autoBaseValue, size: autoSizeBytes, targetKinds: autoKinds })
    : [], [agents, autoBaseValue, autoKinds, autoSizeBytes, autoValid]);
  const autoLastEnd = autoProposal.reduce((end, window) => (window.base + window.size > end ? window.base + window.size : end), 0n);
  const autoAvailable = agents.some(agent => TARGET_KINDS.includes(agent.kind));
  const currentRevision = data.detail.active_revision_id;
  const attachedSeats = (agent: AgentGroup, index: number): number =>
    data.topology?.endpoints.filter(endpoint => endpoint.kind === agent.kind
      && (endpoint.group_index === undefined || endpoint.group_index === index)).length ?? 0;
  const topologyIntent = (data.request?.topology ?? {}) as Record<string, any>;
  const controls = (data.request?.noc_controls ?? data.request?.noc_config ?? {}) as Record<string, any>;

  const updateAgent = (index: number, patch: Partial<AgentGroup>) => {
    setAgents(current => current.map((agent, position) => position === index ? { ...agent, ...patch } : agent));
    setNotice('');
  };
  const updateWindow = (id: string, patch: Partial<AddressWindow>) => {
    setWindows(current => current.map(window => window.id === id ? { ...window, ...patch } : window));
    setNotice('');
  };
  const addWindow = () => {
    const target = Math.min(Math.max(0, windows.length ? windows[windows.length - 1].targetAgentIdx : 0), Math.max(0, agents.length - 1));
    const group = agents[target];
    const next = {
      ...emptyWindow(target),
      selectionPolicy: group && group.count > 1 ? 'FIXED_INSTANCE' as const : null,
      targetInstanceIndex: group && group.count > 1 ? 0 : null,
    };
    setWindows(current => [...current, next]);
    setSelectedWindow(next.id);
    setTab('windows');
  };
  const removeWindow = (id: string) => {
    setWindows(current => current.filter(window => window.id !== id));
    if (selectedWindow === id) setSelectedWindow(null);
  };
  const autoMap = () => {
    if (!autoValid) return;
    const next = autoMapWindows(agents, { base: autoBaseValue, size: autoSizeBytes, targetKinds: autoKinds });
    setWindows(next);
    setSelectedWindow(next[0]?.id ?? null);
    setAutoOpen(false);
    setTab('windows');
    notify?.(`Placed ${next.length} address window(s) from ${formatHexBig(autoBaseValue)}. Review and compile; nothing is inferred from a model name.`);
  };

  const buildDraft = () => {
    const next = clone((data.request ?? {}) as Record<string, unknown>);
    next.agents = agentsToRequest(agents);
    next.address_map = { ranges: windowsToRequest(windows) };
    return next;
  };

  const save = async (compile: boolean) => {
    if (busy) return;
    if (blocking.length) { setError(`Fix ${blocking.length} blocking address issue(s) before saving.`); return; }
    setBusy('validate'); setError(''); setNotice('');
    let savedDraft = false;
    try {
      const next = buildDraft();
      const topologyDoc = next.topology as Record<string, unknown> | undefined;
      const preview = topologyDoc
        ? await gateway.topologyPreview(data.detail.project.project_id, next, topologyDoc)
        : { request: next };
      const canonical = (preview.request ?? next) as Record<string, unknown>;
      setBusy('save');
      const current = await gateway.projectDraft(data.detail.project.project_id);
      if (data.draftMeta?.revisionToken && current.revisionToken !== data.draftMeta.revisionToken) throw new Error('Draft changed on the server. Reload and review before saving.');
      const saved = await gateway.putDraft(data.detail.project.project_id, canonical, data.draftMeta?.revisionToken);
      if (!saved.revisionToken) throw new Error('The gateway returned no saved draft version. Reopen this project before compiling.');
      savedDraft = true;
      if (compile) {
        setBusy('compile');
        await gateway.compileProject(data.detail.project.project_id, saved.revisionToken);
      }
      setNotice(compile ? 'Address map saved and compiled. The revision now carries the resolved decode table.' : 'Address map saved. Compile to materialise the revision and its decode table.');
      notify?.(compile ? 'Agent address map compiled into a new revision.' : 'Agent address map saved to the draft.');
      reload();
    } catch (caught) {
      setError(`${savedDraft ? 'Draft saved; compilation did not finish. ' : ''}${gatewayReason(caught)}`);
      if (savedDraft) reload();
    } finally {
      setBusy(null);
    }
  };

  if (!data.request) return <Empty title="No draft request">Load a gateway project with an editable draft to map its agents.</Empty>;
  const schemaVersion = Number(data.request.schema_version ?? 4);
  if (schemaVersion >= 5) return <Empty title="Schema-v5 draft">
    This page edits the v4 <code>agents</code> and <code>address_map</code> blocks. This draft nests the design under <code>base_v4</code>; editing it here would write fields the v5 parser refuses. Open the schema-v5 authoring surface instead. The Fabric Analysis page reads <code>base_v4</code> read-only.
  </Empty>;

  const tabButton = (id: Tab, label: string) => <button type="button" className={tab === id ? 'active' : ''} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>;

  return <div className="view-layout"><div className="view-main">
    <div className="toolbar">
      <div className="segmented" role="group" aria-label="Agent fabric map sections">
        {tabButton('windows', `Address windows · ${windows.length}`)}
        {tabButton('agents', `Agents · ${agents.length}`)}
        {tabButton('matrix', 'Reachability')}
        {tabButton('controls', 'Control reach')}
      </div>
      <div className="actions">
        <Badge tone={dirty || savedDraftPendingCompile ? 'amber' : 'green'}>{dirty ? 'Unsaved edits' : savedDraftPendingCompile ? 'Saved draft · compile pending' : data.draftMeta?.dirty === false ? 'Matches active revision' : 'Draft loaded'}</Badge>
        <Button onClick={() => setAutoOpen(true)} disabled={!!busy || !autoAvailable} title={autoAvailable ? undefined : 'No declared agent group is a target kind (hbm_controller, ucie_port, peripheral, nic).'}><Icon name="plus" />Auto-map targets</Button>
        <Button onClick={() => save(false)} disabled={!!busy || !dirty || blocking.length > 0}>{busy === 'save' || busy === 'validate' ? 'Saving…' : 'Save draft'}</Button>
        <Button primary onClick={() => save(true)} disabled={!!busy || blocking.length > 0}>{busy === 'compile' ? 'Compiling…' : 'Save & compile'}</Button>
      </div>
    </div>
    {error && <Notice tone="red">{error}</Notice>}
    {notice && <Notice tone="blue">{notice}</Notice>}
    {!dirty && !savedDraftPendingCompile && currentRevision && <p className="meta-line">Active revision <span className="mono">{currentRevision}</span> carries the last compiled address map. Edit a window to create a draft change.</p>}
    {dirty && <Notice tone="amber">These local edits are not in the active revision. Save and compile before evaluating the fabric or generating RTL.</Notice>}
    {!dirty && savedDraftPendingCompile && <Notice tone="amber">The saved server draft differs from active revision <span className="mono">{currentRevision ?? '—'}</span>. Compiler and preview evidence below still belongs to that active revision; compile the saved draft to refresh it.</Notice>}
    {!data.request.topology && <Notice tone="amber">This draft has no typed topology intent. Address edits save through the legacy path and the compiler is the only validator; the static Srota shape, port-budget and island checks are unavailable.</Notice>}

    {tab === 'windows' && <>
      <Section title="System address windows" actions={<><Badge tone={blocking.length ? 'red' : 'green'}>{blocking.length ? `${blocking.length} blocking` : 'Schema-clean'}</Badge><Badge>{formatBytes(coverage.mappedBytes)} mapped</Badge><Button onClick={addWindow} disabled={!agents.length} title={agents.length ? undefined : 'Declare at least one agent group before adding a window.'}><Icon name="plus" />Add window</Button></>}>
        {windows.length === 0 ? <Empty title="No address window is declared">
          Target agents have no system address. Use <strong>Auto-map targets</strong> to place one fixed window per target instance, then review every base and size before compiling. No size is inferred from a model name.
        </Empty> : <>
          <div className="table-scroll"><table className="address-table"><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Target agent</th><th>Selection &amp; instance</th></tr></thead><tbody>
            {windows.map(window => {
              const target = agents[window.targetAgentIdx];
              const rowIssues = issues.filter(issue => issue.window === (window.name.trim() || `window ${windows.indexOf(window) + 1}`));
              return <tr key={window.id} className={`${selectedWindow === window.id ? 'selected' : ''} ${rowIssues.length ? 'window-row-invalid' : ''}`} onClick={() => setSelectedWindow(window.id)}>
                <td><div className="window-name-cell"><input aria-label={`Window name ${window.id}`} value={window.name} placeholder="HBM0" onChange={event => updateWindow(window.id, { name: event.target.value })} /><button type="button" className="icon-button" aria-label={`Remove window ${window.name || window.id}`} onClick={event => { event.stopPropagation(); removeWindow(window.id); }}><Icon name="close" /></button></div></td>
                <td><HexInput value={window.base} onCommit={value => updateWindow(window.id, { base: value })} label={`Window base ${window.id}`} /></td>
                <td><SizeInput value={window.size} onCommit={value => updateWindow(window.id, { size: value })} label={`Window size ${window.id}`} /><br /><small>{formatBytes(window.size)}</small></td>
                <td><select aria-label={`Window target ${window.id}`} value={window.targetAgentIdx} onChange={event => {
                  const targetAgentIdx = Number(event.target.value);
                  const group = agents[targetAgentIdx];
                  const needsSelection = !!group && group.count > 1;
                  updateWindow(window.id, {
                    targetAgentIdx,
                    selectionPolicy: needsSelection ? (window.selectionPolicy ?? 'FIXED_INSTANCE') : null,
                    targetInstanceIndex: needsSelection ? (window.targetInstanceIndex ?? 0) : null,
                  });
                }}>{agents.map((agent, index) => <option key={`${agent.kind}-${index}`} value={index}>{agent.kind} ({agent.count})</option>)}</select></td>
                <td><div className="window-selection-cell">
                  <select aria-label={`Window policy ${window.id}`} value={window.selectionPolicy ?? ''} onChange={event => {
                    const value = event.target.value;
                    updateWindow(window.id, {
                      selectionPolicy: value === 'FIXED_INSTANCE' || value === 'STRIPED' ? value : null,
                      targetInstanceIndex: value === 'FIXED_INSTANCE' ? 0 : null,
                      interleaveBytes: value === 'STRIPED' ? (window.size > 0n && (window.size & (window.size - 1n)) === 0n ? window.size : 4096n) : null,
                    });
                  }}>
                    <option value="" disabled={(target?.count ?? 1) > 1}>Group</option>
                    <option value="FIXED_INSTANCE">Fixed</option>
                    <option value="STRIPED">Striped</option>
                  </select>
                  {window.selectionPolicy === 'FIXED_INSTANCE'
                    ? <input aria-label={`Window instance ${window.id}`} type="number" min={0} max={Math.max(0, (target?.count ?? 1) - 1)} value={window.targetInstanceIndex ?? 0} onChange={event => updateWindow(window.id, { targetInstanceIndex: Math.max(0, Number(event.target.value)) })} />
                    : window.selectionPolicy === 'STRIPED'
                      ? <SizeInput value={window.interleaveBytes ?? 0n} onCommit={value => updateWindow(window.id, { interleaveBytes: value })} label={`Window interleave ${window.id}`} />
                      : <small className="muted">whole group</small>}
                </div></td>
              </tr>;
            })}
          </tbody></table></div>
          <div className="address-axis">
            <span className="mono">{formatHexBig(windows.reduce((low, window) => (window.base < low ? window.base : low), 0n))}</span>
            <span>{formatBytes(coverage.mappedBytes)} mapped · {formatBytes(coverage.overlapBytes)} overlapping · {windows.length} window(s)</span>
            <span className="mono">{formatHex(coverage.maxEnd)}</span>
          </div>
          <div className="address-rows">{windows.map(window => {
            const start = windows.reduce((low, item) => (item.base < low ? item.base : low), 0n);
            const end = coverage.maxEnd > start + 1n ? coverage.maxEnd : start + 1n;
            const span = Number(end - start) || 1;
            const left = (Number(window.base - start) / span) * 100;
            const width = Math.max(0.4, (Number(window.size) / span) * 100);
            return <div key={window.id} className="address-row">
              <button type="button" className="text-button mono" onClick={() => setSelectedWindow(window.id)}>{window.name || 'unnamed'}</button>
              <div className="address-track"><span className={`address-track-fill ${selectedWindow === window.id ? 'selected' : ''}`} style={{ left: `${left}%`, width: `${width}%` }} title={`${formatHex(window.base)} + ${formatBytes(window.size)}`} /></div>
              <small>{formatBytes(window.size)}</small>
            </div>;
          })}</div>
        </>}
      </Section>
      <Section title="Blocking checks" actions={<Badge tone={blocking.length ? 'red' : 'green'}>{blocking.length ? `${blocking.length} open` : 'None'}</Badge>}>
        {issues.length === 0 ? <p className="meta-line">No name, range, target, policy or overlap issue is open. The compiler still re-derives the decode table and may refuse attachment or routing separately.</p>
          : <div className="table-scroll"><table><thead><tr><th>Window</th><th>Severity</th><th>Code</th><th>Detail</th></tr></thead><tbody>
            {issues.map((issue, index) => <tr key={`${issue.code}-${index}`}><th>{issue.window}</th><td><Badge tone={issue.severity === 'error' ? 'red' : 'amber'}>{issue.severity}</Badge></td><td className="mono">{issue.code}</td><td>{issue.detail}</td></tr>)}
          </tbody></table></div>}
      </Section>
      <Assumptions rows={[
        ['Authority', 'The compile request is the only authority. These edits write `agents` and `address_map.ranges`; every other block is preserved verbatim.'],
        ['Schema limits', 'AddressRange carries name, base, size, target_agent_idx and an optional FIXED_INSTANCE or STRIPED selection. There is no per-initiator permission, firewall or protocol-attribute field.'],
        ['Decode semantics', 'The compiler resolves ranges to attached endpoints with IDENTITY transform and ERROR on unmatched. It refuses overlapping ranges, a non-power-of-two interleave and an unaligned striped base.'],
        ['Not claimed', 'A window is not a permission grant, a route, a transaction completion or a hardware qualification.'],
      ]} />
    </>}

    {tab === 'agents' && <>
      <Section title="Declared agent groups" actions={<Badge>{agents.reduce((sum, agent) => sum + agent.count, 0)} agent(s)</Badge>}>
        {agents.length === 0 ? <Empty title="No agent group is declared">Add agents in the workload/parallelism intent before mapping addresses.</Empty>
          : <div className="table-scroll"><table className="address-table"><thead><tr><th>Kind</th><th>Count</th><th>Attached seats</th><th>Data width</th><th>Address width</th><th>Protocol</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
            {agents.map((agent, index) => {
              const attached = attachedSeats(agent, index);
              return <tr key={`${agent.kind}-${index}`} className={selectedAgent === index ? 'selected' : ''} onClick={() => setSelectedAgent(index)}>
                <th className="mono">{agent.kind}</th>
                <td className="numeric">{agent.count}</td>
                <td><Badge tone={attached < agent.count ? 'red' : attached > agent.count ? 'amber' : 'green'}>{attached} / {agent.count}</Badge></td>
                <td><input aria-label={`${agent.kind} data width`} type="number" min={8} value={agent.data_width ?? ''} onChange={event => updateAgent(index, { data_width: event.target.value === '' ? undefined : Number(event.target.value) })} /></td>
                <td><input aria-label={`${agent.kind} address width`} type="number" min={8} value={agent.addr_width ?? ''} onChange={event => updateAgent(index, { addr_width: event.target.value === '' ? undefined : Number(event.target.value) })} /></td>
                <td><select aria-label={`${agent.kind} protocol`} value={agent.protocol ?? 'AXI'} onChange={event => updateAgent(index, { protocol: event.target.value })}>{PROTOCOLS.map(protocol => <option key={protocol}>{protocol}</option>)}{agent.protocol && !PROTOCOLS.includes(agent.protocol) && <option>{agent.protocol}</option>}</select></td>
                <td><input aria-label={`${agent.kind} clock domain`} value={agent.clock_domain ?? ''} placeholder="not declared" onChange={event => updateAgent(index, { clock_domain: event.target.value || null })} /></td>
                <td><input aria-label={`${agent.kind} power domain`} value={agent.power_domain ?? ''} placeholder="not declared" onChange={event => updateAgent(index, { power_domain: event.target.value || null })} /></td>
              </tr>;
            })}
          </tbody></table></div>}
      </Section>
      <Notice tone="amber">Count is the agent universe, not a per-page control. Change it in the workload parallelism intent; a count the topology cannot seat is refused by the compiler rather than silently trimmed.</Notice>
      <Section title="Agent interface coverage">
        <div className="table-scroll"><table><thead><tr><th>Target group</th><th>Instances</th><th>Covered by a window</th><th>Missing instances</th></tr></thead><tbody>
          {targets.length ? targets.map(target => <tr key={target.agentIdx}><th className="mono">{target.kind}</th><td className="numeric">{target.count}</td><td><Badge tone={target.missingInstances.length ? 'amber' : 'green'}>{target.covered} / {target.count}</Badge></td><td className="mono">{target.missingInstances.length ? target.missingInstances.join(', ') : 'none'}</td></tr>)
            : <tr><td colSpan={4}>No window targets a declared agent group.</td></tr>}
        </tbody></table></div>
      </Section>
      <Assumptions rows={[
        ['Editable here', 'data_width, addr_width, protocol, clock_domain and power_domain are real Agent fields and are written to the draft.'],
        ['Not editable here', 'count, kind and the topology shape are workload/placement intent; editing them in an address map would silently change the agent universe.'],
        ['Not claimed', 'The interface descriptor is a declaration. Protocol adaptation, CDC implementation and timing are not established by this page.'],
      ]} />
    </>}

    {tab === 'matrix' && <>
      <Section title="Address-window reachability" actions={<Badge>target totals · {matrix.cols.length} group(s)</Badge>}>
        <div className="table-scroll"><table className="mapping-table"><thead><tr><th scope="col">Rule set</th>{matrix.cols.map(col => <th key={col.agentIdx} scope="col" className="mono">{col.kind}</th>)}</tr></thead><tbody>
          <tr><th scope="row">All initiators</th>{matrix.cols.map((col, colIndex) => {
            const cell = matrix.cell(0, colIndex);
            return <td key={col.agentIdx}><button className={`matrix-cell ${matrixFocus === col.agentIdx ? 'selected' : ''}`} onClick={() => setMatrixFocus(col.agentIdx)} aria-label={`Inspect windows targeting ${col.kind}`}>{cell.windows ? <><strong>{cell.windows} window(s)</strong><br /><small>{formatBytes(cell.bytes)}</small></> : <span className="muted">no window</span>}</button></td>;
          })}</tr>
        </tbody></table></div>
        <p className="meta-line">One target-total row, because the compile schema has no per-initiator rule: every declared initiator sees the same address map. A cell records that a system-address window targets that group. It is not a permission, a firewall rule or an observed flow.</p>
      </Section>
      <Section title="Target instance coverage" actions={<Badge tone={targets.some(target => target.missingInstances.length) ? 'amber' : targets.length ? 'green' : 'neutral'}>{targets.length} target group(s)</Badge>}>
        <div className="table-scroll"><table><thead><tr><th>Target</th><th>Windows</th><th>Instances covered</th><th>Unaddressed instances</th></tr></thead><tbody>
          {targets.map(target => <tr key={target.agentIdx}><th className="mono">{target.kind}</th><td className="numeric">{target.windows}</td><td className="numeric">{target.covered} / {target.count}</td><td className="mono">{target.missingInstances.length ? target.missingInstances.join(', ') : 'none'}</td></tr>)}
        </tbody></table></div>
      </Section>
      {matrixFocus !== null && <Section title={`Windows targeting ${agents[matrixFocus]?.kind ?? 'agent'}`} actions={<Button onClick={() => { setTab('windows'); setSelectedWindow(targetWindows[0]?.id ?? null); }}>Open in address windows</Button>}>
        {targetWindows.length ? <div className="table-scroll"><table className="address-table"><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Selection</th></tr></thead><tbody>
          {targetWindows.map(window => <tr key={window.id}><th className="mono">{window.name}</th><td className="mono">{formatHex(window.base)}</td><td>{formatBytes(window.size)}</td><td>{window.selectionPolicy ?? 'group'}{window.selectionPolicy === 'FIXED_INSTANCE' ? ` · ${window.targetInstanceIndex}` : window.selectionPolicy === 'STRIPED' ? ` · ${formatBytes(window.interleaveBytes ?? 0n)}` : ''}</td></tr>)}
        </tbody></table></div> : <p className="meta-line">No window targets this group.</p>}
      </Section>}
      <Assumptions rows={[
        ['Derivation', 'Rows are initiator agent kinds (compute_tile, nic, peripheral); columns are target kinds (hbm_controller, ucie_port, peripheral) and any group named by a window.'],
        ['Meaning', 'A cell is an address-window count and byte total, not a permission or a measured flow.'],
        ['Missing from the schema', 'Per-initiator read/write/secure permissions and a firewall matrix have no compile-request representation. They cannot be written by this page without inventing a field the compiler would refuse.'],
      ]} />
    </>}

    {tab === 'controls' && <>
      <Section title="Declared fabric context" actions={<PageLink page="flow/optimize">Edit fabric controls</PageLink>}>
        <Properties rows={[
          ['Topology', `${String(topologyIntent.kind ?? '—')} · k=${String(topologyIntent.side_length ?? '—')} · c=${String(topologyIntent.concentration ?? '—')}`],
          ['MECS express', `row ${topologyIntent.mecs_row === true ? 'on' : 'off'} · column ${topologyIntent.mecs_col === true ? 'on' : 'off'}`],
          ['Path shapes', Array.isArray(topologyIntent.path_shapes) && topologyIntent.path_shapes.length ? topologyIntent.path_shapes.join(', ') : 'not declared'],
          ['VC policy', String(topologyIntent.vc_policy ?? 'not declared')],
          ['Side buffer', topologyIntent.sidebuf_enable === true ? `on · watermark ${String(topologyIntent.sidebuf_watermark ?? '—')}` : 'off / not declared'],
          ['Telemetry', `period ${String(topologyIntent.tel_period ?? '—')} · staleness ${String(topologyIntent.tel_latency ?? '—')}`],
          ['Link width', controls.link_width !== undefined && controls.link_width !== null ? `${String(controls.link_width)} b` : 'not declared'],
          ['Router buffer', controls.input_buffer_depth_flits_per_vc !== undefined && controls.input_buffer_depth_flits_per_vc !== null ? `${String(controls.input_buffer_depth_flits_per_vc)} flits / VC` : 'not declared'],
          ['Arbitration', String(controls.arbitration ?? 'compiler default (iSLIP)')],
        ]} />
        <p className="meta-line">These are the topology-independent controls the compiler actually accepts. Per-router overrides, per-port VC matrices and routing registers are not in the compile schema; the table below says which of the accepted controls reach the preview.</p>
        {analysis.checks.filter(check => check.group === 'rtl' && check.status !== 'PASS').map(check => <Notice key={check.id} tone={check.status === 'FAIL' ? 'red' : 'amber'}><strong>{check.title}.</strong> {check.detail}</Notice>)}
      </Section>
      <Section title="Control reach into RTL" actions={<Badge tone={analysis.counts.FAIL ? 'red' : analysis.counts.WARN ? 'amber' : 'green'}>{analysis.counts.PASS} pass · {analysis.counts.WARN} warn · {analysis.counts.FAIL} fail</Badge>}>
        <p className="meta-line">Draft values are compared with compiler and preview evidence for active revision <span className="mono">{currentRevision ?? '—'}</span>. “Compiled” means the compiler derives and checks the control; “Preview” means the certified topology-only emitter supports it—not that an RTL file exists for this revision. The System overview checks gateway-backed preview readiness.</p>
        <div className="table-scroll"><table><thead><tr><th>Control</th><th>Draft declaration</th><th>Compiler</th><th>Preview emitter</th><th>Status</th><th>Why</th></tr></thead><tbody>
          {analysis.rtlRows.map(row => <tr key={row.control}><th>{row.control}</th><td>{row.declared}</td><td>{row.compile}</td><td>{row.preview}</td><td><Badge tone={row.status === 'reaches-preview' ? 'green' : row.status === 'compiled-only' ? 'amber' : row.status === 'refused' ? 'red' : 'neutral'}>{row.status}</Badge></td><td>{row.note}<br /><small className="mono">{row.citation}</small></td></tr>)}
        </tbody></table></div>
        <div className="actions">
          <PageLink page="analysis/fabric">Open full fabric analysis</PageLink>
          <PageLink page="flow/optimize">Edit fabric controls</PageLink>
          <PageLink page="workloads/editor">Edit workload & agents</PageLink>
          <PageLink page="design/system">Check preview readiness</PageLink>
          <PageLink page="flow/run">Check final RTL handoff</PageLink>
        </div>
      </Section>
      <Section title="Resolved address decode" actions={<Badge tone={decode?.rows?.length ? 'green' : 'amber'}>{decode?.available ? `${decode.rows?.length ?? 0} row(s)` : 'not compiled'}</Badge>}>
        {decode?.rows?.length ? <div className="table-scroll"><table className="address-table"><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Target kind</th><th>Instance</th><th>Endpoint</th></tr></thead><tbody>
          {decode.rows.map((row, index) => <tr key={`${row.name ?? index}`}><th className="mono">{row.name ?? `range-${index}`}</th><td className="mono">{formatHex(row.base ?? 0)}</td><td>{formatBytes(row.size ?? 0)}</td><td>{row.target_agent_kind ?? '—'}</td><td className="numeric">{row.target_agent_instance ?? '—'}</td><td className="numeric">{row.target_endpoint_id ?? '—'}</td></tr>)}
        </tbody></table></div> : <p className="meta-line">No resolved decode rows. The active revision either has an empty address map or has not compiled these edits.</p>}
        <Properties rows={[
          ['Address transform', decode?.address_transform ?? '—'],
          ['Unmatched policy', decode?.unmatched_address_policy ?? '—'],
          ['Source', 'compileResult.groups.address_decode'],
          ['RTL decoder', analysis.rtlRows.find(row => row.control === 'Agent address map')?.status === 'reaches-preview' ? 'addr_decode.sv in the topology RTL preview (this build)' : 'Not emitted'],
        ]} />
      </Section>
      <Assumptions rows={[
        ['Why this page exists', 'The model can declare far more than the preview emitter can materialise. This table separates a compiled design from the RTL slice that exists today.'],
        ['Preview scope', 'The certified emitter is a topology-only 2-VC free/escape router preview. It is not a final Srota NoC and does not implement O1TURN-XY/MECS, the FIU, the side buffer or telemetry.'],
        ['Address decoder', 'The decoder is a real emitted module from the resolved AddressDecodeArtifact. It decodes addresses; it does not implement permissions, protocol adaptation or packet routing.'],
      ]} />
    </>}
  </div>
  <Inspector title={selected ? 'Address window' : tab === 'agents' ? 'Agent group' : 'Agent fabric map'}>
    {selected ? <>
      <h3 className="mono">{selected.name || 'unnamed window'}</h3>
      <Properties rows={[
        ['Base', <code>{formatHex(selected.base)}</code>],
        ['Inclusive end', <code>{formatHexBig(selected.base + (selected.size > 0n ? selected.size - 1n : 0n))}</code>],
        ['Size', formatBytes(selected.size)],
        ['Target', `${agents[selected.targetAgentIdx]?.kind ?? 'missing'} · ${agents[selected.targetAgentIdx]?.count ?? 0} instance(s)`],
        ['Selection', selected.selectionPolicy ?? 'group (legacy)'],
        ['Instance', selected.selectionPolicy === 'FIXED_INSTANCE' ? String(selected.targetInstanceIndex ?? 0) : '—'],
        ['Interleave', selected.selectionPolicy === 'STRIPED' ? formatBytes(selected.interleaveBytes ?? 0n) : '—'],
        ['Decode result', (() => { const row = decode?.rows?.find(candidate => exactMatches(candidate.base, selected.base) && exactMatches(candidate.size, selected.size)); return row ? `${row.target_agent_kind ?? 'target'} · endpoint ${row.target_endpoint_id ?? '—'}` : 'Not in the active revision'; })()],
      ]} />
      {windowIssues.length ? windowIssues.map((issue, index) => <Notice key={index} tone="red">{issue.detail}</Notice>) : <Notice tone="blue">No schema issue is open for this window.</Notice>}
      <Button onClick={() => { setWindows(current => current.filter(window => window.id !== selected.id)); setSelectedWindow(null); }} danger>Remove window</Button>
    </> : tab === 'agents' && selectedAgent !== null ? <>
      <h3 className="mono">{agents[selectedAgent]?.kind}</h3>
      <Properties rows={[
        ['Declared count', String(agents[selectedAgent]?.count ?? 0)],
        ['Attached seats', String(agents[selectedAgent] ? attachedSeats(agents[selectedAgent], selectedAgent) : 0)],
        ['Data width', `${agents[selectedAgent]?.data_width ?? '—'} b`],
        ['Address width', `${agents[selectedAgent]?.addr_width ?? '—'} b`],
        ['Protocol', agents[selectedAgent]?.protocol ?? '—'],
        ['Clock domain', agents[selectedAgent]?.clock_domain ?? 'not declared'],
        ['Power domain', agents[selectedAgent]?.power_domain ?? 'not declared'],
        ['Address windows', String(windows.filter(window => window.targetAgentIdx === selectedAgent).length)],
      ]} />
      <p className="meta-line">The interface descriptor is attached to every endpoint of this group; the compiler checks it against the topology seat.</p>
    </> : <>
      <Properties rows={[
        ['Project', data.detail.project.name],
        ['Active revision', currentRevision ?? 'none'],
        ['Agent groups', String(agents.length)],
        ['Address windows', String(windows.length)],
        ['Mapped union', formatBytes(coverage.mappedBytes)],
        ['Blocking issues', String(blocking.length)],
        ['Resolved decode', decode?.available ? `${decode.rows?.length ?? 0} row(s)` : 'not compiled'],
        ['Draft state', dirty ? 'Unsaved edits' : savedDraftPendingCompile ? 'Matches saved draft · compile pending' : 'Matches draft'],
      ]} />
      <PageLink page="analysis/fabric">Analyse routing, ports and RTL reach</PageLink>
      <PageLink page="design/addresses">Open the address map summary</PageLink>
    </>}
    <Section title="Related design view">
      <p className="meta-line">Check endpoint seats and physical connections in this revision’s fabric topology.</p>
      <PageLink page="design/fabric-topology">Inspect physical fabric topology</PageLink>
    </Section>
  </Inspector>
  {autoOpen && <Dialog title="Auto-map target address windows" onClose={() => setAutoOpen(false)}>
    <Notice tone="amber">This places one fixed-instance window per target instance. It uses the base and size you enter; it does not infer a size from a model name or a workload.</Notice>
    <div className="form-grid">
      <Field label="First base address" hint="48-bit or 64-bit hexadecimal; must be exactly representable."><input value={autoBase} onChange={event => setAutoBase(event.target.value)} /></Field>
      <Field label="Bytes per instance" hint="Accepts 256 MiB, 4GiB, 0x1000 or a byte count."><input value={autoSize} onChange={event => setAutoSize(event.target.value)} /></Field>
    </div>
    <Field label="Target agent kinds">
      <div className="actions">{TARGET_KINDS.map(kind => <label key={kind} className="check-chip"><input type="checkbox" checked={autoKinds.includes(kind)} onChange={() => setAutoKinds(current => current.includes(kind) ? current.filter(item => item !== kind) : [...current, kind])} />{kind}</label>)}</div>
    </Field>
    <Properties rows={[
      ['First aligned base', autoProposal[0] ? formatHex(autoProposal[0].base) : 'Invalid'],
      ['Bytes per instance', autoSizeBytes === null ? 'Invalid' : formatBytes(autoSizeBytes)],
      ['Instances to map', String(autoProposal.length)],
      ['Last end', autoLastEnd ? formatHex(autoLastEnd) : 'Invalid'],
      ['Replaces', `${windows.length} current window(s)`],
    ]} />
    {!autoValid && <Notice tone="red">Enter an exact base, a positive byte size and at least one target kind.</Notice>}
    {autoValid && autoProposal.length === 0 && <Notice tone="amber">No declared agent instance matches the selected target kinds. Choose a kind that exists in this draft.</Notice>}
    <div className="dialog-actions"><Button onClick={() => setAutoOpen(false)}>Cancel</Button><Button primary disabled={!autoValid || autoProposal.length === 0} onClick={autoMap}>Replace windows with this map</Button></div>
  </Dialog>}
  </div>;
}

export function agentMapSummary(request: unknown): { windows: number; bytes: bigint; targets: number } {
  const windows = windowsFromRequest(request);
  const coverage = addressCoverage(windows);
  return { windows: windows.length, bytes: coverage.mappedBytes, targets: new Set(windows.map(window => window.targetAgentIdx)).size };
}

export const AGENT_MAP_PURPOSE = 'Declare agent-level address windows and interface controls, then check what actually reaches the compiler and the RTL preview.';

export function AgentFabricMapEmpty() {
  return <Empty title="No gateway project is loaded">
    The agent address map edits a real compile request and writes a real draft. Load a project from <a href="#/shared/projects">Projects &amp; revisions</a> first; this page does not invent a local address map that the compiler never sees.
  </Empty>;
}

