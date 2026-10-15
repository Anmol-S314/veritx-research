import { describe, expect, it } from 'vitest';
import { GraphHistory, type GraphCommand } from '../graph/history';
import { buildPreset } from '../graph/presets';

const link = (id: string, src: string, dst: string) => ({
  id, src, dst, width: 512, pipelineStages: 1, vcClass: 0,
});

const reversibleCommands = {
  move_node: () => ({ type: 'move_node', id: 'n1', x: 123, y: 456 }),
  delete_nodes: () => ({ type: 'delete_nodes', ids: ['n1'] }),
  update_nodes: () => ({ type: 'update_nodes', updates: [{ id: 'n1', patch: { role: 'nic' } }] }),
  load_project: () => ({ type: 'load_project', project: buildPreset('mesh-4x4') }),
  set_routing: () => ({ type: 'set_routing', routing: { policy: 'custom', rules: [] } }),
  set_floorplan: () => ({ type: 'set_floorplan', floorplan: { unit: 'um', die: { originX: 0, originY: 0, width: 10, height: 10 } } }),
  delete_node: () => ({ type: 'delete_node', id: 'n1' }),
  update_node: () => ({ type: 'update_node', id: 'n1', patch: { role: 'nic', ports: 6 } }),
  add_edge: () => ({ type: 'add_edge', edge: link('undo-edge', 'n1', 'n3') }),
  delete_edge: () => ({ type: 'delete_edge', id: 'e1' }),
  update_edge: () => ({ type: 'update_edge', id: 'e1', patch: { width: 1024, pipelineStages: 2 } }),
  paste: () => ({
    type: 'paste',
    nodes: [{ id: 'undo-node', x: 900, y: 900, role: 'nic', ports: 2 }],
    edges: [link('undo-paste-edge', 'n1', 'undo-node')],
  }),
  set_workload: () => ({ type: 'set_workload', workload: { modelFamily: 'unit-test', seqLen: 1, batch: 1, precision: 'fp16', phases: [] } }),
  set_firewall: () => ({ type: 'set_firewall', firewall: { default: 'deny', rules: [{ src: 'n1', dst: 'n2', perm: 'RO' }] } }),
  paste_remapped: () => ({
    type: 'paste_remapped',
    nodes: [{ id: 'undo-remap', x: 900, y: 900, role: 'nic', ports: 2 }],
    edges: [link('undo-remap-edge', 'n1', 'undo-remap')],
    idMap: {},
  }),
  batch: () => ({ type: 'batch', commands: [{ type: 'move_node', id: 'n1', x: 1, y: 2 }] }),
  set_metadata: () => ({ type: 'set_metadata', metadata: { name: 'undo-metadata', tags: ['unit'] } }),
  set_agents: () => ({ type: 'set_agents', agents: [{ id: 'agent-undo', nodeId: 'n1', role: 'initiator', protocol: 'AXI4', capabilities: ['read'], ports: [] }] }),
  set_domains: () => ({
    type: 'set_domains',
    domains: {
      clocks: [{ id: 'clk_core', frequencyHz: 1_000_000_000, source: null }],
      resets: [{ id: 'rst_n', polarity: 'active_low', asynchronous: true }],
      powers: [{ id: 'pd_core', nominalVoltageV: 0.8, canPowerOff: true }],
      portAssignments: [{ nodeId: 'n1', portId: 'p1', clockDomainId: 'clk_core' }],
    },
  }),
  replace_project: () => ({ type: 'replace_project', doc: buildPreset('mesh-4x4') }),
  revert: () => ({ type: 'revert', doc: buildPreset('mesh-4x4') }),
} satisfies Record<Exclude<GraphCommand['type'], 'add_node'>, () => GraphCommand>;

describe('graph command undo/redo exact restoration', () => {
  it.each(Object.entries(reversibleCommands))('%s restores exact prior snapshot and replays exactly', (_name, makeCommand) => {
    const history = new GraphHistory(buildPreset('ring-8'));
    const before = JSON.stringify(history.current());
    const applied = history.apply(makeCommand());
    expect(applied.refused).toBeNull();
    const after = JSON.stringify(history.current());
    expect(after).not.toBe(before);
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
    expect(history.redo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(after);
  });

  it('add_node restores the exact empty-project snapshot and replays exactly', () => {
    const history = new GraphHistory({ schemaVersion: 1, compilerSemanticsVersion: 1, presetHint: null, nodes: [], edges: [] });
    const before = JSON.stringify(history.current());
    const applied = history.apply({
      type: 'add_node', node: { id: 'first', x: 0, y: 0, role: 'nic', ports: 2 },
    });
    expect(applied.refused).toBeNull();
    const after = JSON.stringify(history.current());
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
    expect(history.redo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(after);
  });

  it('an isolated add_node in a nonempty graph is held as a warning and is one undo step', () => {
    const history = new GraphHistory(buildPreset('ring-8'));
    const before = JSON.stringify(history.current());
    expect(history.apply({
      type: 'add_node', node: { id: 'isolated', x: 0, y: 0, role: 'nic', ports: 2 },
    }).refused).toBeNull();
    expect(JSON.stringify(history.current())).not.toBe(before);
    expect(history.canUndo()).toBe(true);
    expect(history.undo()).toBe(true);
    expect(JSON.stringify(history.current())).toBe(before);
  });
});
