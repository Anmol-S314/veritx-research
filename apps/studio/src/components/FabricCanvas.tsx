import { useState, type ReactElement } from 'react';
import type { DesignView } from '../types';
import { fmtNum } from './badges';

type Overlay = 'structure' | 'routing' | 'vc-class' | 'traffic-class' | 'utilization';

const OVERLAYS: { id: Overlay; label: string; needs: string }[] = [
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

function agentCount(d: DesignView, kind: string): number {
  return d.agents.filter((a) => a.kind === kind).reduce((s, a) => s + a.count, 0);
}

function gridFor(routers: number): { cols: number; rows: number } {
  const cols = Math.max(1, Math.ceil(Math.sqrt(Math.max(1, routers))));
  const rows = Math.max(1, Math.ceil(Math.max(1, routers) / cols));
  return { cols, rows };
}

function strokeFor(linkWidth: number | null): number {
  if (!linkWidth) return 1.5;
  if (linkWidth <= 64) return 1.5;
  if (linkWidth <= 128) return 2.5;
  return 4;
}

/** Structural fabric canvas derived from the DesignView only. */
export default function FabricCanvas({ design }: { design: DesignView }): ReactElement {
  const [overlay, setOverlay] = useState<Overlay>('structure');

  const compute = agentCount(design, 'compute');
  const hbm = agentCount(design, 'hbm');
  const edge = agentCount(design, 'nic') + agentCount(design, 'peripheral');
  const conc = design.noc_guided.concentration ?? 1;
  const routerCount = Math.max(1, Math.ceil(compute / Math.max(1, conc)));
  const { cols, rows } = gridFor(routerCount);

  const CELL = 96;
  const M = 70; // margin for edge blocks
  const W = cols * CELL + M * 2;
  const H = rows * CELL + M * 2 + 34; // +34 for HBM row
  const R = 26; // router half-size
  const linkStroke = strokeFor(design.noc_guided.link_width);

  const pos = (i: number): { x: number; y: number } => {
    const c = i % cols;
    const r = Math.floor(i / cols);
    return { x: M + c * CELL + CELL / 2, y: M + r * CELL + CELL / 2 + 17 };
  };

  // Mesh neighbor links between existing routers.
  const links: [number, number][] = [];
  for (let i = 0; i < routerCount; i++) {
    const c = i % cols;
    const r = Math.floor(i / cols);
    if (c + 1 < cols && i + 1 < routerCount && Math.floor((i + 1) / cols) === r) {
      links.push([i, i + 1]);
    }
    if (r + 1 < rows && i + cols < routerCount) links.push([i, i + cols]);
  }

  const hbmTop = Math.ceil(hbm / 2);
  const hbmBottom = hbm - hbmTop;

  const hbmBlock = (k: number, x: number, y: number, label: string): ReactElement => (
    <g key={k}>
      <rect x={x - 30} y={y - 12} width={60} height={24} rx={3} className="cv-hbm" />
      <text x={x} y={y + 4} textAnchor="middle" className="cv-label-sm">
        {label}
      </text>
    </g>
  );

  const activeOverlay = OVERLAYS.find((o) => o.id === overlay);

  return (
    <div className="canvas-wrap">
      <div className="canvas-toolbar">
        <div className="overlay-tabs" role="tablist" aria-label="Canvas overlays">
          {OVERLAYS.map((o) => (
            <button
              key={o.id}
              role="tab"
              aria-selected={overlay === o.id}
              className={`overlay-tab${overlay === o.id ? ' active' : ''}`}
              onClick={() => setOverlay(o.id)}
              title={o.needs || 'Structural view (routers, links, attachments)'}
            >
              {o.label}
            </button>
          ))}
        </div>
        <div className="canvas-meta">
          {routerCount} routers · {links.length} links · {compute} tiles · {hbm} HBM ·
          link width {design.noc_guided.link_width ?? '—'}
        </div>
      </div>

      {overlay !== 'structure' && activeOverlay && (
        <div className="overlay-note">
          <strong>{activeOverlay.label} overlay — extension point, not rendered.</strong>{' '}
          {activeOverlay.needs} The canvas shows structure only; nothing is
          color-fabricated from aggregate data.
        </div>
      )}

      <svg viewBox={`0 0 ${W} ${H}`} className="canvas" role="img" aria-label="Fabric structure">
        {/* links */}
        {links.map(([a, b], k) => {
          const pa = pos(a);
          const pb = pos(b);
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
        {/* routers + attached tiles */}
        {Array.from({ length: routerCount }, (_, i) => {
          const p = pos(i);
          const tiles = Math.min(conc, compute - i * conc);
          return (
            <g key={i}>
              <rect x={p.x - R} y={p.y - R} width={R * 2} height={R * 2} rx={5} className="cv-router" />
              <text x={p.x} y={p.y - 4} textAnchor="middle" className="cv-label">
                R{Math.floor(i / cols)},{i % cols}
              </text>
              <text x={p.x} y={p.y + 11} textAnchor="middle" className="cv-label-sm">
                ×{tiles} tile{tiles === 1 ? '' : 's'}
              </text>
              {/* attachment stub */}
              <line x1={p.x} y1={p.y + R} x2={p.x} y2={p.y + R + 10} className="cv-stub" />
              <circle cx={p.x} cy={p.y + R + 12} r={3} className="cv-agent" />
            </g>
          );
        })}
        {/* HBM blocks on north/south edges */}
        {Array.from({ length: hbmTop }, (_, k) => {
          const anchor = pos(Math.min(k, routerCount - 1));
          const x = M + ((k + 0.5) / Math.max(1, hbmTop)) * (cols * CELL);
          const el = hbmBlock(k, x, 22, `HBM${k}`);
          return (
            <g key={`t${k}`}>
              {el}
              <line x1={x} y1={34} x2={anchor.x} y2={anchor.y - R} className="cv-hbm-link" />
            </g>
          );
        })}
        {Array.from({ length: hbmBottom }, (_, k) => {
          const idx = hbmTop + k;
          const anchor = pos(Math.min(routerCount - 1 - k, routerCount - 1));
          const x = M + ((k + 0.5) / Math.max(1, hbmBottom)) * (cols * CELL);
          const el = hbmBlock(idx, x, H - 22, `HBM${idx}`);
          return (
            <g key={`b${k}`}>
              {el}
              <line x1={x} y1={H - 34} x2={anchor.x} y2={anchor.y + R} className="cv-hbm-link" />
            </g>
          );
        })}
        {/* edge (NIC/peripheral) blocks on west edge */}
        {Array.from({ length: Math.min(edge, rows) }, (_, k) => {
          const y = M + k * CELL + CELL / 2 + 17;
          return (
            <g key={`e${k}`}>
              <rect x={8} y={y - 12} width={44} height={24} rx={3} className="cv-edge" />
              <text x={30} y={y + 4} textAnchor="middle" className="cv-label-sm">
                {k < agentCount(design, 'nic') ? `NIC${k}` : `P${k}`}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="canvas-legend">
        <span>
          <i className="sw sw-router" /> router (conc. {fmtNum(conc)})
        </span>
        <span>
          <i className="sw sw-link" /> mesh link (width ∝ link_width)
        </span>
        <span>
          <i className="sw sw-hbm" /> HBM controller
        </span>
        <span>
          <i className="sw sw-agent" /> agent attachment
        </span>
        <span>
          <i className="sw sw-edge" /> NIC / peripheral
        </span>
      </div>
    </div>
  );
}
