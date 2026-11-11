import { useEffect, useMemo, useRef, useState } from 'react';
import { gateway, gatewayReason, type CatalogAnalysis, type CatalogEvaluation, type CatalogPlan, type CatalogRow } from './gateway';
import { useProject, type LoadedProject } from './project';
import { Assumptions, Badge, Button, Notice, PageLink, type ViewProps } from './ui';
import { JobEvents } from './JobEvents';
import { InteractiveScatter } from './InteractiveScatter';
import { catalogFacts, catalogProfiles, catalogTradeoffPoints } from './catalogRecommendation';
import { catalogPerClassMetrics, rtlVerdict } from './catalogMetrics';
import { CatalogInspector } from './CatalogInspector';
import './analysisCharts.css';
import './catalogCampaign.css';

export { catalogPerClassMetrics, configSummary, metricDimensions, rtlVerdict } from './catalogMetrics';

const terminal = (state: string) => ['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(state);
const tone = (state: string): 'green' | 'red' | 'amber' | 'blue' => state === 'EVALUATED' || state === 'COMPLETED' ? 'green' : ['FAILED', 'EVIDENCE_INVALID'].includes(state) ? 'red' : ['QUEUED', 'RUNNING', 'PREPARING'].includes(state) ? 'blue' : 'amber';

export function AnalysisCell({ analysis, compact = false }: { analysis?: CatalogAnalysis; compact?: boolean }) {
  if (!analysis) return <span className="muted">Not started</span>;
  const metric = analysis.normalized_metrics?.find(m => ['completion_cycles', 'system_makespan_cycles'].includes(m.key) && !m.dimensions?.length);
  const perClass = catalogPerClassMetrics(analysis);
  return <><span className="catalog-analysis-summary"><Badge tone={tone(analysis.status)}>{analysis.status.replaceAll('_', ' ').toLowerCase()}</Badge>
    {analysis.status === 'EVALUATED' && metric && typeof metric.value === 'number' && <strong>{metric.value.toLocaleString()} <small>{metric.unit}</small></strong>}</span>
    {!compact && analysis.status === 'EVALUATED' && perClass.length > 0 && <details className="catalog-per-class">
      <summary>Per traffic class · {perClass.length}</summary>
      <div className="table-scroll"><table><thead><tr><th>Traffic class</th><th>Metric</th><th className="numeric">Value</th><th>Unit</th></tr></thead><tbody>
        {perClass.map(group => group.metrics.map((row, index) => <tr key={`${group.trafficClass}:${row.key}`}>
          {index === 0 && <th scope="rowgroup" rowSpan={group.metrics.length}>{group.trafficClass}</th>}
          <td>{row.key.replaceAll('_', ' ')}</td><td className="numeric">{row.value === null ? 'Unavailable' : row.value.toLocaleString()}</td><td>{row.unit || '—'}</td>
        </tr>))}
      </tbody></table></div>
    </details>}
    {!compact && analysis.reason && <p className="meta-line">{analysis.reason}</p>}</>;
}

function ProfileChoice({ profile, onPick }: {
  profile: ReturnType<typeof catalogProfiles>[number]; onPick: (id: string) => void;
}) {
  const winner = profile.winner;
  return <button type="button" className="catalog-profile" title={`${profile.description} ${profile.reason}`}
    data-profile={profile.id} disabled={!winner} onClick={() => winner && onPick(winner.id)}>
    <span>{profile.label}</span><strong>{winner ? winner.label : profile.tie ? 'No decisive fabric' : 'No winner'}</strong>
    <small>{winner && profile.id === 'network' && winner.network != null ? `${winner.network.toLocaleString()} cycles` : winner && profile.id === 'system' && winner.system != null ? `${winner.system.toLocaleString()} cycles` : winner ? 'Open measured result' : profile.reason}</small>
  </button>;
}

function ComparisonValue({ analysis }: { analysis?: CatalogAnalysis }) {
  const metric = analysis?.status === 'EVALUATED' ? analysis.normalized_metrics?.find(row => ['completion_cycles', 'system_makespan_cycles'].includes(row.key) && !row.dimensions?.length) : null;
  return <><strong>{metric?.value != null ? metric.value.toLocaleString() : '—'}</strong>
    <small>{analysis?.status === 'EVALUATED' ? metric?.value != null ? 'cycles' : 'Not recorded' : analysis?.status.replaceAll('_', ' ').toLowerCase() ?? 'Not started'}</small></>;
}

export function CatalogCampaign({ project, navigate, notify }: ViewProps & { project: LoadedProject }) {
  const { reload } = useProject();
  const id = project.detail.project.project_id;
  const key = `srota-catalog:${id}`;
  const [plan, setPlan] = useState<CatalogPlan | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [planError, setPlanError] = useState('');
  const [jobId, setJobId] = useState(() => { try { return sessionStorage.getItem(key) ?? ''; } catch { return ''; } });
  const [view, setView] = useState<CatalogEvaluation | null>(null);
  const [viewToken, setViewToken] = useState<string | undefined>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [approved, setApproved] = useState(false);
  const [acknowledge, setAcknowledge] = useState(false);
  const [picked, setPicked] = useState('');
  const [comparisonView, setComparisonView] = useState<'table' | 'plot'>('table');
  const reviewRef = useRef<HTMLDivElement>(null);
  const reviewTrigger = useRef<HTMLElement | null>(null);
  const revealReview = () => {
    const panel = reviewRef.current;
    const comparison = panel?.previousElementSibling;
    if (panel && comparison && panel.getBoundingClientRect().top >= comparison.getBoundingClientRect().bottom - 1) panel.scrollIntoView({ block: 'nearest' });
  };
  useEffect(() => {
    if (!picked) return;
    revealReview();
    if (comparisonView === 'table') document.querySelector(`[data-catalog-row="${CSS.escape(picked)}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [picked, comparisonView]);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    gateway.catalogPlan(id).then(value => {
      if (!live) return;
      setPlan(value); setSelected(value.topologies.map(row => row.topology_id)); setPlanError(''); setApproved(false);
    }).catch(caught => { if (live) setPlanError(gatewayReason(caught)); });
    gateway.projectJobs(id, 'CATALOG_EVALUATION').then(value => {
      if (live) setJobId(current => current || value.jobs?.[0]?.job_id || '');
    }).catch(() => { /* A missing job history does not hide the launch panel. */ });
    return () => { live = false; };
  }, [id, project.draftMeta?.revisionToken, retry]);
  useEffect(() => {
    let live = true, timer: number | undefined;
    setView(null); setViewToken(undefined); setError(''); setAcknowledge(false);
    if (!jobId) return;
    try { sessionStorage.setItem(key, jobId); } catch { /* Optional recovery. */ }
    const read = async () => {
      try {
        const value = await gateway.catalogEvaluation(id, jobId);
        if (!live) return;
        setView(value); setViewToken(project.draftMeta?.revisionToken); setError('');
        if (!terminal(value.job.state)) timer = window.setTimeout(read, 2000);
      } catch (caught) { if (live) setError(gatewayReason(caught)); }
    };
    void read();
    return () => { live = false; window.clearTimeout(timer); };
  }, [id, jobId, key, retry, project.draftMeta?.revisionToken]);
  const running = !!jobId && (!view || !terminal(view.job.state)) && !error;
  const rows = view?.rows.length ? view.rows : [];
  const facts = useMemo(() => catalogFacts(rows), [rows]);
  const profiles = useMemo(() => catalogProfiles(facts), [facts]);
  const points = useMemo(() => catalogTradeoffPoints(facts), [facts]);
  const measuredNetwork = facts.filter(fact => typeof fact.network === 'number').sort((a, b) => a.network! - b.network!);
  const measuredSystem = facts.filter(fact => typeof fact.system === 'number').sort((a, b) => a.system! - b.system!);
  const networkBest = measuredNetwork[0] ?? null;
  const systemBest = measuredSystem[0] ?? null;
  const networkTies = networkBest ? measuredNetwork.filter(fact => fact.network === networkBest.network).length : 0;
  const systemTies = systemBest ? measuredSystem.filter(fact => fact.system === systemBest.system).length : 0;
  const selectableCount = facts.filter(fact => fact.selectable).length;
  const pickedRow: CatalogRow | undefined = rows.find(row => row.topology_id === picked);
  const currentEvidence = !!view && !!project.draftMeta?.revisionToken && viewToken === project.draftMeta.revisionToken;
  const configuration = view?.configuration ?? plan?.configuration ?? null;
  const configMismatch = rows.filter(row => row.config && row.config.matched === false);
  const review = (topologyId: string) => {
    if (topologyId) {
      reviewTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (topologyId === picked) {
        revealReview();
        reviewRef.current?.querySelector<HTMLHeadingElement>('h2')?.focus({ preventScroll: true });
      }
    } else {
      if (reviewTrigger.current?.isConnected) reviewTrigger.current.focus();
      else reviewRef.current?.previousElementSibling?.querySelector<HTMLButtonElement>('button')?.focus();
    }
    if (topologyId !== picked) setAcknowledge(false);
    setPicked(topologyId);
  };
  const launch = async () => {
    if (!plan || !approved || !selected.length || busy || running) return;
    setBusy('launch'); setError('');
    try {
      const job = await gateway.launchCatalog(id, plan.draft_design_hash, selected);
      setJobId(job.job_id); setView(null); setApproved(false); setPicked('');
    } catch (caught) { setError(gatewayReason(caught)); }
    finally { setBusy(''); }
  };
  const choose = async (row: CatalogRow) => {
    const token = project.draftMeta?.revisionToken;
    if (!jobId || !row.candidate_id || !row.selectable || !token || !currentEvidence || busy || (row.requires_backend_ack && !acknowledge)) return;
    setBusy(row.candidate_id); setError('');
    try {
      await gateway.selectCatalogFabric(id, jobId, row.candidate_id, token, acknowledge);
      notify(`${row.label} selected from the measured catalog. Refine this fabric's parameters next.`);
      reload(); navigate('flow/optimize');
    } catch (caught) { setError(gatewayReason(caught)); }
    finally { setBusy(''); }
  };
  return <div className="catalog-campaign">
    {planError && <Notice tone="red">{planError}<div className="toolbar"><Button onClick={() => setRetry(n => n + 1)}>Retry workload plan</Button></div></Notice>}
    {!project.draftMeta?.revisionToken && rows.length > 0 && <Notice tone="amber">The project draft version could not be read. Reload the project before selecting a fabric for refinement.</Notice>}
    {!plan && !planError && <p role="status">Reading saved workload intent…</p>}
    {plan && <details className="catalog-setup" key={rows.length ? 'results' : 'setup'} open={!rows.length}>
      <summary><span role="heading" aria-level={2}>{rows.length ? 'Evaluation setup' : 'Choose fabrics to evaluate'}</span><small>{plan.participant_count} participants · {plan.operation_count} {plan.operation_count === 1 ? 'operation' : 'operations'} · {selected.length} of {plan.topologies.length} selected</small></summary>
      <div className="catalog-setup-body">
      {!rows.length && <div className="stat-strip catalog-setup-stats">
        <div className="stat"><span>Saved workload</span><strong>{project.request?.workload?.model_name || project.detail.draft?.workload_id || project.detail.project.name}</strong><small>Frozen for every evaluated fabric</small></div>
        <div className="stat"><span>Participants</span><strong>{plan.participant_count}</strong><small>Declared workload participants</small></div>
        <div className="stat"><span>Operations</span><strong>{plan.operation_count}</strong><small>{plan.operation_count === 1 ? 'Declared operation' : 'Declared operations'}</small></div>
        <div className="stat"><span>Compute stages</span><strong>{plan.compute_stages || 'None'}</strong><small>{plan.compute_stages ? 'Declared system timing' : 'ASTRA-SIM communication only'}</small></div>
      </div>}
      <fieldset className="draft-controls" disabled={running || !!busy}>
        <legend>Fabrics to evaluate</legend>
        <div className="actions">{plan.topologies.map(row => <label className="check-chip" key={row.topology_id}>
          <input type="checkbox" checked={selected.includes(row.topology_id)} onChange={event => { setSelected(ids => event.target.checked ? [...ids, row.topology_id] : ids.filter(value => value !== row.topology_id)); setApproved(false); }} />{row.label}
        </label>)}</div>
        <label className="check-row"><input type="checkbox" checked={approved} onChange={event => setApproved(event.target.checked)} />Generate traffic from this saved workload and run BookSim + ASTRA-SIM for the selected fabrics.</label>
      </fieldset>
      {!rows.length && <p className="fabric-card-note"><strong>No fabric is ranked yet.</strong> Network, System, Balanced and Best evidenced each rank one declared objective after the run. Refusals and failures stay visible rather than becoming zeros.</p>}
      {!plan.compute_stages && <Notice tone="amber">No compute stages are declared. ASTRA-SIM can model communication only where supported; these results are not full model inference latency. <PageLink page="flow/tune">Add compute timing</PageLink></Notice>}
      <div className="toolbar flow-launch-actions"><PageLink page="flow/tune">Back · Workload intent</PageLink>
        <span className="flow-launch-hint" id="catalog-launch-hint">{!selected.length ? 'Select at least one fabric.' : !approved ? 'Confirm the traffic and evaluation scope above.' : 'Ready to generate the workload traffic and measure the selected fabrics.'}</span>
        <Button primary disabled={!approved || !selected.length || !!busy || running} aria-describedby="catalog-launch-hint" onClick={launch}>{busy === 'launch' ? 'Submitting…' : 'Generate trace & run catalog'}</Button></div>
      </div>
    </details>}
    {view && <div className="catalog-run-bar" role="status">
      <Badge tone={tone(view.job.state)}>{view.job.state.toLowerCase()}</Badge>
      <span>{rows.filter(row => !['QUEUED', 'RUNNING'].includes(row.status)).length} / {rows.length || selected.length} fabrics</span>
      <span className="catalog-campaign-scope" title={project.request?.workload?.model_name || project.detail.project.name}>{project.request?.workload?.model_name || project.detail.project.name}</span>
      <span className="toolbar-end">
        {running && <Button disabled={!view.job.cancellable} onClick={() => gateway.cancelJob(jobId).then(() => setRetry(n => n + 1)).catch(caught => setError(gatewayReason(caught)))}>Cancel catalog run</Button>}
        <Button onClick={() => setRetry(n => n + 1)}>Refresh results</Button>
        {plan?.selection && <PageLink page="flow/optimize" primary>Refine {plan.selection.label}</PageLink>}
      </span>
      {view.job.error_message && <Notice tone="red">{view.job.error_message}</Notice>}
      {view.stale && <Notice tone="amber">{view.selection ? `These measurements predate the current saved draft. The chosen ${view.selection.label} selection is preserved, but changed parameters need a new evaluation.` : 'The saved workload or parameters changed. These results remain inspectable, but cannot be selected for the changed design.'}</Notice>}
    </div>}

    {rows.length > 0 && <>
      <div className="stat-strip catalog-summary">
        <div className="stat"><span>Chosen fabric</span><strong>{view?.selection?.label ?? 'Not chosen'}</strong><small>{view?.selection ? 'Selected for parameter refinement' : 'Choose a measured result below'}</small></div>
        <div className="stat"><span>Lowest network completion</span><strong>{networkBest?.network != null ? `${networkBest.network.toLocaleString()} cyc` : 'No result'}</strong><small>{networkBest ? `${networkBest.label}${networkTies > 1 ? ` · ${networkTies}-way tie` : ''} · BookSim` : 'No comparable result'}</small></div>
        <div className="stat"><span>Lowest system makespan</span><strong>{systemBest?.system != null ? `${systemBest.system.toLocaleString()} cyc` : 'No result'}</strong><small>{systemBest ? `${systemBest.label}${systemTies > 1 ? ` · ${systemTies}-way tie` : ''} · ASTRA-SIM` : 'No comparable result'}</small></div>
        <div className="stat"><span>Selectable</span><strong>{selectableCount} / {facts.length}</strong><small>Requirements and evidence checked</small></div>
      </div>
      {configMismatch.length > 0 && <Notice tone="amber">{configMismatch.length} fabrics report different controls and are not directly comparable: {configMismatch.map(row => row.label).join(', ')}.</Notice>}
      <div className="catalog-profiles" role="group" aria-label="Recommended fabrics">
        {profiles.map(profile => <ProfileChoice key={profile.id} profile={profile} onPick={review} />)}
      </div>
      <div className="catalog-results-heading"><div><h2>Fabric comparison</h2><span>{rows.length} measured · {selectableCount} selectable</span></div><span className="catalog-results-note">Chosen fabric marked in the table</span></div>
      <div className={`catalog-workbench${pickedRow ? '' : ' no-selection'}`}>
        <section className="catalog-comparison" aria-label="Fabric comparison">
          <div className="catalog-comparison-toolbar"><div className="segmented" role="group" aria-label="Comparison view">
            <button type="button" aria-pressed={comparisonView === 'table'} className={comparisonView === 'table' ? 'active' : ''} onClick={() => setComparisonView('table')}>All fabrics</button>
            <button type="button" aria-pressed={comparisonView === 'plot'} className={comparisonView === 'plot' ? 'active' : ''} onClick={() => setComparisonView('plot')}>Trade-off plot</button>
          </div><small>Lower cycles is better</small></div>
          {comparisonView === 'table' ? <div className="catalog-comparison-scroll" tabIndex={0} role="region" aria-label="Measured fabric comparison table">
            <table className="catalog-results-table"><thead><tr><th>Fabric</th><th className="numeric">Network</th><th className="numeric">System</th><th>Requirements</th><th>RTL preview</th><th>Details</th></tr></thead><tbody>
              {rows.map(row => {
                const rtl = rtlVerdict(row.rtl_support);
                const chosen = !!row.candidate_id && view?.selection?.candidate_id === row.candidate_id;
                return <tr key={row.topology_id} data-catalog-row={row.topology_id} className={picked === row.topology_id ? 'selected' : ''}>
                  <th scope="row"><span>{row.label}</span>{chosen && <span className="catalog-chosen">Chosen</span>}
                    <small>{row.fabric?.router_count != null ? `${row.fabric.router_count} routers · ` : ''}{row.vc_count != null ? `${row.vc_count} VC${row.vc_count === 1 ? '' : 's'}` : 'VCs not recorded'}</small>
                    {row.config?.matched === false && <small className="catalog-row-warning">Config differs</small>}
                  </th>
                  <td className="numeric"><ComparisonValue analysis={row.analyses?.find(a => a.question === 'NETWORK_COMPLETION')} /></td>
                  <td className="numeric"><ComparisonValue analysis={row.analyses?.find(a => a.question === 'SYSTEM_MAKESPAN')} /></td>
                  <td><span className={row.requirements_pass === true ? 'catalog-row-pass' : row.requirements_pass === false ? 'catalog-row-warning' : ''}>{row.requirements_pass === true ? 'Satisfied' : row.requirements_pass === false ? 'Not satisfied' : 'Not established'}</span></td>
                  <td><span title={rtl.detail}>{row.rtl_support ? row.rtl_support.supported ? 'Available' : 'Unavailable' : 'Not recorded'}</span></td>
                  <td><button type="button" className="text-button" aria-pressed={picked === row.topology_id} aria-controls="catalog-fabric-detail" onClick={() => review(row.topology_id)} aria-label={`Inspect ${row.label}`}>Inspect</button></td>
                </tr>;
              })}
            </tbody></table>
          </div> : <div className="catalog-comparison-plot"><h3>Measured trade-off</h3>
            {points.length > 1 ? <InteractiveScatter points={points} selected={picked || null} onSelect={review}
              xLabel="Network completion (cycles) · lower is better" yLabel="System makespan (cycles) · lower is better"
              label="Measured fabric trade-off between network completion and system makespan" /> : <p>Both scopes are measured for {points.length === 1 ? 'one fabric only' : 'no fabric'}. Other results remain in the table.</p>}
            <p className="meta-line">Only requirements-satisfying fabrics with both measurements are plotted.</p>
          </div>}
          <div className="catalog-comparison-footnote"><span>BookSim network · ASTRA-SIM system</span><span>Inspect a fabric to see every recorded metric.</span></div>
        </section>
        {pickedRow && <div className="catalog-inspector-slot" ref={reviewRef} tabIndex={-1}>
          <CatalogInspector row={{ ...pickedRow, selectable: pickedRow.selectable && currentEvidence }} configuration={configuration} workloadId={view?.workload_id} projectId={id} jobId={jobId} busy={busy}
            acknowledge={acknowledge} onAcknowledge={setAcknowledge} onChoose={() => choose(pickedRow)} onClose={() => review('')}
            chosen={!!pickedRow.candidate_id && view?.selection?.candidate_id === pickedRow.candidate_id} error={error} onRetry={() => setRetry(n => n + 1)} />
        </div>}
      </div>
    </>}
    {error && !pickedRow && <Notice tone="red">{error}<Button onClick={() => setRetry(n => n + 1)}>Retry status</Button></Notice>}
    <div className="catalog-utilities">
      {jobId && <details><summary>Job log &amp; events</summary><JobEvents jobId={jobId} state={view?.job.state} /></details>}
      {rows.length > 0 && <details><summary>Related analysis &amp; downloads</summary><nav aria-label="Related catalog analysis">
        <PageLink page="analysis/summary">Analysis · Summary</PageLink><PageLink page="analysis/curves">Analysis · Curves &amp; Pareto</PageLink>
        <PageLink page="verify/checks">Verify · Checks</PageLink><PageLink page="verify/evidence">Evidence detail</PageLink>
        <PageLink page="design/fabric-topology">Design · Fabric topology</PageLink><PageLink page="flow/run">Flow · Finalize &amp; RTL</PageLink>
        <PageLink page="explore/fabric-search">Reference catalog</PageLink><PageLink page="explore/fabric-ablations">Fabric ablations</PageLink>
        {view?.artifacts.some(file => file.path === 'workload.json') && <a href={gateway.catalogArtifactUrl(id, jobId, 'workload.json')} download>Download generated workload graph</a>}
      </nav><p>Run analysis needs a compiled revision with an evaluation run. Repository references are not this project's measurements.</p></details>}
    </div>
    <Assumptions rows={[
      ['Workload', 'The saved high-level intent is frozen for this job. Collective payloads, declared initiator profiles, compute timing, participants, agents and requirements stay unchanged across fabrics. No model or repository reference trace is needed for this path.'],
      ['Configuration', 'Every row shares one NoC-controls identity (buffer depth, link width, arbitration) and one workload identity. Routing law is derived per topology and named in each row; a row whose configuration identity differs is flagged as not directly comparable.'],
      ['RTL preview', 'Feasibility is predicted from a topology-only compile before selection. It means the one product emitter can produce preview RTL inside its 2–64 router, ≤2-VC, point-to-point slice — never that final simulation-equivalent RTL exists.'],
      ['Research RTL', 'M5 research Verilog presence is reported in the inspector / Flow · Finalize & RTL (flow/run) and never upgrades the product preview.'],
      ['Generated inputs', 'The adapters map the same workload to each topology, then generate BookSim packet traces and ASTRA-SIM execution graphs. A packet trace is not an ASTRA execution graph.'],
      ['Profiles', 'Each profile ranks one declared objective. Network completion is BookSim-only; system makespan includes declared compute stages. Balanced sums ranks over both scopes rather than inventing a fused score. A refused or requirement-failing fabric never wins.'],
      ['Selection', 'Only a completed, evidence-verified network result satisfying declared requirements can be chosen. Missing backend coverage requires explicit acknowledgment. The workload is never resized.'],
      ['Not established', 'A completed catalog run is not requirement compliance, RTL qualification or hardware sign-off.'],
    ]} />
  </div>;
}
