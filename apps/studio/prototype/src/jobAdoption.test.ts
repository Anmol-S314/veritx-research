import { expect, it } from 'vitest';
import type { Job } from './gateway';
import { adoptableJob, supersededNotice } from './jobAdoption';

const job = (id: string, state: string, submitted_at: string): Job => ({ job_id: id, project_id: 'p', kind: 'EVALUATION', state, submitted_at });

it('never adopts a job over one the user just submitted', () => {
  const jobs = [job('old-running', 'RUNNING', '2026-10-27T08:00:00+00:00'), job('new', 'QUEUED', '2026-10-27T09:00:00+00:00')];
  expect(adoptableJob(jobs, { explicitTracking: true })).toBeNull();
  // A launch already moved the panel to the job it submitted; adopting a
  // different job is what left the panel stuck on an older failure.
});

it('resumes the newest in-flight job when opening a project', () => {
  const jobs = [
    job('interrupted', 'FAILED', '2026-10-27T08:00:00+00:00'),
    job('older', 'RUNNING', '2026-10-27T08:30:00+00:00'),
    job('newest', 'FINALIZING', '2026-10-27T08:45:00+00:00'),
    job('done', 'COMPLETED', '2026-10-27T08:50:00+00:00'),
  ];
  expect(adoptableJob(jobs, { explicitTracking: false })?.job_id).toBe('newest');
});

it('adopts nothing when every job is terminal, and nothing when there are none', () => {
  expect(adoptableJob([job('a', 'COMPLETED', '2026-10-27T08:00:00+00:00'), job('b', 'REFUSED', '2026-10-27T08:05:00+00:00')], { explicitTracking: false })).toBeNull();
  expect(adoptableJob([], { explicitTracking: false })).toBeNull();
});

it('an interrupted job is never resumed', () => {
  // A gateway restart marks running jobs FAILED; adopting one would poll a dead
  // record and show a previous failure as if it were the current attempt.
  const jobs = [job('interrupted', 'FAILED', '2026-10-27T08:00:00+00:00')];
  expect(adoptableJob(jobs, { explicitTracking: false })).toBeNull();
});

it('names a superseded refusal and stays silent for a live one', () => {
  const superseded = supersededNotice({ support: 'SUPPORTED', superseded_refusal: { recorded_support: 'UNSUPPORTED', recorded_reason: 'CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1 is a WITHDRAWN capability', re_derived_at: '2026-10-27T09:00:00+00:00' } });
  expect(superseded).toContain('This revision recorded UNSUPPORTED');
  expect(superseded).toContain('WITHDRAWN capability');
  expect(superseded).toContain('recompiling is not required');
  // A refusal that still applies carries no supersession record.
  expect(supersededNotice({ support: 'UNSUPPORTED', reason: 'UNSUPPORTED: seat_capacity' })).toBeNull();
  expect(supersededNotice(null)).toBeNull();
});
