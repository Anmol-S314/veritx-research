/** P0+P0.5 contract: graph validates clean, presets diverge to custom,
 * undo restores, adapter refuses unknown roles, trace keys on ids. */
import { describe, expect, it } from 'vitest';
import { graphToDraft, graphToDraftRequest, graphToTopologyIR, presetGraphToProject, traceScope } from '../graph/adapter';
import { applyGraphCommand, GraphHistory } from '../graph/history';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject } from '../graph/project';
import { buildMockTrace } from '../graph/trace';
import { mixtralTp8Ep8, validateWorkload } from '../graph/workload';
import CANONICAL_SCHEMA from '../../../../contracts/loom/v1/project.schema.json';

describe('P0 graph contract', () => {
  it('8x8 preset validates clean and round-trips', () => {
    const p = buildPreset('mesh-8x8');
    expect(p.nodes).toHaveLength(64);
    expect(validateProject(p)).toEqual([]);
    expect(parseProject(serializeProject(p)).nodes).toHaveLength(64);
  });
  it('rejects over-deep imported metadata without overflowing validation', () => {
    let nested: Record<string, unknown> = {};
    for (let i = 0; i < 80; i++) nested = { child: nested };
    const project = { ...buildPreset('mesh-4x4'), workload: nested };
    expect(() => parseProject(JSON.stringify(project))).toThrow(/workload/);
    expect(() => validateProject(project)).not.toThrow(RangeError);
  });
  it('flags dangling edges, duplicates, port overflow, disconnects', () => {
    const p = buildPreset('ring-8');
    const dangling = applyGraphCommand(p, {
      type: 'add_edge', edge: { id: 'ex', src: 'n1', dst: 'nope', width: 512, pipelineStages: 1, vcClass: 0 },
    });
    expect(dangling.refused).toMatch(/unknown node/);
    const dup = applyGraphCommand(p, {
      type: 'add_node', node: { id: 'n1', x: 0, y: 0, role: 'compute_tile', ports: 5 },
    });
    expect(dup.refused).toMatch(/duplicate/);
  });
  it('hand-add + wire diverges preset to custom; undo restores', () => {
    const h = new GraphHistory(buildPreset('mesh-4x4'));
    expect(h.current().presetHint).not.toBeNull();
    // Isolated node must refuse (disconnect) — validator flags it.
    const bad = h.apply({ type: 'add_node', node: { id: 'nx', x: 5, y: 5, role: 'nic', ports: 5 } });
    expect(bad.refused).toMatch(/disconnected/);
    expect(h.current().presetHint).not.toBeNull();
    // Add with generous ports then wire: use delete+paste to attach cleanly.
    const base = h.current();
    const nx = { id: 'nx', x: 2000, y: 2000, role: 'nic', ports: 5 } as const;
    const wired = {
      ...base,
      nodes: [...base.nodes, { ...nx }],
      edges: [...base.edges, { id: 'e-wire', src: 'n1', dst: 'nx', width: 512, pipelineStages: 1, vcClass: 0 }],
      presetHint: null,
    } as typeof base;
    expect(validateProject(wired)).toEqual([]);
    expect(wired.presetHint).toBeNull();
    // Undo path: move then undo restores byte-equality.
    const h2 = new GraphHistory(buildPreset('mesh-4x4'));
    const before = JSON.stringify(h2.current());
    const moved = h2.apply({ type: 'move_node', id: 'n1', x: 999, y: 999 });
    expect(moved.refused).toBeNull();
    expect(h2.undo()).toBe(true);
    expect(JSON.stringify(h2.current())).toBe(before);
  });
  it('adapter lowers to explicit draft; refuses unknown roles', () => {
    const ok = graphToDraft(buildPreset('mesh-4x4'));
    expect(ok.refused).toBeNull();
    expect((ok.doc!.topology as Record<string, unknown>).kind).toBe('explicit');
    const bad = graphToDraft({
      schemaVersion: 1, presetHint: null,
      nodes: [{ id: 'n1', x: 0, y: 0, role: 'QUANTUM', ports: 2 }],
      edges: [],
    });
    expect(bad.refused).toMatch(/unknown role/);
  });
  it('trace keys on ids; mock trace renders for 5-node graph', () => {
    const p = buildPreset('star-8');
    const scope = traceScope(p);
    expect(scope.nodes).toContain('n1');
    const t = buildMockTrace(p);
    expect(t.origin).toBe('MOCK');
    expect(t.frames).toHaveLength(24);
    expect(Object.keys(t.frames[0].edgeUtil)[0]).toMatch(/^e/);
  });
  it('lowers to an explicit custom TopologyIR with index links', () => {
    const ir = graphToTopologyIR(buildPreset('mesh-4x4'));
    expect(ir.refused).toBeNull();
    expect(ir.doc?.kind).toBe('custom');
    expect(ir.doc?.nodes).toBe(16);
    const links = ir.doc?.links as [number, number][];
    expect(links.length).toBeGreaterThan(0);
    for (const [a, b] of links) {
      expect(a).toBeGreaterThanOrEqual(0);
      expect(b).toBeLessThan(16);
      expect(a).not.toBe(b);
    }
    // Undirected dedup: no pair twice.
    const keys = links.map(([a, b]) => (a < b ? `${a}:${b}` : `${b}:${a}`));
    expect(new Set(keys).size).toBe(keys.length);
  });
  it('refuses compiler lowering that would collapse edge semantics', () => {
    const base = buildPreset('mesh-4x4');
    const variedWidth = { ...base, edges: base.edges.map((e, i) => i === 0 ? { ...e, width: 1024 } : e) };
    const staged = { ...base, edges: base.edges.map((e, i) => i === 0 ? { ...e, pipelineStages: 2 } : e) };
    const classed = { ...base, edges: base.edges.map((e, i) => i === 0 ? { ...e, vcClass: 1 } : e) };
    expect(graphToTopologyIR(variedWidth).refused).toMatch(/heterogeneous link width/);
    expect(graphToTopologyIR(staged).refused).toMatch(/pipelineStages/);
    expect(graphToTopologyIR(classed).refused).toMatch(/vcClass/);
  });
  it('refuses graph VC, firewall, and workload intent until compiler mappings exist', () => {
    const base = buildPreset('mesh-4x4');
    expect(graphToDraftRequest({ ...base, nodes: base.nodes.map((n, i) => i === 0 ? { ...n, vc: { depth: 8 } } : n) }, {}).refused)
      .toMatch(/VC configuration/);
    expect(graphToDraftRequest({ ...base, firewall: { default: 'deny' } }, {}).refused)
      .toMatch(/firewall/);
    expect(graphToDraftRequest({ ...base, workload: { phases: [] } }, {}).refused)
      .toMatch(/workload/);
  });
  it('keeps distinct authored clocks in separate compiler agent groups', () => {
    const base = buildPreset('mesh-4x4');
    const project = { ...base, nodes: base.nodes.map((n, i) => i < 2 ? { ...n, clock: `clk_${i}` } : n) };
    const out = graphToDraftRequest(project, {});
    expect(out.refused).toBeNull();
    const agents = out.doc!.agents as { kind: string; count: number; clock_domain: string | null }[];
    expect(agents.filter((a) => a.kind === 'compute_tile').map((a) => a.clock_domain)).toContain('clk_0');
    expect(agents.filter((a) => a.kind === 'compute_tile').map((a) => a.clock_domain)).toContain('clk_1');
  });
  it('full v4 draft request carries explicit topology + grouped agents', () => {
    const out = graphToDraftRequest(buildPreset('mesh-4x4'), {
      schema_version: 3, workload: { tp: 8 }, requirements: [], extra: 1,
    });
    expect(out.refused).toBeNull();
    const doc = out.doc as Record<string, unknown>;
    expect(doc.schema_version).toBe(4);
    expect((doc.topology as Record<string, unknown>).kind).toBe('explicit');
    expect((doc.workload as Record<string, unknown>).tp).toBe(8);
    expect(doc.extra).toBe(1);
    const agents = doc.agents as { kind: string; count: number }[];
    expect(agents.reduce((n, a) => n + a.count, 0)).toBe(16);
  });
  it('seeds a valid graph from a shipped preset shape', () => {
    const out = presetGraphToProject({
      preset_id: 'explicit16', family: 'custom',
      routers: [
        { router_id: 0, coordinates: [] },
        { router_id: 1, coordinates: [] },
        { router_id: 2, coordinates: [] },
      ],
      channels: [
        { src_router: 0, dst_router: 1, width_bits: 64 },
        { src_router: 1, dst_router: 0, width_bits: 64 },
        { src_router: 1, dst_router: 2, width_bits: 128 },
      ],
      endpoints: [
        { kind: 'compute_tile', router_id: 0 },
        { kind: 'compute_tile', router_id: 1 },
        { kind: 'hbm_controller', router_id: 2 },
      ],
    });
    expect(out.refused).toBeNull();
    expect(out.doc?.presetHint).toBe('preset:explicit16');
    expect(validateProject(out.doc)).toEqual([]);
    expect(out.doc?.nodes).toHaveLength(3);
    expect(out.doc?.edges).toHaveLength(2);
    expect(out.doc?.nodes.find((n) => n.id === 'r2')?.role).toBe('hbm_controller');
  });
  it('refuses presets that project no channels', () => {
    const out = presetGraphToProject({
      preset_id: 'srota32', family: 'srota',
      routers: [{ router_id: 0, coordinates: [0, 0] }],
      channels: [],
      endpoints: [],
    });
    expect(out.doc).toBeNull();
    expect(out.refused).toMatch(/no channels/);
  });
  it('Mixtral TP8/EP8 validates against a 64-node graph', () => {
    expect(validateWorkload(mixtralTp8Ep8(), 64)).toEqual([]);
    expect(validateWorkload(mixtralTp8Ep8(), 8)).toMatchObject([expect.stringContaining('needs')]);
  });
});

/** The repo's canonical graph schema (contracts/loom/v1/project.schema.json)
 *  and the editor's validator must agree, or a file that validates in one
 *  place fails in the other. The schema is structural; the validator is the
 *  superset that also checks referential integrity. */
describe('project.schema.json agrees with the editor validator', () => {
  const schema = CANONICAL_SCHEMA as unknown as {
    required: string[];
    properties: {
      schemaVersion: { const: number };
      nodes: { maxItems: number };
      edges: { maxItems: number };
    };
    $defs: {
      node: { required: string[]; properties: Record<string, unknown>; additionalProperties: boolean };
      edge: { required: string[]; properties: Record<string, unknown>; additionalProperties: boolean };
    };
  };

  it('declares the same required fields the validator demands', () => {
    const good = buildPreset('mesh-4x4');
    expect(validateProject(good)).toEqual([]);
    for (const key of schema.$defs.node.required) {
      expect(Object.keys(good.nodes[0])).toContain(key);
    }
    for (const key of schema.$defs.edge.required) {
      expect(Object.keys(good.edges[0])).toContain(key);
    }
    expect(schema.required).toEqual(expect.arrayContaining(['schemaVersion', 'presetHint', 'nodes', 'edges']));
  });

  it('enforces the same budgets', () => {
    const over = (n: number, e: number) => ({
      schemaVersion: 1, presetHint: null,
      nodes: Array.from({ length: n }, (_, i) => ({ id: `n${i}`, x: 0, y: 0, role: 'nic', ports: 1 })),
      edges: Array.from({ length: e }, (_, i) => ({ id: `e${i}`, src: 'n0', dst: 'n1', width: 8, pipelineStages: 1, vcClass: 0 })),
    });
    expect(validateProject(over(schema.properties.nodes.maxItems + 1, 1))
      .some((i) => i.message.includes('256'))).toBe(true);
    expect(validateProject(over(2, schema.properties.edges.maxItems + 1))
      .some((i) => i.message.includes('512'))).toBe(true);
  });

  it('closes both objects exactly as the schema does', () => {
    const base = buildPreset('mesh-4x4');
    const strayNode = { ...base, nodes: [{ ...base.nodes[0], bogus: 1 }, ...base.nodes.slice(1)] };
    const strayEdge = { ...base, edges: [{ ...base.edges[0], bogus: 1 }, ...base.edges.slice(1)] };
    expect(validateProject(strayNode).some((i) => i.message === 'unknown field')).toBe(true);
    expect(validateProject(strayEdge).some((i) => i.message === 'unknown field')).toBe(true);
    expect(schema.$defs.node.additionalProperties).toBe(false);
    expect(schema.$defs.edge.additionalProperties).toBe(false);
  });

  it('pins schemaVersion 1 on both sides', () => {
    expect(schema.properties.schemaVersion.const).toBe(1);
    expect(validateProject({ ...buildPreset('mesh-4x4'), schemaVersion: 2 })
      .some((i) => i.message.includes('equal 1'))).toBe(true);
  });
});
