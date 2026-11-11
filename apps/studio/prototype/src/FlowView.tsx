import { useEffect, useState } from 'react';
import { gateway, type CatalogAnalysis, type CatalogRow } from './gateway';
import type { PageId } from './model';
import { useLoadedProject, useLoadedRun, useProject, type LoadedProject } from './project';
import { Assumptions, Badge, Button, Empty, Icon, Notice, PageLink, Section, type ViewProps } from './ui';
import { LiveWorkloadPage } from './WorkloadStudio';
import { LiveRequirementsPage } from './RequirementsStudio';
import type { IntentSaveState } from './intent';
import { CatalogCampaign } from './CatalogCampaign';
import { LiveAgents } from './LiveAgents';
import { useGatewayDocument } from './LiveOperations';
import { DraftEditor } from './DraftEditor';
import { LaunchEvaluation } from './LaunchEvaluation';
import { LiveAnalysisWorkspace, type AnalysisTab } from './LiveAnalysis';
import { RunSelect } from './RevisionHistory';
import { FinalDelivery } from './FinalDelivery';
import { FlowStart } from './FlowStart';

const STEPS: PageId[] = ['flow/start', 'flow/tune', 'flow/search', 'flow/optimize', 'flow/run'];

/** The flow is the index, not a second implementation: every step names the
 *  full workspace that already owns the same evidence, so an operator can go
 *  deeper without the flow re-drawing the surface. */
const FULL_WORKSPACES: Partial<Record<PageId, { page: PageId; label: string }[]>> = {
  'flow/tune': [{ page: 'workloads/workflow', label: 'Workloads & requirements' }, { page: 'workloads/lowering', label: 'Lowering preview' }],
  'flow/search': [{ page: 'explore/fabric-search', label: 'Reference catalog' }, { page: 'explore/fabric-ablations', label: 'Fabric ablations' }, { page: 'analysis/curves', label: 'Curves & Pareto' }],
  'flow/optimize': [{ page: 'explore/brief', label: 'Revision study' }, { page: 'design/fabric-topology', label: 'Fabric topology' }],
  'flow/run': [{ page: 'analysis/summary', label: 'Analysis summary' }, { page: 'verify/evidence', label: 'Run evidence' }, { page: 'deliver/package', label: 'Delivery manifest' }],
};

function FlowIndex({ step }: { step: PageId }) {
  const links = FULL_WORKSPACES[step];
  if (!links) return null;
  return <details className="flow-more">
    <summary>Open in full workspace</summary>
    <nav className="flow-more-links" aria-label="Full workspace views">
      {links.map(link => <a key={link.page} href={`#/${link.page}`}>{link.label}<Icon name="arrow" size={13} /></a>)}
    </nav>
  </details>;
}

export function FlowViews(props: ViewProps & { page: PageId }) {
  const step = STEPS.indexOf(props.page);
  const project = useLoadedProject();
  const { project: state } = useProject();
  if (state.phase === 'loading') return <div className="view-main flow-page"><p role="status">Loading project…</p></div>;
  return <div className={`view-main flow-page flow-view flow-page-${props.page.split('/').pop()}`}>
    <FlowIndex step={props.page} />
    {step === 0 ? <FlowStart navigate={props.navigate} notify={props.notify} />
      : !project ? <FlowNoProject step={step} />
        : props.page === 'flow/tune' ? <FlowTune {...props} project={project} />
          : props.page === 'flow/search' ? <FlowSearch {...props} project={project} />
              : props.page === 'flow/optimize' ? <FlowOptimize {...props} project={project} />
                : <FlowRun {...props} project={project} />}
  </div>;
}

function FlowNoProject({ step }: { step: number }) {
  return <>
    <Empty title={`Step ${step + 1} needs a project`}>Start from a shipped preset or open an existing project before continuing.</Empty>
    <div className="toolbar"><PageLink page="flow/start" primary>Go to step 1 · Workload template</PageLink><PageLink page="shared/projects">Open projects &amp; revisions</PageLink></div>
    <Assumptions rows={[['Scope', 'A project is the input to every later step. Nothing is substituted when none is loaded.']]} />
  </>;
}

function FlowTune({ project, notify, navigate }: ViewProps & { project: LoadedProject }) {
  const [tab, setTab] = useState<'workload' | 'requirements'>('workload');
  const [saveState, setSaveState] = useState<IntentSaveState | null>(null);
  const changeTab = (next: 'workload' | 'requirements') => {
    if (next === tab) return;
    if (saveState?.dirty && !window.confirm('Discard unsaved changes in this tab?')) return;
    setSaveState(null); setTab(next);
  };
  // One action bar for both tabs, rendered inside the page's footer so the
  // assumptions block stays below it instead of being split in two.
  const actions = <div className="toolbar flow-launch-actions">
    <PageLink page="flow/start">Back · Workload templates</PageLink>
    <div className="actions">
      <Button primary={saveState?.dirty} disabled={!saveState?.dirty || !saveState.valid || saveState.busy} onClick={() => saveState?.save()}>{saveState?.busy ? 'Saving…' : 'Save workload intent'}</Button>
      <Button primary={!saveState?.dirty} disabled={!project.request || !!saveState?.dirty || !!saveState?.busy} onClick={() => navigate('flow/search')}>Next · Generate traffic &amp; evaluate catalog</Button>
    </div>
  </div>;
  return <>
    <Section title="Define the workload" actions={<Badge>{project.detail.project.name}</Badge>}>
      <div className="intent-tabs" role="tablist" aria-label="Workload intent sections">
        <button type="button" role="tab" aria-selected={tab === 'workload'} onClick={() => changeTab('workload')}>Workload</button>
        <button type="button" role="tab" aria-selected={tab === 'requirements'} onClick={() => changeTab('requirements')}>Requirements</button>
      </div>
      {tab === 'workload'
        ? <LiveWorkloadPage project={project} notify={notify} embedded onSaveState={setSaveState} footer={actions} />
        : <LiveRequirementsPage project={project} notify={notify} embedded onSaveState={setSaveState} footer={actions} />}
      {saveState?.error && <Notice tone="red">{saveState.error}</Notice>}
    </Section>
  </>;
}

function FlowSearch(props: ViewProps & { project: LoadedProject }) {
  return <CatalogCampaign {...props} />;
}

const FLOW_OPTIMIZE_SCOPE: [string, string][] = [
  ['Authored controls', 'Topology, physical assumptions, arbitration, per-VC buffer depth, credit latency, allocator iterations and router pipeline timing are saved through the canonical fabric editor. Srota adds MECS, routing shapes, VC policy, side buffers, telemetry and islands.'],
  ['Derived controls', 'The compiler determines VC count, routing legality and deadlock proof. A successful compile is not a performance measurement.'],
  ['Execution', 'No model is required. Save & compile validates the current form, saves the returned canonical request and compiles that exact draft version.'],
];

function FlowOptimize({ project, navigate, notify }: ViewProps & { project: LoadedProject }) {
  const [method, setMethod] = useState<'manual' | 'ai'>('manual');
  const [manualDirty, setManualDirty] = useState(false);
  const [editorState, setEditorState] = useState<IntentSaveState | null>(null);
  const [baselineRetry, setBaselineRetry] = useState(0);
  const changeMethod = (next: 'manual' | 'ai') => {
    if (next === method || editorState?.busy) return;
    if (manualDirty && !window.confirm('Discard unsaved parameter changes before switching refinement methods?')) return;
    setManualDirty(false); setEditorState(null); setMethod(next);
  };
  const { data, error } = useGatewayDocument(`catalog-selection:${project.detail.project.project_id}:${project.draftMeta?.revisionToken}`, () => gateway.catalogPlan(project.detail.project.project_id));
  const selection = data?.selection ?? null;
  const baseline = useGatewayDocument(`catalog-baseline:${project.detail.project.project_id}:${selection?.job_id ?? 'none'}:${baselineRetry}`, () =>
    selection ? gateway.catalogEvaluation(project.detail.project.project_id, selection.job_id) : Promise.resolve({}));
  useEffect(() => {
    if (!manualDirty) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [manualDirty]);
  if (!data) return error ? <Notice tone="red">{error}</Notice> : <p role="status">Reading fabric selection…</p>;
  if (!data.selection) return <>
    <Empty title="Choose a measured fabric first">Run the catalog on your workload, then choose a result before refining its parameters. <PageLink page="flow/search">Evaluate &amp; choose fabric</PageLink></Empty>
    <Assumptions rows={FLOW_OPTIMIZE_SCOPE} />
  </>;
  const revision = project.detail.active_revision_id;
  const savedDirty = !!project.draftMeta?.dirty;
  const compileState = manualDirty ? 'Unsaved edits' : savedDirty ? 'Saved draft differs' : revision ? `Compiled revision ${revision}` : 'Needs draft';
  const baselineRow = baseline.data?.rows?.find((row: CatalogRow) => row.candidate_id === data.selection.candidate_id || row.topology_id === data.selection.topology_id);
  const network = baselineRow?.objective_values?.completion_cycles ?? baselineRow?.analyses?.find((row: CatalogAnalysis) => row.question === 'NETWORK_COMPLETION')?.normalized_metrics?.find((metric: any) => metric.key === 'completion_cycles' && !metric.dimensions?.length)?.value;
  const system = baselineRow?.objective_values?.system_makespan_cycles ?? baselineRow?.analyses?.find((row: CatalogAnalysis) => row.question === 'SYSTEM_MAKESPAN')?.normalized_metrics?.find((metric: any) => metric.key === 'system_makespan_cycles' && !metric.dimensions?.length)?.value;
  const requirements = baselineRow?.requirements_pass === true ? 'Satisfied' : baselineRow?.requirements_pass === false ? 'Not satisfied' : 'Not established';
  return <>
    <Section title={`Selected fabric · ${data.selection.label}`} actions={<Badge tone={data.selection.workload_id && data.workload_id && data.selection.workload_id !== data.workload_id ? 'amber' : 'blue'}>{data.selection.workload_id && data.workload_id && data.selection.workload_id !== data.workload_id ? 'Workload changed' : 'Workload preserved'}</Badge>}>
      {data.selection.workload_id && data.workload_id && data.selection.workload_id !== data.workload_id && <Notice tone="amber">This fabric was selected for a different saved workload. Re-run the catalog before treating its baseline as current. <PageLink page="flow/search">Evaluate this workload</PageLink></Notice>}
      <div className="stat-strip">
        <div className="stat"><span>Selected fabric</span><strong>{data.selection.label}</strong><small className="mono">{data.selection.candidate_id}</small></div>
        <div className="stat"><span>Network baseline</span><strong>{typeof network === 'number' ? `${network.toLocaleString()} cyc` : baseline.data || baseline.error ? 'Unavailable' : 'Reading…'}</strong><small>Catalog BookSim result</small></div>
        <div className="stat"><span>System baseline</span><strong>{typeof system === 'number' ? `${system.toLocaleString()} cyc` : baseline.data || baseline.error ? 'Unavailable' : 'Reading…'}</strong><small>Catalog ASTRA-SIM result</small></div>
        <div className="stat"><span>Requirements</span><strong>{requirements}</strong><small>{baselineRow?.vc_count != null ? `${baselineRow.vc_count} VCs at selection` : 'VC count not recorded'}</small></div>
      </div>
      <div className="flow-baseline-note"><small>Catalog-time measurements, not the edited draft · {compileState}</small><PageLink page="flow/search">Review catalog evidence</PageLink></div>
      {baseline.error && <Notice tone="amber">Catalog baseline could not be read: {baseline.error}<Button onClick={() => setBaselineRetry(value => value + 1)}>Retry baseline</Button></Notice>}
    </Section>
    <Section title="Parameter refinement" actions={<>
      <div className="segmented" role="group" aria-label="Refinement method">
        <button type="button" className={method === 'manual' ? 'active' : ''} aria-pressed={method === 'manual'} disabled={!!editorState?.busy} onClick={() => changeMethod('manual')}>Manual parameters</button>
        <button type="button" className={method === 'ai' ? 'active' : ''} aria-pressed={method === 'ai'} disabled={!!editorState?.busy} onClick={() => changeMethod('ai')}>AI-assisted refinement</button>
      </div>
      <button type="button" className="text-button" onClick={() => { if (manualDirty && !window.confirm('Change fabric? Unsaved parameter changes will be discarded.')) return; navigate('flow/search'); }}>Change fabric</button>
    </>}>
      {method === 'manual'
        ? <DraftEditor project={project} embedded tuning onDirty={setManualDirty} onSaveState={setEditorState}
            onCompiled={() => notify('Fabric settings compiled. Evaluate the new revision to measure the changes.')}
            onContinue={() => navigate('flow/run')} />
        : <LiveAgents project={project} embedded topologyOnly parametersOnly showAssumptions={false} />}
    </Section>
    <Assumptions rows={method === 'manual' ? FLOW_OPTIMIZE_SCOPE : [...FLOW_OPTIMIZE_SCOPE, ['Model assistance', 'AI refinement proposes parameter changes only after configured model access and explicit consent. A proposal is not measured evidence; it writes the draft, and compilation/evaluation remain explicit later actions.']]} />
  </>;
}

function FlowRun({ project }: ViewProps & { project: LoadedProject }) {
  const { evaluationJob, loadRun } = useProject();
  const run = useLoadedRun();
  const currentRun = run?.detail.revision_id === project.detail.active_revision_id;
  const selection = useGatewayDocument(`final-selection:${project.detail.project.project_id}:${project.draftMeta?.revisionToken}`, () => gateway.catalogPlan(project.detail.project.project_id));
  const [view, setView] = useState<'launch' | 'analyze'>(currentRun ? 'analyze' : 'launch');
  const [touched, setTouched] = useState(false);
  const [tab, setTab] = useState<AnalysisTab>('summary');

  useEffect(() => {
    if (evaluationJob.job?.state === 'COMPLETED') { setTouched(true); setView('analyze'); }
  }, [evaluationJob.job?.state]);
  useEffect(() => {
    if (run && currentRun && !touched) setView('analyze');
    // Only the first automatic selection should move the page; an explicit
    // "Launch evaluations" click must not be undone by a background reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.detail.run_id, currentRun, touched]);

  if (!selection.data) return selection.error ? <Notice tone="red">{selection.error}</Notice> : <p role="status">Reading finalized fabric…</p>;
  if (!selection.data.selection) return <Empty title="Choose a measured fabric first"><PageLink page="flow/search">Evaluate &amp; choose fabric</PageLink></Empty>;
  if (project.draftMeta?.dirty || !project.detail.active_revision_id) return <Notice tone="amber">Compile the selected fabric's saved parameters before final validation. <PageLink page="flow/optimize">Review & compile parameters</PageLink></Notice>;
  return <>
    {view === 'analyze' && run && !currentRun && <Notice tone="amber">This is historical evidence from {run.detail.revision_id}, not the finalized revision {project.detail.active_revision_id}. Launch a new evaluation to validate the final parameters.</Notice>}
    {project.draftMeta?.dirty && <Notice tone="amber"><strong>The saved draft differs from the active revision.</strong> Compile in Fine-tune before launching, or this evaluates the revision that is already published, not the draft changes.</Notice>}
    <Section title="Final fabric evaluation" actions={<>
      <Badge>{project.detail.runs?.length ?? 0} run{(project.detail.runs?.length ?? 0) === 1 ? '' : 's'} in project</Badge>
      {/* In analyze mode the embedded analysis workspace renders its own run
          selector; two selects for one value is duplication, not a choice. */}
      {view === 'launch' && <RunSelect revisions={project.detail.revisions ?? []} runs={project.detail.runs ?? []} value={run?.detail.run_id ?? ''} onChange={runId => { setTouched(true); setView('analyze'); loadRun(runId); }} ariaLabel="Selected run" activeRevisionId={project.detail.active_revision_id} />}
    </>}>
      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Run or analyze">
          <button type="button" className={view === 'launch' ? 'active' : ''} aria-pressed={view === 'launch'} onClick={() => { setTouched(true); setView('launch'); }}>Launch evaluations</button>
          <button type="button" className={view === 'analyze' ? 'active' : ''} aria-pressed={view === 'analyze'} onClick={() => { setTouched(true); setView('analyze'); }} disabled={!run}>Analyze selected run</button>
        </div>
        <PageLink page="flow/optimize">Refine parameters</PageLink>
      </div>
    </Section>

    {view === 'analyze' && run
      ? <LiveAnalysisWorkspace project={project} run={run} tab={tab} onTabChange={setTab} />
      : view === 'analyze' && !run
        ? <Empty title="No run selected">Launch an evaluation, or select an existing run above.</Empty>
        : <LaunchEvaluation project={project} />}
    <FinalDelivery project={project} />
    <Assumptions rows={[
      ['Evaluation plan', 'The gateway determines which analyses are READY for the active revision. Blocked analyses cannot be selected.'],
      ['Launch', 'Launching appends a real run using backend binaries on this host; confirmation is required.'],
      ['Result', 'After completion, the published run is selected for analysis.'],
      ['Qualification', 'A completed run does not imply requirement compliance, RTL qualification or hardware sign-off. Research RTL evidence below is reported separately.'],
    ]} />
  </>;
}
