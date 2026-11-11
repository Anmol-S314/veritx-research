import { useEffect, useState, type ReactNode } from 'react';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { gateway, gatewayReason, type Topology } from './gateway';
import { ControlPlaneGraph, TopologyGraph } from './TopologyGraph';
import { SystemDiagram } from './SystemDiagram';
import { RouterIncidenceMatrix } from './RouterIncidenceMatrix';
import { FabricCanvas, toggleFabricLink, type FabricLink } from './FabricCanvas';
import { cappedClass, shortText } from './format';
import { familyStatus, statusTone, useTopologyFamilies } from './capabilities';
import { Assumptions, Badge, Button, Dialog, Empty, Field, Inspector, Notice, PageLink, Properties, Section } from './ui';
import { deadlockFacts, routerConfiguration } from './routerConfig';
import { INITIATOR_KINDS, accessMatrix, addressCoverage, agentsFromRequest, designDocument, exactMatches, formatBytes, formatHex, validateWindows, windowsFromRequest } from './agentMap';
import { decodeGroup } from './fabricAnalysis';
import { PARALLEL_AXES, axisDegree, parallelColor, parallelGroups, type ParallelAxis } from './parallelism';
import { contextTarget } from './contextSelection';
import { M1AddressEditor, M1PermissionBlocked, M2VcModule, M3DomainBlocked, M4ProtocolBlocked } from './MModulesEditor';
import type { FloorplanDerived, FloorplanView, PhysicalEstimates, RtlReadiness } from './gateway';

const absent = <Badge tone="amber">Not declared in this payload</Badge>;
function statText(value: { min: number | null; mean: number | null; max: number | null }, unit: string): string {
  if (value.min === null) return '—';
  return value.min === value.max ? `${value.min.toFixed(2)} ${unit}` : `${value.min.toFixed(2)}–${(value.max as number).toFixed(2)} ${unit} (mean ${(value.mean as number).toFixed(2)})`;
}
function physicalEstimatesProperties(physical: PhysicalEstimates | null | undefined): [string, ReactNode][] {
  if (!physical) return [['Planning estimates', 'Not recorded — no floorplan physical_estimates for this revision']];
  const rows: [string, ReactNode][] = [];
  rows.push(['Scope (verbatim)', physical.scope]);
  rows.push(['Congestion formula (verbatim)', physical.congestion.formula]);
  rows.push(['Congestion HPWL', statText(physical.congestion.hpwl_stats_um, 'µm')]);
  rows.push(['Congestion load', statText(physical.congestion.load_stats, '')]);
  rows.push(['Congestion max density', physical.congestion.max_density !== null ? String(physical.congestion.max_density) : '—']);
  rows.push(['Wire delay formula (verbatim)', physical.wire_delay_by_plane.formula]);
  rows.push(['Wire delay status', physical.wire_delay_by_plane.status]);
  rows.push(['Wire delay overall', statText(physical.wire_delay_by_plane.overall.delay_ps, 'ps')]);
  if (physical.wire_delay_by_plane.reason) rows.push(['Wire delay reason', physical.wire_delay_by_plane.reason]);
  if (physical.wire_delay_by_plane.by_plane) {
    const planes = Object.entries(physical.wire_delay_by_plane.by_plane);
    if (planes.length) rows.push(['Wire delay by plane', planes.map(([plane, stats]) => `${plane}: ${statText(stats.delay_ps, 'ps')}`).join(' · ')]);
  }
  rows.push(['Clock formula (verbatim)', physical.clock_tree.formula]);
  rows.push(['Clock domain source', physical.clock_tree.domain_source]);
  rows.push(['Clock domains', physical.clock_tree.domains.length ? physical.clock_tree.domains.map(d => `${d.domain} far ${d.far_point_um.toFixed(0)} µm`).join(' · ') : '—']);
  rows.push(['Slack estimate', `${physical.slack_estimate.status} · ${physical.slack_estimate.reason}`]);
  rows.push(['CTS skew estimate', `${physical.cts_skew_estimate.status} · ${physical.cts_skew_estimate.reason}`]);
  return rows;
}
function PhysicalEstimatesSection({ derived }: { derived: FloorplanDerived | null }) {
  const physical = derived?.physical_estimates ?? null;
  return <Section title="Physical estimates (planning-only)" actions={<Badge tone="blue">planning-only</Badge>}>
    <Properties rows={physicalEstimatesProperties(physical)} />
    {physical && physical.congestion.per_router.length > 0 && <div className="table-scroll"><table><thead><tr><th>Router</th><th>Incident channels</th><th>HPWL µm</th><th>Load</th></tr></thead><tbody>{physical.congestion.per_router.slice(0, 32).map(row => <tr key={row.router_id}><th className="mono">R{row.router_id}</th><td className="numeric">{row.incident_channels}</td><td className="numeric">{row.incident_hpwl_um.toFixed(1)}</td><td className="numeric">{row.load.toFixed(3)}</td></tr>)}</tbody></table>{physical.congestion.per_router.length > 32 && <p className="meta-line">Showing 32 of {physical.congestion.per_router.length} routers.</p>}</div>}
    {physical && physical.congestion.density_by_region.length > 0 && <div className="table-scroll"><table><thead><tr><th>Region</th><th>Density</th></tr></thead><tbody>{physical.congestion.density_by_region.map((row, index) => <tr key={index}><th className="mono">[{row.region[0]},{row.region[1]}]</th><td className="numeric">{row.density.toFixed(4)}</td></tr>)}</tbody></table></div>}
  </Section>;
}

function useTopology(data: LoadedProject) {
  return data.topology;
}

function TopologyMissing({ data }: { data: LoadedProject }) {
  const { reload } = useProject();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const compile = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await gateway.compileProject(data.detail.project.project_id, data.draftMeta?.revisionToken);
      reload();
    } catch (failure) {
      setError(gatewayReason(failure));
    } finally {
      setBusy(false);
    }
  };
  return <Empty title="No topology available for this revision">
    <p>{data.topologyError || 'The gateway returned no topology document.'}</p>
    {error && <Notice tone="red">{error}</Notice>}
    <div className="toolbar toolbar-start">
      <Button primary disabled={busy} onClick={compile}>{busy ? 'Compiling…' : 'Compile draft'}</Button>
      <PageLink page="workloads/workflow">Open project workflow</PageLink>
    </div>
  </Empty>;
}

function PendingDraftNotice({ data, children }: { data: LoadedProject; children: ReactNode }) {
  if (!data.draftMeta?.dirty) return null;
  return <Notice tone="amber"><strong>Saved draft differs from active revision {data.detail.active_revision_id ?? '—'}.</strong> {children}</Notice>;
}

export function LiveFabric({ data, notify, banner }: { data: LoadedProject; notify?: (message: string) => void; banner?: ReactNode }) {
  const topology = useTopology(data);
  const sharedLinks = topology?.shared_links ?? [];
  const { reload } = useProject();
  const [selected, setSelected] = useState<number | null>(null);
  const [layer, setLayer] = useState<'physical' | 'none'>('physical');
  const [channelView, setChannelView] = useState<'router' | 'channel'>('router');
  const [hovered, setHovered] = useState<Topology['channels'][number] | null>(null);
  const [filter, setFilter] = useState('');
  const [zoom, setZoom] = useState(100);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [plane, setPlane] = useState<'d' | 'c' | 't'>('d');
  const [selectedWire, setSelectedWire] = useState<number | null>(null);
  const [parallelAxis, setParallelAxis] = useState<'none' | ParallelAxis>('none');
  const [treeTab, setTreeTab] = useState<'routers' | 'wires'>('routers');
  const [controlOpen, setControlOpen] = useState(false);
  const [depth, setDepth] = useState(8);
  const [controlError, setControlError] = useState('');
  const [savingControl, setSavingControl] = useState(false);
  const familyProbe = useTopologyFamilies();
  const request = data.request as Record<string, any> | null;
  const explicit = request?.topology?.kind === 'explicit' ? request.topology.graph : request?.explicit_topology ?? null;
  const linksOf = (graph: any): FabricLink[] => (Array.isArray(graph?.links) ? graph.links : []).filter((pair: any) => Array.isArray(pair) && pair.length === 2).map((pair: any) => [Number(pair[0]), Number(pair[1])] as FabricLink);
  const [graphLinks, setGraphLinks] = useState<FabricLink[]>(() => linksOf(explicit));
  const [editingGraph, setEditingGraph] = useState(false);
  const [savingGraph, setSavingGraph] = useState(false);
  const [graphFeedback, setGraphFeedback] = useState<{ tone: 'blue' | 'red'; text: string } | null>(null);
  useEffect(() => { setGraphLinks(linksOf(explicit)); setGraphFeedback(null); }, [data.detail.project.project_id, data.detail.active_revision_id]);
  const floorplanProjectId = data.detail.project.project_id;
  const floorplanRevisionId = data.detail.active_revision_id;
  const [floorplanViewFabric, setFloorplanViewFabric] = useState<FloorplanView | null>(null);
  const [floorplanErrFabric, setFloorplanErrFabric] = useState('');
  useEffect(() => {
    let live = true;
    gateway.floorplan(floorplanProjectId).then(value => { if (live) setFloorplanViewFabric(value); }).catch(failure => { if (live) setFloorplanErrFabric(gatewayReason(failure)); });
    return () => { live = false; };
  }, [floorplanProjectId, floorplanRevisionId]);
  const floorplanDerivedFabric = floorplanViewFabric?.derived ?? null;
  if (!topology) return <div className="view-layout"><div className="view-main">{banner}<TopologyMissing data={data} /></div></div>;
  const saveGraph = async () => {
    if (!request || !explicit || savingGraph) return;
    setSavingGraph(true); setGraphFeedback(null);
    try {
      const graph = { ...explicit, links: graphLinks };
      const next = request.topology?.kind === 'explicit'
        ? { ...request, topology: { ...request.topology, graph } }
        : { ...request, explicit_topology: graph };
      await gateway.putDraft(data.detail.project.project_id, next, data.draftMeta?.revisionToken);
      setGraphFeedback({ tone: 'blue', text: 'Explicit graph saved to the draft. Compile the revision to materialise it.' });
      notify?.('Explicit graph saved to the draft. Compile the revision to materialise it.');
      reload();
    } catch (error) {
      setGraphFeedback({ tone: 'red', text: gatewayReason(error) });
    } finally { setSavingGraph(false); }
  };
  const router = selected === null ? null : topology.routers.find(r => r.router_id === selected) ?? null;
  const inbound = selected === null ? [] : topology.channels.filter(c => c.dst_router === selected);
  const outbound = selected === null ? [] : topology.channels.filter(c => c.src_router === selected);
  const outboundShared = selected === null ? [] : sharedLinks.filter(link => link.src_router === selected);
  const inboundShared = selected === null ? [] : sharedLinks.filter(link => link.taps.includes(selected));
  const attached = selected === null ? [] : topology.endpoints.filter(e => e.router_id === selected);
  const widths = [...new Set([...topology.channels.map(c => c.width_bits), ...sharedLinks.map(link => link.width_bits)])];
  const latencies = [...new Set([...topology.channels.map(c => c.latency_cycles), ...sharedLinks.map(link => link.latency_cycles)])];
  const shownChannels = selected === null ? topology.channels : topology.channels.filter(c => c.src_router === selected || c.dst_router === selected);
  const uniformChannels = widths.length === 1 && latencies.length === 1;
  const byPair = new Map(topology.channels.map(c => [`${c.src_router}:${c.dst_router}`, c]));
  const pairing = (c: Topology['channels'][number]) => {
    const back = byPair.get(`${c.dst_router}:${c.src_router}`);
    if (!back) return 'missing' as const;
    return back.width_bits === c.width_bits && back.latency_cycles === c.latency_cycles ? 'paired' as const : 'mismatch' as const;
  };
  const portCount = topology.channels.reduce((n, c) => Math.max(n, c.src_port), 0);
  const unpaired = topology.channels.filter(c => pairing(c) !== 'paired');
  const portRows = (selected === null ? topology.routers.map(r => r.router_id) : [selected])
    .sort((a, b) => a - b)
    .map(id => { const out = topology.channels.filter(c => c.src_router === id); return { id, out, byPort: new Map(out.map(c => [c.src_port, c])) }; });
  const selectRouter = (id: number) => setSelected(id === selected ? null : id);
  const linkHandlers = (c: Topology['channels'][number]) => ({ onMouseEnter: () => setHovered(c), onMouseLeave: () => setHovered(null), onFocus: () => setHovered(c), onBlur: () => setHovered(null) });
  const pairingLabel = { paired: 'declared return channel, same width and latency', missing: 'no return channel declared', mismatch: 'return channel declared with a different width or latency' };
  const coordOf = (item: Topology['routers'][number]) => item.coordinates ?? [];
  const hasCoordinates = topology.routers.length > 0 && topology.routers.every(item => coordOf(item).length >= 2);
  const gridSide = hasCoordinates ? Math.max(...topology.routers.map(item => Math.max(coordOf(item)[0], coordOf(item)[1]))) + 1 : null;
  const gridLabel = gridSide ? `${gridSide}×${gridSide}` : 'coordinates not declared';
  const query = filter.trim().toLowerCase();
  const matchingRouters = topology.routers.filter(item => !query || `r${item.router_id} ${item.router_id}`.includes(query));
  const matchingEndpoints = topology.endpoints.filter(item => !query || `${item.kind} ${item.endpoint_id} r${item.router_id} ${item.router_id}`.toLowerCase().includes(query));
  const rowGroups: { key: string; label: string; routers: Topology['routers'] }[] = [];
  if (hasCoordinates) {
    const byRow = new Map<number, Topology['routers']>();
    for (const item of matchingRouters) {
      const row = coordOf(item)[1];
      byRow.set(row, [...(byRow.get(row) ?? []), item]);
    }
    for (const [row, routers] of [...byRow.entries()].sort((a, b) => b[0] - a[0])) {
      rowGroups.push({ key: `row-${row}`, label: `Row ${row}`, routers: [...routers].sort((a, b) => coordOf(a)[0] - coordOf(b)[0]) });
    }
  } else {
    rowGroups.push({ key: 'all', label: 'All routers', routers: matchingRouters });
  }
  const endpointCount = (routerId: number) => topology.endpoints.filter(item => item.router_id === routerId).length;
  const unattached = topology.routers.filter(item => endpointCount(item.router_id) === 0);
  const overSeated = topology.routers.filter(item => (item.seat_capacity ?? Infinity) < endpointCount(item.router_id));
  const findings: { code: string; text: string; object: string; router: number }[] = [];
  if (unpaired.length) findings.push({ code: 'RETURN', text: `${unpaired.length} directed channels have no matching return at the same width and latency`, object: 'Declared channels', router: unpaired[0].src_router });
  if (unattached.length) findings.push({ code: 'ATTACH', text: `${unattached.length} routers have no declared endpoint seat`, object: `R${unattached[0].router_id}`, router: unattached[0].router_id });
  if (overSeated.length) findings.push({ code: 'SEATS', text: `${overSeated.length} routers declare more endpoints than their seat capacity`, object: `R${overSeated[0].router_id}`, router: overSeated[0].router_id });
  const truth = familyStatus(familyProbe.families, topology.family);
  const clock = data.request?.physical?.clock_freq_mhz;
  const lockedDerived = (data.detail.active_revision?.design as Record<string, any> | undefined)?.locked_derived;
  const compileResult = data.compileResult;
  const resources = compileResult?.groups?.resources;
  const deadlock = resources?.deadlock;
  const requestTopology = (data.request as Record<string, any> | null)?.topology;
  const rawPlanes: string[] = topology.planes?.length
    ? topology.planes
    : Array.isArray(requestTopology?.planes) ? requestTopology.planes : ['d'];
  const declaredPlanes = (['d', 'c', 't'] as const).filter(value => rawPlanes.includes(value));
  const activePlane = declaredPlanes.includes(plane) ? plane : 'd';
  const controlPlane = compileResult?.groups?.control_plane;
  const controlSubnet = controlPlane?.available ? controlPlane.subnet ?? null : null;
  const telPeriod = requestTopology?.tel_period;
  const telLatency = requestTopology?.tel_latency;
  const selectedWireLink = selectedWire === null ? null : sharedLinks.find(link => link.shared_link_id === selectedWire) ?? null;
  const mapping = compileResult?.groups?.mapping;
  const parallelism = mapping?.parallelism;
  const mappingRows = mapping?.rows ?? [];
  const mappingAvailable = mapping?.available === true && mappingRows.length > 0;
  const chosenAxis = parallelAxis === 'none' ? null : parallelAxis;
  const activeParallelAxis = chosenAxis && axisDegree(parallelism, chosenAxis) > 1 ? chosenAxis : null;
  const endpointRouter = new Map(topology.endpoints.map(endpoint => [endpoint.endpoint_id, endpoint.router_id]));
  const axisGroups = activeParallelAxis ? parallelGroups(mappingRows, endpointRouter, activeParallelAxis) : [];
  const selectedAxisDegree = activeParallelAxis ? axisDegree(parallelism, activeParallelAxis) : 1;
  const nocControls = (data.request as Record<string, any> | null)?.noc_controls;
  const schemaVersion = Number((data.request as Record<string, any> | null)?.schema_version ?? 0);
  const canEditControls = schemaVersion >= 4 && nocControls !== null && typeof nocControls === 'object';
  const currentDepth = typeof nocControls?.input_buffer_depth_flits_per_vc === 'number'
    ? nocControls.input_buffer_depth_flits_per_vc
    : resources?.arbitration?.input_buffer_depth_flits_per_vc;
  const bufferDepth = currentDepth;
  const validDepth = Number.isInteger(depth) && depth >= 1 && depth <= 64;
  const factRows = (facts: { label: string; value: string; mono?: boolean }[]): [string, ReactNode][] =>
    facts.map(fact => [fact.label, fact.mono ? <span className="mono">{fact.value}</span> : fact.value]);
  const applyDepth = async () => {
    if (!data.request || !canEditControls || savingControl) return;
    if (!validDepth) {
      setControlError('Buffer depth must be a whole number between 1 and 64 flits per VC.');
      return;
    }
    setSavingControl(true);
    setControlError('');
    try {
      const next = {
        ...data.request,
        noc_controls: { ...(nocControls as Record<string, unknown>), input_buffer_depth_flits_per_vc: depth },
      };
      const saved = await gateway.putDraft(data.detail.project.project_id, next, data.draftMeta?.revisionToken);
      await gateway.compileProject(data.detail.project.project_id, saved?.revisionToken);
      setControlOpen(false);
      notify?.(`Buffer depth set to ${depth} flits per VC and the revision was recompiled.`);
      reload();
    } catch (error) {
      setControlError(gatewayReason(error));
    } finally {
      setSavingControl(false);
    }
  };
  return <div className="view-layout"><div className="view-main">
    {banner}
    <PendingDraftNotice data={data}>Topology and compiler evidence below describe the active revision. Compile the saved draft before expecting topology changes here.</PendingDraftNotice>

    {topology.channels.length === 0 && sharedLinks.length === 0 && <Notice tone="amber"><strong>No directed channels or shared wires in this topology document.</strong> Routers and endpoint seats are materialised; link stress, route attribution and playback cannot be drawn for this revision.</Notice>}
    {declaredPlanes.length > 1 && <div className="toolbar fabric-plane-bar">
      <div className="segmented" role="group" aria-label="Packet plane">
        {declaredPlanes.map(value => <button type="button" key={value} className={activePlane === value ? 'active' : ''} onClick={() => { setPlane(value as 'd' | 'c' | 't'); setSelected(null); setSelectedWire(null); }}>
          {value === 'd' ? 'Data (D)' : value === 'c' ? 'Control (C)' : 'Telemetry (T)'}
        </button>)}
      </div>
      <span className="muted">{activePlane === 'd'
        ? `${sharedLinks.length} MECS shared wires`
        : activePlane === 'c'
          ? controlSubnet ? `Subnet ${controlSubnet.id} · ${controlSubnet.k}×${controlSubnet.k} · ${controlSubnet.k * controlSubnet.k} routers` : 'No subnet artifact'
          : `Period ${telPeriod ?? '—'} cycles · latency ${telLatency ?? '—'} cycles`}</span>
    </div>}
    <div className="toolbar fabric-toolbar">
      <div className="actions">
        <Badge tone={truth ? statusTone(truth.status) : 'neutral'}>{truth ? truth.status : 'capability unknown'}</Badge>
        <span className="mono muted">{topology.family} · {topology.counts?.routers ?? topology.routers.length} routers{topology.channels.length > 0 ? ` · ${topology.channels.length} directed channels` : ''}{sharedLinks.length > 0 ? ` · ${sharedLinks.length} shared wires` : ''} · {topology.counts?.endpoints ?? topology.endpoints.length} endpoints</span>
      </div>
      <div className="actions">
        <div className="zoom-control">
          <button type="button" className="zoom-button" onClick={() => setZoom(value => Math.max(50, value - 10))} title="Zoom out">−</button>
          <span className="mono">{zoom}%</span>
          <button type="button" className="zoom-button" onClick={() => setZoom(value => Math.min(200, value + 10))} title="Zoom in">+</button>
          <button type="button" className="zoom-button fit" onClick={() => setZoom(100)}>Fit</button>
        </div>
        <select aria-label="Overlay layer" value={layer} onChange={e => setLayer(e.target.value as typeof layer)}>
          <option value="physical">Declared channels and attachments</option>
          <option value="none">No overlay</option>
        </select>
        {explicit && activePlane === 'd' && <Button onClick={() => setEditingGraph(value => !value)}>{editingGraph ? 'Done editing' : 'Edit links'}</Button>}
      </div>
    </div>
    <div className="fabric-workbench">
      <aside className="fabric-tree">
        {activePlane === 'd' ? <>
        {sharedLinks.length > 0 && <div className="fabric-tree-tabs segmented" role="group" aria-label="Fabric tree view">
          <button type="button" className={treeTab === 'routers' ? 'active' : ''} aria-pressed={treeTab === 'routers'} onClick={() => setTreeTab('routers')}>Routers</button>
          <button type="button" className={treeTab === 'wires' ? 'active' : ''} aria-pressed={treeTab === 'wires'} onClick={() => setTreeTab('wires')}>Wires {sharedLinks.length}</button>
        </div>}
        {treeTab === 'wires' && sharedLinks.length > 0
          ? <div className="fabric-tree-scroll">
            <div className="tree-row-head"><span>Multidrop wires</span><span>{sharedLinks.length}</span></div>
            {sharedLinks.map(link => <button type="button" key={link.shared_link_id} className={`tree-wire${selectedWire === link.shared_link_id ? ' selected' : ''}`} title={`W${link.shared_link_id} · R${link.src_router} → ${link.taps.map(tap => `R${tap}`).join(' · ')} · ${link.width_bits} b · ${link.latency_cycles} cyc`} onClick={() => setSelectedWire(selectedWire === link.shared_link_id ? null : link.shared_link_id)}>
              <span className="mono">W{link.shared_link_id}</span>
              <span className="tree-wire-path mono">R{link.src_router} → {link.taps.map(tap => `R${tap}`).join('·')}</span>
            </button>)}
          </div>
          : <>
          <div className="fabric-search">
            <input aria-label="Filter fabric entities" placeholder="Filter routers, endpoints…" value={filter} onChange={e => setFilter(e.target.value)} />
          </div>
          <div className="fabric-tree-scroll">
            {rowGroups.map(group => <div key={group.key} className="tree-group">
              <div className="tree-row-head"><span>{group.label}</span><span>{group.routers.length}</span></div>
              {group.routers.map(item => <button type="button" key={item.router_id} className={`tree-router${selected === item.router_id ? ' selected' : ''}`} {...contextTarget('router', item.router_id, `Router R${item.router_id}`, `${topology.family} · ${endpointCount(item.router_id)} attached endpoint${endpointCount(item.router_id) === 1 ? '' : 's'}`)} onClick={() => selectRouter(item.router_id)}>
                <span>R{item.router_id}</span><small>{endpointCount(item.router_id)} EP</small>
              </button>)}
            </div>)}
            {matchingRouters.length === 0 && <p className="meta-line">No router matches the filter.</p>}
            <div className="tree-group">
              <div className="tree-row-head"><span>Hardware endpoints</span><span>{topology.endpoints.length}</span></div>
              {matchingEndpoints.slice(0, 80).map(item => <button type="button" key={item.endpoint_id} className="tree-endpoint" {...contextTarget('endpoint', item.endpoint_id, `Endpoint EP-${item.endpoint_id}`, `${item.kind} · attached to R${item.router_id} port ${item.port_id}`)} onClick={() => selectRouter(item.router_id)}>
                <span className="mono">{item.kind}#{item.endpoint_id}</span><span>R{item.router_id} · p{item.port_id}</span>
              </button>)}
              {matchingEndpoints.length > 80 && <p className="meta-line">80 of {matchingEndpoints.length} endpoints shown; refine the filter.</p>}
              {matchingEndpoints.length === 0 && <p className="meta-line">No endpoint matches the filter.</p>}
            </div>
          </div>
          </>}
        </> : <div className="fabric-tree-scroll"><p className="meta-line">No per-router selection on Plane {activePlane.toUpperCase()}.</p></div>}
      </aside>
      <div className="fabric-center">
        <div className="fabric-breadcrumb">
          <span>Fabric: <strong>{topology.family}</strong></span><span className="muted">›</span>
          <span>{activePlane === 'c' ? 'Plane C subnet' : activePlane === 't' ? 'Plane T telemetry overlay' : selected === null ? 'no router selected' : `Router R${selected}`}</span>
          <span className="spacer" />
          <span>Clock <strong className="mono">{clock ? `${clock} MHz` : 'not declared'}</strong></span>
          <span>Flit <strong className="mono">{widths.length ? `${widths.join('/')} bit` : 'not declared'}</strong></span>
          <span>VC <strong>{activePlane === 'c' ? (controlSubnet ? String(controlSubnet.vc_count) : 'not declared') : resources?.vc_count !== undefined ? String(resources.vc_count) : 'not declared'}</strong></span>
          {activePlane === 'd' && mappingAvailable && <label className="parallelism-control">
            <span>Parallelism</span>
            <select aria-label="Parallelism overlay" value={activeParallelAxis ?? 'none'} onChange={e => setParallelAxis(e.target.value as 'none' | ParallelAxis)}>
              <option value="none">None</option>
              {PARALLEL_AXES.map(axis => <option key={axis} value={axis} disabled={axisDegree(parallelism, axis) <= 1}>{axis.toUpperCase()} · {axisDegree(parallelism, axis)}</option>)}
            </select>
          </label>}
        </div>
        <div className="fabric-canvas-scroll">
          <div className="fabric-canvas" style={{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }}>
            {activePlane === 'c'
              ? controlSubnet
                ? <ControlPlaneGraph k={controlSubnet.k} c={controlSubnet.c} routing={controlSubnet.routing} vcs={controlSubnet.vcs} />
                : <Empty title="Plane C is declared but not materialized">The compile result carries no control-plane artifact for this revision. {controlPlane?.reason ?? ''}</Empty>
              : editingGraph && explicit && activePlane === 'd'
                ? <FabricCanvas nodes={Number(explicit.nodes) || 0} links={graphLinks} onToggleLink={(a, b) => setGraphLinks(list => toggleFabricLink(list, a, b))} />
                : <TopologyGraph topology={topology} selected={activePlane === 'd' ? selected : null} onSelect={activePlane === 'd' ? selectRouter : undefined} highlight={activePlane === 'd' ? hovered : null} telemetry={activePlane === 't'} selectedWire={activePlane === 'd' && selectedWireLink ? selectedWire : null} onSelectWire={setSelectedWire} mappingRows={activePlane === 'd' ? mappingRows : undefined} axis={activePlane === 'd' ? activeParallelAxis : null} degreeCount={activePlane === 'd' ? selectedAxisDegree : undefined} />}
          </div>
        </div>
        {activePlane === 'd' && selectedWireLink && <div className="fabric-wire-strip">
          <span><strong className="mono">W{selectedWireLink.shared_link_id}</strong> selected</span>
          <span className="mono">R{selectedWireLink.src_router} → {selectedWireLink.taps.map(tap => `R${tap}`).join(' · ')}</span>
          <span className="mono">{selectedWireLink.width_bits} b · {selectedWireLink.latency_cycles} cyc · {selectedWireLink.taps.length} taps</span>
          <span className="spacer" />
          <Button onClick={() => setSelectedWire(null)}>Clear wire</Button>
        </div>}
        {editingGraph && explicit && activePlane === 'd' && <div className="toolbar toolbar-start fabric-edit-actions">
          <Button primary disabled={savingGraph} onClick={saveGraph}>{savingGraph ? 'Saving…' : 'Save graph to draft'}</Button>
          <Button onClick={() => { setEditingGraph(false); setGraphLinks(linksOf(explicit)); setGraphFeedback(null); }}>Cancel</Button>
        </div>}
        {graphFeedback && <Notice tone={graphFeedback.tone}>{graphFeedback.text}</Notice>}
        <div className="fabric-status">
          {activePlane === 'c' && controlSubnet ? <>
            <span>Plane C · {controlSubnet.k}×{controlSubnet.k} mesh</span>
            <span>{controlSubnet.k * controlSubnet.k} routers · {controlSubnet.c} seats/router</span>
            <span>{controlSubnet.routing.toUpperCase()} · {controlSubnet.vcs.join(' / ')} VCs</span>
          </> : activePlane === 't' ? <>
            <span>Plane T · telemetry vectors</span>
            <span>Period {telPeriod ?? '—'} cycles · latency {telLatency ?? '—'} cycles</span>
            <span>No separate router/channel artifact</span>
          </> : <>
            <span>{gridLabel} · {topology.routers.length} routers</span>
            {topology.channels.length > 0 && <span>{topology.channels.length} directed channels</span>}
            {sharedLinks.length > 0 && <span>{sharedLinks.length} shared wires</span>}
            <span>{widths.length ? `${widths.join('/')} b` : 'width not declared'} · {latencies.length ? `${latencies.join('/')} cyc` : 'latency not declared'}</span>
            <span>{hasCoordinates ? 'Declared coordinates' : 'Layout derived from channels'}</span>
            {activeParallelAxis && <span>Parallelism · {activeParallelAxis.toUpperCase()} {selectedAxisDegree}</span>}
          </>}
          <span className="spacer" />
          <span>{zoom}%</span>
        </div>
      </div>
    </div>
    {activePlane === 'd' && <>
    <div className="fabric-drawer">
      <button type="button" className="fabric-drawer-head" onClick={() => setDrawerOpen(value => !value)} aria-expanded={drawerOpen}>
        <span>Declared-structure findings · {findings.length}</span>
        <Badge tone={findings.length ? 'amber' : 'neutral'}>{findings.length ? `${findings.length} to review` : 'none'}</Badge>
      </button>
      {drawerOpen && (findings.length
        ? <div className="table-scroll"><table><thead><tr><th>Code</th><th>Finding</th><th>Object</th><th /></tr></thead><tbody>
          {findings.map(item => <tr key={item.code}><th className="mono">{item.code}</th><td>{item.text}</td><td className="mono">{item.object}</td><td><Button onClick={() => setSelected(item.router)}>Select router</Button></td></tr>)}
        </tbody></table></div>
        : <p className="meta-line">No declared-structure findings in this payload.</p>)}
    </div>
    {topology.channels.length > 0 && <Section title="Declared channels" actions={<>
      <select aria-label="Channel list layout" value={channelView} onChange={e => setChannelView(e.target.value as typeof channelView)}>
        <option value="router">By router / port</option>
        <option value="channel">By channel</option>
      </select>
      <Badge>directed</Badge>
      <Badge>{channelView === 'router' ? `${portRows.length} of ${topology.routers.length} routers` : shownChannels.length === topology.channels.length ? `${shownChannels.length} channels` : `${shownChannels.length} of ${topology.channels.length}`}</Badge>
    </>}>
      {channelView === 'router'
        ? <div className={`table-scroll${cappedClass(portRows.length)}`}>
          <table className="port-table"><thead><tr><th>Router</th>{Array.from({ length: portCount }, (_, i) => <th key={i}>port {i + 1}</th>)}<th>Return paths</th></tr></thead><tbody>
            {portRows.map(row => {
              const returned = row.out.filter(c => pairing(c) === 'paired').length;
              return <tr key={row.id} className={row.id === selected ? 'selected' : ''}>
                <th className="mono">R{row.id}</th>
                {Array.from({ length: portCount }, (_, i) => {
                  const c = row.byPort.get(i + 1);
                  if (!c) return <td key={i} className="muted" title="No channel declared on this port number; port capacity is not declared">—</td>;
                  const state = pairing(c);
                  return <td key={i}>
                    <button type="button" className={`channel-chip ${state}`} title={`R${c.src_router} / p${c.src_port} → R${c.dst_router} / p${c.dst_port} · ${pairingLabel[state]}`} aria-label={`Router ${c.src_router} port ${c.src_port} to router ${c.dst_router} port ${c.dst_port}, ${pairingLabel[state]}`} {...contextTarget('declared-channel', c.channel_id ?? `${c.src_router}:${c.src_port}->${c.dst_router}:${c.dst_port}`, `Declared channel R${c.src_router}→R${c.dst_router}`, `R${c.src_router} p${c.src_port} → R${c.dst_router} p${c.dst_port} · ${c.width_bits} b · ${c.latency_cycles} cyc · ${pairingLabel[state]}`)} {...linkHandlers(c)} onClick={() => selectRouter(row.id)}>
                      <span className="mono">R{c.dst_router}</span>{state !== 'paired' && <span className="chip-mark" aria-hidden="true">{state === 'mismatch' ? '≠' : '!'}</span>}
                    </button>
                  </td>;
                })}
                <td className="numeric">{returned}/{row.out.length}</td>
              </tr>;
            })}
          </tbody></table>
        </div>
        : <div className={`table-scroll${cappedClass(shownChannels.length)}`}>
          <table className="channel-table"><thead><tr><th>From → to (router / port)</th>{unpaired.length > 0 && <th>Return</th>}{!uniformChannels && <><th>Width</th><th>Latency</th></>}</tr></thead><tbody>
            {shownChannels.map(c => {
              const state = pairing(c);
              return <tr key={`${c.src_router}:${c.src_port}->${c.dst_router}:${c.dst_port}`} className="channel-row" tabIndex={0} aria-label={`Router ${c.src_router} port ${c.src_port} to router ${c.dst_router} port ${c.dst_port}, ${pairingLabel[state]}`} {...contextTarget('declared-channel', c.channel_id ?? `${c.src_router}:${c.src_port}->${c.dst_router}:${c.dst_port}`, `Declared channel R${c.src_router}→R${c.dst_router}`, `R${c.src_router} p${c.src_port} → R${c.dst_router} p${c.dst_port} · ${c.width_bits} b · ${c.latency_cycles} cyc · ${pairingLabel[state]}`)} {...linkHandlers(c)} onClick={() => selectRouter(c.src_router)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectRouter(c.src_router); } }}>
                <td className="mono">R{c.src_router} / p{c.src_port} <span className="muted">→</span> R{c.dst_router} / p{c.dst_port}</td>
                {unpaired.length > 0 && <td className={state === 'paired' ? 'muted' : state === 'missing' ? 'warn-text' : 'error-text'}>{state === 'paired' ? 'same' : state === 'missing' ? '! none' : '≠ differs'}</td>}
                {!uniformChannels && <><td className="numeric">{c.width_bits} b</td><td className="numeric">{c.latency_cycles} cyc</td></>}
              </tr>;
            })}
            {shownChannels.length === 0 && <tr><td className="muted" colSpan={1 + (unpaired.length > 0 ? 1 : 0) + (uniformChannels ? 0 : 2)}>No declared channel touches router {selected}.</td></tr>}
          </tbody></table>
        </div>}
    </Section>}
    {sharedLinks.length > 0 && <Section title="Shared wires (MECS)" actions={<><Badge>multidrop</Badge><Badge>{sharedLinks.length} wires</Badge>{selectedWire !== null && <Button onClick={() => setSelectedWire(null)}>Clear selection</Button>}</>}>
      <div className={`table-scroll${cappedClass(sharedLinks.length)}`}>
        <table><thead><tr><th>Wire</th><th>Driver</th><th>Taps</th><th>Width</th><th>Latency</th></tr></thead><tbody>
          {sharedLinks.map(link => <tr key={link.shared_link_id} className={selectedWire === link.shared_link_id ? 'selected' : ''} {...contextTarget('wire', link.shared_link_id, `Shared wire W${link.shared_link_id}`, `driver R${link.src_router} → taps ${link.taps.map(tap => `R${tap}`).join(', ')} · ${link.width_bits} bits · ${link.latency_cycles} cycles`)}>
            <th><button type="button" className="text-button mono" onClick={() => setSelectedWire(selectedWire === link.shared_link_id ? null : link.shared_link_id)}>W{link.shared_link_id}</button></th>
            <td className="mono">R{link.src_router}</td>
            <td className="mono">{link.taps.map(tap => `R${tap}`).join(' · ')}</td>
            <td className="numeric">{link.width_bits} b</td>
            <td className="numeric">{link.latency_cycles} cyc</td>
          </tr>)}
        </tbody></table>
      </div>
    </Section>}
    {mappingAvailable && <Section title="Parallelism mapping" actions={<Badge>{mapping.rank_count ?? mappingRows.length} mapped ranks</Badge>}>
      <Properties rows={[
        ['Degrees', PARALLEL_AXES.map(axis => `${axis.toUpperCase()} ${axisDegree(parallelism, axis)}`).join(' · ')],
        ['Mapped ranks', String(mapping.rank_count ?? mappingRows.length)],
        ['Idle agents', String(mapping?.idle_agents?.count ?? 0)],
        ['Overlay', activeParallelAxis ? `${activeParallelAxis.toUpperCase()} groups` : 'None'],
      ]} />
      {activeParallelAxis
        ? axisGroups.length
          ? <div className="table-scroll capped"><table><thead><tr><th>Group</th><th>Ranks</th><th>Routers</th></tr></thead><tbody>
            {axisGroups.map(group => <tr key={group.coordinate}>
              <th><span className="parallel-swatch" style={{ background: parallelColor(group.coordinate, selectedAxisDegree) }} />{activeParallelAxis.toUpperCase()} {group.coordinate}</th>
              <td className="numeric">{group.ranks}</td>
              <td className="mono">{group.routers.length ? group.routers.map(router => `R${router}`).join(' · ') : 'No mapped router'}</td>
            </tr>)}
          </tbody></table></div>
          : <p className="muted">No mapped ranks carry a {activeParallelAxis.toUpperCase()} coordinate.</p>
        : null}
    </Section>}
    </>}
    {activePlane === 'c' && <Section title="Plane C · declared subnet" actions={<Badge tone="amber">declared structure</Badge>}>
      {controlSubnet ? <Properties rows={[
        ['Subnet', String(controlSubnet.id)],
        ['Mesh', `${controlSubnet.k}×${controlSubnet.k} · ${controlSubnet.k * controlSubnet.k} routers · ${controlSubnet.c} seats/router`],
        ['Routing', controlSubnet.routing.toUpperCase()],
        ['Virtual channels', controlSubnet.vcs.join(' / ')],
        ['Class → subnet', controlPlane?.class_to_subnet?.rows?.length ? controlPlane.class_to_subnet.rows.map(row => `${row.traffic_class}: subnet ${row.subnet}`).join(' · ') : 'No class→subnet binding materialized'],
      ]} /> : <Notice tone="amber">Plane C is declared in the topology, but the compile result carries no control-plane artifact. {controlPlane?.reason ?? ''}</Notice>}
    </Section>}
    {activePlane === 't' && <>
      <Notice tone="amber"><strong>Plane T is declared, but the payload carries no telemetry topology.</strong></Notice>
      <Section title="Plane T · telemetry" actions={<Badge tone="amber">declared overlay</Badge>}>
        <Properties rows={[
          ['Period', telPeriod !== undefined ? `${telPeriod} cycles` : 'Not declared'],
          ['Latency', telLatency !== undefined ? `${telLatency} cycles` : 'Not declared'],
          ['Topology', 'No separate Plane T router/channel artifact'],
        ]} />
      </Section>
    </>}
    <Section title="Routing law and VC summary" actions={<Badge tone={resources ? 'blue' : 'amber'}>{resources ? 'compile-result' : 'not exposed'}</Badge>}>
      <Properties rows={[
        ['Derived VCs', resources?.vc_count !== undefined ? `${resources.vc_count} per port` : 'Not derived'],
        ['VC ids', resources?.vc_ids?.length ? resources.vc_ids.join(', ') : 'Not declared'],
        ['Escape VCs', resources?.escape_vcs?.length ? resources.escape_vcs.join(', ') : resources?.escape_vcs ? 'none' : 'Not declared'],
        ['Routing law / derivation', resources?.derivation ?? 'Not declared in resources; see locked-derived certificate'],
        ['Traffic class → VC', resources?.traffic_class_to_vcs?.length ? resources.traffic_class_to_vcs.map(([cls, vcs]) => `${cls}: ${vcs.join(', ')}`).join(' · ') : 'Not exposed'],
        ['VC → routing class', resources?.vc_to_routing_class?.length ? resources.vc_to_routing_class.map(([vc, cls]) => `${vc}: ${cls}`).join(' · ') : 'Not exposed'],
        ['Flow control', resources?.arbitration?.flow_control ?? 'Not exposed'],
      ]} />
    </Section>
    <M2VcModule data={data} />
    <PhysicalEstimatesSection derived={floorplanDerivedFabric} />
    {floorplanErrFabric && <Notice tone="red">{floorplanErrFabric}</Notice>}
    <Assumptions rows={[
      ['Scope', 'Declared topology and compile-result facts only. No measured utilization, achieved timing or observed packet path is shown.'],
      ['Planes', 'Plane C is declared structure, not simulated. Plane T is a declared intent with no separate router/channel artifact; its rings are illustrative.'],
      ['Return paths', '! means no reverse channel is declared; ≠ means the reverse channel differs in width or latency.'],
      ['Port dashes', 'No channel is declared on that port number. Port capacity is not declared, so a dash is not a free port.'],
      ['Shared wires', 'One driver feeds many taps; taps contend for the same wire.'],
      ['Router configuration', 'One fabric-wide RouterBehaviorArtifact covers the revision; a selected router has no independent configuration.'],
      ['Parallelism overlay', 'Coloured satellites carry a mapping row, grey ones do not. Group outlines are drawn when an axis has at most 8 groups.'],
      ['Source', 'GET /api/v1/revisions/{revision_id}/topology and compile-result.groups.resources.'],
      ['RTL delivery', 'Research RTL (M5) is reported as file presence only in Flow · Finalize & RTL (flow/run) FinalDelivery; research presence never upgrades the product preview. Product preview support is reported there, not here.'],
    ]} />
  </div><Inspector title={router ? `Router ${router.router_id}` : 'Fabric summary'}>
    {activePlane !== 'd' && <Notice tone="blue">Inspector describes the Plane D fabric; Plane {activePlane.toUpperCase()} has no per-router controls.</Notice>}
    {selectedWireLink && <Section title={`Shared wire W${selectedWireLink.shared_link_id}`} actions={<Button onClick={() => setSelectedWire(null)}>Clear</Button>}>
      <Properties rows={[
        ['Driver', `R${selectedWireLink.src_router}`],
        ['Taps', selectedWireLink.taps.map(tap => `R${tap}`).join(' · ')],
        ['Width', `${selectedWireLink.width_bits} b`],
        ['Latency', `${selectedWireLink.latency_cycles} cyc`],
        ['Resource', 'One multidrop wire; taps contend for the same wire'],
      ]} />
    </Section>}
    {router ? <>
      <h3 className="mono">R{router.router_id}</h3>
      <Properties rows={[
        ['Coordinates', (router.coordinates ?? []).length ? `[${router.coordinates.join(', ')}]` : absent],
        ['Seat capacity', String(router.seat_capacity ?? '—')],
        ['Attached endpoints', attached.length ? String(attached.length) : 'None'],
        ['Inbound / outbound channels', `${inbound.length} / ${outbound.length}`],
        ['Shared wires driven / tapped', `${outboundShared.length} / ${inboundShared.length}`],
        ['Outbound with declared return', `${outbound.filter(c => pairing(c) === 'paired').length} of ${outbound.length}`],
        ['One-way or mismatched outbound', String(outbound.filter(c => pairing(c) !== 'paired').length)],
        ['Utilization / queue occupancy', absent],
        ['Achieved timing', absent],
      ]} />
      <Notice tone="blue"><strong>One router configuration for the fabric.</strong> A control change changes the router class, not one instance.</Notice>
      {routerConfiguration(compileResult).length > 0
        ? <Section title="Derived router configuration" actions={<Badge tone="blue">compile-result</Badge>}>
            <Properties rows={factRows(routerConfiguration(compileResult))} />
          </Section>
        : <Section title="Derived router configuration">
            <p className="muted">The compile result did not expose router behavior for this revision. {data.compileResultError ?? ''}</p>
          </Section>}
      {deadlockFacts(compileResult).length > 0
        ? <Section title="Deadlock proof" actions={<Badge tone={deadlock?.status === 'PASS' ? 'green' : deadlock?.status ? 'red' : 'amber'}>{deadlock?.status ?? 'unknown'}</Badge>}>
            <Properties rows={factRows(deadlockFacts(compileResult))} />
          </Section>
        : <Section title="Deadlock proof">
            <p className="muted">No deadlock proof is exposed for this revision. {data.compileResultError ?? ''}</p>
          </Section>}
      <Section title="Fabric control" actions={<Badge tone={canEditControls ? 'blue' : 'amber'}>{canEditControls ? 'schema v4' : `schema v${schemaVersion || '—'}`}</Badge>}>
        {canEditControls ? <>
          <Properties rows={[
            ['Input buffer now', currentDepth !== undefined ? `${currentDepth} flits / VC` : 'Not declared'],
            ['Scope', 'Every router · every port · every VC'],
            ['Effect', 'Saves the draft, recompiles, and replaces the active revision'],
          ]} />
          <Button primary onClick={() => { setDepth(currentDepth ?? 8); setControlError(''); setControlOpen(true); }}>Review buffer-depth change</Button>
        </> : <Notice tone="amber">This draft is schema v{schemaVersion || '—'} without editable <code>noc_controls</code>. The control is not shown.</Notice>}
      </Section>
      {attached.length > 0 && <Section title="Declared endpoint attachments">
        <ul className="compact-list">{attached.map(item => <li key={item.endpoint_id}><span className="mono">{item.kind}#{item.endpoint_id}</span><span className="muted">port {item.port_id}</span></li>)}</ul>
      </Section>}
      <PageLink page="design/endpoints">Inspect all endpoint attachments</PageLink>
      <PageLink page="design/mapping">Inspect channel adjacency</PageLink>
      <Section title="Related design view">
        <p className="meta-line">Check how these endpoint seats map to agent groups, address windows, and RTL control reach.</p>
        <PageLink page="design/agent-map">Open agent and RTL reach map</PageLink>
      </Section>
    </> : <>
      <Properties rows={[
        ['Family', topology.family],
        ['Capability', truth ? `${truth.status}${truth.stopped_at ? ` · stopped at ${truth.stopped_at}` : ''}` : familyProbe.phase === 'loading' ? 'probing…' : 'probe unavailable'],
        ['Counts', `${topology.counts?.routers ?? 0} routers · ${topology.counts?.channels ?? topology.channels.length} directed channels · ${sharedLinks.length} shared wires · ${topology.counts?.endpoints ?? 0} endpoints`],
        ['Seats', String(topology.counts?.seats ?? '—')],
        ['Router buffer', bufferDepth !== undefined ? `${bufferDepth} flits / VC` : 'Not declared'],
        ['Derived VCs', lockedDerived?.vc_count !== undefined ? String(lockedDerived.vc_count) : 'Not derived'],
        ['Router class', resources ? 'One fabric-wide behavior artifact' : 'Not exposed'],
        ['Deadlock proof', deadlock ? `${deadlock.status ?? 'unknown'} · ${deadlock.method ?? 'method not declared'}` : 'Not exposed'],
        ['Fabric editing', explicit ? 'Explicit node/link canvas in this view' : 'Typed family; edit the declaration in the draft editor'],
        ['Logical coordinates', hasCoordinates ? 'Supplied for every router' : 'Not supplied for this family; layout derived from the channel graph'],
        ['Overlay when set to none', layer === 'none' ? 'Applied; links and nodes keep their declared geometry' : '—'],
      ]} />
      {truth && truth.status !== 'READY' && <Notice tone="amber">{truth.reason || `Stopped at ${truth.stopped_at ?? 'an undeclared stage'}.`}</Notice>}
      <PageLink page="workloads/workflow">Edit topology and NoC controls</PageLink>
      <Section title="Project identity"><Properties rows={[['Project', data.detail.project.name], ['Revision', data.detail.active_revision_id ?? '—'], ['Row source', 'GET /api/v1/revisions/{revision_id}/topology']]} /></Section>
    </>}
  </Inspector>
  {controlOpen && <Dialog title="Review fabric-wide buffer-depth change" onClose={() => { if (!savingControl) setControlOpen(false); }}>
    <Notice tone="amber">This changes every router, every port, and every VC. It is a router-class control, not a per-router override.</Notice>
    <Field label="Input buffer depth (flits per VC)" hint="Whole number 1–64. The engine clamps nothing; an invalid value is refused.">
      <input type="number" min={1} max={64} value={Number.isNaN(depth) ? '' : depth} onChange={e => { setDepth(e.target.valueAsNumber); setControlError(''); }} />
    </Field>
    {controlError && <Notice tone="red">{controlError}</Notice>}
    <Properties rows={[
      ['Revision', data.detail.active_revision_id ?? '—'],
      ['Current', currentDepth !== undefined ? `${currentDepth} flits / VC` : 'Not declared'],
      ['Proposed', validDepth ? `${depth} flits / VC` : '—'],
      ['Scope', 'Every router · every port · every VC'],
      ['Consequence', 'Saves the draft, recompiles, and replaces the active revision; existing runs become stale.'],
      ['Deadlock proof', 'Re-derived and re-run by the compiler'],
    ]} />
    <div className="dialog-actions">
      <Button onClick={() => setControlOpen(false)} disabled={savingControl}>Cancel</Button>
      <Button primary disabled={!validDepth || savingControl || depth === currentDepth} onClick={applyDepth}>{savingControl ? 'Saving & compiling…' : 'Apply and recompile'}</Button>
    </div>
  </Dialog>}
  </div>;
}

export function LiveEndpoints({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const request = data.request;
  const agents = agentsFromRequest(request);
  const endpoints = topology?.endpoints ?? [];
  const byRouter = new Map<number, number>();
  for (const e of endpoints) byRouter.set(e.router_id, (byRouter.get(e.router_id) ?? 0) + 1);
  const kinds = [...new Set(endpoints.map(e => e.kind))];
  const agentForEndpoint = (e: Topology['endpoints'][number]) => {
    const gi = (e as any).group_index;
    if (typeof gi === 'number' && agents[gi]) return agents[gi];
    return agents.find(a => a.kind === e.kind) ?? null;
  };
  return <div className="view-layout"><div className="view-main">

    <PendingDraftNotice data={data}>Agent groups come from the saved draft; endpoint seats come from the active revision. Compile to align these views.</PendingDraftNotice>
    {!topology && <TopologyMissing data={data} />}
    <Section title="Declared agent groups" actions={<Badge>{agents.reduce((n, a) => n + (a.count ?? 0), 0)} agents</Badge>}>
      {agents.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Address width</th><th>Protocol</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
        {agents.map((a, i) => <tr key={`${a.kind}-${i}`}><th>{a.kind}</th><td className="numeric">{a.count}</td><td className="numeric">{a.data_width ?? '—'} b</td><td className="numeric">{a.addr_width ?? '—'} b</td><td>{a.protocol ?? absent}</td><td>{a.clock_domain ?? absent}</td><td>{a.power_domain ?? 'Not recorded'}</td></tr>)}
      </tbody></table></div> : <Empty title="No declared agents">The project request declares no agents.</Empty>}
    </Section>
    <Section title="Attached endpoints" actions={<Badge>{endpoints.length} seats</Badge>}>
      {endpoints.length ? <>
        <div className={`table-scroll${cappedClass(endpoints.length)}`}><table><thead><tr><th>Endpoint</th><th>Kind</th><th>Router</th><th>Port</th><th>Group / index</th><th>Protocol</th><th>Data width</th><th>Address width</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
          {endpoints.map(e => {
            const agent = agentForEndpoint(e);
            return <tr key={e.endpoint_id} {...contextTarget('endpoint', e.endpoint_id, `Endpoint EP-${e.endpoint_id}`, `${e.kind} · attached to R${e.router_id} port ${e.port_id}`)}><td className="mono">EP-{e.endpoint_id}</td><td>{e.kind}</td><td className="mono">R{e.router_id}</td><td className="numeric">{e.port_id}</td><td className="mono">{(e as any).group_index ?? '—'} / {(e as any).instance_index ?? '—'}</td><td>{agent?.protocol ?? 'Not recorded'}</td><td className="numeric">{agent?.data_width !== undefined ? `${agent.data_width} b` : 'Not recorded'}</td><td className="numeric">{agent?.addr_width !== undefined ? `${agent.addr_width} b` : 'Not recorded'}</td><td>{agent?.clock_domain ?? 'Not recorded'}</td><td>{agent?.power_domain ?? 'Not recorded'}</td></tr>;
          })}
        </tbody></table></div>
        <div className="legend"><span>{kinds.join(' · ')}</span><span>{byRouter.size} routers carry endpoints</span></div>
      </> : <Empty title="No endpoints declared">The topology document declares no endpoint seats.</Empty>}
    </Section>
    <M4ProtocolBlocked data={data} />
    <Assumptions rows={[
      ['Source', 'Agent counts from the request; endpoint seats from the revision topology.'],
      ['Counts', 'Declared request counts, not a placement or a physical instance list.'],
    ]} />
  </div></div>;
}

export function LiveMapping({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  if (!topology) return <div className="view-layout"><div className="view-main"><TopologyMissing data={data} /></div></div>;
  const agents = agentsFromRequest(data.request);
  const windows = windowsFromRequest(data.request, agents);
  const matrix = accessMatrix(agents, windows);
  const resources = data.compileResult?.groups?.resources;
  const trafficClassToVCs = resources?.traffic_class_to_vcs;
  const mappingGroup = data.compileResult?.groups?.mapping;
  let coveredCells = 0;
  for (let r = 0; r < matrix.rows.length; r += 1) {
    for (let c = 0; c < matrix.cols.length; c += 1) {
      if (matrix.cell(r, c).windows > 0) coveredCells += 1;
    }
  }
  const pairs = new Map<string, { a: number; b: number; width: number; latency: number; directed: number }>();
  for (const c of topology.channels) {
    const key = c.src_router < c.dst_router ? `${c.src_router}-${c.dst_router}` : `${c.dst_router}-${c.src_router}`;
    const current = pairs.get(key) ?? { a: Math.min(c.src_router, c.dst_router), b: Math.max(c.src_router, c.dst_router), width: c.width_bits, latency: c.latency_cycles, directed: 0 };
    pairs.set(key, { ...current, directed: current.directed + 1 });
  }
  const rows = [...pairs.values()];
  const degree = new Map<number, number>();
  for (const r of rows) { degree.set(r.a, (degree.get(r.a) ?? 0) + 1); degree.set(r.b, (degree.get(r.b) ?? 0) + 1); }
  const degrees = [...new Set(degree.values())].sort((a, b) => a - b);
  return <div className="view-layout"><div className="view-main">

    <PendingDraftNotice data={data}>Channel structure and compiler artifacts describe the active revision; address windows come from the saved draft. Compile before treating the joined view as one design.</PendingDraftNotice>
    <Section title="Connection incidence matrix" actions={<Badge>declared structure</Badge>}>
      <RouterIncidenceMatrix topology={topology} />
    </Section>
    <Section title="Router adjacency from declared channels" actions={<Badge>{rows.length} undirected pairs</Badge>}>
      {rows.length ? <>
        <div className={`table-scroll${cappedClass(rows.length)}`}><table><thead><tr><th>Router pair</th><th>Channels</th><th>Width</th><th>Latency</th></tr></thead><tbody>
          {rows.map(r => <tr key={`${r.a}-${r.b}`}><th className="mono">R{r.a} ↔ R{r.b}</th><td className="numeric">{r.directed}</td><td className="numeric">{r.width} b</td><td className="numeric">{r.latency} cyc</td></tr>)}
        </tbody></table></div>
        <p className="meta-line">Router degree: {degrees.join(', ')}.</p>
      </> : <p className="meta-line">No directed channels are declared.</p>}
    </Section>
    <Section title="Mapping intent">
      <div className="mapping-intent-empty" role="group" aria-label="Initiator to target mapping is declared in the agent fabric map">
        <div className="mapping-intent-node"><strong>Initiators</strong><span>{agentsFromRequest(data.request).filter(agent => INITIATOR_KINDS.has(agent.kind)).reduce((sum, agent) => sum + agent.count, 0)} declared</span></div>
        <div className="mapping-intent-gap"><span>address windows</span><span>not permissions</span></div>
        <div className="mapping-intent-node"><strong>Targets</strong><span>{windowsFromRequest(data.request, agentsFromRequest(data.request)).length} window(s)</span></div>
      </div>
      <Properties rows={[[ 'Initiator→target mapping', windowsFromRequest(data.request, agentsFromRequest(data.request)).length ? 'Declared as address windows' : absent ], ['Access permission', 'Not in the compile schema' ], ['Routing function', data.detail.active_revision?.design?.locked_derived ? String((data.detail.active_revision.design.locked_derived as any).routing ?? '—') : 'Not declared' ], ['Guaranteed reachability', absent ], ['Observed traffic', 'No run selected in this view' ]]} />
      <PageLink page="design/agent-map">Open agent address map</PageLink>
    </Section>
    <Section title="M1 address & permission verdict (summary)" actions={<Badge>M1</Badge>}>
      <Properties rows={[
        ['Rows × cols', `${matrix.rows.length} rows × ${matrix.cols.length} cols · ${coveredCells} covered cell(s) of ${matrix.rows.length * matrix.cols.length}`],
        ['Address windows', windows.length ? `${windows.length} window(s) from request.address_map` : 'Not recorded — no address windows'],
        ['Traffic class → VC rows', trafficClassToVCs && trafficClassToVCs.length ? `${trafficClassToVCs.length} class(es): ${trafficClassToVCs.map(([cls, vcs]) => `${cls} → VC ${vcs.join(', ')}`).join(' · ')}` : 'Not recorded — no CompileResources.traffic_class_to_vcs'],
        ['Mapping group rows', mappingGroup?.rows?.length !== undefined ? `${mappingGroup.rows.length} mapped rank(s) · ${mappingGroup.rank_count ?? mappingGroup.rows.length} rank count` : 'Not recorded — no compile-result mapping group'],
        ['Allow / deny counts', 'Not modelled — no allow/deny field in the compile schema; windows are not permissions'],
        ['Permission enforcement', 'Not modelled'],
      ]} />
    </Section>
    <Assumptions rows={[
      ['Basis', 'Adjacency derived from the declared channel list; a connection is not a permitted flow.'],
      ['Mapping', 'Address windows are declared separately; per-initiator permission, routing function and guaranteed reachability are not declared.'],
      ['Source', 'GET /api/v1/revisions/{revision_id}/topology; access matrix from request.agents + request.address_map; VC rows from compileResult.groups.resources.'],
    ]} />
  </div></div>;
}

export function LiveAddresses({ data }: { data: LoadedProject }) {
  const agents = agentsFromRequest(data.request);
  const windows = windowsFromRequest(data.request, agents);
  const issues = validateWindows(windows, agents);
  const blocking = issues.filter(issue => issue.severity === 'error');
  const coverage = addressCoverage(windows);
  const decode = decodeGroup(data.compileResult);
  const resolvedRows = decode?.rows ?? [];
  const endpointById = new Map((data.topology?.endpoints ?? []).map(e => [e.endpoint_id, e]));
  if (!data.request) return <div className="view-main"><Empty title="No draft request is available">The gateway did not return a draft for this project. The address map is not inferred from the active revision.</Empty></div>;
  return <div className="view-layout"><div className="view-main">
    <PendingDraftNotice data={data}>Declared windows come from the saved draft; resolved rows and endpoint joins come from the active revision. Compile to align them.</PendingDraftNotice>
    <div className="toolbar">
      <div className="actions">
        <Badge tone={blocking.length ? 'red' : windows.length ? 'green' : 'amber'}>{blocking.length ? `${blocking.length} blocking` : windows.length ? 'Schema-clean' : 'No windows'}</Badge>
        <Badge>{formatBytes(coverage.mappedBytes)} mapped</Badge>
        <Badge tone={decode?.available ? 'blue' : 'neutral'}>{decode?.available ? `${decode.rows?.length ?? 0} resolved row(s)` : 'not compiled'}</Badge>
      </div>
      <PageLink page="design/agent-map">Edit agent address map</PageLink>
    </div>
    {windows.length ? <>
      <Section title="Declared address windows" actions={<Badge>{windows.length} window(s)</Badge>}>
        <div className="table-scroll"><table><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Target</th><th>Selection</th><th>Resolved base / size</th><th>Target router / port</th><th>Resolved endpoint</th></tr></thead><tbody>
          {windows.map(window => {
            const row = resolvedRows.find(candidate => exactMatches(candidate.base, window.base) && exactMatches(candidate.size, window.size));
            const endpoint = row?.target_endpoint_id !== undefined && row?.target_endpoint_id !== null ? endpointById.get(row.target_endpoint_id) : undefined;
            return <tr key={window.id}><th className="mono">{window.name || 'unnamed'}</th><td className="mono">{formatHex(window.base)}</td><td>{formatBytes(window.size)}</td><td>{agents[window.targetAgentIdx]?.kind ?? `agent ${window.targetAgentIdx}`}</td><td>{window.selectionPolicy ?? 'group'}{window.selectionPolicy === 'FIXED_INSTANCE' ? ` · ${window.targetInstanceIndex ?? 0}` : window.selectionPolicy === 'STRIPED' ? ` · ${formatBytes(window.interleaveBytes ?? 0n)}` : ''}</td><td className="mono">{row?.base !== undefined && row?.size !== undefined ? `${formatHex(row.base)} · ${formatBytes(row.size)}` : 'Not recorded'}</td><td className="mono">{endpoint ? `R${endpoint.router_id} / p${endpoint.port_id}` : 'Not recorded'}</td><td>{row ? `${row.target_agent_kind ?? 'target'} · endpoint ${row.target_endpoint_id ?? '—'}` : 'not in active revision'}</td></tr>;
          })}
        </tbody></table></div>
      </Section>
      <Section title="Coverage and blocking checks" actions={<Badge tone={blocking.length ? 'red' : 'green'}>{blocking.length ? `${blocking.length} open` : 'None'}</Badge>}>
        <Properties rows={[
          ['Declared bytes', formatBytes(coverage.declaredBytes)],
          ['Mapped union', formatBytes(coverage.mappedBytes)],
          ['Overlapping bytes', formatBytes(coverage.overlapBytes)],
          ['Highest end', <code>{formatHex(coverage.maxEnd)}</code>],
          ['Address transform', decode?.address_transform ?? '—'],
          ['Unmatched policy', decode?.unmatched_address_policy ?? '—'],
        ]} />
        {issues.length > 0 && <div className="table-scroll"><table><thead><tr><th>Window</th><th>Severity</th><th>Code</th><th>Detail</th></tr></thead><tbody>
          {issues.map((issue, index) => <tr key={`${issue.code}-${index}`}><th>{issue.window}</th><td><Badge tone={issue.severity === 'error' ? 'red' : 'amber'}>{issue.severity}</Badge></td><td className="mono">{issue.code}</td><td>{issue.detail}</td></tr>)}
        </tbody></table></div>}
      </Section>
    </> : <Empty title="This project declares no address windows">
      The request's <code>address_map.ranges</code> is empty. An empty map resolves to an empty decode table; target agents have no system address. Open <a href="#/design/agent-map">Agent Fabric Map</a> to place windows explicitly.
    </Empty>}
    <M1AddressEditor data={data} />
    <M1PermissionBlocked data={data} />
    <Assumptions rows={[
      ['Source', 'request.address_map from GET /projects/{id}/draft; resolved rows from compileResult.groups.address_decode.'],
      ['Computed here', 'Range name, base/size, target index, selection policy, overlap and mapped union. Resolved base/size and target router/port join the decode row to the topology attachment where available, else Not recorded.'],
      ['Decoder implementation', 'Resolved decode in Fabric Analysis; runtime enforcement Not established.'],
      ['Not claimed', 'A window is not a permission, a firewall rule, a route or a transaction completion.'],
      ['Deeper checks', 'Routing shape, port budget, island confinement and RTL reach are on Analysis · Fabric Analysis.'],
    ]} />
  </div></div>;
}

export function LiveDomains({ data }: { data: LoadedProject }) {
  const physical = designDocument(data.request).physical as Record<string, any> | undefined;
  const agents = agentsFromRequest(data.request);
  const declaredClocks = agents.filter(a => a.clock_domain);
  return <div className="view-layout"><div className="view-main">

    <Section title="Declared physical parameters">
      <Properties rows={[[ 'Network clock', physical?.clock_freq_mhz ? `${physical.clock_freq_mhz} MHz` : absent ], ['Data width', physical?.data_width ? `${physical.data_width} b` : absent ], ['Declared power domains', physical?.num_power_domains !== undefined ? String(physical.num_power_domains) : absent ], ['Process node', physical?.process_node_nm ? `${physical.process_node_nm} nm` : absent ], ['Achieved timing', absent ], ['Clock tree distance', 'Not established — no CTS backend' ], ['Isolation / retention / sequencing', absent ]]} />
    </Section>
    <Section title="Per-agent clock assignment">
      {declaredClocks.length ? <div className="table-scroll"><table><thead><tr><th>Agent kind</th><th>Clock domain</th><th>Count</th></tr></thead><tbody>
        {declaredClocks.map((a, i) => <tr key={`${a.kind}-${i}`}><th>{a.kind}</th><td className="mono">{a.clock_domain}</td><td className="numeric">{a.count}</td></tr>)}
      </tbody></table></div> : <Properties rows={[['Clock assignment', `Not recorded — ${agents.length} agent group(s) declare clock_domain: null`]]} />}
    </Section>
    <Section title="M3 CDC insertion points (blocked)">
      {declaredClocks.length ? <div className="table-scroll"><table><thead><tr><th>Source</th><th>Source domain → fabric</th><th>Cell type</th></tr></thead><tbody>
        {declaredClocks.map((a, i) => <tr key={`${a.kind}-${i}`}><th>{a.kind}</th><td className="mono">{a.clock_domain} → fabric</td><td>Not emitted in Stage 1</td></tr>)}
      </tbody></table></div> : <Properties rows={[['Crossings', 'Not recorded — no agent declares a clock domain']]} />}
    </Section>
    <Section title="Power intent">
      <Empty title="No power-intent (PF) artifact supplied">No PF artifact was supplied for this revision. Declared power-domain counts and per-agent power_domain strings are intent only; isolation, retention and sequencing are not established.</Empty>
    </Section>
    <M3DomainBlocked data={data} />
    <Assumptions rows={[
      ['Scope', 'Declared physical parameters and agent clock domains only.'],
      ['Not declared', 'Per-agent clocks, CDC, reset sequencing and power intent.'],
      ['Source', 'request.physical and request.agents clock_domain values.'],
      ['Not evaluated', 'Process-specific power or area. No STA numbers are shown.'],
    ]} />
  </div></div>;
}

export function LivePlacement({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const projectId = data.detail.project.project_id;
  const revisionId = data.detail.active_revision_id;
  const [view, setView] = useState<FloorplanView | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ pitch: 2000, footprint: 800, margin: 1000, psPerMm: 120, fixedPs: 40 });
  const valid = Object.values(form).every(value => Number.isFinite(value) && value > 0);

  useEffect(() => {
    let live = true;
    setError('');
    gateway.floorplan(projectId)
      .then(next => { if (live) setView(next); })
      .catch(failure => { if (live) setError(gatewayReason(failure)); });
    return () => { live = false; };
  }, [projectId, revisionId]);

  const declare = async () => {
    if (!valid) return;
    setSaving(true); setError('');
    try {
      const next = await gateway.putFloorplan(projectId, { mode: 'grid', grid: {
        origin_x_um: 0, origin_y_um: 0,
        pitch_x_um: form.pitch, pitch_y_um: form.pitch,
        router_width_um: form.footprint, router_height_um: form.footprint,
        margin_um: form.margin,
        wire: { ps_per_mm: form.psPerMm, fixed_ps: form.fixedPs },
      } });
      setView(next); setEditing(false);
    } catch (failure) {
      setError(gatewayReason(failure));
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    setError('');
    try { setView(await gateway.deleteFloorplan(projectId)); }
    catch (failure) { setError(gatewayReason(failure)); }
  };

  const derived = view?.derived ?? null;
  const mm2 = (um2: number) => `${(um2 / 1e6).toFixed(3)} mm²`;
  const span = (value: { min: number | null; mean: number | null; max: number | null }, unit: string) =>
    value.min === null ? '—'
      : value.min === value.max ? `${value.min.toFixed(2)} ${unit}`
      : `${value.min.toFixed(2)}–${value.max?.toFixed(2)} ${unit} (mean ${value.mean?.toFixed(2)})`;

  return <div className="view-layout"><div className="view-main">

    {!derived && <Notice tone="amber"><strong>No floorplan declared.</strong> Declare a die rule to derive area and link delay.</Notice>}
    {view?.stale && <Notice tone="amber">The declared floorplan is bound to another topology. {view.reason}</Notice>}
    {error && <Notice tone="red">{error}</Notice>}
    <Section title="Floorplan" actions={<>
      <Badge tone={derived ? 'blue' : 'amber'}>{derived ? 'declared' : 'not declared'}</Badge>
      <Button primary onClick={() => setEditing(true)}>{derived ? 'Redeclare' : 'Declare floorplan'}</Button>
      {view?.declared && <Button onClick={remove}>Remove</Button>}
    </>}>
      {derived ? <Properties rows={[
        ['Die', `${derived.die.width_um} × ${derived.die.height_um} µm · ${mm2(derived.die.area_um2)}`],
        ['Routers', `${derived.routers.count} · ${mm2(derived.routers.area_um2)} · ${(derived.routers.utilization * 100).toFixed(1)}% of die`],
        ['Links', `${derived.links.channels} channels · ${span(derived.links.length_um, 'µm')}`],
        ['Declared delay', `${span(derived.links.delay_ps, 'ps')} · ${derived.wire.ps_per_mm} ps/mm + ${derived.wire.fixed_ps} ps`],
        ['Keepouts', derived.keepouts.count ? `${derived.keepouts.count} · ${mm2(derived.keepouts.area_um2)}` : 'None'],
        ['Binding', shortText(view?.topology_hash ?? '', 24)],
      ]} /> : <Properties rows={[['Floorplan', view?.reason ?? 'Not declared']]} />}
    </Section>
    <PhysicalEstimatesSection derived={derived} />
    <Section title="Logical router coordinates" actions={<Badge>{topology?.routers.length ?? 0} routers</Badge>}>
      {topology ? <div className={`table-scroll${cappedClass(topology.routers.length)}`}><table><thead><tr><th>Router</th><th>Coordinates</th><th>Seats</th></tr></thead><tbody>
        {topology.routers.map(router => <tr key={router.router_id}><th className="mono">R{router.router_id}</th><td className="mono">[{router.coordinates.join(', ')}]</td><td className="numeric">{router.seat_capacity ?? '—'}</td></tr>)}
      </tbody></table></div> : <Empty title="No topology">Compile the draft first.</Empty>}
    </Section>
    <Assumptions rows={[
      ['Scope', 'Authored geometry: declared grid rectangles and a declared ps/mm wire model. Not PPA, extracted parasitics or signoff.'],
      ['Not evaluated', 'Congestion, DRC and LVS.'],
      ['Binding', view?.topology_hash ? `Bound to topology ${shortText(view.topology_hash, 24)}.` : 'No floorplan bound to this topology.'],
    ]} />
  </div>
  {editing && <Dialog title="Declare floorplan" onClose={() => { if (!saving) setEditing(false); }}>
    <div className="form-row">
      <Field label="Pitch (µm)"><input type="number" min={1} value={form.pitch} onChange={e => setForm({ ...form, pitch: e.target.valueAsNumber })} /></Field>
      <Field label="Router footprint (µm)"><input type="number" min={1} value={form.footprint} onChange={e => setForm({ ...form, footprint: e.target.valueAsNumber })} /></Field>
      <Field label="Die margin (µm)"><input type="number" min={1} value={form.margin} onChange={e => setForm({ ...form, margin: e.target.valueAsNumber })} /></Field>
    </div>
    <div className="form-row">
      <Field label="Wire delay (ps/mm)"><input type="number" min={1} value={form.psPerMm} onChange={e => setForm({ ...form, psPerMm: e.target.valueAsNumber })} /></Field>
      <Field label="Fixed link delay (ps)"><input type="number" min={0} value={form.fixedPs} onChange={e => setForm({ ...form, fixedPs: e.target.valueAsNumber })} /></Field>
    </div>
    <div className="dialog-actions">
      <Button onClick={() => setEditing(false)} disabled={saving}>Cancel</Button>
      <Button primary onClick={declare} disabled={saving || !valid}>{saving ? 'Declaring…' : 'Declare'}</Button>
    </div>
  </Dialog>}
  </div>;
}

function DesignToRtlHandoff({ data }: { data: LoadedProject }) {
  const projectId = data.detail.project.project_id;
  const revisionId = data.detail.active_revision_id;
  const [readiness, setReadiness] = useState<RtlReadiness | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setReadiness(null);
    setError('');
    gateway.rtlReadiness(projectId)
      .then(value => { if (live) setReadiness(value); })
      .catch(failure => { if (live) setError(gatewayReason(failure)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [projectId, revisionId, data.draftMeta?.revisionToken]);

  const draftState = data.draftMeta?.dirty ? 'Saved draft differs from the active revision' : 'Draft matches the active revision';
  const compileState = data.compileResult?.revision_id === revisionId
    ? `Compiled · ${data.compileResult.certificate?.overall ?? 'verdict recorded'}`
    : data.compileResult ? 'Compile result is for another revision' : 'No compile result for this revision';
  const rtlState = loading ? 'Checking preview support…'
    : error ? 'Readiness unavailable'
      : readiness?.preview_available ? 'Preview available'
        : readiness ? 'Preview blocked' : 'Readiness unavailable';
  const verdictCount = data.compileResult?.stage1_verdicts?.length;
  const finalRtlReason = readiness?.final_rtl_available ? 'available' : (readiness?.final_rtl_reason || 'not available').replace(/[.]+$/, '');

  return <Section title="Design → compiler → RTL preview" actions={<Badge tone={readiness?.preview_available ? 'green' : error ? 'amber' : 'neutral'}>{rtlState}</Badge>}>
    <div className="design-handoff-track">
      <div className="design-handoff-step"><span>01 · Design</span><strong className="mono">{revisionId ?? 'No active revision'}</strong><small>{draftState}</small></div>
      <div className="design-handoff-connector" aria-hidden="true">→</div>
      <div className="design-handoff-step"><span>02 · Compiler</span><strong>{compileState}</strong><small>{verdictCount === undefined ? 'Verdict data unavailable' : `${verdictCount} module verdict${verdictCount === 1 ? '' : 's'} · active revision only`}</small></div>
      <div className="design-handoff-connector" aria-hidden="true">→</div>
      <div className="design-handoff-step"><span>03 · RTL preview</span><strong>{rtlState}</strong><small>{readiness?.preview_support?.emitted_vcs ? `${readiness.preview_support.emitted_vcs} emitted VCs` : 'Topology-only emitter'}</small></div>
    </div>
    {error && <Notice tone="amber">Could not read preview readiness: {error}</Notice>}
    {readiness?.preview_blockers?.length ? <ul className="design-handoff-blockers">{readiness.preview_blockers.slice(0, 3).map((blocker, index) => <li key={`${index}-${blocker}`}>{blocker}</li>)}</ul> : null}
    {readiness && <p className="meta-line design-handoff-note"><strong>Final implementation RTL:</strong> {finalRtlReason}. A supported preview is not a complete implementation or qualification.</p>}
    <div className="actions">
      <PageLink page="design/agent-map">Inspect compiler and RTL control reach</PageLink>
      <PageLink page="flow/run" primary>Open RTL handoff</PageLink>
    </div>
  </Section>;
}

export function LiveSystem({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const agents = data.request?.agents ?? [];
  const workload = data.request?.workload;
  const noc = data.request?.noc_controls;
  const design = (data.detail.active_revision?.design ?? {}) as Record<string, any>;
  const mapping = data.compileResult?.groups?.mapping ?? null;
  const certificate = (design.locked_derived ?? null) as Record<string, unknown> | null;
  const linkWidths = topology ? [...new Set([...topology.channels.map(c => c.width_bits), ...(topology.shared_links ?? []).map(link => link.width_bits)])] : [];
  const floorplanProjectId = data.detail.project.project_id;
  const floorplanRevisionId = data.detail.active_revision_id;
  const [floorplanViewSystem, setFloorplanViewSystem] = useState<FloorplanView | null>(null);
  const [floorplanErrSystem, setFloorplanErrSystem] = useState('');
  useEffect(() => {
    let live = true;
    gateway.floorplan(floorplanProjectId).then(value => { if (live) setFloorplanViewSystem(value); }).catch(failure => { if (live) setFloorplanErrSystem(gatewayReason(failure)); });
    return () => { live = false; };
  }, [floorplanProjectId, floorplanRevisionId]);
  const floorplanDerivedSystem = floorplanViewSystem?.derived ?? null;
  return <div className="view-layout"><div className="view-main">

    <Section title="System composition" actions={<Badge>{agents.length} agent groups</Badge>}>
      <SystemDiagram agents={agents} workload={workload} topology={topology} mapping={mapping} certificate={certificate} />
    </Section>
    <DesignToRtlHandoff data={data} />
    <Section title="Declared system" actions={<Badge>{topology?.family ?? 'family not declared'}</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Element</th><th>Declared value</th><th>Evidence</th></tr></thead><tbody>
        <tr><th>Fabric</th><td>{topology ? `${topology.family} · ${topology.counts?.routers ?? 0} routers · ${topology.counts?.channels ?? 0} channels · ${topology.shared_links?.length ?? 0} shared wires` : 'No topology document'}</td><td>Revision topology</td></tr>
        {agents.map((a, i) => <tr key={`${a.kind}-${i}`}><th>{a.kind}</th><td>{a.count} × {a.data_width ?? '—'} b {a.protocol ?? ''}</td><td>Request agents</td></tr>)}
        <tr><th>Workload</th><td>{workload?.model_name ?? 'Not declared'}{workload ? ` · tp ${workload.tp ?? '—'} dp ${workload.dp ?? '—'} ep ${workload.ep ?? '—'} pp ${workload.pp ?? '—'}` : ''}</td><td>Request workload</td></tr>
        <tr><th>Collectives</th><td>{workload?.collectives?.length ? workload.collectives.map(c => `${c.kind}(${c.dimension}, ${c.payload_bytes} B)`).join(' · ') : 'None declared'}</td><td>Request workload</td></tr>
        <tr><th>Link width</th><td>{noc?.link_width ? `${noc.link_width} b` : 'Not declared'}</td><td>Request noc_controls</td></tr>
        <tr><th>Arbitration</th><td>{noc?.arbitration ?? absent}</td><td>Request noc_controls</td></tr>
        <tr><th>Derived certificate</th><td>{design.locked_derived ? `${design.locked_derived.routing ?? '—'} · VC ${design.locked_derived.vc_count ?? '—'} · ${design.locked_derived.certificate_overall ?? '—'}` : 'Not derived'}</td><td>Active revision design</td></tr>
      </tbody></table></div>
    </Section>
    {topology && <Section title="Topology summary"><div className="table-scroll"><table><thead><tr><th>Measure</th><th>Declared</th></tr></thead><tbody>
      <tr><th>Routers</th><td className="numeric">{topology.counts?.routers ?? topology.routers.length}</td></tr>
      <tr><th>Directed channels</th><td className="numeric">{topology.counts?.channels ?? topology.channels.length}</td></tr>
      <tr><th>Shared wires</th><td className="numeric">{topology.shared_links?.length ?? 0}</td></tr>
      <tr><th>Endpoint seats</th><td className="numeric">{topology.counts?.endpoints ?? topology.endpoints.length}</td></tr>
      <tr><th>Link widths</th><td className="numeric">{linkWidths.length ? `${linkWidths.join(', ')} b` : 'Not declared'}</td></tr>
    </tbody></table></div></Section>}
    <Section title="Deep Module map" actions={<Badge>stage 1 scope</Badge>}>
      <Properties rows={[
        ['M1 · Address & Permission (address_permission)', 'Addresses (design/addresses) — overlap/exclusivity, selection-policy legality, initiator→target permission coverage.'],
        ['M2 · Ordering & VC (ordering_vc)', 'Fabric topology (design/fabric-topology) — routing law, VC derivation, cycle search; derive is the single authority.'],
        ['M3 · Clock, Power & CDC (clock_power_cdc)', 'Domains (design/domains) — domain-ref integrity, multi-domain gate naming insertion points; multi-domain stays UNSUPPORTED in stage 1.'],
        ['M4 · Protocol Adapter (protocol_adapter)', 'Endpoints (design/endpoints) — closed protocol vocabulary, width/ordering compatibility, adapter requirement list. No adapter RTL in stage 1.'],
      ]} />
    </Section>
    <PhysicalEstimatesSection derived={floorplanDerivedSystem} />
    {floorplanErrSystem && <Notice tone="red">{floorplanErrSystem}</Notice>}
    <Assumptions rows={[
      ['Scope', 'Declared composition: request agents, workload, NoC controls and the derived certificate.'],
      ['Diagram', 'Block diagram, not a floorplan or a packet path; arrows imply no traffic.'],
      ['Not evaluated', 'Throughput, latency, power and area on this surface.'],
    ]} />
  </div><Inspector title="System identity">
    <Properties rows={[[ 'Project', data.detail.project.name ], ['Project id', <span className="mono">{data.detail.project.project_id}</span> ], ['Active revision', data.detail.active_revision_id ?? '—' ]]}/>
    <PageLink page="design/endpoints">Inspect endpoints</PageLink>
    <PageLink page="design/fabric-topology">Inspect the fabric</PageLink>
  </Inspector></div>;
}

export function FixtureBanner({ projectName }: { projectName: string | null }) {
  if (!projectName) return null;
  return <Notice tone="amber"><strong>{projectName} loaded; this surface still shows the fixture.</strong></Notice>;
}

export function LiveCatalog({ data, notify }: { data: LoadedProject; notify?: (message: string) => void }) {
  const { reload } = useProject();
  const agents = data.request?.agents ?? [];
  const endpoints = data.topology?.endpoints ?? [];
  const kinds = [...new Set(['compute_tile', 'hbm_controller', 'nic', ...agents.map(agent => agent.kind)])];
  const [kind, setKind] = useState(agents[0]?.kind ?? 'compute_tile');
  const [count, setCount] = useState(1);
  const [width, setWidth] = useState(agents[0]?.data_width ?? 256);
  const [protocol, setProtocol] = useState(agents[0]?.protocol ?? 'AXI');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ tone: 'blue' | 'red'; text: string } | null>(null);
  const seats = new Map<string, number>();
  for (const endpoint of endpoints) seats.set(endpoint.kind, (seats.get(endpoint.kind) ?? 0) + 1);
  const add = async () => {
    const request = data.request as Record<string, any> | null;
    if (!request || busy) return;
    setBusy(true); setFeedback(null);
    try {
      const next = { ...request, agents: [...(request.agents ?? []), { kind, count, data_width: width, addr_width: 64, protocol, clock_domain: null, power_domain: null }] };
      await gateway.putDraft(data.detail.project.project_id, next, data.draftMeta?.revisionToken);
      setFeedback({ tone: 'blue', text: `Added ${count} × ${kind} to the draft. Compile the revision to materialise topology, seats, and evaluation plans.` });
      notify?.(`Added ${count} × ${kind} to the draft. Compile the revision to materialise it.`);
      reload();
    } catch (error) {
      setFeedback({ tone: 'red', text: gatewayReason(error) });
    } finally { setBusy(false); }
  };
  return <div className="view-layout"><div className="view-main">

    <PendingDraftNotice data={data}>Agent groups are saved-draft intent; endpoint seats still come from the active revision. Compile to materialise new counts.</PendingDraftNotice>
    {feedback && <Notice tone={feedback.tone}>{feedback.text}</Notice>}
    <Section title="Declared agent groups" actions={<Badge>{agents.reduce((n, agent) => n + (agent.count ?? 0), 0)} agents</Badge>}>
      {agents.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Protocol</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
        {agents.map((agent, index) => <tr key={`${agent.kind}-${index}`}><th>{agent.kind}</th><td className="numeric">{agent.count}</td><td className="numeric">{agent.data_width ?? '—'} b</td><td>{agent.protocol ?? '—'}</td><td className="mono">{agent.clock_domain ?? 'null'}</td><td className="mono">{agent.power_domain ?? 'null'}</td></tr>)}
      </tbody></table></div> : <Empty title="This draft declares no agent groups">The request carries no agent inventory, so there is nothing to attach.</Empty>}
    </Section>
    <Section title="Add an agent group to the draft">
      <div className="form-grid">
        <Field label="Kind"><select value={kind} onChange={e => setKind(e.target.value)}>{kinds.map(value => <option key={value} value={value}>{value}</option>)}</select></Field>
        <Field label="Count"><input type="number" min={1} value={Number.isNaN(count) ? '' : count} onChange={e => setCount(e.target.valueAsNumber)} /></Field>
        <Field label="Data width (bits)"><input type="number" min={1} value={Number.isNaN(width) ? '' : width} onChange={e => setWidth(e.target.valueAsNumber)} /></Field>
        <Field label="Protocol"><input value={protocol} onChange={e => setProtocol(e.target.value)} /></Field>
      </div>
      <div className="toolbar toolbar-start">
        <Button primary disabled={busy || !data.request || !Number.isInteger(count) || count < 1 || !Number.isInteger(width) || width < 1} onClick={add}>{busy ? 'Saving…' : 'Add to draft'}</Button>
      </div>
    </Section>
    <Section title="Attached endpoint seats" actions={<Badge>{endpoints.length} seats</Badge>}>
      {seats.size ? <div className="table-scroll"><table><thead><tr><th>Endpoint kind</th><th>Seats</th></tr></thead><tbody>
        {[...seats.entries()].map(([seatKind, value]) => <tr key={seatKind}><th>{seatKind}</th><td className="numeric">{value}</td></tr>)}
      </tbody></table></div> : <Empty title="No endpoint seats in this revision">Seats appear after the topology attachment is compiled.</Empty>}
      <PageLink page="design/endpoints">Inspect endpoint attachments</PageLink>
    </Section>
    <Assumptions rows={[
      ['Agent groups', 'request.agents, authored here and written to the project draft; compile to materialise topology, seats and evaluation plans.'],
      ['Endpoint seats', 'Derived from the revision topology; not added here.'],
      ['Not present', 'RTL, implementation and interface IP descriptions.'],
    ]} />
  </div></div>;
}

export type { Topology };
