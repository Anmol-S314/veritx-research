/** Adapter: authoring graph → compiler draft request (explicit topology).
 * The compiler stays authoritative: unknown roles/families refuse here,
 * before any PUT, so the UI never invents a backend capability.
 *
 * Lowering target is a v4 request with an explicit custom TopologyIR —
 * the same shape as the engine's shipped explicit16 preset (custom kind,
 * index links, global link defaults; executes under the AnyNet profile).
 * Node ids map to 0..N-1 indices, edges dedupe to undirected pairs, and agents
 * group by role + clock. Unsupported authored semantics refuse before any PUT.
 */
import { validateProject, type LoomProject } from './project';
import { validationIssue, type ValidationIssue } from './validation';

const KNOWN_ROLES = new Set([
  'compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU',
]);

export interface AdaptOutcome {
  doc: Record<string, unknown> | null;
  refused: string | null;
  issues: ValidationIssue[];
}

interface AdapterRefusal { path: string; message: string }
const adapterIssue = ({ path, message }: AdapterRefusal): ValidationIssue => validationIssue('LOOM_COMPILER_ADAPTER_UNSUPPORTED', path, message);
const adaptRefusal = (path: string, message: string): AdapterRefusal => ({ path, message });
const adaptFailure = (refusal: AdapterRefusal): AdaptOutcome => ({ doc: null, refused: refusal.message, issues: [adapterIssue(refusal)] });

function unsupportedGraphIntent(project: LoomProject): AdapterRefusal | null {
  if (project.firewall !== undefined) return adaptRefusal('$.firewall', 'legacy graph firewall intent is not materialized by the compiler adapter');
  if (project.access !== undefined) return adaptRefusal('$.access', 'graph access-control rules are not materialized by the compiler adapter');
  if (project.workload !== undefined) return adaptRefusal('$.workload', 'graph workload phases are not materialized by the compiler adapter');
  if (project.vcConfig !== undefined) return adaptRefusal('$.vcConfig', 'graph VC/QoS configuration is not materialized by the compiler adapter');
  if (project.domains !== undefined) return adaptRefusal('$.domains', 'graph reset/power domains and crossings are not materialized by the compiler adapter');
  const domainNode = project.nodes.find((n) => n.resetDomain || n.powerDomain);
  if (domainNode) {
    const field = domainNode.resetDomain ? 'resetDomain' : 'powerDomain';
    return adaptRefusal(`$.nodes[id=${domainNode.id}].${field}`, 'graph reset/power domains and crossings are not materialized by the compiler adapter');
  }
  if (project.floorplan !== undefined) return adaptRefusal('$.floorplan', 'graph floorplan intent is not materialized by the compiler adapter');
  if (project.agents?.length) return adaptRefusal('$.agents', 'project agent/port records are not materialized by the compiler adapter');
  const catalogNode = project.nodes.find((n) => n.catalogRef !== undefined);
  if (catalogNode) return adaptRefusal(`$.nodes[id=${catalogNode.id}].catalogRef`, 'catalog-backed node metadata is not materialized by the compiler adapter');
  const physicalEdge = project.edges.find((e) => e.physical !== undefined || e.domainCrossing !== undefined);
  if (physicalEdge) return adaptRefusal(`$.edges[id=${physicalEdge.id}]`, 'edge physical or domain-crossing metadata is not materialized by the compiler adapter');
  if (project.routing !== undefined) return adaptRefusal('$.routing', `graph ${project.routing.policy} routing policy is preview-only and is not materialized by the compiler adapter`);
  const portEdge = project.edges.find((edge) => edge.srcPort !== undefined || edge.dstPort !== undefined);
  if (portEdge) return adaptRefusal(`$.edges[id=${portEdge.id}]`, 'authored edge port assignments are not materialized by the compiler adapter');
  const vcNode = project.nodes.find((n) => n.vc && Object.keys(n.vc).length > 0);
  if (vcNode) return adaptRefusal(`$.nodes[id=${vcNode.id}].vc`, 'per-node VC configuration is not materialized by the compiler adapter');
  return null;
}

function agentGroups(project: LoomProject): { kind: string; count: number; clock: string | null }[] {
  const groups = new Map<string, { kind: string; count: number; clock: string | null }>();
  for (const node of project.nodes) {
    const clock = node.clock ?? null;
    const key = JSON.stringify([node.role, clock]);
    const group = groups.get(key) ?? { kind: node.role, count: 0, clock };
    group.count += 1;
    groups.set(key, group);
  }
  return [...groups.values()];
}

export interface TopologyIROutcome {
  doc: Record<string, unknown> | null;
  refused: string | null;
  linkWidthBits: number;
  issues: ValidationIssue[];
}
const refuseTopology = (path: string, message: string): TopologyIROutcome => ({
  doc: null, refused: message, linkWidthBits: 0, issues: [adapterIssue({ path, message })],
});

/** Lower only edge semantics representable by the compiler's global link attributes. */
export function graphToTopologyIR(project: LoomProject): TopologyIROutcome {
  const index = new Map(project.nodes.map((n, i) => [n.id, i]));
  const seen = new Set<string>();
  const links: [number, number][] = [];
  for (const e of project.edges) {
    const a = index.get(e.src);
    const b = index.get(e.dst);
    if (a === undefined || b === undefined) {
      return refuseTopology(`$.edges[id=${e.id}]`, `edge ${e.id} names a node outside the graph`);
    }
    if (a === b) continue;
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    if (seen.has(key)) continue;
    seen.add(key);
    links.push([a, b]);
  }
  if (project.nodes.length === 0) {
    return refuseTopology('$.nodes', 'the graph has no nodes');
  }
  const stagedEdge = project.edges.find((e) => e.pipelineStages !== 1);
  if (stagedEdge) {
    return refuseTopology(`$.edges[id=${stagedEdge.id}].pipelineStages`, 'per-edge pipelineStages are not materialized by the compiler adapter');
  }
  const classedEdge = project.edges.find((e) => e.vcClass !== 0);
  if (classedEdge) {
    return refuseTopology(`$.edges[id=${classedEdge.id}].vcClass`, 'non-default edge vcClass is not materialized by the compiler adapter');
  }
  const firstWidth = project.edges[0]?.width;
  const widthEdge = project.edges.find((e) => e.width !== firstWidth);
  if (widthEdge) {
    return refuseTopology(`$.edges[id=${widthEdge.id}].width`, 'heterogeneous link width is not representable by global compiler link attributes');
  }
  const widths = new Set(project.edges.map((e) => e.width));
  const linkWidthBits = widths.values().next().value ?? 512;
  const intentRefusal = unsupportedGraphIntent(project);
  if (intentRefusal) return refuseTopology(intentRefusal.path, intentRefusal.message);
  const projectIssues = validateProject(project);
  if (projectIssues.length) return {
    doc: null,
    refused: projectIssues.map(({ path, message }) => `${path}: ${message}`).join('; '),
    linkWidthBits: 0,
    issues: projectIssues,
  };
  return {
    doc: {
      name: 'loom-graph',
      kind: 'custom',
      nodes: project.nodes.length,
      links,
      // The engine accepts global bandwidth/latency only. Width must be
      // uniform; additional per-edge pipeline stages refuse above.
      link_attrs: { bandwidth_GBs: linkWidthBits / 8, latency_ns: 1 },
    },
    refused: null,
    linkWidthBits,
    issues: [],
  };
}

/** Lower a validated graph into a full v4 draft request doc on top of the
 * project's current draft (which carries workload, requirements, physical).
 * topology + agents come from the graph; everything else stays authored. */
export function graphToDraftRequest(
  project: LoomProject,
  base: Record<string, unknown>,
): AdaptOutcome {
  for (const n of project.nodes) {
    if (!KNOWN_ROLES.has(n.role)) {
      return adaptFailure(adaptRefusal(`$.nodes[id=${n.id}].role`, `node ${n.id} carries unknown role ${n.role}`));
    }
  }
  const ir = graphToTopologyIR(project);
  if (!ir.doc) return { doc: null, refused: ir.refused, issues: ir.issues };
  const groups = agentGroups(project);
  const doc: Record<string, unknown> = { ...base };
  delete doc.noc_config;
  delete doc.design_hash;
  delete doc.guardrail_hash;
  doc.schema_version = 4;
  doc.compiler_semantics_version = 4;
  doc.topology = { kind: 'explicit', graph: ir.doc };
  doc.noc_controls = {};
  doc.agents = groups.map((g) => ({
    kind: g.kind, count: g.count, data_width: 256, addr_width: 64,
    protocol: 'AXI', clock_domain: g.clock, power_domain: null,
  }));
  return { doc, refused: null, issues: [] };
}

/** Lower a validated graph into a v4-style draft request doc. */
export function graphToDraft(project: LoomProject): AdaptOutcome {
  for (const n of project.nodes) {
    if (!KNOWN_ROLES.has(n.role)) {
      return adaptFailure(adaptRefusal(`$.nodes[id=${n.id}].role`, `node ${n.id} carries unknown role ${n.role}`));
    }
  }
  const ir = graphToTopologyIR(project);
  if (!ir.doc) return { doc: null, refused: ir.refused, issues: ir.issues };
  const agents = agentGroups(project).map((g) => ({
    kind: g.kind, count: g.count, data_width: 256, addr_width: 64,
    protocol: 'AXI', clock_domain: g.clock, power_domain: null,
  }));
  return {
    doc: {
      schema_version: 4,
      topology: { kind: 'explicit', preset_hint: project.presetHint, graph: ir.doc },
      agents,
    },
    refused: null,
    issues: [],
  };
}

export interface PresetGraphShape {
  preset_id: string;
  family: string;
  routers: { router_id: number; coordinates: number[] }[];
  channels: { src_router: number; dst_router: number; width_bits: number }[];
  endpoints: { kind: string; router_id: number }[];
}

/** Seed an authoring graph from a shipped preset's materialized shape.
 * Nodes take certified coordinates where the family places them (×140),
 * grid fallback otherwise; roles take the majority seated kind per router
 * ('nic' when unseated); edges dedupe directed channels to pairs. A preset
 * that projects no channels refuses — nodes-only would fail connectivity
 * and there is nothing honest to wire automatically. */
export function presetGraphToProject(g: PresetGraphShape): {
  doc: LoomProject | null;
  refused: string | null;
} {
  if (g.routers.length === 0) {
    return { doc: null, refused: `preset ${g.preset_id} materialized no routers` };
  }
  if (g.channels.length === 0) {
    return {
      doc: null,
      refused: `preset ${g.preset_id} projects no channels in its certified view — seed nodes manually or pick a preset with links`,
    };
  }
  const kindOf = new Map<number, Map<string, number>>();
  for (const e of g.endpoints) {
    const m = kindOf.get(e.router_id) ?? new Map<string, number>();
    m.set(e.kind, (m.get(e.kind) ?? 0) + 1);
    kindOf.set(e.router_id, m);
  }
  const degree = new Map<number, number>();
  const pairs = new Map<string, { a: number; b: number; width: number }>();
  const idOf = new Map<number, number>();
  g.routers.forEach((r, i) => idOf.set(r.router_id, i));
  for (const c of g.channels) {
    const a = idOf.get(c.src_router);
    const b = idOf.get(c.dst_router);
    if (a === undefined || b === undefined || a === b) continue;
    degree.set(a, (degree.get(a) ?? 0) + 1);
    degree.set(b, (degree.get(b) ?? 0) + 1);
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    const prev = pairs.get(key);
    if (!prev || c.width_bits > prev.width) {
      pairs.set(key, { a: Math.min(a, b), b: Math.max(a, b), width: c.width_bits });
    }
  }
  const grid = Math.max(1, Math.ceil(Math.sqrt(g.routers.length)));
  const nodes = g.routers.map((r, i) => {
    const idx = idOf.get(r.router_id) ?? i;
    const kinds = kindOf.get(r.router_id);
    let role = 'nic';
    let best = 0;
    for (const [k, n] of kinds ?? []) {
      if (KNOWN_ROLES.has(k) && n > best) { role = k; best = n; }
    }
    const x = r.coordinates.length > 1
      ? 100 + (r.coordinates[0] ?? 0) * 140
      : 100 + (idx % grid) * 140;
    const y = r.coordinates.length > 1
      ? 100 + (r.coordinates[1] ?? 0) * 140
      : 100 + Math.floor(idx / grid) * 140;
    return {
      id: `r${r.router_id}`, x, y, role,
      ports: Math.max(2, degree.get(idx) ?? 2),
      clock: null,
    };
  });
  let n = 0;
  const edges = [...pairs.values()].map((p) => ({
    id: `e${++n}`,
    src: `r${g.routers[p.a].router_id}`,
    dst: `r${g.routers[p.b].router_id}`,
    width: p.width, pipelineStages: 1, vcClass: 0,
  }));
  return {
    doc: {
      schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: `preset:${g.preset_id}`,
      nodes, edges,
    },
    refused: null,
  };
}

/** Trace address space for a graph: ids the playback layer may key on. */
export function traceScope(project: LoomProject): { nodes: string[]; edges: string[] } {
  return {
    nodes: project.nodes.map((n) => n.id),
    edges: project.edges.map((e) => e.id),
  };
}
