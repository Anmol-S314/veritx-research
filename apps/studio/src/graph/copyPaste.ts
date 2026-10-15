import type { GraphEdge, GraphNode } from './project';

export interface GraphFragment { nodes: GraphNode[]; edges: GraphEdge[] }
export interface GraphIdentityContext { nodeIds: Iterable<string>; edgeIds: Iterable<string> }
export interface PastedGraphFragment extends GraphFragment {
  idMap: { nodes: Record<string, string>; edges: Record<string, string> };
}

function allocateCopyId(sourceId: string, occupied: Set<string>): string {
  const root = `${sourceId}-copy`;
  let candidate = root;
  let ordinal = 2;
  while (occupied.has(candidate)) candidate = `${root}-${ordinal++}`;
  occupied.add(candidate);
  return candidate;
}

/** Clone a graph fragment for insertion into an existing project.
 * IDs are derived from stable source IDs plus a deterministic collision suffix;
 * coordinates never participate in identity. The caller supplies current IDs
 * and must apply the returned fragment as one graph-history paste command. */
export function cloneGraphFragment(fragment: GraphFragment, context: GraphIdentityContext): PastedGraphFragment {
  const originalNodeIds = new Set(context.nodeIds);
  const occupiedNodes = new Set(originalNodeIds);
  const occupiedEdges = new Set(context.edgeIds);
  const sourceNodes = new Set<string>();
  for (const node of fragment.nodes) {
    if (!node.id.trim()) throw new Error('cannot copy a node with an empty ID');
    if (sourceNodes.has(node.id)) throw new Error(`cannot copy duplicate node ID ${node.id}`);
    sourceNodes.add(node.id);
  }
  const sourceEdges = new Set<string>();
  for (const edge of fragment.edges) {
    if (!edge.id.trim()) throw new Error('cannot copy an edge with an empty ID');
    if (sourceEdges.has(edge.id)) throw new Error(`cannot copy duplicate edge ID ${edge.id}`);
    sourceEdges.add(edge.id);
  }
  const nodeMap = new Map<string, string>();
  for (const node of fragment.nodes) nodeMap.set(node.id, allocateCopyId(node.id, occupiedNodes));
  const edgeMap = new Map<string, string>();
  for (const edge of fragment.edges) edgeMap.set(edge.id, allocateCopyId(edge.id, occupiedEdges));
  const nodes = fragment.nodes.map((node) => ({ ...node, id: nodeMap.get(node.id)! }));
  const edges = fragment.edges.map((edge) => {
    const src = sourceNodes.has(edge.src) ? nodeMap.get(edge.src)! : edge.src;
    const dst = sourceNodes.has(edge.dst) ? nodeMap.get(edge.dst)! : edge.dst;
    if (!sourceNodes.has(edge.src) && !originalNodeIds.has(edge.src)) throw new Error(`copied edge ${edge.id} has unknown source node ${edge.src}`);
    if (!sourceNodes.has(edge.dst) && !originalNodeIds.has(edge.dst)) throw new Error(`copied edge ${edge.id} has unknown target node ${edge.dst}`);
    return { ...edge, id: edgeMap.get(edge.id)!, src, dst };
  });
  return {
    nodes,
    edges,
    idMap: { nodes: Object.fromEntries(nodeMap), edges: Object.fromEntries(edgeMap) },
  };
}
