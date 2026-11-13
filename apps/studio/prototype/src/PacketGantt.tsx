import { useMemo, useState } from 'react';
import { packetGroupTotals, PHASE_LABELS, PHASE_GROUP, GROUP_LABELS, type ObservedPacketCapture, type ObservedPacketPath, type ObservedPhaseGroup } from './observedPackets';
import { sampledBudget } from './cycleBudget';
import { Badge } from './ui';

const GROUP_CLASS: Record<ObservedPhaseGroup, string> = {
  source: 'gantt-source', queue: 'gantt-queue', arbitration: 'gantt-arb',
  transmission: 'gantt-tx', drain: 'gantt-drain',
};

const ROW = 17, TOP = 28, LEFT = 152, RIGHT = 18, WIDTH = 1500, AXIS = 26;
const cycles = (value: number | null | undefined) => value === null || value === undefined ? '—' : `${value.toLocaleString()} cyc`;
const node = (value: number) => value < 0 ? '—' : `N${value}`;

/** One row per watched packet. The head flit supplies the pipeline; the row
 *  closes at the packet's tail retire so body-flit drain is visible. */
export function PacketGantt({ capture, subnet }: { capture: ObservedPacketCapture; subnet: number }) {
  const all = useMemo(() => capture.packets.filter(row => row.subnet === subnet), [capture, subnet]);
  const [hover, setHover] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [includeSource, setIncludeSource] = useState(true);
  const budget = useMemo(() => sampledBudget(all), [all]);
  const rows = useMemo(() => [...all].sort((a, b) => a.requestTime - b.requestTime || a.packet - b.packet), [all]);
  const start = rows.length ? Math.min(...rows.map(row => includeSource ? row.requestTime : (row.injectionCycle ?? row.requestTime))) : 0;
  const end = rows.length ? Math.max(...rows.map(row => row.retireCycle ?? row.requestTime)) : start + 1;
  const span = Math.max(1, end - start);
  const plot = WIDTH - LEFT - RIGHT;
  const xOf = (cycle: number) => LEFT + Math.max(0, Math.min(1, (cycle - start) / span)) * plot;
  // A click pins one row: once selected, hovering another packet previews
  // nothing and the detail panel keeps the chosen packet. Without a pinned
  // row, hover is a temporary preview over the longest row.
  const focus = rows.find(row => row.packet === (selected ?? hover)) ?? budget.longest ?? rows[0] ?? null;
  const focusTotals = focus ? packetGroupTotals(focus) : null;
  const height = TOP + rows.length * ROW + AXIS;
  const tickCount = 6;
  const ticks = Array.from({ length: tickCount + 1 }, (_, index) => ({
    cycle: start + (span * index) / tickCount,
    x: LEFT + (plot * index) / tickCount,
  }));

  if (!rows.length) return <p className="meta-line">No watched packet path is available on subnet {subnet}.</p>;

  const select = (path: ObservedPacketPath) => setSelected(current => current === path.packet ? null : path.packet);

  return <div className="packet-gantt" data-testid="packet-gantt">
    <div className="gantt-head">
      <div>
        <h3>Sampled packet Gantt</h3>
        <p className="meta-line">Every watched packet on subnet {subnet}; one row per packet, head flit pipeline, closed by the packet tail retire.</p>
      </div>
      <div className="gantt-head-controls">
        <div className="segmented" role="group" aria-label="Gantt span">
          <button type="button" className={includeSource ? 'active' : ''} aria-pressed={includeSource} title="Include the source request-to-injection wait in each row." onClick={() => setIncludeSource(true)}>Full path</button>
          <button type="button" className={!includeSource ? 'active' : ''} aria-pressed={!includeSource} title="Start each row at the watched flit's injection so router and link phases fill the row." onClick={() => setIncludeSource(false)}>Network only</button>
        </div>
        <div className="gantt-legend" aria-label="Gantt phase groups">
          {(['source', 'queue', 'arbitration', 'transmission', 'drain'] as ObservedPhaseGroup[]).filter(group => includeSource || group !== 'source').map(group =>
            <span key={group}><i className={`gantt-key ${GROUP_CLASS[group]}`} aria-hidden="true" />{GROUP_LABELS[group]}</span>)}
        </div>
      </div>
    </div>
    <div className="gantt-summary">
      <span>Watched <strong>{budget.count}</strong></span>
      <span>Complete path <strong>{budget.completeCount}</strong></span>
      <span>Longest <strong>{cycles(budget.longest?.total)}</strong>{budget.longest ? <small> P{budget.longest.packet}</small> : null}</span>
      <span>Median <strong>{cycles(budget.median)}</strong></span>
      <span>p95 <strong>{cycles(budget.p95)}</strong></span>
      {budget.incompleteCount > 0 && <Badge tone="amber">{budget.incompleteCount} incomplete</Badge>}
    </div>
    <div className="gantt-readout" aria-live="polite">
      {focus && focusTotals ? <>
        <strong className="mono">P{focus.packet} · {node(focus.source)} → {node(focus.destination)}</strong>
        {selected === focus.packet && <Badge tone="blue">pinned</Badge>}
        <span>{cycles(focus.total)} · {focus.hops} hops · {focus.flits} flits</span>
        {(['source', 'queue', 'arbitration', 'transmission', 'drain'] as ObservedPhaseGroup[]).filter(group => includeSource || group !== 'source').map(group =>
          <span key={group}><i className={`gantt-key ${GROUP_CLASS[group]}`} aria-hidden="true" />{GROUP_LABELS[group]} <strong>{cycles(focusTotals[group])}</strong></span>)}
        {selected !== null && <button type="button" className="text-button" onClick={() => setSelected(null)}>Unpin</button>}
      </> : <span>Hover or select a row to inspect its phase budget.</span>}
    </div>
    <div className="gantt-scroll">
      <svg className="gantt-svg" viewBox={`0 0 ${WIDTH} ${height}`} width={WIDTH} height={height} role="group" aria-label={`Per-packet cycle Gantt for ${rows.length} watched packets`}>
        <text x={6} y={TOP - 10} className="gantt-axis-title">packet</text>
        {ticks.map(tick => <g key={tick.x}>
          <line x1={tick.x} x2={tick.x} y1={TOP - 8} y2={height - AXIS} className="gantt-grid" />
          <text x={tick.x} y={TOP - 12} textAnchor={tick.x === ticks[0].x ? 'start' : tick.x === ticks[ticks.length - 1].x ? 'end' : 'middle'} className="gantt-tick">{Math.round(tick.cycle).toLocaleString()}</text>
        </g>)}
        <line x1={LEFT} x2={LEFT + plot} y1={TOP - 8} y2={TOP - 8} className="gantt-axis" />
        <line x1={LEFT} x2={LEFT + plot} y1={height - AXIS} y2={height - AXIS} className="gantt-axis" />
        {rows.map((path, index) => {
          const y = TOP + index * ROW;
          const active = path.packet === (selected ?? hover);
          return <g key={path.packet} role="button" tabIndex={0} aria-pressed={selected === path.packet}
            aria-label={`Packet ${path.packet}, ${node(path.source)} to ${node(path.destination)}, ${cycles(path.total)}`}
            className={`gantt-row${active ? ' active' : ''}`}
            onMouseEnter={() => setHover(path.packet)} onMouseLeave={() => setHover(null)}
            onClick={() => select(path)}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(path); } }}>
            <rect x={0} y={y} width={WIDTH} height={ROW} className="gantt-row-bg" aria-hidden="true" />
            <text x={6} y={y + 11} className="gantt-label">P{path.packet}</text>
            <text x={LEFT - 8} y={y + 11} textAnchor="end" className="gantt-route">{node(path.source)} → {node(path.destination)}</text>
            {path.phases.filter(phase => includeSource || phase.kind !== 'source').map((phase, phaseIndex) => {
              const left = xOf(phase.start), right = xOf(phase.end);
              const group = PHASE_GROUP[phase.kind];
              return <rect key={phaseIndex} x={left} y={y + 3} width={Math.max(1, right - left)} height={ROW - 7} rx={1.5}
                className={`gantt-seg ${GROUP_CLASS[group]}`} aria-hidden="true">
                <title>{`P${path.packet} · ${PHASE_LABELS[phase.kind]}${phase.router !== undefined ? ` · R${phase.router}` : ''}${phase.port !== undefined && phase.port >= 0 ? ` p${phase.port}` : ''}: ${phase.start.toLocaleString()}–${phase.end.toLocaleString()} (${(phase.end - phase.start).toLocaleString()} cyc)`}</title>
              </rect>;
            })}
            {path.retireCycle !== null && <line x1={xOf(path.retireCycle)} x2={xOf(path.retireCycle)} y1={y + 2} y2={y + ROW - 2} className={`gantt-retire${path.complete ? '' : ' incomplete'}`} aria-hidden="true" />}
            <rect x={0} y={y} width={WIDTH} height={ROW} className="gantt-row-hit" aria-hidden="true" />
          </g>;
        })}
      </svg>
    </div>
    <figcaption className="meta-line">Rows cover the watched stride sample only; scroll the panel for all {rows.length}. Colour is the phase group; the thin tick is the packet retire. Network only starts each row at injection and omits the request-to-injection source wait. Click a row or any phase segment to pin it, then inspect the pinned packet below; hover shows the exact router, port and cycle range.</figcaption>
    {focus && <div className="gantt-detail">
      <div className="gantt-detail-head"><h3 className="mono">P{focus.packet}</h3><Badge tone={focus.complete ? 'green' : 'amber'}>{focus.complete ? 'complete path' : 'incomplete path'}</Badge></div>
      <div className="table-scroll capped"><table aria-label={`Packet ${focus.packet} phase detail`}>
        <thead><tr><th>Phase</th><th>Router</th><th>Start</th><th>End</th><th>Cycles</th></tr></thead>
        <tbody>
          {focus.phases.map((phase, index) => <tr key={index}>
            <td>{PHASE_LABELS[phase.kind]}</td>
            <td className="mono">{phase.router === undefined ? '—' : `R${phase.router}${phase.port !== undefined && phase.port >= 0 ? `:${phase.port}` : ''}`}</td>
            <td className="numeric">{phase.start.toLocaleString()}</td>
            <td className="numeric">{phase.end.toLocaleString()}</td>
            <td className="numeric">{Math.max(0, phase.end - phase.start).toLocaleString()}</td>
          </tr>)}
        </tbody>
      </table></div>
    </div>}
  </div>;
}
