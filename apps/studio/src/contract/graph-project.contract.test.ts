/** P0+P0.5 contract: graph validates clean, presets diverge to custom,
 * undo restores, adapter refuses unknown roles, trace keys on ids. */
import { describe, expect, it } from 'vitest';
import { graphToDraft, graphToDraftRequest, graphToTopologyIR, presetGraphToProject, traceScope } from '../graph/adapter';
import { applyGraphCommand, GraphHistory } from '../graph/history';
import { allowAllFirewallRules, canonicalFirewall, inspectFirewallRules, setFirewallColumn, setFirewallRow } from '../graph/firewall';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, supportsXYRouting, validateProject } from '../graph/project';
import { buildMockTrace } from '../graph/trace';
import { convertFloorplanIntent, estimateManhattanRouteDelayPs, routeAllManhattanPhysicalEdges } from '../graph/floorplan';
import { previewConnectivityPath, previewCustomPath, previewOddEvenPath, previewWestFirstPath, previewXYPath, validateAllowedRouteReachability, validateWorkloadRoutingCompatibility } from '../graph/routing';
import { autoRankMappings, buildWorkloadRunIntent, mixtralTp8Ep8, moeWorkloadSkeleton, emptyWorkload, parseWorkloadJson, serializeWorkloadJson, validateWorkload, type WorkloadCommunication } from '../graph/workload';
import CANONICAL_SCHEMA from '../../../../contracts/loom/v1/project.schema.json';

describe('P0 graph contract', () => {
  it('validates workload traffic-class VC against authored point-to-point routes', () => {
    const project = buildPreset('mesh-4x4');
    project.routing = { policy: 'xy' };
    const routeEdge = project.edges.find((edge) => edge.src === 'n1' && edge.dst === 'n2')!;
    const otherEdge = project.edges.find((edge) => edge.id !== routeEdge.id)!;
    otherEdge.vcClass = 1;
    const workload = emptyWorkload();
    workload.communications = [{ id: 'p2p', kind: 'point-to-point', sourceNodeId: 'n1', targetNodeId: 'n2', dimension: 'tp', payloadBytes: 16, trafficClass: 'bulk' }];
    workload.trafficClassMappings = [{ trafficClass: 'bulk', vcClass: 1, qosClass: 'best-effort' }];
    expect(validateWorkloadRoutingCompatibility(project, workload)).toContain(
      `communications[0] (n1 → n2): traffic class bulk maps to VC 1, but edge ${routeEdge.id} uses VC 0`,
    );
    workload.trafficClassMappings[0]!.vcClass = 0;
    expect(validateWorkloadRoutingCompatibility(project, workload)).toEqual([]);
    project.routing = undefined;
    expect(validateWorkloadRoutingCompatibility(project, workload)[0]).toContain('no routing policy is selected');
  });
  it('routes XY dimension-order paths over canonical mesh adjacency and serializes the policy', () => {
    const project = buildPreset('mesh-4x4');
    project.routing = { policy: 'xy' };
    expect(supportsXYRouting(project)).toBe(true);
    expect(validateProject(project)).toEqual([]);
    expect(graphToTopologyIR(project)).toMatchObject({ doc: null, refused: expect.stringContaining('preview-only') });
    const preview = previewXYPath(project, 'n1', 'n16');
    expect(preview.error).toBeNull();
    expect(preview.route?.nodePath).toEqual(['n1', 'n2', 'n3', 'n4', 'n8', 'n12', 'n16']);
    expect(preview.route?.provenance).toBe('XY_MESH_DIMENSION_ORDER');
    expect(preview.route?.hops.every((hop) => project.edges.some((edge) => edge.id === hop.edgeId))).toBe(true);
    const portEdge = project.edges[0]!;
    portEdge.srcPort = 2; portEdge.dstPort = 3;
    const forwardPorts = previewXYPath(project, portEdge.src, portEdge.dst).route?.hops[0];
    expect(forwardPorts).toMatchObject({ srcPort: 2, dstPort: 3 });
    const reversePorts = previewXYPath(project, portEdge.dst, portEdge.src).route?.hops[0];
    expect(reversePorts).toMatchObject({ srcPort: 3, dstPort: 2 });
    const portOnly = { ...project, routing: undefined };
    expect(graphToTopologyIR(portOnly).refused).toContain('authored edge port assignments are not materialized by the compiler adapter');
    const adjacent = project.edges.find((edge) => edge.id !== portEdge.id && (edge.src === portEdge.src || edge.dst === portEdge.src))!;
    if (adjacent.src === portEdge.src) adjacent.srcPort = 2;
    else adjacent.dstPort = 2;
    expect(validateProject(project).some((issue) => issue.message.includes('already assigned to edge'))).toBe(true);
    if (adjacent.src === portEdge.src) delete adjacent.srcPort;
    else delete adjacent.dstPort;
    expect(validateProject(project)).toEqual([]);
    const reopened = parseProject(serializeProject(project));
    expect(reopened.routing).toEqual({ policy: 'xy' });
    expect(previewXYPath(project, 'n1', 'n1').route?.hops).toEqual([]);
  });
  it('previews West-First routes with westward hops before vertical turns and refuses unsupported shapes', () => {
    const project = buildPreset('mesh-4x4');
    project.routing = { policy: 'west_first' };
    expect(validateProject(project)).toEqual([]);
    expect(graphToTopologyIR(project).refused).toContain('graph west_first routing policy is preview-only and is not materialized by the compiler adapter');
    const route = previewWestFirstPath(project, 'n4', 'n9');
    expect(route.route?.nodePath).toEqual(['n4', 'n3', 'n2', 'n1', 'n5', 'n9']);
    expect(route.route?.provenance).toBe('WEST_FIRST_MESH_ORDER');
    expect(route.route?.hops.every((hop) => project.edges.some((edge) => edge.id === hop.edgeId))).toBe(true);
    const ring = buildPreset('ring-8');
    ring.routing = { policy: 'west_first' };
    expect(validateProject(ring).some((issue) => issue.message.includes('canonical 4×4 or 8×8 mesh'))).toBe(true);
  });
  it('validates explicit floorplan units and positive die bounds', () => {
    const project = buildPreset('mesh-4x4');
    project.floorplan = { unit: 'mm', die: { originX: -1.5, originY: 0, width: 10, height: 8 } };
    expect(validateProject(project)).toEqual([]);
    project.floorplan.gridStep = 0.5;
    project.floorplan.delayModel = { wireDelayPsPerUnit: 2.5, fixedDelayPs: 3 };
    project.floorplan.placements = [{ nodeId: 'n1', x: 1, y: 2, width: 1, height: 1 }];
    expect(convertFloorplanIntent(project.floorplan, 'um')).toEqual({ unit: 'um', gridStep: 500, delayModel: { wireDelayPsPerUnit: 0.0025, fixedDelayPs: 3 },
      die: { originX: -1500, originY: 0, width: 10000, height: 8000 },
      placements: [{ nodeId: 'n1', x: 1000, y: 2000, width: 1000, height: 1000 }] });
    project.floorplan.placements = undefined;
    project.floorplan.gridStep = undefined;
    const die = project.floorplan.die!;
    die.width = 0;
    expect(validateProject(project)).toContainEqual({ path: '$.floorplan.die.width', message: 'must be positive' });
    die.width = 10;
    project.floorplan.unit = 'inch' as 'mm';
    expect(validateProject(project)).toContainEqual({ path: '$.floorplan.unit', message: 'must be um or mm' });
  });
  it('validates and estimates delay only from explicit authored formula inputs', () => {
    const project = buildPreset('mesh-4x4');
    project.floorplan = { unit: 'mm', die: { originX: 0, originY: 0, width: 20, height: 10 },
      placements: [{ nodeId: 'n1', x: 1, y: 1, width: 2, height: 2 }, { nodeId: 'n2', x: 7, y: 5, width: 2, height: 2 }] };
    expect(validateProject(project)).toEqual([]);
    const route = routeAllManhattanPhysicalEdges([project.edges.find((edge) => edge.src === 'n1' && edge.dst === 'n2')!], project.floorplan.placements!)[0]!;
    expect(estimateManhattanRouteDelayPs(route, { wireDelayPsPerUnit: 2.5, fixedDelayPs: 3 })).toBe(23);
    project.floorplan.delayModel = { wireDelayPsPerUnit: 2.5, fixedDelayPs: 3 };
    project.floorplan.timingConstraints = [{ edgeId: route.edgeId, targetDelayPs: 22 }];
    expect(validateProject(project)).toEqual([]);
    expect(parseProject(serializeProject(project)).floorplan?.timingConstraints).toEqual([{ edgeId: route.edgeId, targetDelayPs: 22 }]);
    project.floorplan.timingConstraints[0]!.targetDelayPs = -1;
    expect(validateProject(project)).toContainEqual({ path: '$.floorplan.timingConstraints[0].targetDelayPs', message: 'must be a finite non-negative number' });
    project.floorplan.timingConstraints = [{ edgeId: 'missing', targetDelayPs: 2 }];
    expect(validateProject(project)).toContainEqual({ path: '$.floorplan.timingConstraints[0].edgeId', message: 'unknown graph edge missing' });
    project.floorplan.delayModel = { wireDelayPsPerUnit: -1, fixedDelayPs: 3 };
    expect(validateProject(project)).toContainEqual({ path: '$.floorplan.delayModel.wireDelayPsPerUnit', message: 'must be a finite non-negative number' });
  });
  it('validates physical rectangles by explicit node ID, unit, and dimensions', () => {
    const project = buildPreset('mesh-4x4');
    project.floorplan = { unit: 'mm', die: { originX: 0, originY: 0, width: 10, height: 8 }, placements: [
      { nodeId: 'n1', x: 1, y: 2, width: 1, height: 1 },
    ] };
    expect(validateProject(project)).toEqual([]);
    const placements = project.floorplan.placements!;
    placements.push({ nodeId: 'n1', x: 2, y: 2, width: 1, height: 1 });
    expect(validateProject(project).some((issue) => issue.message.includes('duplicate physical placement for node n1'))).toBe(true);
    placements.pop();
    placements[0]!.nodeId = 'unknown';
    expect(validateProject(project).some((issue) => issue.message.includes('unknown graph node unknown'))).toBe(true);
    placements[0]!.nodeId = 'n1';
    placements[0]!.width = 0;
    expect(validateProject(project).some((issue) => issue.path.endsWith('.width') && issue.message === 'must be positive')).toBe(true);
    delete project.floorplan.die;
    placements[0]!.width = 1;
    expect(validateProject(project).some((issue) => issue.path === '$.floorplan.die' && issue.message.includes('require an authored die outline'))).toBe(true);
  });
  it('audits every allowed firewall pair and reports missing route policies or rules precisely', () => {
    const project = buildPreset('mesh-4x4');
    project.firewall = { default: 'deny', rules: [
      { src: 'n1', dst: 'n3', perm: 'RW' }, { src: 'n4', dst: 'n13', perm: 'RO' },
      { src: 'n2', dst: 'n8', perm: 'deny' },
    ] };
    const missingPolicy = validateAllowedRouteReachability(project);
    expect(missingPolicy).toHaveLength(2);
    expect(missingPolicy.every((check) => check.error === 'No routing policy is selected for this allowed pair.')).toBe(true);
    project.routing = { policy: 'xy' };
    const routed = validateAllowedRouteReachability(project);
    expect(routed).toHaveLength(2);
    expect(routed.every((check) => check.error === null && check.route !== null)).toBe(true);
    project.routing = { policy: 'custom', rules: [{ src: 'n1', dst: 'n3', nextHop: 'n2' }] };
    const incomplete = validateAllowedRouteReachability(project);
    expect(incomplete[0]?.error).toBe('No next-hop rule for n2 → n3.');
    expect(incomplete[1]?.error).toBe('No next-hop rule for n4 → n13.');
    project.firewall.rules = Array.from({ length: 513 }, () => ({ src: 'n1', dst: 'n3', perm: 'RW' }));
    const overBudget = validateAllowedRouteReachability(project);
    expect(overBudget).toHaveLength(513);
    expect(overBudget.every((check) => check.error?.includes('512-pair authoring audit budget'))).toBe(true);
  });
  it('generates Odd-Even legal routes for every canonical 4×4 pair and refuses other shapes', () => {
    const project = buildPreset('mesh-4x4');
    project.routing = { policy: 'odd_even' };
    expect(validateProject(project)).toEqual([]);
    const direction = (from: string, to: string): string => {
      const a = Number(from.slice(1)) - 1;
      const b = Number(to.slice(1)) - 1;
      return b === a + 1 ? 'E' : b === a - 1 ? 'W' : b > a ? 'S' : 'N';
    };
    for (let source = 1; source <= 16; source++) for (let target = 1; target <= 16; target++) {
      const preview = previewOddEvenPath(project, `n${source}`, `n${target}`);
      expect(preview.error).toBeNull();
      const path = preview.route!.nodePath;
      for (let i = 1; i + 1 < path.length; i++) {
        const incoming = direction(path[i - 1]!, path[i]!);
        const outgoing = direction(path[i]!, path[i + 1]!);
        const col = (Number(path[i]!.slice(1)) - 1) % 4;
        expect(!(incoming === 'E' && ['N', 'S'].includes(outgoing) && (col + 1) % 2 === 1)).toBe(true);
        expect(!(['N', 'S'].includes(incoming) && outgoing === 'W' && (col + 1) % 2 === 0)).toBe(true);
      }
    }
    const mesh8 = buildPreset('mesh-8x8');
    mesh8.routing = { policy: 'odd_even' };
    for (const [source, target] of [['n1', 'n64'], ['n8', 'n57'], ['n56', 'n9'], ['n64', 'n1']]) {
      const preview = previewOddEvenPath(mesh8, source!, target!);
      expect(preview.error).toBeNull();
      expect(preview.route!.hops.every((hop) => mesh8.edges.some((edge) => edge.id === hop.edgeId))).toBe(true);
    }
    const ring = buildPreset('ring-8');
    ring.routing = { policy: 'odd_even' };
    expect(validateProject(ring).some((issue) => issue.message.includes('canonical 4×4 or 8×8 mesh'))).toBe(true);
    expect(previewOddEvenPath(ring, 'n1', 'n4').error).toContain('unsupported for this graph shape');
  });
  it('validates custom next-hop destinations, adjacency, and loops and previews a saved route', () => {
    const project = buildPreset('mesh-4x4');
    project.routing = { policy: 'custom', rules: [
      { src: 'n1', dst: 'n3', nextHop: 'n2' },
      { src: 'n2', dst: 'n3', nextHop: 'n3' },
    ] };
    expect(validateProject(project)).toEqual([]);
    expect(graphToTopologyIR(project).refused).toContain('graph custom routing policy is preview-only and is not materialized by the compiler adapter');
    expect(previewCustomPath(project, 'n1', 'n3').route?.nodePath).toEqual(['n1', 'n2', 'n3']);
    expect(previewCustomPath(project, 'n1', 'n3').route?.provenance).toBe('AUTHORED_NEXT_HOP_TABLE');
    expect(parseProject(serializeProject(project)).routing).toEqual(project.routing);
    project.routing.rules = [{ src: 'n1', dst: 'missing', nextHop: 'n2' }];
    expect(validateProject(project).some((issue) => issue.message.includes('unknown destination graph node missing'))).toBe(true);
    project.routing.rules = [{ src: 'n1', dst: 'n3', nextHop: 'n2' }, { src: 'n2', dst: 'n3', nextHop: 'n1' }];
    expect(validateProject(project).some((issue) => issue.message.includes('next-hop loop before destination n3'))).toBe(true);
    project.routing.rules = [{ src: 'n1', dst: 'n3', nextHop: 'n6' }];
    expect(validateProject(project).some((issue) => issue.message.includes('is not adjacent to source n1'))).toBe(true);
  });
  it('rejects XY routing for unsupported graph shapes instead of inferring canvas geometry', () => {
    const project = buildPreset('ring-8');
    project.routing = { policy: 'xy' };
    expect(supportsXYRouting(project)).toBe(false);
    expect(validateProject(project)).toContainEqual(expect.objectContaining({
      path: '$.routing.policy', message: expect.stringContaining('canonical 4×4 or 8×8 mesh'),
    }));
    const mesh = buildPreset('mesh-4x4');
    mesh.edges.pop();
    expect(supportsXYRouting(mesh)).toBe(false);
  });
  it('firewall rule inspector flags malformed imported entries', () => {
    expect(inspectFirewallRules([{ src: 'a', dst: 'b', perm: 'BAD' }, null])).toEqual([
      { index: 0, previousIndex: null, kind: 'invalid', message: 'rule must have non-empty src/dst and RO/RW perm' },
      { index: 1, previousIndex: null, kind: 'invalid', message: 'rule must be an object with src, dst, and RO/RW perm' },
    ]);
  });
  it('firewall rules report duplicate and conflicting matrix entries precisely', () => {
    expect(inspectFirewallRules([
      { src: 'a', dst: 'b', perm: 'RO' },
      { src: 'a', dst: 'b', perm: 'RW' },
      { src: 'a', dst: 'b', perm: 'RO' },
    ])).toEqual([
      { index: 1, previousIndex: 0, kind: 'conflict', message: 'conflicting RO/RW rules for a → b' },
      { index: 2, previousIndex: 0, kind: 'duplicate', message: 'duplicate rule for a → b' },
    ]);
  });
  it('row/column firewall edits replace only the selected axis in canonical order', () => {
    const current = [{ src: 'a', dst: 'b', perm: 'RO' as const }, { src: 'c', dst: 'a', perm: 'RW' as const }];
    expect(setFirewallRow(current, ['a', 'b', 'c'], 'a', 'RW')).toEqual([
      { src: 'a', dst: 'b', perm: 'RW' }, { src: 'a', dst: 'c', perm: 'RW' }, { src: 'c', dst: 'a', perm: 'RW' },
    ]);
    expect(setFirewallColumn(current, ['a', 'b', 'c'], 'a', 'none')).toEqual([{ src: 'a', dst: 'b', perm: 'RO' }]);
    const history = new GraphHistory(buildPreset('mesh-4x4'));
    const before = JSON.stringify(history.current());
    const bulk = setFirewallRow([], ['n1', 'n2', 'n3'], 'n1', 'RW');
    history.apply({ type: 'set_firewall', firewall: { default: 'deny', rules: bulk } as unknown as { [key: string]: import('../graph/project').JsonValue } });
    expect(history.canUndo()).toBe(true);
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
  });
  it('previews deterministic topology connectivity with ordered edges and VC classes', () => {
    const edges = [
      { id: 'e-b', src: 'mid', dst: 'target', vcClass: 2 },
      { id: 'e-a', src: 'source', dst: 'mid', vcClass: 1 },
    ];
    expect(previewConnectivityPath(['source', 'mid', 'target'], edges, 'source', 'target')).toEqual({
      nodePath: ['source', 'mid', 'target'],
      hops: [
        { edgeId: 'e-a', src: 'source', dst: 'mid', vcClass: 1 },
        { edgeId: 'e-b', src: 'mid', dst: 'target', vcClass: 2 },
      ],
      provenance: 'LOCAL_BFS_CONNECTIVITY_ONLY',
    });
    expect(previewConnectivityPath(['source', 'isolated'], edges, 'source', 'isolated')).toBeNull();
    const tie = previewConnectivityPath(['s', 'a', 'b', 't'], [
      { id: 'z0', src: 's', dst: 'b', vcClass: 0 }, { id: 'z1', src: 'b', dst: 't', vcClass: 0 },
      { id: 'a0', src: 's', dst: 'a', vcClass: 0 }, { id: 'a1', src: 'a', dst: 't', vcClass: 0 },
    ], 's', 't');
    expect(tie?.nodePath).toEqual(['s', 'a', 't']);
  });
  it('allow-all preset writes every explicit non-self graph-node pair', () => {
    expect(allowAllFirewallRules(['b', 'a', 'c'])).toEqual([
      { src: 'a', dst: 'b', perm: 'RW' }, { src: 'a', dst: 'c', perm: 'RW' },
      { src: 'b', dst: 'a', perm: 'RW' }, { src: 'b', dst: 'c', perm: 'RW' },
      { src: 'c', dst: 'a', perm: 'RW' }, { src: 'c', dst: 'b', perm: 'RW' },
    ]);
  });
  it('canonical firewall JSON is stable independent of matrix edit order', () => {
    const forward = canonicalFirewall([
      { src: 'init-a', dst: 'target-b', perm: 'RW' },
      { src: 'init-a', dst: 'target-a', perm: 'RO' },
    ]);
    const reverse = canonicalFirewall([
      { src: 'init-a', dst: 'target-a', perm: 'RO' },
      { src: 'init-a', dst: 'target-b', perm: 'RW' },
    ]);
    expect(forward).toEqual(reverse);
    expect(JSON.stringify(forward)).toBe(JSON.stringify(reverse));
    expect(forward).toEqual({ default: 'deny', rules: [
      { src: 'init-a', dst: 'target-a', perm: 'RO' },
      { src: 'init-a', dst: 'target-b', perm: 'RW' },
    ] });
  });
  it('detects firewall rules with endpoints that cannot match the graph matrix', () => {
    const issues = inspectFirewallRules([
      { src: 'missing', dst: 'n1', perm: 'RW' },
      { src: 'n1', dst: 'n1', perm: 'RO' },
    ], ['n1']);
    expect(issues).toEqual(expect.arrayContaining([
      expect.objectContaining({ index: 0, kind: 'invalid', message: expect.stringContaining('source missing is not a graph node') }),
      expect.objectContaining({ index: 1, kind: 'invalid', message: expect.stringContaining('self-pair n1 → n1 is not represented') }),
    ]));
  });
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
  it('rejects non-positive authored VC depth while leaving catalog limits unspecified', () => {
    const project = buildPreset('mesh-4x4');
    project.nodes[0]!.vc = { depth: 0 };
    expect(validateProject(project)).toContainEqual({
      path: '$.nodes[0].vc.depth', message: 'must be a positive integer when set',
    });
    project.nodes[0]!.vc = { depth: 8 };
    expect(validateProject(project)).toEqual([]);
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
    expect(new Set(t.frames.map((frame) => frame.phase))).toEqual(new Set(['unphased']));
    const phaseTrace = buildMockTrace(p, [
      { kind: 'prefill', name: 'declared-a', startCycle: 0, durationCycles: 1200 },
      { kind: 'decode', name: 'declared-b', startCycle: 1200, durationCycles: 1200 },
    ]);
    expect(phaseTrace.frames[11]?.phase).toBe('declared-a');
    expect(phaseTrace.frames[12]?.phase).toBe('declared-b');
    const untimedTrace = buildMockTrace(p, [{ kind: 'prefill' }]);
    expect(new Set(untimedTrace.frames.map((frame) => frame.phase))).toEqual(new Set(['unphased']));
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
  it('builds deterministic run intent only when phases and all ranks are explicit', () => {
    const workload = mixtralTp8Ep8();
    workload.phases = workload.phases.map((phase, index) => ({
      ...phase, tp: 1, ep: 1, pp: 1, dp: 1, startCycle: index * 100, durationCycles: 100,
    }));
    workload.rankMappings = [{ rank: 0, role: 'rank', nodeId: 'node-0' }];
    const nodeIds = ['node-0'];
    const built = buildWorkloadRunIntent(workload, nodeIds);
    expect(built.issues).toEqual([]);
    expect(built.json).toBe(buildWorkloadRunIntent(workload, nodeIds).json);
    expect(JSON.parse(built.json!).runIntentSchemaVersion).toBe(1);
    workload.rankMappings = [];
    expect(buildWorkloadRunIntent(workload, nodeIds).json).toBeNull();
  });
  it('exports workload JSON deterministically with schema version metadata', () => {
    const workload = mixtralTp8Ep8();
    workload.rankMappings = Array.from({ length: 64 }, (_, rank) => ({ rank, role: `rank-${rank}`, nodeId: `node-${rank}` }));
    const exported = serializeWorkloadJson(workload);
    expect(exported).toBe(serializeWorkloadJson(workload));
    expect(JSON.parse(exported).workloadSchemaVersion).toBe(1);
    expect(JSON.parse(exported).rankMappings).toEqual(workload.rankMappings);
    expect(parseWorkloadJson(exported, Array.from({ length: 64 }, (_, i) => `node-${i}`)).issues).toEqual([]);
  });
  it('parses workload JSON without coercion and localizes schema errors', () => {
    const workload = mixtralTp8Ep8();
    const good = parseWorkloadJson(JSON.stringify(workload), Array.from({ length: 64 }, (_, i) => `node-${i}`));
    expect(good.issues).toEqual([]);
    expect(good.workload).toEqual(workload);
    const unknown = parseWorkloadJson(JSON.stringify({ ...workload, seqLen: '4096', surprise: true }), []);
    expect(unknown.workload).toBeNull();
    expect(unknown.issues).toEqual(expect.arrayContaining([
      '$.surprise: unknown field', '$.seqLen: must be a number',
    ]));
    expect(parseWorkloadJson('{bad json', []).issues[0]).toMatch(/^\$: invalid JSON:/);
    const nested = parseWorkloadJson(JSON.stringify({ ...workload, communications: [{ id: 'x', kind: 'custom', dimension: 'tp', payloadBytes: 1, trafficClass: 'x', hiddenAssumption: true }] }), Array.from({ length: 64 }, (_, i) => `node-${i}`));
    expect(nested.issues).toContain('$.communications[0].hiddenAssumption: unknown field');
  });
  it('keeps point-to-point workload traffic distinct from collectives', () => {
    const workload = mixtralTp8Ep8();
    const p2p: WorkloadCommunication = {
      id: 'comm-p2p', kind: 'point-to-point', dimension: 'dp',
      payloadBytes: 1024, trafficClass: 'latency', sourceNodeId: 'n0', targetNodeId: 'n1',
    };
    workload.communications = [p2p];
    workload.defaultTrafficClassMapping = { vcClass: 0, qosClass: 'default' };
    expect(validateWorkload(workload, 64, ['n0', 'n1'], [0])).toEqual([]);
    workload.communications = [{ ...p2p, sourceNodeId: 'missing' }];
    expect(validateWorkload(workload, 64, ['n0', 'n1'])).toEqual(expect.arrayContaining([
      expect.stringContaining('unknown graph node missing'),
    ]));
  });
  it('auto-maps ranks deterministically in graph order and refuses insufficient capacity', () => {
    const workload = mixtralTp8Ep8();
    const nodes = ['n-z', 'n-a', 'n-x'];
    expect(autoRankMappings(workload, nodes)).toBeNull();
    workload.phases = workload.phases.map((phase) => ({ ...phase, tp: 2, ep: 1, pp: 1, dp: 1 }));
    const first = autoRankMappings(workload, nodes);
    expect(first).toEqual([
      { rank: 0, role: 'rank', nodeId: 'n-z' },
      { rank: 1, role: 'rank', nodeId: 'n-a' },
    ]);
    expect(autoRankMappings(workload, nodes)).toEqual(first);
    const doc = buildPreset('mesh-4x4');
    const history = new GraphHistory(doc);
    history.apply({
      type: 'set_workload',
      workload: { ...workload, rankMappings: first } as unknown as { [key: string]: import('../graph/project').JsonValue },
    });
    expect(history.current().workload?.rankMappings).toEqual(first);
    expect(history.undo()).toBe(true);
    expect(history.current().workload).toBeUndefined();
    expect(history.undo()).toBe(false);
  });
  it('validates explicit rank-to-node mapping identities', () => {
    const workload = mixtralTp8Ep8();
    workload.rankMappings = [
      { rank: 0, role: 'tp', nodeId: 'router-a' },
      { rank: 0, role: '', nodeId: 'missing-node' },
    ];
    expect(validateWorkload(workload, 2, ['router-a', 'router-b'])).toEqual(expect.arrayContaining([
      expect.stringContaining('duplicate rank 0'),
      expect.stringContaining('role: required'),
      expect.stringContaining('unknown graph node missing-node'),
    ]));
  });
  it('accepts unknown optional shape fields but validates values when supplied', () => {
    const workload = mixtralTp8Ep8();
    expect(validateWorkload(workload, 64)).toEqual([]);
    workload.modelName = 'Custom-1'; workload.hiddenSize = 0; workload.layerCount = 2.5;
    expect(validateWorkload(workload, 64)).toEqual(expect.arrayContaining([
      expect.stringContaining('hiddenSize: must be a positive integer'),
      expect.stringContaining('layerCount: must be a positive integer'),
    ]));
  });
  it('validates authored phase names and paired timing bounds', () => {
    const workload = mixtralTp8Ep8();
    workload.phases[0] = { ...workload.phases[0]!, name: 'prefill', startCycle: 0, durationCycles: 128 };
    expect(validateWorkload(workload, 64)).toEqual([]);
    workload.phases[0] = { ...workload.phases[0]!, startCycle: -1, durationCycles: 1.5 };
    expect(validateWorkload(workload, 64)).toEqual(expect.arrayContaining([
      expect.stringContaining('startCycle: must be a non-negative integer'),
      expect.stringContaining('durationCycles: must be a positive integer'),
    ]));
  });
  it('MoE skeleton separates TP and EP without assigning operation semantics', () => {
    const template = moeWorkloadSkeleton(mixtralTp8Ep8());
    expect(template.modelFamily).toBe('moe');
    expect(template.communications?.map(({ kind, dimension, payloadBytes, customName }) => ({ kind, dimension, payloadBytes, customName }))).toEqual([
      { kind: 'custom', dimension: 'tp', payloadBytes: 0, customName: '' },
      { kind: 'custom', dimension: 'ep', payloadBytes: 0, customName: '' },
    ]);
    expect(validateWorkload(template, 64)).toEqual(expect.arrayContaining([
      expect.stringContaining('customName: required'),
      expect.stringContaining('payloadBytes: must be a positive integer'),
    ]));
  });
  it('requires explicit traffic-class VC/QoS mappings and validates them against authored graph classes', () => {
    const workload = mixtralTp8Ep8();
    workload.communications = [{ id: 'ar', kind: 'allreduce', dimension: 'tp', payloadBytes: 512, trafficClass: 'latency' }];
    expect(validateWorkload(workload, 64, undefined, [0])).toContain(
      'communications[0].trafficClass: no explicit VC/QoS mapping or default',
    );
    workload.trafficClassMappings = [{ trafficClass: 'latency', vcClass: 1, qosClass: 'low-latency' }];
    expect(validateWorkload(workload, 64, undefined, [0])).toContain(
      'trafficClassMappings[0].vcClass: class 1 is not present on authored graph edges',
    );
    workload.trafficClassMappings[0]!.vcClass = 0;
    expect(validateWorkload(workload, 64, undefined, [0])).toEqual([]);
    workload.trafficClassMappings[0]!.qosClass = '';
    expect(validateWorkload(workload, 64, undefined, [0])).toContain('trafficClassMappings[0].qosClass: required');
    workload.trafficClassMappings = [];
    workload.defaultTrafficClassMapping = { vcClass: 0, qosClass: 'default' };
    expect(validateWorkload(workload, 64, undefined, [0])).toEqual([]);
  });
  it('validates declared communication dimensions, payloads, and traffic classes', () => {
    const workload = mixtralTp8Ep8();
    const operation: WorkloadCommunication = {
      id: 'comm-1', kind: 'allreduce', dimension: 'tp', payloadBytes: 4096, trafficClass: 'bulk',
    };
    workload.communications = [operation];
    workload.defaultTrafficClassMapping = { vcClass: 0, qosClass: 'default' };
    expect(validateWorkload(workload, 64)).toEqual([]);
    workload.communications = [
      { ...operation, kind: 'custom', customName: '', dimension: 'custom', dimensionName: '', payloadBytes: 0, trafficClass: '' },
    ];
    expect(validateWorkload(workload, 64)).toEqual(expect.arrayContaining([
      expect.stringContaining('customName: required'),
      expect.stringContaining('dimensionName: required'),
      expect.stringContaining('payloadBytes: must be a positive integer'),
      expect.stringContaining('trafficClass: required'),
    ]));
  });
  it('checks authored rank assignments against declared seat demand', () => {
    const workload = mixtralTp8Ep8();
    workload.rankMappings = [
      { rank: 0, role: 'rank', nodeId: 'n0' },
      { rank: 1, role: 'rank', nodeId: 'n1' },
    ];
    expect(validateWorkload(workload, 64, ['n0', 'n1'])).toEqual(expect.arrayContaining([
      expect.stringContaining('parallelism needs 64 mapped rank seats but only 2 are assigned'),
    ]));
  });
  it('reports malformed workload rank-constraint rows without throwing', () => {
    const workload = mixtralTp8Ep8();
    workload.rankConstraints = [null as unknown as NonNullable<typeof workload.rankConstraints>[number]];
    expect(validateWorkload(workload, 64)).toContain('rankConstraints[0]: must be an object');
  });
  it('requires contiguous workload rank mappings with no excess ranks', () => {
    const workload = mixtralTp8Ep8();
    workload.phases = [{ ...workload.phases[0]!, tp: 2, ep: 1, pp: 1, dp: 1 }];
    workload.rankMappings = [
      { rank: 0, role: 'rank', nodeId: 'n0' },
      { rank: 2, role: 'rank', nodeId: 'n2' },
    ];
    expect(validateWorkload(workload, 3, ['n0', 'n1', 'n2'])).toEqual(expect.arrayContaining([
      'rankMappings: missing rank 1',
      'rankMappings[1].rank: exceeds declared parallel demand (2)',
    ]));
  });
  it('prevents mapping multiple workload ranks onto one graph node', () => {
    const workload = mixtralTp8Ep8();
    workload.phases = [{ ...workload.phases[0]!, tp: 2, ep: 1, pp: 1, dp: 1 }];
    workload.rankMappings = [
      { rank: 0, role: 'rank', nodeId: 'n0' },
      { rank: 1, role: 'rank', nodeId: 'n0' },
    ];
    expect(validateWorkload(workload, 2, ['n0', 'n1'])).toContain(
      'rankMappings[1].nodeId: graph node n0 already assigned to rank 0',
    );
  });
  it('rejects invalid workload parameters and duplicate phase IDs', () => {
    const workload = mixtralTp8Ep8();
    workload.seqLen = 0;
    workload.phases[1] = { ...workload.phases[1]!, id: workload.phases[0]!.id, tp: 1.5 };
    const issues = validateWorkload(workload, 64);
    expect(issues).toEqual(expect.arrayContaining([
      'seqLen: must be a positive integer',
      expect.stringContaining('duplicate id'),
      expect.stringContaining('phases[1].tp'),
    ]));
    workload.phases[0] = { ...workload.phases[0]!, pp: -1 };
    expect(validateWorkload(workload, 64)).toEqual(expect.arrayContaining([
      'phases[0].pp: must be a positive integer',
    ]));
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
      routing: { oneOf: Array<{ properties: { policy: { const: string } }; additionalProperties: boolean }> };
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

  it('declares the persisted XY route policy as a closed enum', () => {
    expect(schema.properties.routing.oneOf.map((variant) => variant.properties.policy.const)).toEqual(['xy', 'west_first', 'odd_even', 'custom']);
    expect(schema.properties.routing.oneOf.every((variant) => variant.additionalProperties === false)).toBe(true);
    const project = { ...buildPreset('mesh-4x4'), routing: { policy: 'xy' as const } };
    expect(validateProject(project)).toEqual([]);
  });

  it('pins schemaVersion 1 on both sides', () => {
    expect(schema.properties.schemaVersion.const).toBe(1);
    expect(validateProject({ ...buildPreset('mesh-4x4'), schemaVersion: 2 })
      .some((i) => i.message.includes('equal 1'))).toBe(true);
  });
});
