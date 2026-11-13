import type { Endpoint } from './model';
import { ROUTERS } from './model';

const X0 = 165;
const Y0 = 78;
const STEP_X = 190;
const STEP_Y = 112;
const NODE_W = 90;
const NODE_H = 44;

function point(router: string) {
  const [, row, col] = router.split('_').map(Number);
  return { x: X0 + col * STEP_X, y: Y0 + row * STEP_Y };
}

/** The configured X-then-Y route is an authored routing intent. It is drawn on
 *  logical coordinates only; no measured packet path or link counter is implied. */
export function LocalRouteDiagram({ route, source, target }: { route: string[]; source: Endpoint; target: Endpoint }) {
  const hops = route.map(point);
  const onRoute = new Set(route);
  const routePath = hops.map((hop, index) => `${index === 0 ? 'M' : 'L'} ${hop.x} ${hop.y}`).join(' ');
  const sourcePoint = point(source.router);
  const targetPoint = point(target.router);
  const sameRouter = source.router === target.router;
  return <figure className="topology-figure route-figure">
    <div className="route-canvas-scroll">
      <svg className="route-canvas" viewBox="0 0 900 500" role="img" aria-label={`Configured route from ${source.id} on ${source.router} to ${target.id} on ${target.router}: ${route.join(' to ')}`}>
        <g className="route-mesh">
          {ROUTERS.flatMap(id => {
            const p = point(id);
            const [, row, col] = id.split('_').map(Number);
            return [
              col < 3 ? <line key={`h-${id}`} x1={p.x} y1={p.y} x2={p.x + STEP_X} y2={p.y} /> : null,
              row < 3 ? <line key={`v-${id}`} x1={p.x} y1={p.y} x2={p.x} y2={p.y + STEP_Y} /> : null,
            ];
          })}
        </g>
        <g className="route-trace">
          <path className="route-underlay" d={routePath} />
          <path className="route-line" d={routePath} />
        </g>
        <g className="route-nodes">
          {ROUTERS.map(id => {
            const p = point(id);
            const kind = id === source.router ? ' source' : id === target.router ? ' target' : onRoute.has(id) ? ' on-route' : '';
            return <g key={id} className={`route-node${kind}`}>
              <rect x={p.x - NODE_W / 2} y={p.y - NODE_H / 2} width={NODE_W} height={NODE_H} rx={4} />
              <text x={p.x} y={p.y + 4} textAnchor="middle">{id}</text>
            </g>;
          })}
        </g>
        <g className="route-endpoints">
          <text className="route-endpoint source" x={sourcePoint.x} y={sourcePoint.y - NODE_H / 2 - 10} textAnchor="middle">{source.id}</text>
          <text className="route-endpoint target" x={targetPoint.x} y={targetPoint.y - NODE_H / 2 - 10 + (sameRouter ? NODE_H + 30 : 0)} textAnchor="middle">{target.id}</text>
        </g>
      </svg>
    </div>
    <figcaption>
      Configured route · <span className="mono">{route.join(' → ')}</span> · {route.length - 1} adjacent mesh link{route.length - 1 === 1 ? '' : 's'}.
      Logical mesh adjacency only; this is not an observed packet path, a latency measurement, or an access-permission check.
    </figcaption>
  </figure>;
}
