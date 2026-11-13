import { useEffect, useState, type ReactNode } from 'react';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { gateway, gatewayReason, type Topology } from './gateway';
import { ControlPlaneGraph, TopologyGraph } from './TopologyGraph';
import { FabricCanvas, toggleFabricLink, type FabricLink } from './FabricCanvas';
import { familyStatus, statusTone, useTopologyFamilies } from './capabilities';
import { Badge, Button, Dialog, Empty, Field, Icon, Inspector, Notice, PageLink, Properties, Section } from './ui';
import { deadlockFacts, routerConfiguration } from './routerConfig';
import { PARALLEL_AXES, axisDegree, parallelColor, parallelGroups, type ParallelAxis } from './parallelism';
import { contextTarget } from './contextSelection';

function PendingDraftNotice({ data, children }: { data: LoadedProject; children: ReactNode }) {
  if (!data.draftMeta?.dirty) return null;
  return <Notice tone="amber"><strong>Saved draft differs from active revision {data.detail.active_revision_id ?? '—'}.</strong> {children}</Notice>;
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
    <span>{data.topologyError || 'The gateway returned no topology document.'}</span>
    {error && <Notice tone="red">{error}</Notice>}
    <div className="toolbar toolbar-start">
      <Button primary disabled={busy} onClick={compile}>{busy ? 'Compiling…' : 'Compile draft'}</Button>
      <PageLink page="workloads/workflow">Open project workflow</PageLink>
    </div>
  </Empty>;
}

function FindingRow({ finding, onSelect }: { finding: { code: string; text: string; router: number }; onSelect: () => void }) {
  return <button type="button" className="finding-row" onClick={onSelect}>
    <span className="finding-code mono">{finding.code}</span>
    <span className="finding-text">{finding.text}</span>
    <span className="finding-target mono">R{finding.router}</span>
    <Icon name="arrow" size={13} />
  </button>;
}

export function LiveFabric({ data, notify, banner }: { data: LoadedProject; notify?: (message: string) => void; banner?: ReactNode }) {
  const topology = data.topology;
  const sharedLinks = topology?.shared_links ?? [];
  const { reload } = useProject();
  const [selected, setSelected] = useState<number | null>(null);
  const [selectedWire, setSelectedWire] = useState<number | null>(null);
  const [filter, setFilter] = useState('');
  const [zoom, setZoom] = useState(100);
  const [plane, setPlane] = useState<'d' | 'c' | 't'>('d');
  const [parallelAxis, setParallelAxis] = useState<'none' | ParallelAxis>('none');
  const [treeTab, setTreeTab] = useState<'routers' | 'wires'>('routers');
  const [showWires, setShowWires] = useState(false);
  const [controlOpen, setControlOpen] = useState(false);
  const [depth, setDepth] = useState(8);
  const [controlError, setControlError] = useState('');
  const [savingControl, setSavingControl] = useState(false);
  const [editingGraph, setEditingGraph] = useState(false);
  const [savingGraph, setSavingGraph] = useState(false);
  const [graphFeedback, setGraphFeedback] = useState<{ tone: 'blue' | 'red'; text: string } | null>(null);
  const familyProbe = useTopologyFamilies();
  const request = data.request as Record<string, any> | null;
  const explicit = request?.topology?.kind === 'explicit' ? request.topology.graph : request?.explicit_topology ?? null;
  const linksOf = (graph: any): FabricLink[] => (Array.isArray(graph?.links) ? graph.links : []).filter((pair: any) => Array.isArray(pair) && pair.length === 2).map((pair: any) => [Number(pair[0]), Number(pair[1])] as FabricLink);
  const [graphLinks, setGraphLinks] = useState<FabricLink[]>(() => linksOf(explicit));
  useEffect(() => { setGraphLinks(linksOf(explicit)); setGraphFeedback(null); }, [data.detail.project.project_id, data.detail.active_revision_id]);

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
  const byPair = new Map(topology.channels.map(c => [`${c.src_router}:${c.dst_router}`, c]));
  const pairing = (c: Topology['channels'][number]) => {
    const back = byPair.get(`${c.dst_router}:${c.src_router}`);
    if (!back) return 'missing' as const;
    return back.width_bits === c.width_bits && back.latency_cycles === c.latency_cycles ? 'paired' as const : 'mismatch' as const;
  };
  const unpaired = topology.channels.filter(c => pairing(c) !== 'paired');
  const selectRouter = (id: number) => { setSelectedWire(null); setSelected(id === selected ? null : id); };
  const selectWire = (id: number | null) => { setSelected(null); setSelectedWire(id); setShowWires(true); };
  const coordOf = (item: Topology['routers'][number]) => item.coordinates ?? [];
  const hasCoordinates = topology.routers.length > 0 && topology.routers.every(item => coordOf(item).length >= 2);
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
    for (const [row, routers] of [...byRow.entries()].sort((a, b) => a[0] - b[0])) {
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
  const lockedDerived = (data.detail.active_revision?.design as Record<string, any> | undefined)?.locked_derived;
  const compileResult = data.compileResult;
  const resources = compileResult?.groups?.resources;
  const deadlock = resources?.deadlock;
  const requestTopology = request?.topology;
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
  const nocControls = request?.noc_controls;
  const schemaVersion = Number(request?.schema_version ?? 0);
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

  const openWires = () => { setTreeTab('wires'); setShowWires(true); };
  const clearSelection = () => { setSelected(null); setSelectedWire(null); };

  return <div className="view-layout fabric-view"><div className="view-main">
    {banner}
    <PendingDraftNotice data={data}>Compile the saved draft before expecting topology changes here.</PendingDraftNotice>

    <div className="fabric-toolbar">
      <div className="fabric-toolbar-main">
        <Badge tone={truth ? statusTone(truth.status) : 'neutral'}>{truth ? truth.status : familyProbe.phase === 'loading' ? 'probing…' : 'no capability row'}</Badge>
        <span className="mono fabric-counts">{topology.family} · {topology.counts?.routers ?? topology.routers.length} routers{topology.channels.length > 0 ? ` · ${topology.channels.length} directed channels` : ''}{sharedLinks.length > 0 ? ` · ${sharedLinks.length} shared wires` : ''} · {topology.counts?.endpoints ?? topology.endpoints.length} endpoints</span>
        {declaredPlanes.length > 1 && <div className="segmented fabric-plane-tabs" role="group" aria-label="Packet plane">
          {declaredPlanes.map(value => <button type="button" key={value} className={activePlane === value ? 'active' : ''} onClick={() => { setPlane(value as 'd' | 'c' | 't'); clearSelection(); }}>
            {value === 'd' ? 'Data' : value === 'c' ? 'Control' : 'Telemetry'}
          </button>)}
        </div>}
      </div>
      <div className="actions fabric-toolbar-actions">
        {findings.length > 0 && <button type="button" className={`fabric-finding-chip${selected === null ? ' active' : ''}`} onClick={clearSelection} title="Show declared-structure findings">
          <Icon name="warning" size={13} />{findings.length} finding{findings.length === 1 ? '' : 's'}
        </button>}
        {mappingAvailable && activePlane === 'd' && <label className="fabric-axis-control">
          <span>Parallelism</span>
          <select aria-label="Parallelism overlay" value={activeParallelAxis ?? 'none'} onChange={e => setParallelAxis(e.target.value as 'none' | ParallelAxis)}>
            <option value="none">None</option>
            {PARALLEL_AXES.map(axis => <option key={axis} value={axis} disabled={axisDegree(parallelism, axis) <= 1}>{axis.toUpperCase()} · {axisDegree(parallelism, axis)}</option>)}
          </select>
        </label>}
        {activePlane === 'd' && sharedLinks.length > 0 && <button type="button" className={`fabric-wire-toggle${showWires ? ' active' : ''}`} aria-pressed={showWires} onClick={() => setShowWires(value => !value)} title={showWires ? 'Hide shared wires' : 'Show shared wires'}>
          <Icon name="layers" size={13} />Wires
        </button>}
        <div className="zoom-control">
          <button type="button" className="zoom-button" onClick={() => setZoom(value => Math.max(50, value - 10))} title="Zoom out" aria-label="Zoom out">−</button>
          <span className="mono">{zoom}%</span>
          <button type="button" className="zoom-button" onClick={() => setZoom(value => Math.min(200, value + 10))} title="Zoom in" aria-label="Zoom in">+</button>
          <button type="button" className="zoom-button fit" onClick={() => setZoom(100)}>Fit</button>
        </div>
        {explicit && activePlane === 'd' && <Button onClick={() => setEditingGraph(value => !value)}>{editingGraph ? 'Done' : 'Edit links'}</Button>}
        <a className="button" href="#/workloads/workflow" onClick={() => { try { sessionStorage.setItem(`srota-intent-tab:${data.detail.project.project_id}`, 'fabric'); } catch { /* The link still opens the workflow if storage is unavailable. */ } }}>Edit topology</a>
      </div>
    </div>

    <div className="fabric-workbench">
      <aside className="fabric-tree" aria-label="Fabric objects">
        {activePlane === 'd' ? <>
          <div className="fabric-tree-tabs segmented" role="group" aria-label="Fabric tree view">
            <button type="button" className={treeTab === 'routers' ? 'active' : ''} aria-pressed={treeTab === 'routers'} onClick={() => { setTreeTab('routers'); setSelectedWire(null); }}>Routers</button>
            <button type="button" className={treeTab === 'wires' ? 'active' : ''} aria-pressed={treeTab === 'wires'} onClick={openWires}>Wires {sharedLinks.length}</button>
          </div>
          {treeTab === 'wires' && sharedLinks.length > 0
            ? <div className="fabric-tree-scroll">
              {sharedLinks.map(link => <button type="button" key={link.shared_link_id} className={`tree-wire${selectedWire === link.shared_link_id ? ' selected' : ''}`} title={`W${link.shared_link_id} · R${link.src_router} → ${link.taps.map(tap => `R${tap}`).join(' · ')} · ${link.width_bits} b · ${link.latency_cycles} cyc`} onClick={() => selectWire(selectedWire === link.shared_link_id ? null : link.shared_link_id)}>
                <span className="mono">W{link.shared_link_id}</span>
                <span className="tree-wire-path mono">R{link.src_router} → {link.taps.map(tap => `R${tap}`).join('·')}</span>
              </button>)}
            </div>
            : <>
              <div className="fabric-search">
                <Icon name="search" size={13} />
                <input aria-label="Filter fabric entities" placeholder="Filter routers, endpoints" value={filter} onChange={e => setFilter(e.target.value)} />
              </div>
              <div className="fabric-tree-scroll">
                {rowGroups.map(group => <div key={group.key} className="tree-group">
                  <div className="tree-row-head"><span>{group.label}</span><span>{group.routers.length}</span></div>
                  {group.routers.map(item => <button type="button" key={item.router_id} className={`tree-router${selected === item.router_id ? ' selected' : ''}`} {...contextTarget('router', item.router_id, `Router R${item.router_id}`, `${topology.family} · ${endpointCount(item.router_id)} attached endpoint${endpointCount(item.router_id) === 1 ? '' : 's'}`)} onClick={() => selectRouter(item.router_id)}>
                    <span className="mono">R{item.router_id}</span><small>{endpointCount(item.router_id)} EP</small>
                  </button>)}
                </div>)}
                {matchingRouters.length === 0 && <p className="meta-line">No router matches.</p>}
                <div className="tree-group">
                  <div className="tree-row-head"><span>Endpoints</span><span>{topology.endpoints.length}</span></div>
                  {matchingEndpoints.slice(0, 80).map(item => <button type="button" key={item.endpoint_id} className="tree-endpoint" {...contextTarget('endpoint', item.endpoint_id, `Endpoint EP-${item.endpoint_id}`, `${item.kind} · attached to R${item.router_id} port ${item.port_id}`)} onClick={() => selectRouter(item.router_id)}>
                    <span className="mono">{item.kind}#{item.endpoint_id}</span><span>R{item.router_id} · p{item.port_id}</span>
                  </button>)}
                  {matchingEndpoints.length > 80 && <p className="meta-line">80 of {matchingEndpoints.length} shown. Filter to narrow.</p>}
                  {matchingEndpoints.length === 0 && <p className="meta-line">No endpoint matches.</p>}
                </div>
              </div>
            </>}
        </> : <div className="fabric-tree-scroll"><p className="meta-line">Plane {activePlane.toUpperCase()} has no per-router selection.</p></div>}
      </aside>

      <div className="fabric-center">
        <div className="fabric-canvas-scroll">
          <div className="fabric-canvas" style={{ width: `${zoom}%`, height: `${zoom}%` }}>
            {activePlane === 'c'
              ? controlSubnet
                ? <ControlPlaneGraph k={controlSubnet.k} c={controlSubnet.c} routing={controlSubnet.routing} vcs={controlSubnet.vcs} />
                : <Empty title="Plane C is declared but not materialized">The compile result carries no control-plane artifact for this revision. {controlPlane?.reason ?? ''}</Empty>
              : editingGraph && explicit && activePlane === 'd'
                ? <FabricCanvas nodes={Number(explicit.nodes) || 0} links={graphLinks} onToggleLink={(a, b) => setGraphLinks(list => toggleFabricLink(list, a, b))} />
                : <TopologyGraph topology={topology} selected={activePlane === 'd' ? selected : null} onSelect={activePlane === 'd' ? selectRouter : undefined} telemetry={activePlane === 't'} selectedWire={activePlane === 'd' && selectedWireLink ? selectedWire : null} onSelectWire={activePlane === 'd' ? selectWire : undefined} mappingRows={activePlane === 'd' ? mappingRows : undefined} axis={activePlane === 'd' ? activeParallelAxis : null} degreeCount={activePlane === 'd' ? selectedAxisDegree : undefined} labels={topology.routers.length <= 64} showSharedWires={showWires || selectedWire !== null} />}
          </div>
          {activePlane === 'd' && selected === null && selectedWire === null && !editingGraph && <div className="fabric-canvas-hint">Select a router or wire to inspect</div>}
          {activePlane === 'd' && activeParallelAxis && <div className="fabric-axis-panel">
            <div className="fabric-axis-head"><h2>Parallelism mapping</h2><Badge>{activeParallelAxis.toUpperCase()} {selectedAxisDegree}</Badge></div>
            <table><tbody>{axisGroups.map(group => <tr key={group.coordinate}>
              <th scope="row"><span className="parallel-swatch" style={{ background: parallelColor(group.coordinate, selectedAxisDegree) }} />{activeParallelAxis.toUpperCase()} {group.coordinate}</th>
              <td className="numeric">{group.ranks} ranks</td>
              <td className="mono">{group.routers.length ? group.routers.map(router => `R${router}`).join(' · ') : 'unmapped'}</td>
            </tr>)}</tbody></table>
          </div>}
        </div>

        {activePlane === 'c' && <div className="fabric-plane-sheet">
          <div className="fabric-plane-head"><h2>Plane C · declared subnet</h2><Badge tone="amber">declared structure</Badge></div>
          {controlSubnet ? <Properties rows={[
            ['Subnet', String(controlSubnet.id)],
            ['Mesh', `${controlSubnet.k}×${controlSubnet.k} · ${controlSubnet.k * controlSubnet.k} routers · ${controlSubnet.c} seats/router`],
            ['Routing', controlSubnet.routing.toUpperCase()],
            ['Virtual channels', controlSubnet.vcs.join(' / ')],
            ['Class → subnet', controlPlane?.class_to_subnet?.rows?.length ? controlPlane.class_to_subnet.rows.map(row => `${row.traffic_class}: subnet ${row.subnet}`).join(' · ') : 'No class→subnet binding materialized'],
          ]} /> : <Notice tone="amber">Plane C is declared in the topology, but the compile result carries no control-plane artifact. {controlPlane?.reason ?? ''}</Notice>}
        </div>}
        {activePlane === 't' && <div className="fabric-plane-sheet">
          <div className="fabric-plane-head"><h2>Plane T · telemetry</h2><Badge tone="amber">declared overlay</Badge></div>
          <Properties rows={[
            ['Period', telPeriod !== undefined ? `${telPeriod} cycles` : 'Not declared'],
            ['Latency', telLatency !== undefined ? `${telLatency} cycles` : 'Not declared'],
            ['Topology', 'No separate Plane T router/channel artifact'],
          ]} />
        </div>}

        {activePlane === 'd' && selectedWireLink && <div className="fabric-wire-strip">
          <span><strong className="mono">W{selectedWireLink.shared_link_id}</strong></span>
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
      </div>
    </div>

    {topology.channels.length === 0 && sharedLinks.length === 0 && <Notice tone="amber"><strong>No channels or shared wires in this topology.</strong> Routers and endpoint seats exist; link structure is absent from the payload.</Notice>}
  </div>

  <Inspector title={selectedWireLink ? 'Wire' : router ? 'Router' : 'Fabric'}>
    {activePlane !== 'd' && <Notice tone="blue">Inspector describes the data plane. Switch to Data to select routers and wires.</Notice>}
    {selectedWireLink && <Section title="Shared wire">
      <Properties rows={[
        ['Driver', `R${selectedWireLink.src_router}`],
        ['Taps', selectedWireLink.taps.map(tap => `R${tap}`).join(' · ')],
        ['Width', `${selectedWireLink.width_bits} b`],
        ['Latency', `${selectedWireLink.latency_cycles} cyc`],
        ['Resource', 'One multidrop wire; taps contend for the same wire'],
      ]} />
    </Section>}
    {!selectedWireLink && router ? <>
      <div className="inspector-title-row"><h3 className="mono">R{router.router_id}</h3><Badge tone="blue">{(router.coordinates ?? []).length ? `[${(router.coordinates ?? []).join(', ')}]` : 'coordinates not declared'}</Badge></div>
      <Properties rows={[
        ['Seat capacity', String(router.seat_capacity ?? '—')],
        ['Attached endpoints', attached.length ? String(attached.length) : 'None'],
        ['Inbound / outbound', `${inbound.length} / ${outbound.length}`],
        ['Shared wires driven / tapped', `${outboundShared.length} / ${inboundShared.length}`],
        ['Declared return paths', `${outbound.filter(c => pairing(c) === 'paired').length} of ${outbound.length}`],
        ['Timing / occupancy', <span className="muted">Not declared in this payload</span>],
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
          ]} />
          <Button primary onClick={() => { setDepth(currentDepth ?? 8); setControlError(''); setControlOpen(true); }}>Review buffer-depth change</Button>
        </> : <Notice tone="amber">This draft is schema v{schemaVersion || '—'} without editable <code>noc_controls</code>.</Notice>}
      </Section>
      {attached.length > 0 && <Section title={`Declared endpoints · ${attached.length}`}>
        <ul className="compact-list">{attached.map(item => <li key={item.endpoint_id}><span className="mono">{item.kind}#{item.endpoint_id}</span><span className="muted">port {item.port_id}</span></li>)}</ul>
      </Section>}
      <div className="inspector-links">
        <PageLink page="design/endpoints">Endpoint attachments</PageLink>
        <PageLink page="design/agent-map">Open agent and RTL reach map</PageLink>
      </div>
    </> : !selectedWireLink && <>
      <Properties rows={[
        ['Family', topology.family],
        ['Capability', truth ? `${truth.status}${truth.stopped_at ? ` · stopped at ${truth.stopped_at}` : ''}` : familyProbe.phase === 'loading' ? 'probing…' : 'No registered row for this family'],
        ['Router buffer', bufferDepth !== undefined ? `${bufferDepth} flits / VC` : 'Not declared'],
        ['Derived VCs', lockedDerived?.vc_count !== undefined ? String(lockedDerived.vc_count) : 'Not derived'],
        ['Deadlock proof', deadlock ? `${deadlock.status ?? 'unknown'} · ${deadlock.method ?? 'method not declared'}` : 'Not exposed'],
      ]} />
      {truth && truth.status !== 'READY' && <Notice tone="amber">{truth.reason || `Stopped at ${truth.stopped_at ?? 'an undeclared stage'}.`}</Notice>}
      {!truth && familyProbe.phase === 'ready' && <Notice tone="amber"><strong>No capability row for family “{topology.family}”.</strong> Structural checks and the deadlock proof still run. Materialization, evaluation and qualification are not established by a family probe.</Notice>}
      {findings.length > 0
        ? <Section title={`Findings · ${findings.length}`} actions={<Badge tone="amber">review</Badge>}>
            <div className="finding-list">{findings.map(item => <FindingRow key={item.code} finding={item} onSelect={() => selectRouter(item.router)} />)}</div>
          </Section>
        : <p className="quiet-line">No declared-structure findings.</p>}
      <div className="inspector-links">
        <a className="button" href="#/workloads/workflow" onClick={() => { try { sessionStorage.setItem(`srota-intent-tab:${data.detail.project.project_id}`, 'fabric'); } catch { /* The link still opens the workflow if storage is unavailable. */ } }}>Edit topology and NoC controls</a>
        <PageLink page="analysis/topology">Open analysis overlay</PageLink>
      </div>
      {declaredPlanes.length > 1 && <div className="fabric-plane-facts">
        <span>Plane C</span><span>{controlSubnet ? `${controlSubnet.k}×${controlSubnet.k} · ${controlSubnet.c} seats` : 'not materialized'}</span>
        <span>Plane T</span><span>{telPeriod !== undefined ? `period ${telPeriod} cycles` : 'not declared'}</span>
      </div>}
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
    ]} />
    <div className="dialog-actions">
      <Button onClick={() => setControlOpen(false)} disabled={savingControl}>Cancel</Button>
      <Button primary disabled={!validDepth || savingControl || depth === currentDepth} onClick={applyDepth}>{savingControl ? 'Saving & compiling…' : 'Apply and recompile'}</Button>
    </div>
  </Dialog>}
  </div>;
}
