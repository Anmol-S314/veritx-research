/** Domain authoring operations for the local graph (tracker M3-11/M3-12, M2-20).
 *
 *  Pure, deterministic edits over the typed `domains` contract: the clocks,
 *  resets and powers a project declares, plus the per-port overrides on agent
 *  ports. A missing field on a port assignment means INHERIT — the port takes
 *  whatever the node (or the fabric default) says; a set field is an OVERRIDE.
 *
 *  These functions only shape the authored config. `validateProject` owns the
 *  rules (known references, duplicate ids, unique port assignments); the editor
 *  reports its findings rather than re-implementing them.
 */
import type {
  ClockDomainV1, DomainsConfigV1, GraphNode, LoomProject, PortDomainAssignmentV1,
  PowerDomainV1, ResetDomainV1,
} from './project';

export type DomainKind = 'clocks' | 'resets' | 'powers';
export type DomainEntry = ClockDomainV1 | ResetDomainV1 | PowerDomainV1;
export type NodeDomainField = 'clock' | 'resetDomain' | 'powerDomain';
export type AssignmentField = 'clockDomainId' | 'resetDomainId' | 'powerDomainId';

export const DOMAIN_KINDS: DomainKind[] = ['clocks', 'resets', 'powers'];

export const emptyDomains = (): DomainsConfigV1 =>
  ({ clocks: [], resets: [], powers: [], portAssignments: [] });

export const domainPrefix = (kind: DomainKind): string =>
  kind === 'clocks' ? 'clk' : kind === 'resets' ? 'rst' : 'pd';

export const nodeFieldOf = (kind: DomainKind): NodeDomainField =>
  kind === 'clocks' ? 'clock' : kind === 'resets' ? 'resetDomain' : 'powerDomain';

export const assignmentFieldOf = (kind: DomainKind): AssignmentField =>
  kind === 'clocks' ? 'clockDomainId' : kind === 'resets' ? 'resetDomainId' : 'powerDomainId';

export function listOf(domains: DomainsConfigV1, kind: DomainKind): DomainEntry[] {
  return domains[kind];
}

function withList(domains: DomainsConfigV1, kind: DomainKind, list: DomainEntry[]): DomainsConfigV1 {
  return kind === 'clocks' ? { ...domains, clocks: list as ClockDomainV1[] }
    : kind === 'resets' ? { ...domains, resets: list as ResetDomainV1[] }
      : { ...domains, powers: list as PowerDomainV1[] };
}

/** The next `<prefix>_<n>` id no declared domain already carries. */
export function nextDomainId(kind: DomainKind, used: Iterable<string>): string {
  const taken = new Set(used);
  const prefix = domainPrefix(kind);
  let n = 1;
  while (taken.has(`${prefix}_${n}`)) n += 1;
  return `${prefix}_${n}`;
}

/** Drop keys whose value is `undefined`. The validator's JSON check treats an
 *  `undefined` value as non-JSON, so an absent setting must be an absent key,
 *  never a key set to undefined. */
function pruneUndefined<T extends object>(value: T): T {
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) if (item !== undefined) out[key] = item;
  return out as T;
}

/** Add a domain, or replace the one with the same id. */
export function upsertDomain(domains: DomainsConfigV1, kind: DomainKind, entry: DomainEntry): DomainsConfigV1 {
  const clean = pruneUndefined(entry);
  const list = listOf(domains, kind);
  const index = list.findIndex((domain) => domain.id === clean.id);
  const next = index >= 0 ? list.map((domain, i) => (i === index ? clean : domain)) : [...list, clean];
  return withList(domains, kind, next);
}

/** Remove a domain and every reference to it in the port overrides. A port
 *  assignment left with no overrides at all is dropped (it would be pure
 *  inherit). Node-level references are NOT touched here — the caller clears
 *  those with `nodeReferences` so the document stays valid. */
export function removeDomain(domains: DomainsConfigV1, kind: DomainKind, id: string): DomainsConfigV1 {
  const field = assignmentFieldOf(kind);
  const portAssignments = domains.portAssignments.flatMap((assignment) => {
    if (assignment[field] !== id) return [assignment];
    const next: PortDomainAssignmentV1 = { nodeId: assignment.nodeId, portId: assignment.portId };
    if (assignment.clockDomainId !== undefined && field !== 'clockDomainId') next.clockDomainId = assignment.clockDomainId;
    if (assignment.resetDomainId !== undefined && field !== 'resetDomainId') next.resetDomainId = assignment.resetDomainId;
    if (assignment.powerDomainId !== undefined && field !== 'powerDomainId') next.powerDomainId = assignment.powerDomainId;
    const stillOverrides = next.clockDomainId !== undefined || next.resetDomainId !== undefined || next.powerDomainId !== undefined;
    return stillOverrides ? [next] : [];
  });
  const trimmed = listOf(domains, kind).filter((domain) => domain.id !== id);
  return withList({ ...domains, portAssignments }, kind, trimmed);
}

/** Node ids whose node-level domain field points at `id`. */
export function nodeReferences(doc: Pick<LoomProject, 'nodes'>, kind: DomainKind, id: string): string[] {
  const field = nodeFieldOf(kind);
  return doc.nodes.filter((node) => (node as GraphNode)[field] === id).map((node) => node.id);
}

export function assignmentOf(
  domains: DomainsConfigV1, nodeId: string, portId: string,
): PortDomainAssignmentV1 | null {
  return domains.portAssignments.find((a) => a.nodeId === nodeId && a.portId === portId) ?? null;
}

/** Set or clear one override on a port. Clearing the last override drops the
 *  row, because a row with no override fields is exactly inherit. */
export function upsertPortAssignment(
  domains: DomainsConfigV1, nodeId: string, portId: string, patch: Partial<PortDomainAssignmentV1>,
): DomainsConfigV1 {
  const existing = assignmentOf(domains, nodeId, portId);
  const merged: PortDomainAssignmentV1 = { ...(existing ?? { nodeId, portId }), ...patch, nodeId, portId };
  const next: PortDomainAssignmentV1 = { nodeId, portId };
  if (merged.clockDomainId !== undefined) next.clockDomainId = merged.clockDomainId;
  if (merged.resetDomainId !== undefined) next.resetDomainId = merged.resetDomainId;
  if (merged.powerDomainId !== undefined) next.powerDomainId = merged.powerDomainId;
  const others = domains.portAssignments.filter((a) => !(a.nodeId === nodeId && a.portId === portId));
  const hasOverride = next.clockDomainId !== undefined || next.resetDomainId !== undefined || next.powerDomainId !== undefined;
  return { ...domains, portAssignments: hasOverride ? [...others, next] : others };
}

export function setAssignmentField(
  domains: DomainsConfigV1, nodeId: string, portId: string, field: AssignmentField, value: string | undefined,
): DomainsConfigV1 {
  return upsertPortAssignment(domains, nodeId, portId, { [field]: value } as Partial<PortDomainAssignmentV1>);
}

/** How many nodes and port overrides reference a declared domain. */
export function domainUsage(
  doc: Pick<LoomProject, 'nodes' | 'domains'>, kind: DomainKind, id: string,
): { nodes: number; overrides: number } {
  const field = assignmentFieldOf(kind);
  const domains = doc.domains;
  const overrides = domains
    ? domains.portAssignments.filter((a) => a[field] === id).length
    : 0;
  return { nodes: nodeReferences(doc, kind, id).length, overrides };
}
