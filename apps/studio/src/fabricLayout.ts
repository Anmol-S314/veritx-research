// One derivation of the fabric layout from a DesignView, shared by the 2D
// and 3D canvases. It reads only declared intent (agents, concentration,
// topology family) — never a fabricated artifact.
import type { DesignView } from './types';

export function agentCount(design: DesignView, kind: string): number {
  return design.agents
    .filter((a) => a.kind === kind)
    .reduce((sum, a) => sum + a.count, 0);
}

export function gridFor(routers: number): { cols: number; rows: number } {
  const cols = Math.max(1, Math.ceil(Math.sqrt(Math.max(1, routers))));
  const rows = Math.max(1, Math.ceil(Math.max(1, routers) / cols));
  return { cols, rows };
}

export function strokeFor(linkWidth: number | null): number {
  if (!linkWidth || linkWidth <= 64) return 1.5;
  if (linkWidth <= 128) return 2.5;
  return 4;
}

export interface FabricLayout {
  compute: number;
  hbm: number;
  nic: number;
  edge: number;
  concentration: number;
  routerCount: number;
  cols: number;
  rows: number;
  links: [number, number][];
  topology: string | null;
}

export function deriveFabric(design: DesignView): FabricLayout {
  const compute = agentCount(design, 'compute_tile');
  const hbm = agentCount(design, 'hbm_controller');
  const nic = agentCount(design, 'nic');
  const edge = nic + agentCount(design, 'peripheral');
  const concentration = design.noc_guided.concentration ?? 1;
  const routerCount = Math.max(
    1, Math.ceil(compute / Math.max(1, concentration)));
  const { cols, rows } = gridFor(routerCount);

  const links: [number, number][] = [];
  for (let i = 0; i < routerCount; i++) {
    const c = i % cols;
    const r = Math.floor(i / cols);
    if (c + 1 < cols && i + 1 < routerCount
        && Math.floor((i + 1) / cols) === r) {
      links.push([i, i + 1]);
    }
    if (r + 1 < rows && i + cols < routerCount) links.push([i, i + cols]);
  }

  return {
    compute, hbm, nic, edge, concentration, routerCount, cols, rows, links,
    topology: design.noc_guided.topology_family,
  };
}
