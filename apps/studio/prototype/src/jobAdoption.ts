import type { Job } from './gateway';

const TERMINAL = ['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'];

/** Which job, if any, a freshly loaded project may resume tracking.
 *
 *  Opening a project resumes an in-flight evaluation. That adoption must never
 *  override a job the user submitted in the meantime: the launch already called
 *  `trackEvaluation`, and switching the panel to an older job leaves the new one
 *  unwatched — which is how a launch could appear to fail while its run was
 *  written. Only a non-terminal job can be resumed, and the newest one wins. */
export function adoptableJob(jobs: Job[], options: { explicitTracking: boolean }): Job | null {
  if (options.explicitTracking) return null;
  const live = jobs.filter(job => !!job.job_id && !TERMINAL.includes(job.state));
  const newest = [...live].sort((a, b) => String(a.submitted_at ?? '').localeCompare(String(b.submitted_at ?? '')));
  return newest.at(-1) ?? null;
}

/** Whether the launch panel must say that a recorded refusal is superseded.
 *
 *  Only a stored refusal whose capability was requalified produces this; a live
 *  refusal has no `superseded_refusal` field, so nothing is excused. */
export function supersededNotice(assessment: { support?: string; reason?: string | null; superseded_refusal?: { recorded_support?: string; recorded_reason?: string | null; re_derived_at?: string } | null } | null | undefined): string | null {
  const record = assessment?.superseded_refusal;
  if (!record) return null;
  const recorded = record.recorded_support ?? 'UNSUPPORTED';
  const when = record.re_derived_at ? ` (re-derived ${record.re_derived_at})` : '';
  const why = record.recorded_reason ? ` It recorded: ${record.recorded_reason}` : '';
  return `This revision recorded ${recorded} when it was compiled.${why} The current capability state supports the design${when}, so the recorded refusal no longer blocks a run. The plan below is derived from the live state, not from that record; recompiling is not required.`;
}
