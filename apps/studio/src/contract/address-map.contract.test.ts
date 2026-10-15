/** Address-map analysis over the local authoring graph (tracker M3-23/M3-24).
 *
 *  Pure interval math: overlaps, internal holes, coverage, address-width
 *  overflow and unmapped initiator ports. No server artifact is involved. */
import { describe, expect, it } from 'vitest';
import {
  analyzeAddressMap, hex, mappedRows, parseHexQuantity,
  type AddressWindowRow,
} from '../graph/addressMap';
import type { AgentRole, LoomProject, ProjectAgent } from '../graph/project';

type Window = { base: string; size: string; permissions: ('read' | 'write')[] };
const win = (base: string, size: string): Window => ({ base, size, permissions: ['read', 'write'] });

function agent(id: string, nodeId: string, role: AgentRole, windows: Window[], addressWidth?: number): ProjectAgent {
  return {
    id, nodeId, role, protocol: 'AXI4', capabilities: ['read', 'write'],
    ports: [{ id: 'p1', role, protocol: 'AXI4', dataWidth: 256, addressWidth, capabilities: ['read', 'write'], addressWindows: windows }],
  };
}
const project = (agents: ProjectAgent[]): Pick<LoomProject, 'agents'> => ({ agents });

describe('address map: rows and roles', () => {
  it('reads every window in document order with exclusive ends', () => {
    const report = analyzeAddressMap(project([
      agent('a1', 'n1', 'target', [win('0x0', '0x1000'), win('0x2000', '0x1000')]),
      agent('a2', 'n2', 'target', [win('0x4000', '0x800')]),
    ]));
    expect(report.rows.map((r) => r.key)).toEqual(['a1/p1/0', 'a1/p1/1', 'a2/p1/0']);
    expect(report.rows[0]).toMatchObject({ base: 0n, end: 0x1000n, nodeId: 'n1' });
    expect(report.mapped).toHaveLength(3);
  });

  it('draws the map from target/bidirectional windows, not initiators', () => {
    const rows: AddressWindowRow[] = analyzeAddressMap(project([
      agent('t', 'n1', 'target', [win('0x0', '0x1000')]),
      agent('i', 'n2', 'initiator', [win('0x0', '0x1000')]),
      agent('b', 'n3', 'bidirectional', [win('0x8000', '0x1000')]),
    ])).rows;
    expect(mappedRows(rows).map((r) => r.agentId)).toEqual(['t', 'b']);
  });
});

describe('M3-24: overlaps and holes', () => {
  it('reports a byte-exact overlap between two mapped windows', () => {
    const report = analyzeAddressMap(project([
      agent('a', 'n1', 'target', [win('0x0', '0x2000')]),
      agent('b', 'n2', 'target', [win('0x1000', '0x2000')]),
    ]));
    expect(report.overlaps).toHaveLength(1);
    expect(report.overlaps[0]!.bytes).toBe(0x1000n);
    expect(report.overlaps[0]!.a.agentId).toBe('a');
    expect(report.overlaps[0]!.b.agentId).toBe('b');
    // Overlap merges coverage; it is not a hole.
    expect(report.mappedBytes).toBe(0x3000n);
    expect(report.holes).toEqual([]);
  });

  it('reports internal holes with the leading/trailing space excluded', () => {
    const report = analyzeAddressMap(project([
      agent('a', 'n1', 'target', [win('0x1000', '0x1000')]),
      agent('b', 'n2', 'target', [win('0x4000', '0x1000')]),
      agent('c', 'n3', 'target', [win('0x8000', '0x1000')]),
    ]));
    expect(report.holes).toEqual([
      { from: 0x2000n, to: 0x4000n, bytes: 0x2000n },
      { from: 0x5000n, to: 0x8000n, bytes: 0x3000n },
    ]);
    expect(report.uncoveredBytes).toBe(0x5000n);
    expect(report.mappedBytes).toBe(0x3000n);
    expect(report.spanBytes).toBe(0x9000n - 0x1000n);
    expect(report.mappedNodes).toBe(3);
  });

  it('merges adjacent and nested windows without inventing a hole', () => {
    const report = analyzeAddressMap(project([
      agent('a', 'n1', 'target', [win('0x0', '0x1000'), win('0x1000', '0x1000')]),
      agent('b', 'n2', 'target', [win('0x400', '0x100')]),
    ]));
    expect(report.overlaps).toHaveLength(1);
    expect(report.holes).toEqual([]);
    expect(report.mappedBytes).toBe(0x2000n);
  });

  it('is deterministic regardless of agent order', () => {
    const a = analyzeAddressMap(project([agent('a', 'n1', 'target', [win('0x0', '0x1000')]), agent('b', 'n2', 'target', [win('0x8000', '0x1000')])]));
    const b = analyzeAddressMap(project([agent('b', 'n2', 'target', [win('0x8000', '0x1000')]), agent('a', 'n1', 'target', [win('0x0', '0x1000')])]));
    expect(a.holes).toEqual(b.holes);
    expect(a.mappedBytes).toBe(b.mappedBytes);
  });
});

describe('address map: width, malformed and unmapped initiators', () => {
  it('flags a window that exceeds its declared address width', () => {
    const report = analyzeAddressMap(project([agent('a', 'n1', 'target', [win('0x0', '0x200')], 8)]));
    expect(report.rows[0]!.addressWidth).toBe(8);
    expect(report.rows[0]!.exceedsWidth).toBe(true);
    expect(report.addressWidths).toEqual([8]);
  });

  it('skips a malformed window without coercing it to a number', () => {
    const report = analyzeAddressMap(project([agent('a', 'n1', 'target', [win('nope', '0x100'), win('0x0', '0x100')])]));
    expect(report.malformed).toBe(1);
    expect(report.rows).toHaveLength(1);
    expect(report.rows[0]!.baseText).toBe('0x0');
  });

  it('lists initiator/bidirectional ports that map no address', () => {
    const report = analyzeAddressMap(project([
      agent('i1', 'n1', 'initiator', []),
      agent('i2', 'n2', 'initiator', [win('0x0', '0x100')]),
      agent('b', 'n3', 'bidirectional', []),
      agent('t', 'n4', 'target', []),
    ]));
    expect(report.unmappedInitiators.map((u) => u.agentId)).toEqual(['i1', 'b']);
    expect(report.unmappedInitiators[0]).toMatchObject({ nodeId: 'n1', portId: 'p1', role: 'initiator' });
  });

  it('is empty for a project with no agents', () => {
    const report = analyzeAddressMap({ agents: undefined });
    expect(report.rows).toEqual([]);
    expect(report.mappedBytes).toBe(0n);
    expect(report.holes).toEqual([]);
    expect(report.overlaps).toEqual([]);
    expect(report.unmappedInitiators).toEqual([]);
  });
});

describe('address map: helpers', () => {
  it('parses only hexadecimal quantities', () => {
    expect(parseHexQuantity('0x10')).toBe(0x10n);
    expect(parseHexQuantity('0X10')).toBeNull();
    expect(parseHexQuantity('16')).toBeNull();
    expect(parseHexQuantity('0x')).toBeNull();
    expect(parseHexQuantity(16)).toBeNull();
    expect(parseHexQuantity(null)).toBeNull();
  });

  it('formats hex without a suffix', () => {
    expect(hex(0xdeadbeefn)).toBe('0xdeadbeef');
    expect(hex(0n)).toBe('0x0');
  });
});
