import { useState } from 'react';
import type { LoadedProject } from './project';
import type { Topology } from './gateway';
import { TopologyGraph } from './TopologyGraph';
import { Badge, Empty, Inspector, Notice, PageLink, Properties, Section } from './ui';

const short = (hash?: string | null, keep = 20) => hash ? `${hash.slice(0, keep)}…` : '—';
const absent = <Badge tone="amber">Not declared in this payload</Badge>;
// Long declared-data lists scroll inside a bounded box rather than stretching the page or hiding rows.
const cappedClass = (count: number, limit = 12) => count > limit ? ' capped' : '';

export function LiveBanner({ data }: { data: LoadedProject }) {
  return <Notice tone="blue"><strong>Live project data · {data.detail.project.name}</strong> ({data.detail.project.project_id} · {data.detail.active_revision_id}). </Notice>;
}

function useTopology(data: LoadedProject) {
  return data.topology;
}

function TopologyMissing({ data }: { data: LoadedProject }) {
  return <Empty title="No topology available for this revision">{data.topologyError || 'The gateway returned no topology document.'} Nothing is substituted.</Empty>;
}

export function LiveFabric({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const [selected, setSelected] = useState<number | null>(null);
  const [layer, setLayer] = useState<'physical' | 'none'>('physical');
  const [channelView, setChannelView] = useState<'router' | 'channel'>('router');
  const [hovered, setHovered] = useState<Topology['channels'][number] | null>(null);
  if (!topology) return <div className="view-layout"><div className="view-main"><LiveBanner data={data} /><TopologyMissing data={data} /></div></div>;
  const router = selected === null ? null : topology.routers.find(r => r.router_id === selected) ?? null;
  const inbound = selected === null ? [] : topology.channels.filter(c => c.dst_router === selected);
  const outbound = selected === null ? [] : topology.channels.filter(c => c.src_router === selected);
  const attached = selected === null ? [] : topology.endpoints.filter(e => e.router_id === selected);
  const widths = [...new Set(topology.channels.map(c => c.width_bits))];
  const latencies = [...new Set(topology.channels.map(c => c.latency_cycles))];
  const shownChannels = selected === null ? topology.channels : topology.channels.filter(c => c.src_router === selected || c.dst_router === selected);
  const uniformChannels = widths.length === 1 && latencies.length === 1;
  // Declared return-path check: a channel is paired when the reverse channel exists with the same width and latency.
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
  return <div className="view-layout"><div className="view-main">
    <LiveBanner data={data} />
    <div className="toolbar">
      <select aria-label="Overlay layer" value={layer} onChange={e => setLayer(e.target.value as typeof layer)}>
        <option value="physical">Declared channels and attachments</option>
        <option value="none">No overlay</option>
      </select>
      <Badge>{topology.family} · {topology.counts?.routers ?? 0} routers</Badge>
      <Badge>{widths.join('/')} bit links · {latencies.join('/')} cycle latency</Badge>
      <Badge tone="amber">No utilization, arbitration, or timing result</Badge>
    </div>
    <Notice tone="blue"><strong>Declared geometry only.</strong> No simulation, queue, or timing data.</Notice>
    <Section title="Declared topology" actions={<span className="mono muted">{selected === null ? 'select a router' : `router ${selected} selected`}</span>}>
      <TopologyGraph topology={topology} selected={selected} onSelect={selectRouter} highlight={hovered} />
      <Properties rows={[[ 'Family', topology.family ], ['Counts', `${topology.counts?.routers ?? 0} routers · ${topology.counts?.channels ?? topology.channels.length} directed channels · ${topology.counts?.endpoints ?? 0} endpoints` ], ['Seats', String(topology.counts?.seats ?? '—') ], ['Logical coordinates', topology.routers.every(r => (r.coordinates ?? []).length >= 2) ? 'Supplied for every router' : 'Not supplied for this family; layout derived from the channel graph' ], ['Topology hash', <span className="mono">{short(topology.topology_hash)}</span> ], ['Attachment hash', <span className="mono">{short(topology.attachment_hash)}</span> ], ['Design hash', <span className="mono">{short(topology.design_hash)}</span> ], ['Overlay when set to none', layer === 'none' ? 'Applied; links and nodes keep their declared geometry' : '—' ]]} />
    </Section>
    <Section title="Declared channels" actions={<>
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
                    <button type="button" className={`channel-chip ${state}`} title={`R${c.src_router} / p${c.src_port} → R${c.dst_router} / p${c.dst_port} · ${pairingLabel[state]}`} aria-label={`Router ${c.src_router} port ${c.src_port} to router ${c.dst_router} port ${c.dst_port}, ${pairingLabel[state]}`} {...linkHandlers(c)} onClick={() => selectRouter(row.id)}>
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
              return <tr key={`${c.src_router}:${c.src_port}->${c.dst_router}:${c.dst_port}`} className="channel-row" tabIndex={0} aria-label={`Router ${c.src_router} port ${c.src_port} to router ${c.dst_router} port ${c.dst_port}, ${pairingLabel[state]}`} {...linkHandlers(c)} onClick={() => selectRouter(c.src_router)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectRouter(c.src_router); } }}>
                <td className="mono">R{c.src_router} / p{c.src_port} <span className="muted">→</span> R{c.dst_router} / p{c.dst_port}</td>
                {unpaired.length > 0 && <td className={state === 'paired' ? 'muted' : state === 'missing' ? 'warn-text' : 'error-text'}>{state === 'paired' ? 'same' : state === 'missing' ? '! none' : '≠ differs'}</td>}
                {!uniformChannels && <><td className="numeric">{c.width_bits} b</td><td className="numeric">{c.latency_cycles} cyc</td></>}
              </tr>;
            })}
            {shownChannels.length === 0 && <tr><td className="muted" colSpan={1 + (unpaired.length > 0 ? 1 : 0) + (uniformChannels ? 0 : 2)}>No declared channel touches router {selected}.</td></tr>}
          </tbody></table>
        </div>}
      <p>{uniformChannels ? `Every declared channel is ${widths[0]} b wide at ${latencies[0]} cycle latency. ` : ''}{selected === null ? `All ${topology.channels.length} directed channels are declared; select a router to filter them.` : `Filtered to the channels touching router ${selected}; select it again to clear.`} Hover or focus a channel to trace that exact directed link in the graph, and activate it to select its source router. {unpaired.length === 0 ? 'Every declared channel has a matching return channel at the same width and latency. ' : `${unpaired.length} of ${topology.channels.length} declared channels lack a matching return: ! means no reverse channel is declared, ≠ means the reverse channel differs in width or latency. `}{channelView === 'router' ? 'A dash means no channel is declared on that port number — port capacity is not declared, so a dash is not a free port. ' : ''}Direction is the declared channel direction, not an observed packet path.</p>
    </Section>
  </div><Inspector title={router ? `Router ${router.router_id}` : 'Fabric inspector'}>
    {router ? <>
      <h3 className="mono">R{router.router_id}</h3>
      <Properties rows={[[ 'Coordinates', (router.coordinates ?? []).length ? `[${router.coordinates.join(', ')}]` : absent ], ['Seat capacity', String(router.seat_capacity ?? '—') ], ['Inbound channels', String(inbound.length) ], ['Outbound channels', String(outbound.length) ], ['Outbound with declared return', `${outbound.filter(c => pairing(c) === 'paired').length} of ${outbound.length}` ], ['One-way or mismatched outbound', String(outbound.filter(c => pairing(c) !== 'paired').length) ], ['Attached endpoints', attached.length ? attached.map(e => `${e.kind}#${e.endpoint_id} (port ${e.port_id})`).join(', ') : 'None' ], ['Utilization / queue occupancy', absent ], ['Achieved timing', absent ]]} />
      <PageLink page="design/endpoints">Inspect all endpoint attachments</PageLink>
      <PageLink page="design/mapping">Inspect channel adjacency</PageLink>
    </> : <p>Select a router node to inspect its declared ports, channels, and attachments.</p>}
    <Section title="Project identity"><Properties rows={[[ 'Project', data.detail.project.name ], ['Revision', data.detail.active_revision_id ?? '—' ], ['Design hash', <span className="mono">{short(data.detail.active_revision?.design_hash)}</span> ], ['Row source', 'GET /api/v1/revisions/{revision_id}/topology' ]]} /></Section>
  </Inspector></div>;
}

export function LiveEndpoints({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const request = data.request;
  const agents = request?.agents ?? [];
  const endpoints = topology?.endpoints ?? [];
  const byRouter = new Map<number, number>();
  for (const e of endpoints) byRouter.set(e.router_id, (byRouter.get(e.router_id) ?? 0) + 1);
  const kinds = [...new Set(endpoints.map(e => e.kind))];
  return <div className="view-layout"><div className="view-main">
    <LiveBanner data={data} />
    {!topology && <TopologyMissing data={data} />}
    <Section title="Declared agent groups" actions={<Badge>{agents.reduce((n, a) => n + (a.count ?? 0), 0)} agents</Badge>}>
      {agents.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Address width</th><th>Protocol</th><th>Clock domain</th></tr></thead><tbody>
        {agents.map((a, i) => <tr key={`${a.kind}-${i}`}><th>{a.kind}</th><td className="numeric">{a.count}</td><td className="numeric">{a.data_width ?? '—'} b</td><td className="numeric">{a.addr_width ?? '—'} b</td><td>{a.protocol ?? absent}</td><td>{a.clock_domain ?? absent}</td></tr>)}
      </tbody></table></div> : <Empty title="No declared agents">The project request declares no agents.</Empty>}
      <p>Counts are the declared request; they are not a placement or a physical instance list.</p>
    </Section>
    <Section title="Attached endpoints" actions={<Badge>{endpoints.length} seats</Badge>}>
      {endpoints.length ? <>
        <div className={`table-scroll${cappedClass(endpoints.length)}`}><table><thead><tr><th>Endpoint</th><th>Kind</th><th>Router</th><th>Port</th><th>Group / index</th></tr></thead><tbody>
          {endpoints.map(e => <tr key={e.endpoint_id}><td className="mono">EP-{e.endpoint_id}</td><td>{e.kind}</td><td className="mono">R{e.router_id}</td><td className="numeric">{e.port_id}</td><td className="mono">{(e as any).group_index ?? '—'} / {(e as any).instance_index ?? '—'}</td></tr>)}
        </tbody></table></div>
        <div className="legend"><span>{kinds.join(' · ')}</span><span>{byRouter.size} routers carry endpoints</span></div>
      </> : <Empty title="No endpoints declared">The topology document declares no endpoint seats.</Empty>}
    </Section>
  </div><Inspector title="Endpoint boundary">
    <Properties rows={[[ 'Source', 'agents from the request; seats from the revision topology' ], ['Attachment hash', <span className="mono">{short(topology?.attachment_hash)}</span> ], ['Address assignment', data.request?.address_map?.ranges?.length ? 'Declared ranges exist; see Address Map' : absent ], ['Permission intent', absent ], ['Protocol behaviour', absent ], ['CDC implementation', absent ]]} />
    <PageLink page="design/addresses">Inspect address map</PageLink>
    <PageLink page="design/fabric-topology">Inspect the fabric</PageLink>
  </Inspector></div>;
}

export function LiveMapping({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  if (!topology) return <div className="view-layout"><div className="view-main"><LiveBanner data={data} /><TopologyMissing data={data} /></div></div>;
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
    <LiveBanner data={data} />
    <Notice tone="amber"><strong>Adjacency ≠ permission.</strong> No mapping or access rules are declared.</Notice>
    <Section title="Router adjacency from declared channels" actions={<Badge>{rows.length} undirected pairs</Badge>}>
      <div className={`table-scroll${cappedClass(rows.length)}`}><table><thead><tr><th>Router pair</th><th>Channels</th><th>Width</th><th>Latency</th></tr></thead><tbody>
        {rows.map(r => <tr key={`${r.a}-${r.b}`}><th className="mono">R{r.a} ↔ R{r.b}</th><td className="numeric">{r.directed}</td><td className="numeric">{r.width} b</td><td className="numeric">{r.latency} cyc</td></tr>)}
      </tbody></table></div>
      <p>Router degree in this graph: {degrees.join(', ')}. Every pair is adjacency, not a permitted flow.</p>
    </Section>
    <Section title="Absent mapping intent">
      <Properties rows={[[ 'Initiator→target mapping', absent ], ['Access permission', absent ], ['Routing function', data.detail.active_revision?.design?.locked_derived ? String((data.detail.active_revision.design.locked_derived as any).routing ?? '—') : 'Not declared' ], ['Guaranteed reachability', absent ], ['Observed traffic', 'No run selected in this view' ]]} />
    </Section>
  </div><Inspector title="Mapping boundary">
    <Properties rows={[[ 'Rows', 'Derived from the declared channel list' ], ['Permission enforcement', 'Not modelled' ], ['Protocol compatibility', 'Not evaluated' ], ['Route validity proof', 'Not evaluated here' ], ['Source endpoint', 'GET /api/v1/revisions/{revision_id}/topology' ]]} />
    <PageLink page="design/fabric-topology">Inspect the fabric graph</PageLink>
    <PageLink page="verify/checks">Review verification scope</PageLink>
  </Inspector></div>;
}

export function LiveAddresses({ data }: { data: LoadedProject }) {
  const ranges = data.request?.address_map?.ranges ?? [];
  return <div className="view-layout"><div className="view-main">
    <LiveBanner data={data} />
    {ranges.length ? <Section title="Declared address ranges" actions={<Badge>{ranges.length} ranges</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Target</th></tr></thead><tbody>
        {ranges.map((r, i) => <tr key={`${r.name ?? i}`}><th>{r.name ?? `range-${i}`}</th><td className="mono">{typeof r.base === 'string' ? r.base : r.base ?? '—'}</td><td className="numeric">{r.size_bytes ?? '—'}</td><td>{r.target ?? '—'}</td></tr>)}
      </tbody></table></div>
      <p>Ranges are the declared request values. This view does not compute overlap, alignment, or decode validity for them.</p>
    </Section> : <Empty title="This project declares no address ranges">
      The request's <code>address_map.ranges</code> is empty. No range is invented, and no overlap analysis is possible without declared intervals.
    </Empty>}
  </div><Inspector title="Address boundary">
    <Properties rows={[[ 'Source', 'request.address_map from GET /projects/{id}/draft' ], ['Declared ranges', String(ranges.length) ], ['Overlap computation', ranges.length ? 'Not computed in this view' : 'Not possible' ], ['Decode / permission', absent ], ['Local fixture regions', 'Unchanged; see the local draft elsewhere' ]]} />
    <PageLink page="design/endpoints">Inspect endpoints</PageLink>
  </Inspector></div>;
}

export function LiveDomains({ data }: { data: LoadedProject }) {
  const physical = data.request?.physical;
  const agents = data.request?.agents ?? [];
  const declaredClocks = agents.filter(a => a.clock_domain);
  return <div className="view-layout"><div className="view-main">
    <LiveBanner data={data} />
    <Notice tone="amber"><strong>Declared parameters only.</strong> No per-agent clocks, CDC, or power intent.</Notice>
    <Section title="Declared physical parameters">
      <Properties rows={[[ 'Network clock', physical?.clock_freq_mhz ? `${physical.clock_freq_mhz} MHz` : absent ], ['Data width', physical?.data_width ? `${physical.data_width} b` : absent ], ['Declared power domains', physical?.num_power_domains !== undefined ? String(physical.num_power_domains) : absent ], ['Process node', physical?.process_node_nm ? `${physical.process_node_nm} nm` : absent ], ['Achieved timing', absent ], ['Isolation / retention / sequencing', absent ]]} />
    </Section>
    <Section title="Per-agent clock assignment">
      {declaredClocks.length ? <div className="table-scroll"><table><thead><tr><th>Agent kind</th><th>Clock domain</th><th>Count</th></tr></thead><tbody>
        {declaredClocks.map((a, i) => <tr key={`${a.kind}-${i}`}><th>{a.kind}</th><td className="mono">{a.clock_domain}</td><td className="numeric">{a.count}</td></tr>)}
      </tbody></table></div> : <Empty title="No agent declares a clock domain">
        {agents.length} agent group(s) are declared with <code>clock_domain: null</code>. Domain assignment and any crossing are therefore unknown, not assumed.
      </Empty>}
    </Section>
  </div><Inspector title="Domain boundary">
    <Properties rows={[[ 'Physical parameters', 'From request.physical' ], ['Agent clock domains', declaredClocks.length ? 'Declared' : 'Not declared' ], ['CDC / reset analysis', absent ], ['Power intent artefact', absent ], ['Process-specific power or area', 'Not evaluated' ]]} />
    <PageLink page="design/placement">Inspect logical placement</PageLink>
  </Inspector></div>;
}

export function LivePlacement({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const physical = data.request?.physical;
  const withCoords = topology ? topology.routers.filter(r => (r.coordinates ?? []).length >= 2) : [];
  return <div className="view-layout"><div className="view-main">
    <LiveBanner data={data} />
    <Notice tone="amber"><strong>Logical coordinates, not a floorplan.</strong> No die, area, or constraint data.</Notice>
    {topology ? <>
      <Section title="Logical router coordinates" actions={<Badge>{withCoords.length}/{topology.routers.length} placed</Badge>}>
        {withCoords.length ? <div className={`table-scroll${cappedClass(withCoords.length)}`}><table><thead><tr><th>Router</th><th>Logical coordinates</th><th>Seat capacity</th></tr></thead><tbody>
          {withCoords.map(r => <tr key={r.router_id}><th className="mono">R{r.router_id}</th><td className="mono">[{r.coordinates.join(', ')}]</td><td className="numeric">{r.seat_capacity ?? '—'}</td></tr>)}
        </tbody></table></div> : <Empty title="This topology family supplies no coordinates">The channel graph exists, but no router coordinates were declared. A physical placement is not derived from it.</Empty>}
      </Section>
      <Section title="Absent physical data">
        <Properties rows={[[ 'Die outline / floorplan', absent ], ['Macro or endpoint placement', absent ], ['Physical constraints', absent ], ['Process node (declared)', physical?.process_node_nm ? `${physical.process_node_nm} nm` : absent ], ['Area / congestion / timing', 'Not evaluated' ]]} />
      </Section>
    </> : <TopologyMissing data={data} />}
  </div><Inspector title="Placement boundary">
    <Properties rows={[[ 'Coordinates', 'Logical topology indices' ], ['Physical placement', 'Not supplied' ], ['Anchor/hand placement', 'Not modelled' ], ['DRC / LVS', 'Not evaluated' ]]} />
    <PageLink page="design/fabric-topology">Inspect the fabric graph</PageLink>
  </Inspector></div>;
}

export function LiveSystem({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const agents = data.request?.agents ?? [];
  const workload = data.request?.workload;
  const noc = data.request?.noc_controls;
  const design = (data.detail.active_revision?.design ?? {}) as Record<string, any>;
  return <div className="view-layout"><div className="view-main">
    <LiveBanner data={data} />
    <Section title="Declared system" actions={<Badge>{topology?.family ?? 'family not declared'}</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Element</th><th>Declared value</th><th>Evidence</th></tr></thead><tbody>
        <tr><th>Fabric</th><td>{topology ? `${topology.family} · ${topology.counts?.routers ?? 0} routers · ${topology.counts?.channels ?? 0} channels` : 'No topology document'}</td><td>Revision topology</td></tr>
        {agents.map((a, i) => <tr key={`${a.kind}-${i}`}><th>{a.kind}</th><td>{a.count} × {a.data_width ?? '—'} b {a.protocol ?? ''}</td><td>Request agents</td></tr>)}
        <tr><th>Workload</th><td>{workload?.model_name ?? 'Not declared'}{workload ? ` · tp ${workload.tp ?? '—'} dp ${workload.dp ?? '—'} ep ${workload.ep ?? '—'} pp ${workload.pp ?? '—'}` : ''}</td><td>Request workload</td></tr>
        <tr><th>Collectives</th><td>{workload?.collectives?.length ? workload.collectives.map(c => `${c.kind}(${c.dimension}, ${c.payload_bytes} B)`).join(' · ') : 'None declared'}</td><td>Request workload</td></tr>
        <tr><th>Link width</th><td>{noc?.link_width ? `${noc.link_width} b` : 'Not declared'}</td><td>Request noc_controls</td></tr>
        <tr><th>Arbitration</th><td>{noc?.arbitration ?? absent}</td><td>Request noc_controls</td></tr>
        <tr><th>Derived certificate</th><td>{design.locked_derived ? `${design.locked_derived.routing ?? '—'} · VC ${design.locked_derived.vc_count ?? '—'} · ${design.locked_derived.certificate_overall ?? '—'}` : 'Not derived'}</td><td>Active revision design</td></tr>
      </tbody></table></div>
      <p>Rows report the declared request and the derived certificate only. Throughput, latency, power, and area are not evaluated on this surface.</p>
    </Section>
    {topology && <Section title="Topology summary"><div className="table-scroll"><table><thead><tr><th>Measure</th><th>Declared</th></tr></thead><tbody>
      <tr><th>Routers</th><td className="numeric">{topology.counts?.routers ?? topology.routers.length}</td></tr>
      <tr><th>Directed channels</th><td className="numeric">{topology.counts?.channels ?? topology.channels.length}</td></tr>
      <tr><th>Endpoint seats</th><td className="numeric">{topology.counts?.endpoints ?? topology.endpoints.length}</td></tr>
      <tr><th>Link widths</th><td className="numeric">{[...new Set(topology.channels.map(c => c.width_bits))].join(', ')} b</td></tr>
    </tbody></table></div></Section>}
  </div><Inspector title="System identity">
    <Properties rows={[[ 'Project', data.detail.project.name ], ['Project id', <span className="mono">{data.detail.project.project_id}</span> ], ['Active revision', data.detail.active_revision_id ?? '—' ], ['Design hash', <span className="mono">{short(data.detail.active_revision?.design_hash)}</span> ], ['Workload source', data.request?.workload?.model_name ?? 'Not declared' ]]}/>
    <PageLink page="design/endpoints">Inspect endpoints</PageLink>
    <PageLink page="design/fabric-topology">Inspect the fabric</PageLink>
  </Inspector></div>;
}

export function FixtureBanner({ projectName }: { projectName: string | null }) {
  if (!projectName) return null;
  return <Notice tone="amber"><strong>{projectName} loaded; this surface still shows the fixture.</strong></Notice>;
}

export type { Topology };
