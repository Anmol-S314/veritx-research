import { describe, expect, it } from 'vitest';
import type { RevisionSummary, RunSummary } from './gateway';
import { buildRevisionGroups, previousCompiledRevision, runScopeLabel } from './revisionHistory';

const revisions: RevisionSummary[] = [
  { revision_id: 'p-r01', display_name: 'r01', created_at: '2026-01-01T00:00:00Z', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
  { revision_id: 'p-r02', display_name: 'r02', created_at: '2026-01-02T00:00:00Z', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
  { revision_id: 'p-r03', display_name: 'r03', created_at: '2026-01-03T00:00:00Z', compilation_status: 'UNSUPPORTED', error: '8 seats but 74 agents must attach' },
  { revision_id: 'p-r11', display_name: 'r11', created_at: '2026-01-11T00:00:00Z', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
  { revision_id: 'p-r12', display_name: 'r12', created_at: '2026-01-12T00:00:00Z', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
];

const runs: RunSummary[] = [
  { run_id: 'run-a', revision_id: 'p-r01', status: 'EVALUATED', completed_at: '2026-01-01T10:00:00Z', analysis_backends: [{ question: 'NETWORK_COMPLETION' }] },
  { run_id: 'run-b', revision_id: 'p-r01', status: 'UNSUPPORTED', completed_at: '2026-01-01T11:00:00Z' },
  { run_id: 'run-c', revision_id: 'p-r11', status: 'EVALUATED', completed_at: '2026-01-11T10:00:00Z', analysis_backends: [{ question: 'NETWORK_COMPLETION' }] },
  { run_id: 'run-d', revision_id: 'p-r12', status: 'EVALUATED', completed_at: '2026-01-12T10:00:00Z', analysis_backends: [{ question: 'NETWORK_COMPLETION' }, { question: 'SYSTEM_MAKESPAN' }] },
];

describe('revision history', () => {
  it('keeps every revision visible, including failed compile attempts and revisions without runs', () => {
    const groups = buildRevisionGroups(revisions, runs, 'p-r12');
    expect(groups.map(group => group.label)).toEqual(['r12', 'r11', 'r03', 'r02', 'r01']);
    expect(groups.find(group => group.label === 'r03')?.runs).toEqual([]);
    expect(groups.find(group => group.label === 'r03')?.compilationStatus).toBe('UNSUPPORTED');
  });

  it('puts the active revision first and nests runs oldest-first under it', () => {
    const groups = buildRevisionGroups(revisions, runs, 'p-r12');
    expect(groups[0].isActive).toBe(true);
    const r01 = groups.find(group => group.label === 'r01');
    expect(r01?.runs.map(run => run.run_id)).toEqual(['run-a', 'run-b']);
  });

  it('finds the previous successful compile, skipping failed attempts', () => {
    expect(previousCompiledRevision(revisions, 'p-r11')?.revision_id).toBe('p-r02');
    expect(previousCompiledRevision(revisions, 'p-r12')?.revision_id).toBe('p-r11');
    expect(previousCompiledRevision(revisions, 'p-r01')).toBeNull();
  });

  it('names the analysis scope rather than only the backend', () => {
    expect(runScopeLabel(runs[3])).toBe('NETWORK_COMPLETION + 1 more');
    expect(runScopeLabel(runs[0])).toBe('NETWORK_COMPLETION');
    expect(runScopeLabel(runs[1])).toBe('No analysis recorded');
  });
});
