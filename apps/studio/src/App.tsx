import { useEffect, useState, type ReactElement } from 'react';
import { ContextHeader, Link, StudioProvider, useStudio } from './studio';
import { navigate, parseRoute, usePathname } from './router';
import {
  Overview, ProjectPicker, RunDetail, Runs, Trust, Workload,
} from './pages';
import { Compile, Design, Review, RevisionCompileGroup, Verify } from './pages/design';
import { Compare, Optimize } from './pages/optimize';
import { Serving } from './pages/serving';
import { Performance } from './pages/performance';
import { Synthesize } from './pages/synthesize';
import { Candidates } from './pages/candidates';
import { Reproduce } from './pages/reproduce';
import { CapabilitiesPage } from './pages/capabilities';
import { AgentMatrix } from './pages/agents';
import Loom from './pages/loom';
import { ImplementationLabPage } from './pages/implementation-lab';
import { Evidence, ValidationLab } from './pages/evidence';
import Evaluate from './pages/evaluate';
import OfflineDemo from './pages/offline';
import BrandMark from './components/BrandMark';

type Theme = 'dark' | 'light';

export interface NavItem {
  section: string;
  label: string;
  detail?: string;
  aliases?: string[];
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Existing destinations organized by the object or evidence they expose.
 * A router-control shortcut opens Design's Fabric inspector; it is not a new editor. */
export const NAV_GROUPS: NavGroup[] = [
  { label: 'Architecture', items: [
    { section: 'overview', label: 'Overview' },
    { section: 'design', label: 'System design' },
    { section: 'loom', detail: 'graph', label: 'System graph' },
    { section: 'loom', detail: 'catalog', label: 'IP kinds in use' },
    { section: 'agents', label: 'Agent editor' },
    { section: 'loom', detail: 'agents', label: 'Agent matrix' },
    { section: 'loom', detail: 'access', label: 'Address / access' },
    { section: 'loom', detail: 'domains', label: 'Clock / power domains' },
  ] },
  { label: 'Microarchitecture', items: [
    { section: 'design', detail: 'fabric', label: 'Router controls (Design)' },
    { section: 'design', detail: 'goals', label: 'QoS goals (Design)' },
    { section: 'loom', detail: 'topology', label: 'Router topology' },
  ] },
  { label: 'Experiments', items: [
    { section: 'loom', detail: 'traffic', label: 'Traffic' },
    { section: 'loom', detail: 'simulation', label: 'Simulation results' },
    { section: 'loom', detail: 'workload', label: 'Workload profiling' },
    { section: 'evaluate', label: 'Evaluate', aliases: ['simulate'] },
    { section: 'performance', label: 'Performance' },
    { section: 'serving', label: 'Serving' },
    { section: 'optimize', label: 'Optimize' },
    { section: 'synthesize', label: 'Topology synthesis' },
    { section: 'candidates', label: 'Candidates' },
    { section: 'compare', label: 'Compare', aliases: ['decide'] },
  ] },
  { label: 'Implementation', items: [
    { section: 'compile', label: 'Compile design' },
    { section: 'implementation', label: 'Implementation lab' },
    { section: 'verification', label: 'Verification', aliases: ['verify'] },
    { section: 'loom', detail: 'floorplan', label: 'Abstract floorplan' },
  ] },
  { label: 'Evidence', items: [
    { section: 'runs', label: 'Runs' },
    { section: 'evidence', label: 'Evidence' },
    { section: 'validation', label: 'Validation lab' },
    { section: 'reproduce', label: 'Reproduce' },
    { section: 'capabilities', label: 'Capabilities' },
    { section: 'loom', detail: 'capability', label: 'Fabric capabilities' },
    { section: 'trust', label: 'Trust' },
  ] },
];
const NAV = NAV_GROUPS.flatMap((group) => group.items);

export function resolveNav(section: string): NavItem | null {
  return NAV.find((item) =>
    item.section === section || item.aliases?.includes(section),
  ) ?? null;
}

export function navHref(item: NavItem, projectId: string): string | null {
  if (projectId) return `/projects/${projectId}/${item.section}${item.detail ? `/${item.detail}` : ''}`;
  return item.section === 'runs' || item.section === 'trust' ? `/${item.section}` : null;
}

function Shell(): ReactElement {
  const { mode, projects, activeProjectId, setActiveProjectId } = useStudio();
  const path = usePathname();
  const route = parseRoute(path);
  const [theme, setTheme] = useState<Theme>('light');
  const [openGroup, setOpenGroup] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    if (projects.length === 0) return;
    const known = (id: string): boolean =>
      projects.some((p) => p.project.project_id === id);
    if (route.projectId) {
      if (known(route.projectId)) setActiveProjectId(route.projectId);
      return;
    }
    if (activeProjectId && !known(activeProjectId)) setActiveProjectId('');
  }, [route.projectId, projects, activeProjectId, setActiveProjectId]);

  const projectsLoaded = projects.length > 0;
  const routeProjectKnown =
    route.projectId != null &&
    projects.some((p) => p.project.project_id === route.projectId);
  const staleProject = Boolean(route.projectId) && projectsLoaded && !routeProjectKnown;
  const contextProjectId =
    route.projectId && (!projectsLoaded || routeProjectKnown)
      ? route.projectId
      : projects.some((p) => p.project.project_id === activeProjectId)
        ? activeProjectId
        : '';
  const activeProject = contextProjectId
    ? projects.find((p) => p.project.project_id === contextProjectId)
    : undefined;
  const pid = contextProjectId;
  const onProjectRoute = route.kind === 'project';

  const renderBody = (): ReactElement => {
    if (mode === 'offline') return <OfflineDemo />;
    switch (route.kind) {
      case 'trust':
        return <Trust />;
      case 'runs':
        return <Runs />;
      case 'run':
        return <RunDetail runId={route.runId ?? ''} />;
      case 'revision':
        return route.revisionId && route.group
          ? <RevisionCompileGroup key={route.revisionId}
              revisionId={route.revisionId} group={route.group} />
          : <p className="muted">Not found: {path}</p>;
      case 'project': {
        if (staleProject) return <ProjectPicker />;
        const nav = route.section ? resolveNav(route.section) : null;
        const section = nav ? nav.section : route.section;
        switch (section) {
          case 'workload': return <Workload projectId={pid} />;
          case 'design': return <Design projectId={pid}
            initialGroup={route.detail === 'fabric' || route.detail === 'goals' ? route.detail : undefined} />;
          case 'review': return <Review projectId={pid} />;
          case 'compile': return <Compile projectId={pid} />;
          case 'verification':
          case 'verify': return <Verify projectId={pid} />;
          case 'evaluate':
          case 'simulate': return <Evaluate projectId={pid} />;
          case 'serving': return <Serving projectId={pid} />;
          case 'evidence': return <Evidence projectId={pid} />;
          case 'validation': return <ValidationLab projectId={pid} />;
          case 'compare':
          case 'decide': return <Compare projectId={pid} />;
          case 'optimize': return <Optimize projectId={pid} />;
          case 'performance': return <Performance projectId={pid} />;
          case 'synthesize': return <Synthesize projectId={pid} />;
          case 'candidates': return <Candidates projectId={pid} candidateId={route.detail ?? null} />;
          case 'reproduce': return <Reproduce projectId={pid} />;
          case 'agents': return <AgentMatrix projectId={pid} />;
          case 'loom':
            return <Loom key={pid} projectId={pid} view={route.detail ?? 'topology'} />;
          case 'capabilities': return <CapabilitiesPage />;
          case 'implementation': return <ImplementationLabPage />;
          case 'runs': return <Runs />;
          case 'trust': return <Trust />;
          default: return <Overview projectId={pid} />;
        }
      }
      case 'notfound':
        return <p className="muted">Not found: {path}</p>;
      default:
        return <ProjectPicker />;
    }
  };

  const activeSection = (() => {
    if (!onProjectRoute || !route.section) return '';
    return resolveNav(route.section)?.section ?? '';
  })();

  const isRailActive = (item: NavItem): boolean => {
    if (item.section === 'runs' && (route.kind === 'runs' || route.kind === 'run')) return true;
    if (item.section === 'trust' && route.kind === 'trust') return true;
    if (!onProjectRoute || activeSection !== item.section) return false;
    if (item.section === 'loom') return (route.detail ?? 'topology') === item.detail;
    return (route.detail ?? undefined) === item.detail;
  };
  const activeGroup = NAV_GROUPS.find((group) => group.items.some(isRailActive))?.label ?? 'Architecture';
  const selectedItem = NAV.find(isRailActive);
  useEffect(() => { setOpenGroup(activeGroup); }, [activeGroup]);

  const renderNavItem = (item: NavItem): ReactElement => {
    const to = navHref(item, pid);
    const key = `${item.section}:${item.detail ?? ''}`;
    return to ? (
      <Link
        key={key}
        className={`rail-item rail-link${isRailActive(item) ? ' active' : ''}`}
        to={to}
        title={item.label}
      ><b>{item.label}</b></Link>
    ) : (
      <span key={key} className="rail-item rail-link disabled" aria-disabled="true">
        <b>{item.label}</b>
      </span>
    );
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <BrandMark />
          <div>
            <div className="brand-title">VERITX <span>STUDIO</span></div>
            <div className="brand-sub">
              Fabric engineering console
              <span className={`fixture-mode ${mode === 'live' ? 'live' : ''}`}>
                {mode === 'live'
                  ? 'LIVE'
                  : mode === 'offline'
                    ? 'OFFLINE DEMO'
                    : 'CHECKING…'}
              </span>
            </div>
          </div>
        </div>
        {activeProject ? (
          <ContextHeader project={activeProject} />
        ) : (
          <div className="context-strip">
            <span className="context-label">PROJECT</span>
            <b>none open</b>
          </div>
        )}
        <div className="top-actions">
          {projects.length > 0 && (
            <select
              className="project-select"
              aria-label="Active project"
              value={contextProjectId}
              onChange={(e) =>
                e.target.value
                  ? navigate(`/projects/${e.target.value}/overview`)
                  : navigate('/')
              }
            >
              <option value="">Projects…</option>
              {projects.map((p) => (
                <option key={p.project.project_id} value={p.project.project_id}>
                  {p.project.name}
                </option>
              ))}
            </select>
          )}
          {mode === 'live' && (
            <button className="ghost-button" onClick={() => navigate('/')}>
              New / open
            </button>
          )}
          <a className="ghost-button" href="/landing.html">
            Site <span aria-hidden="true">↗</span>
          </a>
          <button
            className="ghost-button"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>

      <aside className="sidebar" aria-label="Project navigation">
        <nav className="rail" aria-label="Workspaces">
          {NAV_GROUPS.map((group) => (
            <details
              key={group.label}
              className="rail-more"
              open={(openGroup ?? activeGroup) === group.label}
            >
              <summary className="rail-item rail-group-label" onClick={(event) => {
                event.preventDefault();
                setOpenGroup(group.label);
              }}><b>{group.label}</b></summary>
              <div className="rail-more-items">
                {group.items.map(renderNavItem)}
              </div>
            </details>
          ))}
        </nav>
        <select
          className="workspace-jump"
          aria-label="Jump to workspace view"
          value={selectedItem ? navHref(selectedItem, pid) ?? '' : ''}
          onChange={(event) => { if (event.target.value) navigate(event.target.value); }}
        >
          <option value="">Choose a view…</option>
          {NAV_GROUPS.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.items.map((item) => (
                <option key={`${item.section}:${item.detail ?? ''}`}
                  value={navHref(item, pid) ?? ''} disabled={!navHref(item, pid)}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </aside>

      <main className="workspace">{renderBody()}</main>
    </div>
  );
}

export default function App(): ReactElement {
  return (
    <StudioProvider>
      <Shell />
    </StudioProvider>
  );
}
