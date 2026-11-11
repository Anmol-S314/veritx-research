import { useState } from 'react';
import type { Topology } from './gateway';
import { incidenceMatrix, type ConnectionLayer } from './connectionMatrix';

/** Symmetric router×router incidence of declared connection resources. This is
 *  not an initiator→target map: a cell says two routers share a declared
 *  channel or shared-wire tap, never that either may access the other. */
export function RouterIncidenceMatrix({ topology }: { topology: Topology }) {
  const [requested, setRequested] = useState<ConnectionLayer>('channels');
  const hasChannels = topology.channels.length > 0;
  const hasShared = (topology.shared_links ?? []).length > 0;
  if (!hasChannels && !hasShared) {
    return <p className="meta-line">This topology declares no channels and no shared wires, so there is no connection incidence to draw.</p>;
  }
  const layer: ConnectionLayer = requested === 'shared'
    ? (hasShared ? 'shared' : 'channels')
    : (hasChannels ? 'channels' : 'shared');
  const matrix = incidenceMatrix(topology, layer);
  if (matrix.ids.length === 0) {
    return <p className="meta-line">No routers are declared, so there is no incidence matrix.</p>;
  }
  const n = matrix.ids.length;
  const cell = Math.max(6, Math.min(16, Math.floor(560 / n)));
  const step = n <= 16 ? 1 : Math.max(2, Math.ceil(n / 12));
  const left = 36;
  const top = 44;
  const grid = n * cell;
  const width = left + grid + 10;
  const height = top + grid + 26;
  const channels = topology.channels.length;
  const shared = (topology.shared_links ?? []).length;
  return <div className="incidence-figure">
    <div className="incidence-head">
      <div className="segmented" role="group" aria-label="Connection resource layer">
        <button type="button" className={layer === 'channels' ? 'active' : ''} aria-pressed={layer === 'channels'} disabled={!hasChannels} onClick={() => setRequested('channels')}>Channels {channels}</button>
        <button type="button" className={layer === 'shared' ? 'active' : ''} aria-pressed={layer === 'shared'} disabled={!hasShared} onClick={() => setRequested('shared')}>MECS taps {shared}</button>
      </div>
      <span className="muted">{n} routers · {matrix.pairs} connected pairs · max {matrix.max}</span>
    </div>
    <div className="incidence-scroll">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: `${width}px`, maxWidth: '100%' }} role="group" aria-label={`${layer === 'channels' ? 'Directed-channel' : 'Shared-wire'} incidence matrix for ${n} routers`}>
        <title>{layer === 'channels'
          ? 'Symmetric router pair counts of declared directed channels'
          : 'Symmetric router pair counts of declared shared-wire driver-to-tap incidences'}</title>
        {matrix.ids.map((id, i) => (i % step === 0 || i === n - 1) ? <g key={`col-${id}`}>
          <text className="incidence-axis" x={left + i * cell + cell / 2} y={top - 8} textAnchor="end" transform={`rotate(-55 ${left + i * cell + cell / 2} ${top - 8})`}>R{id}</text>
        </g> : null)}
        {matrix.ids.map((id, i) => (i % step === 0 || i === n - 1) ? <text className="incidence-axis" key={`row-${id}`} x={left - 6} y={top + i * cell + cell / 2 + 3} textAnchor="end">R{id}</text> : null)}
        {matrix.ids.map((rowId, row) => matrix.ids.map((colId, col) => {
          const count = matrix.counts[row][col];
          return <rect key={`${rowId}:${colId}`} x={left + col * cell} y={top + row * cell} width={Math.max(1, cell - 1)} height={Math.max(1, cell - 1)} rx={1}
            className={`incidence-cell ${layer}${count > 0 ? ' set' : ' empty'}`}
            style={count > 0 ? { opacity: 0.18 + 0.82 * (count / matrix.max) } : undefined}>
            {count > 0 && <title>{`R${rowId} ↔ R${colId} · ${count} ${layer === 'channels' ? 'directed channel' : 'shared-wire tap'}${count === 1 ? '' : 's'}`}</title>}
          </rect>;
        }))}
        <rect className="incidence-frame" x={left} y={top} width={grid} height={grid} />
      </svg>
    </div>
    <p className="incidence-caption">{layer === 'channels'
      ? 'Cell counts declared directed channels folded into an undirected router pair.'
      : 'Cell counts declared MECS driver→tap incidences folded into a router pair; taps share one resource and are not point-to-point channels.'}</p>
  </div>;
}
