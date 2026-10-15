/** Command log + undo/redo for the authoring graph (P0.5).
 *  Snapshot-based, refusal-closed: a refused command never touches history. */
import type { FloorplanIntent, GraphEdge, GraphNode, JsonValue, LoomProject, RoutingConfig } from './project';
import { errorIssues, makeIssue, validateProject, type ProjectIssue } from './project';

export type GraphCommand =
  | { type: 'add_node'; node: GraphNode }
  | { type: 'move_node'; id: string; x: number; y: number; fromX?: number; fromY?: number }
  | { type: 'delete_node'; id: string; node?: GraphNode; edges?: GraphEdge[] }
  | { type: 'delete_nodes'; ids: string[] }
  | { type: 'update_node'; id: string; patch: Partial<GraphNode>; previous?: Partial<GraphNode> }
  | { type: 'update_nodes'; updates: Array<{ id: string; patch: Partial<GraphNode> }> }
  | { type: 'add_edge'; edge: GraphEdge }
  | { type: 'delete_edge'; id: string; edge?: GraphEdge }
  | { type: 'update_edge'; id: string; patch: Partial<GraphEdge>; previous?: Partial<GraphEdge> }
  | { type: 'paste'; nodes: GraphNode[]; edges: GraphEdge[]; idMap?: Record<string, string> }
  | { type: 'paste_remapped'; nodes: GraphNode[]; edges: GraphEdge[]; idMap: Record<string, string> }
  | { type: 'batch'; commands: GraphCommand[] }
  | { type: 'replace_project'; doc: LoomProject }
  | { type: 'load_project'; project: LoomProject }
  | { type: 'set_routing'; routing: RoutingConfig | undefined }
  | { type: 'set_floorplan'; floorplan: FloorplanIntent | undefined }
  | { type: 'set_workload'; workload: { [key: string]: JsonValue } | undefined; previous?: { [key: string]: JsonValue } | undefined }
  | { type: 'set_firewall'; firewall: { [key: string]: JsonValue } | undefined; previous?: { [key: string]: JsonValue } | undefined }
  /** Exact inverse of any command: restore the whole pre-state document.
   *  Commands that null `presetHint`, reorder arrays, or replace a top-level
   *  field cannot be inverted field-by-field without losing that state, so
   *  revert is expressed as the bytes to restore (same mechanism the snapshot
   *  history uses). */
  | { type: 'revert'; doc: LoomProject };

export interface GraphOutcome {
  doc: LoomProject;
  refused: string | null;
  inverse?: GraphCommand | null;
  /** Canonical machine-readable findings for the refusal (empty on success). */
  issues: ProjectIssue[];
}

export interface DeleteDependencyPreview {
  nodeIds: string[];
  affectedEdges: GraphEdge[];
  missingNodeIds: string[];
}

/** Read-only dependency preview for a node deletion confirmation surface. */
export function previewDeleteNodes(doc: LoomProject, nodeIds: Iterable<string>): DeleteDependencyPreview {
  const requested = [...new Set(nodeIds)];
  const known = new Set(doc.nodes.map((node) => node.id));
  const deleting = new Set(requested.filter((id) => known.has(id)));
  return {
    nodeIds: [...deleting],
    missingNodeIds: requested.filter((id) => !known.has(id)),
    affectedEdges: doc.edges.filter((edge) => deleting.has(edge.src) || deleting.has(edge.dst))
      .map((edge) => JSON.parse(JSON.stringify(edge)) as GraphEdge),
  };
}

const clone = (doc: LoomProject): LoomProject => JSON.parse(JSON.stringify(doc)) as LoomProject;

const refuseIssue = (path: string, message: string): ProjectIssue =>
  makeIssue({ path, message, code: 'LOOM_GRAPH_COMMAND_INVALID', objectRef: path });

/** The JSON pointer a refusal should link to, derived from the command kind. */
function refusalPath(cmd: GraphCommand): string {
  switch (cmd.type) {
    case 'add_node':
    case 'move_node':
    case 'delete_node':
    case 'delete_nodes':
    case 'update_node':
    case 'update_nodes':
      return '$.nodes';
    case 'add_edge':
    case 'delete_edge':
    case 'update_edge':
      return '$.edges';
    case 'paste':
    case 'paste_remapped':
    case 'batch':
      return '$.nodes';
    default:
      return '$';
  }
}

function replaceDocument(next: LoomProject, replacement: LoomProject): void {
  const restored = clone(replacement);
  next.schemaVersion = restored.schemaVersion;
  next.compilerSemanticsVersion = restored.compilerSemanticsVersion;
  next.presetHint = restored.presetHint;
  next.nodes = restored.nodes;
  next.edges = restored.edges;
  if (restored.routing === undefined) delete next.routing;
  else next.routing = restored.routing;
  if (restored.floorplan === undefined) delete next.floorplan;
  else next.floorplan = restored.floorplan;
  if (restored.firewall === undefined) delete next.firewall;
  else next.firewall = restored.firewall;
  if (restored.access === undefined) delete next.access;
  else next.access = restored.access;
  if (restored.metadata === undefined) delete next.metadata;
  else next.metadata = restored.metadata;
  if (restored.workload === undefined) delete next.workload;
  else next.workload = restored.workload;
  if (restored.vcConfig === undefined) delete next.vcConfig;
  else next.vcConfig = restored.vcConfig;
  if (restored.domains === undefined) delete next.domains;
  else next.domains = restored.domains;
  if (restored.agents === undefined) delete next.agents;
  else next.agents = restored.agents;
}

/** Apply one command to `next` in place. Returns a refusal reason or null.
 *  This is the mutation half of `applyGraphCommand`; it validates its own
 *  preconditions but not the whole-document invariants. Callers that group
 *  commands (batch) validate only the final document, so intermediate states
 *  — a node added before its incident edge, a component mid-delete — are
 *  allowed as long as the end state is legal. */
function mutate(next: LoomProject, cmd: GraphCommand): string | null {
  const refuse = (why: string): string => why;
  switch (cmd.type) {
    case 'add_node': {
      if (next.nodes.some((n) => n.id === cmd.node.id)) return refuse(`duplicate node id ${cmd.node.id}`);
      next.nodes.push(cmd.node);
      next.presetHint = null;
      return null;
    }
    case 'move_node': {
      const n = next.nodes.find((x) => x.id === cmd.id);
      if (!n) return refuse(`unknown node ${cmd.id}`);
      n.x = cmd.x; n.y = cmd.y;
      return null;
    }
    case 'delete_node': {
      const node = next.nodes.find((n) => n.id === cmd.id);
      if (!node) return refuse(`unknown node ${cmd.id}`);
      next.nodes = next.nodes.filter((n) => n.id !== cmd.id);
      next.edges = next.edges.filter((e) => e.src !== cmd.id && e.dst !== cmd.id);
      next.presetHint = null;
      return null;
    }
    case 'delete_nodes': {
      const ids = new Set(cmd.ids);
      if (ids.size === 0) return refuse('no nodes selected for deletion');
      const missing = [...ids].filter((id) => !next.nodes.some((node) => node.id === id));
      if (missing.length) return refuse(`unknown node ${missing.join(', ')}`);
      next.nodes = next.nodes.filter((node) => !ids.has(node.id));
      next.edges = next.edges.filter((edge) => !ids.has(edge.src) && !ids.has(edge.dst));
      next.presetHint = null;
      return null;
    }
    case 'update_node': {
      const n = next.nodes.find((x) => x.id === cmd.id);
      if (!n) return refuse(`unknown node ${cmd.id}`);
      Object.assign(n, cmd.patch, { id: n.id });
      next.presetHint = null;
      return null;
    }
    case 'update_nodes': {
      if (cmd.updates.length === 0) return refuse('no nodes selected for batch update');
      const ids = new Set<string>();
      for (const update of cmd.updates) {
        if (ids.has(update.id)) return refuse(`duplicate node in batch update ${update.id}`);
        ids.add(update.id);
        if (!next.nodes.some((node) => node.id === update.id)) return refuse(`unknown node ${update.id}`);
      }
      for (const update of cmd.updates) {
        const node = next.nodes.find((item) => item.id === update.id)!;
        Object.assign(node, update.patch, { id: node.id });
      }
      next.presetHint = null;
      return null;
    }
    case 'add_edge': {
      if (next.edges.some((e) => e.id === cmd.edge.id)) return refuse(`duplicate edge id ${cmd.edge.id}`);
      if (!next.nodes.some((n) => n.id === cmd.edge.src)) return refuse(`unknown node ${cmd.edge.src}`);
      if (!next.nodes.some((n) => n.id === cmd.edge.dst)) return refuse(`unknown node ${cmd.edge.dst}`);
      next.edges.push(cmd.edge);
      next.presetHint = null;
      return null;
    }
    case 'delete_edge': {
      if (!next.edges.some((e) => e.id === cmd.id)) return refuse(`unknown edge ${cmd.id}`);
      next.edges = next.edges.filter((e) => e.id !== cmd.id);
      next.presetHint = null;
      return null;
    }
    case 'update_edge': {
      const e = next.edges.find((x) => x.id === cmd.id);
      if (!e) return refuse(`unknown edge ${cmd.id}`);
      Object.assign(e, cmd.patch, { id: e.id });
      next.presetHint = null;
      return null;
    }
    case 'paste':
    case 'paste_remapped': {
      const ids = new Set(next.nodes.map((n) => n.id));
      let nodes = cmd.nodes;
      let edges = cmd.edges;
      if (cmd.idMap) {
        const map = cmd.idMap;
        nodes = nodes.map((n) => ({ ...n, id: map[n.id] ?? n.id }));
        edges = edges.map((e) => ({
          ...e,
          id: map[e.id] ?? e.id,
          src: map[e.src] ?? e.src,
          dst: map[e.dst] ?? e.dst,
        }));
      }
      for (const n of nodes) if (ids.has(n.id)) return refuse(`duplicate node id ${n.id}`);
      for (const e of edges) {
        if (next.edges.some((x) => x.id === e.id)) return refuse(`duplicate edge id ${e.id}`);
      }
      next.nodes.push(...nodes);
      next.edges.push(...edges);
      next.presetHint = null;
      return null;
    }
    case 'batch': {
      for (const c of cmd.commands) {
        const reason = mutate(next, c);
        if (reason) return refuse(reason);
      }
      return null;
    }
    case 'replace_project': {
      replaceDocument(next, cmd.doc);
      return null;
    }
    case 'load_project': {
      const errors = errorIssues(validateProject(cmd.project));
      if (errors.length) return refuse(errors.map((i) => `${i.path}: ${i.message}`).join('; '));
      replaceDocument(next, cmd.project);
      return null;
    }
    case 'set_routing': {
      if (cmd.routing === undefined) delete next.routing;
      else next.routing = cmd.routing;
      return null;
    }
    case 'set_floorplan': {
      if (cmd.floorplan === undefined) delete next.floorplan;
      else next.floorplan = cmd.floorplan;
      return null;
    }
    case 'set_workload': {
      if (cmd.workload === undefined) delete next.workload;
      else next.workload = cmd.workload;
      return null;
    }
    case 'set_firewall': {
      if (cmd.firewall === undefined) delete next.firewall;
      else next.firewall = cmd.firewall;
      return null;
    }
    case 'revert': {
      replaceDocument(next, cmd.doc);
      return null;
    }
  }
}

export function applyGraphCommand(doc: LoomProject, cmd: GraphCommand): GraphOutcome {
  const next = clone(doc);
  const reason = mutate(next, cmd);
  if (reason) return { doc, refused: reason, inverse: null, issues: [refuseIssue(refusalPath(cmd), reason)] };
  // Warnings (e.g. a disconnected document held mid-edit) are authoring-legal
  // and must not refuse a command; only structural errors do. Compile/run
  // escalate connectivity by validating with `requireConnected`.
  //
  // Workload editing may temporarily hold invalid draft values; the workload
  // panel reports them and serialization/run-intent validation still refuses
  // them. A non-object workload is still a structural error here.
  const workloadDraft = cmd.type === 'set_workload'
    && typeof cmd.workload === 'object' && cmd.workload !== null && !Array.isArray(cmd.workload);
  const errors = workloadDraft ? [] : errorIssues(validateProject(next));
  if (errors.length) {
    return { doc, refused: errors.map((i) => `${i.path}: ${i.message}`).join('; '), inverse: null, issues: errors };
  }
  // Revert is the exact pre-state; it restores derived fields (presetHint) and
  // array order that a field-by-field inverse would lose.
  return { doc: next, refused: null, inverse: { type: 'revert', doc: clone(doc) }, issues: [] };
}

export class GraphHistory {
  private past: LoomProject[] = [];
  private future: LoomProject[] = [];
  constructor(private doc: LoomProject) {}
  current(): LoomProject { return this.doc; }
  apply(cmd: GraphCommand): GraphOutcome {
    const out = applyGraphCommand(this.doc, cmd);
    if (out.refused === null) { this.past.push(this.doc); this.future = []; this.doc = out.doc; }
    return out;
  }
  canUndo(): boolean { return this.past.length > 0; }
  canRedo(): boolean { return this.future.length > 0; }
  undo(): boolean {
    const prev = this.past.pop();
    if (!prev) return false;
    this.future.push(this.doc); this.doc = prev; return true;
  }
  redo(): boolean {
    const nxt = this.future.pop();
    if (!nxt) return false;
    this.past.push(this.doc); this.doc = nxt; return true;
  }
  reset(doc: LoomProject): void { this.doc = doc; this.past = []; this.future = []; }
}
