/** Virtual-channel and QoS operations (M3-06/M3-07/M3-09). Pure over the typed
 *  `vcConfig`; references are kept consistent when a VC or class is removed. */
import { describe, expect, it } from 'vitest';
import {
  emptyVcConfig, nextVcId, removeVc, renameTrafficClass, setArbitrationPolicy,
  setArbitrationValue, setTrafficClassRow, upsertVc,
} from '../graph/vcConfig';
import type { VcConfigV1 } from '../graph/project';

const seeded = (): VcConfigV1 => ({
  virtualChannels: [
    { id: 'vc0', depth: 4, class: 'data', escape: false },
    { id: 'vc1', depth: 8, class: 'control', escape: true },
  ],
  trafficClassMap: [
    { trafficClass: 'req', vcId: 'vc0', qos: 1 },
    { trafficClass: 'rsp', vcId: 'vc1' },
  ],
  arbitration: { policy: 'fixed_priority', priorityByTrafficClass: { req: 2, rsp: 1 } },
});

describe('vc ops: channels', () => {
  it('mints the next free vc id', () => {
    expect(nextVcId(emptyVcConfig())).toBe('vc0');
    expect(nextVcId(seeded())).toBe('vc2');
  });

  it('adds a channel and replaces one with the same id', () => {
    const added = upsertVc(emptyVcConfig(), { id: 'vc0', depth: 4, class: 'data', escape: false });
    expect(added.virtualChannels).toEqual([{ id: 'vc0', depth: 4, class: 'data', escape: false }]);
    const replaced = upsertVc(added, { id: 'vc0', depth: 16, class: 'data', escape: true });
    expect(replaced.virtualChannels).toEqual([{ id: 'vc0', depth: 16, class: 'data', escape: true }]);
  });

  it('removing a channel drops its class rows and prunes arbitration', () => {
    const next = removeVc(seeded(), 'vc1');
    expect(next.virtualChannels.map((vc) => vc.id)).toEqual(['vc0']);
    expect(next.trafficClassMap).toEqual([{ trafficClass: 'req', vcId: 'vc0', qos: 1 }]);
    expect(next.arbitration.priorityByTrafficClass).toEqual({ req: 2 });
  });
});

describe('vc ops: traffic classes', () => {
  it('sets and clears a class mapping', () => {
    const set = setTrafficClassRow(emptyVcConfig(), 'req', 'vc0', 3);
    expect(set.trafficClassMap).toEqual([{ trafficClass: 'req', vcId: 'vc0', qos: 3 }]);
    const cleared = setTrafficClassRow(set, 'req', '');
    expect(cleared.trafficClassMap).toEqual([]);
  });

  it('renames a class, carrying the mapping and arbitration entries', () => {
    const renamed = renameTrafficClass(seeded(), 'req', 'request');
    expect(renamed.trafficClassMap.map((r) => r.trafficClass)).toEqual(['request', 'rsp']);
    expect(renamed.arbitration.priorityByTrafficClass).toEqual({ request: 2, rsp: 1 });
  });
});

describe('vc ops: arbitration', () => {
  it('keeps only the map the chosen policy uses', () => {
    const weighted = setArbitrationPolicy(seeded(), 'weighted_round_robin');
    expect(weighted.arbitration).toEqual({ policy: 'weighted_round_robin' });
    const roundRobin = setArbitrationPolicy(weighted, 'round_robin');
    expect(roundRobin.arbitration).toEqual({ policy: 'round_robin' });
  });

  it('sets and clears one priority or weight value', () => {
    const withWeight = setArbitrationValue(seeded(), 'weightByTrafficClass', 'req', 5);
    expect(withWeight.arbitration.weightByTrafficClass).toEqual({ req: 5 });
    expect(withWeight.arbitration.priorityByTrafficClass).toEqual({ req: 2, rsp: 1 });
    const cleared = setArbitrationValue(withWeight, 'weightByTrafficClass', 'req', null);
    expect(cleared.arbitration.weightByTrafficClass).toBeUndefined();
  });
});
