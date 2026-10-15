import type { CompareSide } from '../../api/types';
import { canonicalJson } from '../../graph/engineProtocol';

export interface RunInputDifference { field: string; runA: string; runB: string }
const display = (value: unknown): string => value == null ? '—'
  : typeof value === 'object' ? canonicalJson(value) : String(value);

/** Compares only input fields actually recorded on the gateway's run sides.
 * It is not a complete project semantic diff or proof that omitted fields match. */
export function compareRecordedRunInputs(a: CompareSide, b: CompareSide): RunInputDifference[] {
  const fields: [keyof CompareSide, string][] = [
    ['revision_id', 'revision'], ['design_hash', 'design fingerprint'],
    ['backend', 'backend'], ['workload_id', 'workload'],
    ['noc', 'NoC configuration'], ['locked_derived', 'locked derived configuration'],
  ];
  return fields.flatMap(([key, field]) => {
    const runA = display(a[key]);
    const runB = display(b[key]);
    return runA === runB ? [] : [{ field, runA, runB }];
  });
}
