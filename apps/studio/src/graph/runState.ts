export type RunStatus = 'queued' | 'preparing' | 'running' | 'parsing' | 'completed' | 'failed' | 'cancelled' | 'timed-out';
export interface RunState { runId: string; status: RunStatus; updatedAt: string; error?: string }
const TRANSITIONS: Record<RunStatus, readonly RunStatus[]> = {
  queued: ['preparing', 'failed', 'cancelled'],
  preparing: ['running', 'failed', 'cancelled'],
  running: ['parsing', 'failed', 'cancelled', 'timed-out'],
  parsing: ['completed', 'failed'],
  completed: [], failed: [], cancelled: [], 'timed-out': [],
};
export function createRunState(runId: string, now = new Date().toISOString()): RunState {
  if (!runId.trim()) throw new Error('runId must be non-empty');
  return { runId, status: 'queued', updatedAt: now };
}
export function transitionRun(state: RunState, next: RunStatus, now = new Date().toISOString(), error?: string): RunState {
  if (!TRANSITIONS[state.status].includes(next)) throw new Error(`invalid run transition ${state.status} → ${next}`);
  if ((next === 'failed' || next === 'timed-out') && !error?.trim()) throw new Error(`${next} transition requires an error reason`);
  return { runId: state.runId, status: next, updatedAt: now, ...(error ? { error } : {}) };
}
/** Parse a persisted record before recovery; invalid states are never trusted. */
export function parseRunState(value: unknown): RunState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('run state must be an object');
  const candidate = value as Record<string, unknown>;
  const statuses = Object.keys(TRANSITIONS);
  if (typeof candidate.runId !== 'string' || !candidate.runId.trim()) throw new Error('run state has invalid runId');
  if (typeof candidate.status !== 'string' || !statuses.includes(candidate.status)) throw new Error('run state has invalid status');
  if (typeof candidate.updatedAt !== 'string' || !Number.isFinite(Date.parse(candidate.updatedAt))) throw new Error('run state has invalid updatedAt');
  if (candidate.error !== undefined && typeof candidate.error !== 'string') throw new Error('run state has invalid error');
  if ((candidate.status === 'failed' || candidate.status === 'timed-out') && (typeof candidate.error !== 'string' || !candidate.error.trim())) throw new Error('failed run state requires an error reason');
  return { runId: candidate.runId, status: candidate.status as RunStatus, updatedAt: candidate.updatedAt, ...(candidate.error ? { error: candidate.error as string } : {}) };
}
