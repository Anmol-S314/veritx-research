import { describe, expect, it } from 'vitest';
import { CANDIDATES, PAGES, branchCandidate, briefErrors, briefSpace, canAttach, candidateById, criteria, frontier, initialState, makeDraft, mappedBytes, overlaps, pageFromHash, parseAddress, patchCandidate, projectPoint, queueFlits, rawGBps, restoreState, routeBetween, agentIntentErrors } from './model';
import { architecturePackage, localChecks } from './checks';
import { NETWORK_CYCLES, PAIR_FIXTURE, flitsGBps, linkObservations } from './analysis';
import { initialInputs, operationPreview, validInputs, workloadIssues } from './workload';

// Export coverage (every supplied code.html has a route) is asserted in tests/prototype.spec.ts,
// which already runs under Node; this file stays dependency-free for the browser build.
const PROMPT_ONLY = ['analysis_logs_artifacts'];

describe('one coherent prototype fixture', () => {
  it('routes every export and prompt-only surface without duplicates', () => {
    expect(new Set(PAGES.map(p => p.id)).size).toBe(PAGES.length);
    expect(new Set(PAGES.map(p => p.source)).size).toBe(PAGES.length);
    expect(PAGES.filter(p => PROMPT_ONLY.includes(p.source))).toHaveLength(PROMPT_ONLY.length);
    for (const p of PAGES) expect(pageFromHash(`#/${p.id}`)).toBe(p);
    expect(pageFromHash('#/unknown')).toBeUndefined();
  });
  it('computes link capacity and configured queues without physical-area claims', () => {
    expect(rawGBps(128, 1400)).toBe(22.4);
    expect(queueFlits({ vcs: 2, depth: 8 })).toBe(1280);
    expect(queueFlits({ vcs: 4, depth: 16 })).toBe(5120);
  });
  it('does not substitute network P99 for transaction P95', () => {
    for (const c of CANDIDATES) {
      const requirement = criteria(c).find(r => r.id === 'REQ-LAT-04')!;
      expect(requirement.outcome).toBe('Not evaluated');
      expect(requirement.name).toContain('P95 transaction');
    }
    expect(candidateById('BASE').run).toBe('SIM-402');
    expect(candidateById('BASE').latency).toBe(28.6);
  });
  it('computes a gated frontier and consistent chart coordinates', () => {
    expect(frontier().map(c => c.id)).toEqual(['C-14', 'C-09']);
    expect(projectPoint(candidateById('C-09'))!.y).toBeGreaterThan(projectPoint(candidateById('BASE'))!.y);
    expect(projectPoint(candidateById('C-27'))).toBeNull();
    expect(projectPoint(candidateById('C-11'))).toBeNull();
  });
  it('computes an address union and a real conflict-free relocation', () => {
    const regions = makeDraft().regions;
    expect(overlaps(regions)).toHaveLength(1);
    expect(overlaps(regions)[0].size).toBe(256 * 2 ** 20);
    expect(mappedBytes(regions) / 2 ** 30).toBe(33.486328125);
    expect(mappedBytes(regions) / 2 ** 48 * 100).toBeCloseTo(0.01277402, 8);
    expect(overlaps(regions.map(r => r.id === 'PCIE_BAR0' ? { ...r, base: 0xc0000000 } : r))).toHaveLength(0);
    expect(parseAddress('0xC000_0000')).toBe(0xc0000000);
    for (const input of ['0x1000000000000', 'garbage', '-1', '0x1.2', '']) expect(parseAddress(input)).toBeNull();
  });
  it('keeps concentrators explicit and prevents silently splitting membership', () => {
    const endpoints = makeDraft().endpoints;
    expect(canAttach(endpoints, 'EP_NPU_0', 'R_1_2')).toBe(true);
    expect(canAttach(endpoints, 'EP_NPU_0', 'R_0_1')).toBe(false);
    expect(canAttach(endpoints, 'EP_NEW', 'R_1_2')).toBe(false);
    expect(canAttach(endpoints, 'EP_NEW', 'R_0_1')).toBe(true);
  });
  it('rejects inconsistent brief values and computes 24 active combinations', () => {
    const b = initialState().brief;
    expect(briefSpace(b)).toBe(24);
    expect(briefErrors(b)).toEqual([]);
    expect(briefErrors({ ...b, maxRuns: 25 })).not.toEqual([]);
    expect(briefErrors({ ...b, concurrency: NaN })).not.toEqual([]);
    expect(briefErrors({ ...b, vcs: [] })).not.toEqual([]);
    expect(briefErrors({ ...b, vcs: [2, 2, 4] })).toContain('Search dimensions must contain unique values.');
  });
});
describe('workload inputs and coherent analysis fixtures', () => {
  it('migrates earlier preview state without discarding draft edits', () => {
    const old: Record<string, unknown> = { ...initialState() };
    (old.draft as ReturnType<typeof makeDraft>).anchor.x = 3300;
    delete old.inputs; delete old.inputArchives; delete old.analysisRun;
    const result = restoreState(JSON.stringify(old));
    expect(result.warning).toBeNull();
    expect(result.state.draft.anchor.x).toBe(3300);
    expect(validInputs(result.state.inputs)).toBe(true);
    expect(result.state.analysisRun).toBe('SIM-402');
  });
  it('reports semantic dependency and binding issues without silently repairing intent', () => {
    const w = initialInputs();
    expect(validInputs(w)).toBe(true);
    expect(workloadIssues(w, makeDraft()).filter(f => f.level === 'error')).toEqual([]);
    w.operations[0].dependsOn = ['OP_WRITE'];
    w.bindings.COMPUTE_A = 'EP_MISSING';
    const messages = workloadIssues(w, makeDraft()).map(f => f.message).join(' ');
    expect(messages).toContain('cycle');
    expect(messages).toContain('unavailable endpoint');
    expect(w.bindings.COMPUTE_A).toBe('EP_MISSING');
  });
  it('calculates minimal data flits without inventing adapter or packet overhead', () => {
    const w = initialInputs(), o = { ...w.operations[3], bytes: 128 };
    expect(operationPreview(o, w).minimum128BitDataFlits).toBe(8);
    expect(operationPreview(w.operations[2], w).requestedBytes).toBeUndefined();
  });
  it('reconciles pair counts, throughput, zeros, and directed-link capacity', () => {
    expect(PAIR_FIXTURE.reduce((n, p) => n + p.deliveredFlits, 0)).toBe(329464);
    expect(flitsGBps(329464)).toBeCloseTo(16.4, 3);
    expect(PAIR_FIXTURE.some(p => p.deliveredFlits === 0)).toBe(true);
    expect(PAIR_FIXTURE.every(p => p.deliveredFlits <= NETWORK_CYCLES)).toBe(true);
    expect(linkObservations().every(l => l.percent >= 0 && l.percent <= 100 && l.flits <= NETWORK_CYCLES)).toBe(true);
  });
});
describe('agent intent is not runtime authorization', () => {
  it('blocks credential-bearing and out-of-policy URLs without opening a connection', () => {
    const valid = { endpoint: 'http://127.0.0.1:3000', dataPolicy: 'local-only' as const, tokenReference: 'AGENT_TOKEN_REF', operations: ['read-selection'] };
    expect(agentIntentErrors(valid)).toEqual([]);
    for (const endpoint of ['https://example.com', 'http://user:password@127.0.0.1:3000', 'http://127.0.0.1:3000/?api_key=secret', 'javascript:alert(1)']) expect(agentIntentErrors({ ...valid, endpoint }).length).toBeGreaterThan(0);
    expect(agentIntentErrors({ ...valid, tokenReference: 'sk-actual-secret' }).length).toBeGreaterThan(0);
  });
});
describe('configured logical routes', () => {
  it('uses adjacent links with column-first, then row movement', () => {
    expect(routeBetween('R_1_2', 'R_0_0')).toEqual(['R_1_2', 'R_1_1', 'R_1_0', 'R_0_0']);
    expect(routeBetween('R_0_0', 'R_0_0')).toEqual(['R_0_0']);
    expect(routeBetween('R_9_0', 'R_0_0')).toEqual([]);
  });
});
describe('local changes preserve evidence and drafts', () => {
  it('archives a complete draft before adopting an isolated candidate', () => {
    const s = initialState(); s.draft.anchor.x = 3200;
    s.draft.endpoints.push({ ...s.draft.endpoints[2], id: 'EP_NEW', router: 'R_0_1' }); s.selectedEndpoint = 'EP_NEW';
    const result = branchCandidate(s, candidateById('C-09'), 1);
    expect(result.archives[0].anchor.x).toBe(3200);
    expect(result.archives[0].endpoints.some(e => e.id === 'EP_NEW')).toBe(true);
    expect(result.draft.anchor.x).toBe(3000);
    expect(result.draft.vcs).toBe(4);
    expect(restoreState(JSON.stringify(result)).warning).toBeNull();
    expect(s.draft.vcs).toBe(2);
  });
  it('blocks stale or conflicting adoption and retains unrelated edits in a valid patch', () => {
    const s = initialState(); s.draft.anchor.y = 2000;
    const result = patchCandidate(s, candidateById('C-09'), 1);
    expect(result.draft.anchor.y).toBe(2000);
    expect(() => branchCandidate(s, candidateById('C-09'), 0)).toThrow('changed');
    s.draft.vcs = 8;
    expect(() => patchCandidate(s, candidateById('C-09'), 1)).toThrow('conflicts');
    expect(() => branchCandidate(s, candidateById('C-27'), 1)).toThrow('completely measured');
  });
  it('validates saved/imported state and reports corrupt content instead of crashing', () => {
    const s = initialState();
    expect(restoreState(JSON.stringify(s)).warning).toBeNull();
    for (const raw of ['{bad', 'null', '{}', JSON.stringify({ ...s, draft: { ...s.draft, endpoints: [] } }), JSON.stringify({ ...s, brief: { ...s.brief, vcs: null } }), JSON.stringify({ ...s, lastExport: { name: 'x.json', draft: s.draft, content: '<script>bad</script>' } })]) expect(restoreState(raw).warning).not.toBeNull();
  });
  it('separates runnable declaration checks from hardware verification', () => {
    const findings = localChecks(makeDraft());
    expect(findings.find(f => f.id === 'LOCAL-ADDR-01')!.outcome).toBe('Violated');
    expect(findings.find(f => f.id === 'LOCAL-REF-01')!.outcome).toBe('Pass');
    expect(findings.find(f => f.id === 'CDC-IMPL-01')!.outcome).toBe('Not evaluated');
  });
  it('captures architecture export inputs without generating hardware or sharing later edits', () => {
    const d = makeDraft(), output = architecturePackage(d, false);
    d.anchor.x = 3300;
    expect(output.capturedDraft.anchor.x).toBe(3000);
    expect(output.illustrative).toBe(true);
    expect(output.fixtureReference).toBeUndefined();
    expect(output.limitations.join(' ')).toContain('No RTL');
  });
});
