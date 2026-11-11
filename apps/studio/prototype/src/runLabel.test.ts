import { describe, expect, it } from 'vitest';
import { revisionLabel, runVersionLabels, runVersionOrder } from './runLabel';

const runs = [
  { run_id: 'c', revision_id: 'p-r02', completed_at: '2026-01-02T12:00:00Z' },
  { run_id: 'a', revision_id: 'p-r01', completed_at: '2026-01-01T12:00:00Z' },
  { run_id: 'e', revision_id: 'p-r11', completed_at: '2026-01-03T12:00:00Z' },
  { run_id: 'b', revision_id: 'p-r01', completed_at: '2026-01-01T11:00:00Z' },
];

describe('run labels', () => {
  it('labels runs by revision and order within the revision', () => {
    const labels = runVersionLabels(runs);
    expect(labels.get('a')).toBe('r01 · run 2');
    expect(labels.get('b')).toBe('r01 · run 1');
    expect(labels.get('c')).toBe('r02 · run 1');
    expect(labels.get('e')).toBe('r11 · run 1');
  });

  it('sorts by numeric revision, not lexical run id', () => {
    expect(runVersionOrder(runs).map(run => run.run_id)).toEqual(['b', 'a', 'c', 'e']);
  });

  it('keeps revision order stable when two runs share a timestamp', () => {
    const sameTime = [
      { run_id: 'second', revision_id: 'p-r02', completed_at: '2026-01-01T00:00:00Z' },
      { run_id: 'first', revision_id: 'p-r02', completed_at: '2026-01-01T00:00:00Z' },
    ];
    expect([...runVersionLabels(sameTime).values()]).toEqual(['r02 · run 1', 'r02 · run 2']);
  });

  it('shortens revision ids without changing their identity', () => {
    expect(revisionLabel('p-0d2849c85ff0-r12')).toBe('r12');
    expect(revisionLabel('p-r01')).toBe('r01');
    expect(revisionLabel(null)).toBe('—');
  });
});
