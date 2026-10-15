import { describe, expect, it } from 'vitest';
import { filterRunHistory, runFingerprintFreshness } from './runHistory';
import type { RunSummary } from '../../api/types';
const run = (run_id: string, patch: Partial<RunSummary> = {}): RunSummary => ({
  run_id, display_name: null, project_id: 'p', revision_id: 'rev', design_hash: null,
  backend: null, status: null, qualification: null, requirements_pass: null,
  started_at: null, completed_at: null, bundle_id: null, workload_id: null, completion_cycles: null,
  ...patch,
});
describe('run history fingerprint freshness', () => {
  it('marks only unequal known fingerprints as older and preserves unknowns', () => {
    expect(runFingerprintFreshness('same', 'same')).toBe('current');
    expect(runFingerprintFreshness('old', 'new')).toBe('older');
    expect(runFingerprintFreshness(null, 'new')).toBe('unknown');
    expect(runFingerprintFreshness('old', null)).toBe('unknown');
    expect(runFingerprintFreshness('', '')).toBe('unknown');
  });
});

describe('run history search', () => {
  it('searches failed/completed records by backend, workload, fingerprint, and status', () => {
    const runs = [run('done', { backend: 'book-sim', workload_id: 'w-a', design_hash: 'abc123', status: 'EVALUATED' }), run('failed', { backend: 'astra', workload_id: 'w-b', status: 'FAILED' })];
    expect(filterRunHistory(runs, 'failed').map(x => x.run_id)).toEqual(['failed']);
    expect(filterRunHistory(runs, 'ASTRA')).toEqual([runs[1]]);
    expect(filterRunHistory(runs, 'w-a')).toEqual([runs[0]]);
    expect(filterRunHistory(runs, 'abc123')).toEqual([runs[0]]);
    const older = run('older', { design_hash: 'old-hash' });
    expect(filterRunHistory([...runs, older], 'older', 'abc123')).toEqual([older]);
    expect(filterRunHistory(runs, '')).toBe(runs);
  });
});
