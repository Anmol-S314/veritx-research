// Topology graph visualization: base vs generated candidate.
// Added links (candidate-only), removed links (base-only, dashed),
// kept links. Routers as grid-positioned nodes; degree shown beside
// high-degree routers. Pure rendering of explicit link lists — React
// infers no routing, no performance, no qualification here.
import type { ReactElement } from 'react';
import { diffGraphs, type Edge } from './graph';

const ADDED = '#2f9e44';
const REMOVED = '#e03131';
const KEPT = '#868e96';

export function TopologyGraph({
  base,
  candidate,
  nodes,
  k,
  title,
}: {
  base: Edge[];
  candidate: Edge[] | null;
  nodes: number;
  k: number;
  title?: string;
}): ReactElement {
  const W = 460;
  const H = 340;
  const pad = 34;
  const spanX = Math.max(k - 1, 1);
  const rows = Math.max(Math.ceil(nodes / k), 1);
  const spanY = Math.max(rows - 1, 1);
  const X = (id: number): number =>
    pad + ((id % k) / spanX) * (W - 2 * pad);
  const Y = (id: number): number =>
    pad + (Math.floor(id / k) / spanY) * (H - 2 * pad);

  const diff = candidate ? diffGraphs(base, candidate) : null;
  const keyOf = (e: Edge): string => `${e[0]}-${e[1]}`;
  const clsOf = (e: Edge): { stroke: string; dash: string } => {
    if (!diff) return { stroke: KEPT, dash: '' };
    const key = keyOf(e);
    if (diff.added.some((a) => keyOf(a) === key)) {
      return { stroke: ADDED, dash: '' };
    }
    if (diff.removed.some((r) => keyOf(r) === key)) {
      return { stroke: REMOVED, dash: '5 4' };
    }
    return { stroke: KEPT, dash: '' };
  };
  const drawn = candidate
    ? [...(diff?.kept ?? []), ...(diff?.added ?? []), ...(diff?.removed ?? [])]
    : base;
  const addedKeys = new Set((diff?.added ?? []).map(keyOf));
  const deg = new Map<number, number>();
  (candidate ?? base).forEach(([u, v]) => {
    deg.set(u, (deg.get(u) ?? 0) + 1);
    deg.set(v, (deg.get(v) ?? 0) + 1);
  });
  const maxDeg = Math.max(0, ...deg.values());

  return (
    <figure className="topo-graph">
      {title && <figcaption className="muted">{title}</figcaption>}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={title ?? 'topology graph: base versus candidate links'}
      >
        {drawn.map((e) => {
          const c = clsOf(e);
          return (
            <line
              key={keyOf(e)}
              x1={X(e[0])}
              y1={Y(e[0])}
              x2={X(e[1])}
              y2={Y(e[1])}
              stroke={c.stroke}
              strokeWidth={addedKeys.has(keyOf(e)) ? 2.4 : 1.4}
              strokeDasharray={c.dash || undefined}
              opacity={0.85}
            />
          );
        })}
        {Array.from({ length: nodes }, (_, id) => (
          <g key={id}>
            <circle cx={X(id)} cy={Y(id)} r={7} fill="#fff" stroke="#343a40" strokeWidth={1.4} />
            <text x={X(id)} y={Y(id) + 3.4} textAnchor="middle" fontSize={8.5} fill="#343a40">
              {id}
            </text>
            {(deg.get(id) ?? 0) === maxDeg && maxDeg > 0 && (
              <text x={X(id) + 10} y={Y(id) - 8} fontSize={9} fill="#495057">
                d{maxDeg}
              </text>
            )}
          </g>
        ))}
      </svg>
      <div className="graph-legend muted">
        <span><i className="sw" style={{ background: KEPT }} /> kept</span>{' '}
        <span><i className="sw" style={{ background: ADDED }} /> added</span>{' '}
        <span><i className="sw" style={{ background: REMOVED }} /> removed</span>{' '}
        <span>layout: {k}×{rows} grid positions (drawing aid only — not physical placement)</span>
      </div>
    </figure>
  );
}
