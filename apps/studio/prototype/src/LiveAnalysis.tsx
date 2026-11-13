import { Fragment, useEffect, useRef, useState } from 'react';
import { EvidenceDocuments } from './EvidenceDocuments';
import { RawArtifacts, fetchVerifiedArtifact } from './RawArtifacts';
import AnalysisCurves from './AnalysisCurves';
import { useGatewayDocument } from './LiveOperations';
import { useLoadedProject, useLoadedRun, useProject } from './project';
import type { LoadedProject, LoadedRun } from './project';
import { gateway, gatewayReason, type Comparison, type ComparisonRow, type RunDetail } from './gateway';
import { Assumptions, Badge, Button, Empty, Inspector, Notice, PageLink, Properties, Section } from './ui';
import { LaunchEvaluation } from './LaunchEvaluation';
import { TrustChecks } from './TrustChecks';
import { MeasuredLinks, MeasuredRouterTotals, ObservedRunPlayback, RouteSweep, RunFlitPlayback, RunHistory, useRunTopology } from './LiveSimulation';
import { useSimLoad } from './measuredData';
import { MeasuredLoadShape } from './MeasuredLoadShape';
import { MeasuredDelayCost } from './MeasuredDelayCost';
import { CycleBudget } from './CycleBudget';
import type { UtilizationRange } from './channelAnalysis';
import { bytes as bytesLabel, cappedClass, num, shortText } from './format';
import { revisionLabel, runVersionLabels } from './runLabel';
import { RevisionHistory, RunSelect } from './RevisionHistory';
import { contextTarget } from './contextSelection';

const short = (value?: string | null, keep = 20) => shortText(value, keep, 'Not supplied');

export function LiveGate({ children, tab = 'summary', onTabChange }: {
  children: (project: LoadedProject, run: LoadedRun) => React.ReactNode;
  tab?: AnalysisTab; onTabChange?: (tab: AnalysisTab) => void;
}) {
  const { run: runState, loadRun } = useProject();
  const project = useLoadedProject();
  const run = useLoadedRun();
  // A run switch sets phase=loading, which makes useLoadedRun return null.
  // Keep the last successfully loaded run for the same project so the page
  // does not fall back to the run picker table or reset its analysis tab.
  const cached = useRef<{ projectId: string; run: LoadedRun } | null>(null);
  const currentRun = run && project && run.detail.project_id === project.detail.project.project_id ? run : null;
  if (project && currentRun) cached.current = { projectId: project.detail.project.project_id, run: currentRun };
  const shown = currentRun ?? (project && cached.current?.projectId === project.detail.project.project_id ? cached.current.run : null);
  if (!project) return <div className="view-main"><Empty title="No project loaded">Load a project from <a href="#/shared/projects">Projects &amp; revisions</a> to read its evaluations from the gateway.</Empty><Assumptions rows={[['Scope', 'Readings come from a gateway project; without one there is nothing to read.']]} /></div>;
  if (!shown && tab === 'curves') {
    // Curves & Pareto carries a measured workload reference that does not
    // depend on a run. Keep the section tabs visible and render that
    // reference instead of the generic run gate.
    return <div className="view-main">
      <Notice tone="blue"><strong>{project.detail.project.name}: no evaluation selected.</strong> Showing the measured workload reference.</Notice>
      <div className="analysis-tabs" role="tablist" aria-label="Analysis sections">
        {ANALYSIS_TABS.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id}
          className={tab === item.id ? 'active' : ''} onClick={() => onTabChange?.(item.id)}>{item.label}</button>)}
      </div>
      <AnalysisCurves project={project} />
      <Assumptions rows={[
        ['Workload reference', 'Measured repository evidence, not this project’s candidates.'],
        ['Project study', 'Requires a completed optimization study.'],
      ]} />
    </div>;
  }
  if (!shown) {
    const runs = project.detail.runs ?? [];
    return <div className="view-main">
      <Notice tone="amber"><strong>{project.detail.project.name}: no evaluation selected.</strong> {runs.length ? 'Pick a run below.' : 'This project has no runs.'}</Notice>
      {runState.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Loading run {short(runState.runId, 24)}…</p>}
      {runState.phase === 'error' && <Notice tone="red">{runState.reason}</Notice>}
      {/* The readings are sections of this page, so the section list stays
          visible and each section says what it needs. Removing the list makes
          the workspace look broken rather than unpopulated. */}
      <div className="analysis-tabs" role="tablist" aria-label="Analysis sections">
        {ANALYSIS_TABS.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id}
          className={tab === item.id ? 'active' : ''} onClick={() => onTabChange?.(item.id)}>{item.label}</button>)}
      </div>
      <Section title={`${ANALYSIS_TABS.find(item => item.id === tab)?.label ?? 'Analysis'} needs a run`}>
        <Properties rows={[
          ['Reads', ANALYSIS_NEEDS[tab]],
          ['This project', runs.length ? `${runs.length} run${runs.length === 1 ? '' : 's'} recorded` : 'no runs recorded'],
          ['Why this is empty', runs.length ? 'No run is selected, so nothing is read on this page yet.' : 'No evaluation has been published for this project, so no run exists to read.'],
        ]} />
      </Section>
      <RevisionHistory
        revisions={project.detail.revisions ?? []}
        runs={runs}
        activeRevisionId={project.detail.active_revision_id}
        selectedRunId={null}
        onOpenRun={loadRun}
      />
      <LaunchEvaluation project={project} />
      <Assumptions rows={[
        ['Not measured', 'An unmeasured value is unavailable, not zero and not a pass.'],
      ]} />
    </div>;
  }
  return <>{children(project, shown)}</>;
}

export function RunBar({ project, run, actions }: { project: LoadedProject; run: LoadedRun; actions?: React.ReactNode }) {
  const { loadRun, run: runState } = useProject();
  const runs = project.detail.runs ?? [];
  const pendingRun = runState.phase === 'loading' ? runState.runId : null;
  return <div className="toolbar run-bar">
    <RunSelect
      revisions={project.detail.revisions ?? []}
      runs={runs}
      value={pendingRun ?? run.detail.run_id}
      onChange={loadRun}
      ariaLabel="Selected run"
      activeRevisionId={project.detail.active_revision_id}
    />
    {pendingRun && <Badge tone="amber">Loading run…</Badge>}
    {runState.phase === 'error' && <Badge tone="red" title={runState.reason}>Run load failed</Badge>}
    {project.draftMeta?.dirty && <Badge tone="amber" title="The draft has changes that are not in this run's revision. This run still describes the saved revision.">Draft edited</Badge>}
    {actions && <span className="toolbar-end">{actions}</span>}
  </div>;
}


function questionRole(question?: string | null): string {
  if (!question) return 'Evidence';
  if (/DRAM|MEMORY/i.test(question)) return 'Memory';
  if (/^NETWORK/i.test(question)) return 'Network';
  if (/SYSTEM|RANK|MAKESPAN|COMMUNICATION/i.test(question)) return 'System';
  return 'Evidence';
}


export function LiveAnalysisSummary({ project, run, onTabChange }: {
  project: LoadedProject; run: LoadedRun; onTabChange?: (tab: AnalysisTab) => void;
}) {
  const d = run.detail;
  const metrics = d.evaluation?.metrics ?? {};
  const metricKeys = [...METRIC_ORDER.filter(key => metrics[key] !== undefined), ...Object.keys(metrics).filter(key => !METRIC_ORDER.includes(key))];
  const knownMetricKeys = new Set(METRIC_GROUPS.flatMap(group => group.keys));
  const metricGroups = [
    ...METRIC_GROUPS.map(group => ({ ...group, keys: group.keys.filter(key => metricKeys.includes(key)) })).filter(group => group.keys.length),
    ...(metricKeys.some(key => !knownMetricKeys.has(key)) ? [{ label: 'Other reported values', keys: metricKeys.filter(key => !knownMetricKeys.has(key)) }] : []),
  ];
  const entries = d.requirements?.entries ?? [];
  const satisfied = entries.filter(e => /SATISFIED|PASS|MET/i.test(String(e.verdict))).length;
  const failed = entries.filter(e => /FAIL|VIOLAT|UNSATISF|UNMET/i.test(String(e.verdict))).length;
  const unmeasured = entries.filter(e => /UNMEASUR|NOT[_ ]?EVALUATED|UNKNOWN|NO VERDICT/i.test(String(e.verdict))).length;
  const pending = Math.max(0, entries.length - satisfied - failed - unmeasured);
  const openLaunch = () => {
    const el = document.getElementById('launch-evaluation') as HTMLDetailsElement | null;
    if (el) { el.open = true; el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  };
  const memoryAnalyses = (d.analyses ?? []).filter(item => item.question === 'DRAM_TIMING' || item.backend_id === 'RAMULATOR2_HBM3_V1');
  const memoryModelBackends = [...new Set(memoryAnalyses.map(item => item.backend_id).filter((value): value is string => Boolean(value)))];
  const hasMemory = memoryAnalyses.length > 0;
  const requirementTone = !entries.length ? 'neutral' : failed ? 'red' : satisfied === entries.length ? 'green' : 'amber';
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} actions={<>{onTabChange && hasMemory && <Button onClick={() => onTabChange('memory')}>Open Memory</Button>}<Button onClick={openLaunch}>Run new evaluation</Button></>} />
    <div className="stat-strip">
      <div className="stat"><span>Status</span><strong>{d.status}</strong><small>{d.qualification ? `Qualification: ${d.qualification}` : 'Qualification not declared'}</small></div>
      <div className="stat"><span>Completion cycles</span><strong>{num(metrics.completion_cycles)}</strong><small>{metrics.completion_cycles == null ? 'Not reported' : 'Run-level reported value'}</small></div>
      <div className="stat"><span>Sample window</span><strong>{num(metrics.sample_window_cycles, ' cyc')}</strong><small>{metrics.sample_window_cycles == null ? 'No measurement window' : 'Recorded window'}</small></div>
      <div className="stat"><span>Requirements met</span><strong>{entries.length ? `${satisfied}/${entries.length}` : '—'}</strong><small>{entries.length ? (satisfied === entries.length ? 'Every declared requirement satisfied' : [failed ? `${failed} failed` : '', unmeasured ? `${unmeasured} unmeasurable` : '', pending ? `${pending} not evaluated` : ''].filter(Boolean).join(' · ') || 'Review requirement verdicts') : 'None declared'}</small></div>
    </div>
    {onTabChange && hasMemory && null}
    {!d.evaluation && <Notice tone="amber"><strong>No evaluation block:</strong> status {d.status}, bundle {d.bundle_id ? 'recorded' : 'not recorded'}.</Notice>}
    <Section title="Requirement verdicts" actions={<Badge tone={requirementTone}>{entries.length ? `${satisfied}/${entries.length} satisfied` : 'none declared'}</Badge>}>
      {entries.length ? <div className={`table-scroll${cappedClass(entries.length)}`}><table className="requirement-table"><thead><tr><th>Requirement</th><th>Class / QoS</th><th>Verdict</th><th>Measured</th><th>Required</th><th>Metric authority</th></tr></thead><tbody>
        {entries.map((entry, i) => <Fragment key={`${entry.requirement_index ?? i}`}>
          <tr>
            <th className="mono">REQ-{entry.requirement_index ?? i + 1}</th>
            <td>{entry.traffic_class ?? '—'} / {entry.qos_class ?? '—'}</td>
            <td><Badge tone={/PASS|MET|SATISFIED/i.test(String(entry.verdict)) ? 'green' : /FAIL|VIOLAT/i.test(String(entry.verdict)) ? 'red' : 'amber'}>{entry.verdict ?? 'Not evaluated'}</Badge></td>
            <td className="numeric">{num(entry.measured)}</td>
            <td className="numeric">{entry.required === null || entry.required === undefined ? '—' : String(entry.required)}</td>
            <td><small>{entry.metric_authority ?? 'Not supplied'}</small></td>
          </tr>
          {entry.reason && <tr className="requirement-reason"><td colSpan={6}>
            <details className="inline-details"><summary>Why REQ-{entry.requirement_index ?? i + 1} received this verdict</summary><small>{entry.reason}</small></details>
          </td></tr>}
        </Fragment>)}
      </tbody></table></div> : <Empty title="No requirement verdicts">The run recorded no requirement verdicts.</Empty>}
    </Section>
    {run.gaps.length > 0 && <Section title="Partial reads"><ul>{run.gaps.map(g => <li key={g}>{g}</li>)}</ul></Section>}
    <Section title="Reported metrics" actions={<Badge>{metricKeys.length} values</Badge>}>
      {metricKeys.length ? <div className="table-scroll metric-table-scroll"><table aria-label="Reported metrics" className="metric-table"><thead><tr><th>Metric</th><th>Unit</th><th className="numeric">Value</th></tr></thead><tbody>
        {metricGroups.map(group => <Fragment key={group.label}>
          <tr className="metric-group"><th colSpan={3}>{group.label}</th></tr>
          {group.keys.map(key => <tr key={key}><th><span>{metricLabel(key)}</span><small className="mono">{key}</small></th><td>{metricUnit(key)}</td><td className="numeric">{num(metrics[key])}</td></tr>)}
        </Fragment>)}
      </tbody></table></div> : <Empty title="No metrics reported">This evaluation produced no metric block.</Empty>}
    </Section>
    <LaunchEvaluation project={project} collapsed />
    <Assumptions rows={[
      ['Run scope', 'Reads the selected run bundle. An unmeasured value is unavailable, not zero and not a pass.'],
      ['Metrics scope', 'Network evaluation only. DRAM timing is reported on the Memory tab.'],
      ['Analyses', 'Counts are analyses, not metrics. Values stay attributed to the model on their row and are never combined across backends.'],
      ['Latency definition', 'Backend-reported averages only; no percentile or distribution.'],
      ['Transaction completion', 'Not measured; packet averages are not transaction P95.'],
      ['Raw metrics', 'run.evaluation.metrics. An unmeasured value is absent, not zero.'],
      ['Analyses limitations', uniqueLimitations(d.analyses)],
      ['Backend', d.backend ?? 'Not declared'],
      ['Qualification', d.qualification ?? 'Not declared'],
      ['Qualification basis', d.qualification_basis ?? 'Not declared'],
      ['Revision', d.revision_id],
      ['Started / completed', `${d.started_at ?? '—'} → ${d.completed_at ?? '—'}`],
      ['Wall time', num(d.evaluation?.network_traffic_window?.wall_time_ns, ' ns')],
      ...(hasMemory ? [['Memory model', `${memoryModelBackends.length ? `${memoryModelBackends.join(', ')} reports DRAM timing.` : 'A DRAM_TIMING analysis is recorded.'} Separate models and clocks; cycle counts are not additive with the network.`] as [string, React.ReactNode]] : []),
      ...(d.evaluation?.fidelity_warning ? [['Fidelity warning', d.evaluation.fidelity_warning] as [string, React.ReactNode]] : []),
    ]} />
  </div></div>;
}

const shortRevision = (id?: string | null): string => revisionLabel(id);

const METRIC_ORDER = ['completion_cycles', 'sample_window_cycles', 'delivered_packets', 'flits_injected', 'flits_accepted', 'injected_trace_packets', 'loaded_trace_packets', 'packet_latency_avg', 'flit_latency_avg'];
const METRIC_GROUPS: { label: string; keys: string[] }[] = [
  { label: 'Run totals', keys: ['completion_cycles', 'sample_window_cycles', 'delivered_packets', 'flits_injected', 'flits_accepted'] },
  { label: 'Trace replay', keys: ['injected_trace_packets', 'loaded_trace_packets', 'pkt_count'] },
  { label: 'Latency', keys: ['packet_latency_avg', 'flit_latency_avg', 'honest_latency', 'p50', 'p95', 'p99'] },
];
const METRIC_LABELS: Record<string, string> = {
  completion_cycles: 'Completion cycles', sample_window_cycles: 'Sample window', delivered_packets: 'Delivered packets',
  flits_injected: 'Flits injected', flits_accepted: 'Flits accepted', injected_trace_packets: 'Injected trace packets',
  loaded_trace_packets: 'Loaded trace packets', packet_latency_avg: 'Packet latency average', flit_latency_avg: 'Flit latency average',
  honest_latency: 'Honest latency', p50: 'Packet P50', p95: 'Packet P95', p99: 'Packet P99', pkt_count: 'Packet count',
};
const METRIC_UNITS: Record<string, string> = {
  completion_cycles: 'cycles', sample_window_cycles: 'cycles', delivered_packets: 'packets', flits_injected: 'flits',
  flits_accepted: 'flits', injected_trace_packets: 'packets', loaded_trace_packets: 'packets', packet_latency_avg: 'cycles',
  flit_latency_avg: 'cycles', honest_latency: 'cycles', p50: 'cycles', p95: 'cycles', p99: 'cycles', pkt_count: 'packets',
};
const metricLabel = (key: string) => METRIC_LABELS[key] ?? key.replaceAll('_', ' ');
const metricUnit = (key: string) => METRIC_UNITS[key] ?? '—';

export type AnalysisTab = 'summary' | 'memory' | 'matrix' | 'topology' | 'trace' | 'comparison' | 'curves';

const ANALYSIS_TABS: { id: AnalysisTab; label: string }[] = [
  { id: 'summary', label: 'Summary' },
  { id: 'memory', label: 'Memory' },
  { id: 'matrix', label: 'Traffic matrix' },
  { id: 'topology', label: 'Topology' },
  { id: 'trace', label: 'Trace' },
  { id: 'comparison', label: 'Compare' },
  { id: 'curves', label: 'Curves & Pareto' },
];

const ANALYSIS_NEEDS: Record<AnalysisTab, string> = {
  summary: 'the selected run record: metrics, requirement verdicts and stated limitations',
  memory: 'a DRAM_TIMING analysis in the selected run',
  matrix: 'the selected run\u2019s traffic artifact and per-pair counters',
  topology: 'the selected run\u2019s compile result, declared topology and sealed series',
  trace: 'the selected run\u2019s trace artifact or observed watch capture',
  comparison: 'two or more runs over comparable revisions',
  curves: 'the measured workload reference; project study analysis lives in Explore → Revision study',
};

/** One analysis surface. The readings are sections of this page, not
 *  separate destinations: switching tabs must not lose the selected run.
 *  The tab lives above LiveGate so a run-loading transition cannot reset it. */
export function LiveAnalysisWorkspace({ project, run, tab, onTabChange }: {
  project: LoadedProject; run: LoadedRun; tab: AnalysisTab; onTabChange: (tab: AnalysisTab) => void;
}) {
  const { loadRun } = useProject();
  const activeRevisionId = project.detail.active_revision_id;
  const historical = run.detail.revision_id !== activeRevisionId;
  const labels = runVersionLabels(project.detail.runs ?? []);
  const activeRuns = [...(project.detail.runs ?? [])]
    .filter(entry => entry.revision_id === activeRevisionId)
    .sort((a, b) => String(a.completed_at ?? '').localeCompare(String(b.completed_at ?? '')));
  const activeRun = activeRuns[activeRuns.length - 1] ?? null;
  return <div className="analysis-workspace">
    {historical && <Notice tone="amber">
      <strong>Viewing {labels.get(run.detail.run_id) ?? 'a historical run'}.</strong>{' '}
      The active revision is {revisionLabel(activeRevisionId)}.
      {activeRun
        ? <> <Button onClick={() => loadRun(activeRun.run_id)}>Return to active run</Button></>
        : <> <PageLink page="analysis/summary">Evaluate active revision</PageLink></>}
    </Notice>}
    <div className="analysis-tabs" role="tablist" aria-label="Analysis sections">
      {ANALYSIS_TABS.map(item => <button key={item.id} role="tab" aria-selected={tab === item.id}
        className={tab === item.id ? 'active' : ''} onClick={() => onTabChange(item.id)}>{item.label}</button>)}
    </div>
    {tab === 'memory' ? <LiveMemory project={project} run={run} />
      : tab === 'matrix' ? <LiveMatrix project={project} run={run} />
      : tab === 'topology' ? <LiveAnalysisTopology project={project} run={run} />
      : tab === 'trace' ? <LiveTrace project={project} run={run} />
      : tab === 'comparison' ? <LiveComparison project={project} run={run} />
      : tab === 'curves' ? <div className="view-layout"><div className="view-main"><AnalysisCurves project={project} /></div></div>
      : <LiveAnalysisSummary project={project} run={run} onTabChange={onTabChange} />}
  </div>;
}

/** Limitations repeat verbatim across the analyses that share a backend;
 *  joining the raw list prints the same paragraph several times. */
function uniqueLimitations(analyses: LoadedRun['detail']['analyses']): string {
  const text = (analyses ?? []).flatMap(a => a.limitations ?? []);
  return [...new Set(text)].join('; ') || 'None declared';
}

type RunAnalysis = NonNullable<RunDetail['analyses']>[number];

function analysisNumber(analysis: RunAnalysis, key: string): number | null {
  const summary = analysis.native_summary ?? {};
  const raw = summary[key];
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  const metric = (analysis.normalized_metrics ?? []).find(item => item.key === key);
  return typeof metric?.value === 'number' && Number.isFinite(metric.value) ? metric.value : null;
}

const memoryBackends = (analyses: RunAnalysis[] | undefined) => (analyses ?? []).find(item => item.question === 'DRAM_TIMING' || item.backend_id === 'RAMULATOR2_HBM3_V1');

export function LiveMemory({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const memory = memoryBackends(run.detail.analyses);
  const tone = memory && /PASS|QUALIFIED/i.test(String(memory.qualification ?? memory.status)) ? 'green' : 'amber';
  if (!memory) return <div className="view-main analysis-page">
    <RunBar project={project} run={run} />
    <Empty title="No DRAM_TIMING analysis in this run" action={<>
      <PageLink page="analysis/summary" primary>Inspect this run's analyses</PageLink>
      <PageLink page="workloads/lowering">Inspect workload intent</PageLink>
    </>}>
      Ramulator did not run for this evaluation, so the run records no <code>RAMULATOR2_HBM3_V1</code> result.
      No DRAM timing is estimated from the network measurements.
    </Empty>
    <Assumptions rows={[
      ['Evidence', 'The Memory tab is populated only from a recorded Ramulator result; no DRAM result is estimated from the network run.'],
      ['Scope', 'Ramulator is invoked only when the run plan includes memory timing. Memory-access bytes remain workload input.'],
    ]} />
  </div>;
  const completionCycles = analysisNumber(memory, 'completion_cycles');
  const averageReadLatency = analysisNumber(memory, 'average_read_latency_cycles');
  const rowHits = analysisNumber(memory, 'row_hits') ?? 0;
  const rowMisses = analysisNumber(memory, 'row_misses') ?? 0;
  const rowConflicts = analysisNumber(memory, 'row_conflicts') ?? 0;
  const readQueue = analysisNumber(memory, 'read_queue_len_avg');
  const writeQueue = analysisNumber(memory, 'write_queue_len_avg');
  const readBytes = analysisNumber(memory, 'completed_read_bytes');
  const writeBytes = analysisNumber(memory, 'completed_write_bytes');
  const generated = analysisNumber(memory, 'generated_requests');
  const accepted = analysisNumber(memory, 'accepted_requests');
  const completed = analysisNumber(memory, 'completed_requests');
  const outstanding = analysisNumber(memory, 'outstanding_requests');
  const totalBytes = (readBytes ?? 0) + (writeBytes ?? 0);
  const outcomes = rowHits + rowConflicts + rowMisses;
  const denominator = outcomes || generated || 0;
  const hitShare = denominator > 0 ? 100 * rowHits / denominator : null;
  const conflictShare = denominator > 0 ? 100 * rowConflicts / denominator : null;
  const missShare = denominator > 0 ? 100 * rowMisses / denominator : null;
  const exceptions = rowConflicts + rowMisses;
  const exceptionShare = denominator > 0 ? 100 * exceptions / denominator : null;
  const exceptionOneIn = exceptions > 0 && denominator > 0 ? denominator / exceptions : null;
  const conflictPer10k = denominator > 0 ? 10_000 * rowConflicts / denominator : null;
  const missOneIn = rowMisses > 0 && denominator > 0 ? denominator / rowMisses : null;
  const percent = (value: number | null, digits = 2) => value === null ? '—' : `${value.toFixed(digits)} %`;
  const readShare = totalBytes > 0 ? 100 * (readBytes ?? 0) / totalBytes : null;
  const writeShare = totalBytes > 0 ? 100 * (writeBytes ?? 0) / totalBytes : null;
  const avgBytes = completed && completed > 0 ? totalBytes / completed : null;
  const completionShare = generated && generated > 0 && completed !== null ? 100 * completed / generated : null;
  const queuePeak = Math.max(1, readQueue ?? 0, writeQueue ?? 0);
  const networkCycles = run.detail.evaluation?.metrics?.completion_cycles;
  const profile = (memory.limitations ?? []).find(line => /HBM3|profile/i.test(line)) ?? 'No memory profile stated in this analysis.';
  const profileSummary = /single HBM3 channel \([^)]*\)/i.exec(profile)?.[0] ?? profile;
  return <div className="view-layout"><div className="view-main analysis-page">
    <RunBar project={project} run={run} actions={<Badge tone={tone}>{memory.qualification ?? memory.status ?? 'Recorded'}</Badge>} />
    <div className="section-heading memory-heading"><h2>HBM3 memory timing</h2><Badge tone="blue">{memory.question ?? 'DRAM_TIMING'}</Badge></div>
    <div className="router-kpis memory-kpis">
      <div><span>Memory completion</span><strong>{num(completionCycles)}</strong><small>Ramulator cycles</small></div>
      <div><span>Avg read latency</span><strong>{num(averageReadLatency, ' cyc', 2)}</strong><small>from Ramulator request service</small></div>
      <div><span>Row hit rate</span><strong>{hitShare === null ? '—' : `${hitShare.toFixed(2)} %`}</strong><small>{num(rowConflicts)} conflicts · {num(rowMisses)} misses</small></div>
      <div><span>Completed requests</span><strong>{num(completed)}</strong><small>{completionShare === null ? '—' : `${completionShare.toFixed(1)} %`} · {num(outstanding)} outstanding</small></div>
      <div><span>Completed traffic</span><strong>{bytesLabel(totalBytes)}</strong><small>{avgBytes === null ? '—' : `${avgBytes.toFixed(1)} B / request`}</small></div>
      <div><span>Read queue</span><strong>{num(readQueue, '', 2)}</strong><small>write queue {num(writeQueue, '', 2)}</small></div>
    </div>
    <Section title="HBM request outcomes" actions={<Badge>{num(denominator)} requests</Badge>}>
      <div className="memory-outcomes">
        <div className="memory-outcome-card memory-outcome-hit">
          <span className="memory-outcome-label">Row hits</span>
          <div className="memory-outcome-figure"><strong>{hitShare === null ? '—' : hitShare.toFixed(2)}</strong>{hitShare !== null && <span>%</span>}</div>
          <span className="memory-outcome-count">{num(rowHits)} of {num(denominator)} requests</span>
          <span className="memory-outcome-note">Requested row already open</span>
        </div>
        <div className="memory-outcome-card memory-outcome-exceptions">
          <div className="memory-outcome-head">
            <span className="memory-outcome-label">Exceptions</span>
            <strong>{num(exceptions)}</strong>
            <span className="memory-outcome-share">{percent(exceptionShare)} · {exceptionOneIn === null ? '—' : `1 in ${num(exceptionOneIn, '', 0)} requests`}</span>
          </div>
          <div className="memory-outcome-ledger">
            <div className="memory-outcome-row">
              <i className="memory-conflict" />
              <span>Row conflicts</span>
              <strong>{num(rowConflicts)}</strong>
              <small>{percent(conflictShare, 3)} of requests · {num(conflictPer10k, '', 1)} per 10,000</small>
            </div>
            <div className="memory-outcome-row">
              <i className="memory-miss" />
              <span>Row misses</span>
              <strong>{num(rowMisses)}</strong>
              <small>{missShare !== null && missShare > 0 && missShare < 0.001 ? '<0.001 %' : percent(missShare, 5)} of requests · {missOneIn === null ? '—' : `1 in ${num(missOneIn, '', 0)}`}</small>
            </div>
          </div>
        </div>
      </div>
    </Section>
    <Section title="Memory traffic and queue pressure">
      <div className="memory-grid">
        <div className="memory-panel">
          <h3>Completed bytes</h3>
          <div className="memory-traffic-ledger">
            <div className="memory-traffic-row">
              <i className="memory-read" />
              <span>Read</span>
              <strong>{bytesLabel(readBytes)}</strong>
              <small>{readShare === null ? '—' : `${readShare.toFixed(3)} %`} of completed traffic</small>
            </div>
            <div className="memory-traffic-row">
              <i className="memory-write" />
              <span>Write</span>
              <strong>{bytesLabel(writeBytes)}</strong>
              <small>{writeShare === null ? '—' : `${writeShare.toFixed(3)} %`} of completed traffic</small>
            </div>
          </div>
        </div>
        <div className="memory-panel">
          <h3>Average queue occupancy</h3>
          <div className="memory-queue-row"><span>Read queue</span><span className="metric-bar"><span style={{ width: `${100 * (readQueue ?? 0) / queuePeak}%` }} /></span><strong>{num(readQueue, '', 2)}</strong></div>
          <div className="memory-queue-row"><span>Write queue</span><span className="metric-bar"><span style={{ width: `${100 * (writeQueue ?? 0) / queuePeak}%` }} /></span><strong>{num(writeQueue, '', 2)}</strong></div>
        </div>
      </div>
    </Section>
    <Section title="Network vs memory scope">
      <div className="table-scroll"><table><thead><tr><th>Analysis</th><th>Backend</th><th>Completion cycles</th><th>Scope</th></tr></thead><tbody>
        <tr><th>Network completion</th><td className="mono">{run.detail.backend ?? 'BOOKSIM_STANDALONE'}</td><td className="numeric">{num(networkCycles)}</td><td>Packet network simulation</td></tr>
        <tr><th>DRAM timing</th><td className="mono">{memory.backend_id}</td><td className="numeric">{num(completionCycles)}</td><td>HBM3 memory cycle simulation</td></tr>
      </tbody></table></div>
    </Section>
    <Section title="Backend scope" actions={<Badge tone={tone}>{memory.question ?? 'DRAM_TIMING'}</Badge>}>
      <Properties rows={[
        ['Backend', <span className="mono">{memory.backend_id ?? 'RAMULATOR2_HBM3_V1'}</span>],
        ['Model fidelity', memory.model_fidelity ?? '—'],
        ['Qualification', memory.qualification ?? '—'],
        ['Status', memory.status ?? '—'],
        ['Requests generated / accepted / completed', `${num(generated)} / ${num(accepted)} / ${num(completed)}`],
        ['Outstanding requests', num(outstanding)],
        ['Profile', profileSummary],
        ['Limitations', memory.limitations?.length ? <ul>{memory.limitations.map((line, index) => <li key={index}>{line}</li>)}</ul> : 'None declared'],
      ]} />
    </Section>
    <Assumptions rows={[
      ['Scope', 'HBM3 memory timing from Ramulator. This page reports the memory analysis, not an end-to-end runtime.'],
      ['Not additive', 'Ramulator and BookSim model separate resources with different clocks and scopes; their cycle counts are never added.'],
      ['Request stream', 'Simulated; request generation is assumed, not measured.'],
      ['Queue occupancy', 'Average outstanding requests in Ramulator queues. Queue length is not latency and is not a utilization percentage.'],
      ['Row outcomes', 'A conflict means a different row is already open in the bank; a miss means no row is open. Neither is a failed request or packet loss.'],
      ['Analysis question', memory.question ?? 'DRAM_TIMING'],
      ['Native evidence', memory.status === 'EVALUATED' ? 'Recorded by this run bundle' : 'Not evaluated'],
      ['NoC / memory composition', 'Not modeled; cycle counts are not additive.'],
      ['Calibration', 'Not established.'],
      ['Per-request histogram', 'Not supplied by this aggregate view.'],
    ]}>
      <PageLink page="verify/evidence">Inspect evidence bundle</PageLink>
    </Assumptions>
  </div><Inspector title="Memory claim scope">
    <Properties rows={[
      ['Run', <span className="mono">{short(run.detail.run_id, 24)}</span>],
      ['HBM profile', profileSummary],
      ['Request stream', 'Assumed by the memory lowerer; see stated limitations'],
      ['NoC coupling', 'Not modeled'],
      ['Calibration', 'Not established'],
      ['Per-request histogram', 'Not supplied by this aggregate view'],
    ]} />
    <PageLink page="verify/evidence">Inspect evidence bundle</PageLink>
    <PageLink page="verify/checks">Trust checks</PageLink>
  </Inspector></div>;
}

function pairMatches(entry: { src: number; dst: number }, value: string): boolean {
  const normalized = value.trim().replace(/\s+/g, '');
  if (!normalized) return true;
  const exact = normalized.match(/^(\d+)(?:>|->|→|:)(\d+)$/);
  if (exact) return entry.src === Number(exact[1]) && entry.dst === Number(exact[2]);
  if (/^\d+$/.test(normalized)) return entry.src === Number(normalized) || entry.dst === Number(normalized);
  return `${entry.src} ${entry.dst}`.includes(normalized);
}

function MatrixHeatmap({ grid, basis, selected, onSelect }: {
  grid: number[][]; basis: 'packets' | 'flits';
  selected?: { src: number; dst: number };
  onSelect: (pair: string) => void;
}) {
  const n = grid.length;
  const maxCell = Math.max(1, ...grid.flat());
  const cell = n <= 16 ? Math.max(8, Math.min(30, Math.floor(620 / Math.max(1, n)))) : Math.max(6, Math.min(14, Math.floor(760 / Math.max(1, n))));
  const step = n <= 16 ? 1 : Math.max(2, Math.ceil(n / 12));
  const left = 34;
  const top = 38;
  const right = 58;
  const bottom = 54;
  const plot = n * cell;
  const width = left + plot + right + 8;
  const height = top + plot + bottom;
  const rowTotals = grid.map(row => row.reduce((sum, value) => sum + value, 0));
  const columnTotals = grid[0]?.map((_, destination) => grid.reduce((sum, row) => sum + (row[destination] ?? 0), 0)) ?? [];
  const maxRow = Math.max(1, ...rowTotals);
  const maxColumn = Math.max(1, ...columnTotals);
  return <div className="matrix-heatmap-scroll">
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: `${width}px`, maxWidth: '100%' }} role="group" aria-label={`${basis === 'packets' ? 'Packet' : 'Flit'} count heatmap by source and destination, with source and destination totals`}>
      <title>{`${basis === 'packets' ? 'Packet' : 'Flit'} count by source → destination; max cell ${maxCell}`}</title>
      {grid.map((_, index) => (index % step === 0 || index === n - 1) ? <g key={`labels-${index}`}>
        <text className="matrix-heat-axis" x={left + index * cell + cell / 2} y={top - 6} textAnchor="end" transform={`rotate(-55 ${left + index * cell + cell / 2} ${top - 6})`}>{index}</text>
        <text className="matrix-heat-axis" x={left - 5} y={top + index * cell + cell / 2 + 3} textAnchor="end">{index}</text>
      </g> : null)}
      {grid.map((row, source) => row.map((value, destination) => {
        const selectedCell = selected?.src === source && selected?.dst === destination;
        return <rect key={`${source}:${destination}`} className={`matrix-heat-cell${selectedCell ? ' selected' : ''}`} {...contextTarget('pair', `${source}:${destination}`, `Endpoint pair ${source} → ${destination}`, `${value.toLocaleString()} ${basis} · measured trace pair`)} x={left + destination * cell} y={top + source * cell} width={Math.max(1, cell - 1)} height={Math.max(1, cell - 1)} fill={value === 0 ? '#f1f5f8' : `rgba(15,108,158,${0.1 + 0.78 * value / maxCell})`} onClick={() => onSelect(`${source}:${destination}`)}>
          <title>{`${source} → ${destination}: ${value.toLocaleString()} ${basis}`}</title>
        </rect>;
      }))}
      <rect x={left} y={top} width={plot} height={plot} className="matrix-heat-frame" />
      {/* Matrix marginals: the row and column totals make the sparse pair pattern legible. */}
      {rowTotals.map((value, source) => <rect key={`row-total-${source}`} className="matrix-margin-bar" x={left + plot + 8} y={top + source * cell} width={Math.max(0, (value / maxRow) * (right - 16))} height={Math.max(1, cell - 2)}>
        <title>{`Source ${source} total: ${value.toLocaleString()} ${basis}`}</title>
      </rect>)}
      {columnTotals.map((value, destination) => <rect key={`column-total-${destination}`} className="matrix-margin-bar" x={left + destination * cell} y={top + plot + 8} width={Math.max(1, cell - 2)} height={Math.max(0, (value / maxColumn) * (bottom - 20))}>
        <title>{`Destination ${destination} total: ${value.toLocaleString()} ${basis}`}</title>
      </rect>)}
      <text className="matrix-heat-axis" x={left + plot + 8} y={top - 6}>source Σ</text>
      <text className="matrix-heat-axis" x={left} y={height - 8}>destination Σ</text>
    </svg>
  </div>;
}

export function LiveMatrix({ project, run, variant }: { project: LoadedProject; run: LoadedRun; variant?: 'missing' }) {
  const [basis, setBasis] = useState<'packets' | 'flits'>('packets');
  const [trafficClass, setTrafficClass] = useState<string>('all');
  const [pair, setPair] = useState<string>('');
  const [query, setQuery] = useState('');
  const matrix = run.matrix;
  if (!matrix) return <div className="view-main"><RunBar project={project} run={run} /><Notice tone="amber"><strong>No traffic matrix.</strong> {run.gaps.find(g => g.startsWith('traffic matrix')) ?? ''}</Notice><Assumptions rows={[['Scope', 'The run bundled no traffic matrix; pair counts are unavailable rather than zero.']]} /></div>;
  const classMatrices = matrix.class_matrices ?? {};
  const classIds = Object.keys(classMatrices).sort((a, b) => Number(a) - Number(b));
  const classData = trafficClass === 'all' ? undefined : classMatrices[trafficClass];
  const packetGrid = classData?.matrix ?? matrix.matrix ?? [];
  const flitGrid = classData?.flit_matrix ?? matrix.flit_matrix ?? [];
  const grid = (basis === 'packets' ? packetGrid : flitGrid) ?? [];
  const max = Math.max(1, ...grid.flat());
  const pairs = classData?.pairs ?? (trafficClass === 'all' ? matrix.pairs ?? [] : []);
  const selected = pairs.find(p => `${p.src}:${p.dst}` === pair) ?? pairs[0];
  const totalPackets = classData?.packets ?? matrix.packets ?? pairs.reduce((sum, p) => sum + p.packets, 0);
  const totalFlits = classData?.flits ?? matrix.flits ?? pairs.reduce((sum, p) => sum + p.flits, 0);
  const allPackets = matrix.packets ?? Object.values(matrix.classes ?? {}).reduce((sum, value) => sum + value, 0);
  const classLabel = trafficClass === 'all' ? 'all classes' : `class ${trafficClass}`;
  const selectClass = (next: string) => { setTrafficClass(next); setPair(''); setQuery(''); };
  const patterns = (() => {
    const groups = new Map<string, { packets: number; flits: number; count: number; totalFlits: number; example: typeof pairs[number] }>();
    for (const entry of pairs) {
      const key = `${entry.packets}:${entry.flits}`;
      const group = groups.get(key) ?? { packets: entry.packets, flits: entry.flits, count: 0, totalFlits: 0, example: entry };
      group.count += 1;
      group.totalFlits += entry.flits;
      groups.set(key, group);
    }
    return [...groups.values()].sort((a, b) => b.totalFlits - a.totalFlits);
  })();

  const filtered = pairs
    .filter(entry => pairMatches(entry, query))
    .sort((a, b) => basis === 'flits'
      ? b.flits - a.flits || b.packets - a.packets
      : b.packets - a.packets || b.flits - a.flits);
  const shareOf = (value: number) => totalPackets > 0 ? `${(100 * value / totalPackets).toFixed(2)} %` : '—';
  const topFlows = [...pairs].sort((a, b) => basis === 'flits' ? b.flits - a.flits : b.packets - a.packets).slice(0, 5);
  const topFlowPeak = Math.max(1, ...topFlows.map(entry => basis === 'flits' ? entry.flits : entry.packets));
  const CLASS_COLORS = ['#0f6c9e', '#8a6d3b', '#246847', '#6b4f9e', '#a32928'];
  const classMix = Object.entries(matrix.classes ?? {}).map(([id, value], index) => ({ id, value, color: CLASS_COLORS[index % CLASS_COLORS.length] }));
  const activePairs = pairs.filter(entry => entry.src !== entry.dst && (entry.packets > 0 || entry.flits > 0)).length || (trafficClass === 'all' ? matrix.distinct_pairs ?? 0 : 0);
  const possiblePairs = Math.max(1, (matrix.nodes ?? 0) * Math.max(0, (matrix.nodes ?? 0) - 1));
  const pairDensity = possiblePairs > 0 ? 100 * activePairs / possiblePairs : 0;
  const basisTotal = basis === 'packets' ? totalPackets : totalFlits;
  const topPair = pairs.reduce<typeof pairs[number] | null>((best, entry) => {
    if (!best) return entry;
    return (basis === 'flits' ? entry.flits : entry.packets) > (basis === 'flits' ? best.flits : best.packets) ? entry : best;
  }, null);
  const topPairShare = topPair && basisTotal > 0 ? 100 * (basis === 'flits' ? topPair.flits : topPair.packets) / basisTotal : null;
  const pairValues = pairs.map(entry => basis === 'flits' ? entry.flits : entry.packets).sort((a, b) => a - b);
  const pairMiddle = pairValues.length >> 1;
  const pairMedian = pairValues.length === 0 ? 0 : pairValues.length % 2 ? pairValues[pairMiddle] : (pairValues[pairMiddle - 1] + pairValues[pairMiddle]) / 2;
  const pairMin = pairValues[0] ?? 0;
  const pairMax = pairValues[pairValues.length - 1] ?? 0;
  const topPattern = patterns[0];
  const topFiveShare = basisTotal > 0 ? 100 * topFlows.reduce((sum, entry) => sum + (basis === 'flits' ? entry.flits : entry.packets), 0) / basisTotal : 0;
  const formatPairValue = (value: number) => Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1);
  return <div className="view-main analysis-page">
    <RunBar project={project} run={run} />
    <div className="toolbar matrix-toolbar">
      <div className="actions">
        <select aria-label="Matrix basis" value={basis} onChange={e => setBasis(e.target.value as typeof basis)}><option value="packets">Packets</option><option value="flits">Flits</option></select>
        {classIds.length > 0 && <div className="segmented matrix-class-filter" role="group" aria-label="Traffic class matrix">
          <button type="button" className={trafficClass === 'all' ? 'active' : ''} aria-pressed={trafficClass === 'all'} onClick={() => selectClass('all')}>All classes</button>
          {classIds.map(id => <button type="button" key={id} className={trafficClass === id ? 'active' : ''} aria-pressed={trafficClass === id} onClick={() => selectClass(id)}>class {id}</button>)}
        </div>}
      </div>
      <label className="field pair-search"><span>Find a pair</span>
        <input aria-label="Filter endpoint pairs" value={query} placeholder="source, destination, or 0→8" onChange={event => {
          const value = event.target.value;
          setQuery(value);
          const first = pairs.filter(entry => pairMatches(entry, value)).sort((a, b) => b.flits - a.flits)[0];
          setPair(first ? `${first.src}:${first.dst}` : '');
        }} />
      </label>
    </div>
    <Section title="Traffic profile" actions={<div className="actions"><Badge>{pairs.length} pairs</Badge>{trafficClass !== 'all' && <Badge tone="amber">{classLabel}</Badge>}</div>}>
      <p className="meta-line">Source trace · <span className="mono">{matrix.source?.trace ?? 'Not declared'}</span></p>
      <div className="stat-strip matrix-kpis">
        <div className="stat"><span>{trafficClass === 'all' ? 'Trace packets' : `Class ${trafficClass} packets`}</span><strong>{num(totalPackets)}</strong><small>measured pair counts</small></div>
        <div className="stat"><span>{trafficClass === 'all' ? 'Trace flits' : `Class ${trafficClass} flits`}</span><strong>{num(totalFlits)}</strong><small>same measurement window</small></div>
        <div className="stat"><span>Active pairs</span><strong>{num(activePairs)}</strong><small>of {num(possiblePairs)} off-diagonal pairs · {pairDensity.toFixed(1)} %</small></div>
        <div className="stat"><span>Top pair share</span><strong>{topPairShare === null ? '—' : `${topPairShare.toFixed(2)} %`}</strong><small>{topPair ? `${topPair.src} → ${topPair.dst} · ${num(basis === 'flits' ? topPair.flits : topPair.packets)} ${basis}` : 'No pair traffic'}</small></div>
      </div>
      <div className="traffic-profile">
        <div className="trace-profile-card">
          <h3>Pair distribution <small>{activePairs} active pairs</small></h3>
          <div className="balance-grid matrix-balance">
            <div><span>Median pair</span><strong>{formatPairValue(pairMedian)}</strong><small>{formatPairValue(pairMin)}–{formatPairValue(pairMax)} {basis}</small></div>
            <div><span>Pattern groups</span><strong>{patterns.length}</strong><small>{topPattern ? `${topPattern.count} pairs in largest` : 'No pair pattern'}</small></div>
            <div><span>Top 5 share</span><strong>{topFiveShare.toFixed(1)} %</strong><small>{basis} in top 5 pairs</small></div>
          </div>
          {patterns.length === 1
            ? <p className="trace-insight"><strong>Balanced.</strong> All {activePairs} active pairs carry {num(topPattern?.packets ?? 0)} packets · {num(topPattern?.flits ?? 0)} flits.</p>
            : patterns.length <= 4
              ? <>
                <div className="pattern-bars">{patterns.map(group => <div className="pattern-row" key={`${group.packets}:${group.flits}`}>
                  <span className="mono">{num(group.packets)} pkt · {num(group.flits)} flits</span>
                  <span className="flow-track"><i style={{ width: `${100 * group.totalFlits / Math.max(1, totalFlits)}%` }} /></span>
                  <span className="numeric">{group.count} pairs</span>
                  <small>{totalFlits > 0 ? `${(100 * group.totalFlits / totalFlits).toFixed(1)} % flits` : '—'}</small>
                </div>)}</div>
              </>
              : <>
                <div className="flow-bars">{topFlows.map(entry => <button type="button" className="flow-row" key={`${entry.src}:${entry.dst}`} {...contextTarget('pair', `${entry.src}:${entry.dst}`, `Endpoint pair ${entry.src} → ${entry.dst}`, `${entry.packets} packets · ${entry.flits} flits`)} onClick={() => setPair(`${entry.src}:${entry.dst}`)} title={`${entry.packets} packets · ${entry.flits} flits`}>
                  <span className="mono flow-name">{entry.src} → {entry.dst}</span>
                  <span className="flow-track"><i style={{ width: `${100 * (basis === 'flits' ? entry.flits : entry.packets) / topFlowPeak}%` }} /></span>
                  <span className="numeric">{num(basis === 'flits' ? entry.flits : entry.packets)}</span>
                </button>)}</div>
                <p className="trace-insight"><strong>Top 5 pairs</strong> carry {topFiveShare.toFixed(1)} % of {basis} across {activePairs} active pairs.</p>
              </>}
        </div>
        <div className="trace-profile-card">
          <h3>Packets by class</h3>
          <div className="class-mix-bar" role="img" aria-label="Trace packets by traffic class">
            {classMix.map(item => <span key={item.id} style={{ width: `${100 * item.value / Math.max(1, allPackets)}%`, background: item.color }} title={`class ${item.id}: ${item.value} packets`} />)}
          </div>
          <div className="class-mix-legend">{classMix.length ? classMix.map(item => {
            const canFilter = classIds.includes(item.id);
            return <button type="button" key={item.id} className={`class-mix-entry${trafficClass === item.id ? ' active' : ''}`} disabled={!canFilter} aria-pressed={trafficClass === item.id} onClick={() => selectClass(item.id)} title={canFilter ? `Show only class ${item.id}` : 'Per-class matrix not supplied'}>
              <i style={{ background: item.color }} />class {item.id} <strong>{num(item.value)}</strong> pkt
            </button>;
          }) : <span className="muted">No class split reported.</span>}
          {trafficClass !== 'all' && <button type="button" className="class-mix-entry" onClick={() => selectClass('all')}>All classes</button>}</div>
        </div>
      </div>
    </Section>
    <Section title={`${basis === 'packets' ? 'Packet' : 'Flit'} count by source → destination${trafficClass === 'all' ? '' : ` · class ${trafficClass}`}`} actions={<div className="actions">
      <Badge>{matrix.availability}</Badge>
      <Badge>{matrix.nodes} nodes</Badge>
      <Badge>{num(classData?.distinct_pairs ?? pairs.length)} distinct pairs</Badge>
      <Badge>max {num(max)}</Badge>
    </div>}>
      {grid.length ? <>
        <MatrixHeatmap grid={grid} basis={basis} selected={selected} onSelect={src => setPair(src)} />
        <div className="legend"><span>Cell = {basis === 'packets' ? 'packets' : 'flits'}</span><span>Right/bottom bars = source/destination totals</span><span>Click a cell to select a pair</span></div>
      </> : <Empty title="The matrix document holds no grid">The run reports availability {matrix.availability} without a node grid.</Empty>}
      {selected && <div className="pair-focus">
        <div>
          <span className="meta-line">Selected pair</span>
          <strong className="mono">{selected.src} → {selected.dst}</strong>
          <small>{num(selected.packets)} packets · {num(selected.flits)} flits · share of trace packets {shareOf(selected.packets)}</small>
        </div>
        <div className="actions">
          {pair && <Button onClick={() => setPair('')}>Clear</Button>}
        </div>
      </div>}
      {pairs.length > 0 && <details className="plot-data" open={!!query}><summary>Pair table · {filtered.length === pairs.length ? `all ${pairs.length} reported pairs` : `${filtered.length} of ${pairs.length} pairs`}</summary>
        {query && <p className="meta-line">Filtered by “{query}”. Clear the search to restore every reported pair. <Button onClick={() => { setQuery(''); setPair(''); }}>Clear search</Button></p>}
        {filtered.length ? <div className="table-scroll capped"><table>
          <thead><tr><th>Source</th><th>Destination</th><th>Packets</th><th>Flits</th><th>Trace share</th></tr></thead>
          <tbody>{filtered.map(entry => <tr key={`${entry.src}:${entry.dst}`} className={selected && entry.src === selected.src && entry.dst === selected.dst ? 'selected' : ''} {...contextTarget('pair', `${entry.src}:${entry.dst}`, `Endpoint pair ${entry.src} → ${entry.dst}`, `${entry.packets.toLocaleString()} packets · ${entry.flits.toLocaleString()} flits`)} onClick={() => setPair(`${entry.src}:${entry.dst}`)}>
            <td className="mono"><button type="button" className="text-button" onClick={() => setPair(`${entry.src}:${entry.dst}`)} aria-label={`Select pair ${entry.src} to ${entry.dst}`}>{entry.src}</button></td><td className="mono">{entry.dst}</td><td className="numeric">{num(entry.packets)}</td><td className="numeric">{num(entry.flits)}</td><td className="numeric">{shareOf(entry.packets)}</td>
          </tr>)}</tbody>
        </table></div> : <p className="meta-line">No pair matches. Try a source or destination number, or a pair such as <code>0→8</code>.</p>}
      </details>}
    </Section>
    {patterns.length > 1 && <Section title="Flow patterns" actions={<Badge>{patterns.length} patterns</Badge>}>
      <div className="table-scroll"><table>
        <thead><tr><th>Per-pair pattern</th><th>Pairs</th><th>Total packets</th><th>Total flits</th><th>Share of flits</th></tr></thead>
        <tbody>{patterns.map(group => <tr key={`${group.packets}:${group.flits}`}>
          <th>{num(group.packets)} pkt · {num(group.flits)} flits</th>
          <td className="numeric">{group.count}</td>
          <td className="numeric">{num(group.packets * group.count)}</td>
          <td className="numeric">{num(group.totalFlits)}</td>
          <td className="numeric">{totalFlits > 0 ? `${(100 * group.totalFlits / totalFlits).toFixed(1)} %` : '—'}</td>
        </tr>)}</tbody>
      </table></div>
    </Section>}
    <Assumptions rows={[
      ['Scope', 'Zero cells are recorded zeros, not missing data.'],
      ['Not supplied', 'Per-pair latency and observed route. The selected pair shows packet/flit counts only.'],
      ['Per-class matrices', classIds.length ? `${classIds.length} classes reported. Aggregate class counts are never split into inferred pairs.` : 'Not supplied. Aggregate class counts are never split into inferred pairs.'],
      ['Grouping', 'Pairs with identical reported counters are grouped under Flow patterns when more than one pattern exists; the pair table always keeps the full reported list.'],
      ['Availability', matrix.availability],
      ['Source trace', <span className="mono">{matrix.source?.trace ?? 'Not declared'}</span>],
      ['Declared packets', num(matrix.source?.declared_packets)],
      ['Trace packets', num(matrix.packets)],
      ['Trace flits', num(matrix.flits)],
      ['Class filter', classLabel],
      ['Traffic classes', matrix.classes ? Object.entries(matrix.classes).map(([key, value]) => `class ${key} · ${value.toLocaleString()} packets`).join(' · ') : 'No class split reported'],
      ...(variant === 'missing' ? [['Data scenario', 'Fixture scenario with real data.'] as [string, React.ReactNode]] : []),
    ]}>
      <PageLink page="analysis/metrics">Inspect reported metrics</PageLink>
    </Assumptions>
  </div>;
}

export function LiveAnalysisTopology({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const topology = useRunTopology(project, run);
  // The four measured panels all read the same sampled-series artifact. Probe
  // it once: when the deployment did not sample, one explanation replaces a
  // stack of identical "Not recorded" sections.
  const load = useSimLoad(run.detail.run_id);
  const sampled = load.phase === 'ready' && (load.data?.channels?.length ?? 0) > 0;
  // A GEC-hybrid route is a ranked candidate union, not one deterministic
  // path. The shared-resource projection cannot place a flit on one wire, so
  // say that once instead of failing twice with internal jargon.
  const routeProjectable = topology?.family !== 'gec_hybrid';
  const [channelQuery, setChannelQuery] = useState('');
  const [loadRange, setLoadRange] = useState<UtilizationRange | null>(null);
  // A bin belongs to the sampled distribution of one run; carrying it to a
  // different run would filter that run by a range the user never chose.
  useEffect(() => { setLoadRange(null); }, [run.detail.run_id]);
  const pickLoadRange = (range: UtilizationRange | null) => {
    setLoadRange(range);
    if (range) requestAnimationFrame(() => document.getElementById('measured-channel-activity')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };
  const [channelsExpanded, setChannelsExpanded] = useState(false);
  const channels = topology?.channels ?? [];
  const widths = [...new Set(channels.map(c => c.width_bits))].sort((a, b) => a - b);
  const latencies = [...new Set(channels.map(c => c.latency_cycles))].sort((a, b) => a - b);
  const query = channelQuery.trim().toLowerCase();
  const channelRows = channels
    .map((channel, index) => ({ channel, index }))
    .filter(({ channel, index }) => !query || `ch-${index + 1} ${index + 1} ${channel.src_router}:${channel.src_port} ${channel.dst_router}:${channel.dst_port}`.includes(query));
  return <div className="view-main analysis-page">
    <RunBar project={project} run={run} />
    <CycleBudget project={project} run={run} />
    {sampled && <MeasuredRouterTotals run={run} topology={topology} />}
    {sampled && <MeasuredLoadShape run={run} topology={topology} selectedRange={loadRange} onSelectRange={pickLoadRange} />}
    {!sampled && <Section title="Measured channel counters" actions={<Badge tone={load.phase === 'loading' ? 'blue' : 'amber'}>{load.phase === 'loading' ? 'Reading…' : 'Not captured'}</Badge>}>
      {load.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the sampled channel artifact…</p>}
      {load.phase === 'error' && <Notice tone="red">{load.reason}</Notice>}
      {load.phase !== 'loading' && load.phase !== 'error' && <>
        <p className="meta-line">{load.phase === 'ready'
          ? 'This run’s sampled artifact carries no per-channel rows, so per-router load, load shape, channel activity and delay cost cannot be derived.'
          : 'This run has no sampled per-channel counters, so per-router load, load shape, channel activity and delay cost cannot be derived.'} Sampled series are an opt-in gateway setting (<span className="mono">VERITX_SERIES_SAMPLE_PERIOD</span>); this deployment produced the run without them, so rerunning here will not add counters.</p>
        <p className="meta-line">What this run does record: aggregate completion cycles, endpoint-pair packets and flits, requirement verdicts, and the declared topology below.</p>
      </>}
    </Section>}
    {routeProjectable && <RunFlitPlayback project={project} run={run} />}
    {routeProjectable && <RouteSweep project={project} run={run} />}
    {!routeProjectable && <Section title="Routing projection" actions={<Badge tone="amber">Not projectable</Badge>}>
      <p className="meta-line">This GEC-hybrid fabric routes as a ranked candidate union per source and destination, not one deterministic shared-resource path, so a flit cannot be placed on a single wire. Packet playback and the route sweep are unavailable for this fabric; the declared channels and shared wires remain listed below.</p>
    </Section>}
    {sampled && <MeasuredLinks run={run} topology={topology} utilizationRange={loadRange} onClearRange={() => setLoadRange(null)} />}
    {sampled && <MeasuredDelayCost run={run} topology={topology} />}
    <details className="fold-section" open={channelsExpanded || Boolean(query)} onToggle={event => { if (!query) setChannelsExpanded(event.currentTarget.open); }}>
      <summary>
        <span className="fold-caret" aria-hidden="true">▸</span>
        <h2>{topology?.shared_links?.length ? 'Declared channels & shared wires' : 'Declared directed channels'}</h2>
        <Badge>{channelRows.length === channels.length ? `${channels.length} channels` : `${channelRows.length} of ${channels.length}`}</Badge>
      </summary>
      <div className="fold-section-body">
        {channels.length ? <>
          <div className="toolbar toolbar-start channel-toolbar">
            <label className="field channel-search"><span>Find a channel</span>
              <input aria-label="Find a declared channel" value={channelQuery} placeholder="CH-42, router 3, or 3:1 → 4:1" onChange={event => setChannelQuery(event.target.value)} />
            </label>
            <span className="muted">{channelRows.length} match{channelRows.length === 1 ? '' : 'es'} · the whole list scrolls in place</span>
            {channelQuery && <Button onClick={() => setChannelQuery('')}>Clear</Button>}
          </div>
          {channelRows.length ? <div className="table-scroll capped channel-table-scroll"><table>
            <thead><tr><th>Channel</th><th>From</th><th>To</th><th>Width (bits)</th><th>Latency (cycles)</th></tr></thead><tbody>
              {channelRows.map(({ channel, index }) => <tr key={`${channel.src_router}-${channel.src_port}-${channel.dst_router}-${index}`}>
                <th className="mono">CH-{index + 1}</th>
                <td className="mono">{channel.src_router}:{channel.src_port}</td>
                <td className="mono">{channel.dst_router}:{channel.dst_port}</td>
                <td className="numeric">{channel.width_bits}</td>
                <td className="numeric">{channel.latency_cycles}</td>
              </tr>)}
            </tbody>
          </table></div> : <Empty title="No channel matches">Try a channel number such as <code>CH-42</code>, or a router such as <code>3</code>.</Empty>}
        </> : topology?.shared_links?.length ? <><div className="table-scroll capped"><table><thead><tr><th>Wire</th><th>Driver</th><th>Taps</th><th>Width</th><th>Latency</th></tr></thead><tbody>{topology.shared_links.map(wire => <tr key={wire.shared_link_id}><th>W{wire.shared_link_id}</th><td>R{wire.src_router}</td><td>{wire.taps.map(router => `R${router}`).join(', ')}</td><td>{wire.width_bits} bits</td><td>{wire.latency_cycles} cycles</td></tr>)}</tbody></table></div></> : <Empty title="No channels declared">The revision topology carries no channel list.</Empty>}
      </div>
    </details>
    <RunHistory project={project} run={run} />
    <Assumptions rows={[
      ['Recorded by this run', 'Endpoint-pair packets/flits, sampled per-channel flits, queue and latency counters, and aggregate completion cycles.'],
      ['Not recorded', 'Per-initiator latency, unique packets per channel, and cycle-by-cycle router-internal occupancy for the whole run. Per-packet timing exists only for the watched stride sample.'],
      ['Derived', 'Channel shares and bins come from sampled counters. Derived shares are never called utilization.'],
      ['Interval aggregates', <>From this run&apos;s sampled-counter artifact, not cycle-by-cycle playback. Formula: <span className="mono">flits_per_window/(window_cycles*link_capacity_flits_per_cycle)</span>.</>],
      ['Cycle budget', 'Injection span is the workload trace\'s first-to-last request; completion is the last ejected flit. The post-request tail includes source backlog and network drain. The watched split uses the latest sampled injection, so backlog is a lower bound and network drain an upper bound.'],
      ['Measured fabric work', <>Queue, arbitration and transmit counters are sums over every recorded channel and window. They are work counters, not elapsed cycles, and can overlap. Measured flits include local eject and multi-hop traversals.</>],
      ['Watched packet path', 'The head flit path from observed_hops.log. Router queue is receive-to-routing; arbitration is VC plus switch allocation; transmission is route, crossbar, link flight and ejection; drain is the tail retire after the head.'],
      ['Packet sample', 'At most 96 watched packets, a bounded stride sample, not a full per-packet trace. Per-packet queue and arbitration are available only for that sample.'],
      ['Channel ids', <>Declared channel ids are topology-local and 1-based. Measured <span className="mono">CH-…</span> ids encode the BookSim source router and output port and do not share this numbering.</>],
      ['Shared wires', 'One driver and multiple taps. Zero point-to-point channels does not mean an empty fabric.'],
      ['Link widths declared', widths.length ? `${widths.join(', ')} bits` : 'Not declared'],
      ['Link latencies declared', latencies.length ? `${latencies.join(', ')} cycles` : 'Not declared'],
      ['Topology family', topology?.family ?? 'Not supplied'],
      ['Source', 'GET /api/v1/revisions/{id}/topology and the sampled-counter artifact'],
      ['Run evaluated revision', run.detail.revision_id],
      ['Current revision', project.detail.active_revision_id ?? '—'],
      ['Same revision', project.detail.active_revision_id === run.detail.revision_id ? 'Yes' : 'No'],
    ]}>
      <PageLink page="analysis/matrix">Inspect endpoint-pair counts</PageLink>
    </Assumptions>
  </div>;
}


type PacketStats = {
  packets: number; makespan: number; drainTail: number; throughput: number;
  avg: number; p50: number; p95: number; p99: number; max: number;
  hops: number; queue: number; network: number; queueShare: number;
  latencies: number[];
};

function percentile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const at = (sorted.length - 1) * q;
  const low = Math.floor(at), high = Math.ceil(at);
  return sorted[low] + (sorted[high] - sorted[low]) * (at - low);
}

/** The per-packet table visualize_trace.py ranks runs on: makespan, drain
 *  tail, throughput, and the latency percentiles. It needs packets_out.csv,
 *  which carries one row per retired packet. */
function packetStats(text: string): PacketStats {
  const lines = text.trim().split(/\r?\n/);
  const header = lines[0].split(',').map(cell => cell.trim());
  const column = (name: string): number => {
    const index = header.indexOf(name);
    if (index < 0) throw new Error(`packets file has no '${name}' column`);
    return index;
  };
  const iTotal = column('total_latency'), iRequest = column('request_time');
  const iArrival = column('arrival_time');
  const iHops = column('hops'), iQueue = column('source_queue_delay'), iNetwork = column('network_latency');
  const iSize = header.indexOf('packet_size_flits');
  const rows = lines.slice(1).filter(line => line.trim()).map(line => line.split(',').map(Number));
  if (rows.length === 0) throw new Error('packets file has no rows');
  const latencies = rows.map(row => row[iTotal]).sort((a, b) => a - b);
  const request = rows.map(row => row[iRequest]);
  const arrival = rows.map(row => row[iArrival]);
  const t0 = Math.min(...request), t1 = Math.max(...arrival);
  const span = Math.max(1, t1 - t0);
  const flits = rows.reduce((sum, row) => sum + (iSize >= 0 ? row[iSize] : 1), 0);
  const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / values.length;
  const queue = rows.map(row => row[iQueue]), network = rows.map(row => row[iNetwork]);
  return {
    packets: rows.length, makespan: span, drainTail: t1 - Math.max(...request),
    throughput: flits / span,
    avg: mean(latencies), p50: percentile(latencies, 0.5), p95: percentile(latencies, 0.95),
    p99: percentile(latencies, 0.99), max: latencies[latencies.length - 1],
    hops: mean(rows.map(row => row[iHops])), queue: mean(queue), network: mean(network),
    queueShare: 100 * queue.reduce((a, b) => a + b, 0) / Math.max(1, latencies.reduce((a, b) => a + b, 0)),
    latencies,
  };
}

function LatencyDistribution({ files, runId, expected, metrics }: {
  files: Record<string, string>; runId: string; expected: number | null;
  metrics: Record<string, number | null | undefined>;
}) {
  const [phase, setPhase] = useState<'idle' | 'busy' | 'ready' | 'error'>('idle');
  const [stats, setStats] = useState<PacketStats | null>(null);
  const [reason, setReason] = useState('');
  const path = Object.keys(files).find(candidate => /(^|\/)packets[^/]*\.csv$/i.test(candidate)) ?? '';

  const load = async (): Promise<void> => {
    setPhase('busy'); setReason('');
    try {
      const bytes = await fetchVerifiedArtifact(runId, path, files[path]);
      setStats(packetStats(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
      setPhase('ready');
    } catch (error) {
      setReason(error instanceof Error ? error.message : String(error));
      setPhase('error');
    }
  };

  if (!path) return <Section title="Packet latency distribution">
    {typeof metrics.p50 === 'number' ? <>
      <div className="table-scroll"><table><thead><tr><th>Statistic</th><th>Value</th></tr></thead><tbody>
        <tr><th>p50 / median</th><td className="numeric">{metrics.p50.toFixed(2)} cyc</td></tr>
        <tr><th>p95</th><td className="numeric">{typeof metrics.p95 === 'number' ? `${metrics.p95.toFixed(2)} cyc` : '—'}</td></tr>
        <tr><th>p99</th><td className="numeric">{typeof metrics.p99 === 'number' ? `${metrics.p99.toFixed(2)} cyc` : '—'}</td></tr>
        <tr><th>Honest average</th><td className="numeric">{typeof metrics.honest_latency === 'number' ? `${metrics.honest_latency.toFixed(2)} cyc` : '—'}</td></tr>
        <tr><th>Samples</th><td className="numeric">{typeof metrics.pkt_count === 'number' ? metrics.pkt_count.toLocaleString() : '—'}</td></tr>
      </tbody></table></div>
    </> : <Empty title="No per-packet latencies in this bundle">The bundle has no <code>packets_out.csv</code> (one row per retired packet), so percentiles, drain tail and queue-vs-network delay are unavailable.</Empty>}
  </Section>;

  const counts = (() => {
    if (!stats) return [];
    const lo = stats.latencies[0], hi = stats.max;
    const width = Math.max(1, (hi - lo) / 24);
    const bins = new Array<number>(24).fill(0);
    for (const value of stats.latencies) {
      bins[Math.min(23, Math.floor((value - lo) / width))] += 1;
    }
    return bins.map((count, index) => ({ from: lo + index * width, count }));
  })();
  const peak = Math.max(1, ...counts.map(bin => bin.count));

  return <Section title="Packet latency distribution" actions={<Badge>{stats ? `${stats.packets} packets` : 'packets_out.csv'}</Badge>}>
    <p className="meta-line">Computed in the browser from <code>{path}</code>.</p>
    {phase === 'idle' && <Button primary onClick={() => void load()}>Read packets and compute percentiles</Button>}
    {phase === 'busy' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Verifying and reading packets…</p>}
    {phase === 'error' && <Notice tone="red">{reason}</Notice>}
    {stats && <>
      <div className="table-scroll"><table><thead><tr><th>Statistic</th><th>Value</th></tr></thead><tbody>
        <tr><th>Retired packets</th><td className="numeric">{stats.packets.toLocaleString()}{expected ? ` / ${expected.toLocaleString()} expected` : ''}</td></tr>
        <tr><th>Completion</th><td className="numeric">{expected ? `${(100 * stats.packets / expected).toFixed(1)} %` : '—'}</td></tr>
        <tr><th>Makespan</th><td className="numeric">{stats.makespan.toLocaleString()} cyc</td></tr>
        <tr><th>Drain tail</th><td className="numeric">{stats.drainTail.toLocaleString()} cyc</td></tr>
        <tr><th>Throughput</th><td className="numeric">{stats.throughput.toFixed(3)} flits/cyc</td></tr>
        <tr><th>Average latency</th><td className="numeric">{stats.avg.toFixed(2)} cyc</td></tr>
        <tr><th>p50 / median</th><td className="numeric">{stats.p50.toFixed(2)} cyc</td></tr>
        <tr><th>p95</th><td className="numeric">{stats.p95.toFixed(2)} cyc</td></tr>
        <tr><th>p99</th><td className="numeric">{stats.p99.toFixed(2)} cyc</td></tr>
        <tr><th>Max</th><td className="numeric">{stats.max.toFixed(2)} cyc</td></tr>
        <tr><th>Average hops</th><td className="numeric">{stats.hops.toFixed(2)}</td></tr>
        <tr><th>Source queue / network</th><td className="numeric">{stats.queue.toFixed(2)} / {stats.network.toFixed(2)} cyc</td></tr>
        <tr><th>Queue share of latency</th><td className="numeric">{stats.queueShare.toFixed(1)} %</td></tr>
      </tbody></table></div>
      <svg className="trace-bars" viewBox="0 0 720 220" role="img"
        aria-label={`Latency histogram: ${stats.packets} retired packets`}>
        {counts.map((bin, index) => {
          const height = bin.count === 0 ? 0 : Math.max(1, 180 * bin.count / peak);
          return <rect key={index} x={40 + index * 27.5} y={200 - height} width={25} height={height}
            className="trace-bar" />;
        })}
        <line x1="40" x2="700" y1="200" y2="200" className="trace-axis" />
        <text x="40" y="214" className="trace-label">{stats.latencies[0].toFixed(0)} cyc</text>
        <text x="680" y="214" className="trace-label">{stats.max.toFixed(0)} cyc</text>
        <text x="40" y="14" className="trace-label">packets per latency bin · p50 {stats.p50.toFixed(1)} · p95 {stats.p95.toFixed(1)} · p99 {stats.p99.toFixed(1)}</text>
      </svg>
    </>}
  </Section>;
}

export function LiveTrace({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const files = run.artifacts?.bundle?.files ?? {};
  const hasObservedCapture = Object.keys(files).some(path => path.endsWith('/observed_hops.log') || path === 'observed_hops.log');
  const metrics = run.detail.evaluation?.metrics ?? {};
  const loaded = metrics.loaded_trace_packets ?? null;
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <ObservedRunPlayback project={project} run={run} />
    <RawArtifacts key={run.detail.run_id} runId={run.detail.run_id} files={files} tracesOnly />
    <LatencyDistribution files={files} runId={run.detail.run_id} expected={typeof loaded === 'number' ? loaded : null} metrics={metrics} />
    <Assumptions rows={[
      ['Requested injections', 'From the fixed workload and revision, so identical inputs produce the same trace. They are not observed delivery or packet hops.'],
      ['Observed hops', 'Sampled BookSim hops are run observations, not hardware telemetry. Physical capture is not collected.'],
      ['Playback boundary', 'Observed markers show a flit after a recorded receipt and before its recorded send. In-flight positions, unlogged routers and queue internals are not inferred.'],
      ['Packet Gantt', 'One row per watched packet on the selected subnet. The row uses the head flit pipeline and closes at the packet tail retire; body flits are not drawn individually. Network only omits the request-to-injection source wait.'],
      ['Subnets and wires', 'Native subnets are isolated. Where the port-to-wire map is verified, a wire is drawn from its driver to its farthest tap. Watch capture can add diagnostic overhead.'],
      ['Raw artifacts', 'Shown only after whole-file digest verification. The routing dump is a verification input, not a standalone first-hop view.'],
      ['Percentiles', 'Packet latency percentiles need one row per retired packet. Average latency is never converted into a percentile or histogram.'],
    ]} />
  </div><Inspector title="Trace boundary">
    <Properties rows={[
      ['Files in bundle', String(run.artifacts?.bundle?.file_count ?? Object.keys(files).length)],
      ['Observed hops', hasObservedCapture ? 'Bounded sampled capture' : 'Not captured'],
      ['Not in this trace', 'Hardware telemetry · synthetic traces'],
    ]} />
    <PageLink page="verify/evidence">Inspect the evidence bundle</PageLink>
    <PageLink page="analysis/topology">Projected playback &amp; link stress</PageLink>
  </Inspector></div>;
}

const comparisonVerdictLabel: Record<string, string> = {
  COMPARABLE: 'comparable',
  NOT_COMPARABLE: 'not comparable',
  MODEL_DIFFERENCE: 'model difference',
  MISSING_MEASUREMENT: 'missing measurement',
  QUALIFICATION_DIFFERENCE: 'qualification difference',
  DEFINITION_DIFFERENCE: 'definition difference',
};
const comparisonVerdictTone = (verdict: string): 'green' | 'blue' | 'amber' | 'red' =>
  verdict === 'COMPARABLE' ? 'green'
    : verdict === 'MODEL_DIFFERENCE' ? 'blue'
      : verdict === 'DEFINITION_DIFFERENCE' ? 'red'
        : 'amber';
const shortRunId = (value?: string | null): string => value ? `${value.slice(0, 8)}…` : 'Not recorded';

export function LiveComparison({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const others = (project.detail.runs ?? []).filter(r => r.run_id !== run.detail.run_id);
  const [otherId, setOtherId] = useState(others[0]?.run_id ?? '');
  const [runFilter, setRunFilter] = useState('');
  const [other, setOther] = useState<{ phase: 'idle' | 'loading' | 'loaded' | 'error'; detail?: RunDetail; reason?: string }>({ phase: 'idle' });
  useEffect(() => {
    if (!otherId) return;
    let live = true;
    setOther({ phase: 'loading' });
    gateway.run(otherId).then(detail => { if (live) setOther({ phase: 'loaded', detail }); })
      .catch(error => { if (live) setOther({ phase: 'error', reason: gatewayReason(error) }); });
    return () => { live = false; };
  }, [otherId]);
  const backend = useGatewayDocument(
    `comparison:${run.detail.run_id}:${other.detail?.run_id ?? 'none'}`,
    () => other.detail ? gateway.compare(run.detail.run_id, other.detail.run_id) : Promise.resolve({} as Comparison),
  );
  const comparison = backend.data as Comparison | undefined;
  const backendRows = (comparison?.rows ?? []) as ComparisonRow[];
  const compatibility = (comparison?.compatibility ?? {}) as Comparison['compatibility'];
  const verdictNote = !other.detail ? null : !backend.data
    ? (backend.error ? `Backend comparison unavailable: ${backend.error}` : 'Reading backend comparison…')
    : compatibility.compatible
      ? 'Backend verdict: comparable. Deltas below are server-computed.'
      : `Backend verdict: not comparable. ${(compatibility.reasons ?? []).join('; ') || 'See per-row verdicts.'}`;

  const sideA = comparison?.a ?? {};
  const sideB = comparison?.b ?? {};
  const aRun = {
    runId: sideA.run_id ?? run.detail.run_id,
    backend: sideA.backend ?? run.detail.backend ?? null,
    status: sideA.status ?? run.detail.status,
    qualification: sideA.qualification ?? run.detail.qualification ?? null,
    revision: sideA.revision_id ?? run.detail.revision_id,
    window: sideA.measurement_window_cycles ?? null,
    config: sideA.backend_config_hash ?? null,
  };
  const bRun = {
    runId: sideB.run_id ?? other.detail?.run_id ?? null,
    backend: sideB.backend ?? other.detail?.backend ?? null,
    status: sideB.status ?? other.detail?.status ?? null,
    qualification: sideB.qualification ?? other.detail?.qualification ?? null,
    revision: sideB.revision_id ?? other.detail?.revision_id ?? null,
    window: sideB.measurement_window_cycles ?? null,
    config: sideB.backend_config_hash ?? null,
  };

  const groups: { question: string; rows: ComparisonRow[] }[] = [];
  for (const row of backendRows) {
    const question = row.question ?? '';
    const group = groups.find(entry => entry.question === question);
    if (group) group.rows.push(row);
    else groups.push({ question, rows: [row] });
  }
  const verdictCounts = backendRows.reduce<Record<string, number>>((counts, row) => {
    counts[row.verdict] = (counts[row.verdict] ?? 0) + 1;
    return counts;
  }, {});

  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <div className="toolbar compare-toolbar">
      <label className="field"><span>Compare against</span>
        <select aria-label="Comparison run" value={otherId} onChange={e => setOtherId(e.target.value)}>
          {others.length === 0 && <option value="">No other run in this project</option>}
          {others.map(r => <option key={r.run_id} value={r.run_id}>{r.display_name ?? r.run_id} · {shortRunId(r.run_id)} · {r.backend ?? 'backend not declared'} · {r.status}</option>)}
        </select>
      </label>
      {other.phase === 'loading' && <Badge tone="amber">Reading run…</Badge>}
      {other.phase === 'error' && <Badge tone="red">{other.reason}</Badge>}
    </div>
    {verdictNote && <Notice tone={!backend.data || compatibility.compatible ? 'blue' : 'amber'}>{verdictNote}</Notice>}
    {other.detail && <div className="compare-sides" role="group" aria-label="Compared runs">
      <div className="compare-side">
        <div className="compare-side-head"><strong>A · this run</strong><Badge tone="blue">{aRun.status ?? 'status not stated'}</Badge></div>
        <div className="compare-side-body">
          <div className="mono compare-run-id">{aRun.runId ?? 'Not recorded'}</div>
          <dl className="side-facts">
            <div><dt>Backend</dt><dd className="mono">{aRun.backend ?? 'Not declared'}</dd></div>
            <div><dt>Qualification</dt><dd>{aRun.qualification ?? 'Not declared'}</dd></div>
            <div><dt>Revision</dt><dd className="mono">{aRun.revision ? shortRevision(aRun.revision) : 'Not stated'}</dd></div>
            <div><dt>Window</dt><dd>{aRun.window == null ? 'Not stated' : `${num(aRun.window)} cycles`}</dd></div>
            <div><dt>Backend config</dt><dd className="mono" title={aRun.config ?? 'Not declared'}>{aRun.config ? `${aRun.config.slice(0, 16)}…` : 'Not declared'}</dd></div>
          </dl>
        </div>
      </div>
      <div className="compare-side">
        <div className="compare-side-head"><strong>B · comparison run</strong><Badge>{bRun.status ?? 'status not stated'}</Badge></div>
        <div className="compare-side-body">
          <div className="mono compare-run-id">{bRun.runId ?? 'Not recorded'}</div>
          <dl className="side-facts">
            <div><dt>Backend</dt><dd className="mono">{bRun.backend ?? 'Not declared'}</dd></div>
            <div><dt>Qualification</dt><dd>{bRun.qualification ?? 'Not declared'}</dd></div>
            <div><dt>Revision</dt><dd className="mono">{bRun.revision ? shortRevision(bRun.revision) : 'Not stated'}</dd></div>
            <div><dt>Window</dt><dd>{bRun.window == null ? 'Not stated' : `${num(bRun.window)} cycles`}</dd></div>
            <div><dt>Backend config</dt><dd className="mono" title={bRun.config ?? 'Not declared'}>{bRun.config ? `${bRun.config.slice(0, 16)}…` : 'Not declared'}</dd></div>
          </dl>
        </div>
      </div>
    </div>}
    <Section title="Reported metrics side by side · backend verdicts" actions={backendRows.length ? <div className="compare-verdict-counts">
      {Object.keys(comparisonVerdictLabel).filter(verdict => verdictCounts[verdict]).map(verdict =>
        <Badge key={verdict} tone={comparisonVerdictTone(verdict)}>{verdictCounts[verdict]} {comparisonVerdictLabel[verdict]}</Badge>)}
    </div> : undefined}>
      {other.detail && backendRows.length ? <div className="table-scroll compare-table-scroll"><table className="compare-table"><thead><tr><th>Metric</th><th>Unit</th><th>A · {shortRunId(aRun.runId)}</th><th>B · {shortRunId(bRun.runId)}</th><th>Δ (B − A)</th><th>Verdict</th></tr></thead><tbody>
        {groups.map((group, groupIndex) => {
          const groupReason = group.rows.length > 0 && group.rows.every(row => row.reason === group.rows[0].reason) ? group.rows[0].reason : null;
          const groupVerdicts = group.rows.reduce<Record<string, number>>((counts, row) => {
            counts[row.verdict] = (counts[row.verdict] ?? 0) + 1;
            return counts;
          }, {});
          return <Fragment key={`${group.question}:${groupIndex}`}>
            <tr className="metric-group">
              <th colSpan={6}>
                <div className="metric-group-head">
                  <span className="metric-group-role">{questionRole(group.question)}</span>
                  <strong className="mono">{group.question || 'Unclassified metric'}</strong>
                  <span className="metric-group-count">{group.rows.length} metric{group.rows.length === 1 ? '' : 's'}</span>
                  {Object.entries(groupVerdicts).map(([verdict, count]) =>
                    <Badge key={verdict} tone={comparisonVerdictTone(verdict)}>{count} {comparisonVerdictLabel[verdict] ?? verdict}</Badge>)}
                </div>
                {groupReason && <p className="metric-group-reason">{groupReason}</p>}
              </th>
            </tr>
            {group.rows.map((row, i) => <tr key={`${row.question ?? ''}:${row.key ?? '?'}:${i}`} data-verdict={row.verdict}>
              <th className="metric-cell">
                <span className="metric-name">{row.key ?? '—'}{row.dimensions ? <span className="metric-dimension"> · {row.dimensions}</span> : null}</span>
                <span className="metric-definition mono">{row.definition_id ?? 'Definition not supplied'}</span>
              </th>
              <td>{row.unit ?? '—'}</td>
              <td className="numeric">{num(row.a)}</td><td className="numeric">{num(row.b)}</td>
              <td className="numeric">{row.comparable && typeof row.delta_b_minus_a === 'number' && Number.isFinite(row.delta_b_minus_a) ? num(row.delta_b_minus_a) : '—'}</td>
              <td>
                <Badge tone={comparisonVerdictTone(row.verdict)}>{row.verdict ?? '—'}</Badge>
                {!groupReason && row.reason && <small className="row-reason">{row.reason}</small>}
                {!groupReason && row.differs && <small className="mono row-differs">{row.differs}</small>}
              </td>
            </tr>)}
          </Fragment>;
        })}
      </tbody></table></div> : other.phase === 'error' ? <Empty title="Second run unavailable">{other.reason}</Empty> : !other.detail ? <Empty title="Nothing to compare">Pick a second run; this project has {others.length}.</Empty> : backend.error ? <Notice tone="amber">Backend comparison unavailable: {backend.error}</Notice> : <p>Reading backend comparison…</p>}
    </Section>

    <Assumptions rows={[
      ['Authority', <><span className="mono">GET /api/v1/compare</span>; the browser performs no gating arithmetic.</>],
      ['Comparability', 'Rows are grouped by the question that measured them. A row is comparable only when the server finds the same question, metric, unit, coordinates, model fidelity, backend configuration, window and qualification.'],
      ['Requirement verdicts', 'Evaluated per run on each run summary, not across runs.'],
      ['Not claimed', 'Statistical significance. Confidence intervals are not supplied.'],
    ]} />
  </div><Inspector title="Runs in project">
    <p className="meta-line">Select the comparison run (B). Run A is open on this page.</p>
    {others.length > 8 && <label className="search-field"><input aria-label="Filter runs" placeholder="Filter runs…" value={runFilter} onChange={event => setRunFilter(event.target.value)} /></label>}
    <ol className="compare-run-list">
      <li className="compare-run-current">
        <span className="compare-run-marker" aria-hidden="true" />
        <div className="compare-run-copy">
          <strong>{aRun.runId ? shortRunId(aRun.runId) : 'This run'}</strong>
          <span className="mono">A · {aRun.revision ? shortRevision(aRun.revision) : 'revision not stated'}</span>
          <small>{aRun.status}{aRun.backend ? ` · ${aRun.backend}` : ' · backend not declared'}</small>
        </div>
      </li>
      {others.filter(r => !runFilter || `${r.run_id} ${r.display_name ?? ''} ${r.status} ${r.backend ?? ''}`.toLowerCase().includes(runFilter.toLowerCase())).map(r => <li key={r.run_id}>
        <button type="button" className="compare-run" aria-pressed={r.run_id === otherId} onClick={() => setOtherId(r.run_id)}>
          <span className="compare-run-marker" aria-hidden="true" />
          <span className="compare-run-copy">
            <strong>{r.display_name ?? shortRunId(r.run_id)}</strong>
            <span className="mono">{shortRunId(r.run_id)} · {shortRevision(r.revision_id)}</span>
            <small>{r.status}{r.backend ? ` · ${r.backend}` : ' · backend not declared'}</small>
          </span>
        </button>
      </li>)}
    </ol>
    <PageLink page="analysis/summary">Evaluation summary</PageLink>
  </Inspector></div>;
}

export function LiveEvidence({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const files = run.artifacts?.bundle?.files ?? {};
  const total = Object.values(files).length;
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    <Section title="Evidence identity">
      <Properties rows={[[ 'Run', <span className="mono">{run.detail.run_id}</span> ], ['Evaluated revision', run.detail.revision_id ], ['Evidence record', run.detail.evidence?.evidence_id ? 'Recorded' : 'Not reported' ], ['Bundle', run.detail.bundle_id ? 'Recorded' : 'Not reported' ], ['Files', String(run.artifacts?.bundle?.file_count ?? total) ], ['Qualification', `${run.detail.qualification ?? '—'} · ${run.detail.qualification_basis ?? 'no basis declared'}` ]]} />
    </Section>
    <EvidenceDocuments key={run.detail.run_id} runId={run.detail.run_id} />
    <RawArtifacts key={`raw-${run.detail.run_id}`} runId={run.detail.run_id} files={files} />
    <Section title="Bundle files" actions={<Badge>{total} listed</Badge>}>
      {total ? <div className="table-scroll bundle-files-table"><table><thead><tr><th>Path</th><th>Status</th></tr></thead><tbody>
        {Object.keys(files).map(path => <tr key={path}><td className="mono">{path}</td><td><Badge tone="green">Recorded</Badge></td></tr>)}
      </tbody></table></div> : <Empty title="No bundle files returned">The artifacts endpoint returned no bundle files for this run.</Empty>}
    </Section>
    {run.gaps.length > 0 && <Notice tone="amber">Partial reads: {run.gaps.join(' · ')}</Notice>}
    <Assumptions rows={[
      ['Evidence origin', 'Repository gateway run bundle.'],
      ['Prototype computation', 'None; values are displayed as reported. Raw artifacts are digest-verified before they are shown.'],
      ['Integrity verification', 'See the checks view.'],
      ['Not measured', 'Transaction-level latency.'],
      ['Hardware qualification', 'Not established by a network simulation.'],
    ]} />
  </div><Inspector title="Claim scope">
    <Properties rows={[[ 'Evidence origin', 'Repository gateway run bundle' ], ['Computed by this prototype', 'Nothing; values are displayed as reported' ], ['Integrity verification', 'See Local Checks' ], ['Transaction-level latency', 'Not measured' ], ['Hardware qualification', 'Not established by a network simulation' ]]} />
    <PageLink page="verify/checks">Inspect conservation and route realization</PageLink>
    <PageLink page="analysis/metrics">Inspect metrics</PageLink>
  </Inspector></div>;
}

export function LiveChecks({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const integrity = run.integrity;
  const rows = [
    ['Packet conservation', integrity?.packet_conservation],
    ['Flit conservation', integrity?.flit_conservation],
  ] as const;
  return <div className="view-layout"><div className="view-main">
    <RunBar project={project} run={run} />
    {!integrity && <Notice tone="amber"><strong>No integrity document.</strong> {run.gaps.find(g => g.startsWith('integrity')) ?? ''}</Notice>}
    {integrity && <>
      <Section title="Conservation">
        <div className="table-scroll"><table><thead><tr><th>Quantity</th><th>Stage</th><th>Value</th><th>Availability</th></tr></thead><tbody>
          {rows.flatMap(([label, block]) => Object.entries(block ?? {}).map(([stage, value]) => {
            if (typeof value === 'string') return <tr key={`${label}-${stage}`} className="selected"><th>{label}</th><td>backend verdict</td><td className="numeric">{value}</td><td><Badge tone={/CONSERVED|PASS/i.test(value) ? 'green' : 'amber'}>reported</Badge></td></tr>;
            const entry = value as { value: number | null; availability: string };
            return <tr key={`${label}-${stage}`}><th>{label}</th><td>{stage}</td><td className="numeric">{num(entry?.value)}</td><td><Badge tone={entry?.availability === 'MEASURED' ? 'green' : 'amber'}>{entry?.availability ?? '—'}</Badge></td></tr>;
          }))}
        </tbody></table></div>
      </Section>
      <Section title="Route realization">
        <Properties rows={[[ 'Status', integrity.route_realization?.status ?? '—' ], ['Scope', integrity.route_realization?.scope ?? '—' ], ['Full path claimed', integrity.route_realization?.full_path_claimed ? 'Yes' : 'No' ]]} />
      </Section>
      <Section title="Per-analysis status">
        <div className="table-scroll"><table><thead><tr><th>Analysis</th><th>Backend</th><th>Status</th><th>Packets / flits</th></tr></thead><tbody>
          {Object.entries(integrity.analyses ?? {}).map(([name, value]) => <tr key={name}><th className="mono">{name}</th><td>{value.backend ?? '—'}</td><td><Badge tone={value.status === 'EVALUATED' ? 'green' : 'amber'}>{value.status ?? '—'}</Badge></td><td className="numeric">{num(value.packets)} / {num(value.flits)}</td></tr>)}
        </tbody></table></div>
      </Section>
    </>}
    <TrustChecks project={project} run={run} />
    <Assumptions rows={[
      ['Source', 'GET /api/v1/runs/{run_id}/integrity'],
      ['Conservation', 'Backend-reported, per-stage availability. NOT_AVAILABLE means undeclared, not zero.'],
      ['Deadlock proof', 'Not supplied.'],
      ['Functional correctness', 'Not evaluated.'],
      ['Prototype computation', 'None.'],
    ]} />
  </div><Inspector title="Check scope">
    <Properties rows={[[ 'Source', 'GET /api/v1/runs/{run_id}/integrity' ], ['Conservation', 'Backend-reported, per-stage availability' ], ['Deadlock proof', 'Not supplied' ], ['Functional correctness', 'Not evaluated' ], ['Prototype computation', 'None' ]]} />
    <PageLink page="verify/evidence">Inspect evidence bundle</PageLink>
  </Inspector></div>;
}

export function LiveRunArtifacts({ run }: { run: LoadedRun }) {
  const bundle = run.artifacts?.bundle;
  const files = bundle?.files ?? {};
  const entries = Object.entries(files);
  return <>
    <EvidenceDocuments key={run.detail.run_id} runId={run.detail.run_id} />
    <RawArtifacts key={`raw-${run.detail.run_id}`} runId={run.detail.run_id} files={files} />
    <Properties rows={[[ 'Run', <span className="mono">{run.detail.run_id.slice(0, 13)}…</span> ], ['File count', String(bundle?.file_count ?? entries.length) ], ['Endpoint', 'GET /api/v1/runs/{run_id}/artifacts' ], ['Files shown here', `${entries.length} recorded` ]]} />
    {entries.length ? <div className="table-scroll"><table><thead><tr><th>Artifact</th><th>Status</th></tr></thead><tbody>
      {entries.map(([path]) => <tr key={path}><td className="mono">{path}</td><td><Badge tone="green">Recorded</Badge></td></tr>)}
    </tbody></table></div> : <Empty title="No artifact files for this run">The artifacts endpoint returned no file map.</Empty>}
  </>;
}
