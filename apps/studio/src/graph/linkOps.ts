/** Port-to-port link compatibility, checked at pick time (tracker M1-15).
 *
 *  The validator refuses an invalid edge before save/run; this helper lets the
 *  editor refuse the SAME conditions the moment a target is chosen, with a
 *  precise reason, instead of creating an edge that can never validate.
 *  Direction is the DECLARED `interfaceRole`; it is never inferred from `role`.
 */
import { directionPairProblem } from './interfaceRole';
import { protocolCompatibilityProblem } from './protocolCompat';
import type { LoomProject } from './project';

export function linkCompatibilityProblem(project: Pick<LoomProject, 'nodes' | 'edges' | 'agents'>, src: string, dst: string): string | null {
  if (src === dst) return 'a link needs two distinct endpoints';
  const from = project.nodes.find((n) => n.id === src);
  const to = project.nodes.find((n) => n.id === dst);
  if (!from) return `unknown source node ${src}`;
  if (!to) return `unknown target node ${dst}`;

  const direction = directionPairProblem(from.interfaceRole, to.interfaceRole);
  if (direction) return direction;

  const protocol = protocolCompatibilityProblem(project, src, dst);
  if (protocol) return protocol;

  if (project.edges.some((e) => e.src === src && e.dst === dst)) {
    return `duplicate directed link ${src} -> ${dst}`;
  }

  const egress = project.edges.filter((e) => e.src === src).length;
  if (egress >= from.ports) return `source ${src} is out of ports (${from.ports} declared)`;
  const ingress = project.edges.filter((e) => e.dst === dst).length;
  if (ingress >= to.ports) return `target ${dst} is out of ports (${to.ports} declared)`;

  return null;
}
