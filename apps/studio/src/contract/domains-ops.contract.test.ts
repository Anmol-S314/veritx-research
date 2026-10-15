/** Domain authoring operations (M3-11/M3-12, M2-20): pure over the typed
 *  `domains` contract. Inherit = a missing field; override = a set field. */
import { describe, expect, it } from 'vitest';
import {
  assignmentFieldOf, assignmentOf, domainUsage, emptyDomains, listOf, nextDomainId,
  nodeFieldOf, nodeReferences, removeDomain, setAssignmentField, upsertDomain, upsertPortAssignment,
} from '../graph/domains';
import type { DomainsConfigV1, LoomProject } from '../graph/project';

const base = (): DomainsConfigV1 => ({
  clocks: [{ id: 'clk_1', frequencyHz: null, source: null }, { id: 'clk_2', frequencyHz: null, source: null }],
  resets: [{ id: 'rst_1', polarity: 'active_low', asynchronous: true }],
  powers: [{ id: 'pd_1', nominalVoltageV: 0.8, canPowerOff: false }],
  portAssignments: [{ nodeId: 'n1', portId: 'p1', clockDomainId: 'clk_1', powerDomainId: 'pd_1' }],
});

describe('domain operations: ids and upsert', () => {
  it('mints the next free <prefix>_<n> id', () => {
    expect(nextDomainId('clocks', [])).toBe('clk_1');
    expect(nextDomainId('clocks', ['clk_1', 'clk_2'])).toBe('clk_3');
    expect(nextDomainId('resets', ['rst_1'])).toBe('rst_2');
    expect(nextDomainId('powers', ['pd_9'])).toBe('pd_1');
  });

  it('maps a kind to its node field, override field and prefix', () => {
    expect(nodeFieldOf('clocks')).toBe('clock');
    expect(nodeFieldOf('resets')).toBe('resetDomain');
    expect(nodeFieldOf('powers')).toBe('powerDomain');
    expect(assignmentFieldOf('clocks')).toBe('clockDomainId');
    expect(assignmentFieldOf('resets')).toBe('resetDomainId');
    expect(assignmentFieldOf('powers')).toBe('powerDomainId');
  });

  it('adds a new domain and replaces one with the same id', () => {
    const added = upsertDomain(emptyDomains(), 'clocks', { id: 'clk_1', frequencyHz: 1e9, source: 'pll0' });
    expect(added.clocks).toEqual([{ id: 'clk_1', frequencyHz: 1e9, source: 'pll0' }]);
    const replaced = upsertDomain(added, 'clocks', { id: 'clk_1', frequencyHz: 2e9, source: null });
    expect(replaced.clocks).toEqual([{ id: 'clk_1', frequencyHz: 2e9, source: null }]);
    expect(listOf(added, 'clocks')).toHaveLength(1);
  });
});

describe('domain operations: removal clears references', () => {
  it('drops the domain and any override field that pointed at it', () => {
    const next = removeDomain(base(), 'clocks', 'clk_1');
    expect(next.clocks.map((c) => c.id)).toEqual(['clk_2']);
    // The row still overrides power, so it survives with that field only.
    expect(next.portAssignments).toEqual([{ nodeId: 'n1', portId: 'p1', powerDomainId: 'pd_1' }]);
  });

  it('drops a port row left with no overrides at all', () => {
    const onlyClock: DomainsConfigV1 = {
      ...emptyDomains(),
      clocks: [{ id: 'clk_1' }],
      portAssignments: [{ nodeId: 'n1', portId: 'p1', clockDomainId: 'clk_1' }],
    };
    expect(removeDomain(onlyClock, 'clocks', 'clk_1').portAssignments).toEqual([]);
  });

  it('reports the node-level references a caller must clear', () => {
    const doc: Pick<LoomProject, 'nodes'> = { nodes: [
      { id: 'n1', x: 0, y: 0, role: 'nic', ports: 2, clock: 'clk_1' },
      { id: 'n2', x: 0, y: 0, role: 'nic', ports: 2, clock: 'clk_2' },
      { id: 'n3', x: 0, y: 0, role: 'nic', ports: 2, resetDomain: 'clk_1' },
    ] };
    expect(nodeReferences(doc, 'clocks', 'clk_1')).toEqual(['n1']);
    expect(nodeReferences(doc, 'resets', 'clk_1')).toEqual(['n3']);
    expect(nodeReferences(doc, 'powers', 'clk_1')).toEqual([]);
  });
});

describe('domain operations: port overrides', () => {
  it('sets and clears a single override field, dropping empty rows', () => {
    const set = upsertPortAssignment(emptyDomains(), 'n1', 'p1', { clockDomainId: 'clk_1' });
    expect(set.portAssignments).toEqual([{ nodeId: 'n1', portId: 'p1', clockDomainId: 'clk_1' }]);
    expect(assignmentOf(set, 'n1', 'p1')).toMatchObject({ clockDomainId: 'clk_1' });

    const cleared = setAssignmentField(set, 'n1', 'p1', 'clockDomainId', undefined);
    expect(cleared.portAssignments).toEqual([]);
    expect(assignmentOf(cleared, 'n1', 'p1')).toBeNull();
  });

  it('keeps other override fields when one is cleared', () => {
    const two = upsertPortAssignment(base(), 'n1', 'p1', { resetDomainId: 'rst_1' });
    const cleared = setAssignmentField(two, 'n1', 'p1', 'clockDomainId', undefined);
    expect(cleared.portAssignments).toEqual([{ nodeId: 'n1', portId: 'p1', powerDomainId: 'pd_1', resetDomainId: 'rst_1' }]);
  });
});

describe('domain operations: usage', () => {
  it('counts node references and port overrides', () => {
    const doc = {
      nodes: [
        { id: 'n1', x: 0, y: 0, role: 'nic', ports: 2, clock: 'clk_1' },
        { id: 'n2', x: 0, y: 0, role: 'nic', ports: 2 },
      ] as LoomProject['nodes'],
      domains: base(),
    };
    expect(domainUsage(doc, 'clocks', 'clk_1')).toEqual({ nodes: 1, overrides: 1 });
    expect(domainUsage(doc, 'powers', 'pd_1')).toEqual({ nodes: 0, overrides: 1 });
    expect(domainUsage(doc, 'resets', 'rst_1')).toEqual({ nodes: 0, overrides: 0 });
  });
});
