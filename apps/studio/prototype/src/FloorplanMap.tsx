import type { FloorplanView } from './gateway';

/** Authored grid geometry only. This is not a floorplan from a placer, a
 *  congestion map, or signoff geometry. */
export type FloorplanAnnotation = { id: string; label: string; x_um: number; y_um: number; width_um: number; height_um: number };

export function FloorplanMap({ view, annotations = [] }: { view: FloorplanView; annotations?: FloorplanAnnotation[] }) {
  const floorplan = view.floorplan;
  if (!floorplan) return null;
  const { die_width_um: width, die_height_um: height, routers, keepouts } = floorplan;
  const margin = Math.max(width, height) * 0.05;
  const label = routers.length <= 64;
  return <figure className="topology-figure floorplan-figure">
    <div className="floorplan-canvas-scroll">
      <svg className="floorplan-canvas" viewBox={`${-margin} ${-margin} ${width + margin * 2} ${height + margin * 2}`} role="img" aria-label={`Declared floorplan ${width} by ${height} micrometres, ${routers.length} router rectangles and ${keepouts.length} keepouts`}>
        <rect className="floorplan-die" x={0} y={0} width={width} height={height} />
        {keepouts.map(keepout => <rect key={keepout.keepout_id} className="floorplan-keepout" x={keepout.x_um} y={keepout.y_um} width={keepout.width_um} height={keepout.height_um}>
          <title>{`Keepout ${keepout.keepout_id} · ${keepout.width_um} × ${keepout.height_um} µm`}</title>
        </rect>)}
        {annotations.map(annotation => <g key={annotation.id} className="floorplan-anchor">
          <rect x={annotation.x_um} y={annotation.y_um} width={annotation.width_um} height={annotation.height_um}>
            <title>{`${annotation.label} · ${annotation.width_um} × ${annotation.height_um} µm at ${annotation.x_um}, ${annotation.y_um} µm`}</title>
          </rect>
        </g>)}
        {routers.map(router => <g key={router.router_id} className="floorplan-router">
          <rect x={router.x_um} y={router.y_um} width={router.width_um} height={router.height_um} rx={Math.min(router.width_um, router.height_um) * 0.1}>
            <title>{`Router R${router.router_id} · ${router.x_um}, ${router.y_um} µm · ${router.width_um} × ${router.height_um} µm`}</title>
          </rect>
          {label && <text x={router.x_um + router.width_um / 2} y={router.y_um + router.height_um / 2} textAnchor="middle" dominantBaseline="central" style={{ fontSize: Math.min(router.width_um, router.height_um) * 0.36 }}>{router.router_id}</text>}
        </g>)}
      </svg>
    </div>
    <div className="legend">
      <span><i className="legend-dot" />Die {width} × {height} µm</span>
      <span><i className="legend-dot blue" />Declared router</span>
      <span><i className="legend-dot red" />Keepout</span>
      {annotations.length > 0 && <span><i className="legend-dot amber" />Declared anchor window (allowed, not reserved)</span>}
      <span>{routers.length} routers · {keepouts.length} keepouts · authored geometry, not placement or signoff</span>
    </div>
  </figure>;
}
