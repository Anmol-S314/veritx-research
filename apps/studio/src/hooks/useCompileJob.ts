import { useEffect, useState } from 'react';
import { api, type JobView } from '../api';
import { useAsync, useJobPoll } from '../studio';

export const jobActive = (job: JobView | null): boolean => !!job
  && !['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state);

/** Recover active work after navigation; never replay an old completed compile. */
export function useCompileJob(projectId: string | undefined, onTerminal: (job: JobView) => void) {
  const history = useAsync(() => projectId ? api.projectJobs(projectId, 'COMPILE')
    : Promise.resolve({ contract_version: 1 as const, jobs: [] as JobView[] }), [projectId]);
  const [selected, setSelected] = useState<JobView | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    if (history.result.state === 'ready' && !selected) {
      setSelected(history.result.data.jobs.find(jobActive) ?? null);
    }
  }, [history.result, selected]);
  const polled = useJobPoll(selected?.job_id ?? null, onTerminal, setError);
  const job = polled?.job_id === selected?.job_id ? polled : selected;
  const submit = async (hash: string): Promise<void> => {
    setSubmitting(true);
    setError(null);
    try {
      if (!projectId) throw new Error('Select a project before compiling.');
      setSelected(await api.compileJob(projectId, hash));
    }
    catch (err) { setError(err instanceof Error ? err : new Error(String(err))); }
    finally { setSubmitting(false); }
  };
  return { job, submit, error: error ?? (history.result.state === 'error' ? history.result.error : null),
    active: submitting || jobActive(job) || history.result.state === 'loading', retry: history.reload };
}
