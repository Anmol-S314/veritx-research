import { lazy, Suspense, useEffect, useState } from 'react';
import { BASE_REVISION, HIDDEN_GROUPS, HIDDEN_PAGES, PAGE_ALIASES, PAGES, STORAGE_KEY, WORKSPACE_HOME, overlaps, pageFromHash, restoreState, type PageId } from './model';
// Keep unopened workspaces out of the desktop startup path.
const FlowViews = lazy(() => import('./FlowView').then(module => ({ default: module.FlowViews })));
const DesignViews = lazy(() => import('./DesignViews').then(module => ({ default: module.DesignViews })));
const ExploreViews = lazy(() => import('./ExploreViews').then(module => ({ default: module.ExploreViews })));
const OperationalViews = lazy(() => import('./OperationalViews').then(module => ({ default: module.OperationalViews })));
const WorkloadViews = lazy(() => import('./WorkloadViews').then(module => ({ default: module.WorkloadViews })));
const AnalysisViews = lazy(() => import('./AnalysisViews').then(module => ({ default: module.AnalysisViews })));
const AgentViews = lazy(() => import('./AgentViews').then(module => ({ default: module.AgentViews })));
import { Button, Dialog, Icon, downloadJson } from './ui';
import { ProjectProvider, useProject } from './project';
const AssistantDrawer = lazy(() => import('./AssistantDrawer').then(module => ({ default: module.AssistantDrawer })));
import { startPicking } from './contextSelection';
import { desktopGatewayBase } from './desktop';
import { gateway } from './gateway';
import { GatewayProjects } from './GatewayProjects';

function loadInitial() { try { return restoreState(localStorage.getItem(STORAGE_KEY)); } catch { return { ...restoreState(null), warning: 'Browser storage is unavailable. Edits work in memory; export your project before closing.' }; } }
// The live gateway exposes one resource behind several fixture-era routes. Navigation stops
// offering several names for the same view; the routes themselves still resolve so old links work.
const LIVE_ALIASES = new Set<string>([
  'workloads/library', 'workloads/editor', 'workloads/requirements', 'workloads/lowering',
  'analysis/missing', 'analysis/matrix',
  'analysis/metrics', 'analysis/topology', 'analysis/trace', 'analysis/comparison',
  'explore/progress', 'explore/results', 'explore/comparison', 'explore/adoption',
  'verify/overview',
  'deliver/readiness', 'deliver/configuration', 'deliver/job', 'deliver/artifacts',
]);

/** Deep links that resolve to the same live resource as a canonical page.
 *  Resolving them keeps the heading, breadcrumb and sidebar selection honest
 *  instead of presenting five names for one revision manifest. Fixture mode
 *  keeps the original routes: there the pages really are different. */
const LIVE_PAGE_ALIASES: Partial<Record<PageId, PageId>> = {
  'analysis/metrics': 'analysis/summary',
  'analysis/missing': 'analysis/matrix',
  'verify/overview': 'verify/evidence',
  'deliver/readiness': 'deliver/package',
  'deliver/configuration': 'deliver/package',
  'deliver/job': 'deliver/package',
  'deliver/artifacts': 'deliver/package',
};

/** One sentence under the title: what this page answers, and what it is not.
 *  Only pages whose purpose is not obvious from the title are listed. */
const PAGE_PURPOSE: Partial<Record<PageId, string>> = {
  'design/agent-map': 'What it answers: which agents have system-address windows, which instances they cover, and which interface controls are actually written to the compile request. It does not grant permissions or generate protocol adapters.',
  'analysis/fabric': 'What it answers: whether the declared addresses, routing shapes, port budget and island placement satisfy the static rules, and which controls reach the RTL preview. It is not a compiled certificate, simulation or hardware qualification.',
  'verify/evidence': 'What it answers: what the selected run produced and which files back it. It does not score, re-run or qualify hardware.',
  'verify/checks': 'What it answers: whether the backend’s own conservation and route checks passed for this run. A pass is not functional correctness or RTL qualification.',
  'verify/support': 'What it answers: which backends the gateway can lower and execute, and where their declared capability gaps are. Capability is not qualification of your design.',
  'verify/obligations': 'What it answers: which engineering questions are still open for this project and revision, and what evidence exists for each.',
  'deliver/package': 'What it answers: the revision’s artifact manifest — every artifact, its inputs and its proof. RTL preview lives in Flow · Finalize & RTL; nothing here generates hardware.',
};

/** One line that says what a whole workspace is for, shown under its name. */
const GROUP_PURPOSE: Record<string, string> = {
  Flow: 'Guided path: workload → catalog → fabric → parameters → RTL preview.',
  Design: 'Declared architecture: fabric, endpoints, mapping, addresses, domains.',
  'Workloads & Requirements': 'Workload intent, acceptance criteria and validation.',
  Analysis: 'Measured values and verdicts for the selected run.',
  Explore: 'Reference catalog, ablations and revision studies.',
  Verify: 'Evidence and backend checks for the selected run.',
  Deliver: 'Artifact manifest and proofs of the active revision.',
  'Optional agents': 'Model-assisted and runtime-connection surfaces; no tools or mutations.',
  Desktop: 'Projects, revisions and local settings.',
};

export function App() { return <ProjectProvider><Shell /></ProjectProvider>; }
function Shell() {
  const { project, run, evaluationJob, load, clear, listPhase, health } = useProject();
  const loaded = project.phase === 'loaded' ? project.data : null;
  const liveRun = run.phase === 'loaded' ? run.data : null;
  const liveJob = evaluationJob.job && !['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(evaluationJob.job.state) ? evaluationJob.job : null;
  const projectName = loaded?.detail.project.name ?? 'Falcon8_NoC_Gen2';
  const projectState = loaded ? `${loaded.detail.active_revision_id ?? 'no revision'} · live store` : `${'/local draft'}`;
  const [initial] = useState(loadInitial);
  const [state, setState] = useState(initial.state);
  const [storageBlocked, setStorageBlocked] = useState(!!initial.warning);
  const [notice, setNotice] = useState<string | null>(initial.warning);
  const [hash, setHash] = useState(window.location.hash || '#/flow/start');
  const [palette, setPalette] = useState(false), [query, setQuery] = useState(''), [drawer, setDrawer] = useState(false), [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantLoaded, setAssistantLoaded] = useState(false);
  const [lastPages, setLastPages] = useState<Record<string, PageId>>({ Flow: 'flow/start', Design: 'design/system', 'Workloads & Requirements': 'workloads/workflow', Analysis: 'analysis/summary', Explore: 'explore/fabric', Verify: 'verify/evidence', Deliver: 'deliver/package', Desktop: 'shared/projects' });
  const requestedPage = pageFromHash(hash);
  const page = (() => {
    const canonical = requestedPage && loaded ? LIVE_PAGE_ALIASES[requestedPage.id] : undefined;
    return canonical ? PAGES.find(entry => entry.id === canonical) ?? requestedPage : requestedPage;
  })();
  const activePageId = page ? (PAGE_ALIASES[page.id] ?? page.id) : undefined;
  const group = page?.group ?? 'Design';
  function navigate(id: PageId) { window.location.hash = `/${id}`; setPalette(false); }
  useEffect(() => {
    if (!window.location.hash) window.history.replaceState(null, '', '#/flow/start');
    else {
      const root = window.location.hash.replace(/^#\/?/, '');
      if (WORKSPACE_HOME[root]) window.history.replaceState(null, '', `#/${WORKSPACE_HOME[root]}`);
    }
    const onHash = () => { setHash(window.location.hash); setDrawer(false); };
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setQuery(''); setPalette(v => !v); } };
    window.addEventListener('hashchange', onHash); window.addEventListener('keydown', onKey);
    return () => { window.removeEventListener('hashchange', onHash); window.removeEventListener('keydown', onKey); };
  }, []);
  useEffect(() => {
    if (!page) return;
    const canonical = PAGE_ALIASES[page.id] ?? page.id;
    // A hidden live alias is a deep link, not the workspace's landing page.
    if (!(loaded && LIVE_ALIASES.has(canonical))) {
      setLastPages(p => p[page.group] === canonical ? p : ({ ...p, [page.group]: canonical }));
    }
    document.title = `${page.short} · Srota Studio prototype`;
  }, [page, loaded]);
  useEffect(() => {
    if (storageBlocked) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
    catch { setStorageBlocked(true); setNotice('Could not save browser state. Current edits remain in memory; export a project backup.'); }
  }, [state, storageBlocked]);
  const shared = { state, setState, notify: (message: string) => setNotice(message), navigate };
  const nav = PAGES.filter(p => p.group === group && !HIDDEN_PAGES.has(p.id) && !(loaded && LIVE_ALIASES.has(p.id)));
  const conflicts = overlaps(state.draft.regions).length;
  // Desktop startup must not present the browser's illustrative fixture as a live project.
  if (desktopGatewayBase && !loaded) return <main className="view-main flow-page" id="main-workspace" tabIndex={-1} style={{ height: '100dvh' }}>
    <section className="section"><h1>Srota Studio projects</h1><p>Choose or create a project in the desktop backend to open the live workspace. This desktop has its own local project store; existing browser/backend projects are not imported automatically.</p></section>
    <GatewayProjects />
  </main>;
  return <div className={`app-shell${assistantOpen ? ' assistant-open' : ''}`}><a className="skip-link" href="#main-workspace" onClick={e => { e.preventDefault(); document.getElementById('main-workspace')?.focus(); }}>Skip to workspace</a><header className="global-header"><a href="#/flow/start" className="brand" aria-label="Srota Studio home"><span className="brand-mark"><Icon name="network" size={21} /></span><strong>Srota <span>Studio</span></strong></a><span className="header-divider" /><a href="#/shared/projects" className="project-switch" title={loaded ? "Gateway project" : "Local illustrative project"}><Icon name="folder" /><span>{projectName}</span></a><span className="header-revision mono">{loaded ? projectState : `${state.draft.id} · edit ${state.draft.revision}`}</span><div className="header-right"><button className="command-button" onClick={() => { setQuery(''); setPalette(true); }}><Icon name="search" /><span>Find a view</span><kbd>Ctrl K</kbd></button><button className="icon-button" onClick={() => { setAssistantLoaded(true); setAssistantOpen(true); startPicking(); }} aria-label="Pick context for the assistant" title="Pick context (Ctrl+I)"><Icon name="target" /></button><button className="icon-button" onClick={() => { setAssistantLoaded(true); setAssistantOpen(value => !value); }} aria-label="Contextual assistant" aria-expanded={assistantOpen} aria-controls="assistant-drawer" title="Contextual assistant"><Icon name="assistant" /></button><a className="icon-button" href="#/shared/environment" aria-label="Environment and local settings"><Icon name="settings" /></a></div></header><nav className="global-nav" aria-label="Workspaces">{['Flow', 'Design', 'Workloads & Requirements', 'Analysis', 'Explore', 'Verify', 'Deliver'].map(name => lastPages[name] ? <a key={name} href={`#/${lastPages[name]}`} aria-current={group === name ? 'page' : undefined}>{name}</a> : <button key={name} disabled title="No HTML exports supplied for this workspace yet">{name}<span className="pending-label">Not imported</span></button>)}<a href={`#/${lastPages.Desktop}`} className="desktop-link" aria-current={group === 'Desktop' ? 'page' : undefined}>Project & settings</a></nav><div className="workspace-shell" data-group={group}><aside className="view-sidebar"><div className="sidebar-heading"><Icon name={group === 'Flow' ? 'branch' : group === 'Explore' ? 'chart' : group === 'Verify' ? 'shield' : group === 'Deliver' ? 'download' : 'layers'} /><h2>{group}</h2></div><p className="sidebar-group-purpose">{GROUP_PURPOSE[group]}</p><nav aria-label={`${group} views`}>{nav.map(p => <a key={p.id} href={`#/${p.id}`} aria-current={activePageId === p.id ? 'page' : undefined} title={PAGE_PURPOSE[p.id]}><span>{p.short}</span>{activePageId === p.id && <Icon name="arrow" size={14} />}</a>)}</nav><div className="sidebar-context"><h3>Working context</h3><dl>{loaded ? <><dt>Loaded project</dt><dd>{loaded.detail.project.name}</dd><dt>Revision</dt><dd className="mono">{loaded.detail.active_revision_id ?? "none"}</dd><dt>Declared fabric</dt><dd>{loaded.topology ? `${loaded.topology.counts?.routers ?? 0} routers · ${loaded.topology.counts?.channels ?? 0} channels${(loaded.topology.counts?.shared_links ?? 0) > 0 ? ` · ${loaded.topology.counts?.shared_links} shared wires` : ''}` : "no topology document"}</dd><dt>Endpoint seats</dt><dd>{loaded.topology ? `${loaded.topology.counts?.endpoints ?? 0} declared` : "none"}</dd><dt>Declared workload</dt><dd>{loaded.request?.workload ? `${loaded.request.workload.model_name || loaded.detail.draft?.workload_id || 'unnamed'} · TP${loaded.request.workload.tp ?? 1}${loaded.request.workload.ep && loaded.request.workload.ep > 1 ? ` EP${loaded.request.workload.ep}` : ''}` : "no workload block"}</dd><dt>Compute stages</dt><dd>{loaded.request?.compute?.stages?.length ? `${loaded.request.compute.stages.length} declared` : "none"}</dd></> : <><dt>Topology intent</dt><dd>4×4 mesh · 16 routers</dd><dt>Endpoints in sample</dt><dd>{state.draft.endpoints.length} · explicit attachments</dd><dt>Network clock assumption</dt><dd>1.4 GHz · 128-bit links</dd><dt>Historical inputs</dt><dd className="mono">{BASE_REVISION} / w12 / r5</dd></>}</dl><p>{loaded ? "Gateway project · edits require save and compile." : "No local agent runtime or RTL generator is connected."}</p></div><a className="sidebar-bottom" href="#/shared/projects"><Icon name="branch" />{state.archives.length} preserved local drafts</a></aside><main className="workspace" id="main-workspace" tabIndex={-1}>{page ? <><div className="page-heading"><div><span className="breadcrumb">{projectName} / {group}</span><h1>{page.title}</h1>{PAGE_PURPOSE[page.id] && <p className="page-purpose">{PAGE_PURPOSE[page.id]}</p>}</div></div>{notice && <div className="status-message" role="status"><Icon name="info" /><span>{notice}</span>{storageBlocked ? <><Button onClick={() => downloadJson('srota-preview-recovery-backup.json', state)}>Export current preview</Button><Button onClick={() => { setStorageBlocked(false); setNotice('New local preview accepted for browser storage.'); }}>Accept current preview for saving</Button></> : <button className="icon-button" aria-label="Dismiss message" onClick={() => setNotice(null)}><Icon name="close" /></button>}</div>}<div className="page-content" key={requestedPage?.id ?? page.id}><Suspense fallback={<div className="view-main" role="status">Loading workspace…</div>}>{(project.phase === 'loading' || project.phase === 'error') && page.id !== 'shared/projects' ? <div className="view-main"><p role={project.phase === 'error' ? 'alert' : 'status'}>{project.phase === 'loading' ? `Loading project ${project.projectId}…` : `Project unavailable: ${project.reason}`}</p>{project.phase === 'error' && <Button onClick={() => load(project.projectId)}>Retry project</Button>}<Button onClick={clear}>Use sample project</Button></div> : group === 'Flow' ? <FlowViews {...shared} page={page.id} /> : group === 'Design' ? <DesignViews {...shared} page={page.id} /> : group === 'Explore' ? <ExploreViews {...shared} page={page.id} /> : group === 'Analysis' ? <AnalysisViews {...shared} page={page.id} /> : group === 'Workloads & Requirements' ? <WorkloadViews {...shared} page={page.id} /> : group === 'Optional agents' ? <AgentViews {...shared} page={page.id} /> : <OperationalViews {...shared} page={page.id} />}</Suspense></div></> : <div className="view-main"><h1>View not found</h1><p>This route has not been imported. Your draft is unchanged.</p><Button onClick={() => navigate('design/system')}>Return to Design</Button></div>}</main></div><footer className="status-bar"><button onClick={() => setDrawer(v => !v)} aria-expanded={drawer} aria-controls="jobs-drawer"><Icon name="terminal" /><span>Jobs & activity</span><span className="status-count">{liveJob ? `1 ${liveJob.state.toLowerCase()}` : "0 tracked evaluations"}</span></button><button onClick={() => navigate('shared/jobs')}><Icon name="warning" /><span>{loaded ? 'Address checks not run' : `${conflicts} address overlap${conflicts === 1 ? '' : 's'}`}</span></button><span className="status-divider" /><span>{storageBlocked ? 'Memory-only · export edits' : loaded ? `Gateway ${gateway.base} · ${listPhase === 'offline' ? 'unreachable' : health ? 'connected' : 'not checked'}` : 'Sample project · local browser state'}</span><span className="status-spacer" /><span>{PAGES.length} imported views</span><span className="status-divider" /><span>No hardware qualification</span></footer>{drawer && <section className="jobs-drawer" id="jobs-drawer" aria-label="Local jobs and activity"><div className="section-heading"><h2>{liveJob ? "Gateway job & activity" : "Activity"}</h2><div className="actions"><Button onClick={() => navigate('shared/jobs')}>Open full view</Button><button className="icon-button" aria-label="Close jobs drawer" onClick={() => setDrawer(false)}><Icon name="close" /></button></div></div><p>{liveJob ? <>Gateway job <span className="mono">{liveJob.job_id}</span> is <strong>{liveJob.state.toLowerCase()}</strong> on revision <span className="mono">{liveJob.revision_id}</span>. Progress is the gateway's job state, not a percentage.</> : "No evaluation job is tracked."}</p><ol className="activity-list">{state.events.slice(0, 6).map((e, i) => <li key={`${i}-${e}`}>{e}</li>)}</ol></section>}{palette && <Dialog title="Find a workspace view" onClose={() => setPalette(false)}><label className="search-field"><Icon name="search" /><input autoFocus aria-label="Search views" placeholder={`Search the ${PAGES.length} imported views…`} value={query} onChange={e => setQuery(e.target.value)} /></label><div className="command-results">{PAGES.filter(p => !HIDDEN_PAGES.has(p.id) && !HIDDEN_GROUPS.has(p.group) && !(loaded && LIVE_ALIASES.has(p.id)) && `${p.group} ${p.title}`.toLowerCase().includes(query.toLowerCase())).map(p => <button key={p.id} onClick={() => navigate(p.id)}><span>{p.title}</span><small>{p.group}</small><Icon name="arrow" size={14} /></button>)}</div></Dialog>}{assistantLoaded && <Suspense fallback={null}><AssistantDrawer open={assistantOpen} onOpen={() => { setAssistantLoaded(true); setAssistantOpen(true); }} onClose={() => setAssistantOpen(false)} page={page ? { id: page.id, title: page.title, short: page.short, group: page.group } : null} project={loaded} run={liveRun} navigate={navigate} /></Suspense>}</div>;
}
