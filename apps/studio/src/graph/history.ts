/** Command log + undo/redo for the authoring graph (P0.5).
 * Snapshot-based, refusal-closed: a refused command never touches history. */
import type { GraphEdge, GraphNode, JsonValue, LoomProject } from './project';
import { validateProject } from './project';

export type GraphCommand =
  | { type: 'add_node'; node: GraphNode }
  | { type: 'move_node'; id: string; x: number; y: number }
  | { type: 'delete_node'; id: string }
  | { type: 'update_node'; id: string; patch: Partial<GraphNode> }
  | { type: 'add_edge'; edge: GraphEdge }
  | { type: 'delete_edge'; id: string }
  | { type: 'update_edge'; id: string; patch: Partial<GraphEdge> }
  | { type: 'paste'; nodes: GraphNode[]; edges: GraphEdge[] }
  | { type: 'set_workload'; workload: { [key: string]: JsonValue } | undefined }
  | { type: 'set_firewall'; firewall: { [key: string]: JsonValue } | undefined };

export interface GraphOutcome {
  doc: LoomProject;
  refused: string | null;
}

const clone = (doc: LoomProject): LoomProject => JSON.parse(JSON.stringify(doc)) as LoomProject;

export function applyGraphCommand(doc: LoomProject, cmd: GraphCommand): GraphOutcome {
  const next = clone(doc);
  const refuse = (why: string): GraphOutcome => ({ doc, refused: why });
  switch (cmd.type) {
    case 'add_node': {
      if (next.nodes.some((n) => n.id === cmd.node.id)) return refuse(`duplicate node id ${cmd.node.id}`);
      next.nodes.push(cmd.node);
      next.presetHint = null;
      break;
    }
    case 'move_node': {
      const n = next.nodes.find((x) => x.id === cmd.id);
      if (!n) return refuse(`unknown node ${cmd.id}`);
      n.x = cmd.x; n.y = cmd.y;
      break;
    }
    case 'delete_node': {
      if (!next.nodes.some((n) => n.id === cmd.id)) return refuse(`unknown node ${cmd.id}`);
      next.nodes = next.nodes.filter((n) => n.id !== cmd.id);
      next.edges = next.edges.filter((e) => e.src !== cmd.id && e.dst !== cmd.id);
      next.presetHint = null;
      break;
    }
    case 'update_node': {
      const n = next.nodes.find((x) => x.id === cmd.id);
      if (!n) return refuse(`unknown node ${cmd.id}`);
      Object.assign(n, cmd.patch, { id: n.id });
      next.presetHint = null;
      break;
    }
    case 'add_edge': {
      if (next.edges.some((e) => e.id === cmd.edge.id)) return refuse(`duplicate edge id ${cmd.edge.id}`);
      if (!next.nodes.some((n) => n.id === cmd.edge.src)) return refuse(`unknown node ${cmd.edge.src}`);
      if (!next.nodes.some((n) => n.id === cmd.edge.dst)) return refuse(`unknown node ${cmd.edge.dst}`);
      next.edges.push(cmd.edge);
      next.presetHint = null;
      break;
    }
    case 'delete_edge': {
      if (!next.edges.some((e) => e.id === cmd.id)) return refuse(`unknown edge ${cmd.id}`);
      next.edges = next.edges.filter((e) => e.id !== cmd.id);
      next.presetHint = null;
      break;
    }
    case 'update_edge': {
      const e = next.edges.find((x) => x.id === cmd.id);
      if (!e) return refuse(`unknown edge ${cmd.id}`);
      Object.assign(e, cmd.patch, { id: e.id });
      next.presetHint = null;
      break;
    }
    case 'paste': {
      const ids = new Set(next.nodes.map((n) => n.id));
      for (const n of cmd.nodes) if (ids.has(n.id)) return refuse(`duplicate node id ${n.id}`);
      next.nodes.push(...cmd.nodes);
      next.edges.push(...cmd.edges);
      next.presetHint = null;
      break;
    }
    case 'set_workload': {
      if (cmd.workload === undefined) delete next.workload;
      else next.workload = cmd.workload;
      break;
    }
    case 'set_firewall': {
      if (cmd.firewall === undefined) delete next.firewall;
      else next.firewall = cmd.firewall;
      break;
    }
  }
  const issues = validateProject(next);
  if (issues.length) return refuse(issues.map((i) => `${i.path}: ${i.message}`).join('; '));
  return { doc: next, refused: null };
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
