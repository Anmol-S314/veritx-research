import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildPreset } from '../graph/presets';
import { routeAllManhattanPhysicalEdges } from '../graph/floorplan';
import { GraphHistory } from '../graph/history';
import { parseProject, serializeProject, validateProject } from '../graph/project';
import { emptyWorkload, parseWorkloadJson, serializeWorkloadJson, validateWorkload, type WorkloadBlock } from '../graph/workload';
import type { GraphCommand } from '../graph/history';
import type { GraphStore } from '../graph/store';
import { FirewallEditor, FloorplanPreview, NodeEditor, NodeTable, SimPlayback, WorkloadEditor } from '../pages/loom/authoring';

const storeWithMapping = (withConflicts = false, malformedRules = false): GraphStore => {
  const doc = buildPreset('mesh-4x4');
  doc.workload = {
    modelFamily: 'test', paramsB: 1, seqLen: 16, batch: 1, precision: 'fp16',
    phases: [{ id: 'phase-0', name: 'Prefill', kind: 'prefill', tokens: 16, batch: 1, tp: 1, ep: 1, pp: 1, dp: 1 }],
    rankMappings: [{ rank: 0, role: 'worker', nodeId: 'n1' }],
  };
  if (withConflicts) doc.firewall = { default: 'deny', rules: [
    { src: 'n1', dst: 'n2', perm: 'RO' }, { src: 'n1', dst: 'n2', perm: 'RW' },
  ] };
  if (malformedRules) doc.firewall = { default: 'deny', rules: 'not-an-array' };
  return {
    doc, dirty: false, error: null, canUndo: false, canRedo: false, isCustom: true,
    run: () => null, undo: () => undefined, redo: () => undefined,
    loadPreset: () => undefined, loadJson: () => null, serialize: () => '',
  };
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('workload and access authoring views', () => {
  it('persists node VC depth edits through graph history while preserving other VC metadata', () => {
    const store = storeWithMapping();
    store.doc.nodes[0]!.vc = { policyTag: 'existing' };
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    render(<NodeTable store={store} />);
    fireEvent.change(screen.getByLabelText('vc template depth'), { target: { value: '16' } });
    fireEvent.click(screen.getByRole('button', { name: 'Batch apply VC depth → 16 rows' }));
    expect(history.current().nodes.every((node) => node.vc?.depth === 16)).toBe(true);
    expect(history.current().nodes[0]?.vc).toMatchObject({ policyTag: 'existing', depth: 16 });
    expect(JSON.parse(serializeProject(history.current())).nodes[0].vc).toEqual({ policyTag: 'existing', depth: 16 });
  });
  it('blocks run-intent export when a point-to-point traffic-class VC conflicts with the routed path', () => {
    const store = storeWithMapping();
    store.doc.routing = { policy: 'xy' };
    const first = store.doc.edges.find((edge) => edge.src === 'n1' && edge.dst === 'n2')!;
    store.doc.edges.find((edge) => edge.id !== first.id)!.vcClass = 1;
    const workload = store.doc.workload as unknown as WorkloadBlock;
    workload.communications = [{ id: 'p2p', kind: 'point-to-point', sourceNodeId: 'n1', targetNodeId: 'n2', dimension: 'tp', payloadBytes: 16, trafficClass: 'bulk' }];
    workload.trafficClassMappings = [{ trafficClass: 'bulk', vcClass: 1, qosClass: 'best-effort' }];
    render(<WorkloadEditor store={store} />);
    expect(screen.getByText(/traffic class bulk maps to VC 1/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Export validated run intent' }) as HTMLButtonElement).disabled).toBe(true);
  });
  it('writes edited workload fields through validated set_workload history actions', () => {
    const store = storeWithMapping();
    const workload = store.doc.workload as unknown as WorkloadBlock;
    workload.communications = [{ id: 'comm-0', kind: 'allreduce', dimension: 'tp', payloadBytes: 16, trafficClass: 'default' }];
    const history = new GraphHistory(store.doc);
    const commands: GraphCommand[] = [];
    store.run = (command) => {
      commands.push(command);
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('model name'), { target: { value: 'authored-model' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('tokens phase-0'), { target: { value: '64' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('payload bytes comm-0'), { target: { value: '2048' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('mapping role 0'), { target: { value: 'worker' } });
    rerender(<WorkloadEditor store={store} />);
    expect(commands.every((command) => command.type === 'set_workload')).toBe(true);
    expect(history.current().workload).toMatchObject({
      modelName: 'authored-model', phases: [{ tokens: 64 }],
      communications: [{ payloadBytes: 2048 }], rankMappings: [{ role: 'worker' }],
    });
    expect(validateProject(history.current())).toEqual([]);
    const beforeRefusal = JSON.stringify(history.current());
    const refused = history.apply({ type: 'set_workload', workload: 'not-an-object' as unknown as { [key: string]: import('../graph/project').JsonValue } });
    expect(refused.refused).toContain('$.workload: must be a JSON object');
    expect(JSON.stringify(history.current())).toBe(beforeRefusal);
  });
  it('starts an empty custom workload without hidden phases, operations, model shape or mappings', () => {
    const workload = emptyWorkload();
    expect(workload).toEqual({ modelFamily: 'custom', seqLen: 1, batch: 1, precision: 'fp16', phases: [], communications: [], rankMappings: [] });
    expect(validateWorkload(workload, 16).map((i) => i.message)).toContain('at least one phase is required');
    const store = storeWithMapping();
    store.doc.workload = undefined;
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Create empty custom workload' }));
    rerender(<WorkloadEditor store={store} />);
    expect((screen.getByLabelText('model family') as HTMLInputElement).value).toBe('custom');
    expect((screen.getByLabelText('seq len') as HTMLInputElement).value).toBe('1');
    expect((screen.getByLabelText('batch') as HTMLInputElement).value).toBe('1');
    expect((screen.getByLabelText('precision') as HTMLSelectElement).value).toBe('fp16');
    expect(document.body.textContent).toMatch(/no assumed model shape, phases, communication operations or rank mappings/i);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain('at least one phase is required');
  });
  it('loads editable dense example assumptions and labels the unstated inputs', () => {
    const store = storeWithMapping();
    store.doc.workload = undefined;
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Load dense example' }));
    rerender(<WorkloadEditor store={store} />);
    expect((screen.getByLabelText('parameter count billions') as HTMLInputElement).value).toBe('47');
    expect((screen.getByLabelText('seq len') as HTMLInputElement).value).toBe('4096');
    expect((screen.getByLabelText('batch') as HTMLInputElement).value).toBe('8');
    expect((screen.getByLabelText('precision') as HTMLSelectElement).value).toBe('fp16');
    expect((screen.getByLabelText('tp ph-prefill') as HTMLInputElement).value).toBe('8');
    expect((screen.getByLabelText('ep ph-prefill') as HTMLInputElement).value).toBe('8');
    expect((screen.getByLabelText('tp ph-decode') as HTMLInputElement).value).toBe('8');
    expect((screen.getByLabelText('ep ph-decode') as HTMLInputElement).value).toBe('1');
    expect(document.body.textContent).toMatch(/No communications, phase cycle timing, or measured behavior is implied/i);
  });
  it('labels mock playback phases only from explicit project start/duration boundaries', () => {
    const store = storeWithMapping();
    const workload = store.doc.workload as unknown as WorkloadBlock;
    workload.phases = [
      { id: 'warmup', name: 'Warmup', kind: 'prefill', startCycle: 0, durationCycles: 600, tokens: 16, batch: 1, tp: 1, ep: 1, pp: 1, dp: 1 },
      { id: 'decode', name: 'Decode', kind: 'decode', startCycle: 600, durationCycles: 1200, tokens: 16, batch: 1, tp: 1, ep: 1, pp: 1, dp: 1 },
    ];
    const { container } = render(<SimPlayback store={store} />);
    expect(container.textContent).toContain('cycle 0 · phase Warmup');
    fireEvent.change(screen.getByLabelText('scrub'), { target: { value: '7' } });
    expect(container.textContent).toContain('cycle 700 · phase Decode');
    fireEvent.change(screen.getByLabelText('scrub'), { target: { value: '18' } });
    expect(container.textContent).toContain('cycle 1800 · phase unphased');
  });
  it('edits and validates pinned, allowed-node, and required-role rank constraints', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Rank constraint' }));
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('pinned node 0'), { target: { value: 'n2' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('required role 0'), { target: { value: 'trainer' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByLabelText('allowed node 0 n1'));
    rerender(<WorkloadEditor store={store} />);
    let issues = screen.getByLabelText('Workload validation issues').textContent ?? '';
    expect(issues).toContain('pinned node is not in allowed node set');
    expect(issues).toContain('rank 0 is pinned to n2, not n1');
    expect(issues).toContain('rank 0 requires role trainer, not worker');
    fireEvent.change(screen.getByLabelText('pinned node 0'), { target: { value: 'n1' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('required role 0'), { target: { value: 'worker' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.queryByLabelText('Workload validation issues')).toBeNull();
    const workload = history.current().workload as unknown as WorkloadBlock;
    expect(workload.rankConstraints).toEqual([{ rank: 0, pinnedNodeId: 'n1', requiredRole: 'worker', allowedNodeIds: ['n1'] }]);
    expect(parseWorkloadJson(serializeWorkloadJson(workload), store.doc.nodes.map((node) => node.id))).toMatchObject({ workload: { rankConstraints: workload.rankConstraints }, issues: [] });
  });
  it('maps operation traffic classes to authored VC/QoS values and validates explicit fallback', () => {
    const store = storeWithMapping();
    const workload = store.doc.workload as unknown as WorkloadBlock;
    workload.communications = [{ id: 'comm-latency', kind: 'allreduce', dimension: 'tp', payloadBytes: 64, trafficClass: 'latency' }];
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain('no explicit VC/QoS mapping or default');
    fireEvent.click(screen.getByRole('button', { name: '+ Traffic class mapping' }));
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('mapped traffic class 0'), { target: { value: 'latency' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('mapped QoS class 0'), { target: { value: 'latency-qos' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.queryByLabelText('Workload validation issues')).toBeNull();
    const mapped = history.current().workload as unknown as WorkloadBlock;
    expect(mapped.trafficClassMappings).toEqual([{ trafficClass: 'latency', vcClass: 0, qosClass: 'latency-qos' }]);
    expect(parseWorkloadJson(serializeWorkloadJson(mapped), store.doc.nodes.map((node) => node.id), [0]).issues).toEqual([]);
    fireEvent.click(screen.getByLabelText('remove traffic class mapping 0'));
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('default traffic class VC'), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('default traffic class QoS'), { target: { value: 'default-qos' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.queryByLabelText('Workload validation issues')).toBeNull();
    expect((history.current().workload as unknown as WorkloadBlock).defaultTrafficClassMapping).toEqual({ vcClass: 0, qosClass: 'default-qos' });
  });
  it('summarizes canonical workload shape, phases, declared bytes and mapping completeness', () => {
    const store = storeWithMapping();
    const workload = store.doc.workload as unknown as WorkloadBlock;
    workload.modelName = 'Example';
    workload.hiddenSize = 4096;
    workload.layerCount = 32;
    workload.communications = [{ id: 'ar', kind: 'allreduce', dimension: 'tp', payloadBytes: 2048, trafficClass: 'bulk' }];
    render(<WorkloadEditor store={store} />);
    const summary = screen.getByLabelText('Workload summary').textContent ?? '';
    expect(summary).toContain('test · Example · 1B · hidden 4096 · layers 32');
    expect(summary).toContain('seq 16 · batch 1 · precision fp16');
    expect(summary).toContain('TP 1 / EP 1 / PP 1 / DP 1');
    expect(summary).toContain('1 / 1 · Prefill');
    expect(summary).toContain('2048 B');
    expect(summary).toContain('1 / 1');
  });
  it('selects serialized XY policy and previews a dimension-order path on canonical mesh', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FirewallEditor store={store} />);
    const policy = screen.getByLabelText('routing policy') as HTMLSelectElement;
    expect((policy.querySelector('option[value="xy"]') as HTMLOptionElement).disabled).toBe(false);
    fireEvent.change(policy, { target: { value: 'xy' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n1 to n12: DENY' }));
    rerender(<FirewallEditor store={store} />);
    expect(history.current().routing).toEqual({ policy: 'xy' });
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('XY routed path:');
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('XY_MESH_DIMENSION_ORDER');
    expect(parseProject(serializeProject(history.current())).routing).toEqual({ policy: 'xy' });
  });
  it('selects serialized West-First policy and previews an ordered mesh route', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FirewallEditor store={store} />);
    const policy = screen.getByLabelText('routing policy') as HTMLSelectElement;
    expect((policy.querySelector('option[value="west_first"]') as HTMLOptionElement).disabled).toBe(false);
    fireEvent.change(policy, { target: { value: 'west_first' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n4 to n9: DENY' }));
    rerender(<FirewallEditor store={store} />);
    expect(history.current().routing).toEqual({ policy: 'west_first' });
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('West-First routed path:');
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('WEST_FIRST_MESH_ORDER');
    expect(parseProject(serializeProject(history.current())).routing).toEqual({ policy: 'west_first' });
  });
  it('authors endpoint port indices on edges and validates them through graph history', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const edge = store.doc.edges[0]!;
    const { rerender } = render(<NodeEditor store={store} />);
    fireEvent.click(screen.getByTestId(`edge-hit-${edge.id}`));
    rerender(<NodeEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`edge src port ${edge.id}`), { target: { value: '2' } });
    rerender(<NodeEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`edge dst port ${edge.id}`), { target: { value: '3' } });
    rerender(<NodeEditor store={store} />);
    expect(history.current().edges[0]).toMatchObject({ srcPort: 2, dstPort: 3 });
    const invalid = history.apply({ type: 'update_edge', id: edge.id, patch: { srcPort: 5 } });
    expect(invalid.refused).toContain('port 5 is outside');
    expect(history.current().edges[0]).toMatchObject({ srcPort: 2, dstPort: 3 });
    expect(parseProject(serializeProject(history.current())).edges[0]).toMatchObject({ srcPort: 2, dstPort: 3 });
    expect(history.apply({ type: 'set_routing', routing: { policy: 'xy' } }).refused).toBeNull();
    store.doc = history.current();
    cleanup();
    const { rerender: rerenderFirewall } = render(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: `${edge.src} to ${edge.dst}: DENY` }));
    rerenderFirewall(<FirewallEditor store={store} />);
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('ports 2→3');
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('XY_MESH_DIMENSION_ORDER');
  });
  it('authors explicit die bounds with unit conversion, validation, serialization, and undo', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('die coordinate unit'), { target: { value: 'mm' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('die origin x'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('die origin y'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('die width'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('die height'), { target: { value: '8' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Apply die outline' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan).toEqual({ unit: 'mm', die: { originX: 1, originY: 2, width: 10, height: 8 } });
    fireEvent.change(screen.getByLabelText('placement x'), { target: { value: '1.5' } });
    fireEvent.change(screen.getByLabelText('placement y'), { target: { value: '2.5' } });
    fireEvent.change(screen.getByLabelText('placement width'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('placement height'), { target: { value: '1' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Place physical rectangle' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements).toEqual([{ nodeId: 'n1', x: 1.5, y: 2.5, width: 1, height: 1 }]);
    expect(parseProject(serializeProject(history.current())).floorplan).toEqual(history.current().floorplan);
    const physicalSvg = screen.getByLabelText('Physical placement view');
    vi.spyOn(physicalSvg, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 600, height: 360, right: 600, bottom: 360, x: 0, y: 0, toJSON: () => ({}) } as DOMRect);
    fireEvent.click(screen.getByRole('button', { name: 'n1 physical rectangle' }));
    rerender(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('physical anchor x'), { target: { value: '3.24' } });
    fireEvent.click(screen.getByRole('button', { name: 'align n1 to anchor x' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements?.[0]?.x).toBe(3.2);
    expect(history.undo()).toBe(true);
    store.doc = history.current(); rerender(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('physical anchor y'), { target: { value: '3.24' } });
    fireEvent.click(screen.getByRole('button', { name: 'align n1 to anchor y' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements?.[0]?.y).toBe(3.2);
    expect(history.undo()).toBe(true);
    store.doc = history.current(); rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'lock physical placement n1' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements?.[0]?.locked).toBe(true);
    expect(parseProject(serializeProject(history.current())).floorplan?.placements?.[0]?.locked).toBe(true);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'n1 physical rectangle' }), { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(physicalSvg, { pointerId: 1, clientX: 154, clientY: 130 });
    fireEvent.pointerUp(physicalSvg, { pointerId: 1, clientX: 154, clientY: 130 });
    expect(history.current().floorplan?.placements?.[0]).toMatchObject({ x: 1.5, y: 2.5, locked: true });
    fireEvent.click(screen.getByRole('button', { name: 'unlock physical placement n1' }));
    rerender(<FloorplanPreview store={store} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'n1 physical rectangle' }), { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(physicalSvg, { pointerId: 1, clientX: 154, clientY: 130 });
    fireEvent.pointerUp(physicalSvg, { pointerId: 1, clientX: 154, clientY: 130 });
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements).toEqual([{ nodeId: 'n1', x: 2.5, y: 3.3, width: 1, height: 1 }]);
    expect(history.undo()).toBe(true);
    store.doc = history.current(); rerender(<FloorplanPreview store={store} />);
    fireEvent.pointerDown(screen.getByRole('button', { name: 'n1 resize handle' }), { pointerId: 2, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(physicalSvg, { pointerId: 2, clientX: 154, clientY: 130 });
    fireEvent.pointerUp(physicalSvg, { pointerId: 2, clientX: 154, clientY: 130 });
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements).toEqual([{ nodeId: 'n1', x: 1.5, y: 2.5, width: 2, height: 1.8 }]);
    expect(history.undo()).toBe(true);
    store.doc = history.current(); rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n1 physical rectangle' }));
    rerender(<FloorplanPreview store={store} />);
    expect(screen.getByText(/Selected physical node: n1/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('placement x'), { target: { value: '3.14' } });
    fireEvent.change(screen.getByLabelText('placement width'), { target: { value: '1.26' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Update physical rectangle' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements).toEqual([{ nodeId: 'n1', x: 3.1, y: 2.5, width: 1.3, height: 1 }]);
    expect(history.undo()).toBe(true);
    store.doc = history.current(); rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements).toEqual([{ nodeId: 'n1', x: 1.5, y: 2.5, width: 1, height: 1 }]);
    fireEvent.change(screen.getByLabelText('die coordinate unit'), { target: { value: 'um' } });
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan).toEqual({ unit: 'um', die: { originX: 1000, originY: 2000, width: 10000, height: 8000 }, placements: [{ nodeId: 'n1', x: 1500, y: 2500, width: 1000, height: 1000 }] });
    fireEvent.change(screen.getByLabelText('die width'), { target: { value: '0' } });
    rerender(<FloorplanPreview store={store} />);
    expect((screen.getByRole('button', { name: 'Apply die outline' }) as HTMLButtonElement).disabled).toBe(true);
    expect(history.undo()).toBe(true);
    expect(history.current().floorplan).toEqual({ unit: 'mm', die: { originX: 1, originY: 2, width: 10, height: 8 }, placements: [{ nodeId: 'n1', x: 1.5, y: 2.5, width: 1, height: 1 }] });
  });
  it('persists an independent physical snap grid and uses it for rectangle authoring', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('die coordinate unit'), { target: { value: 'mm' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('die origin x'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('die origin y'), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText('die width'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('die height'), { target: { value: '10' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Apply die outline' }));
    rerender(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('physical grid step'), { target: { value: '0.5' } });
    fireEvent.blur(screen.getByLabelText('physical grid step'));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.gridStep).toBe(0.5);
    fireEvent.change(screen.getByLabelText('placement x'), { target: { value: '1.7' } });
    fireEvent.change(screen.getByLabelText('placement y'), { target: { value: '2.7' } });
    fireEvent.change(screen.getByLabelText('placement width'), { target: { value: '1.3' } });
    fireEvent.change(screen.getByLabelText('placement height'), { target: { value: '1.3' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Place physical rectangle' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements).toEqual([{ nodeId: 'n1', x: 1.5, y: 2.5, width: 1.5, height: 1.5 }]);
    expect(parseProject(serializeProject(history.current())).floorplan?.gridStep).toBe(0.5);
    expect(history.undo()).toBe(true);
    expect(history.current().floorplan?.gridStep).toBe(0.5);
    expect(history.undo()).toBe(true);
    expect(history.current().floorplan?.gridStep).toBeUndefined();
  });
  it('renders physical routes from current placements and recomputes lengths after a placement edit', () => {
    const store = storeWithMapping();
    store.doc.floorplan = { unit: 'mm', die: { originX: 0, originY: 0, width: 20, height: 10 }, placements: [
      { nodeId: 'n1', x: 1, y: 1, width: 2, height: 2 },
      { nodeId: 'n2', x: 7, y: 5, width: 2, height: 2 },
    ] };
    const history = new GraphHistory(store.doc);
    store.run = (command) => { const outcome = history.apply(command); store.doc = history.current(); return outcome.refused; };
    const { rerender } = render(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'route all Manhattan physical links' }));
    expect(screen.getByTestId('physical-route-e1')).toBeTruthy();
    expect(screen.getByLabelText('Physical Manhattan route details').textContent).toContain('e1: 8 mm');
    expect(screen.getByText('Estimated delay unavailable until both formula inputs are explicitly authored.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('wire delay per physical unit'), { target: { value: '2.5' } });
    fireEvent.change(screen.getByLabelText('fixed endpoint delay'), { target: { value: '3' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'apply physical delay estimate inputs' }));
    rerender(<FloorplanPreview store={store} />);
    expect(screen.getByLabelText('Physical Manhattan route details').textContent).toContain('Estimated delay 23 ps');
    fireEvent.change(screen.getByLabelText('target delay e1'), { target: { value: '22' } });
    rerender(<FloorplanPreview store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'apply target delay e1' }));
    rerender(<FloorplanPreview store={store} />);
    expect(screen.getByLabelText('Physical Manhattan route details').textContent).toContain('Estimated FAIL against 22 ps target');
    expect(parseProject(serializeProject(history.current())).floorplan?.timingConstraints).toEqual([{ edgeId: 'e1', targetDelayPs: 22 }]);
    const placements = history.current().floorplan!.placements!.map((placement) => placement.nodeId === 'n2' ? { ...placement, x: 8 } : placement);
    store.run({ type: 'set_floorplan', floorplan: { ...history.current().floorplan!, placements } });
    rerender(<FloorplanPreview store={store} />);
    expect(screen.getByLabelText('Physical Manhattan route details').textContent).toContain('e1: 9 mm');
    expect(screen.getByLabelText('Physical Manhattan route details').textContent).toContain('Estimated delay 25.5 ps');
    expect(screen.getByLabelText('Physical Manhattan route details').textContent).toContain('Estimated FAIL against 22 ps target');
  });
  it('derives deterministic Manhattan physical link previews and unresolved placement statuses', () => {
    const store = storeWithMapping();
    const edge = store.doc.edges.find((candidate) => candidate.src === 'n1' && candidate.dst === 'n2')!;
    const placements = [
      { nodeId: 'n1', x: 1, y: 1, width: 2, height: 2 },
      { nodeId: 'n2', x: 7, y: 5, width: 2, height: 2 },
    ];
    const first = routeAllManhattanPhysicalEdges([edge], placements);
    expect(first).toEqual([{ edgeId: edge.id, status: 'routed', points: [{ x: 3, y: 2 }, { x: 7, y: 2 }, { x: 7, y: 6 }], length: 8, provenance: 'LOCAL_MANHATTAN_PLACEMENT_PREVIEW' }]);
    expect(routeAllManhattanPhysicalEdges([edge], placements)).toEqual(first);
    expect(routeAllManhattanPhysicalEdges([edge], [placements[0]!])[0]).toMatchObject({ status: 'unresolved', error: 'Missing physical placement for n2.' });
    expect(routeAllManhattanPhysicalEdges([edge], [...placements.slice(0, 1), { ...placements[1]!, x: 8 }])[0]?.length).toBe(9);
  });
  it('drags unplaced graph nodes into the authored die using explicit size and physical-grid coordinates', () => {
    const store = storeWithMapping();
    store.doc.floorplan = { unit: 'mm', gridStep: 0.5, die: { originX: 0, originY: 0, width: 10, height: 10 } };
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('placement width'), { target: { value: '1.3' } });
    fireEvent.change(screen.getByLabelText('placement height'), { target: { value: '1.3' } });
    rerender(<FloorplanPreview store={store} />);
    const physicalSvg = screen.getByLabelText('Physical placement view');
    vi.spyOn(physicalSvg, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 600, height: 360, right: 600, bottom: 360, x: 0, y: 0, toJSON: () => ({}) } as DOMRect);
    let dragged = '';
    const dataTransfer = { setData: (_type: string, value: string): void => { dragged = value; }, getData: (): string => dragged, effectAllowed: 'move' };
    fireEvent.dragStart(screen.getByRole('button', { name: 'drag unplaced node n1' }), { dataTransfer });
    const dragOver = new Event('dragover', { bubbles: true, cancelable: true });
    Object.defineProperty(dragOver, 'dataTransfer', { value: dataTransfer });
    fireEvent(physicalSvg, dragOver);
    const drop = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperties(drop, { dataTransfer: { value: dataTransfer }, clientX: { value: 165 }, clientY: { value: 110 } });
    fireEvent(physicalSvg, drop);
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements).toEqual([{ nodeId: 'n1', x: 2.5, y: 3, width: 1.5, height: 1.5 }]);
    expect(screen.queryByRole('button', { name: 'drag unplaced node n1' })).toBeNull();
  });
  it('authors, serializes, validates and removes physical keepout regions', () => {
    const store = storeWithMapping();
    store.doc.floorplan = { unit: 'mm', die: { originX: 0, originY: 0, width: 10, height: 10 }, placements: [] };
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    render(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('keepout id'), { target: { value: 'no-place-west' } });
    fireEvent.change(screen.getByLabelText('keepout x'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('keepout y'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('keepout width'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('keepout height'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add keepout' }));
    expect(history.current().floorplan?.keepouts).toEqual([{ id: 'no-place-west', x: 1, y: 2, width: 2, height: 3 }]);
    expect(screen.getByLabelText('Physical keepout no-place-west')).toBeTruthy();
    expect(parseProject(serializeProject(history.current())).floorplan?.keepouts).toEqual(history.current().floorplan?.keepouts);
    const refused = history.apply({ type: 'set_floorplan', floorplan: { ...history.current().floorplan!, placements: [{ nodeId: 'n1', x: 2, y: 3, width: 1, height: 1 }] } });
    expect(refused.refused).toContain('intersects keepout no-place-west');
    fireEvent.click(screen.getByRole('button', { name: 'remove keepout no-place-west' }));
    expect(history.current().floorplan?.keepouts).toEqual([]);
    expect(history.undo()).toBe(true);
    expect(history.current().floorplan?.keepouts).toEqual([{ id: 'no-place-west', x: 1, y: 2, width: 2, height: 3 }]);
  });
  it('authors persisted manual physical waypoints and resets an edge to automatic routing', () => {
    const store = storeWithMapping();
    store.doc.floorplan = { unit: 'mm', die: { originX: 0, originY: 0, width: 10, height: 10 }, placements: [
      { nodeId: 'n1', x: 1, y: 1, width: 1, height: 1 }, { nodeId: 'n2', x: 5, y: 5, width: 1, height: 1 },
    ] };
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const edge = store.doc.edges.find((item) => item.src === 'n1' && item.dst === 'n2')!;
    render(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText(`waypoint x ${edge.id}`), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText(`waypoint y ${edge.id}`), { target: { value: '8' } });
    fireEvent.click(screen.getByRole('button', { name: `add waypoint ${edge.id}` }));
    expect(history.current().edges.find((item) => item.id === edge.id)?.physical?.waypoints).toEqual([{ x: 4, y: 8 }]);
    expect(parseProject(serializeProject(history.current())).edges.find((item) => item.id === edge.id)?.physical?.waypoints).toEqual([{ x: 4, y: 8 }]);
    fireEvent.click(screen.getByRole('button', { name: `reset route ${edge.id} to automatic` }));
    expect(history.current().edges.find((item) => item.id === edge.id)?.physical?.waypoints).toBeUndefined();
  });
  it('aligns selected physical rectangles to shared anchors and leaves locked instances unchanged', () => {
    const store = storeWithMapping();
    store.doc.floorplan = { unit: 'mm', gridStep: 0.5, die: { originX: 0, originY: 0, width: 10, height: 10 }, placements: [
      { nodeId: 'n1', x: 1, y: 1, width: 1, height: 1 },
      { nodeId: 'n2', x: 4, y: 5, width: 1, height: 1 },
      { nodeId: 'n3', x: 7, y: 9, width: 1, height: 1, locked: true },
    ] };
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FloorplanPreview store={store} />);
    fireEvent.change(screen.getByLabelText('group anchor x'), { target: { value: '3.24' } });
    fireEvent.click(screen.getByLabelText('select physical placement n1'));
    fireEvent.click(screen.getByLabelText('select physical placement n2'));
    expect((screen.getByLabelText('select physical placement n3') as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'align selected placements to group anchor x' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements?.map((placement) => [placement.nodeId, placement.x])).toEqual([['n1', 3], ['n2', 3], ['n3', 7]]);
    expect(history.undo()).toBe(true);
    store.doc = history.current();
    expect(history.current().floorplan?.placements?.map((placement) => [placement.nodeId, placement.x])).toEqual([['n1', 1], ['n2', 4], ['n3', 7]]);
    fireEvent.change(screen.getByLabelText('group anchor y'), { target: { value: '3.24' } });
    fireEvent.click(screen.getByRole('button', { name: 'align selected placements to group anchor y' }));
    rerender(<FloorplanPreview store={store} />);
    expect(history.current().floorplan?.placements?.map((placement) => [placement.nodeId, placement.y])).toEqual([['n1', 3], ['n2', 3], ['n3', 9]]);
    expect(history.undo()).toBe(true);
    expect(history.current().floorplan?.placements?.map((placement) => [placement.nodeId, placement.y])).toEqual([['n1', 1], ['n2', 5], ['n3', 9]]);
  });
  it('shows a per-pair route reachability audit for allowed firewall rules', () => {
    const store = storeWithMapping();
    store.doc.firewall = { default: 'deny', rules: [{ src: 'n1', dst: 'n3', perm: 'RW' }] };
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FirewallEditor store={store} />);
    expect(screen.getByText('Allowed route reachability: 0 valid / 1 errors')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('routing policy'), { target: { value: 'xy' } });
    rerender(<FirewallEditor store={store} />);
    expect(screen.getByText('Allowed route reachability: 1 valid / 0 errors')).toBeTruthy();
    fireEvent.click(screen.getByText('Allowed route reachability: 1 valid / 0 errors'));
    expect(screen.getByText(/n1 → n3 \(RW\): n1 → n2 → n3/)).toBeTruthy();
  });
  it('selects serialized Odd-Even policy and previews an Odd-Even-legal route', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FirewallEditor store={store} />);
    fireEvent.change(screen.getByLabelText('routing policy'), { target: { value: 'odd_even' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Expand (16 nodes)' }));
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n1 to n16: DENY' }));
    rerender(<FirewallEditor store={store} />);
    expect(history.current().routing).toEqual({ policy: 'odd_even' });
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('Odd-Even routed path:');
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('ODD_EVEN_TURN_MODEL_SHORTEST');
    expect(parseProject(serializeProject(history.current())).routing).toEqual({ policy: 'odd_even' });
  });
  it('edits a custom next-hop table, blocks invalid drafts, and previews the applied route', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FirewallEditor store={store} />);
    fireEvent.change(screen.getByLabelText('routing policy'), { target: { value: 'custom' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Next-hop rule' }));
    rerender(<FirewallEditor store={store} />);
    expect((screen.getByRole('button', { name: 'Apply custom routing table' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('route source 0'), { target: { value: 'n1' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.change(screen.getByLabelText('route destination 0'), { target: { value: 'n3' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.change(screen.getByLabelText('route next hop 0'), { target: { value: 'n2' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Next-hop rule' }));
    rerender(<FirewallEditor store={store} />);
    fireEvent.change(screen.getByLabelText('route source 1'), { target: { value: 'n2' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.change(screen.getByLabelText('route destination 1'), { target: { value: 'n3' } });
    rerender(<FirewallEditor store={store} />);
    fireEvent.change(screen.getByLabelText('route next hop 1'), { target: { value: 'n3' } });
    rerender(<FirewallEditor store={store} />);
    expect((screen.getByRole('button', { name: 'Apply custom routing table' }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Apply custom routing table' }));
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n1 to n3: DENY' }));
    rerender(<FirewallEditor store={store} />);
    expect(history.current().routing).toEqual({ policy: 'custom', rules: [
      { src: 'n1', dst: 'n3', nextHop: 'n2' }, { src: 'n2', dst: 'n3', nextHop: 'n3' },
    ] });
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('Custom routed path:');
    expect(screen.getByLabelText('Firewall cell inspector').textContent).toContain('AUTHORED_NEXT_HOP_TABLE');
    expect(parseProject(serializeProject(history.current())).routing).toEqual(history.current().routing);
  });
  it('does not offer XY as an enabled policy for unsupported graph shapes', () => {
    const store = storeWithMapping();
    store.doc = buildPreset('ring-8');
    render(<FirewallEditor store={store} />);
    expect(((screen.getByLabelText('routing policy') as HTMLSelectElement).querySelector('option[value="xy"]') as HTMLOptionElement).disabled).toBe(true);
    expect(((screen.getByLabelText('routing policy') as HTMLSelectElement).querySelector('option[value="west_first"]') as HTMLOptionElement).disabled).toBe(true);
  });
  it('displays precise firewall conflict diagnostics', () => {
    render(<FirewallEditor store={storeWithMapping(true)} />);
    expect(screen.getByLabelText('Firewall rule conflicts').textContent).toContain('indices 0 and 1');
    expect(screen.getByLabelText('Firewall rule conflicts').textContent).toContain('conflicting RO/RW');
  });
  it('surfaces firewall rules that cannot match graph nodes with exact rule references', () => {
    const store = storeWithMapping();
    store.doc.firewall = { default: 'deny', rules: [{ src: 'missing-node', dst: 'n1', perm: 'RW' }] };
    render(<FirewallEditor store={store} />);
    const diagnostics = screen.getByLabelText('Firewall rule conflicts').textContent ?? '';
    expect(diagnostics).toContain('Invalid rule at index 0');
    expect(diagnostics).toContain('source missing-node is not a graph node; rule cannot match');
  });
  it('surfaces malformed firewall block shape without crashing the cell matrix', () => {
    render(<FirewallEditor store={storeWithMapping(false, true)} />);
    expect(screen.getByLabelText('Firewall rule conflicts').textContent).toContain('firewall.rules must be an array');
  });
  it('applies explicit deny-by-default in one undoable graph-history command', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    const before = JSON.stringify(history.current());
    store.run = (command) => history.apply(command).refused;
    render(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Deny by default' }));
    expect(history.current().firewall).toEqual({ default: 'deny', rules: [] });
    expect(history.canUndo()).toBe(true);
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
  });
  it('applies allow-all in one undoable graph-history command', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    const before = JSON.stringify(history.current());
    store.run = (command) => history.apply(command).refused;
    render(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Allow all (all graph nodes)' }));
    expect((history.current().firewall?.rules as unknown[])).toHaveLength(16 * 15);
    expect(history.canUndo()).toBe(true);
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
  });
  it('writes deterministic firewall JSON from matrix edits without selected-cell view state', () => {
    const store = storeWithMapping();
    store.doc.firewall = { default: 'deny', rules: [] };
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n2 to n1: DENY' }));
    rerender(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n1 to n3: DENY' }));
    rerender(<FirewallEditor store={store} />);
    const firewall = history.current().firewall;
    expect(firewall).toEqual({ default: 'deny', rules: [
      { src: 'n1', dst: 'n3', perm: 'RO' }, { src: 'n2', dst: 'n1', perm: 'RO' },
    ] });
    expect(Object.keys(firewall ?? {}).sort()).toEqual(['default', 'rules']);
    const serialized = serializeProject(history.current());
    expect(serializeProject(history.current())).toBe(serialized);
    expect(JSON.parse(serialized)).not.toHaveProperty('selectedCell');
    expect(JSON.parse(serialized).firewall).toEqual(firewall);
  });
  it('applies a selected firewall row through one graph-history command', () => {
    const store = storeWithMapping();
    const commands: unknown[] = [];
    store.run = (command) => { commands.push(command); return null; };
    render(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Set row RW' }));
    expect(commands).toHaveLength(1);
    expect(commands[0]).toMatchObject({ type: 'set_firewall', firewall: { default: 'deny', rules: expect.any(Array) } });
    expect((commands[0] as { firewall: { rules: unknown[] } }).firewall.rules).toHaveLength(15);
  });
  it('inspects an explicit firewall rule alongside the policy-routed path', () => {
    const store = storeWithMapping();
    store.doc.firewall = { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'RW' }] };
    store.doc.routing = { policy: 'xy' };
    render(<FirewallEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'n1 to n2: RW' }));
    const inspector = screen.getByLabelText('Firewall cell inspector').textContent ?? '';
    expect(inspector).toContain('Matched rule: {"src":"n1","dst":"n2","perm":"RW"}');
    expect(inspector).toContain('Permission: RW · precedence: explicit rule');
    expect(inspector).toContain('XY routed path: n1 —e1→ n2');
    expect(inspector).toContain('ports unassigned→unassigned; VC ');
    expect(inspector).toContain('provenance XY_MESH_DIMENSION_ORDER');
  });
  it('shows selected firewall cell permission and explicit default-deny provenance', () => {
    render(<FirewallEditor store={storeWithMapping()} />);
    fireEvent.click(screen.getByRole('button', { name: 'n1 to n2: DENY' }));
    const inspector = screen.getByLabelText('Firewall cell inspector').textContent ?? '';
    expect(inspector).toContain('n1 → n2');
    expect(inspector).toContain('precedence: default deny');
    expect(inspector).toContain('Topology connectivity only (not routed)');
    expect(inspector).toContain('provenance LOCAL_BFS_CONNECTIVITY_ONLY');
    expect(inspector).toContain('ports unassigned→unassigned');
  });
  it('creates, edits, reorders, removes and serializes authored phases with cycle timing', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Phase' }));
    let phases = history.current().workload?.phases as { id: string }[];
    expect(phases).toHaveLength(2);
    const added = phases[1]!.id;
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`tokens ${added}`), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain(`phases[1].tokens`);
    fireEvent.change(screen.getByLabelText(`tokens ${added}`), { target: { value: '1024' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`phase batch ${added}`), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain(`phases[1].batch`);
    fireEvent.change(screen.getByLabelText(`phase batch ${added}`), { target: { value: '16' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`name ${added}`), { target: { value: 'Steady' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`kind ${added}`), { target: { value: 'prefill' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`start cycle ${added}`), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`duration cycles ${added}`), { target: { value: '100' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Authored phase cycle timeline').textContent).toContain('Steady');
    fireEvent.click(screen.getByLabelText(`move ${added} up`));
    rerender(<WorkloadEditor store={store} />);
    phases = history.current().workload?.phases as { id: string }[];
    expect(phases[0]?.id).toBe(added);
    const originalRow = screen.getByLabelText('name phase-0').closest('.row') as HTMLElement;
    fireEvent.click(within(originalRow).getByRole('button', { name: 'Remove' }));
    rerender(<WorkloadEditor store={store} />);
    const saved = parseProject(serializeProject(history.current())).workload?.phases as { id: string; name?: string; kind: string; startCycle?: number; durationCycles?: number }[];
    expect(saved).toEqual([{ id: added, name: 'Steady', kind: 'prefill', tokens: 1024, batch: 16, tp: 1, ep: 1, pp: 1, dp: 1, startCycle: 0, durationCycles: 100 }]);
  });
  it('edits collective and custom communication kind, dimension, payload and name', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Communication operation' }));
    const id = (history.current().workload as { communications?: { id: string }[] } | undefined)?.communications?.[0]?.id;
    expect(id).toBeTruthy();
    rerender(<WorkloadEditor store={store} />);
    const kind = screen.getByLabelText(`operation kind ${id}`);
    expect(Array.from(kind.querySelectorAll('option')).map((option) => option.value)).toEqual(expect.arrayContaining(['allreduce', 'allgather', 'alltoall', 'reduce-scatter', 'custom']));
    for (const [index, value] of ['allreduce', 'allgather', 'alltoall', 'reduce-scatter', 'custom'].entries()) {
      fireEvent.change(kind, { target: { value } });
      rerender(<WorkloadEditor store={store} />);
      fireEvent.change(screen.getByLabelText(`operation dimension ${id}`), { target: { value: 'ep' } });
      rerender(<WorkloadEditor store={store} />);
      fireEvent.change(screen.getByLabelText(`payload bytes ${id}`), { target: { value: String(100 + index) } });
      rerender(<WorkloadEditor store={store} />);
      expect((history.current().workload as unknown as WorkloadBlock).communications?.[0]).toMatchObject({ kind: value, dimension: 'ep', payloadBytes: 100 + index });
    }
    fireEvent.change(screen.getByLabelText(`custom operation name ${id}`), { target: { value: 'ring-exchange' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`operation dimension ${id}`), { target: { value: 'custom' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`custom dimension name ${id}`), { target: { value: 'expert' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`payload bytes ${id}`), { target: { value: '2048' } });
    rerender(<WorkloadEditor store={store} />);
    const saved = parseProject(serializeProject(history.current())).workload?.communications;
    expect(saved).toEqual([{ id, kind: 'custom', customName: 'ring-exchange', dimension: 'custom', dimensionName: 'expert', payloadBytes: 2048, trafficClass: 'default' }]);
  });
  it('exports deterministic versioned workload JSON including rank mappings through the browser download action', async () => {
    const store = storeWithMapping();
    const createDescriptor = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
    const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:workload');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    vi.useFakeTimers();
    try {
      render(<WorkloadEditor store={store} />);
      fireEvent.click(screen.getByRole('button', { name: 'Export workload JSON' }));
      expect(anchorClick).toHaveBeenCalledOnce();
      expect(createObjectURL).toHaveBeenCalledOnce();
      const blob = createObjectURL.mock.calls[0]![0];
      const exported = JSON.parse(await blob.text()) as WorkloadBlock & { workloadSchemaVersion: number };
      expect(exported.workloadSchemaVersion).toBe(1);
      expect(exported.rankMappings).toEqual([{ rank: 0, role: 'worker', nodeId: 'n1' }]);
      expect(blob.type).toContain('application/json');
      vi.runOnlyPendingTimers();
    } finally {
      vi.useRealTimers();
      if (createDescriptor) Object.defineProperty(URL, 'createObjectURL', createDescriptor);
      else Reflect.deleteProperty(URL, 'createObjectURL');
      if (revokeDescriptor) Object.defineProperty(URL, 'revokeObjectURL', revokeDescriptor);
      else Reflect.deleteProperty(URL, 'revokeObjectURL');
    }
  });
  it('records only supported normalized precision enums without changing other workload data', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    const original = history.current().workload as unknown as WorkloadBlock;
    for (const precision of ['fp16', 'fp8', 'int8', 'bf16']) {
      fireEvent.change(screen.getByLabelText('precision'), { target: { value: precision } });
      rerender(<WorkloadEditor store={store} />);
      const current = history.current().workload as unknown as WorkloadBlock;
      expect(current.precision).toBe(precision);
      expect(current.phases).toEqual(original.phases);
      expect(current.rankMappings).toEqual(original.rankMappings);
      expect(current.communications).toEqual(original.communications);
    }
    expect(JSON.parse(serializeProject(history.current())).workload.precision).toBe('bf16');
    expect(validateWorkload({ ...original, precision: 'fp32' }, store.doc.nodes.length, store.doc.nodes.map((node) => node.id))
      .map((i) => i.message))
      .toContain('precision: unsupported value fp32');
  });
  it('imports valid workload JSON and rejects localized schema errors without coercion', async () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const initial = store.doc.workload as unknown as WorkloadBlock;
    const uploaded = { ...initial, modelFamily: 'imported-workload' };
    render(<WorkloadEditor store={store} />);
    const input = screen.getByLabelText('import workload JSON');
    const validFile = new File([serializeWorkloadJson(uploaded)], 'valid.json', { type: 'application/json' });
    fireEvent.change(input, { target: { files: [validFile] } });
    await waitFor(() => expect(screen.getByText('Imported valid.json')).toBeTruthy());
    expect((history.current().workload as unknown as WorkloadBlock).modelFamily).toBe('imported-workload');
    const invalid = { ...uploaded, seqLen: '16' };
    const invalidFile = new File([JSON.stringify(invalid)], 'bad.json', { type: 'application/json' });
    fireEvent.change(input, { target: { files: [invalidFile] } });
    await waitFor(() => expect(screen.getByText(/Import rejected:.*\$\.seqLen: must be a number/)).toBeTruthy());
    expect((history.current().workload as unknown as WorkloadBlock).modelFamily).toBe('imported-workload');
    expect((history.current().workload as unknown as WorkloadBlock).seqLen).toBe(16);
  });
  it('keeps unknown model-shape metadata optional and validates supplied ranges', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('parameter count billions'), { target: { value: '' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('hidden size'), { target: { value: '' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('layer count'), { target: { value: '' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.queryByLabelText('Workload validation issues')).toBeNull();
    expect(screen.getByText(/parameter count unknown/)).toBeTruthy();
    const unknownShape = parseProject(serializeProject(history.current())).workload as unknown as WorkloadBlock;
    expect(unknownShape.paramsB).toBeUndefined();
    expect(parseWorkloadJson(serializeWorkloadJson(unknownShape), store.doc.nodes.map((node) => node.id)).issues).toEqual([]);
    fireEvent.change(screen.getByLabelText('parameter count billions'), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain('paramsB: must be a positive finite number');
    fireEvent.change(screen.getByLabelText('parameter count billions'), { target: { value: '' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('hidden size'), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain('hiddenSize: must be a positive integer when set');
    fireEvent.change(screen.getByLabelText('hidden size'), { target: { value: '' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('layer count'), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain('layerCount: must be a positive integer when set');
  });
  it('validates TP/EP product demand against graph and explicitly mapped node seats', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('tp phase-0'), { target: { value: '5' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('ep phase-0'), { target: { value: '4' } });
    rerender(<WorkloadEditor store={store} />);
    const issues = screen.getByLabelText('Workload validation issues').textContent ?? '';
    expect(issues).toContain('parallelism needs 20 nodes but the graph has 16');
    expect(issues).toContain('parallelism needs 20 mapped rank seats but only 1 are assigned');
    expect((screen.getByRole('button', { name: 'Auto-map ranks' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Export validated run intent' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByRole('status').some((status) => status.textContent?.includes('BLOCKED'))).toBe(true);
  });
  it('records Dense/MoE/custom family and model name as descriptive metadata only', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    const initial = JSON.stringify(history.current().workload);
    for (const family of ['dense', 'moe', 'custom']) {
      fireEvent.change(screen.getByLabelText('model family'), { target: { value: family } });
      rerender(<WorkloadEditor store={store} />);
      expect((history.current().workload as unknown as WorkloadBlock).modelFamily).toBe(family);
      const now = history.current().workload as unknown as WorkloadBlock;
      const baseline = JSON.parse(initial) as WorkloadBlock;
      expect(now.phases).toEqual(baseline.phases);
      expect(now.communications).toEqual(baseline.communications);
    }
    fireEvent.change(screen.getByLabelText('model name'), { target: { value: 'Example 70B' } });
    rerender(<WorkloadEditor store={store} />);
    const saved = parseProject(serializeProject(history.current())).workload as unknown as WorkloadBlock;
    expect(saved.modelName).toBe('Example 70B');
    expect(saved.modelFamily).toBe('custom');
    expect(saved.phases).toEqual((JSON.parse(initial) as WorkloadBlock).phases);
  });
  it('manually reassigns a rank to a graph node and immediately revalidates mapping', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('mapping node 0'), { target: { value: 'n2' } });
    rerender(<WorkloadEditor store={store} />);
    expect((history.current().workload as unknown as WorkloadBlock).rankMappings).toEqual([{ rank: 0, role: 'worker', nodeId: 'n2' }]);
    expect(screen.queryByLabelText('Workload validation issues')).toBeNull();
    fireEvent.change(screen.getByLabelText('tp phase-0'), { target: { value: '2' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Rank mapping' }));
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('mapping node 1'), { target: { value: 'n2' } });
    rerender(<WorkloadEditor store={store} />);
    expect(screen.getByLabelText('Workload validation issues').textContent).toContain('graph node n2 already assigned to rank 0');
  });
  it('auto-maps ranks deterministically under the chosen policy as one undoable operation', () => {
    const store = storeWithMapping();
    const workload = store.doc.workload as unknown as WorkloadBlock;
    workload.phases[0]!.tp = 2;
    workload.rankMappings = [];
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    // Default policy: graph order.
    expect((screen.getByLabelText('rank assignment policy') as HTMLSelectElement).value).toBe('graph-order');
    fireEvent.click(screen.getByRole('button', { name: 'Auto-map ranks' }));
    const nodes = store.doc.nodes.map((node) => node.id);
    expect(history.current().workload?.rankMappings).toEqual([
      { rank: 0, role: 'rank', nodeId: nodes[0] },
      { rank: 1, role: 'rank', nodeId: nodes[1] },
    ]);
    expect(history.canUndo()).toBe(true);
    expect(history.undo()).toBe(true);
    expect(history.current().workload?.rankMappings).toEqual([]);
    // Chosen policy: spread. Deterministic and distinct from graph order when
    // the node list is larger than the rank demand.
    fireEvent.change(screen.getByLabelText('rank assignment policy'), { target: { value: 'spread' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'Auto-map ranks' }));
    const spread = [
      { rank: 0, role: 'rank', nodeId: nodes[0] },
      { rank: 1, role: 'rank', nodeId: nodes[Math.floor(nodes.length / 2)] },
    ];
    expect(history.current().workload?.rankMappings).toEqual(spread);
    expect(spread[1]!.nodeId).not.toBe(nodes[1]);
    // Re-running the same policy reproduces the same table.
    history.undo();
    fireEvent.click(screen.getByRole('button', { name: 'Auto-map ranks' }));
    expect(history.current().workload?.rankMappings).toEqual(spread);
  });
  it('reports the workload×backend preflight before any run (supported / unsupported / blocked)', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    const preflight = (): string => screen.getByLabelText('workload backend preflight').textContent ?? '';
    expect(preflight()).toContain('SUPPORTED');
    // Authored phase timing with a backend that declares it ignores timing -> UNSUPPORTED.
    fireEvent.change(screen.getByLabelText('start cycle phase-0'), { target: { value: '0' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('duration cycles phase-0'), { target: { value: '10' } });
    rerender(<WorkloadEditor store={store} />);
    expect(preflight()).toContain('UNSUPPORTED');
    expect(preflight()).toContain('workload.backend.phase_cycles');
    // An invalid workload is BLOCKED, never merely unsupported.
    fireEvent.change(screen.getByLabelText('tp phase-0'), { target: { value: '20' } });
    rerender(<WorkloadEditor store={store} />);
    expect(preflight()).toContain('BLOCKED');
  });
  it('inserts a TP/EP MoE skeleton without assuming collective or dispatch/combine semantics', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: 'MoE TP/EP skeleton' }));
    rerender(<WorkloadEditor store={store} />);
    const saved = parseProject(serializeProject(history.current())).workload as { modelFamily: string; communications: { id: string; kind: string; dimension: string; payloadBytes: number; trafficClass: string; customName?: string }[] };
    expect(saved.modelFamily).toBe('moe');
    expect(saved.communications).toEqual([
      { id: 'moe-tp-operation', kind: 'custom', dimension: 'tp', payloadBytes: 0, trafficClass: '', customName: '' },
      { id: 'moe-ep-operation', kind: 'custom', dimension: 'ep', payloadBytes: 0, trafficClass: '', customName: '' },
    ]);
  });
  it('authors point-to-point source/target references and payload as a distinct operation', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.click(screen.getByRole('button', { name: '+ Communication operation' }));
    const id = (history.current().workload as { communications?: { id: string }[] } | undefined)?.communications?.[0]?.id;
    expect(id).toBeTruthy();
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`operation kind ${id}`), { target: { value: 'point-to-point' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`source node ${id}`), { target: { value: 'n1' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`target node ${id}`), { target: { value: 'n2' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText(`payload bytes ${id}`), { target: { value: '4096' } });
    rerender(<WorkloadEditor store={store} />);
    const saved = parseProject(serializeProject(history.current())).workload?.communications;
    expect(saved).toEqual([{ id, kind: 'point-to-point', dimension: 'tp', payloadBytes: 4096, trafficClass: 'default', sourceNodeId: 'n1', targetNodeId: 'n2' }]);
  });
  it('edits rank role/node IDs and round-trips the explicit mapping through project JSON', () => {
    const store = storeWithMapping();
    const history = new GraphHistory(store.doc);
    store.run = (command) => {
      const outcome = history.apply(command);
      store.doc = history.current();
      return outcome.refused;
    };
    const { rerender } = render(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('mapping role 0'), { target: { value: 'trainer' } });
    rerender(<WorkloadEditor store={store} />);
    fireEvent.change(screen.getByLabelText('mapping node 0'), { target: { value: 'n2' } });
    rerender(<WorkloadEditor store={store} />);
    expect(history.current().workload?.rankMappings).toEqual([{ rank: 0, role: 'trainer', nodeId: 'n2' }]);
    const roundTrip = parseProject(serializeProject(history.current()));
    expect(roundTrip.workload?.rankMappings).toEqual([{ rank: 0, role: 'trainer', nodeId: 'n2' }]);
  });
  it('search-filters rank mappings by rank, role, or graph node', () => {
    const store = storeWithMapping();
    render(<WorkloadEditor store={store} />);
    const filter = screen.getByLabelText('filter rank mappings');
    expect(screen.getByLabelText('mapping rank 0')).toBeTruthy();
    fireEvent.change(filter, { target: { value: 'n2' } });
    expect(screen.queryByLabelText('mapping rank 0')).toBeNull();
    fireEvent.change(filter, { target: { value: 'worker' } });
    expect(screen.getByLabelText('mapping rank 0')).toBeTruthy();
  });
  it('renders rank labels on authored nodes and cross-probes node selection to a mapping row', () => {
    render(<WorkloadEditor store={storeWithMapping()} />);
    const node = screen.getByRole('button', { name: 'n1: r0:worker' });
    expect(screen.getByLabelText('Rank mapping overlay on authored graph')).toBeTruthy();
    expect(screen.getByLabelText('Workload summary')).toBeTruthy();
    expect(screen.getByLabelText('Authored phase cycle timeline')).toBeTruthy();
    expect(screen.getByText(/Run status: BLOCKED/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('mapping rank 0').closest('.row')!);
    expect(node.querySelector('rect')?.getAttribute('fill')).toBe('var(--accent)');
    fireEvent.click(node);
    expect(screen.getByLabelText('mapping rank 0').closest('.row')?.className).toContain('selected');
    expect((screen.getByLabelText('name phase-0') as HTMLInputElement).value).toBe('Prefill');
  });
});
