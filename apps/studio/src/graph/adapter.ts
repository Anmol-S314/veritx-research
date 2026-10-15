/** Local graph → canonical V4/V5 topology adapter.
 *
 * Apply only the explicit router/link topology. Preserve the canonical draft's
 * agents, interfaces, controls, address map, and V5 extensions byte-for-byte;
 * graph node roles/coordinates remain editor annotations, not endpoint bindings
 * or physical placement claims.
 */
import { errorIssues, validateProject, type LoomProject } from './project';

// Accepted editor labels. They remain annotations; draft agent groups are
// preserved rather than inferred from per-router labels.
const KNOWN_ROLES = new Set([
  'compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU',
]);

export interface AdaptOutcome {
  doc: Record<string, unknown> | null;
  refused: string | null;
}

function unsupportedGraphIntent(project: LoomProject): string | null {
  if (project.firewall !== undefined) return 'graph firewall intent is not materialized by the compiler adapter';
  if (project.workload !== undefined) return 'graph workload phases are not materialized by the compiler adapter';
  if (project.nodes.some((n) => n.vc && Object.keys(n.vc).length > 0)) {
    return 'per-node VC configuration is not materialized by the compiler adapter';
  }
  return null;
}


/** Lower only edge semantics representable by the compiler's global link attributes. */
export function graphToTopologyIR(project: LoomProject): {
  doc: Record<string, unknown> | null;
  refused: string | null;
  linkWidthBits: number;
} {
  const index = new Map(project.nodes.map((n, i) => [n.id, i]));
  const seen = new Set<string>();
  const links: [number, number][] = [];
  for (const e of project.edges) {
    const a = index.get(e.src);
    const b = index.get(e.dst);
    if (a === undefined || b === undefined) {
      return { doc: null, refused: `edge ${e.id} names a node outside the graph`, linkWidthBits: 0 };
    }
    if (a === b) continue;
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    if (seen.has(key)) continue;
    seen.add(key);
    links.push([a, b]);
  }
  if (project.nodes.length === 0) {
    return { doc: null, refused: 'the graph has no nodes', linkWidthBits: 0 };
  }
  if (project.edges.some((e) => e.pipelineStages !== 1)) {
    return { doc: null, refused: 'per-edge pipelineStages are not materialized by the compiler adapter', linkWidthBits: 0 };
  }
  if (project.edges.some((e) => e.vcClass !== 0)) {
    return { doc: null, refused: 'non-default edge vcClass is not materialized by the compiler adapter', linkWidthBits: 0 };
  }
  const widths = new Set(project.edges.map((e) => e.width));
  if (widths.size > 1) {
    return { doc: null, refused: 'heterogeneous link width is not representable by global compiler link attributes', linkWidthBits: 0 };
  }
  const linkWidthBits = widths.values().next().value ?? 512;
  const intentRefusal = unsupportedGraphIntent(project);
  if (intentRefusal) return { doc: null, refused: intentRefusal, linkWidthBits: 0 };
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
  };
}

/** Return projection-only graph errors before the generic draft refusal. */
function graphProjectionProblem(project: LoomProject): string | null {
  for (const node of project.nodes) {
    if (!KNOWN_ROLES.has(node.role)) {
      return `node ${node.id} carries unknown role ${node.role}`;
    }
  }
  // Compile/run require a single component. The editor holds a disconnected
  // document as a warning; the compiler escalates it to a refusal here.
  const issues = errorIssues(validateProject(project, { requireConnected: true }));
  if (issues.length) return issues.map((i) => `${i.path}: ${i.message}`).join('; ');
  return graphToTopologyIR(project).refused;
}

function graphApplyRefusal(base?: Record<string, unknown>): string {
  const schema = base?.schema_version;
  const root = schema === 5 ? 'the V5 draft root' : schema === 4
    ? 'the V4 draft' : 'the project draft';
  return `Cannot apply this local graph to ${root}: a canonical V4/V5 draft is required so existing agent, interface, control, address-map, and V5 intent can be preserved. No draft was changed.`;
}

/** Replace only the topology in a canonical V4 draft or a V5 draft's base_v4.
 * All other authored fields remain intact; the local graph does not claim to
 * author endpoint bindings, node roles, or physical placement. */
export function graphToDraftRequest(
  project: LoomProject,
  base: Record<string, unknown>,
): AdaptOutcome {
  const problem = graphProjectionProblem(project);
  if (problem) return { doc: null, refused: problem };
  const topology = graphToTopologyIR(project);
  if (!topology.doc) return { doc: null, refused: topology.refused };

  if (base.schema_version === 4) {
    return {
      doc: { ...base, topology: { kind: 'explicit', graph: topology.doc } },
      refused: null,
    };
  }
  if (base.schema_version === 5 && base.base_v4 !== null
      && typeof base.base_v4 === 'object' && !Array.isArray(base.base_v4)) {
    const baseV4 = base.base_v4 as Record<string, unknown>;
    if (baseV4.schema_version !== 4) {
      return { doc: null, refused: 'V5 draft does not contain a canonical V4 base.' };
    }
    return {
      doc: { ...base, base_v4: {
        ...baseV4, topology: { kind: 'explicit', graph: topology.doc },
      } },
      refused: null,
    };
  }
  return { doc: null, refused: graphApplyRefusal(base) };
}

/** A canonical draft is required to preserve non-topology design intent. */
export function graphToDraft(project: LoomProject): AdaptOutcome {
  const problem = graphProjectionProblem(project);
  if (problem) return { doc: null, refused: problem };
  return { doc: null, refused: 'A canonical V4/V5 draft is required to apply this topology.' };
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
      schemaVersion: 1, presetHint: `preset:${g.preset_id}`,
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
