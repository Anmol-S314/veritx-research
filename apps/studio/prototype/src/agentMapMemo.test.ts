import { describe, expect, it } from 'vitest';
import {
  hasUnsavedAgentMap, memoizedRangesJson, memoizedSavedRangesJson,
  windowsFromRequest, windowsToRequest, type AddressWindow,
} from './agentMap';

const agents = [
  { kind: 'compute_tile', count: 2, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: null, power_domain: null },
  { kind: 'hbm_controller', count: 1, data_width: 512, addr_width: 48, protocol: 'CHI', clock_domain: null, power_domain: null },
];

const windows: AddressWindow[] = [
  { id: 'w1', name: 'HBM0', base: 0x1000n, size: 0x1000n, targetAgentIdx: 1,
    selectionPolicy: null, targetInstanceIndex: null, interleaveBytes: null },
];

const request = { agents: [{ kind: 'compute_tile', count: 2, data_width: 256, addr_width: 64, protocol: 'AXI' }, { kind: 'hbm_controller', count: 1, data_width: 512, addr_width: 48, protocol: 'CHI' }],
                  address_map: { ranges: [{ name: 'HBM0', base: 4096, size: 4096, target_agent_idx: 1 }] } };

describe('memoized canonical ranges', () => {
  it('returns the same bytes as the direct serialization', () => {
    expect(memoizedRangesJson(windows)).toBe(JSON.stringify(windowsToRequest(windows)));
    expect(memoizedSavedRangesJson(request, agents))
      .toBe(JSON.stringify(windowsToRequest(windowsFromRequest(request, agents))));
  });

  it('serves repeated calls from cache without changing results', () => {
    expect(memoizedRangesJson(windows)).toBe(memoizedRangesJson(windows));
    expect(memoizedSavedRangesJson(request, agents)).toBe(memoizedSavedRangesJson(request, agents));
  });

  it('keeps hasUnsavedAgentMap semantics identical to the unmemoized form', () => {
    expect(hasUnsavedAgentMap(agents, windows, request)).toBe(false);
    expect(hasUnsavedAgentMap(agents, [...windows, { ...windows[0], id: 'w2', name: 'HBM1', base: 0x8000n }], request)).toBe(true);
  });
});
