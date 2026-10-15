/** Endpoint protocol compatibility for authoring links (tracker M2-18).
 *
 *  A node's declared protocols come from the ports of its authored agents. Two
 *  nodes may be linked when they share at least one protocol, when either side
 *  declares no protocol (unconstrained), or when an explicit bridge block sits
 *  on one end. Otherwise the link needs a bridge, and this reports why.
 */
import type { LoomProject } from './project';

/** Declared protocols on a node, from every agent port, sorted and unique. */
export function nodeProtocols(project: Pick<LoomProject, 'agents'>, nodeId: string): string[] {
  const protocols = new Set<string>();
  for (const agent of project.agents ?? []) {
    if (agent.nodeId !== nodeId) continue;
    for (const port of agent.ports) if (port.protocol.trim()) protocols.add(port.protocol);
  }
  return [...protocols].sort();
}

/** A node is an explicit bridge when its role or catalog reference says so. */
export function isBridgeNode(project: Pick<LoomProject, 'nodes'>, nodeId: string): boolean {
  const node = project.nodes.find((n) => n.id === nodeId);
  if (!node) return false;
  if (node.role === 'ucie_port') return true;
  if ((node.catalogRef?.itemId ?? '').startsWith('bridge.')) return true;
  return node.catalogRef?.fallbackMetadata?.['class'] === 'bridge';
}

/** Compatibility message for a proposed link, or null when compatible. */
export function protocolCompatibilityProblem(project: Pick<LoomProject, 'nodes' | 'agents'> | (Pick<LoomProject, 'nodes'> & { agents?: LoomProject['agents'] }), src: string, dst: string): string | null {
  const from = nodeProtocols(project, src);
  const to = nodeProtocols(project, dst);
  if (from.length === 0 || to.length === 0) return null;
  if (from.some((protocol) => to.includes(protocol))) return null;
  if (isBridgeNode(project, src) || isBridgeNode(project, dst)) return null;
  return `no shared protocol between ${src} (${from.join(', ')}) and ${dst} (${to.join(', ')}); insert an explicit bridge`;
}
