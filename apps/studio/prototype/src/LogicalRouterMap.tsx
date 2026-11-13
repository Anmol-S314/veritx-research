import type { Topology } from './gateway';

const CELL = 60;
const NODE_W = 44;
const NODE_H = 30;
const PAD = 36;

/** Logical router coordinates from the revision topology. This is not a die
 *  floorplan: no physical distance, area, congestion or placement is implied. */
export function LogicalRouterMap({ topology }: { topology: Topology }) {
  const placed = topology.routers.filter(router => Array.isArray(router.coordinates) && router.coordinates.length >= 2);
  if (placed.length !== topology.routers.length || placed.length === 0) {
    return <p className="meta-line">The revision does not declare a complete coordinate pair for every router, so no logical map is drawn.</p>;
  }
  const cols = Math.max(...placed.map(router => router.coordinates[0])) + 1;
  const rows = Math.max(...placed.map(router => router.coordinates[1])) + 1;
  const width = cols * CELL + PAD * 2;
  const height = rows * CELL + PAD * 2;
  const point = (routerId: number) => {
    const router = placed.find(candidate => candidate.router_id === routerId);
    return router ? { x: PAD + CELL / 2 + router.coordinates[0] * CELL, y: PAD + CELL / 2 + router.coordinates[1] * CELL } : null;
  };
  const label = placed.length <= 64;
  const shared = topology.shared_links ?? [];
  const pairs = new Map<string, [number, number]>();
  for (const channel of topology.channels) {
    const key = channel.src_router < channel.dst_router ? `${channel.src_router}-${channel.dst_router}` : `${channel.dst_router}-${channel.src_router}`;
    if (!pairs.has(key)) pairs.set(key, [channel.src_router, channel.dst_router]);
  }
  return <figure className="topology-figure logical-placement-figure">
    <div className="logical-placement-scroll">
      <svg className="logical-placement-canvas" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Declared logical router coordinates, ${cols} by ${rows} grid, ${placed.length} routers. Not a floorplan.`}>
        <g className="logical-placement-grid">
          {Array.from({ length: cols + 1 }, (_, index) => <line key={`v-${index}`} x1={PAD + index * CELL} y1={PAD} x2={PAD + index * CELL} y2={PAD + rows * CELL} />)}
          {Array.from({ length: rows + 1 }, (_, index) => <line key={`h-${index}`} x1={PAD} y1={PAD + index * CELL} x2={PAD + cols * CELL} y2={PAD + index * CELL} />)}
        </g>
        <g className="logical-placement-links">
          {[...pairs.values()].map(([src, dst]) => {
            const from = point(src), to = point(dst);
            return from && to ? <line key={`${src}-${dst}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} /> : null;
          })}
        </g>
        {shared.length > 0 && <g className="logical-placement-shared">
          {shared.map(link => {
            const from = point(link.src_router);
            if (!from) return null;
            return link.taps.map(tap => {
              const to = point(tap);
              return to ? <line key={`wire-${link.shared_link_id}-${tap}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} /> : null;
            });
          })}
        </g>}
        <g className="logical-placement-nodes">
          {placed.map(router => {
            const p = point(router.router_id);
            if (!p) return null;
            const seats = topology.endpoints.filter(endpoint => endpoint.router_id === router.router_id).length;
            return <g key={router.router_id} className="logical-placement-node">
              <rect x={p.x - NODE_W / 2} y={p.y - NODE_H / 2} width={NODE_W} height={NODE_H} rx={3} />
              {label && <text x={p.x} y={p.y + 4} textAnchor="middle">{router.router_id}</text>}
              {seats > 0 && <circle className="logical-placement-seat" cx={p.x + NODE_W / 2 - 2} cy={p.y - NODE_H / 2 + 2} r={2.6} />}
              <title>{`Router R${router.router_id} · logical coordinates [${router.coordinates.join(', ')}]${seats ? ` · ${seats} endpoint seat${seats === 1 ? '' : 's'}` : ''}`}</title>
            </g>;
          })}
        </g>
      </svg>
    </div>
    <div className="legend">
      <span><i className="legend-dot" />Declared router coordinate</span>
      <span><i className="legend-dot blue" />Router with endpoint seats</span>
      {shared.length > 0 && <span><i className="legend-dot amber" />Declared shared wire</span>}
      <span>{placed.length} routers · {cols} × {rows} logical grid · no die frame or physical distance</span>
    </div>
    <figcaption>
      <span className="mono">{topology.family}</span> · logical router coordinates only. This map is not a floorplan, placement, congestion view, or signoff geometry.
    </figcaption>
  </figure>;
}
