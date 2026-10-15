import type { RunSummary } from '../../api/types';

export type RunFingerprintFreshness = 'current' | 'older' | 'unknown';

/** Compare only gateway-provided design hashes; missing hashes are unknown,
 * never assumed to match. This is metadata and never mutates/deletes a run. */
export function runFingerprintFreshness(
  runHash: string | null | undefined,
  currentHash: string | null | undefined,
): RunFingerprintFreshness {
  if (!runHash || !currentHash) return 'unknown';
  return runHash === currentHash ? 'current' : 'older';
}

/** Search list metadata only; it does not rank or alter any run. */
export function filterRunHistory(
  runs: RunSummary[],
  query: string,
  currentDesignHash?: string | null,
): RunSummary[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return runs;
  return runs.filter(run => [
    run.run_id, run.display_name, run.backend, run.workload_id, run.design_hash, run.status,
    runFingerprintFreshness(run.design_hash, currentDesignHash) === 'older'
      ? 'older project fingerprint'
      : runFingerprintFreshness(run.design_hash, currentDesignHash) === 'current'
        ? 'current project fingerprint' : 'fingerprint freshness unknown',
  ].some(value => value?.toLocaleLowerCase().includes(needle)));
}
