import { describe, expect, it } from 'vitest';
import { compareRecordedRunInputs } from './compareInputs';
import type { CompareSide } from '../../api/types';
const side = (patch: Partial<CompareSide> = {}): CompareSide => ({
  run_id: 'r', display_name: null, revision_id: 'rev', design_hash: 'sha256:a',
  backend: 'book-sim', status: 'EVALUATED', qualification: null, workload_id: 'w1',
  noc: { width: 64, routing: 'xy' }, locked_derived: {}, requirements_pass: null, ...patch,
});
describe('recorded run input comparison', () => {
  it('separates changed recorded inputs from output metrics and ignores object key order', () => {
    const a = side();
    const b = side({ workload_id: 'w2', noc: { routing: 'xy', width: 128 } });
    expect(compareRecordedRunInputs(a, side({ noc: { routing: 'xy', width: 64 } }))).toEqual([]);
    expect(compareRecordedRunInputs(a, b)).toEqual([
      { field: 'workload', runA: 'w1', runB: 'w2' },
      { field: 'NoC configuration', runA: '{"routing":"xy","width":64}', runB: '{"routing":"xy","width":128}' },
    ]);
  });
});
