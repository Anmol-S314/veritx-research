import type { MappingRow, Topology } from './gateway';
import { parallelColor, parallelGroups, type ParallelAxis } from './parallelism';
import { contextTarget } from './contextSelection';

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
    const size = Math.min(760 / Math.max(cols, 1), 520 / Math.max(rows, 1), 130);
    const x0 = (800 - cols * size) / 2 + size / 2;
    const y0 = (620 - rows * size) / 2 + size / 2;
    for (const r of placed) points.set(r.router_id, { x: x0 + r.coordinates[0] * size, y: y0 + r.coordinates[1] * size });
    return { points, derived: false };
  }
  // Neighbour-first ordering around a circle keeps connected routers adjacent without inventing coordinates.
  const adjacency = new Map<number, number[]>();
  for (const c of topology.channels) {
    adjacency.set(c.src_router, [...(adjacency.get(c.src_router) ?? []), c.dst_router]);
    adjacency.set(c.dst_router, [...(adjacency.get(c.dst_router) ?? []), c.src_router]);
  }
  for (const link of topology.shared_links ?? []) {
    for (const tap of link.taps) {
      adjacency.set(link.src_router, [...(adjacency.get(link.src_router) ?? []), tap]);
      adjacency.set(tap, [...(adjacency.get(tap) ?? []), link.src_router]);
    }
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

export function topologyLayout(topology: Topology) { return layout(topology); }

/** Fit the drawing to the routers actually present. The old fixed 800×620
 *  frame left a 3×3 fabric tiny in the middle of a large panel; a 9×9 fabric
 *  occupied the same area because spacing was already capped. The frame now
 *  keeps a constant margin around the real graph, so small and large fabrics
 *  both use the canvas. */
function graphViewBox(points: Iterable<Point>, padding = 46): string {
  const list = [...points];
  if (!list.length) return '0 0 800 620';
  const xs = list.map(point => point.x), ys = list.map(point => point.y);
  const minX = Math.min(...xs) - padding, maxX = Math.max(...xs) + padding;
  const minY = Math.min(...ys) - padding, maxY = Math.max(...ys) + padding;
  const width = Math.max(240, maxX - minX), height = Math.max(240, maxY - minY);
  const centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2;
  return `${centerX - width / 2} ${centerY - height / 2} ${width} ${height}`;
}

// Bend a link only when its straight segment would pass through another router.
// Flatfly cliques and torus wraparounds otherwise collapse visually into a mesh.
export function topologyLinkPath(p: Point, q: Point, points: Iterable<Point>): string {
  const dx = q.x - p.x, dy = q.y - p.y;
  const length = Math.hypot(dx, dy);
  if (!length) return `M ${p.x} ${p.y} L ${q.x} ${q.y}`;
  const crossings = [...points].filter(r => {
    const t = ((r.x - p.x) * dx + (r.y - p.y) * dy) / (length * length);
    return t > 0.001 && t < 0.999 && Math.abs((r.x - p.x) * dy - (r.y - p.y) * dx) / length < 1;
  }).length;
  if (!crossings) return `M ${p.x} ${p.y} L ${q.x} ${q.y}`;
  const bend = 32 + crossings * 28;
  return `M ${p.x} ${p.y} Q ${(p.x + q.x) / 2 - dy / length * bend} ${(p.y + q.y) / 2 + dx / length * bend} ${q.x} ${q.y}`;
}

// One undirected edge per router pair; both directions of a declared channel collapse to one line.
export function undirectedLinks(topology: Topology): [number, number][] {
  const links: [number, number][] = [];
  const seen = new Set<string>();
  for (const c of topology.channels) {
    const key = c.src_router < c.dst_router ? `${c.src_router}-${c.dst_router}` : `${c.dst_router}-${c.src_router}`;
    if (seen.has(key)) continue;
    seen.add(key);
    links.push([c.src_router, c.dst_router]);
  }
  return links;
}

export function TopologyGraph({ topology, selected, onSelect, highlight, load, telemetry = false, mappingRows, axis = null, degreeCount, selectedWire = null, onSelectWire, labels, showSharedWires = true }: { topology: Topology; selected?: number | null; onSelect?: (routerId: number) => void; highlight?: Topology['channels'][number] | null; load?: Map<string, number>; telemetry?: boolean; mappingRows?: MappingRow[]; axis?: ParallelAxis | null; degreeCount?: number; selectedWire?: number | null; onSelectWire?: (wireId: number | null) => void; labels?: boolean; showSharedWires?: boolean }) {
  const { points, derived } = layout(topology);
  const radius = topology.counts?.routers > 40 ? 8 : 11;
  const showLabels = labels ?? (topology.counts?.routers ?? 0) <= 25;
  const links = undirectedLinks(topology);
  const endpoints = new Map<number, number>();
  const endpointsByRouter = new Map<number, Topology['endpoints']>();
  for (const e of topology.endpoints) {
    endpoints.set(e.router_id, (endpoints.get(e.router_id) ?? 0) + 1);
    endpointsByRouter.set(e.router_id, [...(endpointsByRouter.get(e.router_id) ?? []), e]);
  }
  const shared = topology.shared_links ?? [];
  const activeAxis = axis ?? null;
  const endpointRouter = new Map(topology.endpoints.map(e => [e.endpoint_id, e.router_id]));
  const mappingByEndpoint = new Map((mappingRows ?? []).map(row => [row.endpoint_id, row]));
  const axisRows = activeAxis ? (mappingRows ?? []) : [];
  const degree = activeAxis ? Math.max(1, degreeCount ?? Math.max(1, ...axisRows.map(row => row.coordinates[activeAxis!] + 1))) : 1;
  const groups = activeAxis ? parallelGroups(axisRows, endpointRouter, activeAxis) : [];
  const showGroups = !!activeAxis && groups.length > 1 && groups.length <= 8;
  const viewBox = graphViewBox(points.values());
  const placed = topology.routers.filter(router => Array.isArray(router.coordinates) && router.coordinates.length >= 2);
  const axesReady = placed.length === topology.routers.length && topology.routers.length > 0 && topology.routers.length <= 144;
  const columnAxes = new Map<number, Point>();
  const rowAxes = new Map<number, Point>();
  if (axesReady) {
    for (const router of placed) {
      const point = points.get(router.router_id);
      if (!point) continue;
      const [column, row] = router.coordinates;
      const priorColumn = columnAxes.get(column);
      if (!priorColumn || point.y < priorColumn.y) columnAxes.set(column, point);
      const priorRow = rowAxes.get(row);
      if (!priorRow || point.x < priorRow.x) rowAxes.set(row, point);
    }
  }
  return <figure className="topology-figure">
    <svg className="gateway-topology" viewBox={viewBox} role="img" aria-label={`${topology.family} topology from the repository gateway, ${topology.counts?.routers ?? 0} routers, ${topology.counts?.channels ?? topology.channels.length} directed channels and ${shared.length} shared wires`}>
      <defs><marker id="gateway-tip" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 z" fill="#0f6c9e" /></marker></defs>
      {axesReady && <g className="gateway-axes" aria-hidden="true">
        {[...columnAxes.entries()].map(([column, point]) => <text key={`col-${column}`} x={point.x} y={point.y - radius - 7} textAnchor="middle">{column}</text>)}
        {[...rowAxes.entries()].map(([row, point]) => <text key={`row-${row}`} x={point.x - radius - 7} y={point.y + 4} textAnchor="end">{row}</text>)}
      </g>}
      {telemetry && <g className="gateway-telemetry" aria-hidden="true">
        {[...points.entries()].map(([id, p]) => <circle key={`tel-${id}`} className="gateway-telemetry-ring" cx={p.x} cy={p.y} r={radius + 6} />)}
      </g>}
      {shared.length > 0 && <g className="gateway-shared-links" data-dim={selectedWire !== null} data-visible={showSharedWires || selectedWire !== null}>
        {shared.map(link => {
          const p = points.get(link.src_router);
          const taps = link.taps.map(id => points.get(id)).filter((q): q is Point => Boolean(q));
          if (!p || taps.length === 0) return null;
          const active = selectedWire === link.shared_link_id;
          const first = taps[0];
          return <g key={`shared-${link.shared_link_id}`} className={`shared-wire${active ? ' selected' : ''}`}
            {...contextTarget('wire', link.shared_link_id, `Shared wire W${link.shared_link_id}`, `driver R${link.src_router} → taps ${link.taps.map(tap => `R${tap}`).join(', ')} · ${link.width_bits} bits · ${link.latency_cycles} cycles`)}
            role={onSelectWire ? 'button' : undefined} tabIndex={onSelectWire ? 0 : undefined}
            aria-label={onSelectWire ? `Shared wire W${link.shared_link_id}, router ${link.src_router} to ${link.taps.length} taps` : undefined}
            onClick={() => onSelectWire?.(active ? null : link.shared_link_id)}
            onKeyDown={e => { if (onSelectWire && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSelectWire(active ? null : link.shared_link_id); } }}>
            <polyline points={[p, ...taps].map(q => `${q.x},${q.y}`).join(' ')} />
            {taps.map((q, i) => <circle key={i} className="shared-wire-tap" cx={q.x} cy={q.y} r={3.2} />)}
            {active && <text className="shared-wire-label" x={(p.x + first.x) / 2} y={(p.y + first.y) / 2 - 5} textAnchor="middle">W{link.shared_link_id}</text>}
          </g>;
        })}
      </g>}
      <g className="gateway-links" data-dim={highlight ? 'true' : undefined}>
        {links.map(([a, b]) => {
          const p = points.get(a), q = points.get(b);
          if (!p || !q) return null;
          return <path key={`${a}-${b}`} d={topologyLinkPath(p, q, points.values())} fill="none"><title>{`Router ${a} ↔ router ${b} · declared connectivity (directions collapsed)`}</title></path>;
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
      {load && (() => {
        const peak = Math.max(1, ...load.values());
        return <g className="gateway-load" aria-hidden="true">
          {topology.channels.map(c => {
            const value = load.get(`${c.src_router}:${c.src_port}->${c.dst_router}:${c.dst_port}`) ?? 0;
            if (!value) return null;
            const p = points.get(c.src_router), q = points.get(c.dst_router);
            if (!p || !q) return null;
            const dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy) || 1, share = value / peak;
            const ox = (-dy / len) * 1.8, oy = (dx / len) * 1.8;
            return <line key={`${c.src_router}:${c.src_port}->${c.dst_router}:${c.dst_port}`} x1={p.x + ox} y1={p.y + oy} x2={q.x + ox} y2={q.y + oy} style={{ strokeWidth: 1.5 + 4 * share, opacity: 0.3 + 0.55 * share }} />;
          })}
        </g>;
      })()}
      {showGroups && groups.map(group => {
        const members = group.routers.map(id => points.get(id)).filter((p): p is Point => Boolean(p));
        if (members.length === 0) return null;
        const minX = Math.min(...members.map(p => p.x)) - 18;
        const minY = Math.min(...members.map(p => p.y)) - 18;
        const maxX = Math.max(...members.map(p => p.x)) + 18;
        const maxY = Math.max(...members.map(p => p.y)) + 18;
        const color = parallelColor(group.coordinate, degree);
        return <rect key={`parallel-${group.coordinate}`} className="parallel-group" x={minX} y={minY} width={maxX - minX} height={maxY - minY} rx={10} style={{ stroke: color, fill: color }}>
          <title>{`${activeAxis?.toUpperCase()} ${group.coordinate} · ${group.ranks} ranks · ${group.routers.length} routers`}</title>
        </rect>;
      })}
      <g className="gateway-nodes">
        {[...points.entries()].map(([id, p]) => {
          const paintAxis = activeAxis;
          const nodeEndpoints = endpointsByRouter.get(id) ?? [];
          return <g key={id} className={`gateway-node${selected === id ? ' gateway-node-selected' : ''}${highlight && (highlight.src_router === id || highlight.dst_router === id) ? ' gateway-node-touched' : ''}`} {...contextTarget('router', id, `Router R${id}`, `${topology.family} · ${topology.channels.filter(channel => channel.src_router === id).length} outbound / ${topology.channels.filter(channel => channel.dst_router === id).length} inbound declared channels · ${nodeEndpoints.length} attached endpoint${nodeEndpoints.length === 1 ? '' : 's'}`)} role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined} aria-label={onSelect ? `Select router ${id}` : undefined} onClick={() => onSelect?.(id)} onKeyDown={e => { if (onSelect && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSelect(id); } }}>
            <title>{`Router R${id} · ${nodeEndpoints.length} attached endpoint${nodeEndpoints.length === 1 ? '' : 's'} · ${topology.channels.filter(channel => channel.src_router === id).length} out / ${topology.channels.filter(channel => channel.dst_router === id).length} in`}</title>
            <circle cx={p.x} cy={p.y} r={selected === id ? radius + 3 : radius} />
            {nodeEndpoints.length > 0 && !paintAxis && <rect className="gateway-node-seat" x={p.x - (radius > 8 ? 2.2 : 1.8)} y={p.y - (radius > 8 ? 2.2 : 1.8)} width={radius > 8 ? 4.4 : 3.6} height={radius > 8 ? 4.4 : 3.6} rx={1} />}
            {paintAxis && nodeEndpoints.map((endpoint, index) => {
              const row = mappingByEndpoint.get(endpoint.endpoint_id);
              const coordinate = row?.coordinates[paintAxis];
              const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(1, nodeEndpoints.length);
              const distance = radius + 9;
              return <g key={`ep-${endpoint.endpoint_id}`} className="parallel-satellite-group">
                <title>{`${row ? `rank ${row.rank}` : 'unmapped'} · ${paintAxis.toUpperCase()} ${coordinate ?? '—'} · router ${id}`}</title>
                <circle className="parallel-satellite" cx={p.x + Math.cos(angle) * distance} cy={p.y + Math.sin(angle) * distance} r={3.6} style={{ fill: coordinate !== undefined ? parallelColor(coordinate, degree) : '#c9d1da' }} />
              </g>;
            })}
            {showLabels && <text className={`gateway-node-id${selected === id ? ' selected' : ''}`} x={p.x} y={p.y + radius + (radius > 8 ? 11 : 12)} textAnchor="middle">{id}</text>}
            {!paintAxis && !showLabels && endpoints.get(id) && topology.counts?.routers <= 40 ? <text className="endpoint-count" x={p.x + radius + 4} y={p.y - radius} >{endpoints.get(id)}</text> : null}
          </g>;
        })}
      </g>
    </svg>
    <figcaption>
      <span className="mono">{topology.family}</span> · {topology.counts?.routers ?? 0} routers{topology.channels.length > 0 ? ` · ${topology.channels.length} directed channels` : ''}{shared.length > 0 ? ` · ${shared.length} shared wires` : ''} · {topology.counts?.endpoints ?? 0} endpoints
      {shared.length > 0 && <> · <strong>dashed lines are shared wires (one driver, many taps)</strong></>}
      <> · {links.length} router-pair links</>
      {telemetry && <> · <strong>Plane T telemetry overlay</strong></>}
      {derived && <> · <strong>derived layout; no router coordinates supplied</strong></>}
    </figcaption>
  </figure>;
}

// Plane C is a fixed k×k XY control mesh derived from the canonical
// ControlPlaneArtifact. It is a SECOND subnet, so it is drawn separately and
// never recoloured onto Plane D. No per-router selection: the artifact is
// declared structure, not a configurable data-plane fabric.
export function ControlPlaneGraph({ k, c, routing, vcs }: { k: number; c: number; routing: string; vcs: string[] }) {
  const points = new Map<number, Point>();
  const size = Math.min(760 / Math.max(k, 1), 520 / Math.max(k, 1), 130);
  const x0 = (800 - k * size) / 2 + size / 2;
  const y0 = (620 - k * size) / 2 + size / 2;
  for (let y = 0; y < k; y++) for (let x = 0; x < k; x++) points.set(y * k + x, { x: x0 + x * size, y: y0 + y * size });
  const links: [number, number][] = [];
  for (let y = 0; y < k; y++) for (let x = 0; x < k; x++) {
    const id = y * k + x;
    if (x + 1 < k) links.push([id, id + 1]);
    if (y + 1 < k) links.push([id, id + k]);
  }
  const radius = k > 6 ? 7 : 11;
  const viewBox = graphViewBox(points.values());
  return <figure className="topology-figure">
    <svg className="gateway-topology gateway-control-plane" viewBox={viewBox} role="img" aria-label={`Plane C declared control subnet, ${k} by ${k} mesh, ${k * k} routers`}>
      <g className="gateway-links">
        {links.map(([a, b]) => {
          const p = points.get(a), q = points.get(b);
          return p && q ? <line key={`${a}-${b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} /> : null;
        })}
      </g>
      <g className="gateway-nodes">
        {[...points.entries()].map(([id, p]) => <g key={id} className="gateway-node">
          <circle cx={p.x} cy={p.y} r={radius} />
          {k * k <= 25 && <text x={p.x} y={p.y + radius + 12} textAnchor="middle">{id}</text>}
        </g>)}
      </g>
    </svg>
    <figcaption><span className="mono">Plane C</span> · {k}×{k} mesh · {k * k} routers · {c} seats/router · <span className="mono">{routing.toUpperCase()}</span> · {vcs.join(' / ')} VCs · <strong>declared structure</strong></figcaption>
  </figure>;
}
