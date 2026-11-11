/**
 * Catalog fabric search -> project draft handoff.
 *
 * The catalog search measures a repository trace. Its latency, throughput,
 * power and area values belong to that trace and are never transferred into a
 * project. Only the fabric intent (family, dimensions, buffer depth) crosses
 * the boundary; the project must compile and evaluate it on its own workload.
 */

export type CatalogFabric = {
  topology: string;
  family?: string | null;
  nodes?: number | null;
  vcBufSize?: number | null;
};

export type DraftTopologyIntent = {
  kind: 'mesh' | 'torus' | 'concentrated_mesh';
  side_length: number;
  concentration: number;
};

const CONCENTRATED_MESH_CONCENTRATION = 4;

/**
 * Map a catalog topology to the draft fields the fabric editor can author.
 * Returns null for learned/irregular families (Fly, SROTA, QTree, Tree4,
 * Ring) that the project editor cannot express as a regular topology.
 */
export function draftTopologyFor(fabric: CatalogFabric): DraftTopologyIntent | null {
  const family = (fabric.family ?? '').trim().toUpperCase();
  const nodes = Number(fabric.nodes);
  if (!Number.isFinite(nodes) || nodes <= 0) return null;

  if (family === 'MESH' || family === 'TORUS') {
    const side = Math.round(Math.sqrt(nodes));
    if (side * side !== nodes) return null;
    return { kind: family === 'MESH' ? 'mesh' : 'torus', side_length: side, concentration: 1 };
  }

  if (family === 'CONCENTRATED_MESH') {
    const side = Math.round(Math.sqrt(nodes / CONCENTRATED_MESH_CONCENTRATION));
    if (side * side * CONCENTRATED_MESH_CONCENTRATION !== nodes) return null;
    return { kind: 'concentrated_mesh', side_length: side, concentration: CONCENTRATED_MESH_CONCENTRATION };
  }

  return null;
}

/** A measured buffer depth is the only numeric search setting the draft carries. */
export function draftDepthFor(fabric: CatalogFabric): number | null {
  const depth = Number(fabric.vcBufSize);
  return Number.isInteger(depth) && depth > 0 ? depth : null;
}

/** Human-readable reason the selected catalog row cannot be written to a draft. */
export function handoffReason(fabric: CatalogFabric): string {
  if (!draftTopologyFor(fabric)) {
    const family = (fabric.family ?? '').trim().toUpperCase();
    if (family === 'SROTA') return 'SROTA is authorable in the Fabric tab, but this catalog variant carries plane, MECS and routing settings that the one-click apply does not copy. Set them explicitly.';
    if (family.startsWith('GEC')) return 'GEC is authorable in the Fabric tab with an explicit mode, but this catalog variant does not carry that mode into the one-click apply. Set it explicitly.';
    if (family === 'FAT_TREE') return 'Fat-tree is authorable in the Fabric tab with an explicit switch radix and level count; this catalog variant does not carry them into the one-click apply.';
    if (family === 'FLATFLY') return 'Flatfly is authorable in the Fabric tab with explicit radix and dimension fields; this catalog variant does not carry them into the one-click apply.';
    return 'This family is measured in the repository catalog but is not authorable in the project fabric editor. It stays a reference.';
  }
  if (!draftDepthFor(fabric)) return 'The selected row has no measured buffer depth to carry.';
  return '';
}
