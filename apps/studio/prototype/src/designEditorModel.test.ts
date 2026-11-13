import { describe, expect, it } from 'vitest';
import { collectProblems, derive, rangeBounds } from './designEditorModel';
import type { LoadedProject } from './project';

const project = (over: Record<string, unknown> = {}): LoadedProject => ({
  detail: { active_revision_id: 'p-r09' },
  request: { agents: [{ kind: 'compute_tile', count: 1, clock_domain: 'clk_a' }, { kind: 'hbm_controller', count: 1, clock_domain: null }], address_map: { ranges: [] } },
  draftMeta: null,
  topology: { family: 'mesh', counts: {}, routers: [], channels: [], endpoints: [
    { endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0, group_index: 0 },
    { endpoint_id: 1, router_id: 3, kind: 'hbm_controller', port_id: 0, group_index: 1 }] },
  topologyError: '', compileResult: null, compileResultError: '', ...over,
} as unknown as LoadedProject);

describe('rangeBounds', () => {
  it('is exact above 2^53 and refuses unusable ranges', () => {
    expect(rangeBounds({ base: '0xFFFFFFFFFFFFFFF0', size: 8 })).toEqual({ base: 0xFFFFFFFFFFFFFFF0n, end: 0xFFFFFFFFFFFFFFF8n });
    expect(rangeBounds({ base: '0x0', size: 0 })).toBeNull();
    expect(rangeBounds({ base: 'zz', size: 4 })).toBeNull();
  });
});

describe('collectProblems', () => {
  it('flags overlapping ranges and abutting ranges differently', () => {
    const d = project({ request: { address_map: { ranges: [{ name: 'a', base: 0, size: 16 }, { name: 'b', base: 8, size: 16 }, { name: 'c', base: 24, size: 8 }] } } });
    const p = collectProblems(d, null).filter(x => x.code === 'LOCAL-ADDR-01');
    expect(p).toHaveLength(1);
    expect(p[0].at).toEqual({ kind: 'range', id: 'b' });
  });

  it('keeps refusals, findings and unevaluated obligations apart and orders by severity', () => {
    const d = project({ compileResult: {
      stage1_verdicts: [{ module: 'vc', ok: false, status: 'REFUSED', reason: 'too few VCs', findings: [] }, { module: 'ok', ok: true, status: 'PASS', reason: null, findings: [] }],
      stage1_findings: ['a finding'],
      certificate: { overall: 'PASS', obligations: [{ obligation: 'cdc', status: 'NOT_EVALUATED' }, { obligation: 'x', status: 'PASS' }, { obligation: 'y', status: 'FAILED' }] },
    } });
    const p = collectProblems(d, { dirty: true, valid: true, busy: false, error: '', save: () => {} });
    expect(p.map(x => x.severity)).toEqual(['error', 'error', 'warning', 'unevaluated', 'info']);
    expect(p.find(x => x.code === 'NOT_EVALUATED')?.severity).toBe('unevaluated');
    expect(p.at(-1)?.code).toBe('STALE');
  });
});

describe('derive', () => {
  it('joins endpoints to agent groups and decode rows without inventing missing links', () => {
    const d = derive(project({ compileResult: { groups: { address_decode: { rows: [{ name: 'a', target_endpoint_id: 1 }, { name: 'orphan' }] } } } }));
    expect(d.byRouter.get(3)?.map(e => e.endpoint_id)).toEqual([1]);
    expect(d.rangesByEp.get(1)?.map(r => r.name)).toEqual(['a']);
    expect(d.rangesByEp.has(0)).toBe(false);
    expect(d.agentOf(d.eps[1])?.clock_domain).toBeNull();
    expect(d.clocks).toEqual(['clk_a']);
    expect(d.rowFor('orphan')?.target_endpoint_id).toBeUndefined();
  });
});
