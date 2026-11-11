import { describe, expect, it } from 'vitest';
import { PARALLEL_AXES, axisDegree, parallelColor, parallelGroups } from './parallelism';
import type { MappingRow } from './gateway';

const row = (rank: number, endpoint: number, tp: number, ep: number): MappingRow => ({
  rank,
  endpoint_id: endpoint,
  agent_kind: 'compute_tile',
  group_index: 0,
  instance_index: rank,
  coordinates: { tp, dp: 0, ep, pp: 0 },
});

const rows = [row(0, 10, 0, 0), row(1, 11, 1, 0), row(2, 12, 0, 1), row(3, 13, 1, 1)];
const endpointRouter = new Map([[10, 0], [11, 0], [12, 1], [13, 1]]);

describe('parallelism mapping helpers', () => {
  it('exposes exactly the four compiler axes', () => {
    expect(PARALLEL_AXES).toEqual(['tp', 'dp', 'ep', 'pp']);
  });

  it('falls back to degree one rather than zero', () => {
    expect(axisDegree(null, 'tp')).toBe(1);
    expect(axisDegree({ tp: 8, dp: 1, ep: 4, pp: 1 }, 'tp')).toBe(8);
    expect(axisDegree({ tp: 8, dp: 0, ep: 4, pp: 1 }, 'dp')).toBe(1);
  });

  it('groups ranks and routers by the selected axis without inventing membership', () => {
    const tp = parallelGroups(rows, endpointRouter, 'tp');
    expect(tp).toEqual([
      { coordinate: 0, ranks: 2, routers: [0, 1] },
      { coordinate: 1, ranks: 2, routers: [0, 1] },
    ]);
    const ep = parallelGroups(rows, endpointRouter, 'ep');
    expect(ep.map(group => [group.coordinate, group.ranks])).toEqual([[0, 2], [1, 2]]);
  });

  it('keeps a rank whose endpoint has no router out of the router list', () => {
    const groups = parallelGroups([row(0, 99, 3, 0)], new Map(), 'tp');
    expect(groups).toEqual([{ coordinate: 3, ranks: 1, routers: [] }]);
  });

  it('produces a stable distinct colour per coordinate', () => {
    expect(parallelColor(0, 4)).not.toBe(parallelColor(1, 4));
    expect(parallelColor(1, 4)).toBe(parallelColor(1, 4));
    expect(parallelColor(4, 4)).toBe(parallelColor(0, 4));
  });
});
