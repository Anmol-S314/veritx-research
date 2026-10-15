import { describe, expect, it } from 'vitest';
import { createRunState, parseRunState, transitionRun } from './runState';

describe('run-state transitions', () => {
  it('follows queued→preparing→running→parsing→completed and serializes for recovery', () => {
    let state = createRunState('r-1', '2026-01-01T00:00:00Z');
    state = transitionRun(state, 'preparing', '2026-01-01T00:00:01Z');
    state = transitionRun(state, 'running', '2026-01-01T00:00:02Z');
    state = transitionRun(state, 'parsing', '2026-01-01T00:00:03Z');
    state = transitionRun(state, 'completed', '2026-01-01T00:00:04Z');
    expect(parseRunState(JSON.parse(JSON.stringify(state)))).toEqual(state);
    expect(() => transitionRun(state, 'running')).toThrow(/invalid run transition/);
  });
  it('requires actionable failure reasons and rejects corrupt persisted state', () => {
    expect(() => transitionRun(createRunState('r-2'), 'failed')).toThrow(/requires an error reason/);
    expect(() => parseRunState({ runId: 'r', status: 'mystery', updatedAt: 'bad' })).toThrow(/invalid status/);
    expect(() => parseRunState({ runId: 'r', status: 'failed', updatedAt: '2026-01-01T00:00:00Z' })).toThrow(/requires an error reason/);
  });
});
