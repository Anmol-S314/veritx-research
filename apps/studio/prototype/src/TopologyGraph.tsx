import type { Topology } from './gateway';

// Draws whatever the backend declared: coordinates when the family supplies them, otherwise a
// deterministic derived layout that is labelled as such. No grid shape is assumed, so a 3x3 mesh,
// a 64-tile GEC, and an explicit graph all render from the same channel list.
type Point = { x: number; y: number };

function layout(topology: Topology): { points: Map<number, Point>; derived: boolean } {
  const points = new Map<number, Point>();
  const placed = topology.routers.filter(r => Array.isArray(r.coordinates) && r.coordinates.length >= 2);
  if (placed.length === topology.routers.length && topology.routers.length > 0) {
    const cols = Math.max(...placed.map(r => r.coordinates[0])) + 1;
    const rows = Math.max(...placed.map(r => r.coordinates[1])) + 1;
    const size = Math.min(760 / Math.max(cols, 1), 520 / Math.max(rows, 1), 92);
    for (const r of placed) points.set(r.router_id, { x: 40 + r.coordinates[0] * size, y: 36 + r.coordinates[1] * size });
    return { points, derived: false };
  }
  // Neighbour-first ordering around a circle keeps connected routers adjacent without inventing coordinates.
  const adjacency = new Map<number, number[]>();
  for (const c of topology.channels) {
    adjacency.set(c.src_router, [...(adjacency.get(c.src_router) ?? []), c.dst_router]);
    adjacency.set(c.dst_router, [...(adjacency.get(c.dst_router) ?? []), c.src_router]);
  }
  const order: number[] = [];
  const seen = new Set<number>();
  for (const seed of topology.routers.map(r => r.router_id)) {
    if (seen.has(seed)) continue;
    const queue = [seed];
    while (queue.length) {
      const id = queue.shift()!;
      if (seen.has(id)) continue;
      seen.add(id); order.push(id);
      queue.push(...(adjacency.get(id) ?? []).filter(n => !seen.has(n)));
    }
  }
  // Deterministic concentric rings: readable for 9 through 64+ routers without inventing coordinates.
  const perRing = 32;
  const rings = Math.max(1, Math.ceil(order.length / perRing));
  order.forEach((id, i) => {
    const ring = Math.floor(i / perRing);
    const indexInRing = i % perRing;
    const countInRing = Math.min(perRing, order.length - ring * perRing);
    const radius = rings === 1 ? Math.min(250, 60 + countInRing * 3.6) : 150 + ring * 100;
    const angle = (2 * Math.PI * indexInRing) / Math.max(countInRing, 1) - Math.PI / 2;
    points.set(id, { x: 400 + Math.cos(angle) * radius, y: 310 + Math.sin(angle) * radius });
  });
  return { points, derived: true };
}

export function TopologyGraph({ topology, selected, onSelect, highlight }: { topology: Topology; selected?: number | null; onSelect?: (routerId: number) => void; highlight?: Topology['channels'][number] | null }) {
  const { points, derived } = layout(topology);
  const radius = topology.counts?.routers > 40 ? 7 : 11;
  const links: [number, number][] = [];
  const seen = new Set<string>();
  for (const c of topology.channels) {
    const key = c.src_router < c.dst_router ? `${c.src_router}-${c.dst_router}` : `${c.dst_router}-${c.src_router}`;
    if (seen.has(key)) continue;
    seen.add(key);
    links.push([c.src_router, c.dst_router]);
  }
  const endpoints = new Map<number, number>();
  for (const e of topology.endpoints) endpoints.set(e.router_id, (endpoints.get(e.router_id) ?? 0) + 1);
  return <figure className="topology-figure">
    <svg className="gateway-topology" viewBox="0 0 800 620" role="img" aria-label={`${topology.family} topology from the repository gateway, ${topology.counts?.routers ?? 0} routers and ${topology.counts?.channels ?? topology.channels.length} directed channels`}>
      <defs><marker id="gateway-tip" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 z" fill="#0f6c9e" /></marker></defs>
      <g className="gateway-links" data-dim={highlight ? 'true' : undefined}>
        {links.map(([a, b]) => {
          const p = points.get(a), q = points.get(b);
          if (!p || !q) return null;
          return <line key={`${a}-${b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} />;
        })}
      </g>
      {highlight && (() => {
        const p = points.get(highlight.src_router), q = points.get(highlight.dst_router);
        if (!p || !q) return null;
        const dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy) || 1, ux = dx / len, uy = dy / len;
        const gap = radius + 3;
        return <g className="gateway-highlight" aria-hidden="true">
          <line x1={p.x + ux * gap} y1={p.y + uy * gap} x2={q.x - ux * gap} y2={q.y - uy * gap} markerEnd="url(#gateway-tip)" />
        </g>;
      })()}
      <g className="gateway-nodes">
        {[...points.entries()].map(([id, p]) => <g key={id} className={`gateway-node${selected === id ? ' gateway-node-selected' : ''}${highlight && (highlight.src_router === id || highlight.dst_router === id) ? ' gateway-node-touched' : ''}`} role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined} aria-label={onSelect ? `Select router ${id}` : undefined} onClick={() => onSelect?.(id)} onKeyDown={e => { if (onSelect && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSelect(id); } }}>
          <circle cx={p.x} cy={p.y} r={selected === id ? radius + 3 : radius} />
          {topology.counts?.routers <= 25 && <text x={p.x} y={p.y + radius + 12} textAnchor="middle">{id}</text>}
          {endpoints.get(id) && topology.counts?.routers <= 40 ? <text className="endpoint-count" x={p.x + radius + 4} y={p.y - radius} >{endpoints.get(id)}</text> : null}
        </g>)}
      </g>
    </svg>
    <figcaption>
      <span className="mono">{topology.family}</span> · {topology.counts?.routers ?? 0} routers · {topology.counts?.channels ?? topology.channels.length} directed channels · {topology.counts?.endpoints ?? 0} endpoints
      {derived && <> · <strong>layout derived from the channel graph; the backend supplied no router coordinates</strong></>}
    </figcaption>
  </figure>;
}
