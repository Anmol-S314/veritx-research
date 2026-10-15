/** Versioned editable graph document for Loom. This is authoring data, not a
 * compiled fabric or execution claim. Keep the compiler adapter separate. */
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface GraphNode {
  id: string;
  x: number;
  y: number;
  role: string;
  ports: number;
  clock?: string | null;
  vc?: { [key: string]: JsonValue };
}

export interface GraphEdge {
  id: string;
  src: string;
  dst: string;
  width: number;
  pipelineStages: number;
  vcClass: number;
  srcPort?: number;
  dstPort?: number;
}

export interface CustomRoutingRule {
  src: string;
  dst: string;
  nextHop: string;
}

export type RoutingConfig = { policy: 'xy' | 'west_first' | 'odd_even' } | { policy: 'custom'; rules: CustomRoutingRule[] };
export type PhysicalUnit = 'um' | 'mm';
export interface DieOutline { originX: number; originY: number; width: number; height: number }
export interface PhysicalPlacement { nodeId: string; x: number; y: number; width: number; height: number; locked?: boolean }
export interface PhysicalDelayModel { wireDelayPsPerUnit: number; fixedDelayPs: number }
export interface PhysicalTimingConstraint { edgeId: string; targetDelayPs: number }
export interface FloorplanIntent { unit: PhysicalUnit; die?: DieOutline; gridStep?: number; placements?: PhysicalPlacement[]; delayModel?: PhysicalDelayModel; timingConstraints?: PhysicalTimingConstraint[] }

export interface LoomProject {
  schemaVersion: 1;
  presetHint: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  routing?: RoutingConfig;
  floorplan?: FloorplanIntent;
  firewall?: { [key: string]: JsonValue };
  workload?: { [key: string]: JsonValue };
}

export interface ProjectIssue { path: string; message: string }

const MAX_NODES = 256;
const MAX_EDGES = 512;
const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const isPositiveInt = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const MAX_METADATA_DEPTH = 64;

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
const isJsonValue = (value: unknown, depth = 0): value is JsonValue => {
  if (depth > MAX_METADATA_DEPTH) return false;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((child) => isJsonValue(child, depth + 1));
  return isRecord(value) && Object.values(value).every((child) => isJsonValue(child, depth + 1));
};

/** Validate identity, endpoint, degree and connectivity invariants before a
 *  graph document enters editor state or is serialized. */
export function validateProject(value: unknown): ProjectIssue[] {
  const issues: ProjectIssue[] = [];
  const issue = (path: string, message: string): void => { issues.push({ path, message }); };
  if (!isRecord(value)) return [{ path: '$', message: 'must be an object' }];
  const allowed = new Set(['schemaVersion', 'presetHint', 'nodes', 'edges', 'routing', 'floorplan', 'firewall', 'workload']);
  for (const key of Object.keys(value)) if (!allowed.has(key)) issue(`$.${key}`, 'unknown field');
  if (value.schemaVersion !== 1) issue('$.schemaVersion', 'must equal 1');
  if (value.presetHint !== null && typeof value.presetHint !== 'string') issue('$.presetHint', 'must be a string or null');
  if (!Array.isArray(value.nodes)) issue('$.nodes', 'must be an array');
  if (!Array.isArray(value.edges)) issue('$.edges', 'must be an array');
  if (Array.isArray(value.nodes) && value.nodes.length > MAX_NODES) issue('$.nodes', `exceeds ${MAX_NODES}-node budget`);
  if (Array.isArray(value.edges) && value.edges.length > MAX_EDGES) issue('$.edges', `exceeds ${MAX_EDGES}-edge budget`);
  if (value.routing !== undefined) {
    if (!isRecord(value.routing)) issue('$.routing', 'must be an object');
    else if (value.routing.policy === 'xy') {
      for (const key of Object.keys(value.routing)) if (key !== 'policy') issue(`$.routing.${key}`, 'unknown field');
      if (!supportsXYRouting({ presetHint: value.presetHint as string | null, nodes: value.nodes as GraphNode[], edges: value.edges as GraphEdge[] })) {
        issue('$.routing.policy', 'xy is supported only on the canonical 4×4 or 8×8 mesh graph; other shapes are refused');
      }
    } else if (value.routing.policy === 'west_first' || value.routing.policy === 'odd_even') {
      for (const key of Object.keys(value.routing)) if (key !== 'policy') issue(`$.routing.${key}`, 'unknown field');
      if (!supportsXYRouting({ presetHint: value.presetHint as string | null, nodes: value.nodes as GraphNode[], edges: value.edges as GraphEdge[] })) {
        issue(`$.routing.policy`, `${value.routing.policy} is supported only on the canonical 4×4 or 8×8 mesh graph; other shapes are refused`);
      }
    } else if (value.routing.policy === 'custom') {
      for (const key of Object.keys(value.routing)) if (!['policy', 'rules'].includes(key)) issue(`$.routing.${key}`, 'unknown field');
      if (!Array.isArray(value.routing.rules)) issue('$.routing.rules', 'must be an array');
      else for (const message of validateCustomRoutingRules(value.nodes, value.edges, value.routing.rules)) {
        const cut = message.indexOf(':');
        if (cut < 0) issue('$.routing', message);
        else issue(`$.${message.slice(0, cut)}`, message.slice(cut + 1).trim());
      }
    } else issue('$.routing.policy', 'unsupported routing policy');
  }
  if (value.floorplan !== undefined) {
    if (!isRecord(value.floorplan)) issue('$.floorplan', 'must be an object');
    else {
      for (const key of Object.keys(value.floorplan)) if (!['unit', 'die', 'gridStep', 'placements', 'delayModel', 'timingConstraints'].includes(key)) issue(`$.floorplan.${key}`, 'unknown field');
      if (value.floorplan.unit !== 'um' && value.floorplan.unit !== 'mm') issue('$.floorplan.unit', 'must be um or mm');
      if (value.floorplan.gridStep !== undefined && (!isFiniteNumber(value.floorplan.gridStep) || value.floorplan.gridStep <= 0)) {
        issue('$.floorplan.gridStep', 'must be a finite positive number');
      }
      if (value.floorplan.timingConstraints !== undefined) {
        if (!Array.isArray(value.floorplan.timingConstraints)) issue('$.floorplan.timingConstraints', 'must be an array');
        else value.floorplan.timingConstraints.forEach((raw, index) => {
          const path = `$.floorplan.timingConstraints[${index}]`;
          if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
          for (const key of Object.keys(raw)) if (!['edgeId', 'targetDelayPs'].includes(key)) issue(`${path}.${key}`, 'unknown field');
          if (typeof raw.edgeId !== 'string' || !raw.edgeId.trim()) issue(`${path}.edgeId`, 'must be a non-empty edge ID');
          if (!isFiniteNumber(raw.targetDelayPs) || raw.targetDelayPs < 0) issue(`${path}.targetDelayPs`, 'must be a finite non-negative number');
        });
      }
      if (value.floorplan.delayModel !== undefined) {
        const model = value.floorplan.delayModel;
        if (!isRecord(model)) issue('$.floorplan.delayModel', 'must be an object');
        else {
          for (const key of Object.keys(model)) if (!['wireDelayPsPerUnit', 'fixedDelayPs'].includes(key)) issue(`$.floorplan.delayModel.${key}`, 'unknown field');
          for (const key of ['wireDelayPsPerUnit', 'fixedDelayPs'] as const) {
            if (!isFiniteNumber(model[key]) || model[key] < 0) issue(`$.floorplan.delayModel.${key}`, 'must be a finite non-negative number');
          }
        }
      }
      if (value.floorplan.placements !== undefined) {
        if (!Array.isArray(value.floorplan.placements)) issue('$.floorplan.placements', 'must be an array');
        else value.floorplan.placements.forEach((raw, index) => {
          const path = `$.floorplan.placements[${index}]`;
          if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
          for (const key of Object.keys(raw)) if (!['nodeId', 'x', 'y', 'width', 'height', 'locked'].includes(key)) issue(`${path}.${key}`, 'unknown field');
          if (typeof raw.nodeId !== 'string' || !raw.nodeId.trim()) issue(`${path}.nodeId`, 'must be a non-empty node ID');
          for (const key of ['x', 'y', 'width', 'height'] as const) if (!isFiniteNumber(raw[key])) issue(`${path}.${key}`, 'must be finite');
          if (isFiniteNumber(raw.width) && raw.width <= 0) issue(`${path}.width`, 'must be positive');
          if (isFiniteNumber(raw.height) && raw.height <= 0) issue(`${path}.height`, 'must be positive');
          if (raw.locked !== undefined && typeof raw.locked !== 'boolean') issue(`${path}.locked`, 'must be boolean when set');
        });
        if (value.floorplan.unit !== 'um' && value.floorplan.unit !== 'mm') issue('$.floorplan.unit', 'physical placements require explicit um or mm units');
        if (value.floorplan.die === undefined) issue('$.floorplan.die', 'physical placements require an authored die outline');
      }
      if (value.floorplan.die !== undefined) {
        const die = value.floorplan.die;
        if (!isRecord(die)) issue('$.floorplan.die', 'must be an object');
        else {
          for (const key of Object.keys(die)) if (!['originX', 'originY', 'width', 'height'].includes(key)) issue(`$.floorplan.die.${key}`, 'unknown field');
          for (const key of ['originX', 'originY', 'width', 'height'] as const) {
            if (!isFiniteNumber(die[key])) issue(`$.floorplan.die.${key}`, 'must be a finite number');
          }
          if (isFiniteNumber(die.width) && die.width <= 0) issue('$.floorplan.die.width', 'must be positive');
          if (isFiniteNumber(die.height) && die.height <= 0) issue('$.floorplan.die.height', 'must be positive');
        }
      }
    }
  }
  for (const key of ['firewall', 'workload'] as const) {
    if (value[key] !== undefined && (!isRecord(value[key]) || !isJsonValue(value[key]))) {
      issue(`$.${key}`, 'must be a JSON object');
    }
  }

  const nodes = Array.isArray(value.nodes) ? value.nodes : [];
  const edges = Array.isArray(value.edges) ? value.edges : [];
  if (isRecord(value.floorplan) && Array.isArray(value.floorplan.timingConstraints)) {
    const constraintIds = new Set<string>();
    value.floorplan.timingConstraints.forEach((raw, index) => {
      if (!isRecord(raw) || typeof raw.edgeId !== 'string') return;
      const path = `$.floorplan.timingConstraints[${index}].edgeId`;
      if (constraintIds.has(raw.edgeId)) issue(path, `duplicate timing constraint for ${raw.edgeId}`);
      constraintIds.add(raw.edgeId);
      if (!edges.some((edge) => isRecord(edge) && edge.id === raw.edgeId)) issue(path, `unknown graph edge ${raw.edgeId}`);
    });
  }
  const nodeIds = new Set<string>();
  const nodeById = new Map<string, Record<string, unknown>>();
  const degree = new Map<string, number>();
  nodes.forEach((raw, i) => {
    const path = `$.nodes[${i}]`;
    if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(raw)) {
      if (!['id', 'x', 'y', 'role', 'ports', 'clock', 'vc'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    }
    if (typeof raw.id !== 'string' || raw.id.trim() === '') issue(`${path}.id`, 'must be a non-empty string');
    else if (nodeIds.has(raw.id)) issue(`${path}.id`, `duplicate node id ${raw.id}`);
    else { nodeIds.add(raw.id); nodeById.set(raw.id, raw); degree.set(raw.id, 0); }
    if (!isFiniteNumber(raw.x)) issue(`${path}.x`, 'must be finite');
    if (!isFiniteNumber(raw.y)) issue(`${path}.y`, 'must be finite');
    if (typeof raw.role !== 'string' || raw.role.trim() === '') issue(`${path}.role`, 'must be a non-empty string');
    if (!isPositiveInt(raw.ports)) issue(`${path}.ports`, 'must be a positive integer');
    if (raw.clock !== undefined && raw.clock !== null && (typeof raw.clock !== 'string' || raw.clock === '')) issue(`${path}.clock`, 'must be a non-empty string or null');
    if (raw.vc !== undefined && (!isRecord(raw.vc) || !isJsonValue(raw.vc))) issue(`${path}.vc`, 'must be a JSON object');
    else if (isRecord(raw.vc) && raw.vc.depth !== undefined && !isPositiveInt(raw.vc.depth)) {
      issue(`${path}.vc.depth`, 'must be a positive integer when set');
    }
  });

  if (isRecord(value.floorplan) && Array.isArray(value.floorplan.placements)) {
    const placedNodeIds = new Set<string>();
    value.floorplan.placements.forEach((raw, index) => {
      if (!isRecord(raw) || typeof raw.nodeId !== 'string') return;
      const path = `$.floorplan.placements[${index}].nodeId`;
      if (!nodeIds.has(raw.nodeId)) issue(path, `unknown graph node ${raw.nodeId}`);
      if (placedNodeIds.has(raw.nodeId)) issue(path, `duplicate physical placement for node ${raw.nodeId}`);
      placedNodeIds.add(raw.nodeId);
    });
  }

  const edgeIds = new Set<string>();
  const adjacency = new Map([...nodeIds].map((id) => [id, new Set<string>()]));
  edges.forEach((raw, i) => {
    const path = `$.edges[${i}]`;
    if (!isRecord(raw)) { issue(path, 'must be an object'); return; }
    for (const key of Object.keys(raw)) {
      if (!['id', 'src', 'dst', 'width', 'pipelineStages', 'vcClass', 'srcPort', 'dstPort'].includes(key)) issue(`${path}.${key}`, 'unknown field');
    }
    if (typeof raw.id !== 'string' || raw.id.trim() === '') issue(`${path}.id`, 'must be a non-empty string');
    else if (edgeIds.has(raw.id)) issue(`${path}.id`, `duplicate edge id ${raw.id}`);
    else edgeIds.add(raw.id);
    const src = typeof raw.src === 'string' ? raw.src : '';
    const dst = typeof raw.dst === 'string' ? raw.dst : '';
    if (!nodeIds.has(src)) issue(`${path}.src`, `unknown node ${src || '(empty)'}`);
    if (!nodeIds.has(dst)) issue(`${path}.dst`, `unknown node ${dst || '(empty)'}`);
    if (src && src === dst) issue(path, 'self-loops are not supported');
    if (isPositiveInt(raw.width) === false) issue(`${path}.width`, 'must be a positive integer');
    if (!isPositiveInt(raw.pipelineStages)) issue(`${path}.pipelineStages`, 'must be a positive integer');
    if (typeof raw.vcClass !== 'number' || !Number.isSafeInteger(raw.vcClass) || raw.vcClass < 0) issue(`${path}.vcClass`, 'must be a non-negative integer');
    for (const [field, endpoint] of [['srcPort', src], ['dstPort', dst]] as const) {
      const port = raw[field];
      if (port === undefined) continue;
      if (!Number.isSafeInteger(port) || typeof port !== 'number' || port < 0) {
        issue(`${path}.${field}`, 'must be a non-negative integer when set');
        continue;
      }
      const capacity = nodeById.get(endpoint)?.ports;
      if (isPositiveInt(capacity) && port >= capacity) issue(`${path}.${field}`, `port ${port} is outside ${endpoint}'s 0..${capacity - 1} port range`);
    }
    if (nodeIds.has(src) && nodeIds.has(dst)) {
      degree.set(src, (degree.get(src) ?? 0) + 1);
      degree.set(dst, (degree.get(dst) ?? 0) + 1);
      adjacency.get(src)?.add(dst);
      adjacency.get(dst)?.add(src);
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
  for (const [id, used] of degree) {
    const ports = nodeById.get(id)?.ports;
    if (isPositiveInt(ports) && used > ports) issue(`$.nodes[id=${id}].ports`, `${used} incident edges exceed ${ports} ports`);
  }
  if (nodeIds.size > 1) {
    const seen = new Set<string>();
    const pending = [nodeIds.values().next().value as string];
    while (pending.length) {
      const id = pending.pop() as string;
      if (seen.has(id)) continue;
      seen.add(id);
      for (const next of adjacency.get(id) ?? []) if (!seen.has(next)) pending.push(next);
    }
    if (seen.size !== nodeIds.size) issue('$.nodes', 'graph is disconnected');
  }
  return issues;
}

export function parseProject(json: string): LoomProject {
  let value: unknown;
  try { value = JSON.parse(json); }
  catch (error) { throw new Error(`invalid project JSON: ${error instanceof Error ? error.message : String(error)}`); }
  const issues = validateProject(value);
  if (issues.length) throw new Error(issues.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return value as LoomProject;
}

export function serializeProject(project: LoomProject): string {
  const issues = validateProject(project);
  if (issues.length) throw new Error(issues.map(({ path, message }) => `${path}: ${message}`).join('\n'));
  return `${JSON.stringify(project, null, 2)}\n`;
}
