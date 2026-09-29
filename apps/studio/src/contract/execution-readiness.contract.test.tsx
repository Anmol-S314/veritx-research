/** Execution-readiness matching contract (fixtures only).
 *
 * Backend families match the top-level run backend OR any per-analysis
 * backend in a federated run. The displayed status is always the matched
 * leg's own status — never borrowed, never "no run" when evidence exists.
 */
import { describe, expect, it } from 'vitest';
import { render, within } from '@testing-library/react';
import { ExecutionReadiness } from '../components/ProjectHeader';
import type { RunSummary } from '../api/types';

function summary(over: Partial<RunSummary>): RunSummary {
  return {
    run_id: 'r',
    display_name: null,
    project_id: 'p',
    revision_id: 'r',
    design_hash: null,
    backend: null,
    status: null,
    qualification: null,
    requirements_pass: null,
    started_at: null,
    completed_at: null,
    bundle_id: null,
    workload_id: null,
    completion_cycles: null,
    ...over,
  };
}

function sectionOf(container: HTMLElement): HTMLElement {
  return within(container).getByText('Execution').closest('section')!;
}

describe('ExecutionReadiness matching', () => {
  it('matches top-level backends (happy path)', () => {
    const { container } = render(
      <ExecutionReadiness
        runs={[
          summary({ run_id: 'a', backend: 'BOOKSIM_STANDALONE',
            status: 'EVALUATED', qualification: 'QUALIFIED',
            completion_cycles: 100 }),
        ]}
      />,
    );
    const section = sectionOf(container);
    expect(within(section).getByText('EVALUATED')).toBeTruthy();
    expect(within(section).getAllByText('no run').length).toBe(3);
  });

  it('matches per-analysis backends inside a federated run', () => {
    const { container } = render(
      <ExecutionReadiness
        runs={[
          summary({
            run_id: 'fed-1',
            backend: 'BOOKSIM_STANDALONE',
            status: 'EVALUATED',
            qualification: 'QUALIFIED',
            analysis_backends: [
              { backend_id: 'BOOKSIM_STANDALONE',
                question: 'NETWORK_COMPLETION', status: 'EVALUATED' },
              { backend_id: 'ASTRA2_EMBEDDED_BOOKSIM',
                question: 'SYSTEM_MAKESPAN', status: 'EVALUATED' },
              { backend_id: 'RAMULATOR2_HBM3_V1',
                question: 'DRAM_TIMING', status: 'BLOCKED' },
            ],
          }),
        ]}
      />,
    );
    const section = sectionOf(container);
    // ASTRA is evidence, not "no run", with its own leg status.
    const runs = within(section).getAllByText('open run');
    expect(runs.length).toBe(3);
    expect(within(section).getByText('BLOCKED')).toBeTruthy();
    // SERVING has no evidence anywhere: honestly "no run".
    const noRuns = within(section).getAllByText('no run');
    expect(noRuns.length).toBe(1);
  });

  it('never borrows another backend status', () => {
    const { container } = render(
      <ExecutionReadiness
        runs={[
          summary({
            run_id: 'fed-2',
            backend: 'BOOKSIM_STANDALONE',
            status: 'FAILED',
            analysis_backends: [
              { backend_id: 'ASTRA2_EMBEDDED_BOOKSIM',
                question: 'SYSTEM_MAKESPAN', status: 'EVALUATED' },
            ],
          }),
        ]}
      />,
    );
    const section = sectionOf(container);
    // The ASTRA row shows EVALUATED (its leg), while the BOOKSIM row
    // keeps the run's FAILED — per-row statuses, never borrowed.
    const rows = within(section).getAllByText('open run').map(
      (link) => link.closest('div.kv')?.textContent ?? '',
    );
    const astra = rows.find((t) => t.includes('ASTRA')) ?? '';
    const booksim = rows.find((t) => t.includes('BookSim')) ?? '';
    expect(astra).toContain('EVALUATED');
    expect(astra).not.toContain('FAILED');
    expect(booksim).toContain('FAILED');
  });
});
