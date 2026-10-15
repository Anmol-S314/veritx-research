/** P0+P0.5 contract: graph validates clean, presets diverge to custom,
 * undo restores, adapter refuses unknown roles, trace keys on ids. */
import { describe, expect, it } from 'vitest';
import { graphToDraft, graphToDraftRequest, graphToTopologyIR, presetGraphToProject, traceScope } from '../graph/adapter';
import { applyGraphCommand, GraphHistory } from '../graph/history';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject } from '../graph/project';
import { validateProjectDocument } from '../project/document';
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
    // An isolated node is authoring-legal (warning), so a paste/duplicate can
    // be held before it is wired in; compile escalates it to a refusal.
    const add = h.apply({ type: 'add_node', node: { id: 'nx', x: 2000, y: 2000, role: 'nic', ports: 5 } });
    expect(add.refused).toBeNull();
    const held = validateProject(h.current());
    expect(held.some((i) => i.code === 'graph.disconnected' && i.severity === 'warning')).toBe(true);
    expect(held.some((i) => i.severity === 'error')).toBe(false);
    expect(graphToDraftRequest(h.current(), { schema_version: 4 }).refused).toMatch(/disconnected/);
    h.undo();
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
  it('requires a canonical draft when applying a graph topology', () => {
    const out = graphToDraft(buildPreset('mesh-4x4'));
    expect(out.doc).toBeNull();
    expect(out.refused).toMatch(/canonical V4\/V5 draft is required/i);
    const bad = graphToDraft({
      schemaVersion: 1, presetHint: null,
      nodes: [{ id: 'n1', x: 0, y: 0, role: 'QUANTUM', ports: 2 }],
      edges: [],
    });
    expect(bad.doc).toBeNull();
    expect(bad.refused).toMatch(/unknown role QUANTUM/);
    const ring = buildPreset('ring-8');
    const npu = graphToDraftRequest({
      ...ring,
      nodes: ring.nodes.map((node, i) => i === 0 ? { ...node, role: 'NPU' } : node),
    }, { schema_version: 4 });
    expect(npu.doc?.topology).toMatchObject({ kind: 'explicit' });
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
  it('applies only the explicit topology while preserving V4 and V5 intent', () => {
    const project = buildPreset('mesh-4x4');
    const v4 = {
      schema_version: 4, compiler_semantics_version: 4,
      workload: { tp: 8 }, requirements: [],
      agents: [{ kind: 'compute_tile', count: 2, data_width: 128, addr_width: 40, protocol: 'CHI' }],
      topology: { kind: 'mesh', side_length: 2, concentration: 1 },
      noc_controls: { allocator_iterations: 3 },
      address_map: { ranges: [{ base: 4096, size: 4096, target_agent_idx: 0 }] },
    };
    const v4Before = JSON.stringify(v4);
    const v4Out = graphToDraftRequest(project, v4);
    expect(v4Out.refused).toBeNull();
    expect(v4Out.doc).toMatchObject({
      ...v4,
      topology: { kind: 'explicit', graph: { kind: 'custom', nodes: 16 } },
    });
    expect(v4Out.doc?.agents).toEqual(v4.agents);
    expect(v4Out.doc?.noc_controls).toEqual(v4.noc_controls);
    expect(v4Out.doc?.address_map).toEqual(v4.address_map);
    expect(JSON.stringify(v4)).toBe(v4Before);

    const v5 = {
      schema_version: 5, compiler_semantics_version: 5,
      base_v4: { ...v4 },
      agent_intents: [{ agent_group_index: 0, transaction_clock_domain: 'core' }],
      access_policy: { rules: [{ permission: 'DENY' }] },
      migration_provenance: { source: 'test' },
    };
    const v5Before = JSON.stringify(v5);
    const v5Out = graphToDraftRequest(project, v5);
    expect(v5Out.refused).toBeNull();
    expect(v5Out.doc?.base_v4).toMatchObject({
      ...v4,
      topology: { kind: 'explicit', graph: { kind: 'custom', nodes: 16 } },
    });
    expect(v5Out.doc?.agent_intents).toEqual(v5.agent_intents);
    expect(v5Out.doc?.access_policy).toEqual(v5.access_policy);
    expect(v5Out.doc?.migration_provenance).toEqual(v5.migration_provenance);
    expect(JSON.stringify(v5)).toBe(v5Before);
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
  it('retains an NPU role in a local preset projection without compiling it', () => {
    const out = presetGraphToProject({
      preset_id: 'local-npu', family: 'custom',
      routers: [{ router_id: 0, coordinates: [] }, { router_id: 1, coordinates: [] }],
      channels: [{ src_router: 0, dst_router: 1, width_bits: 64 }],
      endpoints: [{ kind: 'NPU', router_id: 0 }, { kind: 'hbm_controller', router_id: 1 }],
    });
    expect(out.doc?.nodes[0].role).toBe('NPU');
    expect(out.doc && graphToDraft(out.doc).doc).toBeNull();
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
    expect(validateWorkload(mixtralTp8Ep8(), 8).map((i) => i.message))
      .toMatchObject([expect.stringContaining('needs')]);
  });
});

/** M0-16: every validator returns the same canonical result shape. A caller can
 *  render any validator's output without special-casing which one produced it. */
describe('canonical validation result model', () => {
  const canonicalKeys = ['path', 'message', 'severity', 'code', 'objectRef'];
  const assertCanonical = (issues: { severity?: string; code?: string; message?: string; objectRef?: string }[]) => {
    for (const issue of issues) {
      for (const key of canonicalKeys) expect(issue).toHaveProperty(key);
      expect(['error', 'warning']).toContain(issue.severity);
      expect(typeof issue.code).toBe('string');
      expect((issue.code ?? '').length).toBeGreaterThan(0);
      expect(typeof issue.objectRef).toBe('string');
    }
  };

  it('graph, workload and document validators agree on the shape', () => {
    assertCanonical(validateProject({
      ...buildPreset('ring-8'),
      edges: [{ id: 'e', src: 'n1', dst: 'nope', width: 8, pipelineStages: 1, vcClass: 0 }],
    }));
    assertCanonical(validateWorkload(
      { ...mixtralTp8Ep8(), modelFamily: '', phases: [] }, 1));
    assertCanonical(validateProjectDocument({ bogus: true }));
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
