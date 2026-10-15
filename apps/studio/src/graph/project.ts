/** Versioned editable graph document for Loom. This is authoring data, not a
 * compiled fabric or execution claim. Keep the compiler adapter separate. */
import { graphIdProblem } from './ids';

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface CatalogReference {
  catalogId: string;
  itemId: string;
  version: string;
  overrides: { [key: string]: JsonValue };
  fallbackMetadata: { [key: string]: JsonValue };
}

export interface GraphNode {
  id: string;
  x: number;
  y: number;
  role: string;
  ports: number;
  clock?: string | null;
  resetDomain?: string | null;
  powerDomain?: string | null;
  catalogRef?: CatalogReference;
  vc?: { [key: string]: JsonValue };
  /** Declared interface direction; unset means unconstrained (M1-28). */
  interfaceRole?: InterfaceRole | null;
}

export type AgentRole = 'initiator' | 'target' | 'bidirectional';
export type AgentCapability = 'read' | 'write' | 'atomic' | 'coherent' | 'streaming';
export interface AgentPort {
  id: string;
  role: AgentRole;
  protocol: string;
  dataWidth: number;
  addressWidth?: number | null;
  capabilities: AgentCapability[];
  addressWindows?: { base: string; size: string; permissions: ('read' | 'write')[] }[];
}
export interface ProjectAgent { id: string; nodeId: string; role: AgentRole; protocol: string; capabilities: AgentCapability[]; ports: AgentPort[] }
export interface VirtualChannelV1 { id: string; depth: number; class: string; escape: boolean }
export interface TrafficClassMappingV1 { trafficClass: string; vcId: string; qos?: number }
export interface VcArbitrationV1 {
  policy: 'round_robin' | 'fixed_priority' | 'weighted_round_robin';
  priorityByTrafficClass?: Record<string, number>;
  weightByTrafficClass?: Record<string, number>;
}
export interface VcConfigV1 {
  virtualChannels: VirtualChannelV1[];
  trafficClassMap: TrafficClassMappingV1[];
  arbitration: VcArbitrationV1;
}
export interface ClockDomainV1 { id: string; frequencyHz?: number | null; source?: string | null }
export interface ResetDomainV1 { id: string; polarity?: 'active_high' | 'active_low'; asynchronous?: boolean; clockDomainId?: string }
export interface PowerDomainV1 { id: string; nominalVoltageV?: number | null; canPowerOff?: boolean }
export interface PortDomainAssignmentV1 { nodeId: string; portId: string; clockDomainId?: string; resetDomainId?: string; powerDomainId?: string }
export interface DomainsConfigV1 { clocks: ClockDomainV1[]; resets: ResetDomainV1[]; powers: PowerDomainV1[]; portAssignments: PortDomainAssignmentV1[] }
export type CrossingPolicyNameV1 = 'same_domain' | 'synchronizer' | 'async_fifo' | 'reset_bridge' | 'level_shifter' | 'isolation' | 'explicit_none';
export interface DomainCrossingPolicyV1 { policy: CrossingPolicyNameV1; elementNodeId?: string; notes?: string }
export interface EdgeDomainCrossingV1 { clock?: DomainCrossingPolicyV1; reset?: DomainCrossingPolicyV1; power?: DomainCrossingPolicyV1 }

export type AccessPolicy = 'read_write' | 'read_only' | 'deny';
export interface AccessScope { nodeIds: string[]; agentIds?: string[] }
export interface FirewallRule { id: string; precedence: number; source: AccessScope; target: AccessScope; policy: AccessPolicy }
export interface FirewallConfig { defaultPolicy: AccessPolicy; rules: FirewallRule[] }
export interface Rect { x: number; y: number; width: number; height: number }

/** Rectangles that only touch at an edge are not considered overlapping. */
function rectanglesOverlap(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}
export interface FloorplanPlacement { nodeId: string; bounds: Rect; locked: boolean; hierarchyId?: string | null }
export interface FloorplanKeepout { id: string; bounds: Rect; kind?: string }
export interface FloorplanHierarchy { id: string; parentId?: string | null; nodeIds: string[] }
export interface Floorplan { units: 'nm' | 'um' | 'mm'; dieOutline: Rect; placements: FloorplanPlacement[]; keepouts: FloorplanKeepout[]; hierarchies: FloorplanHierarchy[] }
export interface ProjectMetadata { name?: string; description?: string; tags?: string[] }
export interface PhysicalWaypoint { x: number; y: number }
export interface PhysicalEdge { routeLength?: number; layer?: string | null; routeClass?: string | null; locked?: boolean; waypoints?: PhysicalWaypoint[] }
export interface CustomRoutingRule { src: string; dst: string; nextHop: string }
export type RoutingConfig = { policy: 'xy' | 'west_first' | 'odd_even' } | { policy: 'custom'; rules: CustomRoutingRule[] };
export type PhysicalUnit = 'um' | 'mm';
export interface DieOutline { originX: number; originY: number; width: number; height: number }
export interface PhysicalPlacement { nodeId: string; x: number; y: number; width: number; height: number; locked?: boolean }
export interface PhysicalDelayModel { wireDelayPsPerUnit: number; fixedDelayPs: number }
export interface PhysicalTimingConstraint { edgeId: string; targetDelayPs: number }
export interface PhysicalKeepout { id: string; x: number; y: number; width: number; height: number }
export interface FloorplanIntent { unit: PhysicalUnit; die?: DieOutline; gridStep?: number; placements?: PhysicalPlacement[]; keepouts?: PhysicalKeepout[]; delayModel?: PhysicalDelayModel; timingConstraints?: PhysicalTimingConstraint[] }

export interface GraphEdge {
  id: string;
  src: string;
  dst: string;
  width: number;
  pipelineStages: number;
  vcClass: number;
  srcPort?: number;
  dstPort?: number;
  domainCrossing?: EdgeDomainCrossingV1;
  physical?: PhysicalEdge;
}

export interface LoomProject {
  schemaVersion: 1;
  compilerSemanticsVersion: 1;
  presetHint: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  routing?: RoutingConfig;
  /** Legacy physical-authoring intent coexists with the versioned floorplan contract. */
  floorplan?: FloorplanIntent;
  /** Legacy authoring page representation retained for compatibility. */
  firewall?: { [key: string]: JsonValue };
  /** Versioned normalized access-control contract. */
  access?: FirewallConfig;
  metadata?: ProjectMetadata;
  workload?: { [key: string]: JsonValue };
  vcConfig?: VcConfigV1;
  domains?: DomainsConfigV1;
  agents?: ProjectAgent[];
}

/** Canonical validation result model (tracker M0-16/M1-29): every validator
 *  returns a severity, a stable machine code, a human message, and the object
 *  it refers to. Warnings are authoring-legal; errors block every path. The
 *  single-component policy is a warning while editing and an error when the
 *  graph is compiled/run. */
export type IssueSeverity = 'error' | 'warning';

export interface ProjectIssue {
  path: string;
  message: string;
  severity: IssueSeverity;
  code: string;
  /** Stable reference to the object at fault, e.g. `$.nodes[id=n3]`. */
  objectRef: string;
  /** Component membership, present only for `graph.disconnected`. */
  components?: string[][];
  /** Optional safe, mechanical fix a UI may offer. */
  quickFix?: { label: string; code: string };
}

export interface ValidationOptions {
  /** Escalate a disconnected document from a warning to an error. Compile and
   *  run pass `true`; the authoring editor omits it so a pasted subgraph can
   *  be held before it is wired in. */
  requireConnected?: boolean;
}

export const errorIssues = (issues: ProjectIssue[]): ProjectIssue[] =>
  issues.filter((i) => i.severity === 'error');

export const hasErrors = (issues: ProjectIssue[]): boolean =>
  issues.some((i) => i.severity === 'error');

import { directionPairProblem, isInterfaceRole, type InterfaceRole } from './interfaceRole';

const MAX_NODES = 256;
const MAX_EDGES = 512;
const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const isPlainRecord = (value: unknown): value is Record<string, unknown> =>
  isRecord(value) && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
const isPositiveInt = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const MAX_METADATA_DEPTH = 64;
export const MAX_PROJECT_JSON_CHARS = 8 * 1024 * 1024;
export const MAX_PROJECT_JSON_BYTES = 8 * 1024 * 1024;
export const MAX_PROJECT_JSON_DEPTH = 128;
/** XY is defined for graphs with canonical row-major n1..n16/n64 IDs and exact
 * 4×4/8×8 mesh adjacency. Canvas coordinates and preset labels are ignored. */
function hasCanonicalMeshAdjacency(nodes: unknown, edges: unknown): boolean {
  if (!Array.isArray(nodes) || !Array.isArray(edges)) return false;
  const side = nodes.length === 16 ? 4 : nodes.length === 64 ? 8 : 0;
  if (!side || nodes.length !== side * side) return false;
  const expectedNodes = new Set(Array.from({ length: side * side }, (_, index) => `n${index + 1}`));
  if (nodes.some((node) => !isRecord(node) || typeof node.id !== 'string' || !expectedNodes.has(node.id))) return false;
  if (new Set(nodes.map((node) => (node as Record<string, unknown>).id)).size !== expectedNodes.size) return false;
  const expectedEdges = new Set<string>();
  const idAt = (x: number, y: number): string => `n${y * side + x + 1}`;
  for (let y = 0; y < side; y++) for (let x = 0; x < side; x++) {
    if (x + 1 < side) expectedEdges.add([idAt(x, y), idAt(x + 1, y)].sort().join('|'));
    if (y + 1 < side) expectedEdges.add([idAt(x, y), idAt(x, y + 1)].sort().join('|'));
  }
  if (edges.length !== expectedEdges.size) return false;
  const actual = new Set<string>();
  for (const edge of edges) {
    if (!isRecord(edge) || typeof edge.src !== 'string' || typeof edge.dst !== 'string') return false;
    actual.add([edge.src, edge.dst].sort().join('|'));
  }
  return actual.size === expectedEdges.size && [...expectedEdges].every((edge) => actual.has(edge));
}

export function supportsXYRouting(project: Pick<LoomProject, 'presetHint' | 'nodes' | 'edges'>): boolean {
  return hasCanonicalMeshAdjacency(project.nodes, project.edges);
}

export function validateCustomRoutingRules(nodes: unknown, edges: unknown, rules: unknown): string[] {
  const issues: string[] = [];
  if (!Array.isArray(rules)) return ['routing.rules: must be an array'];
  const nodeIds = new Set(Array.isArray(nodes)
    ? nodes.flatMap((node) => isRecord(node) && typeof node.id === 'string' ? [node.id] : []) : []);
  const adjacencies = new Set(Array.isArray(edges)
    ? edges.flatMap((edge) => isRecord(edge) && typeof edge.src === 'string' && typeof edge.dst === 'string'
      ? [[edge.src, edge.dst].sort().join('|')] : []) : []);
  const nextByDestination = new Map<string, Map<string, string>>();
  const seenPairs = new Set<string>();
  const valid: { index: number; src: string; dst: string; nextHop: string }[] = [];
  rules.forEach((raw, index) => {
    const path = `routing.rules[${index}]`;
    if (!isRecord(raw)) { issues.push(`${path}: must be an object`); return; }
    for (const key of Object.keys(raw)) if (!['src', 'dst', 'nextHop'].includes(key)) issues.push(`${path}.${key}: unknown field`);
    const { src, dst, nextHop } = raw;
    if (typeof src !== 'string' || !src.trim()) issues.push(`${path}.src: required`);
    if (typeof dst !== 'string' || !dst.trim()) issues.push(`${path}.dst: required`);
    if (typeof nextHop !== 'string' || !nextHop.trim()) issues.push(`${path}.nextHop: required`);
    if (typeof src !== 'string' || typeof dst !== 'string' || typeof nextHop !== 'string' || !src || !dst || !nextHop) return;
    if (!nodeIds.has(src)) issues.push(`${path}.src: unknown graph node ${src}`);
    if (!nodeIds.has(dst)) issues.push(`${path}.dst: unknown destination graph node ${dst}`);
    if (!nodeIds.has(nextHop)) issues.push(`${path}.nextHop: unknown graph node ${nextHop}`);
    if (src === dst) issues.push(`${path}: source and destination must differ`);
    if (src !== nextHop && !adjacencies.has([src, nextHop].sort().join('|'))) {
      issues.push(`${path}.nextHop: ${nextHop} is not adjacent to source ${src}`);
    }
    const pair = `${src}\u0000${dst}`;
    const duplicate = seenPairs.has(pair);
    if (duplicate) issues.push(`${path}: duplicate next-hop rule for ${src} → ${dst}`);
    else seenPairs.add(pair);
    if (!nodeIds.has(src) || !nodeIds.has(dst) || !nodeIds.has(nextHop) || src === dst || duplicate) return;
    const targetRules = nextByDestination.get(dst) ?? new Map<string, string>();
    targetRules.set(src, nextHop);
    nextByDestination.set(dst, targetRules);
    valid.push({ index, src, dst, nextHop });
  });
  for (const [destination, nextHops] of nextByDestination) {
    for (const rule of valid.filter((entry) => entry.dst === destination)) {
      const visited = new Set<string>();
      let current = rule.src;
      while (current !== destination) {
        if (visited.has(current)) {
          issues.push(`routing.rules[${rule.index}]: next-hop loop before destination ${destination}`);
          break;
        }
        visited.add(current);
        const next = nextHops.get(current);
        if (!next) break;
        current = next;
      }
    }
  }
  return [...new Set(issues)];
}
const isJsonValue = (value: unknown, depth = 0, ancestors = new WeakSet<object>()): value is JsonValue => {
  if (depth > MAX_METADATA_DEPTH) return false;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'object') return false;
  if (ancestors.has(value)) return false;
  ancestors.add(value);
  const valid = Array.isArray(value)
    ? value.every((child) => isJsonValue(child, depth + 1, ancestors))
    : isPlainRecord(value) && Object.values(value).every((child) => isJsonValue(child, depth + 1, ancestors));
  ancestors.delete(value);
  return valid;
};

/** Derive a stable machine code from a JSON path and message. Every issue built
 *  without an explicit code gets one, so a UI can key on codes, not prose. */
const codeFor = (path: string, message: string): string => {
  const base = path.replace(/^\$\.?/, '').replace(/\[[^\]]*\]/g, '').replace(/\.$/, '') || 'root';
  const slug = message.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
  return `${base}.${slug}`;
};

export interface IssueInit {
  path: string;
  message: string;
  severity?: IssueSeverity;
  /** Stable machine code; derived from path+message when omitted. */
  code?: string;
  /** Stable reference to the object at fault; defaults to `path`. */
  objectRef?: string;
  /** Component membership, for `graph.disconnected`. */
  components?: string[][];
  /** Optional safe, mechanical fix a UI may offer. */
  quickFix?: { label: string; code: string };
}

/** Canonical constructor for a validation result (tracker M0-16). Every
 *  validator builds issues through here so severity, code, message and object
 *  reference are always present, consistently derived, and the optional
 *  quick-fix/components metadata has one shape. */
export const makeIssue = (init: IssueInit): ProjectIssue => {
  const issue: ProjectIssue = {
    path: init.path,
    message: init.message,
    severity: init.severity ?? 'error',
    code: init.code ?? codeFor(init.path, init.message),
    objectRef: init.objectRef ?? init.path,
  };
  if (init.components) issue.components = init.components;
  if (init.quickFix) issue.quickFix = init.quickFix;
  return issue;
};

/** Validate identity, endpoint, degree and connectivity invariants before a
 *  graph document enters editor state or is serialized. */


export function validateProject(value: unknown, options: ValidationOptions = {}): ProjectIssue[] {
  const issues: ProjectIssue[] = [];
  const issue = (path: string, message: string, extra: Partial<ProjectIssue> = {}): void => {
    // Every issue links to the object at fault; `path` is the JSON pointer and
    // `objectRef` is the stable id form when the caller knows one. Project
    // validation findings carry the canonical coarse machine code unless a
    // more specific code is supplied.
    issues.push(makeIssue({ path, message, code: 'LOOM_PROJECT_INVALID', ...extra }));
  };
  const checkKeys = (record: Record<string, unknown>, path: string, allowedKeys: readonly string[]): void => {
    for (const key of Object.keys(record)) if (!allowedKeys.includes(key)) issue(`${path}.${key}`, 'unknown field');
  };
  if (!isRecord(value)) {
    issue('$', 'must be an object');
    return issues;
  }
  const allowed = new Set(['schemaVersion', 'compilerSemanticsVersion', 'presetHint', 'nodes', 'edges', 'routing', 'firewall', 'access', 'floorplan', 'metadata', 'workload', 'vcConfig', 'domains', 'agents']);
  for (const key of Object.keys(value)) if (!allowed.has(key)) issue(`$.${key}`, 'unknown field');
  if (value.schemaVersion !== 1) issue('$.schemaVersion', 'must equal 1; migrate this project before opening it');
  if (value.compilerSemanticsVersion !== 1) issue('$.compilerSemanticsVersion', 'unsupported compiler semantics version; migrate this project before running it');
  if (value.presetHint !== null && typeof value.presetHint !== 'string') issue('$.presetHint', 'must be a string or null');
  if (!Array.isArray(value.nodes)) issue('$.nodes', 'must be an array');
  if (!Array.isArray(value.edges)) issue('$.edges', 'must be an array');
  if (Array.isArray(value.nodes) && value.nodes.length > MAX_NODES) issue('$.nodes', `exceeds ${MAX_NODES}-node budget`);
  if (Array.isArray(value.edges) && value.edges.length > MAX_EDGES) issue('$.edges', `exceeds ${MAX_EDGES}-edge budget`);
  for (const key of ['firewall', 'workload', 'vcConfig', 'domains'] as const) {
    if (value[key] !== undefined && (!isRecord(value[key]) || !isJsonValue(value[key]))) {
      issue(`$.${key}`, 'must be a JSON object');
    }
  }

  const nodes = Array.isArray(value.nodes) ? value.nodes : [];
  const edges = Array.isArray(value.edges) ? value.edges : [];
  if (value.routing !== undefined) {
    const routing = value.routing;
    if (!isRecord(routing)) issue('$.routing', 'must be an object');
    else if (routing.policy === 'custom') {
      checkKeys(routing, '$.routing', ['policy', 'rules']);
      for (const detail of validateCustomRoutingRules(nodes, edges, routing.rules)) issue('$.routing', detail);
    } else if (routing.policy === 'xy' || routing.policy === 'west_first' || routing.policy === 'odd_even') {
      checkKeys(routing, '$.routing', ['policy']);
      if (!supportsXYRouting({ presetHint: typeof value.presetHint === 'string' ? value.presetHint : null, nodes: nodes as GraphNode[], edges: edges as GraphEdge[] })) {
        issue('$.routing.policy', `${routing.policy} is supported only on the canonical 4×4 or 8×8 mesh graph`);
      }
    } else issue('$.routing.policy', 'unsupported routing policy');
  }
  if (value.workload !== undefined && isRecord(value.workload)) {
    const workload = value.workload;
    checkKeys(workload, '$.workload', ['workloadSchemaVersion', 'modelFamily', 'modelName', 'parameterCount', 'hiddenSize', 'layers', 'layerCount', 'paramsB', 'seqLen', 'batch', 'precision', 'phases', 'communications', 'rankMappings', 'rankConstraints', 'trafficClassMappings', 'defaultTrafficClassMapping']);
    for (const field of ['modelFamily', 'modelName', 'precision'] as const) if (workload[field] !== undefined && (typeof workload[field] !== 'string' || !workload[field].trim())) issue(`$.workload.${field}`, 'must be a non-empty string');
    if (workload.parameterCount !== undefined && workload.parameterCount !== null && (!isFiniteNumber(workload.parameterCount) || workload.parameterCount < 0)) issue('$.workload.parameterCount', 'must be null or a non-negative finite number');
    for (const field of ['hiddenSize', 'layers'] as const) if (workload[field] !== undefined && workload[field] !== null && (!isPositiveInt(workload[field]))) issue(`$.workload.${field}`, 'must be null or a positive integer');
    if (workload.paramsB !== undefined && (!isFiniteNumber(workload.paramsB) || workload.paramsB < 0)) issue('$.workload.paramsB', 'must be a non-negative finite number');
    for (const field of ['seqLen', 'batch'] as const) if (workload[field] !== undefined && !isPositiveInt(workload[field])) issue(`$.workload.${field}`, 'must be a positive integer');
    if (workload.phases !== undefined) {
      if (!Array.isArray(workload.phases)) issue('$.workload.phases', 'must be an array');
      else {
        const phaseIds = new Set<string>();
        workload.phases.forEach((phase, pi) => {
          const path = `$.workload.phases[${pi}]`;
          if (!isRecord(phase)) { issue(path, 'must be an object'); return; }
          checkKeys(phase, path, ['id', 'name', 'kind', 'startCycle', 'durationCycles', 'tokens', 'batch', 'tp', 'ep', 'pp', 'dp', 'communicationOps', 'tensorSizes', 'mappingRefs', 'timingHints']);
          if (phase.id !== undefined) {
            if (typeof phase.id !== 'string' || !phase.id.trim()) issue(`${path}.id`, 'must be a non-empty stable ID');
            else if (phaseIds.has(phase.id)) issue(`${path}.id`, `duplicate phase ID ${phase.id}`);
            else phaseIds.add(phase.id);
          }
          if (phase.name !== undefined && (typeof phase.name !== 'string' || !phase.name.trim())) issue(`${path}.name`, 'must be non-empty when set');
          if (phase.kind !== undefined && (typeof phase.kind !== 'string' || !phase.kind.trim())) issue(`${path}.kind`, 'must be a non-empty string');
          if (phase.startCycle !== undefined && (!Number.isSafeInteger(phase.startCycle) || (phase.startCycle as number) < 0)) issue(`${path}.startCycle`, 'must be a non-negative safe integer');
          if (phase.durationCycles !== undefined && (!Number.isSafeInteger(phase.durationCycles) || (phase.durationCycles as number) < 1)) issue(`${path}.durationCycles`, 'must be a positive safe integer');
          for (const field of ['tokens', 'batch', 'tp', 'ep', 'pp', 'dp'] as const) if (phase[field] !== undefined && !isPositiveInt(phase[field])) issue(`${path}.${field}`, 'must be a positive integer');
          const mappingRefSet = Array.isArray(phase.mappingRefs) && phase.mappingRefs.every(ref => typeof ref === 'string' && ref.trim()) ? new Set(phase.mappingRefs as string[]) : null;
          const tensorRefSet = isRecord(phase.tensorSizes) ? new Set(Object.keys(phase.tensorSizes)) : null;
          if (phase.communicationOps !== undefined) {
            if (!Array.isArray(phase.communicationOps)) issue(`${path}.communicationOps`, 'must be an array');
            else phase.communicationOps.forEach((op, oi) => {
              const opPath = `${path}.communicationOps[${oi}]`;
              if (!isRecord(op)) { issue(opPath, 'must be an object'); return; }
              checkKeys(op, opPath, ['kind', 'trafficClass', 'tensorRef', 'mappingRef']);
              for (const field of ['kind', 'trafficClass'] as const) if (typeof op[field] !== 'string' || !op[field].trim()) issue(`${opPath}.${field}`, 'must be a non-empty string');
              for (const field of ['tensorRef', 'mappingRef'] as const) if (op[field] !== undefined && (typeof op[field] !== 'string' || !op[field].trim())) issue(`${opPath}.${field}`, 'must be a non-empty string when provided');
              if (typeof op.mappingRef === 'string' && mappingRefSet && !mappingRefSet.has(op.mappingRef)) issue(`${opPath}.mappingRef`, 'must reference an ID listed in the phase mappingRefs');
              if (typeof op.tensorRef === 'string' && tensorRefSet && !tensorRefSet.has(op.tensorRef)) issue(`${opPath}.tensorRef`, 'must reference a tensor listed in the phase tensorSizes');
            });
          }
          if (phase.tensorSizes !== undefined) {
            if (!isRecord(phase.tensorSizes)) issue(`${path}.tensorSizes`, 'must be an object');
            else for (const [name, size] of Object.entries(phase.tensorSizes)) if (!Number.isSafeInteger(size) || (size as number) < 0) issue(`${path}.tensorSizes.${name}`, 'must be a non-negative integer');
          }
          if (phase.mappingRefs !== undefined) {
            if (!Array.isArray(phase.mappingRefs) || phase.mappingRefs.some(ref => typeof ref !== 'string' || !ref.trim())) issue(`${path}.mappingRefs`, 'must contain non-empty stable references');
            else if (new Set(phase.mappingRefs).size !== phase.mappingRefs.length) issue(`${path}.mappingRefs`, 'references must be unique');
          }
          if (phase.timingHints !== undefined) {
            const hints = phase.timingHints;
            const hintPath = `${path}.timingHints`;
            if (!isRecord(hints)) issue(hintPath, 'must be an object');
            else {
              checkKeys(hints, hintPath, ['startCycle', 'durationCycles', 'source']);
              if (hints.startCycle !== undefined && (!Number.isSafeInteger(hints.startCycle) || (hints.startCycle as number) < 0)) issue(`${hintPath}.startCycle`, 'must be a non-negative safe integer');
              if (hints.durationCycles !== undefined && (!Number.isSafeInteger(hints.durationCycles) || (hints.durationCycles as number) < 1)) issue(`${hintPath}.durationCycles`, 'must be a positive safe integer');
              if (hints.source !== undefined && (typeof hints.source !== 'string' || !hints.source.trim())) issue(`${hintPath}.source`, 'must be a non-empty string');
              if (Number.isSafeInteger(hints.startCycle) && Number.isSafeInteger(hints.durationCycles) && (hints.startCycle as number) + (hints.durationCycles as number) > Number.MAX_SAFE_INTEGER) issue(hintPath, 'cycle range exceeds safe integer limits');
            }
          }
        });
      }
    }
  }
  if (value.vcConfig !== undefined && isRecord(value.vcConfig)) {
    const config = value.vcConfig;
    checkKeys(config, '$.vcConfig', ['virtualChannels', 'trafficClassMap', 'arbitration']);
    const virtualChannels = Array.isArray(config.virtualChannels) ? config.virtualChannels : [];
    const vcIds = new Set<string>();
    if (!Array.isArray(config.virtualChannels)) issue('$.vcConfig.virtualChannels', 'must be an array');
    virtualChannels.forEach((raw, i) => {
      const path = `$.vcConfig.virtualChannels[${i}]`;
      if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
      checkKeys(raw, path, ['id', 'depth', 'class', 'escape']);
      if (typeof raw.id !== 'string' || !raw.id.trim()) issue(`${path}.id`, 'must be a non-empty stable ID');
      else if (vcIds.has(raw.id)) issue(`${path}.id`, `duplicate virtual channel ID ${raw.id}`);
      else vcIds.add(raw.id);
      if (!isPositiveInt(raw.depth)) issue(`${path}.depth`, 'must be a positive integer');
      if (typeof raw.class !== 'string' || !raw.class.trim()) issue(`${path}.class`, 'must be a non-empty string');
      if (typeof raw.escape !== 'boolean') issue(`${path}.escape`, 'must be boolean');
    });
    const trafficClasses = Array.isArray(config.trafficClassMap) ? config.trafficClassMap : [];
    const trafficClassNames = new Set<string>();
    if (!Array.isArray(config.trafficClassMap)) issue('$.vcConfig.trafficClassMap', 'must be an array');
    trafficClasses.forEach((raw, i) => {
      const path = `$.vcConfig.trafficClassMap[${i}]`;
      if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
      checkKeys(raw, path, ['trafficClass', 'vcId', 'qos']);
      if (typeof raw.trafficClass !== 'string' || !raw.trafficClass.trim()) issue(`${path}.trafficClass`, 'must be a non-empty string');
      else if (trafficClassNames.has(raw.trafficClass)) issue(`${path}.trafficClass`, `duplicate traffic class ${raw.trafficClass}`);
      else trafficClassNames.add(raw.trafficClass);
      if (typeof raw.vcId !== 'string' || !vcIds.has(raw.vcId)) issue(`${path}.vcId`, `unknown virtual channel ${String(raw.vcId ?? '')}`);
      if (raw.qos !== undefined && (!Number.isSafeInteger(raw.qos) || (raw.qos as number) < 0)) issue(`${path}.qos`, 'must be a non-negative integer');
    });
    if (!isRecord(config.arbitration)) issue('$.vcConfig.arbitration', 'must be an object');
    else {
      const arbitration = config.arbitration;
      checkKeys(arbitration, '$.vcConfig.arbitration', ['policy', 'priorityByTrafficClass', 'weightByTrafficClass']);
      if (!['round_robin', 'fixed_priority', 'weighted_round_robin'].includes(String(arbitration.policy))) issue('$.vcConfig.arbitration.policy', 'unsupported arbitration policy');
      for (const field of ['priorityByTrafficClass', 'weightByTrafficClass'] as const) {
        const values = arbitration[field];
        if (values === undefined) continue;
        if (!isRecord(values)) { issue(`$.vcConfig.arbitration.${field}`, 'must be an object'); continue; }
        for (const [trafficClass, value] of Object.entries(values)) {
          const path = `$.vcConfig.arbitration.${field}.${trafficClass}`;
          if (!trafficClassNames.has(trafficClass)) issue(path, 'must reference a declared traffic class');
          if (field === 'priorityByTrafficClass' ? (!Number.isSafeInteger(value) || (value as number) < 0) : (!Number.isSafeInteger(value) || (value as number) < 1)) issue(path, field === 'priorityByTrafficClass' ? 'must be a non-negative integer' : 'must be a positive integer');
        }
      }
    }
  }
  if (value.agents !== undefined) {
    if (!Array.isArray(value.agents)) issue('$.agents', 'must be an array');
    else {
      const agentIds = new Set<string>();
      const validRoles = ['initiator', 'target', 'bidirectional'];
      const validCapabilities = ['read', 'write', 'atomic', 'coherent', 'streaming'];
      value.agents.forEach((agent, ai) => {
        const path = `$.agents[${ai}]`;
        if (!isRecord(agent)) { issue(path, 'must be an object'); return; }
        checkKeys(agent, path, ['id', 'nodeId', 'role', 'protocol', 'capabilities', 'ports']);
        if (typeof agent.id !== 'string' || !agent.id.trim()) issue(`${path}.id`, 'must be a non-empty stable ID');
        else if (agentIds.has(agent.id)) issue(`${path}.id`, `duplicate agent id ${agent.id}`);
        else agentIds.add(agent.id);
        if (typeof agent.nodeId !== 'string' || !nodes.some(n => isRecord(n) && n.id === agent.nodeId)) issue(`${path}.nodeId`, `unknown node ${String(agent.nodeId ?? '')}`);
        if (!validRoles.includes(String(agent.role))) issue(`${path}.role`, 'must be initiator, target, or bidirectional');
        if (typeof agent.protocol !== 'string' || !agent.protocol.trim()) issue(`${path}.protocol`, 'must be a non-empty string');
        if (!Array.isArray(agent.capabilities) || agent.capabilities.some(c => !validCapabilities.includes(String(c)))) issue(`${path}.capabilities`, 'contains unsupported capability');
        else if (new Set(agent.capabilities).size !== agent.capabilities.length) issue(`${path}.capabilities`, 'capabilities must be unique');
        if (!Array.isArray(agent.ports)) { issue(`${path}.ports`, 'must be an array'); return; }
        const portIds = new Set<string>();
        agent.ports.forEach((port, pi) => {
          const pp = `${path}.ports[${pi}]`;
          if (!isRecord(port)) { issue(pp, 'must be an object'); return; }
          checkKeys(port, pp, ['id', 'role', 'protocol', 'dataWidth', 'addressWidth', 'capabilities', 'addressWindows']);
          if (typeof port.id !== 'string' || !port.id.trim()) issue(`${pp}.id`, 'must be a non-empty stable port ID');
          else if (portIds.has(port.id)) issue(`${pp}.id`, `duplicate port id ${port.id}`);
          else portIds.add(port.id);
          if (!validRoles.includes(String(port.role))) issue(`${pp}.role`, 'must be initiator, target, or bidirectional');
          if (typeof port.protocol !== 'string' || !port.protocol.trim()) issue(`${pp}.protocol`, 'must be a non-empty string');
          if (!isPositiveInt(port.dataWidth)) issue(`${pp}.dataWidth`, 'must be a positive integer');
          if (port.addressWidth !== undefined && port.addressWidth !== null && (!isPositiveInt(port.addressWidth) || port.addressWidth > 64)) issue(`${pp}.addressWidth`, 'must be null or an integer from 1 through 64');
          if (!Array.isArray(port.capabilities) || port.capabilities.some(c => !validCapabilities.includes(String(c)))) issue(`${pp}.capabilities`, 'contains unsupported capability');
          else if (new Set(port.capabilities).size !== port.capabilities.length) issue(`${pp}.capabilities`, 'capabilities must be unique');
          if (port.addressWindows !== undefined) {
            if (!Array.isArray(port.addressWindows)) issue(`${pp}.addressWindows`, 'must be an array');
            else port.addressWindows.forEach((window, wi) => {
              const wp = `${pp}.addressWindows[${wi}]`;
              if (!isRecord(window)) { issue(wp, 'must be an object'); return; }
              checkKeys(window, wp, ['base', 'size', 'permissions']);
              const hex = /^0x[0-9a-fA-F]+$/;
              const base = typeof window.base === 'string' ? window.base : null;
              const size = typeof window.size === 'string' ? window.size : null;
              if (base === null || !hex.test(base)) issue(`${wp}.base`, 'must be a hexadecimal string');
              else if (base.length > 18) issue(`${wp}.base`, 'must fit the maximum 64-bit address width');
              if (size === null || !hex.test(size)) issue(`${wp}.size`, 'must be a hexadecimal string');
              else if (size.length > 19) issue(`${wp}.size`, 'must fit within the maximum 64-bit address space');
              else if (BigInt(size) <= 0n) issue(`${wp}.size`, 'must be greater than zero');
              if (base !== null && hex.test(base) && base.length <= 18 && size !== null && hex.test(size) && size.length <= 19 && BigInt(size) > 0n) {
                const addressWidth = isPositiveInt(port.addressWidth) ? port.addressWidth : 64;
                const limit = 1n << BigInt(addressWidth);
                if (BigInt(base) >= limit) issue(`${wp}.base`, 'must fit the declared address width');
                else if (BigInt(base) + BigInt(size) > limit) issue(`${wp}.size`, 'address window exceeds the declared address width');
              }
              if (!Array.isArray(window.permissions) || window.permissions.some(p => p !== 'read' && p !== 'write')) issue(`${wp}.permissions`, 'must contain read/write permissions');
              else if (new Set(window.permissions).size !== window.permissions.length) issue(`${wp}.permissions`, 'permissions must be unique');
            });
          }
        });
      });
      // Target address windows are globally compared after shape/range checks.
      // Overlap is reported at both participating windows with exact stable IDs.
      const targetWindows: { path: string; agent: string; port: string; base: bigint; end: bigint; text: string }[] = [];
      for (const [ai, agent] of value.agents.entries()) {
        if (!isRecord(agent) || !Array.isArray(agent.ports)) continue;
        for (const [pi, port] of agent.ports.entries()) {
          if (!isRecord(port) || !['target', 'bidirectional'].includes(String(port.role)) || !Array.isArray(port.addressWindows)) continue;
          for (const [wi, window] of port.addressWindows.entries()) {
            if (!isRecord(window) || typeof window.base !== 'string' || typeof window.size !== 'string'
              || !/^0x[0-9a-fA-F]+$/.test(window.base) || !/^0x[0-9a-fA-F]+$/.test(window.size)
              || window.base.length > 18 || window.size.length > 19) continue;
            const base = BigInt(window.base), size = BigInt(window.size);
            if (size <= 0n) continue;
            const agentId = typeof agent.id === 'string' ? agent.id : `agents[${ai}]`;
            const portId = typeof port.id === 'string' ? port.id : `ports[${pi}]`;
            targetWindows.push({ path: `$.agents[${ai}].ports[${pi}].addressWindows[${wi}]`, agent: agentId, port: portId, base, end: base + size, text: `${window.base}..0x${(base + size - 1n).toString(16)}` });
          }
        }
      }
      for (let i = 0; i < targetWindows.length; i++) for (let j = i + 1; j < targetWindows.length; j++) {
        const a = targetWindows[i]!, b = targetWindows[j]!;
        if (a.base < b.end && b.base < a.end) {
          issue(`${a.path}.base`, `target address window ${a.agent}/${a.port} ${a.text} overlaps ${b.agent}/${b.port} ${b.text}`);
          issue(`${b.path}.base`, `target address window ${b.agent}/${b.port} ${b.text} overlaps ${a.agent}/${a.port} ${a.text}`);
        }
      }
    }
  }
  const nodeIds = new Set<string>();
  const nodeById = new Map<string, Record<string, unknown>>();
  const degree = new Map<string, number>();
  const interfaceRoleByNode = new Map<string, InterfaceRole>();
  nodes.forEach((raw, i) => {
    const path = `$.nodes[${i}]`;
    if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(raw)) {
      if (!['id', 'x', 'y', 'role', 'ports', 'clock', 'resetDomain', 'powerDomain', 'catalogRef', 'vc', 'interfaceRole'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    }
    const nodeIdProblem = graphIdProblem(raw.id);
    if (nodeIdProblem) issue(`${path}.id`, nodeIdProblem, { code: 'node.id_format', objectRef: `${path}.id` });
    else if (nodeIds.has(raw.id as string)) issue(`${path}.id`, `duplicate node id ${raw.id}`);
    else { nodeIds.add(raw.id as string); nodeById.set(raw.id as string, raw); degree.set(raw.id as string, 0); }
    if (!isFiniteNumber(raw.x)) issue(`${path}.x`, 'must be finite');
    if (!isFiniteNumber(raw.y)) issue(`${path}.y`, 'must be finite');
    if (typeof raw.role !== 'string' || raw.role.trim() === '') issue(`${path}.role`, 'must be a non-empty string');
    if (!isPositiveInt(raw.ports)) issue(`${path}.ports`, 'must be a positive integer');
    for (const key of ['clock', 'resetDomain', 'powerDomain'] as const) {
      if (raw[key] !== undefined && raw[key] !== null && (typeof raw[key] !== 'string' || raw[key] === '')) issue(`${path}.${key}`, 'must be a non-empty string or null');
    }
    if (raw.catalogRef !== undefined) {
      if (!isRecord(raw.catalogRef)) issue(`${path}.catalogRef`, 'must be an object');
      else {
        checkKeys(raw.catalogRef, `${path}.catalogRef`, ['catalogId', 'itemId', 'version', 'overrides', 'fallbackMetadata']);
        for (const key of ['catalogId', 'itemId', 'version']) if (typeof raw.catalogRef[key] !== 'string' || !String(raw.catalogRef[key]).trim()) issue(`${path}.catalogRef.${key}`, 'must be a non-empty string');
        for (const key of ['overrides', 'fallbackMetadata']) if (!isRecord(raw.catalogRef[key]) || !isJsonValue(raw.catalogRef[key])) issue(`${path}.catalogRef.${key}`, 'must be a JSON object');
      }
    }
    if (raw.vc !== undefined && (!isRecord(raw.vc) || !isJsonValue(raw.vc))) issue(`${path}.vc`, 'must be a JSON object');
    if (raw.interfaceRole !== undefined && raw.interfaceRole !== null && !isInterfaceRole(raw.interfaceRole)) {
      issue(`${path}.interfaceRole`, `must be one of INITIATOR, TARGET, BIDIRECTIONAL, STREAM_SOURCE, STREAM_SINK or null`, {
        code: 'node.interface_role', objectRef: `$.nodes[id=${typeof raw.id === 'string' ? raw.id : i}]`,
      });
    } else if (isInterfaceRole(raw.interfaceRole)) {
      interfaceRoleByNode.set(raw.id as string, raw.interfaceRole);
    }
    if (isRecord(raw.vc) && raw.vc.depth !== undefined && !isPositiveInt(raw.vc.depth)) issue(`${path}.vc.depth`, 'must be a positive integer when set');
  });

  const agentIds = new Set<string>();
  if (Array.isArray(value.agents)) for (const agent of value.agents) if (isRecord(agent) && typeof agent.id === 'string') agentIds.add(agent.id);
  const policies = new Set(['read_write', 'read_only', 'deny']);
  if (value.access !== undefined) {
    const firewall = value.access;
    if (!isRecord(firewall)) issue('$.access', 'must be an object');
    else {
      checkKeys(firewall, '$.access', ['defaultPolicy', 'rules']);
      if (typeof firewall.defaultPolicy !== 'string' || !policies.has(firewall.defaultPolicy)) issue('$.access.defaultPolicy', 'must be read_write, read_only, or deny');
      if (!Array.isArray(firewall.rules)) issue('$.access.rules', 'must be an array');
      else {
        const ruleIds = new Set<string>();
        const precedences = new Set<number>();
        firewall.rules.forEach((rawRule, ri) => {
          const rp = `$.access.rules[${ri}]`;
          if (!isRecord(rawRule)) { issue(rp, 'must be an object'); return; }
          checkKeys(rawRule, rp, ['id', 'precedence', 'source', 'target', 'policy']);
          if (typeof rawRule.id !== 'string' || !rawRule.id.trim()) issue(`${rp}.id`, 'must be a non-empty stable ID');
          else if (ruleIds.has(rawRule.id)) issue(`${rp}.id`, `duplicate rule id ${rawRule.id}`);
          else ruleIds.add(rawRule.id);
          if (!Number.isSafeInteger(rawRule.precedence) || (rawRule.precedence as number) < 0) issue(`${rp}.precedence`, 'must be a non-negative integer');
          else if (precedences.has(rawRule.precedence as number)) issue(`${rp}.precedence`, 'must be unique; lower numbers take precedence');
          else precedences.add(rawRule.precedence as number);
          if (typeof rawRule.policy !== 'string' || !policies.has(rawRule.policy)) issue(`${rp}.policy`, 'must be read_write, read_only, or deny');
          for (const scopeKey of ['source', 'target'] as const) {
            const scope = rawRule[scopeKey];
            const sp = `${rp}.${scopeKey}`;
            if (!isRecord(scope)) { issue(sp, 'must be an object'); continue; }
            checkKeys(scope, sp, ['nodeIds', 'agentIds']);
            if (!Array.isArray(scope.nodeIds) || scope.nodeIds.length === 0 || scope.nodeIds.some(id => typeof id !== 'string' || !nodeIds.has(id))) issue(`${sp}.nodeIds`, 'must be a non-empty list of known node IDs');
            else if (new Set(scope.nodeIds).size !== scope.nodeIds.length) issue(`${sp}.nodeIds`, 'node IDs must be unique');
            if (scope.agentIds !== undefined) {
              if (!Array.isArray(scope.agentIds) || scope.agentIds.some(id => typeof id !== 'string' || !agentIds.has(id))) issue(`${sp}.agentIds`, 'must contain known agent IDs');
              else if (new Set(scope.agentIds).size !== scope.agentIds.length) issue(`${sp}.agentIds`, 'agent IDs must be unique');
            }
          }
        });
      }
    }
  }
  if (value.metadata !== undefined) {
    if (!isRecord(value.metadata)) issue('$.metadata', 'must be an object');
    else {
      checkKeys(value.metadata, '$.metadata', ['name', 'description', 'tags']);
      if (value.metadata.name !== undefined && (typeof value.metadata.name !== 'string' || !value.metadata.name.trim() || value.metadata.name.length > 200)) issue('$.metadata.name', 'must be a non-empty string of at most 200 characters');
      if (value.metadata.description !== undefined && typeof value.metadata.description !== 'string') issue('$.metadata.description', 'must be a string');
      if (value.metadata.tags !== undefined && (!Array.isArray(value.metadata.tags) || value.metadata.tags.some(tag => typeof tag !== 'string' || !tag.trim()) || new Set(value.metadata.tags).size !== value.metadata.tags.length)) issue('$.metadata.tags', 'must contain unique non-empty strings');
    }
  }
  const rectangleValid = (rect: unknown): rect is Record<string, unknown> => isRecord(rect) && isFiniteNumber(rect.x) && isFiniteNumber(rect.y) && isFiniteNumber(rect.width) && rect.width > 0 && isFiniteNumber(rect.height) && rect.height > 0;
  if (value.floorplan !== undefined) {
    const fp = value.floorplan;
    if (!isRecord(fp)) issue('$.floorplan', 'must be an object');
    else if ('unit' in fp) {
      checkKeys(fp, '$.floorplan', ['unit', 'die', 'gridStep', 'placements', 'keepouts', 'delayModel', 'timingConstraints']);
      if (fp.unit !== 'um' && fp.unit !== 'mm') issue('$.floorplan.unit', 'must be um or mm');
      if (fp.die !== undefined) {
        if (!isRecord(fp.die)) issue('$.floorplan.die', 'must be an object');
        else {
          checkKeys(fp.die, '$.floorplan.die', ['originX', 'originY', 'width', 'height']);
          for (const field of ['originX', 'originY'] as const) if (!isFiniteNumber(fp.die[field])) issue(`$.floorplan.die.${field}`, 'must be finite');
          for (const field of ['width', 'height'] as const) if (!isFiniteNumber(fp.die[field]) || fp.die[field] <= 0) issue(`$.floorplan.die.${field}`, 'must be positive');
        }
      }
      if (fp.gridStep !== undefined && (!isFiniteNumber(fp.gridStep) || fp.gridStep <= 0)) issue('$.floorplan.gridStep', 'must be positive');
      if (fp.delayModel !== undefined) {
        if (!isRecord(fp.delayModel)) issue('$.floorplan.delayModel', 'must be an object');
        else for (const field of ['wireDelayPsPerUnit', 'fixedDelayPs'] as const) if (!isFiniteNumber(fp.delayModel[field]) || fp.delayModel[field] < 0) issue(`$.floorplan.delayModel.${field}`, 'must be a finite non-negative number');
      }
      if (fp.placements !== undefined && !Array.isArray(fp.placements)) issue('$.floorplan.placements', 'must be an array');
      if (fp.keepouts !== undefined && !Array.isArray(fp.keepouts)) issue('$.floorplan.keepouts', 'must be an array');
      const physicalKeepouts: Array<{ id: string; bounds: Rect; index: number }> = [];
      const keepoutIds = new Set<string>();
      if (Array.isArray(fp.keepouts) && fp.keepouts.length > 0 && fp.die === undefined) issue('$.floorplan.die', 'physical keepouts require an authored die outline');
      if (Array.isArray(fp.keepouts)) fp.keepouts.forEach((raw, index) => {
        const path = `$.floorplan.keepouts[${index}]`;
        if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
        checkKeys(raw, path, ['id', 'x', 'y', 'width', 'height']);
        if (typeof raw.id !== 'string' || !raw.id.trim()) issue(`${path}.id`, 'must be a non-empty stable ID');
        else if (keepoutIds.has(raw.id)) issue(`${path}.id`, `duplicate keepout ID ${raw.id}`);
        else keepoutIds.add(raw.id);
        for (const field of ['x', 'y'] as const) if (!isFiniteNumber(raw[field])) issue(`${path}.${field}`, 'must be finite');
        for (const field of ['width', 'height'] as const) if (!isFiniteNumber(raw[field]) || raw[field] <= 0) issue(`${path}.${field}`, 'must be positive');
        if (['x', 'y', 'width', 'height'].every((field) => isFiniteNumber(raw[field])) && (raw.width as number) > 0 && (raw.height as number) > 0) {
          const bounds = { x: raw.x as number, y: raw.y as number, width: raw.width as number, height: raw.height as number };
          if (isRecord(fp.die) && isFiniteNumber(fp.die.originX) && isFiniteNumber(fp.die.originY) && isFiniteNumber(fp.die.width) && isFiniteNumber(fp.die.height)
            && (bounds.x < fp.die.originX || bounds.y < fp.die.originY || bounds.x + bounds.width > fp.die.originX + fp.die.width || bounds.y + bounds.height > fp.die.originY + fp.die.height)) issue(path, 'keepout must lie within the authored die outline');
          if (typeof raw.id === 'string') physicalKeepouts.push({ id: raw.id, bounds, index });
        }
      });
      const placementIds = new Set<string>();
      const validLegacyPlacements: Array<{ nodeId: string; x: number; y: number; width: number; height: number; index: number }> = [];
      if (Array.isArray(fp.placements)) fp.placements.forEach((placement, index) => {
        const path = `$.floorplan.placements[${index}]`;
        if (!isRecord(placement)) { issue(path, 'must be an object'); return; }
        checkKeys(placement, path, ['nodeId', 'x', 'y', 'width', 'height', 'locked']);
        if (typeof placement.nodeId !== 'string' || !nodeIds.has(placement.nodeId)) issue(`${path}.nodeId`, `unknown graph node ${String(placement.nodeId ?? '')}`);
        else if (placementIds.has(placement.nodeId)) issue(`${path}.nodeId`, `duplicate physical placement for node ${placement.nodeId}`);
        else placementIds.add(placement.nodeId);
        if (fp.die === undefined && Array.isArray(fp.placements) && fp.placements.length) issue('$.floorplan.die', 'physical placements require an authored die outline');
        for (const field of ['x', 'y'] as const) if (!isFiniteNumber(placement[field])) issue(`${path}.${field}`, 'must be finite');
        for (const field of ['width', 'height'] as const) if (!isFiniteNumber(placement[field]) || placement[field] <= 0) issue(`${path}.${field}`, 'must be positive');
        if (['x', 'y', 'width', 'height'].every((field) => isFiniteNumber(placement[field])) && (placement.width as number) > 0 && (placement.height as number) > 0) {
          const rect = { nodeId: String(placement.nodeId), x: placement.x as number, y: placement.y as number, width: placement.width as number, height: placement.height as number, index };
          validLegacyPlacements.forEach((other) => {
            if (rect.x < other.x + other.width && rect.x + rect.width > other.x && rect.y < other.y + other.height && rect.y + rect.height > other.y)
              issue(path, `overlaps physical placement for node ${other.nodeId} at $.floorplan.placements[${other.index}]`);
          });
          if (isRecord(fp.die) && isFiniteNumber(fp.die.originX) && isFiniteNumber(fp.die.originY) && isFiniteNumber(fp.die.width) && isFiniteNumber(fp.die.height)
            && (rect.x < fp.die.originX || rect.y < fp.die.originY || rect.x + rect.width > fp.die.originX + fp.die.width || rect.y + rect.height > fp.die.originY + fp.die.height))
            issue(`${path}.x`, 'placement must lie within the authored die outline');
          physicalKeepouts.forEach((keepout) => {
            if (rectanglesOverlap(rect, keepout.bounds)) issue(path, `intersects keepout ${keepout.id} at $.floorplan.keepouts[${keepout.index}]`);
          });
          validLegacyPlacements.push(rect);
        }
      });
      if (fp.timingConstraints !== undefined && !Array.isArray(fp.timingConstraints)) issue('$.floorplan.timingConstraints', 'must be an array');
      if (Array.isArray(fp.timingConstraints)) fp.timingConstraints.forEach((constraint, index) => {
        const path = `$.floorplan.timingConstraints[${index}]`;
        if (!isRecord(constraint)) { issue(path, 'must be an object'); return; }
        checkKeys(constraint, path, ['edgeId', 'targetDelayPs']);
        if (typeof constraint.edgeId !== 'string' || !edges.some(edge => isRecord(edge) && edge.id === constraint.edgeId)) issue(`${path}.edgeId`, `unknown graph edge ${String(constraint.edgeId ?? '')}`);
        if (!isFiniteNumber(constraint.targetDelayPs) || constraint.targetDelayPs < 0) issue(`${path}.targetDelayPs`, 'must be a finite non-negative number');
      });
    } else {
      checkKeys(fp, '$.floorplan', ['units', 'dieOutline', 'placements', 'keepouts', 'hierarchies']);
      if (!['nm', 'um', 'mm'].includes(String(fp.units))) issue('$.floorplan.units', 'must be nm, um, or mm');
      if (!rectangleValid(fp.dieOutline)) issue('$.floorplan.dieOutline', 'must have finite origin and positive width/height');
      else checkKeys(fp.dieOutline, '$.floorplan.dieOutline', ['x', 'y', 'width', 'height']);
      const die = rectangleValid(fp.dieOutline) ? fp.dieOutline : null;
      const checkInsideDie = (bounds: unknown, path: string): void => {
        if (!die || !rectangleValid(bounds)) return;
        const rect = bounds;
        const x = rect.x as number;
        const y = rect.y as number;
        const width = rect.width as number;
        const height = rect.height as number;
        if (x < (die.x as number) || y < (die.y as number) || x + width > (die.x as number) + (die.width as number) || y + height > (die.y as number) + (die.height as number)) issue(path, 'must lie within the die outline');
      };
      for (const field of ['placements', 'keepouts', 'hierarchies'] as const) if (!Array.isArray(fp[field])) issue(`$.floorplan.${field}`, 'must be an array');
      const hierarchyIds = new Set<string>();
      const hierarchyMembers = new Map<string, Set<string>>();
      const hierarchyParents = new Map<string, string>();
      if (Array.isArray(fp.hierarchies)) fp.hierarchies.forEach((raw, hi) => {
        const hp = `$.floorplan.hierarchies[${hi}]`;
        if (!isRecord(raw)) { issue(hp, 'must be an object'); return; }
        checkKeys(raw, hp, ['id', 'parentId', 'nodeIds']);
        if (typeof raw.id !== 'string' || !raw.id.trim()) issue(`${hp}.id`, 'must be a non-empty stable ID');
        else if (hierarchyIds.has(raw.id)) issue(`${hp}.id`, `duplicate hierarchy id ${raw.id}`);
        else hierarchyIds.add(raw.id);
        if (!Array.isArray(raw.nodeIds) || raw.nodeIds.length === 0 || raw.nodeIds.some(id => typeof id !== 'string' || !nodeIds.has(id))) issue(`${hp}.nodeIds`, 'must be a non-empty list of known node IDs');
        else {
          if (new Set(raw.nodeIds).size !== raw.nodeIds.length) issue(`${hp}.nodeIds`, 'node IDs must be unique');
          if (typeof raw.id === 'string') hierarchyMembers.set(raw.id, new Set(raw.nodeIds as string[]));
        }
      });
      if (Array.isArray(fp.hierarchies)) fp.hierarchies.forEach((raw, hi) => {
        if (!isRecord(raw) || raw.parentId == null) return;
        if (typeof raw.parentId !== 'string' || !hierarchyIds.has(raw.parentId)) issue(`$.floorplan.hierarchies[${hi}].parentId`, `unknown hierarchy ${String(raw.parentId)}`);
        else if (typeof raw.id === 'string') hierarchyParents.set(raw.id, raw.parentId);
      });
      const reportedHierarchyCycles = new Set<string>();
      for (const id of hierarchyParents.keys()) {
        const visited: string[] = [];
        const positions = new Map<string, number>();
        let current = id;
        while (hierarchyParents.has(current)) {
          const cycleStart = positions.get(current);
          if (cycleStart !== undefined) {
            const members = visited.slice(cycleStart).sort();
            const cycleKey = JSON.stringify(members);
            if (!reportedHierarchyCycles.has(cycleKey)) {
              reportedHierarchyCycles.add(cycleKey);
              issue(`$.floorplan.hierarchies[id=${current}].parentId`, 'hierarchy parent relationships must be acyclic');
            }
            break;
          }
          positions.set(current, visited.length);
          visited.push(current);
          current = hierarchyParents.get(current)!;
        }
      }
      const validPlacements: Array<{ nodeId: string; bounds: Rect; index: number }> = [];
      if (Array.isArray(fp.placements)) {
        const placed = new Set<string>();
        fp.placements.forEach((raw, pi) => {
          const pp = `$.floorplan.placements[${pi}]`;
          if (!isRecord(raw)) { issue(pp, 'must be an object'); return; }
          checkKeys(raw, pp, ['nodeId', 'bounds', 'locked', 'hierarchyId']);
          if (typeof raw.nodeId !== 'string' || !nodeIds.has(raw.nodeId)) issue(`${pp}.nodeId`, `unknown node ${String(raw.nodeId ?? '')}`);
          else if (placed.has(raw.nodeId)) issue(`${pp}.nodeId`, `duplicate placement for ${raw.nodeId}`);
          else placed.add(raw.nodeId);
          if (!rectangleValid(raw.bounds)) issue(`${pp}.bounds`, 'must have finite origin and positive width/height');
          else {
            checkKeys(raw.bounds, `${pp}.bounds`, ['x', 'y', 'width', 'height']);
            checkInsideDie(raw.bounds, `${pp}.bounds`);
            const bounds = raw.bounds as unknown as Rect;
            if (typeof raw.nodeId === 'string') {
              validPlacements.forEach((other) => {
                if (rectanglesOverlap(bounds, other.bounds)) issue(`${pp}.bounds`, `overlaps node ${other.nodeId} at $.floorplan.placements[${other.index}].bounds`);
              });
              validPlacements.push({ nodeId: raw.nodeId, bounds, index: pi });
            }
          }
          if (typeof raw.locked !== 'boolean') issue(`${pp}.locked`, 'must be boolean');
          if (raw.hierarchyId != null && (typeof raw.hierarchyId !== 'string' || !hierarchyIds.has(raw.hierarchyId))) issue(`${pp}.hierarchyId`, `unknown hierarchy ${String(raw.hierarchyId)}`);
          else if (typeof raw.hierarchyId === 'string' && typeof raw.nodeId === 'string' && hierarchyMembers.has(raw.hierarchyId) && !hierarchyMembers.get(raw.hierarchyId)!.has(raw.nodeId)) issue(`${pp}.hierarchyId`, `node ${raw.nodeId} is not a member of hierarchy ${raw.hierarchyId}`);
        });
      }
      if (Array.isArray(fp.keepouts)) {
        const keepoutIds = new Set<string>();
        fp.keepouts.forEach((raw, ki) => {
          const kp = `$.floorplan.keepouts[${ki}]`;
          if (!isRecord(raw)) { issue(kp, 'must be an object'); return; }
          checkKeys(raw, kp, ['id', 'bounds', 'kind']);
          if (typeof raw.id !== 'string' || !raw.id.trim()) issue(`${kp}.id`, 'must be a non-empty stable ID');
          else if (keepoutIds.has(raw.id)) issue(`${kp}.id`, `duplicate keepout id ${raw.id}`);
          else keepoutIds.add(raw.id);
          if (!rectangleValid(raw.bounds)) issue(`${kp}.bounds`, 'must have finite origin and positive width/height');
          else {
            checkKeys(raw.bounds, `${kp}.bounds`, ['x', 'y', 'width', 'height']);
            checkInsideDie(raw.bounds, `${kp}.bounds`);
            const bounds = raw.bounds as unknown as Rect;
            validPlacements.forEach((placement) => {
              if (rectanglesOverlap(bounds, placement.bounds)) issue(`$.floorplan.placements[${placement.index}].bounds`, `intersects keepout ${String(raw.id)} at ${kp}.bounds`);
            });
          }
        });
      }
    }
  }

  const edgeIds = new Set<string>();
  const directedPairs = new Map<string, string>();
  const adjacency = new Map([...nodeIds].map((id) => [id, new Set<string>()]));
  edges.forEach((raw, i) => {
    const path = `$.edges[${i}]`;
    if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(raw)) {
      if (!['id', 'src', 'dst', 'width', 'pipelineStages', 'vcClass', 'srcPort', 'dstPort', 'domainCrossing', 'physical'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    }
    const edgeIdProblem = graphIdProblem(raw.id);
    if (edgeIdProblem) issue(`${path}.id`, edgeIdProblem, { code: 'edge.id_format', objectRef: `${path}.id` });
    else if (edgeIds.has(raw.id as string)) issue(`${path}.id`, `duplicate edge id ${raw.id}`);
    else edgeIds.add(raw.id as string);
    const src = typeof raw.src === 'string' ? raw.src : '';
    const dst = typeof raw.dst === 'string' ? raw.dst : '';
    if (!nodeIds.has(src)) issue(`${path}.src`, `unknown node ${src || '(empty)'}`);
    if (!nodeIds.has(dst)) issue(`${path}.dst`, `unknown node ${dst || '(empty)'}`);
    if (src && src === dst) issue(path, 'self-loops are not supported');
    if (nodeIds.has(src) && nodeIds.has(dst) && src !== dst) {
      const pair = `${src}\u0000${dst}`;
      const first = directedPairs.get(pair);
      if (first !== undefined) {
        issue(path, `duplicate directed link ${src} -> ${dst} (also ${first})`, {
          code: 'edge.duplicate_directed_link',
          objectRef: `$.edges[id=${typeof raw.id === 'string' ? raw.id : i}]`,
        });
      } else {
        directedPairs.set(pair, typeof raw.id === 'string' ? raw.id : path);
      }
    }
    if (isPositiveInt(raw.width) === false) issue(`${path}.width`, 'must be a positive integer');
    if (!isPositiveInt(raw.pipelineStages)) issue(`${path}.pipelineStages`, 'must be a positive integer');
    if (typeof raw.vcClass !== 'number' || !Number.isSafeInteger(raw.vcClass) || raw.vcClass < 0) issue(`${path}.vcClass`, 'must be a non-negative integer');
    for (const [field, endpoint] of [['srcPort', src], ['dstPort', dst]] as const) {
      const port = raw[field];
      if (port === undefined) continue;
      if (!Number.isSafeInteger(port) || typeof port !== 'number' || port < 0) issue(`${path}.${field}`, 'must be a non-negative integer when set');
      else {
        const node = nodeById.get(endpoint);
        const capacity = node?.ports;
        if (isPositiveInt(capacity) && port >= capacity) issue(`${path}.${field}`, `port ${port} is outside ${endpoint}'s 0..${capacity - 1} port range`);
      }
    }
    if (raw.domainCrossing !== undefined && (!isRecord(raw.domainCrossing) || !isJsonValue(raw.domainCrossing))) issue(`${path}.domainCrossing`, 'must be a JSON object');
    if (raw.physical !== undefined) {
      if (!isRecord(raw.physical)) issue(`${path}.physical`, 'must be an object');
      else {
        for (const key of Object.keys(raw.physical)) if (!['routeLength', 'layer', 'routeClass', 'locked', 'waypoints'].includes(key)) issue(`${path}.physical.${key}`, 'unknown field');
        if (raw.physical.routeLength !== undefined && (!isFiniteNumber(raw.physical.routeLength) || raw.physical.routeLength < 0)) issue(`${path}.physical.routeLength`, 'must be a non-negative finite number');
        for (const key of ['layer', 'routeClass'] as const) if (raw.physical[key] !== undefined && raw.physical[key] !== null && (typeof raw.physical[key] !== 'string' || !raw.physical[key].trim())) issue(`${path}.physical.${key}`, 'must be a non-empty string or null');
        if (raw.physical.locked !== undefined && typeof raw.physical.locked !== 'boolean') issue(`${path}.physical.locked`, 'must be boolean');
        if (raw.physical.waypoints !== undefined && !Array.isArray(raw.physical.waypoints)) issue(`${path}.physical.waypoints`, 'must be an array');
        if (Array.isArray(raw.physical.waypoints)) {
          if (raw.physical.waypoints.length > 0 && (!isRecord(value.floorplan) || !('unit' in value.floorplan) || !isRecord(value.floorplan.die))) issue('$.floorplan.die', 'manual physical waypoints require a legacy floorplan with an authored die outline');
          raw.physical.waypoints.forEach((waypoint, index) => {
            const wp = `${path}.physical.waypoints[${index}]`;
            if (!isRecord(waypoint)) { issue(wp, 'must be an object'); return; }
            checkKeys(waypoint, wp, ['x', 'y']);
            if (!isFiniteNumber(waypoint.x)) issue(`${wp}.x`, 'must be finite');
            if (!isFiniteNumber(waypoint.y)) issue(`${wp}.y`, 'must be finite');
            const die = isRecord(value.floorplan) && isRecord(value.floorplan.die) ? value.floorplan.die : null;
            if (die && isFiniteNumber(waypoint.x) && isFiniteNumber(waypoint.y)
              && isFiniteNumber(die.originX) && isFiniteNumber(die.originY) && isFiniteNumber(die.width) && isFiniteNumber(die.height)
              && (waypoint.x < die.originX || waypoint.x > die.originX + die.width || waypoint.y < die.originY || waypoint.y > die.originY + die.height)) issue(wp, 'waypoint must lie within the authored die outline');
          });
        }
      }
    }
    if (nodeIds.has(src) && nodeIds.has(dst)) {
      degree.set(src, (degree.get(src) ?? 0) + 1);
      degree.set(dst, (degree.get(dst) ?? 0) + 1);
      adjacency.get(src)?.add(dst);
      adjacency.get(dst)?.add(src);
      const pairProblem = directionPairProblem(interfaceRoleByNode.get(src), interfaceRoleByNode.get(dst));
      if (pairProblem) {
        issue(`${path}`, `invalid direction pairing ${src} -> ${dst}: ${pairProblem}`, {
          code: 'edge.direction_incompatible',
          objectRef: `$.edges[id=${typeof raw.id === 'string' ? raw.id : i}]`,
        });
      }
    }
  });

  const assignedPorts = new Map<string, Map<number, string>>();
  edges.forEach((raw, i) => {
    if (!isRecord(raw)) return;
    const path = `$.edges[${i}]`;
    for (const [field, endpoint, portField] of [['srcPort', raw.src, 'srcPort'], ['dstPort', raw.dst, 'dstPort']] as const) {
      const port = raw[field];
      if (typeof endpoint !== 'string' || !nodeIds.has(endpoint) || typeof port !== 'number' || !Number.isSafeInteger(port) || port < 0) continue;
      const used = assignedPorts.get(endpoint) ?? new Map<number, string>();
      const prior = used.get(port);
      if (prior) issue(`${path}.${portField}`, `port ${port} on ${endpoint} is already assigned to edge ${prior}`);
      else used.set(port, typeof raw.id === 'string' ? raw.id : `edge[${i}]`);
      assignedPorts.set(endpoint, used);
    }
  });

  // Validate named clock/reset/power references when the typed domain contract is present.
  // Older v1 projects without `domains` retain their historical opaque clock labels.
  if (value.domains !== undefined) {
    const d = value.domains;
    const domainArrays = ['clocks', 'resets', 'powers', 'portAssignments'] as const;
    if (!isRecord(d)) issue('$.domains', 'must be an object');
    const records = new Map<string, Record<string, unknown>[]>();
    if (isRecord(d)) {
      checkKeys(d, '$.domains', domainArrays);
      for (const key of domainArrays) {
      const raw = d[key];
      if (!Array.isArray(raw)) { issue(`$.domains.${key}`, 'must be an array'); records.set(key, []); continue; }
      records.set(key, raw.filter(isRecord));
      if (raw.some((entry) => !isRecord(entry))) issue(`$.domains.${key}`, 'entries must be objects');
      }
    }
    const ids = new Map<string, Set<string>>();
    for (const [collection, entries] of [['clocks', records.get('clocks') ?? []], ['resets', records.get('resets') ?? []], ['powers', records.get('powers') ?? []]] as const) {
      const seen = new Set<string>();
      entries.forEach((entry, i) => {
        const path = `$.domains.${collection}[${i}]`;
        const allowed = collection === 'clocks' ? ['id', 'frequencyHz', 'source'] : collection === 'resets' ? ['id', 'polarity', 'asynchronous', 'clockDomainId'] : ['id', 'nominalVoltageV', 'canPowerOff'];
        checkKeys(entry, path, allowed);
        if (typeof entry.id !== 'string' || !entry.id.trim()) issue(`${path}.id`, 'must be a non-empty string');
        else if (seen.has(entry.id)) issue(`${path}.id`, `duplicate domain id ${entry.id}`);
        else seen.add(entry.id);
        if (collection === 'clocks') {
          if (entry.frequencyHz !== undefined && entry.frequencyHz !== null && (!isFiniteNumber(entry.frequencyHz) || entry.frequencyHz <= 0)) issue(`${path}.frequencyHz`, 'must be null or a positive finite number');
          if (entry.source !== undefined && entry.source !== null && typeof entry.source !== 'string') issue(`${path}.source`, 'must be null or a string');
        } else if (collection === 'resets') {
          if (entry.polarity !== undefined && entry.polarity !== 'active_high' && entry.polarity !== 'active_low') issue(`${path}.polarity`, 'must be active_high or active_low');
          if (entry.asynchronous !== undefined && typeof entry.asynchronous !== 'boolean') issue(`${path}.asynchronous`, 'must be boolean');
        } else {
          if (entry.nominalVoltageV !== undefined && entry.nominalVoltageV !== null && (!isFiniteNumber(entry.nominalVoltageV) || entry.nominalVoltageV <= 0)) issue(`${path}.nominalVoltageV`, 'must be null or a positive finite number');
          if (entry.canPowerOff !== undefined && typeof entry.canPowerOff !== 'boolean') issue(`${path}.canPowerOff`, 'must be boolean');
        }
      });
      ids.set(collection, seen);
    }
    const refs: [string, string][] = [['clock', 'clocks'], ['resetDomain', 'resets'], ['powerDomain', 'powers']];
    nodes.forEach((raw, i) => {
      if (!isRecord(raw)) return;
      for (const [field, collection] of refs) {
        const ref = raw[field];
        if (typeof ref === 'string' && !ids.get(collection)?.has(ref)) issue(`$.nodes[${i}].${field}`, `unknown ${collection} domain ${ref}`);
      }
    });
    (records.get('resets') ?? []).forEach((reset, i) => {
      if (typeof reset.clockDomainId === 'string' && !ids.get('clocks')?.has(reset.clockDomainId)) issue(`$.domains.resets[${i}].clockDomainId`, `unknown clocks domain ${reset.clockDomainId}`);
    });
    const portIdsByNode = new Map<string, Set<string>>();
    if (Array.isArray(value.agents)) for (const agent of value.agents) {
      if (!isRecord(agent) || typeof agent.nodeId !== 'string' || !Array.isArray(agent.ports)) continue;
      const portIds = portIdsByNode.get(agent.nodeId) ?? new Set<string>();
      for (const port of agent.ports) if (isRecord(port) && typeof port.id === 'string') portIds.add(port.id);
      portIdsByNode.set(agent.nodeId, portIds);
    }
    const assignmentKeys = new Set<string>();
    (records.get('portAssignments') ?? []).forEach((assignment, i) => {
      const path = `$.domains.portAssignments[${i}]`;
      checkKeys(assignment, path, ['nodeId', 'portId', 'clockDomainId', 'resetDomainId', 'powerDomainId']);
      if (typeof assignment.nodeId !== 'string' || !nodeIds.has(assignment.nodeId)) issue(`${path}.nodeId`, `unknown node ${String(assignment.nodeId ?? '')}`);
      if (typeof assignment.portId !== 'string' || !assignment.portId.trim()) issue(`${path}.portId`, 'must be a non-empty stable port ID');
      else if (typeof assignment.nodeId === 'string' && portIdsByNode.has(assignment.nodeId) && !portIdsByNode.get(assignment.nodeId)!.has(assignment.portId)) issue(`${path}.portId`, `unknown port ${assignment.portId} on node ${assignment.nodeId}`);
      const key = JSON.stringify([assignment.nodeId, assignment.portId]);
      if (assignmentKeys.has(key)) issue(path, 'duplicate port domain assignment');
      else assignmentKeys.add(key);
      for (const [field, collection] of [['clockDomainId', 'clocks'], ['resetDomainId', 'resets'], ['powerDomainId', 'powers']] as const) {
        const ref = assignment[field];
        if (ref !== undefined && (typeof ref !== 'string' || !ids.get(collection)?.has(ref))) issue(`$.domains.portAssignments[${i}].${field}`, `unknown ${collection} domain ${String(ref ?? '')}`);
      }
    });
    edges.forEach((raw, i) => {
      if (!isRecord(raw) || raw.domainCrossing === undefined) return;
      const crossing = raw.domainCrossing;
      if (!isRecord(crossing) || !isJsonValue(crossing)) return;
      checkKeys(crossing, `$.edges[${i}].domainCrossing`, ['clock', 'reset', 'power']);
      if (Object.keys(crossing).length === 0) issue(`$.edges[${i}].domainCrossing`, 'must define at least one crossing policy');
      for (const kind of ['clock', 'reset', 'power']) {
        const policy = crossing[kind];
        if (policy === undefined) continue;
        const allowedPolicies: Record<string, string[]> = {
          clock: ['same_domain', 'synchronizer', 'async_fifo', 'explicit_none'],
          reset: ['same_domain', 'reset_bridge', 'explicit_none'],
          power: ['same_domain', 'level_shifter', 'isolation', 'explicit_none'],
        };
        if (!isRecord(policy)) issue(`$.edges[${i}].domainCrossing.${kind}`, 'must be an object');
        else {
          const policyPath = `$.edges[${i}].domainCrossing.${kind}`;
          checkKeys(policy, policyPath, ['policy', 'elementNodeId', 'notes']);
          if (typeof policy.policy !== 'string' || !allowedPolicies[kind].includes(policy.policy)) issue(`${policyPath}.policy`, `unsupported ${kind} crossing policy`);
          if (policy.elementNodeId !== undefined && (typeof policy.elementNodeId !== 'string' || !nodeIds.has(policy.elementNodeId))) issue(`${policyPath}.elementNodeId`, `unknown crossing element node ${String(policy.elementNodeId)}`);
          if (policy.notes !== undefined && typeof policy.notes !== 'string') issue(`${policyPath}.notes`, 'must be a string');
        }
      }
    });
  }

  for (const [id, used] of degree) {
    const ports = nodeById.get(id)?.ports;
    if (isPositiveInt(ports) && used > ports) {
      issue(`$.nodes[id=${id}].ports`, `${used} incident edges exceed ${ports} ports`, {
        code: 'node.ports_oversubscribed', objectRef: `$.nodes[id=${id}]`,
      });
    }
  }
  if (nodeIds.size > 1) {
    const seen = new Set<string>();
    const components: string[][] = [];
    for (const root of nodeIds) {
      if (seen.has(root)) continue;
      const component: string[] = [];
      const pending = [root];
      while (pending.length) {
        const id = pending.pop() as string;
        if (seen.has(id)) continue;
        seen.add(id);
        component.push(id);
        for (const next of adjacency.get(id) ?? []) if (!seen.has(next)) pending.push(next);
      }
      components.push(component.sort());
    }
    if (components.length > 1) {
      issue('$.nodes', `graph is disconnected (${components.length} components)`, {
        severity: options.requireConnected ? 'error' : 'warning',
        code: 'graph.disconnected',
        objectRef: '$.nodes',
        components,
        quickFix: { label: 'Select a component to attach', code: 'graph.attach_component' },
      });
    }
  }
  return issues;
}

/** Recursively sort object keys so equal JSON values serialize identically
 *  regardless of the order they were assigned. Arrays keep their order. */
export const canonicalizeJson = (value: JsonValue): JsonValue => {
  if (Array.isArray(value)) return value.map(canonicalizeJson);
  if (value !== null && typeof value === 'object') {
    const out: { [key: string]: JsonValue } = {};
    for (const key of Object.keys(value).sort()) out[key] = canonicalizeJson(value[key]);
    return out;
  }
  return value;
};

/** Normalize a project into a canonical shape: fixed field ordering per node
 *  and edge, optional empties dropped, and unordered metadata key-sorted. Two
 *  semantically equal projects produce byte-identical output (M0-19). */
export function canonicalizeProject(project: LoomProject): Record<string, unknown> {
  const nodes = project.nodes.map((n) => {
    const out: Record<string, unknown> = {
      id: n.id, x: n.x, y: n.y, role: n.role, ports: n.ports,
    };
    out.clock = n.clock ?? null;
    if (n.resetDomain !== undefined) out.resetDomain = n.resetDomain;
    if (n.powerDomain !== undefined) out.powerDomain = n.powerDomain;
    if (n.catalogRef !== undefined) out.catalogRef = canonicalizeJson(n.catalogRef as unknown as JsonValue);
    if (n.vc !== undefined && Object.keys(n.vc).length > 0) out.vc = canonicalizeJson(n.vc);
    if (n.interfaceRole !== undefined) out.interfaceRole = n.interfaceRole;
    return out;
  });
  const edges = project.edges.map((e) => {
    const out: Record<string, unknown> = {
      id: e.id, src: e.src, dst: e.dst, width: e.width,
      pipelineStages: e.pipelineStages, vcClass: e.vcClass,
    };
    if (e.srcPort !== undefined) out.srcPort = e.srcPort;
    if (e.dstPort !== undefined) out.dstPort = e.dstPort;
    if (e.domainCrossing !== undefined) out.domainCrossing = canonicalizeJson(e.domainCrossing as unknown as JsonValue);
    if (e.physical !== undefined) out.physical = canonicalizeJson(e.physical as unknown as JsonValue);
    return out;
  });
  const out: Record<string, unknown> = {
    schemaVersion: project.schemaVersion,
    compilerSemanticsVersion: project.compilerSemanticsVersion,
    presetHint: project.presetHint, nodes, edges,
  };
  if (project.routing !== undefined) out.routing = canonicalizeJson(project.routing as unknown as JsonValue);
  if (project.firewall !== undefined) out.firewall = canonicalizeJson(project.firewall);
  if (project.access !== undefined) out.access = canonicalizeJson(project.access as unknown as JsonValue);
  if (project.floorplan !== undefined) out.floorplan = canonicalizeJson(project.floorplan as unknown as JsonValue);
  if (project.metadata !== undefined) out.metadata = canonicalizeJson(project.metadata as unknown as JsonValue);
  if (project.workload !== undefined) out.workload = canonicalizeJson(project.workload);
  if (project.vcConfig !== undefined) out.vcConfig = canonicalizeJson(project.vcConfig as unknown as JsonValue);
  if (project.domains !== undefined) out.domains = canonicalizeJson(project.domains as unknown as JsonValue);
  if (project.agents !== undefined) out.agents = canonicalizeJson(project.agents as unknown as JsonValue);
  return out;
}

/** cyrb53 — a small deterministic, non-cryptographic string hash. Used to give
 *  a project a stable fingerprint for diffs and run manifests. */
export const stableHash = (input: string): string => {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16).padStart(16, '0');
};

/** Stable content fingerprint of a project's canonical form. Equal projects
 *  hash equal; any edit changes the hash. */
export function fingerprintProject(project: LoomProject): string {
  return stableHash(JSON.stringify(canonicalizeProject(project)));
}

export function parseProject(json: string): LoomProject {
  const result = parseProjectResult(json);
  if (!result.ok) {
    const syntaxIssue = result.issues.find((issue) => issue.message.startsWith('invalid project JSON:'));
    if (syntaxIssue) throw new Error(syntaxIssue.message);
    throw new Error(result.issues.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  }
  return result.project;
}

export type ProjectParseResult = { ok: true; project: LoomProject } | { ok: false; issues: ProjectIssue[] };

/** Pre-parse admission limits: reject pathologically large or deeply nested
 *  JSON before it can exhaust the parser or the validator. */
function projectJsonAdmissionIssue(json: string): ProjectIssue | null {
  if (json.length > MAX_PROJECT_JSON_CHARS) {
    return makeIssue({ path: '$', message: `project JSON exceeds ${MAX_PROJECT_JSON_CHARS} character limit`, code: 'LOOM_PROJECT_INVALID', objectRef: '$' });
  }
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (const char of json) {
    if (inString) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') inString = false;
    } else if (char === '"') inString = true;
    else if (char === '{' || char === '[') {
      if (++depth > MAX_PROJECT_JSON_DEPTH) {
        return makeIssue({ path: '$', message: `project JSON nesting exceeds ${MAX_PROJECT_JSON_DEPTH} levels`, code: 'LOOM_PROJECT_INVALID', objectRef: '$' });
      }
    } else if (char === '}' || char === ']') depth -= 1;
  }
  return null;
}

/** Non-throwing parse/validation API for callers that need canonical findings. */
export function parseProjectResult(json: string): ProjectParseResult {
  const admissionIssue = projectJsonAdmissionIssue(json);
  if (admissionIssue) return { ok: false, issues: [admissionIssue] };
  let value: unknown;
  try { value = JSON.parse(json); }
  catch (error) {
    const message = `invalid project JSON: ${error instanceof Error ? error.message : String(error)}`;
    return { ok: false, issues: [makeIssue({ path: '$', message, code: 'LOOM_PROJECT_INVALID', objectRef: '$' })] };
  }
  const errors = errorIssues(validateProject(value));
  if (errors.length) return { ok: false, issues: errors };
  return { ok: true, project: value as LoomProject };
}

/** Parse a locally autosaved editor draft while preserving temporarily invalid workload values. */
export function parseProjectDraft(json: string): LoomProject {
  const admissionIssue = projectJsonAdmissionIssue(json);
  if (admissionIssue) throw new Error(admissionIssue.message);
  const value: unknown = JSON.parse(json);
  if (!isRecord(value)) throw new Error('project draft must be an object');
  const workload = value.workload;
  const baseErrors = errorIssues(validateProject({ ...value, workload: undefined }));
  if (baseErrors.length) throw new Error(baseErrors.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  if (workload !== undefined && (!isRecord(workload) || !isJsonValue(workload))) throw new Error('$.workload: draft must be a JSON object');
  return value as unknown as LoomProject;
}

/** Normalize only defaults with unambiguous meaning; do not invent workload, VC, access or physical data. */
export function normalizeProject(project: LoomProject): LoomProject {
  return {
    ...project,
    nodes: project.nodes.map((node) => ({ ...node, clock: node.clock ?? null })),
    edges: project.edges.map((edge) => ({ ...edge })),
  };
}

/** Recursively sort object keys (never array order) for byte-identical output. */
function sortJsonKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortJsonKeys);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([k, v]) => [k, sortJsonKeys(v)]));
  }
  return value;
}

/** Stable-key ordering without sorting semantic arrays (nodes/edges retain authored order). */
export function serializeProject(project: LoomProject): string {
  const errors = errorIssues(validateProject(project));
  if (errors.length) throw new Error(errors.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return `${JSON.stringify(sortJsonKeys(canonicalizeProject(project)), null, 2)}\n`;
}
