import { useState, type ReactElement } from 'react';
import { BASE_REVISION, DOMAINS, DOMAIN_IDS, ROUTERS, canAttach, editDraft, hex, mappedBytes, overlaps, parseAddress, routeBetween, sizeLabel, type DomainId, type Endpoint, type PageId } from './model';
import { Badge, Button, Dialog, Field, Icon, Inspector, Notice, PageLink, Properties, Section, type ViewProps } from './ui';
import { FabricView } from './FabricView';
import { useProject } from './project';
import { AgentFabricMap, AgentFabricMapEmpty } from './AgentFabricMap';
import { EndpointSeatSections } from './EndpointSeats';
import { localEndpointSeats } from './localSeatModel';
import { localAgentGroups, localPhysical, localWindows } from './localDesign';
import { DomainSections } from './DomainSections';
import { PlacementSections } from './PlacementSections';
import { localAgents, localFloorplan, localPlacementAnnotations, localTopology, localWindowTargets } from './localDesign';
import { SeatCoverageTable } from './CoverageSections';
import { SystemDiagram } from './SystemDiagram';
import { AddressSections } from './AddressSections';
import { LiveAddresses, LiveCatalog, LiveDomains, LiveEndpoints, LiveMapping, LivePlacement, LiveSystem } from './LiveDesign';
import { LiveFabric } from './LiveFabric';
import { LocalRouteDiagram } from './LocalRouteDiagram';
import { DesignFlowPage } from './DesignFlow';
import { DesignEditor } from './DesignEditor';



// Design surfaces switch to live project data when a project is loaded from the gateway.
// Surfaces with no live equivalent keep the authored fixture and say so.
export function DesignViews(props: ViewProps & { page: PageId }) {
  const { project } = useProject();
  const [searchHandoff, setSearchHandoff] = useState<any>(() => {
    if (props.page !== 'design/fabric-topology') return null;
    try { const raw = sessionStorage.getItem('srota-workload-search-handoff'); return raw ? JSON.parse(raw) : null; } catch { return null; }
  });
  const handoffReference = searchHandoff && <Notice tone="amber">
    <div className="handoff-reference">
      <div>
        <strong>Explore reference: {searchHandoff.selected?.topology ?? 'topology not recorded'} · {searchHandoff.selected?.request?.vc_buf_size ?? '?'} flits/VC.</strong>{' '}
        Not applied to this project.
        <details className="inline-details">
          <summary>Reference details</summary>
          <Properties rows={[[ 'Workload', searchHandoff.workload?.label ?? searchHandoff.workload?.workload_id ?? 'Not recorded' ], ['P95 / throughput', `${searchHandoff.selected?.latency ?? 'Unavailable'} cycles · ${searchHandoff.selected?.throughput ?? 'Unavailable'} packets/cycle`], ['Modeled power / area / replay energy', `${searchHandoff.selected?.power ?? 'Unavailable'} W · ${searchHandoff.selected?.area ?? 'Unavailable'} mm² · ${searchHandoff.selected?.energy ?? 'Unavailable'} pJ`], ['Evidence source', `${searchHandoff.selected?.source ?? 'Not recorded'} · ${searchHandoff.selected?.log ?? 'log unavailable'}`]]} />
          {searchHandoff.selected?.model?.limitations && <p>{searchHandoff.selected.model.limitations}</p>}
          <details><summary>Exact search request</summary><pre className="code-preview">{JSON.stringify(searchHandoff.selected?.request, null, 2)}</pre></details>
        </details>
      </div>
      <Button onClick={() => { sessionStorage.removeItem('srota-workload-search-handoff'); setSearchHandoff(null); }}>Dismiss</Button>
    </div>
  </Notice>;
  const loaded = project.phase === 'loaded' ? project.data : null;
  if (loaded) {
    let live: ReactElement | null = null;
    switch (props.page) {
      case 'design/editor': live = <DesignEditor data={loaded} />; break;
      case 'design/flow': live = <DesignFlowPage data={loaded} />; break;
      case 'design/fabric-topology': live = <LiveFabric data={loaded} notify={props.notify} banner={handoffReference} />; break;
      case 'design/system': live = <LiveSystem data={loaded} />; break;
      case 'design/catalog': live = <LiveCatalog data={loaded} notify={props.notify} />; break;
      case 'design/endpoints': live = <LiveEndpoints data={loaded} />; break;
      case 'design/mapping': live = <LiveMapping data={loaded} />; break;
      case 'design/agent-map': live = <AgentFabricMap data={loaded} notify={props.notify} />; break;
      case 'design/addresses': live = <LiveAddresses data={loaded} />; break;
      case 'design/domains': live = <LiveDomains data={loaded} />; break;
      case 'design/placement': live = <LivePlacement data={loaded} />; break;
      default: break;
    }
    if (live) return live;
  }
  switch (props.page) {
    case 'design/editor': return <DesignEditor data={null} />;
    case 'design/flow': return <DesignFlowPage data={null} state={props.state} />;
    case 'design/fabric-topology': return <FabricView {...props} banner={handoffReference} />;
    case 'design/system': return <SystemView {...props} />;
    case 'design/catalog': return <CatalogView {...props} />;
    case 'design/endpoints': return <EndpointsView {...props} />;
    case 'design/mapping': return <MappingView {...props} />;
    case 'design/agent-map': return <AgentFabricMapEmpty />;
    case 'design/addresses': return <AddressView {...props} />;
    case 'design/domains': return <DomainsView {...props} />;
    case 'design/placement': return <PlacementView {...props} />;
    default: return null;
  }
}
function EndpointDetails({ state, navigate }: ViewProps) {
  const ep = state.draft.endpoints.find(e => e.id === state.selectedEndpoint) ?? state.draft.endpoints[0];
  return <><h3 className="mono">{ep.id}</h3><Badge tone="blue">{ep.source}</Badge><Properties rows={[
    ['Role', ep.role], ['Interface', ep.profile], ['Data width', `${ep.width} bits`], ['Domain', ep.domain], ['Physical attachment', `${ep.router} · Local`], ['Concentration', ep.concentrator ? `${ep.concentrator} · slot ${ep.slot}` : 'Dedicated local attachment'],
    ['Model description', 'Declared intent'], ['RTL integration', 'Not established'], ['ASIC / FPGA qualification', 'Not evaluated'],
  ]} /><div className="stack"><Button onClick={() => navigate('design/endpoints')}>Edit attachment<Icon name="arrow" /></Button><Button onClick={() => navigate('design/mapping')}>Inspect mapping</Button><Button onClick={() => navigate('verify/support')}>Inspect capability scope</Button></div></>;
}
function LocalDesignHandoff() {
  return <Section title="Design → compiler → RTL preview" actions={<Badge tone="amber">Local sample</Badge>}>
    <div className="design-handoff-track">
      <div className="design-handoff-step"><span>01 · Design</span><strong>Illustrative local draft</strong><small>Edits stay in this browser</small></div>
      <div className="design-handoff-connector" aria-hidden="true">→</div>
      <div className="design-handoff-step"><span>02 · Compiler</span><strong>Not compiled</strong><small>No active gateway revision</small></div>
      <div className="design-handoff-connector" aria-hidden="true">→</div>
      <div className="design-handoff-step"><span>03 · RTL preview</span><strong>Not assessed</strong><small>Preview readiness requires a loaded gateway project</small></div>
    </div>
    <div className="actions"><PageLink page="shared/projects" primary>Load a gateway project</PageLink><PageLink page="design/fabric-topology">Inspect the sample fabric</PageLink></div>
  </Section>;
}

function SystemView(props: ViewProps) {
  const { state, navigate } = props;
  const [selected, setSelected] = useState<string | null>(state.selectedEndpoint);
  const endpoints = state.draft.endpoints;
  const attachedRouters = new Set(endpoints.map(endpoint => endpoint.router));
  const crossings = endpoints.filter(endpoint => endpoint.domain !== 'clk_fabric');
  const agents = localAgents(state.draft);
  const topology = localTopology(state.draft);
  const selectedEndpoint = endpoints.find(endpoint => endpoint.id === selected) ?? null;
  return <div className="view-layout">
    <div className="view-main">
      <div className="toolbar">
        <span className="mono muted">4×4 mesh · 16 routers · {endpoints.length} endpoints on {attachedRouters.size} routers · {crossings.length} clock crossings · 128 b links · no arbitration declared · 4 obligations open</span>
        <div className="actions"><Button onClick={() => navigate('design/fabric-topology')}>Open fabric topology</Button></div>
      </div>

      <Section title="System composition" actions={<><span className="mono muted">{selectedEndpoint ? `${selectedEndpoint.id} selected` : 'Nothing selected'}</span><PageLink page="design/catalog"><Icon name="plus" />Add endpoint</PageLink></>}>
        <SystemDiagram agents={agents} workload={undefined} topology={topology} mapping={null} certificate={null} />
        <div className="legend">
          <span><i className="legend-dot blue" />Declared agent group</span>
          <span><i className="legend-dot green" />Attached endpoint seat</span>
          <span>Workload → agent groups → seats → fabric. Arrows are declared composition, not traffic or a floorplan.</span>
        </div>
      </Section>

      <Section title="Endpoint attachment">
        <div className="table-scroll"><table><thead><tr><th>Endpoint</th><th>Role</th><th>Interface</th><th>Clock domain</th><th>Attachment</th><th>Source</th></tr></thead><tbody>
          {endpoints.map(endpoint => <tr key={endpoint.id} className={endpoint.id === selected ? 'selected' : ''}>
            <th><button className="text-button mono" onClick={() => setSelected(endpoint.id)}>{endpoint.id}</button></th>
            <td>{endpoint.role}</td>
            <td>{endpoint.width}-bit<br /><small>{endpoint.profile}</small></td>
            <td className="mono">{endpoint.domain}</td>
            <td className="mono">{endpoint.router} / Local<br /><small>{endpoint.concentrator ? `${endpoint.concentrator} · slot ${endpoint.slot}` : 'Dedicated'}</small></td>
            <td><Badge>{endpoint.source}</Badge></td>
          </tr>)}
        </tbody></table></div>
      </Section>

      <LocalDesignHandoff />


    </div>
    <Inspector title={selected && selectedEndpoint ? `Endpoint ${selectedEndpoint.id}` : 'Selected endpoint'}>
      {selectedEndpoint ? <EndpointDetails {...props} /> : <p className="muted">Select an endpoint in the composition or the attachment table to inspect it.</p>}
    </Inspector>
  </div>;
}

const CATALOG = [
  { id: 'traffic_compute', name: 'Compute traffic model', kind: 'Model-only', profile: 'AXI interface intent', role: 'Initiator' as const, width: 128, note: 'Editable compute duration / traffic intent. No compute datapath is emitted.' },
  { id: 'memory_port', name: 'Memory controller interface', kind: 'Supplied IP', profile: 'Memory interface intent', role: 'Target' as const, width: 256, note: 'Supplied-controller integration boundary. No controller, PHY, or licence is included.' },
  { id: 'host_port', name: 'Host interface description', kind: 'Interface intent', profile: 'Host interface intent', role: 'Dual' as const, width: 128, note: 'Declared host transaction roles. Protocol bridge implementation is not established.' },
  { id: 'adapter', name: 'Network adapter profile', kind: 'Interface intent', profile: 'Adapter contract', role: 'Dual' as const, width: 128, note: 'A contract placeholder, not a qualified AXI/CHI adapter or RTL generator.' },
];
function CatalogView(props: ViewProps) {
  const { state, setState, notify } = props;
  const [query, setQuery] = useState(''); const [selected, setSelected] = useState(CATALOG[0]);
  const [adding, setAdding] = useState(false); const [id, setId] = useState('EP_NEW_0'); const [router, setRouter] = useState('R_0_1');
  const [domain, setDomain] = useState<DomainId>('clk_fabric');
  const validId = /^[A-Z][A-Z0-9_]{1,40}$/.test(id) && !state.draft.endpoints.some(e => e.id === id);
  const available = canAttach(state.draft.endpoints, id, router);
  const coverage = ['Model-only', 'Supplied IP', 'Interface intent'].map(source => {
    const entries = CATALOG.filter(entry => entry.kind === source);
    const instances = state.draft.endpoints.filter(endpoint => endpoint.source === source);
    return { source, entries, instances, routers: new Set(instances.map(endpoint => endpoint.router)).size };
  });
  const instanceTotal = state.draft.endpoints.length;
  function add() {
    if (!validId || !available) return;
    const endpoint: Endpoint = { id, role: selected.role, profile: selected.profile, width: selected.width, domain, router, source: selected.kind as Endpoint['source'] };
    setState(s => ({ ...editDraft(s, `Added agent group ${id} as one local endpoint seat. No compile or hardware generated.`, d => ({ ...d, endpoints: [...d.endpoints, endpoint] })), selectedEndpoint: id }));
    setAdding(false); notify(`${id} added as a local agent group. Hardware support remains unassessed.`);
  }
  return <div className="view-layout"><div className="view-main"><div className="toolbar"><label className="search-field"><Icon name="search" /><input aria-label="Search agent catalog" placeholder="Search block descriptions…" value={query} onChange={e => setQuery(e.target.value)} /></label><Badge>Local sample agent catalog · {CATALOG.length} entries</Badge><Button primary onClick={() => setAdding(true)}><Icon name="plus" />Add agent group</Button><PageLink page="design/endpoints">Inspect endpoint instances</PageLink></div><Section title="Agent descriptions"><div className="table-scroll"><table><thead><tr><th>Entry</th><th>Classification</th><th>Interface intent</th><th>RTL / target</th></tr></thead><tbody>{CATALOG.filter(c => `${c.name} ${c.kind}`.toLowerCase().includes(query.toLowerCase())).map(c => <tr key={c.id} className={selected.id === c.id ? 'selected' : ''}><th><button className="text-button" onClick={() => setSelected(c)}>{c.name}</button></th><td><Badge>{c.kind}</Badge></td><td>{c.width}-bit · {c.role}</td><td>Not established</td></tr>)}</tbody></table></div></Section><SeatCoverageTable title="Draft coverage by source classification" rows={coverage.map(row => ({ key: row.source, declared: row.entries.length, seats: row.instances.length }))} total={instanceTotal} declaredLabel="Catalog entries" seatsLabel="Draft endpoints" emptyTitle="No endpoints in this draft" emptyBody="Add an agent group from a description to populate the sample draft." actions={<Badge>{instanceTotal} endpoint instances</Badge>} /></div><Inspector title="Agent description"><h3>{selected.name}</h3><Badge tone="blue">{selected.kind}</Badge><p>{selected.note}</p><Properties rows={[[ 'Interface', selected.profile ], ['Data width', `${selected.width} bits`], ['Simulation backend', 'Not connected'], ['RTL generation', 'Not established for this sample'], ['Physical qualification', 'Not evaluated']]} /><Button primary onClick={() => setAdding(true)}><Icon name="plus" />Add from this description</Button><PageLink page="design/endpoints">Inspect endpoints</PageLink></Inspector>{adding && <Dialog title="Add agent group (local sample)" onClose={() => setAdding(false)}><Notice>This adds one local endpoint seat for the agent group. It does not compile, allocate addresses, grant access, or generate an adapter.</Notice><div className="form-grid"><Field label="Agent group identifier" hint="Uppercase letters, digits and underscores; unique in this draft."><input value={id} onChange={e => setId(e.target.value)} /></Field><Field label="Router attachment"><select value={router} onChange={e => setRouter(e.target.value)}>{ROUTERS.map(r => <option key={r}>{r}</option>)}</select></Field><Field label="Declared clock domain"><select value={domain} onChange={e => setDomain(e.target.value as DomainId)}>{DOMAIN_IDS.map(d => <option key={d}>{d}</option>)}</select></Field></div>{!validId && <Notice tone="red">Choose a valid, unique endpoint identifier.</Notice>}{!available && <Notice tone="red">This Local port is occupied. Select an unused port; adding a new concentrator is not implemented in this preview.</Notice>}<Properties rows={[[ 'Objects to add', id || 'Unnamed agent group' ], ['Source', selected.name], ['Address / permission', 'Unassigned; no implicit grant'], ['Generation support', 'Not established']]} /><div className="dialog-actions"><Button onClick={() => setAdding(false)}>Cancel</Button><Button primary disabled={!validId || !available} onClick={add}>Add group to draft</Button></div></Dialog>}</div>;
}
function EndpointsView(props: ViewProps) {
  const { state, setState, notify } = props;
  const [selectedRouter, setSelectedRouter] = useState<number | null>(null);
  const draftEndpoints = state.draft.endpoints;
  const ep = draftEndpoints.find(e => e.id === state.selectedEndpoint) ?? draftEndpoints[0];
  const [editing, setEditing] = useState(false); const [router, setRouter] = useState(ep.router);
  const [query, setQuery] = useState('');
  const valid = canAttach(draftEndpoints, ep.id, router);
  const model = localEndpointSeats(state.draft);
  const selectedSeat = draftEndpoints.findIndex(endpoint => endpoint.id === ep.id);
  const routerName = (id: number | null) => id === null ? 'No router selected' : ROUTERS[id];
  return <div className="view-layout"><div className="view-main"><Notice tone="blue"><strong>Local sample:</strong> attachment is browser draft intent. No compiler materializes these seats; a gateway project derives seats from the active revision.</Notice><div className="toolbar"><div className="actions"><PageLink page="design/catalog"><Icon name="plus" />Add agent group</PageLink><Badge>{new Set(draftEndpoints.map(e => e.router)).size} routers attached</Badge><Badge>{draftEndpoints.filter(e => e.concentrator).length} concentrated slots</Badge></div><div className="actions"><PageLink page="design/mapping">Inspect mapping</PageLink></div></div><EndpointSeatSections model={model} selected={selectedRouter} onSelect={setSelectedRouter} query={query} onQuery={setQuery} selectedEndpoint={selectedSeat} onSelectEndpoint={seat => { const endpoint = draftEndpoints[seat]; if (endpoint) setState(current => ({ ...current, selectedEndpoint: endpoint.id })); }} banner={selectedRouter !== null && <Notice tone="blue"><strong>{routerName(selectedRouter)}</strong> carries {model.endpoints.filter(e => e.router_id === selectedRouter).length} declared seat{model.endpoints.filter(e => e.router_id === selectedRouter).length === 1 ? '' : 's'} in this sample.</Notice>} /></div><Inspector title="Endpoint & attachment"><EndpointDetails {...props} /><Section title="Attachment intent"><Button primary onClick={() => { setRouter(ep.router); setEditing(true); }}>Review attachment edit</Button></Section></Inspector>{editing && <Dialog title={`Edit attachment — ${ep.id}`} onClose={() => setEditing(false)}><Field label="Target router / Local port"><select value={router} onChange={e => setRouter(e.target.value)}>{ROUTERS.map(r => <option key={r}>{r}</option>)}</select></Field>{!valid && <Notice tone="red">Port occupancy or concentrator membership blocks this edit. Shared concentrators cannot be split by moving one member.</Notice>}<Properties rows={[[ 'Before', `${ep.router} / Local` ], ['Proposed', `${router} / Local`], ['Consequences', 'Current draft changes; historical evaluations remain unchanged.'], ['Compatibility', 'Attachment intent only; no protocol or hardware qualification.']]} /><div className="dialog-actions"><Button onClick={() => setEditing(false)}>Cancel</Button><Button primary disabled={!valid || router === ep.router} onClick={() => { setState(s => editDraft(s, `Moved ${ep.id} attachment to ${router} locally.`, d => ({ ...d, endpoints: d.endpoints.map(e => e.id === ep.id ? { ...e, router } : e) }))); setEditing(false); notify('Attachment intent updated. Re-evaluation required.'); }}>Apply local attachment</Button></div></Dialog>}</div>;
}
function MappingView({ state, setState }: ViewProps) {
  const sources = state.draft.endpoints.filter(e => e.role !== 'Target'), targets = state.draft.endpoints.filter(e => e.role === 'Target');
  const [pair, setPair] = useState('EP_NPU_0:EP_HBM_0'); const [layer, setLayer] = useState('intended');
  const [sourceId, targetId] = pair.split(':'); const source = sources.find(e => e.id === sourceId) ?? sources[0], target = targets.find(e => e.id === targetId) ?? targets[0];
  const key = `${source.id}:${target.id}`, mapping = state.draft.mappings[key] ?? { intended: false, permission: 'deny' as const };
  const route = routeBetween(source.router, target.router);
  const update = (change: Partial<typeof mapping>) => setState(s => editDraft(s, `Changed ${key} ${Object.keys(change).join(', ')} intent.`, d => ({ ...d, mappings: { ...d.mappings, [key]: { ...mapping, ...change } } })));
  return <div className="view-layout"><div className="view-main"><div className="toolbar"><Field label="Displayed relationship"><select value={layer} onChange={e => setLayer(e.target.value)}><option value="intended">Intended mapping</option><option value="permission">Declared permission</option><option value="reachable">Logical reachability</option><option value="routing">Configured route</option></select></Field><Badge>{sources.length} initiators × {targets.length} targets</Badge></div><Section title="Independent relationship layers"><div className="table-scroll"><table className="mapping-table"><thead><tr><th scope="col">Initiator / target</th>{targets.map(t => <th key={t.id} className="mono" scope="col">{t.id}</th>)}</tr></thead><tbody>{sources.map(s => <tr key={s.id}><th scope="row" className="mono">{s.id}</th>{targets.map(t => { const k = `${s.id}:${t.id}`, m = state.draft.mappings[k], path = routeBetween(s.router, t.router); return <td key={k}><button className={`matrix-cell ${key === k ? 'selected' : ''}`} onClick={() => setPair(k)} aria-label={`Inspect ${s.id} to ${t.id}`}>{layer === 'intended' ? m?.intended ? 'Declared' : 'Unmapped' : layer === 'permission' ? m?.permission === 'allow' ? 'Allow intent' : 'Deny intent' : layer === 'reachable' ? `${path.length - 1} mesh hops` : 'Column, then row'}</button></td>; })}</tr>)}</tbody></table></div></Section><Section title="Configured route, not an observed packet path" actions={<Badge>{route.length - 1} hop{route.length - 1 === 1 ? '' : 's'}</Badge>}><LocalRouteDiagram route={route} source={source} target={target} /><div className="legend"><span><i className="legend-dot blue" />Source and configured route</span><span><i className="legend-dot green" />Target</span><span>Declared logical link</span></div><div className="route-path">{route.map((r, i) => <span key={r}>{i > 0 && <Icon name="arrow" />}<code>{r}</code></span>)}</div></Section></div><Inspector title="Selected endpoint pair"><h3 className="mono">{source.id}<br />to {target.id}</h3><Properties rows={[[ 'Mapping', mapping.intended ? 'Declared' : 'Unmapped' ], ['Permission intent', mapping.permission], ['Logical graph', 'Reachable'], ['Hardware route validation', 'Not evaluated'], ['Observed traffic', 'No artifact connected']]} /><Section title="Explicit intent edits"><label className="check-row"><input type="checkbox" checked={mapping.intended} onChange={e => update({ intended: e.target.checked })} />Declare intended relationship</label><Field label="Access permission intent"><select value={mapping.permission} onChange={e => update({ permission: e.target.value as 'allow' | 'deny' })}><option value="allow">Allow</option><option value="deny">Deny</option></select></Field></Section><PageLink page="design/addresses">Inspect address map</PageLink></Inspector></div>;
}
function AddressView({ state, setState, notify }: ViewProps) {
  const [selected, setSelected] = useState('NPU_WEIGHTS'); const [review, setReview] = useState(false); const [input, setInput] = useState('0xC0000000');
  const regions = state.draft.regions, region = regions.find(r => r.id === selected) ?? regions[0], conflicts = overlaps(regions), union = mappedBytes(regions);
  const base = parseAddress(input); const proposed = base === null ? regions : regions.map(r => r.id === 'PCIE_BAR0' ? { ...r, base } : r);
  const candidateRegion = proposed.find(r => r.id === 'PCIE_BAR0')!;
  const valid = base !== null && base + candidateRegion.size <= 2 ** 48 && !overlaps(proposed).some(o => o.a === 'PCIE_BAR0' || o.b === 'PCIE_BAR0');
  return <div className="view-layout"><div className="view-main">
    <div className="toolbar"><div className="actions"><Badge>48-bit declared physical address space</Badge><Badge tone={conflicts.length ? 'red' : 'green'}>{conflicts.length} interval overlaps</Badge></div><div className="actions"><Button onClick={() => setReview(true)}>Review BAR relocation</Button></div></div>
    <AddressSections
      windows={localWindows(state.draft)}
      agents={localAgentGroups(state.draft)}
      selected={region.id}
      onSelect={setSelected}
      targetLabelById={localWindowTargets(state.draft)}
      coverageExtra={[['Mapped union', <span key="union">{(union / 2 ** 30).toFixed(6)} GiB · {(union / 2 ** 48 * 100).toFixed(6)}% of the 48-bit space</span>]]}
      banner={conflicts.length > 0 && <Notice tone="amber">An overlap exists in the declared address map. Runtime decoder behavior has not been evaluated.</Notice>}
    />

  </div><Inspector title="Address region"><h3 className="mono">{region.id}</h3><Properties rows={[[ 'Base', <code>{hex(region.base)}</code> ], ['Size', sizeLabel(region.size)], ['Inclusive end', <code>{hex(region.base + region.size - 1)}</code>], ['Exclusive end', <code>{hex(region.base + region.size)}</code>], ['Attributes', region.attributes], ['Target', region.target], ['Decoder implementation', 'Not evaluated']]} />{conflicts.filter(c => c.a === region.id || c.b === region.id).map(c => <Notice key={c.a + c.b} tone="red">Overlap with {c.a === region.id ? c.b : c.a}: {sizeLabel(c.size)} beginning at <code>{hex(c.start)}</code>.</Notice>)}<PageLink page="verify/checks">Run local interval checks</PageLink></Inspector>{review && <Dialog title="Review PCIE_BAR0 address relocation" onClose={() => setReview(false)}><Notice>No automatic permission, routing, or hardware changes. This edits the local address intent only.</Notice><Field label="Proposed base address" hint="48-bit hexadecimal address. Size stays 512 MiB."><input value={input} onChange={e => setInput(e.target.value)} /></Field><Properties rows={[[ 'Current base', hex(regions.find(r => r.id === 'PCIE_BAR0')!.base) ], ['Proposed end', base === null ? 'Invalid input' : hex(base + candidateRegion.size - 1)], ['Local interval check', valid ? 'No overlapping declared intervals' : 'Invalid or conflicting interval'], ['Historical evidence', `Still applies to ${BASE_REVISION}, not this edit`]]} />{!valid && <Notice tone="red">Enter a valid 48-bit base whose complete region does not overlap another declared interval.</Notice>}<div className="dialog-actions"><Button onClick={() => setReview(false)}>Cancel</Button><Button primary disabled={!valid} onClick={() => { setState(s => editDraft(s, 'Relocated PCIE_BAR0 in the local address map.', d => ({ ...d, regions: proposed }))); setReview(false); notify('Address intent updated. Runtime decoder checks remain unassessed.'); }}>Apply local address edit</Button></div></Dialog>}</div>;
}
function DomainsView({ state, setState, notify }: ViewProps) {
  const [selected, setSelected] = useState(state.selectedEndpoint), [review, setReview] = useState(false), [target, setTarget] = useState<DomainId>('clk_fabric');
  const ep = state.draft.endpoints.find(e => e.id === selected) ?? state.draft.endpoints[0];
  const crossings = state.draft.endpoints.filter(e => e.domain !== 'clk_fabric');
  const chips = state.draft.endpoints.map(endpoint => ({
    id: endpoint.id,
    title: endpoint.id,
    meta: `${endpoint.role} · ${endpoint.width}-bit`,
    detail: endpoint.domain !== 'clk_fabric' ? 'crossing · bridge open' : `${endpoint.router} / Local`,
    domain: endpoint.domain,
  }));
  return <div className="view-layout"><div className="view-main">
    <div className="toolbar"><div className="actions"><Badge>{DOMAINS.length} declared domains</Badge><Badge>{crossings.length} non-fabric endpoints</Badge><Badge tone={crossings.length ? 'amber' : 'neutral'}>CDC not established</Badge></div><div className="actions"><PageLink page="design/system">Inspect system composition</PageLink></div></div>
    <DomainSections
      agents={localAgentGroups(state.draft)}
      physical={localPhysical()}
      chips={chips}
      crossingDomain="clk_fabric"
      selected={ep.id}
      onSelect={id => setSelected(id)}
      figcaption={`${crossings.length} of ${state.draft.endpoints.length} endpoints declare a clock outside clk_fabric. Assignment is declared intent; no CDC or reset-domain analysis is implied.`}
    />

  </div><Inspector title="Domain assignment"><Field label="Endpoint"><select value={ep.id} onChange={e => setSelected(e.target.value)}>{state.draft.endpoints.map(e => <option key={e.id}>{e.id}</option>)}</select></Field><Properties rows={[[ 'Source', ep.source ], ['Current assignment', ep.domain], ['Destination network', 'clk_fabric'], ['Bridge implementation', 'Not established'], ['Reset-domain analysis', 'Not evaluated']]} /><Button primary onClick={() => { setTarget(ep.domain); setReview(true); }}>Review assignment change</Button><PageLink page="verify/obligations">Inspect CDC obligation</PageLink></Inspector>{review && <Dialog title={`Review clock assumption — ${ep.id}`} onClose={() => setReview(false)}><Field label="New declared clock domain"><select value={target} onChange={e => setTarget(e.target.value as DomainId)}>{DOMAIN_IDS.map(d => <option key={d}>{d}</option>)}</select></Field><Notice tone="amber">Domain assignment does not validate timing or implement CDC/reset bridges.</Notice><Properties rows={[[ 'Before', ep.domain ], ['After', target], ['Consequence', 'Model assumption changed. Historical evaluation conditions are preserved.']]} /><div className="dialog-actions"><Button onClick={() => setReview(false)}>Cancel</Button><Button primary disabled={target === ep.domain} onClick={() => { setState(s => editDraft(s, `Changed ${ep.id} declared domain to ${target}. No CDC claim established.`, d => ({ ...d, endpoints: d.endpoints.map(e => e.id === ep.id ? { ...e, domain: target } : e) }))); setReview(false); notify('Clock intent updated; implementation and timing remain unassessed.'); }}>Apply declared assumption</Button></div></Dialog>}</div>;
}
function PlacementView({ state, setState, notify }: ViewProps) {
  const [review, setReview] = useState(false), [x, setX] = useState(state.draft.anchor.x), [y, setY] = useState(state.draft.anchor.y);
  const valid = [x, y].every(v => Number.isFinite(v) && v >= 250 && v <= 4550);
  const anchor = state.draft.anchor;
  return <div className="view-layout"><div className="view-main">
    <div className="toolbar"><div className="actions"><Badge>4,800 × 4,800 μm declared frame</Badge><Badge>16 anchored routers</Badge><Badge tone="amber">advisory geometry</Badge></div><div className="actions"><PageLink page="design/system">Logical arrangement</PageLink></div></div>
    <PlacementSections
      view={localFloorplan()}
      annotations={localPlacementAnnotations(state.draft)}
      actions={<Button primary onClick={() => { setX(anchor.x); setY(anchor.y); setReview(true); }}>Review constraint edit</Button>}
      banner={<Notice tone="amber"><strong>Advisory geometry.</strong> No DEF/GDS, congestion, timing or DRC evidence is connected.</Notice>}
    />

  </div><Inspector title="Selected placement intent"><h3 className="mono">ANCHOR_01 · R_1_2</h3><Badge>Advisory constraint only</Badge><Properties rows={[[ 'Coordinate origin', 'Top-left; μm' ], ['Anchor', `${anchor.x}, ${anchor.y} μm`], ['Allowed box', '500 × 500 μm'], ['Declared box area', '0.25 mm²'], ['Downstream enforcement', 'Not established'], ['Wire delay / slack', 'Not evaluated']]} /><Button primary onClick={() => { setX(anchor.x); setY(anchor.y); setReview(true); }}>Review constraint edit</Button></Inspector>{review && <Dialog title="Review router anchor intent" onClose={() => setReview(false)}><div className="form-grid"><Field label="Anchor X (μm)"><input type="number" min="250" max="4550" value={Number.isNaN(x) ? '' : x} onChange={e => setX(e.target.valueAsNumber)} /></Field><Field label="Anchor Y (μm)"><input type="number" min="250" max="4550" value={Number.isNaN(y) ? '' : y} onChange={e => setY(e.target.valueAsNumber)} /></Field></div>{!valid && <Notice tone="red">The complete 500 μm box must stay inside the declared frame (anchor 250–4,550 μm).</Notice>}<Properties rows={[[ 'Current', `${anchor.x}, ${anchor.y} μm` ], ['Proposed', `${x}, ${y} μm`], ['Estimated delay / power', 'Not estimated'], ['Historical evidence', 'Retained for its original inputs; applicability not automatically upgraded.']]} /><div className="dialog-actions"><Button onClick={() => setReview(false)}>Cancel</Button><Button primary disabled={!valid || (x === anchor.x && y === anchor.y)} onClick={() => { setState(s => editDraft(s, 'Updated ANCHOR_01 placement intent locally.', d => ({ ...d, anchor: { x, y } }))); setReview(false); notify('Advisory placement intent updated. No physical checks were run.'); }}>Apply local constraint</Button></div></Dialog>}</div>;
}
