/** Access-flow resolution (M3-27): firewall cell + routing preview → verdict. */
import { describe, expect, it } from 'vitest';
import { accessFlow, connectivityOnly } from '../graph/accessFlow';
import type { LoomProject } from '../graph/project';

const edge = { id: 'e1', src: 'n1', dst: 'n2', width: 512, pipelineStages: 1, vcClass: 0 };
const node = (id: string) => ({ id, x: 0, y: 0, role: 'compute_tile', ports: 5 });

const base = (extra: Partial<LoomProject> = {}): LoomProject => ({
  schemaVersion: 1,
  compilerSemanticsVersion: 1,
  presetHint: null,
  nodes: [node('n1'), node('n2')],
  edges: [edge],
  routing: { policy: 'custom', rules: [{ src: 'n1', dst: 'n2', nextHop: 'n2' }] },
  ...extra,
});

const firewall = (perm: 'RO' | 'RW') => ({ default: 'deny' as const, rules: [{ src: 'n1', dst: 'n2', perm }] });

describe('M3-27: access flow', () => {
  it('permits a pair with an authored rule and a preview route', () => {
    const flow = accessFlow(base({ firewall: firewall('RW') }), 'n1', 'n2');
    expect(flow.verdict).toBe('PERMITTED');
    expect(flow.perm).toBe('RW');
    expect(flow.nodePath).toEqual(['n1', 'n2']);
    expect(flow.hops).toHaveLength(1);
  });

  it('reads an authored read-only rule as READ_ONLY', () => {
    expect(accessFlow(base({ firewall: firewall('RO') }), 'n1', 'n2').verdict).toBe('READ_ONLY');
  });

  it('denies a pair with no authored rule (firewall default is deny)', () => {
    const flow = accessFlow(base(), 'n1', 'n2');
    expect(flow.verdict).toBe('DENIED');
    expect(flow.nodePath).toBeNull();
  });

  it('reports NO_POLICY when a rule is allowed but no routing policy is set', () => {
    const flow = accessFlow(base({ firewall: firewall('RW'), routing: undefined }), 'n1', 'n2');
    expect(flow.verdict).toBe('NO_POLICY');
    expect(flow.error).toMatch(/No routing policy/);
  });

  it('reports NO_ROUTE when the policy yields no path', () => {
    // Allowed, custom policy selected, but no next-hop rule for the pair.
    const flow = accessFlow(base({ firewall: firewall('RW'), routing: { policy: 'custom', rules: [] } }), 'n1', 'n2');
    expect(flow.verdict).toBe('NO_ROUTE');
    expect(flow.error).toMatch(/No next-hop rule/);
  });

  it('treats a self pair as SELF', () => {
    expect(accessFlow(base(), 'n1', 'n1').verdict).toBe('SELF');
  });

  it('offers a firewall-independent connectivity path', () => {
    expect(connectivityOnly(base(), 'n1', 'n2')).toEqual(['n1', 'n2']);
  });
});
