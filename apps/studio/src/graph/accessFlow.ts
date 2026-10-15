/** Access-flow resolution over the local authoring graph (tracker M3-27).
 *
 *  Answers one question for an authored node pair: does the access policy
 *  permit it, and if so does a route exist under the authored routing policy?
 *  It joins three authored facts — the firewall block, the routing policy, and
 *  the graph — and states a verdict. It is NOT a certified route and NOT an
 *  execution result; the certified path is queried server-side elsewhere.
 */
import { previewConnectivityPath, previewCustomPath, previewOddEvenPath, previewWestFirstPath, previewXYPath, type ConnectivityHop } from './routing';
import type { LoomProject } from './project';

export type AccessVerdict = 'PERMITTED' | 'READ_ONLY' | 'DENIED' | 'NO_ROUTE' | 'NO_POLICY' | 'SELF';

export interface AccessFlow {
  src: string;
  dst: string;
  /** The authored firewall cell, or null when no rule names the pair (the
   *  firewall default is deny). */
  perm: 'RO' | 'RW' | null;
  nodePath: string[] | null;
  hops: ConnectivityHop[];
  /** Why no preview route was produced, when that is the case. */
  error: string | null;
  verdict: AccessVerdict;
}

function authoredPerm(project: LoomProject, src: string, dst: string): 'RO' | 'RW' | null {
  const rules = project.firewall?.rules;
  if (!Array.isArray(rules)) return null;
  const found = rules.find((raw) => raw !== null && typeof raw === 'object' && !Array.isArray(raw)
    && (raw as Record<string, unknown>).src === src && (raw as Record<string, unknown>).dst === dst);
  if (!found) return null;
  const perm = (found as Record<string, unknown>).perm;
  return perm === 'RO' || perm === 'RW' ? perm : null;
}

function previewRoute(project: LoomProject, src: string, dst: string):
{ nodePath: string[] | null; hops: ConnectivityHop[]; error: string | null } {
  const result = project.routing?.policy === 'xy' ? previewXYPath(project, src, dst)
    : project.routing?.policy === 'west_first' ? previewWestFirstPath(project, src, dst)
      : project.routing?.policy === 'odd_even' ? previewOddEvenPath(project, src, dst)
        : project.routing?.policy === 'custom' ? previewCustomPath(project, src, dst)
          : null;
  if (!result) return { nodePath: null, hops: [], error: 'No routing policy is selected for this pair.' };
  return result.route
    ? { nodePath: result.route.nodePath, hops: result.route.hops, error: null }
    : { nodePath: null, hops: [], error: result.error };
}

export function accessFlow(project: LoomProject, src: string, dst: string): AccessFlow {
  if (src === dst) {
    return { src, dst, perm: null, nodePath: [src], hops: [], error: null, verdict: 'SELF' };
  }
  const perm = authoredPerm(project, src, dst);
  if (perm === null) {
    return { src, dst, perm: null, nodePath: null, hops: [], error: null, verdict: 'DENIED' };
  }
  const route = previewRoute(project, src, dst);
  if (!route.nodePath) {
    return {
      src, dst, perm, nodePath: null, hops: [], error: route.error,
      verdict: project.routing ? 'NO_ROUTE' : 'NO_POLICY',
    };
  }
  return {
    src, dst, perm, nodePath: route.nodePath, hops: route.hops, error: null,
    verdict: perm === 'RO' ? 'READ_ONLY' : 'PERMITTED',
  };
}

/** The authored connectivity path (ignores firewall), for the "is there a path
 *  at all" question when no routing policy is selected. */
export function connectivityOnly(project: LoomProject, src: string, dst: string): string[] | null {
  const preview = previewConnectivityPath(
    project.nodes.map((node) => node.id), project.edges, src, dst,
  );
  return preview ? preview.nodePath : null;
}
