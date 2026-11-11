import { useEffect, useRef, useState } from 'react';
import { JobEvents } from './JobEvents';
import { gateway, gatewayReason, type EvaluationPlan, type EvaluationPlanRow, type Job } from './gateway';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { Badge, Button, Empty, Notice, Properties, Section } from './ui';
import { stamp } from './format';
import { supersededNotice } from './jobAdoption';

const STAGES = ['QUEUED', 'PREPARING', 'RUNNING', 'FINALIZING'];
const TERMINAL = ['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'];
const isTerminal = (state: string) => TERMINAL.includes(state);
const stateTone = (state: string) => state === 'COMPLETED' ? 'green' : state === 'REFUSED' || state === 'FAILED' ? 'red' : state === 'CANCELLED' ? 'amber' : 'blue';
const secondsSince = (value?: string | null) => { const t = value ? Date.parse(value) : NaN; return Number.isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 1000)) : null; };
const secondsBetween = (a?: string | null, b?: string | null) => { const x = a ? Date.parse(a) : NaN, y = b ? Date.parse(b) : NaN; return Number.isFinite(x) && Number.isFinite(y) ? Math.max(0, Math.round((y - x) / 1000)) : null; };

// A running job must look alive: re-render once a second so elapsed/updated times move.
function useTicker(active: boolean) {
  const [, tick] = useState(0);
  useEffect(() => { if (!active) return; const timer = window.setInterval(() => tick(n => n + 1), 1000); return () => window.clearInterval(timer); }, [active]);
}

type PlanState = { phase: 'loading' } | { phase: 'error'; reason: string } | { phase: 'loaded'; plan: EvaluationPlan };

export function LaunchEvaluation({ project, collapsed = false }: { project: LoadedProject; collapsed?: boolean }) {
  const { evaluationJob, trackEvaluation, cancelEvaluation } = useProject();
  const revisionId = project.detail.active_revision_id;
  const superseded = supersededNotice(project.detail.active_evaluation);
  const [plan, setPlan] = useState<PlanState>({ phase: 'loading' });
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [history, setHistory] = useState<Job[]>([]);
  const [awaiting, setAwaiting] = useState(false);
  const [pendingJobId, setPendingJobId] = useState<string | null>(null);
  const job = evaluationJob.job;
  const [requested, setRequested] = useState(!collapsed);
  const needsPlan = !collapsed || requested || !!job;
  const generation = useRef(0);
  const jobPanel = useRef<HTMLDivElement>(null);
  const jobActive = !!job && !isTerminal(job.state);
  useTicker(jobActive);
  const elapsed = job ? (jobActive ? secondsSince(job.submitted_at) : secondsBetween(job.submitted_at, job.updated_at)) : null;
  const polledAgo = jobActive ? secondsSince(job.updated_at) : null;
  const jobKey = job?.job_id;

  const loadHistory = () => {
    gateway.projectJobs?.(project.detail.project.project_id, 'EVALUATION')
      .then(d => setHistory(d.jobs ?? []))
      .catch(() => setHistory([]));
  };

  useEffect(() => {
    if (!needsPlan) return;
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
  }, [revisionId, needsPlan]);

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
  // Bring the job panel into view as soon as it exists; the user just pressed a button.
  useEffect(() => {
    if (jobKey) jobPanel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [jobKey]);

  const rows: EvaluationPlanRow[] = plan.phase === 'loaded' ? (plan.plan.analyses ?? []) : [];
  const readyRows = rows.filter(r => r.readiness === 'READY' && r.question);
  const blockedRows = rows.filter(r => r.readiness !== 'READY');
  const canLaunch = plan.phase === 'loaded' && plan.plan.revision_id === revisionId && confirmed && !submitting && !awaiting && !evaluationJob.error && selected.length > 0 && !!revisionId && !(job && !isTerminal(job.state));
  const activeStage = job ? STAGES.indexOf(job.state) : -1;
  const showResults = () => {
    const strip = document.querySelector('.stat-strip');
    if (strip) strip.scrollIntoView({ behavior: 'smooth', block: 'start' });
    else location.hash = '/analysis/summary';
  };

  const body = <>
    {plan.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the evaluation plan for this revision…</p>}
    {(() => { const runs = project.detail.runs ?? []; const own = runs.filter(r => r.revision_id === revisionId); return own.length === 0 && runs.length > 0 ? <Notice tone="amber"><strong>{revisionId ?? 'Active revision'} has no run.</strong> Existing runs belong to {[...new Set(runs.map(r => r.revision_id))].join(', ')}.</Notice> : null; })()}
    {plan.phase === 'error' && <Notice tone="red"><strong>No evaluation plan available.</strong> {plan.reason}</Notice>}
    {/* A revision pins the capability state of its compile. When a withdrawn
        capability is requalified the recorded refusal is superseded, and the
        page must say so instead of showing a verdict it no longer holds. */}
    {superseded && <Notice tone="blue"><strong>An earlier refusal for this revision is superseded.</strong> {superseded}</Notice>}

    {plan.phase === 'loaded' && <>
      <div className="toolbar evaluation-context">
        <Badge tone="blue">Revision <span className="mono">{revisionId}</span></Badge>
        <Badge>{project.detail.project.name}</Badge>
        <Badge>{(project.detail.runs ?? []).length} project run{(project.detail.runs ?? []).length === 1 ? '' : 's'}</Badge>
      </div>
      <div className="table-scroll"><table className="plan-table"><thead><tr><th>Run</th><th>Question</th><th>Backend</th><th>Readiness</th><th>Qualification / model</th></tr></thead><tbody>
        {rows.map(row => {
          const name = row.question ?? 'unnamed question';
          const selectable = row.readiness === 'READY';
          const basis = row.qualification?.basis ?? row.reason ?? 'No basis stated';
          const model = row.qualification?.model_fidelity ?? row.model_fidelity ?? '—';
          return <tr key={`${name}-${row.backend}`} className={selected.includes(name) ? 'selected' : ''}>
            <td><input type="checkbox" aria-label={`Select ${name}`} disabled={!selectable || submitting} checked={selected.includes(name)} onChange={() => setSelected(s => s.includes(name) ? s.filter(q => q !== name) : [...s, name])} /></td>
            <th>{name}</th>
            <td className="mono">{row.backend ?? '—'}</td>
            <td><Badge tone={selectable ? 'green' : 'amber'}>{row.readiness ?? 'unknown'}</Badge></td>
            <td>{selectable
              ? <details className="inline-details"><summary>{model}</summary><small>{basis}</small>{!!row.limitations?.length && <ul>{row.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>}</details>
              : <details className="inline-details"><summary className="warn-text">Why blocked</summary><small>{basis}</small></details>}</td>
          </tr>;
        })}
      </tbody></table></div>
      {blockedRows.length > 0 && <p className="meta-line">{blockedRows.length} of {rows.length} questions are blocked.</p>}
      {readyRows.length === 0 && <Empty title="Nothing on this revision is ready to run">The plan reports no READY analysis.</Empty>}

      <label className="check-row"><input type="checkbox" checked={confirmed} disabled={submitting || readyRows.length === 0} onChange={e => setConfirmed(e.target.checked)} />
        I understand: run real backends and save a new run.
      </label>
      <div className="toolbar">
        <Button primary disabled={!canLaunch} onClick={launch}>{submitting ? 'Submitting…' : `Launch ${selected.length} ${selected.length === 1 ? 'analysis' : 'analyses'}`}</Button>
        <span className="muted">{selected.length} of {readyRows.length} READY question{readyRows.length === 1 ? '' : 's'} selected</span>
      </div>
    </>}

    {submitError && <Notice tone="red"><strong>The gateway refused the request.</strong> {submitError}</Notice>}
    {evaluationJob.error && <Notice tone="red"><strong>Job polling stopped.</strong> {evaluationJob.error} {pendingJobId && <Button onClick={() => trackEvaluation(pendingJobId)}>Retry job status</Button>}</Notice>}
    {awaiting && !job && !evaluationJob.error && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Submitting · waiting for the job record…</p>}

    {job && <div ref={jobPanel} className="job-panel">
      <Section title="Job" actions={<Badge tone={stateTone(job.state)}>{jobActive ? <><span className="pulse-dot" aria-hidden="true" />{job.state}</> : job.state}</Badge>}>
        {jobActive && <div className="job-progress" role="progressbar" aria-label={`Evaluation job ${job.state}`}><span /></div>}
        <ol className="job-steps" aria-label="Job stages">
          {STAGES.map((stage, i) => <li key={stage} data-state={job.state === 'COMPLETED' || activeStage > i ? 'done' : activeStage === i ? 'current' : 'pending'}>{stage.toLowerCase()}</li>)}
        </ol>
        <p className="job-timing">{jobActive ? <>Running {elapsed ?? 0}s · updated {polledAgo ?? 0}s ago · polling every 2s</> : job.state === 'COMPLETED' ? <>Completed in {elapsed ?? 0}s</> : <>{job.state} after {elapsed ?? 0}s</>}</p>
        <details className="inline-details"><summary>Job record</summary>
          <Properties rows={[[ 'Job id', <span className="mono">{job.job_id}</span> ], ['Kind', job.kind ], ['Revision', job.revision_id ?? '—' ], ['Submitted', stamp(job.submitted_at) ], ['Updated', stamp(job.updated_at) ], ['Cancellable', job.cancellable ? 'Yes' : 'No (the gateway reports it as not cancellable now)' ], ['Error code', job.error_code ?? 'None' ], ['Error message', job.error_message ?? 'None' ], ['Result', job.result?.run_id ? <span className="mono">{job.result.run_id}</span> : 'Not published' ]]} />
        </details>
        {job.cancellable && <div className="toolbar"><Button danger onClick={cancel}>Cancel job</Button></div>}
        {job.state === 'COMPLETED' && job.result?.run_id && <div className="run-published">
          <div><strong>Run published</strong><span className="mono">{job.result.run_id.slice(0, 13)}…</span><small>Selected now. Its results are on this page.</small></div>
          <Button primary onClick={showResults}>View results</Button>
        </div>}
        {(job.state === 'REFUSED' || job.state === 'FAILED') && <Notice tone="red">
          <strong>{job.state}:</strong> {job.error_message ?? 'The gateway reported no message for this job.'} {job.error_code ? `(${job.error_code})` : ''}{' '}
          {/* The run record is written even when its verdict is a failure, so a
              job that names a run must not claim that nothing was written. */}
          {job.result?.run_id
            ? <>The attempt is still recorded as a run: <span className="mono">{job.result.run_id.slice(0, 13)}…</span> — open it below to read what it reports.</>
            : 'No run was written, so nothing is shown as a result.'}
        </Notice>}
        {job.state === 'CANCELLED' && <Notice tone="amber"><strong>Cancelled</strong> by the gateway; no result is shown.</Notice>}
      </Section>
    </div>}

    {(job?.job_id || pendingJobId) && <JobEvents key={job?.job_id ?? pendingJobId!} jobId={job?.job_id ?? pendingJobId!} />}
    {history.length > 0 && <Section title="Evaluation jobs in this project" actions={<Badge>{history.length}</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Job</th><th>Revision</th><th>State</th><th>Submitted</th><th>Run</th></tr></thead><tbody>
        {history.map(h => <tr key={h.job_id}><th className="mono">{h.job_id}</th><td className="mono">{h.revision_id ?? '—'}</td><td><Badge tone={stateTone(h.state)}>{h.state}</Badge></td><td>{stamp(h.submitted_at)}</td><td className="mono">{h.result?.run_id ?? '—'}</td></tr>)}
      </tbody></table></div>
    </Section>}
  </>;

  if (!collapsed) return <Section title="Run a new evaluation on this revision" actions={<Badge tone="amber">Writes a real run</Badge>}>{body}</Section>;
  return <details className="launch-disclosure" id="launch-evaluation" open={job || awaiting ? true : undefined} onToggle={event => { if (event.currentTarget.open) setRequested(true); }}>
    <summary>Run a new evaluation on this revision <span className="muted">{plan.phase === 'loaded' ? `${readyRows.length} ready · ${blockedRows.length} blocked` : needsPlan ? 'Checking readiness…' : 'Check readiness when opened'}</span> <Badge tone="amber">Writes a real run</Badge></summary>
    <div className="launch-body">{body}</div>
  </details>;
}
