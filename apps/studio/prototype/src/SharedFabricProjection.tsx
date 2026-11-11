import { useEffect, useMemo, useState } from 'react';
import { gateway, gatewayReason, type Topology } from './gateway';
import type { LoadedRun } from './project';
import { fetchVerifiedArtifact } from './RawArtifacts';
import { decodeInjectionTrace, type InjectionRow } from './trace';
import { topologyLayout } from './TopologyGraph';
import { Button, Notice } from './ui';
import { projectSharedTrace, sharedResourceLoads, type SharedRouteTable, type FabricHop, type FabricPacket } from './sharedRoutes';

export function SharedFabricProjection({ run, topology, decoded, mode }: { run: LoadedRun; topology: Topology; decoded?: { rows: InjectionRow[]; total: number }; mode: 'playback' | 'sweep' }) {
  const [input, setInput] = useState<{ table: SharedRouteTable; config: string; trace: { rows: InjectionRow[]; total: number } } | null>(null);
  const [error, setError] = useState('');
  const [plane, setPlane] = useState('all');
  const [shape, setShape] = useState('ROW_FIRST');
  const [cycle, setCycle] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [swept, setSwept] = useState(false);
  const [selected, setSelected] = useState('');
  useEffect(() => {
    let live = true;
    setInput(null); setError(''); setSwept(false); setPlaying(false); setSelected('');
    const load = async () => {
      const files = run.artifacts?.bundle?.files ?? {};
      const tracePath = Object.keys(files).find(path => path.endsWith('/network_completion/run/workload.trace')) ?? Object.keys(files).find(path => path.endsWith('/workload.trace'));
      if (!tracePath) throw new Error('No sealed injection trace in this run.');
      const configPath = tracePath.replace(/workload\.trace$/, 'config.cfg');
      if (!files[configPath]) throw new Error('No sealed executed config beside the injection trace.');
      const [compiled, configBytes, traceBytes] = await Promise.all([gateway.compileResult(run.detail.revision_id), fetchVerifiedArtifact(run.detail.run_id, configPath, files[configPath]), decoded ? Promise.resolve(null) : fetchVerifiedArtifact(run.detail.run_id, tracePath, files[tracePath])]);
      const table = (compiled.groups?.routing as { shared_route?: SharedRouteTable } | undefined)?.shared_route;
      if (!table?.artifact_id) {
        const family = (compiled.groups?.fabric as { topology?: { family?: string } } | undefined)?.topology?.family;
        throw new Error(family === 'gec_hybrid'
          ? 'This GEC-hybrid fabric routes as a ranked candidate union per source and destination, not as one deterministic shared-resource path, so a flit cannot be placed on a single wire. The declared channels and shared wires remain listed below.'
          : 'This revision exposes no deterministic shared-resource route table, so a flit cannot be placed on a single wire. The declared channels and shared wires remain listed below.');
      }
      const decoder = new TextDecoder('utf-8', { fatal: true });
      const trace = decoded ?? decodeInjectionTrace(decoder.decode(traceBytes!), 20000);
      if (live) { setInput({ table, config: decoder.decode(configBytes), trace }); setShape(Object.values(table.shape_of_partition ?? {})[0] ?? 'DETERMINISTIC'); setCycle(trace.rows[0]?.cycle ?? 0); }
    };
    void load().catch(error => { if (live) setError(gatewayReason(error)); });
    return () => { live = false; };
  }, [run.detail.run_id, run.detail.revision_id, run.artifacts, decoded]);
  const projection = useMemo(() => {
    if (!input) return null;
    try { return { ...projectSharedTrace(topology, input.table, input.config, input.trace.rows, shape), error: '' }; }
    catch (error) { return { packets: [] as FabricPacket[], rejected: [], error: String(error) }; }
  }, [input, topology, shape]);
  const packets = useMemo(() => (projection?.packets ?? []).filter(packet => plane === 'all' || packet.plane === Number(plane)), [projection, plane]);
  const loads = useMemo(() => sharedResourceLoads(packets), [packets]);
  const end = packets.reduce((max, packet) => Math.max(max, packet.row.cycle + packet.duration + 12), 1);
  const start = packets.reduce((min, packet) => Math.min(min, packet.row.cycle), end);
  useEffect(() => { setPlaying(false); setCycle(start); }, [plane, shape, start]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setCycle(value => Math.min(end, value + speed)), 50);
    return () => window.clearInterval(timer);
  }, [playing, end, speed]);
  useEffect(() => { if (cycle >= end) setPlaying(false); }, [cycle, end]);
  if (error || projection?.error) return <Notice tone="red">{error || projection?.error}</Notice>;
  if (!input || !projection) return <p className="loading-line">Reading sealed class/subnet assignments and certified shared-resource decisions…</p>;
  const { points } = topologyLayout(topology);
  const shapes = [...new Set(Object.values(input.table.shape_of_partition ?? {}))];
  const livePackets = packets.filter(packet => cycle >= packet.row.cycle && cycle < packet.row.cycle + packet.duration + 12);
  const currentHop = (packet: FabricPacket) => {
    let remaining = cycle - packet.row.cycle;
    for (const hop of packet.hops) { if (remaining < hop.latency) return { hop, fraction: remaining / hop.latency }; remaining -= hop.latency; }
    return null;
  };
  const stress = new Map<string, number>();
  if (mode === 'sweep') { if (swept) for (const load of loads) stress.set(load.hop.key, load.flits); }
  else for (const packet of livePackets) { const at = currentHop(packet); if (at) stress.set(at.hop.key, (stress.get(at.hop.key) ?? 0) + packet.row.flits); }
  const peak = Math.max(1, ...stress.values());
  const wires = topology.shared_links ?? [];
  const segments: FabricHop[] = [];
  if (plane !== '1') for (const wire of wires) segments.push({ key: `D:${wire.shared_link_id}`, plane: 0, wire: wire.shared_link_id, from: wire.src_router, to: wire.taps[wire.taps.length - 1], tap: null, latency: wire.latency_cycles });
  if (plane !== '0') {
    const coordinates = new Map(topology.routers.map(router => [router.coordinates.join(','), router.router_id]));
    for (const router of topology.routers) {
      const [x, y] = router.coordinates;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const to = coordinates.get(`${x + dx},${y + dy}`);
        if (to !== undefined) segments.push({ key: `C:${router.router_id}:${to}`, plane: 1, from: router.router_id, to, latency: 1, tap: null });
      }
    }
  }
  // Plane D buses sit above/left of the router row; Plane C sits below/right, so a
  // driver and its taps are never confused with a point-to-point mesh link.
  const offsetPoint = (hop: FabricHop, id: number) => {
    const p = points.get(id)!, a = points.get(hop.from)!, b = points.get(hop.to)!;
    const shift = hop.plane === 0 ? -7 : 7;
    return { x: p.x + (a.x === b.x ? shift : 0), y: p.y + (a.y === b.y ? shift : 0) };
  };
  const chooseResource = (key: string) => {
    setSelected(key); setPlaying(false);
    for (const packet of packets) {
      let elapsed = 0;
      for (const hop of packet.hops) { if (hop.key === key) { setCycle(packet.row.cycle + elapsed); return; } elapsed += hop.latency; }
    }
  };
  const requestedFlits = packets.reduce((sum, packet) => sum + packet.row.flits, 0);
  return <div className="shared-projection" data-testid={`shared-${mode}`}>
    <div className="toolbar toolbar-start">
      <label className="field">Native plane<select aria-label={`${mode} native plane`} value={plane} onChange={event => { setPlane(event.target.value); setSelected(''); }}><option value="all">Both planes</option><option value="0">Plane D · shared wires</option><option value="1">Plane C · private XY</option></select></label>
      {shapes.length > 1 && <label className="field">Projected Plane D shape<select aria-label={`${mode} projected shape`} value={shape} onChange={event => setShape(event.target.value)}>{shapes.map(value => <option key={value} value={value}>{value}</option>)}</select></label>}
      {mode === 'sweep' && <Button primary onClick={() => setSwept(true)}>Sweep shared resources</Button>}
    </div>
    {mode === 'playback' && <div className="playback-controls">
      <Button primary onClick={() => { if (cycle >= end) setCycle(start); setPlaying(value => !value); }}>{playing ? 'Pause' : 'Play'}</Button>
      <Button onClick={() => { setPlaying(false); setCycle(start); }}>Reset</Button>
      <Button disabled={!packets.some(packet => packet.hops.length && packet.row.cycle > cycle)} onClick={() => { setPlaying(false); setCycle(packets.reduce((next, packet) => packet.hops.length && packet.row.cycle > cycle ? Math.min(next, packet.row.cycle) : next, end)); }}>Next transfer</Button>
      <input aria-label="Shared playback cycle" type="range" min={start} max={end} value={cycle} onChange={event => { setPlaying(false); setCycle(Number(event.target.value)); }} />
      <span className="mono">cycle {cycle} / {end}</span>
      <label className="field field-inline"><span>Cycles / tick</span><select aria-label="Shared playback speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}>{[1, 4, 16, 64].map(value => <option key={value}>{value}</option>)}</select></label>
    </div>}
    <div className="report-strip"><span>Projected packets <strong>{packets.length.toLocaleString()}</strong></span><span>Requested flits <strong>{requestedFlits.toLocaleString()}</strong></span><span>Local packets <strong>{packets.filter(packet => !packet.hops.length).length.toLocaleString()}</strong></span><span>{mode === 'playback' ? 'Visible packets' : 'Resources touched'} <strong>{mode === 'playback' ? livePackets.length : swept ? loads.length : '—'}</strong></span><span>Rejected rows <strong>{projection.rejected.length}</strong></span></div>
    {projection.rejected.length > 0 && <details><summary>Unprojected rows ({projection.rejected.length})</summary><p>{projection.rejected.slice(0, 10).map(row => `Line ${row.row}: ${row.reason}`).join('; ')}</p></details>}
    <svg className="playback-canvas" viewBox="0 0 800 620" role="img" aria-label={`Shared fabric ${mode} · ${plane === 'all' ? 'both planes' : plane === '0' ? 'Plane D' : 'Plane C'}`}>
      {segments.map(hop => {
        const a = offsetPoint(hop, hop.from), b = offsetPoint(hop, hop.to), value = stress.get(hop.key) ?? 0;
        const wire = hop.wire === undefined ? undefined : wires.find(entry => entry.shared_link_id === hop.wire);
        const width = selected === hop.key ? 8 : value ? 2.5 + 5 * value / peak : 1.5;
        return <g key={hop.key} data-resource={hop.key} data-load={value}>
          <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={hop.plane === 0 ? '#138a86' : '#c77b23'} strokeWidth={width} strokeDasharray={hop.plane === 0 ? undefined : '5 4'} opacity={value ? 0.9 : 0.28}>
            <title>{hop.plane === 0 ? `Wire ${hop.key.slice(2)}: driver R${hop.from}, ${wire?.taps.length ?? 0} tap(s)` : `Private Plane C channel R${hop.from} → R${hop.to}`} · {value} {mode === 'sweep' ? 'attributed' : 'concurrent projected'} flits</title>
          </line>
          {wire?.taps.map((tap, index) => {
            const guide = points.get(wire.src_router)!, target = points.get(tap)!;
            const stub = { x: target.x + (guide.x === target.x ? -7 : 0), y: target.y + (guide.y === target.y ? -7 : 0) };
            return <g key={tap}><line x1={stub.x} y1={stub.y} x2={target.x} y2={target.y} stroke="#138a86" strokeWidth={2} opacity={value ? 0.85 : 0.4} /><rect x={stub.x - 2.5} y={stub.y - 2.5} width={5} height={5} fill="#138a86" opacity={value ? 0.95 : 0.5}><title>{`Tap ${index} on wire ${hop.key.slice(2)} lands at R${tap}; tap index is native drop order`}</title></rect></g>;
          })}
        </g>;
      })}
      {[...points].map(([router, point]) => <g key={router}><circle cx={point.x} cy={point.y} r={6} fill="#526779" stroke="white" strokeWidth={1.5} /><text x={point.x} y={point.y - 12} textAnchor="middle">R{router}</text></g>)}
      {mode === 'playback' && livePackets.map(packet => {
        const at = currentHop(packet);
        let p = points.get(packet.destinationRouter)!;
        if (at) { const a = offsetPoint(at.hop, at.hop.from), b = offsetPoint(at.hop, at.hop.to); p = { x: a.x + (b.x - a.x) * at.fraction, y: a.y + (b.y - a.y) * at.fraction }; }
        return <circle key={packet.row.line} data-packet={packet.row.line} cx={p.x} cy={p.y} r={3 + Math.min(3, packet.row.flits / 4)} fill={packet.plane === 0 ? '#138a86' : '#c77b23'} stroke="white"><title>Line {packet.row.line} · class {packet.row.trafficClass} · Plane {packet.plane === 0 ? 'D' : 'C'} · {packet.row.flits} flits{at ? ` · ${at.hop.key}${at.hop.tap === null ? '' : ` tap ${at.hop.tap}`}` : ' · destination hold'}</title></circle>;
      })}
    </svg>
    {mode === 'sweep' && swept && <div className="table-scroll capped"><table aria-label="Shared resource attribution"><thead><tr><th>Resource</th><th>Driver / destination</th><th>Tap breakdown (flits)</th><th>Packets</th><th>Attributed flits</th></tr></thead><tbody>{loads.map(load => <tr key={load.hop.key}><th><button className="text-button" aria-pressed={selected === load.hop.key} onClick={() => chooseResource(load.hop.key)}>{load.hop.key}</button></th><td>{load.hop.plane === 0 ? `R${load.hop.from} · shared wire` : `R${load.hop.from} → R${load.hop.to}`}</td><td>{[...load.taps].map(([tap, flits]) => `tap ${tap}: ${flits.toLocaleString()}`).join(' · ') || 'private channel'}</td><td>{load.packets.toLocaleString()}</td><td>{load.flits.toLocaleString()}</td></tr>)}</tbody></table></div>}
  </div>;
}
