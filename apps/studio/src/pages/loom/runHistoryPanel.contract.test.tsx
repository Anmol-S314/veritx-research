import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { RunSummary } from '../../api/types';
import RunHistoryPanel from './RunHistoryPanel';

const run = (run_id: string, patch: Partial<RunSummary> = {}): RunSummary => ({
  run_id, display_name: null, project_id: 'p', revision_id: 'rev', design_hash: null,
  backend: null, status: null, qualification: null, requirements_pass: null,
  started_at: null, completed_at: null, bundle_id: null, workload_id: null, completion_cycles: null,
  ...patch,
});

describe('RunHistoryPanel', () => {
  it('renders and searches completed and failed summaries by backend/workload/fingerprint/status', () => {
    const completed = run('run-complete', { status: 'EVALUATED', backend: 'book-sim', workload_id: 'work-a', design_hash: 'current-hash' });
    const failed = run('run-failed', { status: 'FAILED', backend: 'astra', workload_id: 'work-b', design_hash: 'older-hash' });
    const view = render(<RunHistoryPanel runs={[completed, failed]} currentDesignHash="current-hash" />);

    expect(screen.getByText(/2 of 2 runs · includes non-evaluated outcomes/)).toBeTruthy();
    const records = [...view.container.querySelectorAll('li')].map(item => item.textContent ?? '');
    expect(records).toHaveLength(2);
    expect(records[0]).toMatch(/run-complete.*EVALUATED.*book-sim.*work-a.*current-hash/);
    expect(records[1]).toMatch(/run-failed.*FAILED.*astra.*work-b.*older-hash/);
    expect(screen.getByLabelText('Project fingerprint older')).toBeTruthy();

    const search = screen.getByRole('textbox', { name: 'Search run history' });
    fireEvent.change(search, { target: { value: 'FAILED' } });
    expect(screen.getByText(/1 of 2 runs/)).toBeTruthy();
    expect(screen.getByText(/run-failed/)).toBeTruthy();
    expect(screen.queryByText(/run-complete/)).toBeNull();
    fireEvent.change(search, { target: { value: 'work-a' } });
    expect(screen.getByText(/run-complete/)).toBeTruthy();
    expect(screen.queryByText(/run-failed/)).toBeNull();
  });
});
