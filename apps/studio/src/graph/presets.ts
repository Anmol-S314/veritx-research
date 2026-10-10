/** Graph presets: seed the authoring graph, any edit diverges to custom.
 * Authoring data only — lowering to the compiler lives in adapter.ts. */
import type { GraphEdge, GraphNode, LoomProject } from './project';

export type PresetId =
  | 'mesh-4x4' | 'mesh-8x8' | 'torus-4x4' | 'ring-8' | 'star-8' | 'tree-15' | 'srota-opt-16';

export const PRESETS: { id: PresetId; label: string; hint: string }[] = [
  { id: 'mesh-4x4', label: 'Mesh 4×4', hint: 'mesh' },
  { id: 'mesh-8x8', label: 'Mesh 8×8', hint: '8x8-mesh' },
  { id: 'torus-4x4', label: 'Torus 4×4', hint: 'torus' },
  { id: 'ring-8', label: 'Ring ×8', hint: 'ring' },
  { id: 'star-8', label: 'Star ×8', hint: 'star' },
  { id: 'tree-15', label: 'Tree ×15', hint: 'tree' },
  { id: 'srota-opt-16', label: 'Srota-Opt ×16', hint: 'srota-opt' },
];

const STEP = 120;
let edgeSeq = 0;
const edge = (src: string, dst: string, width = 512): GraphEdge => ({
  id: `e${++edgeSeq}`, src, dst, width, pipelineStages: 1, vcClass: 0,
});
const node = (id: string, x: number, y: number, role = 'compute_tile'): GraphNode => ({
  id, x, y, role, ports: 5, clock: 'clk_core',
});

function gridNodes(cols: number, rows: number, role: (i: number) => string): GraphNode[] {
  return Array.from({ length: cols * rows }, (_, i) => node(
    `n${i + 1}`,
    80 + (i % cols) * STEP,
    80 + Math.floor(i / cols) * STEP,
    role(i),
  ));
}
function meshEdges(cols: number, rows: number): GraphEdge[] {
  const out: GraphEdge[] = [];
  const at = (c: number, r: number): string => `n${r * cols + c + 1}`;
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    if (c + 1 < cols) out.push(edge(at(c, r), at(c + 1, r)));
    if (r + 1 < rows) out.push(edge(at(c, r), at(c, r + 1)));
  }
  return out;
}

export function buildPreset(id: PresetId): LoomProject {
  edgeSeq = 0;
  switch (id) {
    case 'mesh-4x4': {
      const nodes = gridNodes(4, 4, (i) => (i % 5 === 4 ? 'hbm_controller' : 'compute_tile'));
      return { schemaVersion: 1, presetHint: 'mesh', nodes, edges: meshEdges(4, 4) };
    }
    case 'mesh-8x8': {
      const nodes = gridNodes(8, 8, (i) => (i % 9 === 8 ? 'hbm_controller' : 'compute_tile'));
      return { schemaVersion: 1, presetHint: '8x8-mesh', nodes, edges: meshEdges(8, 8) };
    }
    case 'torus-4x4': {
      const nodes = gridNodes(4, 4, () => 'compute_tile');
      const edges = meshEdges(4, 4);
      for (let r = 0; r < 4; r++) edges.push(edge(`n${r * 4 + 1}`, `n${r * 4 + 4}`));
      for (let c = 0; c < 4; c++) edges.push(edge(`n${c + 1}`, `n${12 + c + 1}`));
      return { schemaVersion: 1, presetHint: 'torus', nodes, edges };
    }
    case 'ring-8': {
      const nodes = Array.from({ length: 8 }, (_, i) => node(
        `n${i + 1}`,
        320 + 220 * Math.cos((2 * Math.PI * i) / 8),
        260 + 220 * Math.sin((2 * Math.PI * i) / 8),
      ));
      const edges = nodes.map((n, i) => edge(n.id, nodes[(i + 1) % nodes.length].id));
      return { schemaVersion: 1, presetHint: 'ring', nodes, edges };
    }
    case 'star-8': {
      const hub = node('n1', 320, 260, 'nic');
      const nodes = [hub, ...Array.from({ length: 7 }, (_, i) => node(
        `n${i + 2}`,
        320 + 240 * Math.cos((2 * Math.PI * i) / 7),
        260 + 240 * Math.sin((2 * Math.PI * i) / 7),
      ))];
      return { schemaVersion: 1, presetHint: 'star', nodes, edges: nodes.slice(1).map((n) => edge('n1', n.id)) };
    }
    case 'tree-15': {
      const nodes: GraphNode[] = [];
      for (let level = 0; level < 4; level++) {
        const count = 2 ** level;
        for (let k = 0; k < count; k++) {
          const idx = 2 ** level + k;
          nodes.push(node(`n${idx}`, 120 + k * (960 / count), 80 + level * STEP,
            level === 3 ? 'compute_tile' : 'nic'));
        }
      }
      const edges: GraphEdge[] = [];
      for (let i = 1; i < 8; i++) { edges.push(edge(`n${i}`, `n${2 * i}`)); edges.push(edge(`n${i}`, `n${2 * i + 1}`)); }
      return { schemaVersion: 1, presetHint: 'tree', nodes, edges };
    }
    case 'srota-opt-16': {
      // 4×4 with express skip-1 links on rows 1,3 (hint only — compiler
      // lowers this as explicit/mesh until a srota intent kind exists).
      const nodes = gridNodes(4, 4, (i) => (i % 4 === 3 ? 'hbm_controller' : 'compute_tile'));
      const edges = meshEdges(4, 4);
      for (const r of [0, 2]) edges.push(edge(`n${r * 4 + 1}`, `n${r * 4 + 3}`, 1024));
      return { schemaVersion: 1, presetHint: 'srota-opt', nodes, edges };
    }
  }
}
