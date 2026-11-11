import { describe, expect, it } from 'vitest';
import { deadlockFacts, routerConfiguration } from './routerConfig';
import type { CompileResult } from './gateway';

const result: CompileResult = {
  groups: {
    resources: {
      arbitration: {
        allocator_iterations: 1,
        flow_control: 'credit',
        input_buffer_depth_flits_per_vc: 8,
        input_vc_packet_policy: 'one_packet_at_a_time',
        output_stage_depth_flits_per_vc: 1,
        switch_allocator: 'islip',
        vc_allocator: 'islip',
      },
      deadlock: {
        status: 'PASS',
        method: 'channel-vc-cdg/v2',
        witness: {
          acyclic: true,
          sccs_gt_1: 0,
          node_count: 288,
          edge_count: 508,
          cdg_route_classes: ['DOR_XY'],
          escape_vcs: [],
          vc_count: 1,
          route_realization_scheme: 'v2_channel_id',
        },
      },
      vc_count: 1,
      traffic_class_to_vcs: [['tp_collective', [0]], ['ep_dispatch', [0]]],
      vc_to_routing_class: [[0, 'DOR_XY']],
    },
  },
};

describe('router configuration comes from the compile result', () => {
  it('reports the derived router class facts without inventing defaults', () => {
    const facts = routerConfiguration(result);
    expect(facts).toContainEqual({ label: 'Virtual channels', value: '1 per port' });
    expect(facts).toContainEqual({ label: 'Input buffer', value: '8 flits / VC' });
    expect(facts).toContainEqual({ label: 'VC allocator', value: 'islip' });
    expect(facts).toContainEqual({ label: 'Traffic class → VC', value: 'tp_collective: 0 · ep_dispatch: 0' });
  });

  it('returns nothing when the compile result has no resources', () => {
    expect(routerConfiguration(null)).toEqual([]);
    expect(routerConfiguration({ groups: {} })).toEqual([]);
    expect(deadlockFacts(null)).toEqual([]);
  });

  it('does not claim a buffer depth that was not reported', () => {
    const sparse: CompileResult = { groups: { resources: { vc_count: 2, arbitration: null } } };
    expect(routerConfiguration(sparse)).toEqual([{ label: 'Virtual channels', value: '2 per port' }]);
  });

  it('renders the deadlock witness as proof facts', () => {
    const facts = deadlockFacts(result);
    expect(facts).toContainEqual({ label: 'Status', value: 'PASS' });
    expect(facts).toContainEqual({ label: 'Cycle', value: 'none' });
    expect(facts).toContainEqual({ label: 'CDG nodes', value: '288' });
    expect(facts).toContainEqual({ label: 'Escape VCs', value: 'none' });
  });

  it('reads a shared-resource proof from evidence when the witness is null', () => {
    const shared: CompileResult = {
      groups: {
        resources: {
          deadlock: {
            status: 'PASS',
            method: 'shared-resource-cdg/v1',
            witness: {
              acyclic: null as unknown as undefined,
              node_count: null as unknown as undefined,
              edge_count: null as unknown as undefined,
            },
            evidence: {
              nodes: 80,
              edges: 72,
              cycle: [],
              proof_method: 'CHANNEL_VC_DEPENDENCY_ACYCLIC',
            },
          },
        },
      },
    };
    const facts = deadlockFacts(shared);
    expect(facts).toContainEqual({ label: 'Cycle', value: 'none' });
    expect(facts).toContainEqual({ label: 'CDG nodes', value: '80' });
    expect(facts).toContainEqual({ label: 'Proof method', value: 'CHANNEL_VC_DEPENDENCY_ACYCLIC' });
    expect(facts.some(f => f.value === 'no')).toBe(false);
  });
});
