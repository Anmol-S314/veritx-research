import type { ReactElement } from 'react';
import { fmtNum } from './badges';
import { bucketOf, strokeFor, type FabricModel, type FabricNode } from '../fabricLayout';

export type Overlay = 'structure' | 'routing' | 'vc-class' | 'traffic-class' | 'utilization';

export const OVERLAYS: { id: Overlay; label: string; needs: string }[] = [
  { id: 'structure', label: 'Structure', needs: '' },
  {
    id: 'routing',
    label: 'Routing',
    needs: 'Per-flow route dump. Contract views carry only the derived algorithm.',
  },
  {
    id: 'vc-class',
    label: 'VC class',
    needs: 'Per-channel VC assignment table from the bundle (engine-side artifact).',
  },
  {
    id: 'traffic-class',
    label: 'Traffic class',
    needs: 'Per-class counters. Evaluation yields one aggregate window only.',
  },
  {
    id: 'utilization',
    label: 'Utilization',
    needs: 'Per-link load counters, which no frozen view carries.',
  },
];

/** Presentation labels are friendlier than engine values (AgentKind). */
export const AGENT_LABELS: Record<string, string> = {
  compute_tile: 'Compute tile',
  hbm_controller: 'HBM controller',
  nic: 'NIC',
  peripheral: 'Peripheral',
  ucie_port: 'UCIe port',
};

export function agentLabel(kind: string): string {
  return AGENT_LABELS[kind] ?? kind;
}

const CHIP_CLASS: Record<string, string> = {
  compute: 'cv-agent',
  hbm: 'cv-hbm',
  nic: 'cv-edge',
  edge: 'cv-edge',
};

/** Per-router chips drawn from the materialized endpoint set. */
function chips(node: FabricNode): string[] {
  return Object.entries(node.attached)
    .sort(([a], [b]) => a.localeCompare(b))
    .flatMap(([kind, count]) =>
      Array.from({ length: Math.min(count, 8) }, () => bucketOf(kind)));
}

/**
 * Pure 2D structural renderer. Overlay selection is owned by FabricView.
 *
 * `model.source === 'topology'` draws the certified graph: router
 * coordinates, collapsed physical links, per-router agent seats. The
 * `intent` preview draws declared counts only — side blocks are declared
 * agents whose attachment position is not materialized yet, and say so
 * in the legend.
 */
export default function FabricCanvas({ model }: {
  model: FabricModel;
  overlay?: Overlay;
}): ReactElement {
  const { nodes, edges, cols, rows, concentration, totals, source } = model;
  const materialized = source === 'topology';

  const CELL = 96;
  const M = 70; // margin for edge blocks
  const W = Math.max(1, cols) * CELL + M * 2;
  const H = Math.max(1, rows) * CELL + M * 2 + 34; // +34 for HBM row
  const R = 26; // router half-size
  const linkStroke = strokeFor(model.linkWidth);

  const pos = (node: FabricNode): { x: number; y: number } => ({
    x: M + node.col * CELL + CELL / 2,
    y: M + node.row * CELL + CELL / 2 + 17,
  });

  const nodeId = new Map(nodes.map((n) => [n.id, n]));

  const hbmTop = Math.ceil(totals.hbm / 2);
  const hbmBottom = totals.hbm - hbmTop;

  const hbmBlock = (k: number, x: number, y: number, label: string): ReactElement => (
    <g key={k}>
      <rect x={x - 30} y={y - 12} width={60} height={24} rx={3} className="cv-hbm" />
      <text x={x} y={y + 4} textAnchor="middle" className="cv-label-sm">
        {label}
      </text>
    </g>
  );

  return (
    <div className="canvas-wrap">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="canvas"
        role="img"
        aria-label={materialized
          ? `Fabric structure: ${nodes.length} routers, ${edges.length} links`
          : `Fabric preview: ~${nodes.length} routers from declared counts`}
      >
        {/* links */}
        {edges.map((edge, k) => {
          const na = nodeId.get(edge.a);
          const nb = nodeId.get(edge.b);
          if (!na || !nb) return null;
          const pa = pos(na);
          const pb = pos(nb);
          return (
            <line
              key={k}
              x1={pa.x}
              y1={pa.y}
              x2={pb.x}
              y2={pb.y}
              className="cv-link"
              strokeWidth={linkStroke}
            />
          );
        })}
        {/* routers (+ materialized seats) */}
        {nodes.map((node) => {
          const p = pos(node);
          const seats = chips(node);
          const seated = Object.values(node.attached)
            .reduce((sum, count) => sum + count, 0);
          return (
            <g key={node.id}>
              <rect
                x={p.x - R}
                y={p.y - R}
                width={R * 2}
                height={R * 2}
                rx={5}
                className="cv-router"
              />
              <text x={p.x} y={p.y - 4} textAnchor="middle" className="cv-label">
                R{node.row},{node.col}
              </text>
              <text x={p.x} y={p.y + 11} textAnchor="middle" className="cv-label-sm">
                {materialized
                  ? `${seated}/${node.seats} seat${node.seats === 1 ? '' : 's'}`
                  : `conc. ${concentration}`}
              </text>
              {seats.length > 0 && (
                <g>
                  <line
                    x1={p.x}
                    y1={p.y + R}
                    x2={p.x}
                    y2={p.y + R + 8}
                    className="cv-stub"
                  />
                  {seats.map((bucket, i) => (
                    <circle
                      key={i}
                      cx={p.x + (i - (seats.length - 1) / 2) * 9}
                      cy={p.y + R + 12}
                      r={3.5}
                      className={CHIP_CLASS[bucket] ?? 'cv-agent'}
                    />
                  ))}
                </g>
              )}
            </g>
          );
        })}
        {/* preview only: declared HBM controllers, attachment not materialized */}
        {!materialized && Array.from({ length: hbmTop }, (_, k) => {
          const anchor = pos(nodes[Math.min(k, nodes.length - 1)]);
          const x = M + ((k + 0.5) / Math.max(1, hbmTop)) * (cols * CELL);
          return (
            <g key={`t${k}`}>
              {hbmBlock(k, x, 22, `HBM${k}`)}
              <line x1={x} y1={34} x2={anchor.x} y2={anchor.y - R} className="cv-hbm-link" />
            </g>
          );
        })}
        {!materialized && Array.from({ length: hbmBottom }, (_, k) => {
          const idx = hbmTop + k;
          const anchor = pos(nodes[Math.max(0, nodes.length - 1 - k)]);
          const x = M + ((k + 0.5) / Math.max(1, hbmBottom)) * (cols * CELL);
          return (
            <g key={`b${k}`}>
              {hbmBlock(idx, x, H - 22, `HBM${idx}`)}
              <line x1={x} y1={H - 34} x2={anchor.x} y2={anchor.y + R} className="cv-hbm-link" />
            </g>
          );
        })}
        {/* preview only: declared NIC / peripheral agents */}
        {!materialized && Array.from(
          { length: Math.min(totals.edge, Math.max(1, rows)) },
          (_, k) => {
            const y = M + k * CELL + CELL / 2 + 17;
            return (
              <g key={`e${k}`}>
                <rect x={8} y={y - 12} width={44} height={24} rx={3} className="cv-edge" />
                <text x={30} y={y + 4} textAnchor="middle" className="cv-label-sm">
                  {k < totals.nic ? `NIC${k}` : `P${k}`}
                </text>
              </g>
            );
          },
        )}
      </svg>

      <div className="canvas-legend">
        <span>
          <i className="sw sw-router" /> router
          {' '}
          {materialized ? `(seat cap. ${fmtNum(nodes[0]?.seats ?? 1)})`
            : `(conc. ${fmtNum(concentration)}, preview)`}
        </span>
        <span>
          <i className="sw sw-link" /> link (width ∝ link width)
        </span>
        {materialized ? (
          <span>
            <i className="sw sw-agent" /> attached agent
            {' '}
            ({fmtNum(model.counts.endpoints)})
          </span>
        ) : (
          <>
            <span>
              <i className="sw sw-hbm" /> declared HBM
              {' '}
              ({fmtNum(totals.hbm)}) — position not materialized
            </span>
            <span>
              <i className="sw sw-edge" /> declared NIC / peripheral
              {' '}
              ({fmtNum(totals.edge)}) — position not materialized
            </span>
          </>
        )}
      </div>
    </div>
  );
}
