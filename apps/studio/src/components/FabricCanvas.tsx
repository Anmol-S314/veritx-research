import { useState, type ReactElement } from 'react';
import type { TopologyView } from '../types';
import { fmtNum } from './badges';
import { bucketOf, strokeFor, type FabricModel, type FabricNode } from '../fabricLayout';
import FabricInspector, { type FabricSelection } from './FabricInspector';
import { additiveGesture } from '../util';

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

function chips(node: FabricNode): string[] {
  return Object.entries(node.attached)
    .sort(([a], [b]) => a.localeCompare(b))
    .flatMap(([kind, count]) =>
      Array.from({ length: Math.min(count, 8) }, () => bucketOf(kind)));
}

export default function FabricCanvas({ model, topology, selection, onSelect }: {
  model: FabricModel;
  topology?: TopologyView | null;
  overlay?: Overlay;
  /** The selection this canvas draws, when someone else owns it. A list,
   *  because the certified graph is a graph: the Loom workspace hands over
   *  every held vertex and edge at once. Omit it and the canvas holds its own,
   *  which is what a draft page with nowhere to put an inspector wants. */
  selection?: FabricSelection[] | null;
  /** `additive` is the modifier gesture off the originating event. It travels
   *  with the pick so the receiving store decides what accumulating means,
   *  rather than the canvas guessing from a global. */
  onSelect?: (s: FabricSelection | null, additive: boolean) => void;
}): ReactElement {
  const { nodes, edges, cols, rows, concentration, totals, source } = model;
  const materialized = source === 'topology';
  const [local, setLocal] = useState<FabricSelection | null>(null);
  const held: FabricSelection[] = selection === undefined
    ? (local ? [local] : [])
    : (selection ?? []);

  // Selection is reported upward as well as held, so the draft canvas can drive
  // an inspector even though it has no certified topology to inspect.
  const select = (s: FabricSelection | null, additive = false): void => {
    setLocal(s);
    onSelect?.(s, additive);
  };

  const channelByPair = new Map<string, number>();
  if (topology) {
    for (const c of topology.channels) {
      const key = `${Math.min(c.src_router, c.dst_router)}-`
        + `${Math.max(c.src_router, c.dst_router)}`;
      if (!channelByPair.has(key)) channelByPair.set(key, c.channel_id);
    }
  }
  const heldIds = <K extends 'routerId' | 'channelId' | 'endpointId'>(
    field: K,
  ): Set<number> => new Set(
    held.flatMap((s) => {
      const value = s[field];
      return value === undefined ? [] : [value];
    }),
  );
  const heldNodes = heldIds('routerId');
  const heldChannels = heldIds('channelId');
  const heldEndpoints = heldIds('endpointId');
  const pairKey = (a: number, b: number): string => (
    `${Math.min(a, b)}-${Math.max(a, b)}`
  );
  const edgeHeld = (a: number, b: number): boolean => {
    const channel = channelByPair.get(pairKey(a, b));
    return channel !== undefined && heldChannels.has(channel);
  };
  // Routers are selectable on the draft too — the draft already knows where
  // every router lands, so refusing selection there would hide the one surface
  // where a change is actually authored.
  const pickRouter = (id: number, additive = false): void =>
    select({ kind: 'router', routerId: id }, additive);
  const pickLink = materialized
    ? (a: number, b: number, additive = false) =>
      select({
        kind: 'channel',
        channelId: channelByPair.get(
          `${Math.min(a, b)}-${Math.max(a, b)}`,
        ),
      }, additive)
    : undefined;
  const nodeEndpoints = (routerId: number) =>
    topology
      ? topology.endpoints.filter((e) => e.router_id === routerId)
      : [];

  const CELL = 96;
  const M = 70; 
  const W = Math.max(1, cols) * CELL + M * 2;
  const H = Math.max(1, rows) * CELL + M * 2 + 34; 
  const R = 26; 
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
        
        {edges.map((edge, k) => {
          const na = nodeId.get(edge.a);
          const nb = nodeId.get(edge.b);
          if (!na || !nb) return null;
          const pa = pos(na);
          const pb = pos(nb);
          if (edge.kind === 'wrap') {
            const midX = (pa.x + pb.x) / 2;
            const midY = (pa.y + pb.y) / 2;
            const centreX = M + (cols * CELL) / 2;
            const centreY = M + 17 + (rows * CELL) / 2;
            let nx = midX - centreX;
            let ny = midY - centreY;
            const len = Math.hypot(nx, ny) || 1;
            nx /= len;
            ny /= len;
            const bulge = 34;
            return (
              <path
                key={k}
                d={`M ${pa.x} ${pa.y} Q ${midX + nx * bulge} ${midY + ny * bulge} ${pb.x} ${pb.y}`}
                className="cv-link cv-link-wrap"
                fill="none"
                strokeWidth={linkStroke}
              >
                <title>declared wrap link (preview)</title>
              </path>
            );
          }
          return (
            <line
              key={k}
              x1={pa.x}
              y1={pa.y}
              x2={pb.x}
              y2={pb.y}
              className={`cv-link${edge.kind === 'tree' ? ' cv-link-tree' : ''}${pickLink ? ' cv-clickable' : ''}${edgeHeld(edge.a, edge.b) ? ' cv-selected' : ''}`}
              strokeWidth={linkStroke}
              onClick={pickLink
                ? (e) => pickLink(edge.a, edge.b, additiveGesture(e))
                : undefined}
            >
              {pickLink && <title>inspect channel</title>}
            </line>
          );
        })}
        
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
                className={`cv-router cv-clickable${heldNodes.has(node.id) ? ' cv-selected' : ''}`}
                onClick={(e) => pickRouter(node.id, additiveGesture(e))}
              >
                <title>inspect router R{node.row},{node.col}</title>
              </rect>
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
                  
                  {materialized && topology && nodeEndpoints(node.id).map((e, i) => (
                    <circle
                      key={`ep${e.endpoint_id}`}
                      cx={p.x + (i - (seats.length - 1) / 2) * 9}
                      cy={p.y + R + 12}
                      r={5.5}
                      className={`cv-endpoint-hit${
                        heldEndpoints.has(e.endpoint_id) ? ' cv-endpoint-sel' : ''}`}
                      onClick={(ev) => select(
                        { kind: 'endpoint', endpointId: e.endpoint_id },
                        additiveGesture(ev),
                      )}
                    >
                      <title>
                        {e.kind} g{e.group_index} i{e.instance_index}
                      </title>
                    </circle>
                  ))}
                </g>
              )}
            </g>
          );
        })}
        
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

      {topology && (
        <FabricInspector
          topology={topology}
          selection={held.length === 1 ? held[0] : null}
          onClose={() => select(null)}
        />
      )}

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
