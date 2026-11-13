import { useEffect, useState } from 'react';
import { gateway, type CatalogAnalysis, type CatalogRow } from './gateway';
import type { PageId } from './model';
import { useLoadedProject, useLoadedRun, useProject, type LoadedProject, type LoadedRun } from './project';
import { Assumptions, Badge, Button, Empty, Icon, Notice, PageLink, Section, type ViewProps } from './ui';
import { stamp } from './format';
import { IntentWorkspace } from './IntentWorkspace';
import type { IntentSaveState, IntentTab } from './intent';
import { CatalogCampaign } from './CatalogCampaign';
import { LiveAgents } from './LiveAgents';
import { useGatewayDocument } from './LiveOperations';
import { DraftEditor } from './DraftEditor';
import { LaunchEvaluation } from './LaunchEvaluation';
import { RunSelect } from './RevisionHistory';
import { FlowStart } from './FlowStart';
import { RtlStack } from './RtlStack';
import { FinalDelivery } from './FinalDelivery';

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
    <Empty icon="branch" title={`Step ${step + 1} needs a project`} action={<><PageLink page="flow/start" primary>Go to step 1 · Workload template</PageLink><PageLink page="shared/projects">Open projects &amp; revisions</PageLink></>}>
      The guided flow runs against a gateway project so every save, compile and run has an identity. Start from a workload template or open an existing project; the local sample is never substituted for it.
    </Empty>
    <Assumptions rows={[['Scope', 'A project is the input to every later step. Nothing is substituted when none is loaded.']]} />
  </>;
}

function FlowTune({ project, notify, navigate }: ViewProps & { project: LoadedProject }) {
  const [tab, setTab] = useState<IntentTab>('workload');
  return <IntentWorkspace
    project={project}
    notify={notify}
    tab={tab}
    onTabChange={setTab}
    tabs={['workload', 'requirements']}
    actions={({ save }) => <>
      <PageLink page="flow/start">Back · Workload templates</PageLink>
      <Button primary={!!save?.dirty} disabled={!save?.dirty || !save.valid || save.busy} onClick={() => save?.save()}>{save?.busy ? 'Saving…' : 'Save workload intent'}</Button>
      <Button primary={!save?.dirty} disabled={!project.request || !!save?.dirty || !!save?.busy} onClick={() => navigate('flow/search')}>Next · Evaluate catalog</Button>
    </>}
  />;
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
    <Empty icon="chart" title="Choose a measured fabric first" action={<PageLink page="flow/search" primary>Evaluate &amp; choose fabric</PageLink>}>
      Refinement edits the measured winner's existing topology and router controls. Run the catalog on this workload, inspect the comparison, and choose a result before this step can open.
    </Empty>
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
    <Section title={`Parameter refinement · ${data.selection.label}`} actions={<>
      <div className="segmented" role="group" aria-label="Refinement method">
        <button type="button" className={method === 'manual' ? 'active' : ''} aria-pressed={method === 'manual'} disabled={!!editorState?.busy} onClick={() => changeMethod('manual')}>Manual parameters</button>
        <button type="button" className={method === 'ai' ? 'active' : ''} aria-pressed={method === 'ai'} disabled={!!editorState?.busy} onClick={() => changeMethod('ai')}>AI-assisted refinement</button>
      </div>
      <button type="button" className="text-button" onClick={() => { if (manualDirty && !window.confirm('Change fabric? Unsaved parameter changes will be discarded.')) return; navigate('flow/search'); }}>Change fabric</button>
    </>}>
      {data.selection.workload_id && data.workload_id && data.selection.workload_id !== data.workload_id && <Notice tone="amber">This fabric was selected for a different saved workload. Re-run the catalog before treating its baseline as current. <PageLink page="flow/search">Evaluate this workload</PageLink></Notice>}
      <div className="fact-line flow-baseline">
        <span><small>Network</small> <strong>{typeof network === 'number' ? `${network.toLocaleString()} cyc` : baseline.data || baseline.error ? 'Unavailable' : 'Reading…'}</strong></span>
        <span><small>System</small> <strong>{typeof system === 'number' ? `${system.toLocaleString()} cyc` : baseline.data || baseline.error ? 'Unavailable' : 'Reading…'}</strong></span>
        <span><small>Requirements</small> <strong>{requirements}</strong></span>
        <span><small>Draft</small> <strong>{compileState}</strong></span>
        <PageLink page="flow/search">Catalog evidence</PageLink>
      </div>
      {baseline.error && <Notice tone="amber">Catalog baseline could not be read: {baseline.error}<Button onClick={() => setBaselineRetry(value => value + 1)}>Retry baseline</Button></Notice>}
      {method === 'manual'
        ? <DraftEditor project={project} embedded tuning onDirty={setManualDirty} onSaveState={setEditorState}
            onCompiled={() => notify('Fabric settings compiled. Evaluate the new revision to measure the changes.')}
            onContinue={() => navigate('flow/run')} />
        : <LiveAgents project={project} embedded topologyOnly parametersOnly showAssumptions={false} />}
    </Section>
    <Assumptions rows={method === 'manual' ? FLOW_OPTIMIZE_SCOPE : [...FLOW_OPTIMIZE_SCOPE, ['Model assistance', 'AI refinement proposes parameter changes only after configured model access and explicit consent. A proposal is not measured evidence; it writes the draft, and compilation/evaluation remain explicit later actions.']]} />
  </>;
}

function RunReceipt({ run }: { run: LoadedRun }) {
  const metric = (key: string) => run.detail.analyses
    ?.flatMap(analysis => analysis.normalized_metrics ?? [])
    .find(value => value.key === key && !value.dimensions?.length)?.value;
  const network = metric('completion_cycles');
  const system = metric('system_makespan_cycles');
  return <>
    <div className="stat-strip">
      <div className="stat"><span>Network completion</span><strong>{typeof network === 'number' ? `${network.toLocaleString()} cyc` : 'Not recorded'}</strong><small>BookSim</small></div>
      <div className="stat"><span>System makespan</span><strong>{typeof system === 'number' ? `${system.toLocaleString()} cyc` : 'Not recorded'}</strong><small>ASTRA-SIM</small></div>
      <div className="stat"><span>Requirements</span><strong>{run.detail.requirements_pass === true ? 'Pass' : run.detail.requirements_pass === false ? 'Fail' : 'Not recorded'}</strong><small>{run.detail.qualification ?? 'Qualification not recorded'}</small></div>
    </div>
    <div className="fact-line flow-run-facts">
      <span><small>Run</small> <strong>{run.detail.display_name ?? run.detail.run_id.slice(0, 13)}</strong></span>
      <span><small>Backend</small> <strong>{run.detail.backend ?? 'Not recorded'}</strong></span>
      <span><small>Completed</small> <strong>{run.detail.completed_at ? stamp(run.detail.completed_at) : 'Not recorded'}</strong></span>
    </div>
    <div className="toolbar toolbar-start">
      <PageLink page="analysis/summary" primary>Open full analysis</PageLink>
      <PageLink page="verify/evidence">Verify evidence</PageLink>
    </div>
  </>;
}

function FlowRun({ project }: ViewProps & { project: LoadedProject }) {
  const { evaluationJob, loadRun } = useProject();
  const run = useLoadedRun();
  const currentRun = run?.detail.revision_id === project.detail.active_revision_id;
  const [selectionRetry, setSelectionRetry] = useState(0);
  const selection = useGatewayDocument(`final-selection:${project.detail.project.project_id}:${project.draftMeta?.revisionToken}:${selectionRetry}`, () => gateway.catalogPlan(project.detail.project.project_id));
  const [view, setView] = useState<'launch' | 'analyze'>(currentRun ? 'analyze' : 'launch');
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (evaluationJob.job?.state === 'COMPLETED') { setTouched(true); setView('analyze'); }
  }, [evaluationJob.job?.state]);
  useEffect(() => {
    if (run && currentRun && !touched) setView('analyze');
    // Only the first automatic selection should move the page; an explicit
    // "Launch evaluations" click must not be undone by a background reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.detail.run_id, currentRun, touched]);

  if (!selection.data) return selection.error
    ? <Notice tone="red">{selection.error}<div className="toolbar"><Button onClick={() => setSelectionRetry(value => value + 1)}>Retry fabric selection</Button></div></Notice>
    : <p role="status">Reading finalized fabric…</p>;
  if (!selection.data.selection) return <Empty icon="shield" title="Choose a measured fabric first" action={<PageLink page="flow/search" primary>Evaluate &amp; choose fabric</PageLink>}>
    Final validation and the RTL preview are scoped to the fabric selected from a measured catalog run. Choose a result first; this step does not invent one.
  </Empty>;
  if (project.draftMeta?.dirty || !project.detail.active_revision_id) return <Empty icon="layers" title="Compile the selected parameters first" action={<><PageLink page="flow/optimize" primary>Review &amp; compile parameters</PageLink><PageLink page="workloads/workflow">Open project workflow</PageLink></>}>
    Compile the selected fabric's saved parameters before final validation. Final validation reads a compiled revision, so there is nothing stable to evaluate here yet.
  </Empty>;
  const showingRun = view === 'analyze' && !!run;
  return <>
    {showingRun && run && !currentRun && <Notice tone="amber">This is historical evidence from {run.detail.revision_id}, not the finalized revision {project.detail.active_revision_id}. Launch a new evaluation to validate the final parameters.</Notice>}
    {showingRun && run
      ? <Section title="Final evaluation" actions={<>
        <Badge tone={run.detail.status === 'EVALUATED' ? 'green' : run.detail.status === 'FAILED' ? 'red' : 'amber'}>{run.detail.status.toLowerCase()}</Badge>
        <RunSelect revisions={project.detail.revisions ?? []} runs={project.detail.runs ?? []} value={run.detail.run_id} onChange={runId => { setTouched(true); loadRun(runId); }} ariaLabel="Selected run" activeRevisionId={project.detail.active_revision_id} />
        <Button onClick={() => { setTouched(true); setView('launch'); }}>New evaluation</Button>
        <PageLink page="flow/optimize">Refine parameters</PageLink>
      </>}>
        <RunReceipt run={run} />
      </Section>
      : <>
        {run && <div className="toolbar"><Button onClick={() => { setTouched(true); setView('analyze'); }}>Back to selected run</Button></div>}
        <LaunchEvaluation project={project} />
      </>}
    <FinalDelivery project={project} />
    <RtlStack project={project} />
    <div className="flow-delivery-link"><PageLink page="deliver/package">Open delivery &amp; RTL preview</PageLink></div>
    <Assumptions rows={[
      ['Evaluation plan', 'The gateway determines which analyses are READY for the active revision. Blocked analyses cannot be selected.'],
      ['Launch', 'Launching appends a real run using backend binaries on this host; confirmation is required.'],
      ['Result', 'After completion, the published run is selected for analysis.'],
      ['Qualification', 'A completed run does not imply requirement compliance, RTL qualification or hardware sign-off.'],
    ]} />
  </>;
}
