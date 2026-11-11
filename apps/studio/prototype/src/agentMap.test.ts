import { describe, expect, it } from 'vitest';
import {
  accessMatrix, addressCoverage, agentsFromRequest, alignUp, autoMapWindows, checkWorkloadFit, formatBytes, formatHex, formatHexBig,
  hasUnsavedAgentMap, parseAddress, parseAddressBigInt, parseAddressCanonical, parseSize, parseSizeBigInt, sizeM2FromEnvelope,
  targetCoverage, validateWindows, windowsFromRequest, windowsToRequest,
  type AddressWindow, type AgentGroup, type WorkloadEnvelope,
} from './agentMap';

const agents: AgentGroup[] = [
  { kind: 'compute_tile', count: 4, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: null, power_domain: null },
  { kind: 'hbm_controller', count: 2, data_width: 512, addr_width: 48, protocol: 'CHI', clock_domain: 'clk_hbm', power_domain: null },
  { kind: 'ucie_port', count: 1, data_width: 256, addr_width: 64, protocol: 'UCIe', clock_domain: null, power_domain: null },
];

const window = (overrides: Partial<AddressWindow> = {}): AddressWindow => ({
  id: 'w1', name: 'HBM0', base: 0x1000_0000n, size: 0x1000_0000n,
  targetAgentIdx: 1, selectionPolicy: 'FIXED_INSTANCE', targetInstanceIndex: 0, interleaveBytes: null,
  ...overrides,
});

describe('address parsing and formatting', () => {
  it('parses hexadecimal and decimal addresses exactly', () => {
    expect(parseAddress('0x1000_0000')).toBe(0x1000_0000);
    expect(parseAddress('4096')).toBe(4096);
    expect(parseAddress('0x')).toBeNull();
    expect(parseAddress('-1')).toBeNull();
    expect(parseAddress('0x1_0000_0000_0000_0000')).toBeNull();
  });

  it('reads decimal size suffixes as binary units', () => {
    expect(parseSize('256 MiB')).toBe(256 * 1024 ** 2);
    expect(parseSize('4KiB')).toBe(4096);
    expect(parseSize('0x2000')).toBe(8192);
    expect(parseSize('1.5 MiB')).toBe(1.5 * 1024 ** 2);
    expect(parseSize('nope')).toBeNull();
  });

  it('formats addresses in four-digit groups and bytes in binary units', () => {
    expect(formatHex(0x1000_0000)).toBe('0x1000_0000');
    expect(formatHex(0x1234)).toBe('0x0000_1234');
    expect(formatBytes(256 * 1024 ** 2)).toBe('256 MiB');
    expect(formatBytes(1536)).toBe('1.5 KiB');
  });

  it('aligns up without changing an aligned value', () => {
    expect(alignUp(4097, 4096)).toBe(8192);
    expect(alignUp(8192, 4096)).toBe(8192);
  });
});

describe('BigInt canonical address parsing (exact, no Number rounding)', () => {
  const TWO_POW_48_MINUS_1 = (1n << 48n) - 1n;
  const TWO_POW_48 = 1n << 48n;
  const TWO_POW_53 = 1n << 53n;

  it('parses the 48-bit ceiling exactly (2^48 − 1)', () => {
    expect(parseAddressBigInt('0xFFFF_FFFF_FFFF')).toBe(TWO_POW_48_MINUS_1);
    expect(parseAddressBigInt(TWO_POW_48_MINUS_1.toString())).toBe(TWO_POW_48_MINUS_1);
    // The safe-number wrapper is also exact here (2^48 < 2^53).
    expect(parseAddress('0xFFFF_FFFF_FFFF')).toBe(Number(TWO_POW_48_MINUS_1));
    expect(parseAddressCanonical('0xFFFF_FFFF_FFFF')).toBe(TWO_POW_48_MINUS_1.toString(10));
  });

  it('parses the first address past 48 bits (0x1_0000_0000_0000)', () => {
    expect(parseAddressBigInt('0x1_0000_0000_0000')).toBe(TWO_POW_48);
    expect(parseAddressCanonical('0x1_0000_0000_0000')).toBe(TWO_POW_48.toString(10));
    expect(parseAddress('0x1_0000_0000_0000')).toBe(Number(TWO_POW_48));
  });

  it('carries HBM bases past 2^53 exactly as canonical strings', () => {
    // A base just over the safe-integer ceiling: Number() would round it.
    const hbmBase = TWO_POW_53 + 1n; // 0x2000_0000_0000 + 1
    expect(hbmBase.toString(16)).toBe('20000000000001');
    expect(parseAddressBigInt('0x20_0000_0000_0001')).toBe(hbmBase);
    expect(parseAddressCanonical('0x20_0000_0000_0001')).toBe(hbmBase.toString(10));
    // Canonical string round-trips through the BigInt parser exactly.
    expect(parseAddressBigInt(parseAddressCanonical('0x20_0000_0000_0001')!)).toBe(hbmBase);
    // The safe-number wrapper refuses instead of rounding.
    expect(parseAddress('0x20_0000_0000_0001')).toBeNull();
  });

  it('formats big addresses exactly (no Number rounding in hex output)', () => {
    expect(formatHexBig(TWO_POW_53 + 1n)).toBe('0x0020_0000_0000_0001');
    expect(formatHexBig('0xFFFF_FFFF_FFFF')).toBe('0xFFFF_FFFF_FFFF');
    expect(formatHexBig(TWO_POW_48)).toBe('0x0001_0000_0000_0000');
    // Number path still formats small values identically.
    expect(formatHex(0x1234)).toBe('0x0000_1234');
  });

  it('refuses values past the unsigned 64-bit ceiling and malformed input', () => {
    expect(parseAddressBigInt('0x1_0000_0000_0000_0000')).toBeNull(); // 2^64
    expect(parseAddressBigInt('-1')).toBeNull();
    expect(parseAddressBigInt('')).toBeNull();
    expect(parseAddressBigInt('0x')).toBeNull();
    expect(parseAddressCanonical('garbage')).toBeNull();
  });

  it('parses sizes exactly, refusing inexact fractions', () => {
    expect(parseSizeBigInt('1.5 MiB')).toBe(1572864n);
    expect(parseSizeBigInt('256 MiB')).toBe(BigInt(256 * 1024 ** 2));
    expect(parseSizeBigInt('0x2000')).toBe(8192n);
    // 1.1 B is not an exact byte count after unit scaling — refused, not rounded.
    expect(parseSizeBigInt('1.1 B')).toBeNull();
    // Safe wrapper still widens exactly for in-range sizes.
    expect(parseSize('256 MiB')).toBe(256 * 1024 ** 2);
  });
});

describe('workload-fit resolver', () => {
  const design = {
    workloadHash: 'wl-design-v1',
    envelope: {
      maxBurstiness: 4096, maxConcurrency: 256, maxOutstanding: 32, maxDependencies: 512,
      latencyAchievedNs: 900, bandwidthCapacityGbps: 96,
    },
    m2: { maxOutstanding: 32, splitAt: 4096 },
  };
  const base: WorkloadEnvelope = {
    burstiness: 2048, concurrency: 128, outstandingDemand: 16,
    dependencyCount: 200, latencyBudgetNs: 1200, bandwidthDemandGbps: 48,
  };

  it('sizes M2 from the envelope deterministically', () => {
    expect(sizeM2FromEnvelope(base)).toEqual({ maxOutstanding: 16, splitAt: 2048 });
    expect(sizeM2FromEnvelope({ ...base, outstandingDemand: 16.2, burstiness: 3.1 })).toEqual({ maxOutstanding: 17, splitAt: 4 });
  });

  it('reports satisfied when the hash matches and the envelope fits', () => {
    const verdict = checkWorkloadFit('wl-design-v1', design, base);
    expect(verdict.status).toBe('satisfied');
    expect(verdict.exceeded).toEqual([]);
    expect(verdict.checks).toHaveLength(6);
  });

  it('reports same-design-fits when the hash changed but the envelope still fits', () => {
    const verdict = checkWorkloadFit('wl-design-v2', design, { ...base, outstandingDemand: 28, bandwidthDemandGbps: 90 });
    expect(verdict.status).toBe('same-design-fits');
    expect(verdict.exceeded).toEqual([]);
  });

  it('reports needs-re-synthesis with verbatim dimensions when capacity is exceeded', () => {
    const verdict = checkWorkloadFit('wl-design-v3', design, { ...base, outstandingDemand: 64, latencyBudgetNs: 500, bandwidthDemandGbps: 128 });
    expect(verdict.status).toBe('needs-re-synthesis');
    expect(verdict.exceeded).toHaveLength(3);
    expect(verdict.exceeded.join(' ')).toContain('outstanding');
    expect(verdict.exceeded.join(' ')).toContain('latency');
    expect(verdict.exceeded.join(' ')).toContain('bandwidth');
    const outstanding = verdict.checks.find(check => check.dimension.startsWith('outstanding'))!;
    expect(outstanding).toMatchObject({ demand: 64, capacity: 32, fits: false });
  });
});

describe('request translation', () => {
  it('accepts the legacy size_bytes/target spelling', () => {
    const windows = windowsFromRequest({ address_map: { ranges: [{ name: 'HBM', base: '0x1000', size_bytes: 4096, target: 1 }] } });
    expect(windows).toHaveLength(1);
    expect(windows[0]).toMatchObject({ name: 'HBM', base: 0x1000n, size: 4096n, targetAgentIdx: 1, selectionPolicy: null });
  });

  it('resolves a legacy target kind name against the declared agent groups', () => {
    const windows = windowsFromRequest({ address_map: { ranges: [{ name: 'HBM', base: '0x100000000', size_bytes: 4096, target: 'hbm_controller' }] } }, agents);
    expect(windows[0].targetAgentIdx).toBe(1);
  });

  it('writes only the schema fields and sorts by base', () => {
    const ranges = windowsToRequest([
      window({ id: 'b', name: 'B', base: 0x2000n, size: 0x1000n }),
      window({ id: 'a', name: 'A', base: 0x1000n, size: 0x1000n }),
    ]);
    expect(ranges.map(range => range.name)).toEqual(['A', 'B']);
    expect(ranges[0]).toMatchObject({ base: 0x1000, size: 0x1000, target_agent_idx: 1, selection_policy: 'FIXED_INSTANCE', target_instance_index: 0 });
    expect(ranges[0]).not.toHaveProperty('size_bytes');
  });

  it('detects unsaved edits against a canonical request', () => {
    const request = { agents, address_map: { ranges: windowsToRequest([window()]) } };
    expect(hasUnsavedAgentMap(agents, [window()], request)).toBe(false);
    expect(hasUnsavedAgentMap(agents, [window({ size: 0x2000n })], request)).toBe(true);
  });

  it('is not dirty when the editable model is re-read from the same request', () => {
    const request = { agents, address_map: { ranges: windowsToRequest([window()]) } };
    const currentAgents = agentsFromRequest(request);
    const currentWindows = windowsFromRequest(request, currentAgents);
    expect(hasUnsavedAgentMap(currentAgents, currentWindows, request)).toBe(false);
  });

  it('reads agents without inventing missing fields', () => {
    expect(agentsFromRequest({ agents: [{ kind: 'compute_tile', count: 2 }] })[0]).toMatchObject({
      kind: 'compute_tile', count: 2, data_width: undefined, addr_width: undefined, protocol: undefined, clock_domain: null,
    });
  });
});

describe('window validation', () => {
  it('accepts a fixed-instance window inside the target address width', () => {
    expect(validateWindows([window()], agents)).toEqual([]);
  });

  it('reports overlaps with both endpoints', () => {
    const issues = validateWindows([
      window({ name: 'A', base: 0x1000n, size: 0x2000n }),
      window({ name: 'B', base: 0x2000n, size: 0x1000n }),
    ], agents);
    expect(issues.some(issue => issue.code === 'OVERLAP' && issue.detail.includes('A') && issue.detail.includes('B'))).toBe(true);
  });

  it('refuses an instance index outside the declared group', () => {
    const issues = validateWindows([window({ targetInstanceIndex: 9 })], agents);
    expect(issues.some(issue => issue.code === 'INSTANCE_OUT_OF_RANGE')).toBe(true);
  });

  it('refuses a striped window that is not power-of-two aligned', () => {
    const issues = validateWindows([window({ selectionPolicy: 'STRIPED', targetInstanceIndex: null, interleaveBytes: 0x1800n })], agents);
    expect(issues.some(issue => issue.code === 'INTERLEAVE_NOT_POW2')).toBe(true);
  });

  it('requires an explicit selection for a multi-instance target', () => {
    const issues = validateWindows([window({ selectionPolicy: null, targetInstanceIndex: null })], agents);
    expect(issues.some(issue => issue.code === 'GROUP_SELECTION_REQUIRED')).toBe(true);
  });

  it('refuses a selection policy on a singleton target', () => {
    const issues = validateWindows([window({ targetAgentIdx: 2, selectionPolicy: 'FIXED_INSTANCE', targetInstanceIndex: 0 })], agents);
    expect(issues.some(issue => issue.code === 'SINGLETON_HAS_POLICY')).toBe(true);
  });

  it('refuses a range above the target agent address width', () => {
    const issues = validateWindows([window({ base: 0x1_0000_0000_0000n, size: 0x1000n })], agents);
    expect(issues.some(issue => issue.code === 'TARGET_ADDR_WIDTH')).toBe(true);
  });
});

describe('coverage and reachability', () => {
  it('counts overlapping bytes once', () => {
    const coverage = addressCoverage([
      window({ name: 'A', base: 0x1000n, size: 0x1000n }),
      window({ name: 'B', base: 0x1800n, size: 0x1000n }),
    ]);
    expect(coverage.declaredBytes).toBe(0x2000n);
    expect(coverage.mappedBytes).toBe(0x1800n);
    expect(coverage.overlapBytes).toBe(0x800n);
  });

  it('counts a striped window as covering every instance', () => {
    const coverage = targetCoverage(agents, [window({ selectionPolicy: 'STRIPED', targetInstanceIndex: null, interleaveBytes: 0x1000n })]);
    expect(coverage[0]).toMatchObject({ kind: 'hbm_controller', count: 2, covered: 2, missingInstances: [] });
  });

  it('includes a declared target group that has no window', () => {
    const coverage = targetCoverage(agents, [window()]);
    const ucie = coverage.find(entry => entry.kind === 'ucie_port');
    expect(ucie).toMatchObject({ count: 1, covered: 0, missingInstances: [0] });
  });

  it('builds an address-window matrix without claiming permission', () => {
    const matrix = accessMatrix(agents, [window()]);
    expect(matrix.rows.map(row => row.kind)).toContain('compute_tile');
    expect(matrix.cols.map(col => col.kind)).toContain('hbm_controller');
    const row = matrix.rows.findIndex(item => item.kind === 'compute_tile');
    const col = matrix.cols.findIndex(item => item.kind === 'hbm_controller');
    expect(matrix.cell(row, col)).toEqual({ windows: 1, bytes: 0x1000_0000n });
  });

  it('auto-maps one fixed window per target instance', () => {
    const windows = autoMapWindows(agents, { base: 0x1000_0000n, size: 0x1000_0000n, targetKinds: ['hbm_controller'] });
    expect(windows).toHaveLength(2);
    expect(windows.map(item => item.targetInstanceIndex)).toEqual([0, 1]);
    expect(windows[0].base).toBe(0x1000_0000n);
    expect(windows[1].base).toBe(0x2000_0000n);
  });

  it('auto-maps a singleton target without a selection policy', () => {
    const windows = autoMapWindows(agents, { base: 0x1000_0000n, size: 0x1000_0000n, targetKinds: ['ucie_port'] });
    expect(windows).toHaveLength(1);
    expect(windows[0]).toMatchObject({ selectionPolicy: null, targetInstanceIndex: null });
  });

  it('reads a schema-v5 base_v4 design', () => {
    const request = { schema_version: 5, base_v4: { agents, address_map: { ranges: windowsToRequest([window()]) } } };
    expect(agentsFromRequest(request)).toHaveLength(3);
    expect(windowsFromRequest(request, agentsFromRequest(request))[0]).toMatchObject({ name: 'HBM0', targetAgentIdx: 1 });
  });
});
