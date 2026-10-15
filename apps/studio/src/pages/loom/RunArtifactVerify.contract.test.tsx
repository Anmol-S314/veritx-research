import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, type RunVerifyView } from '../../api';
import RunArtifactVerify from './RunArtifactVerify';
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const result: RunVerifyView = { contract_version: 1, run_id: 'run-1', status: 'VERIFIED', bundle_id: 'bundle-a', file_count: 4, files_checked: 4 };
describe('gateway run artifact verification', () => {
  it('requires a selected run and displays exact gateway verification counts', async () => {
    const verify = vi.spyOn(api, 'verifyRun').mockResolvedValue(result);
    const { rerender } = render(<RunArtifactVerify runId={null} />);
    expect((screen.getByRole('button', { name: 'Verify run bundle' }) as HTMLButtonElement).disabled).toBe(true);
    rerender(<RunArtifactVerify runId="run-1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Verify run bundle' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('4/4 files'));
    expect(verify).toHaveBeenCalledWith('run-1');
    expect(screen.getByText(/imported local traces are not covered/)).toBeTruthy();
  });
  it('surfaces verification failure without a verified badge', async () => {
    vi.spyOn(api, 'verifyRun').mockRejectedValue(new Error('digest mismatch'));
    render(<RunArtifactVerify runId="run-2" />);
    fireEvent.click(screen.getByRole('button', { name: 'Verify run bundle' }));
    expect((await screen.findByRole('alert')).textContent).toContain('digest mismatch');
    expect(screen.queryByText(/VERIFIED/)).toBeNull();
  });
});
