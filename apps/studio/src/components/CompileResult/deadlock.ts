import type { CdgAnalysis } from '../../api';

export type DeadlockTone = 'ok' | 'bad' | 'muted';

export interface DeadlockMessage {
  tone: DeadlockTone;
  text: string;
}

export function deadlockMessage(
  analysis: CdgAnalysis | null | undefined,
): DeadlockMessage {
  const verdict = analysis?.analysis_verdict ?? 'NOT_RUN';
  switch (verdict) {
    case 'PASS':
      return {
        tone: 'ok',
        text: 'DEADLOCK_FREE established — the channel/VC dependency '
          + 'graph is acyclic. No cycle witness exists.',
      };
    case 'FAIL':
      return {
        tone: 'bad',
        text: 'Deadlock freedom not established — a dependency cycle '
          + 'was found.',
      };
    case 'UNSUPPORTED':
      return {
        tone: 'muted',
        text: 'Deadlock analysis unsupported for this routing/resource '
          + 'profile. No DEADLOCK_FREE claim is made.',
      };
    case 'NOT_RUN':
    default:
      return {
        tone: 'muted',
        text: 'Deadlock analysis was not run.',
      };
  }
}
