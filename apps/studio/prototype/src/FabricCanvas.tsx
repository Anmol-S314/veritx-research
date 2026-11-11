import { useState } from 'react';

export type FabricLink = [number, number];

export function parseFabricLinks(text: string): FabricLink[] {
  return text.split('\n').map(line => line.trim()).filter(Boolean).map(line => line.split(/\s+/).map(Number)).filter(parts => parts.length === 2 && parts.every(Number.isInteger)) as FabricLink[];
}

// The authoring canvas for explicit fabrics: nodes are placed from the declared count, and a link
// is added or removed by clicking its two endpoints. It edits the declaration, never a picture.
export function FabricCanvas({ nodes, links, onToggleLink }: { nodes: number; links: FabricLink[]; onToggleLink: (a: number, b: number) => void }) {
  const [pick, setPick] = useState<number | null>(null);
  const count = Math.max(0, Math.min(256, nodes));
  const cols = Math.max(1, Math.ceil(Math.sqrt(count)));
  const position = (index: number) => ({ x: 40 + (cols === 1 ? 0 : (index % cols) * (560 / (cols - 1))), y: 36 + Math.floor(index / cols) * 46 });
  const pickNode = (index: number) => {
    if (pick === null || pick === index) { setPick(pick === index ? null : index); return; }
    onToggleLink(pick, index);
    setPick(null);
  };
  return <div className="graph-canvas">
    <svg viewBox={`0 0 640 ${Math.max(140, 70 + Math.ceil(count / cols) * 46)}`} role="group" aria-label="Explicit fabric canvas; click two nodes to toggle a link">
      {links.map(([a, b], index) => {
        if (a >= count || b >= count) return null;
        const p = position(a), q = position(b);
        return <line key={`${a}-${b}-${index}`} className="graph-edge" x1={p.x} y1={p.y} x2={q.x} y2={q.y} onClick={() => onToggleLink(a, b)} />;
      })}
      {Array.from({ length: count }, (_, index) => {
        const p = position(index);
        return <g key={index} className={`graph-node${pick === index ? ' picked' : ''}`} role="button" tabIndex={0} aria-label={`Node ${index}${pick === index ? ', anchor' : ''}`} onClick={() => pickNode(index)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pickNode(index); } }}>
          <circle cx={p.x} cy={p.y} r={9} />
          {count <= 64 && <text x={p.x} y={p.y + 3} textAnchor="middle">{index}</text>}
        </g>;
      })}
    </svg>
    <p className="meta-line">{pick !== null ? `Anchor: node ${pick}.` : 'No anchor selected.'} {links.length} declared link{links.length === 1 ? '' : 's'}{count >= 256 ? ' (canvas capped at 256 nodes; the text list is authoritative)' : ''}.</p>
    {count === 0 && <p className="meta-line">Set a node count to place nodes on the canvas.</p>}
  </div>;
}

export function toggleFabricLink(links: FabricLink[], a: number, b: number): FabricLink[] {
  if (a === b) return links;
  const lo = Math.min(a, b), hi = Math.max(a, b);
  const exists = links.some(([x, y]) => Math.min(x, y) === lo && Math.max(x, y) === hi);
  return exists ? links.filter(([x, y]) => !(Math.min(x, y) === lo && Math.max(x, y) === hi)) : [...links, [lo, hi]];
}
