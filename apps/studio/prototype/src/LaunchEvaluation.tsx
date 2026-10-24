import { useEffect, useRef, useState } from 'react';
import { JobEvents } from './JobEvents';
import { gateway, gatewayReason, type EvaluationPlan, type EvaluationPlanRow, type Job } from './gateway';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { Badge, Button, Empty, Notice, PageLink, Properties, Section } from './ui';

const STAGES = ['QUEUED', 'PREPARING', 'RUNNING', 'FINALIZING'];
const TERMINAL = ['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'];
const isTerminal = (state: string) => TERMINAL.includes(state);
const stateTone = (state: string) => state === 'COMPLETED' ? 'green' : state === 'REFUSED' || state === 'FAILED' ? 'red' : state === 'CANCELLED' ? 'amber' : 'blue';
const stamp = (value?: string | null) => value ? value.replace('T', ' ').replace('+00:00', 'Z') : '—';

type PlanState = { phase: 'loading' } | { phase: 'error'; reason: string } | { phase: 'loaded'; plan: EvaluationPlan };

export function LaunchEvaluation({ project }: { project: LoadedProject }) {
  const { evaluationJob, trackEvaluation, cancelEvaluation } = useProject();
  const revisionId = project.detail.active_revision_id;
  const [plan, setPlan] = useState<PlanState>({ phase: 'loading' });
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [history, setHistory] = useState<Job[]>([]);
  const [awaiting, setAwaiting] = useState(false);
  const [pendingJobId, setPendingJobId] = useState<string | null>(null);
  const job = evaluationJob.job;
  const generation = useRef(0);

  const loadHistory = () => {
    gateway.projectJobs?.(project.detail.project.project_id, 'EVALUATION')
      .then(d => setHistory(d.jobs ?? []))
      .catch(() => setHistory([]));
  };

  useEffect(() => {
    if (!revisionId) { setPlan({ phase: 'error', reason: 'This project has no active revision to evaluate.' }); return; }
    let live = true;
    ++generation.current;
    setConfirmed(false); setSelected([]); setSubmitError(null); setAwaiting(false); setHistory([]);
    setPlan({ phase: 'loading' });
    gateway.evaluationPlan(revisionId)
      .then(result => {
        if (!live) return;
        setPlan({ phase: 'loaded', plan: result });
        const ready = (result.analyses ?? []).filter(a => a.readiness === 'READY' && a.question).map(a => a.question as string);
        setSelected(ready);
      })
      .catch(error => { if (live) setPlan({ phase: 'error', reason: gatewayReason(error) }); });
    loadHistory();
    return () => { live = false; ++generation.current; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revisionId]);

  const launch = async () => {
    if (!revisionId || plan.phase !== 'loaded' || plan.plan.revision_id !== revisionId || !confirmed || !selected.length || selected.some(q => !(plan.plan.analyses ?? []).some(row => row.question === q && row.readiness === 'READY'))) return;
    const ticket = generation.current;
    setSubmitting(true); setSubmitError(null); setAwaiting(true);
    try {
      const submitted = await gateway.evaluate(revisionId, { questions: selected });
      if (ticket === generation.current) { setPendingJobId(submitted.job_id); trackEvaluation(submitted.job_id); }
    } catch (error) {
      if (ticket === generation.current) { setSubmitError(gatewayReason(error)); setAwaiting(false); }
    } finally {
      if (ticket === generation.current) setSubmitting(false);
    }
  };

  const cancel = () => cancelEvaluation();

  const jobState = job?.state ?? '';
  useEffect(() => {
    if (job) setAwaiting(false);
  }, [job]);
  useEffect(() => {
    if (jobState && TERMINAL.includes(jobState)) loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobState]);

  const rows: EvaluationPlanRow[] = plan.phase === 'loaded' ? (plan.plan.analyses ?? []) : [];
  const readyRows = rows.filter(r => r.readiness === 'READY' && r.question);
  const blockedRows = rows.filter(r => r.readiness !== 'READY');
  const canLaunch = plan.phase === 'loaded' && plan.plan.revision_id === revisionId && confirmed && !submitting && !awaiting && !evaluationJob.error && selected.length > 0 && !!revisionId && !(job && !isTerminal(job.state));
  const activeStage = job ? STAGES.indexOf(job.state) : -1;

  return <>
    <Section title="Run a new evaluation on this revision" actions={<Badge tone="amber">Writes a real run</Badge>}>
      <Notice tone="amber"><strong>Runs real backends and appends a run to this project.</strong></Notice>
      <Properties rows={[[ 'Revision', <span className="mono">{revisionId ?? 'none'}</span> ], ['Project', `${project.detail.project.name} (${project.detail.project.project_id})` ], ['Backends chosen by', 'The gateway, per question, from its own evaluation plan' ], ['Progress reported', 'Job state only; no percentage or ETA is invented' ], ['Existing runs in project', String((project.detail.runs ?? []).length) ]]} />

      {plan.phase === 'loading' && <p>Reading the evaluation plan for this revision…</p>}
      {(() => { const runs = project.detail.runs ?? []; const own = runs.filter(r => r.revision_id === revisionId); return own.length === 0 && runs.length > 0 ? <Notice tone="amber"><strong>{revisionId ?? 'Active revision'} has no run.</strong> Existing runs belong to {[...new Set(runs.map(r => r.revision_id))].join(', ')}.</Notice> : null; })()}
      {plan.phase === 'error' && <Notice tone="red"><strong>No evaluation plan available.</strong> {plan.reason}</Notice>}
      {plan.phase === 'loaded' && <>
        <h3>Questions this revision can answer</h3>
        <div className="table-scroll"><table><thead><tr><th>Run</th><th>Question</th><th>Backend</th><th>Readiness</th><th>Qualification</th><th>Model</th></tr></thead><tbody>
          {rows.map(row => {
            const name = row.question ?? 'unnamed question';
            const selectable = row.readiness === 'READY';
            return <tr key={`${name}-${row.backend}`} className={selected.includes(name) ? 'selected' : ''}>
              <td><input type="checkbox" aria-label={`Select ${name}`} disabled={!selectable || submitting} checked={selected.includes(name)} onChange={() => setSelected(s => s.includes(name) ? s.filter(q => q !== name) : [...s, name])} /></td>
              <th>{name}</th>
              <td className="mono">{row.backend ?? '—'}</td>
              <td><Badge tone={selectable ? 'green' : 'amber'}>{row.readiness ?? 'unknown'}</Badge></td>
              <td><small>{row.qualification?.basis ?? row.reason ?? 'No basis stated'}</small></td>
              <td><small>{row.qualification?.model_fidelity ?? row.model_fidelity ?? '—'}</small></td>
            </tr>;
          })}
        </tbody></table></div>
        {blockedRows.length > 0 && <p>{blockedRows.length} question{blockedRows.length === 1 ? ' is' : 's are'} not READY and cannot be selected. The gateway states why above; this page does not override it.</p>}
        {readyRows.length === 0 && <Empty title="Nothing on this revision is ready to run">The plan reports no READY analysis, so no launch is offered.</Empty>}

        <label className="check-row"><input type="checkbox" checked={confirmed} disabled={submitting || readyRows.length === 0} onChange={e => setConfirmed(e.target.checked)} />
          I understand this runs real backend binaries on this host and appends a new run to {project.detail.project.name}.
        </label>
        <div className="toolbar">
          <Button primary disabled={!canLaunch} onClick={launch}>{submitting ? 'Submitting…' : `Launch ${selected.length} ${selected.length === 1 ? 'analysis' : 'analyses'}`}</Button>
          <span className="muted">{selected.length} of {readyRows.length} READY question{readyRows.length === 1 ? '' : 's'} selected</span>
        </div>
      </>}

      {submitError && <Notice tone="red"><strong>The gateway refused the request.</strong> {submitError}</Notice>}
      {evaluationJob.error && <Notice tone="red"><strong>Job polling stopped.</strong> {evaluationJob.error} {pendingJobId && <Button onClick={() => trackEvaluation(pendingJobId)}>Retry job status</Button>}</Notice>}

      {awaiting && !job && !evaluationJob.error && <Notice tone="blue">Waiting for the job record…</Notice>}
      {job && <Section title="Job" actions={<Badge tone={stateTone(job.state)}>{job.state}</Badge>}>
        <Properties rows={[[ 'Job id', <span className="mono">{job.job_id}</span> ], ['Kind', job.kind ], ['Revision', job.revision_id ?? '—' ], ['Submitted', stamp(job.submitted_at) ], ['Updated', stamp(job.updated_at) ], ['Cancellable', job.cancellable ? 'Yes' : 'No (the gateway reports it as not cancellable now)' ], ['Error code', job.error_code ?? 'None' ], ['Error message', job.error_message ?? 'None' ], ['Result', job.result?.run_id ? <a className="mono" href="#/analysis/summary">{job.result.run_id}</a> : 'Not published' ]] } />
        <div className="toolbar">
          {STAGES.map((stage, i) => <Badge key={stage} tone={activeStage > i || job.state === 'COMPLETED' ? 'green' : activeStage === i ? 'blue' : 'neutral'}>{stage}</Badge>)}
          {job.cancellable && <Button danger onClick={cancel}>Cancel job</Button>}
        </div>
        {job.state === 'COMPLETED' && job.result?.run_id && <Notice tone="blue"><strong>Run published:</strong> <span className="mono">{job.result.run_id}</span> — selected now. <PageLink page="analysis/summary">Open analysis</PageLink></Notice>}
        {(job.state === 'REFUSED' || job.state === 'FAILED') && <Notice tone="red"><strong>{job.state}:</strong> {job.error_message ?? 'No message supplied.'} {job.error_code ? `(${job.error_code})` : ''} Nothing written.</Notice>}
        {job.state === 'CANCELLED' && <Notice tone="amber"><strong>Cancelled</strong> by the gateway; no result is shown.</Notice>}
        {!isTerminal(job.state) && <p>Polling <code>/jobs/{'{job_id}'}</code> every 2 s.</p>}
      </Section>}

      {(job?.job_id || pendingJobId) && <JobEvents key={job?.job_id ?? pendingJobId!} jobId={job?.job_id ?? pendingJobId!} />}
      {history.length > 0 && <Section title="Evaluation jobs in this project" actions={<Badge>{history.length}</Badge>}>
        <div className="table-scroll"><table><thead><tr><th>Job</th><th>Revision</th><th>State</th><th>Submitted</th><th>Run</th></tr></thead><tbody>
          {history.map(h => <tr key={h.job_id}><th className="mono">{h.job_id}</th><td className="mono">{h.revision_id ?? '—'}</td><td><Badge tone={stateTone(h.state)}>{h.state}</Badge></td><td>{stamp(h.submitted_at)}</td><td className="mono">{h.result?.run_id ?? '—'}</td></tr>)}
        </tbody></table></div>
      </Section>}
    </Section>
  </>;
}
