import {
  useCallback, useMemo, useRef, useState, type ReactElement,
} from 'react';
import type { TopologyView } from '../types';
import type { CanonicalRoute as RouteResult } from '../api';
import { agentLabel } from './FabricCanvas';

/**
 * The 2D Fabric Inspector (Gate 8 §55–§57, §15–§26 of the Phase-2 brief).
 *
 * Draws the **compiled** TopologyArtifact and AgentAttachmentArtifact:
 * routers at their canonical coordinates, directed channels collapsed to
 * physical links, and per-router seats showing occupancy. No synthetic
 * geometry, no perspective, no depth — concentration is local seat
 * capacity, never a z-axis.
 *
 * Three properties this component is responsible for:
 *
 *  * **wrap links are drawn as arcs**, derived from canonical coordinates
 *    (a channel joining routers more than one grid step apart is a
 *    wraparound). They are never approximated as ordinary local edges.
 *  * **unused seats are visible**: a router draws `seat_capacity` marks,
 *    the first `occupied` filled. No endpoint object is invented for an
 *    empty seat.
 *  * **every scientific visual has a data equivalent**: the router,
 *    channel and attachment tables below the drawing are the accessible
 *    representation, not prose.
 *
 * Selection is presentation state only and never mutates an artifact.
 */

export interface FabricSelectionState {
  kind: 'router' | 'channel' | 'endpoint' | null;
  id?: number;
}

const CELL = 96;
const MARGIN = 70;
const ROUTER_HALF = 26;
const SEAT_R = 2.6;
const SEAT_GAP = 6.2;

/** A channel joining routers more than one grid step apart is a wrap. */
function isWrap(a: TopologyView['routers'][number] | undefined,
                b: TopologyView['routers'][number] | undefined): boolean {
  if (!a || !b) return false;
  const ca = a.coordinates ?? [];
  const cb = b.coordinates ?? [];
  for (let i = 0; i < Math.max(ca.length, cb.length); i += 1) {
    if (Math.abs((ca[i] ?? 0) - (cb[i] ?? 0)) > 1) return true;
  }
  return false;
}

export default function FabricInspector2D({
  topology, route = null, showRoute = false, onSelectionChange,
}: {
  topology: TopologyView;
  /** The canonical DERIVED EXPECTED route to overlay, if any. */
  route?: RouteResult | null;
  showRoute?: boolean;
  onSelectionChange?: (selection: FabricSelectionState) => void;
}): ReactElement {
  const [selection, setSelection] = useState<FabricSelectionState>(
    { kind: null });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);

  const select = useCallback((next: FabricSelectionState) => {
    setSelection(next);
    onSelectionChange?.(next);
  }, [onSelectionChange]);

  const routerById = useMemo(
    () => new Map(topology.routers.map((r) => [r.router_id, r])),
    [topology.routers]);

  const occupiedByRouter = useMemo(() => {
    const counts = new Map<number, number>();
    for (const endpoint of topology.endpoints) {
      counts.set(endpoint.router_id, (counts.get(endpoint.router_id) ?? 0) + 1);
    }
    return counts;
  }, [topology.endpoints]);

  /** Undirected physical pairs, keeping the representative channel id. */
  const links = useMemo(() => {
    const byPair = new Map<string, {
      a: number; b: number; channelId: number; widthBits: number;
      wrap: boolean;
    }>();
    for (const channel of topology.channels) {
      const a = Math.min(channel.src_router, channel.dst_router);
      const b = Math.max(channel.src_router, channel.dst_router);
      if (a === b) continue;
      const key = `${a}-${b}`;
      const existing = byPair.get(key);
      if (!existing) {
        byPair.set(key, {
          a, b, channelId: channel.channel_id,
          widthBits: channel.width_bits,
          wrap: isWrap(routerById.get(a), routerById.get(b)),
        });
      } else {
        existing.widthBits = Math.max(existing.widthBits, channel.width_bits);
      }
    }
    return [...byPair.values()];
  }, [topology.channels, routerById]);

  const cols = Math.max(
    1, ...topology.routers.map((r) => (r.coordinates?.[0] ?? 0) + 1));
  const rows = Math.max(
    1, ...topology.routers.map((r) => (r.coordinates?.[1] ?? 0) + 1));
  const width = cols * CELL + MARGIN * 2;
  const height = rows * CELL + MARGIN * 2;

  const pos = (routerId: number): { x: number; y: number } => {
    const router = routerById.get(routerId);
    const col = router?.coordinates?.[0] ?? 0;
    const row = router?.coordinates?.[1] ?? 0;
    return {
      x: MARGIN + col * CELL + CELL / 2,
      y: MARGIN + row * CELL + CELL / 2,
    };
  };

  // Route overlay: the canonical channel sequence and the routers it visits.
  const routeChannelIds = useMemo(
    () => new Set((route?.hops ?? []).map((h) => h.channel_id)),
    [route]);
  const routeRouterIds = useMemo(
    () => new Set(route?.routers ?? []), [route]);

  const viewBox = `${-pan.x / zoom} ${-pan.y / zoom} `
    + `${width / zoom} ${height / zoom}`;

  const onWheel = (event: React.WheelEvent): void => {
    event.preventDefault();
    setZoom((z) => Math.min(4, Math.max(0.4, z * (event.deltaY < 0 ? 1.12 : 0.89))));
  };

  const selectedRouter = selection.kind === 'router'
    ? routerById.get(selection.id ?? -1) : undefined;
  const selectedEndpoints = selection.kind === 'router'
    ? topology.endpoints.filter((e) => e.router_id === selection.id)
    : [];

  return (
    <div className="fabric-inspector">
      <div className="fabric-toolbar">
        <div className="segmented small">
          <button onClick={() => setZoom((z) => Math.min(4, z * 1.25))}>+</button>
          <button onClick={() => setZoom((z) => Math.max(0.4, z / 1.25))}>−</button>
          <button onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>
            fit
          </button>
        </div>
        <span className="muted">
          {topology.routers.length} routers · {links.length} links ·{' '}
          {topology.endpoints.length} attached ·{' '}
          {topology.counts.seats - topology.endpoints.length} unused seats
          {' '}· zoom {zoom.toFixed(2)}×
        </span>
      </div>

      <svg
        className="canvas fabric-svg"
        viewBox={viewBox}
        role="img"
        aria-label={`Compiled fabric: ${topology.routers.length} routers, `
          + `${links.length} links, ${topology.endpoints.length} attached `
          + `endpoints. The router, channel and attachment tables below are `
          + `the data equivalent of this drawing.`}
        onWheel={onWheel}
        onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY }; }}
        onMouseUp={() => { drag.current = null; }}
        onMouseLeave={() => { drag.current = null; }}
        onMouseMove={(e) => {
          if (!drag.current) return;
          const dx = e.clientX - drag.current.x;
          const dy = e.clientY - drag.current.y;
          drag.current = { x: e.clientX, y: e.clientY };
          setPan((p) => ({ x: p.x - dx / zoom, y: p.y - dy / zoom }));
        }}
      >
        {links.map((link) => {
          const pa = pos(link.a);
          const pb = pos(link.b);
          const onRoute = showRoute && routeChannelIds.has(link.channelId);
          const classes = [
            'cv-link',
            link.wrap ? 'cv-link-wrap' : '',
            onRoute ? 'cv-link-route' : '',
            showRoute && !onRoute ? 'cv-link-subdued' : '',
          ].filter(Boolean).join(' ');
          if (link.wrap) {
            // A wraparound is drawn as an arc bulging away from the fabric
            // centre so it reads as a chord, never as a local edge.
            const midX = (pa.x + pb.x) / 2;
            const midY = (pa.y + pb.y) / 2;
            const centreX = MARGIN + (cols * CELL) / 2;
            const centreY = MARGIN + (rows * CELL) / 2;
            let nx = midX - centreX;
            let ny = midY - centreY;
            const len = Math.hypot(nx, ny) || 1;
            nx /= len; ny /= len;
            const bulge = 40;
            return (
              <path
                key={link.channelId}
                d={`M ${pa.x} ${pa.y} Q ${midX + nx * bulge} ${midY + ny * bulge} ${pb.x} ${pb.y}`}
                className={classes}
                fill="none"
                onClick={() => select({ kind: 'channel', id: link.channelId })}
              >
                <title>wrap link · channel {link.channelId}</title>
              </path>
            );
          }
          return (
            <line
              key={link.channelId}
              x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
              className={classes}
              strokeWidth={Math.max(1, Math.min(4, link.widthBits / 96))}
              onClick={() => select({ kind: 'channel', id: link.channelId })}
            >
              <title>channel {link.channelId}</title>
            </line>
          );
        })}

        {topology.routers.map((router) => {
          const p = pos(router.router_id);
          const occupied = occupiedByRouter.get(router.router_id) ?? 0;
          const capacity = router.seat_capacity;
          const onRoute = showRoute && routeRouterIds.has(router.router_id);
          // Seats are drawn one mark per unit of capacity: filled for an
          // occupied seat, hollow for unused capacity. No endpoint object
          // is invented for an empty seat.
          const seats = Array.from({ length: capacity }, (_, i) => i);
          return (
            <g key={router.router_id}>
              <rect
                x={p.x - ROUTER_HALF} y={p.y - ROUTER_HALF}
                width={ROUTER_HALF * 2} height={ROUTER_HALF * 2} rx={5}
                className={[
                  'cv-router',
                  'cv-clickable',
                  onRoute ? 'cv-router-route' : '',
                  selection.kind === 'router'
                    && selection.id === router.router_id
                    ? 'cv-router-selected' : '',
                ].filter(Boolean).join(' ')}
                onClick={() => select({ kind: 'router', id: router.router_id })}
              >
                <title>router {router.router_id}</title>
              </rect>
              <text x={p.x} y={p.y - 6} textAnchor="middle" className="cv-label">
                R{router.router_id}
              </text>
              <text x={p.x} y={p.y + 7} textAnchor="middle"
                    className="cv-label-sm">
                {occupied}/{capacity}
              </text>
              <g transform={`translate(${p.x - ((capacity - 1) * SEAT_GAP) / 2}, ${p.y + ROUTER_HALF + 10})`}>
                {seats.map((i) => (
                  <circle
                    key={i}
                    cx={i * SEAT_GAP} cy={0} r={SEAT_R}
                    className={i < occupied ? 'cv-seat-used' : 'cv-seat-unused'}
                  />
                ))}
              </g>
            </g>
          );
        })}

        {topology.endpoints.map((endpoint) => {
          const router = routerById.get(endpoint.router_id);
          if (!router) return null;
          const p = pos(endpoint.router_id);
          const siblings = topology.endpoints.filter(
            (e) => e.router_id === endpoint.router_id);
          const index = siblings.findIndex(
            (e) => e.endpoint_id === endpoint.endpoint_id);
          return (
            <circle
              key={endpoint.endpoint_id}
              cx={p.x - ((siblings.length - 1) * 10) / 2 + index * 10}
              cy={p.y + ROUTER_HALF + 24}
              r={4}
              className={[
                'cv-endpoint',
                `cv-endpoint-${endpoint.kind}`,
                selection.kind === 'endpoint'
                  && selection.id === endpoint.endpoint_id
                  ? 'cv-endpoint-selected' : '',
              ].join(' ')}
              onClick={() => select({ kind: 'endpoint',
                                      id: endpoint.endpoint_id })}
            >
              <title>
                {agentLabel(endpoint.kind)} · endpoint {endpoint.endpoint_id}
              </title>
            </circle>
          );
        })}

        {showRoute && route && route.routers.length > 1 && (
          <polyline
            className="cv-route-path"
            fill="none"
            points={route.routers
              .map((id) => { const p = pos(id); return `${p.x},${p.y}`; })
              .join(' ')}
          />
        )}
      </svg>

      <div className="canvas-legend">
        <span><i className="sw sw-router" /> router</span>
        <span><i className="sw sw-seat-used" /> occupied seat</span>
        <span><i className="sw sw-seat-unused" /> unused seat</span>
        <span><i className="sw sw-agent" /> attached agent</span>
        {links.some((l) => l.wrap) && (
          <span><i className="sw sw-wrap" /> wraparound link</span>
        )}
        {showRoute && (
          <span><i className="sw sw-route" /> canonical derived route
            (expected — not observed)</span>
        )}
      </div>

      {selectedRouter && (
        <div className="inspector-detail">
          <div className="inspector-head">
            <h5>Router {selectedRouter.router_id}</h5>
            <button className="btn btn-small"
                    onClick={() => select({ kind: null })}>×</button>
          </div>
          <div className="kv-grid">
            <div className="kv"><span>coordinates</span>
              <span className="num">
                {(selectedRouter.coordinates ?? []).join(', ')}
              </span></div>
            <div className="kv"><span>seat capacity</span>
              <span className="num">{selectedRouter.seat_capacity}</span></div>
            <div className="kv"><span>used seats</span>
              <span className="num">{selectedEndpoints.length}</span></div>
            <div className="kv"><span>unused seats</span>
              <span className="num">
                {selectedRouter.seat_capacity - selectedEndpoints.length}
              </span></div>
            <div className="kv"><span>incident channels</span>
              <span className="num">
                {topology.channels.filter(
                  (c) => c.src_router === selectedRouter.router_id
                    || c.dst_router === selectedRouter.router_id).length}
              </span></div>
          </div>
          {selectedEndpoints.length > 0 && (
            <table className="tbl">
              <thead>
                <tr><th>endpoint</th><th>agent</th><th>group</th>
                  <th>instance</th></tr>
              </thead>
              <tbody>
                {selectedEndpoints.map((e) => (
                  <tr key={e.endpoint_id}>
                    <td className="num">{e.endpoint_id}</td>
                    <td>{agentLabel(e.kind)}</td>
                    <td className="num">{e.group_index}</td>
                    <td className="num">{e.instance_index}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Gate 8 §24 / Phase-2 §19: the data equivalent of the drawing. */}
      <details className="fabric-tables">
        <summary>
          Data tables ({topology.routers.length} routers ·{' '}
          {topology.channels.length} channels · {topology.endpoints.length}{' '}
          attachments)
        </summary>
        <h5 className="inspector-label">Routers</h5>
        <table className="tbl">
          <thead>
            <tr><th>router</th><th>coordinates</th><th>seat capacity</th>
              <th>used</th><th>unused</th></tr>
          </thead>
          <tbody>
            {topology.routers.map((r) => {
              const used = occupiedByRouter.get(r.router_id) ?? 0;
              return (
                <tr key={r.router_id}>
                  <td className="num">{r.router_id}</td>
                  <td className="num">{(r.coordinates ?? []).join(', ')}</td>
                  <td className="num">{r.seat_capacity}</td>
                  <td className="num">{used}</td>
                  <td className="num">{r.seat_capacity - used}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <h5 className="inspector-label">Channels</h5>
        <table className="tbl">
          <thead>
            <tr><th>channel</th><th>src router</th><th>src port</th>
              <th>dst router</th><th>dst port</th><th>width</th>
              <th>wrap</th></tr>
          </thead>
          <tbody>
            {topology.channels.map((c) => (
              <tr key={c.channel_id}>
                <td className="num">{c.channel_id}</td>
                <td className="num">{c.src_router}</td>
                <td className="num">{c.src_port}</td>
                <td className="num">{c.dst_router}</td>
                <td className="num">{c.dst_port}</td>
                <td className="num">{c.width_bits}</td>
                <td>{isWrap(routerById.get(c.src_router),
                            routerById.get(c.dst_router)) ? 'yes' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h5 className="inspector-label">Attachments</h5>
        <table className="tbl">
          <thead>
            <tr><th>endpoint</th><th>agent</th><th>group</th>
              <th>instance</th><th>router</th></tr>
          </thead>
          <tbody>
            {topology.endpoints.map((e) => (
              <tr key={e.endpoint_id}>
                <td className="num">{e.endpoint_id}</td>
                <td>{agentLabel(e.kind)}</td>
                <td className="num">{e.group_index}</td>
                <td className="num">{e.instance_index}</td>
                <td className="num">{e.router_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
