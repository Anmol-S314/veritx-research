import { useEffect, useMemo, useState } from 'react';
import type { Topology } from './gateway';
import { topologyLayout } from './TopologyGraph';
import { decodeFlitFates, decodeObservedHops, observedPositions, observedWireFlights } from './observedHops';
import { decodeObservedPackets } from './observedPackets';
import { PacketGantt } from './PacketGantt';
import { verifyObserved } from './observedVerify';
import type { SharedRouteTable } from './sharedRoutes';
import { Badge, Notice } from './ui';

/** Observed capture: recorded router receipt/send events, checked hop by hop
 *  against the certified route set. A flit the checks cannot place is named,
 *  never animated. */
export function ObservedPlayback({ text, topology, table, config, portWires }: {
  text: string; topology: Topology;
  table?: SharedRouteTable | null; config?: string;
  portWires?: Map<string, { wire: number; taps: number[] }>;
}) {
  const events = useMemo(() => decodeObservedHops(text, topology), [text, topology]);
  const subnets = [...new Set(events.map(event => event.subnet))].sort();
  const [subnet, setSubnet] = useState(subnets[0] ?? 0);
  const first = events[0]?.cycle ?? 0, last = events.at(-1)?.cycle ?? 0;
  const [cycle, setCycle] = useState(first), [playing, setPlaying] = useState(false), [speed, setSpeed] = useState(1);
  useEffect(() => { setCycle(first); setPlaying(false); setSubnet(events[0]?.subnet ?? 0); }, [events, first]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setCycle(value => Math.min(last, value + 1)), Math.max(20, 100 / speed));
    return () => window.clearInterval(timer);
  }, [playing, last, speed]);
  useEffect(() => { if (cycle >= last) setPlaying(false); }, [cycle, last]);
  const fates = useMemo(() => decodeFlitFates(text), [text]);
  const packets = useMemo(() => decodeObservedPackets(text, topology), [text, topology]);
  const verification = useMemo(() => table && config ? verifyObserved(events, topology, table, config, portWires ?? new Map(), fates) : null, [events, topology, table, config, portWires, fates]);
  const { points } = topologyLayout(topology);
  const positions = observedPositions(events, cycle, subnet);
  const timeline = (() => {
    const span = Math.max(1, last - first + 1), bins = 36;
    const counts = new Array<number>(bins).fill(0);
    for (const event of events) {
      if (event.subnet !== subnet) continue;
      counts[Math.min(bins - 1, Math.max(0, Math.floor((event.cycle - first) / span * bins)))] += 1;
    }
    const peak = Math.max(1, ...counts);
    return counts.map((count, index) => ({ count, cycle: Math.round(first + index / bins * span), height: Math.max(4, 100 * count / peak) }));
  })();
  const transitions = new Set<string>();
  const previous = new Map<number, number>();
  for (const event of events) {
    if (event.subnet !== subnet || event.kind !== 'receive') continue;
    const from = previous.get(event.flit);
    if (from !== undefined && from !== event.router) transitions.add(`${from}:${event.router}`);
    previous.set(event.flit, event.router);
  }
  // An observed send whose wire binding is verified lets the in-flight hop be
  // drawn on the real wire instead of an anonymous dashed pair.
  const inFlight = useMemo(() => observedWireFlights(events, cycle, subnet, portWires), [events, cycle, subnet, portWires]);
  const wires = topology.shared_links ?? [];
  if (!events.length) return <p>No supported router receipt/send events were captured. The raw watch log remains available in artifacts.</p>;
  const sampled = verification?.flits.length ?? 0;
  return <figure className="trace-figure playback">
    <div className="playback-controls observed-controls">
      <div className="actions">
        <button className="button primary" aria-label={playing ? 'Pause observed capture' : 'Play observed capture'} onClick={() => { if (cycle >= last) setCycle(first); setPlaying(value => !value); }}>{playing ? 'Pause' : 'Play'}</button>
        <button className="button" aria-label="Reset observed capture" onClick={() => { setCycle(first); setPlaying(false); }}>Reset</button>
      </div>
      <div className="observed-scrubber">
        <div className="observed-timeline-label"><span>Event density</span></div>
        <div className="observed-timeline" aria-label="Observed event density">
          {timeline.map((bin, index) => <button type="button" key={index} className={bin.cycle <= cycle && (timeline[index + 1]?.cycle ?? last + 1) > cycle ? 'active' : ''} aria-label={`Jump to cycle ${bin.cycle}: ${bin.count} events`} title={`cycle ${bin.cycle}: ${bin.count} events`} onClick={() => { setPlaying(false); setCycle(bin.cycle); }}><i style={{ height: `${bin.height}%` }} /></button>)}
        </div>
        <input type="range" aria-label="Observed playback cycle" min={first} max={last} value={cycle} onChange={event => { setPlaying(false); setCycle(Number(event.target.value)); }} />
        <div className="observed-cycle">
          <span className="mono">Cycle {cycle} / {last}</span>
          <label>Speed <select aria-label="Observed playback speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option></select></label>
          <label>Subnet <select aria-label="Observed subnet" value={subnet} onChange={event => setSubnet(Number(event.target.value))}>{subnets.map(value => <option key={value} value={value}>{value}{topology.family === 'srota' ? value === 0 ? ' · Plane D' : value === 1 ? ' · Plane C' : '' : ''}</option>)}</select></label>
        </div>
      </div>
    </div>
    {verification && (() => {
      const accounted = verification.verified + verification.local + verification.mismatched + verification.unverified;
      const missing = Math.max(0, sampled - accounted);
      const warn = !verification.mismatched && (verification.unverified > 0 || missing > 0);
      const verdict = verification.mismatched ? 'Mismatch found'
        : missing > 0 ? 'Capture incomplete'
          : verification.unverified > 0 ? 'Unverifiable flits'
            : 'All watched flits accounted for';
      return <>
        <div className={`observed-verdict ${verification.mismatched ? 'bad' : warn ? 'warn' : 'good'}`}>
          <Badge tone={verification.mismatched ? 'red' : warn ? 'amber' : 'green'}>{verdict}</Badge>
          {verification.wireVerified === 0 && <span>Route evidence only; no wire binding was verified.</span>}
        </div>
        <div className="observed-breakdown" role="img" aria-label={`${verification.verified} full route, ${verification.local} local, ${verification.mismatched} mismatched, ${verification.unverified} unverifiable`}>
          {verification.verified > 0 && <i className="full" style={{ flexGrow: verification.verified }} title={`${verification.verified} full route`} />}
          {verification.local > 0 && <i className="local" style={{ flexGrow: verification.local }} title={`${verification.local} local`} />}
          {verification.mismatched > 0 && <i className="mismatch" style={{ flexGrow: verification.mismatched }} title={`${verification.mismatched} mismatched`} />}
          {verification.unverified > 0 && <i className="unverified" style={{ flexGrow: verification.unverified }} title={`${verification.unverified} unverifiable`} />}
        </div>
        <div className="observed-summary" data-testid="observed-verification">
          <span>Watched <strong>{sampled}</strong></span>
          <span>Full route <strong>{verification.verified}</strong></span>
          <span>Local <strong>{verification.local}</strong></span>
          {verification.wireVerified > 0 && <span>Wire-verified <strong>{verification.wireVerified}</strong></span>}
          {verification.mismatched > 0 && <span>Mismatched <strong>{verification.mismatched}</strong></span>}
          {verification.unverified > 0 && <span>Unverifiable <strong>{verification.unverified}</strong></span>}
          {verification.shapes.length > 0 && <span>Executed shape <strong>{verification.shapes.map(shape => `${shape.shape} ${shape.flits}`).join(' · ')}</strong></span>}
        </div>
      </>;
    })()}
    {verification?.firstMismatch && <Notice tone="red"><strong>Recorded path is not in the certified route set.</strong> {verification.firstMismatch}. Playback stays off the projection until this is explained.</Notice>}
    {!verification && <p className="meta-line">No certified route table in this bundle; recorded events are shown unverified.</p>}
    <div className="observed-canvas-head">
      <div className="observed-legend"><span><i className="observed-key active" />Recorded receipt</span><span><i className="observed-key dash" />Recorded transition</span><span><i className="observed-key flight" />In-flight on verified wire</span></div>
    </div>
    <svg className="playback-canvas observed-canvas" viewBox="0 0 800 620" role="img" aria-label={`Observed router events at cycle ${cycle}, subnet ${subnet}`}>
      <defs><marker id="observed-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 z" fill="#187b80" /></marker></defs>
      <g className="observed-wires">{wires.map(wire => { const a = points.get(wire.src_router), b = points.get(wire.taps[wire.taps.length - 1]); return a && b ? <line key={wire.shared_link_id} className="observed-wire" x1={a.x} y1={a.y - 7} x2={b.x} y2={b.y - 7} /> : null; })}</g>
      <g className="observed-transitions">{[...transitions].map(key => { const [from, to] = key.split(':').map(Number), a = points.get(from), b = points.get(to); return a && b ? <line key={key} className="observed-transition" markerEnd="url(#observed-arrow)" x1={a.x} y1={a.y} x2={b.x} y2={b.y}><title>Successive recorded router receipts: R{from} → R{to}; not a complete wiring diagram</title></line> : null; })}</g>
      <g className="observed-flights">{wires.filter(wire => inFlight.has(wire.shared_link_id)).map(wire => { const a = points.get(wire.src_router), b = points.get(wire.taps[wire.taps.length - 1]); const count = inFlight.get(wire.shared_link_id)!; return a && b ? <line key={`live-${wire.shared_link_id}`} className="observed-flight" x1={a.x} y1={a.y - 7} x2={b.x} y2={b.y - 7} style={{ strokeWidth: 2 + Math.min(6, count) }}><title>{`Wire ${wire.shared_link_id}: ${count} recorded send(s) in flight at cycle ${cycle}`}</title></line> : null; })}</g>
      {[...points].map(([id, point]) => { const present = positions.filter(event => event.router === id); return <g key={id} className={`observed-node-group${present.length ? ' active' : ''}`}><circle className="observed-node" cx={point.x} cy={point.y} r={present.length ? 16 : 7}><title>{`Router ${id}: ${present.length} captured flits observed resident`}</title></circle><text className="observed-label" x={point.x} y={point.y + 30} textAnchor="middle">R{id}</text>{present.length > 0 && <text className="observed-count" x={point.x} y={point.y + 4} textAnchor="middle">{present.length}</text>}</g>; })}
    </svg>
    <figcaption><strong>Observed router events.</strong> {events.length} receipt/send events for {sampled || 'the sampled'} watched flit ids. Markers show a flit after a recorded receipt and before its recorded send.</figcaption>
    <PacketGantt capture={packets} subnet={subnet} />
    {verification && verification.flits.length > 0 && <details>
      <summary>Per-flit check ({verification.flits.length} watched)</summary>
      <div className="table-scroll capped"><table aria-label="Observed flit verification"><thead><tr><th>Flit</th><th>Plane</th><th>Source → destination router</th><th>Recorded hops</th><th>Wires</th><th>Executed shape</th><th>Verdict</th></tr></thead><tbody>
        {verification.flits.slice(0, 40).map(flit => <tr key={flit.flit}>
          <th className="mono">{flit.flit}{flit.packet !== undefined && <><br /><small className="muted">pkt {flit.packet}</small></>}</th>
          <td>{flit.plane === 0 ? 'D' : 'C'}</td>
          <td className="mono">{flit.sourceRouter === -1 ? '—' : `R${flit.sourceRouter} → R${flit.destinationRouter}`}</td>
          <td className="numeric">{Math.max(0, flit.receipts.length - 1)}</td>
          <td className="mono">{flit.observedWires.length ? flit.observedWires.map(wire => wire === null ? '?' : wire).join(' → ') : '—'}</td>
          <td>{flit.shape ?? '—'}</td>
          <td><Badge tone={flit.verdict === 'verified' || flit.verdict === 'local' ? 'green' : flit.verdict === 'mismatch' ? 'red' : 'amber'}>{flit.verdict}</Badge>{flit.verdict === 'verified' && !flit.wireVerified && <small className="muted"> · route only</small>}{flit.reason && <><br /><small className="muted">{flit.reason}</small></>}</td>
        </tr>)}
      </tbody></table></div>
    </details>}
  </figure>;
}
