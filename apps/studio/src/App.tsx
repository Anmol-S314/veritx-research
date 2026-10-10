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

interface NavItem {
  section: string;
  label: string;
  aliases?: string[];
}
const PRIMARY_NAV: NavItem[] = [
  { section: 'overview', label: 'Overview' },
  { section: 'design', label: 'Design' },
  { section: 'compile', label: 'Compile' },
  { section: 'evaluate', label: 'Evaluate', aliases: ['simulate'] },
  { section: 'loom', label: 'Fabric' },
  { section: 'runs', label: 'Runs' },
];
const MORE_NAV: NavItem[] = [
  { section: 'performance', label: 'Performance' },
  { section: 'serving', label: 'Serving' },
  { section: 'optimize', label: 'Optimize' },
  { section: 'synthesize', label: 'Synthesize' },
  { section: 'candidates', label: 'Candidates' },
  { section: 'compare', label: 'Compare', aliases: ['decide'] },
  { section: 'agents', label: 'Agents' },
  { section: 'verification', label: 'Verification', aliases: ['verify'] },
  { section: 'evidence', label: 'Evidence' },
  { section: 'reproduce', label: 'Reproduce' },
  { section: 'capabilities', label: 'Capabilities' },
  { section: 'validation', label: 'Validation lab' },
  { section: 'implementation', label: 'Implementation lab' },
  { section: 'trust', label: 'Trust' },
];
const NAV = [...PRIMARY_NAV, ...MORE_NAV];

function resolveNav(section: string): NavItem | null {
  return NAV.find((item) =>
    item.section === section || item.aliases?.includes(section),
  ) ?? null;
}

function Shell(): ReactElement {
  const { mode, projects, activeProjectId, setActiveProjectId } = useStudio();
  const path = usePathname();
  const route = parseRoute(path);
  const [theme, setTheme] = useState<Theme>('light');

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
          case 'design': return <Design projectId={pid} />;
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

  const isRailActive = (section: string): boolean => {
    if (section === 'runs' && (route.kind === 'runs' || route.kind === 'run')) return true;
    if (section === 'trust' && route.kind === 'trust') return true;
    if (!onProjectRoute) return false;
    if (activeSection === section) return true;
    return section === 'compare' && activeSection === 'optimize';
  };

  const renderNavItem = (item: NavItem): ReactElement => {
    const to = pid ? `/projects/${pid}/${item.section}`
      : item.section === 'runs' ? '/runs'
        : item.section === 'trust' ? '/trust' : null;
    return to ? (
      <Link
        key={item.section}
        className={`rail-item${isRailActive(item.section) ? ' active' : ''}`}
        to={to}
        title={item.label}
      ><b>{item.label}</b></Link>
    ) : (
      <span key={item.section} className="rail-item disabled" aria-disabled="true">
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
        <nav className="rail" aria-label="Primary navigation">
          {PRIMARY_NAV.map(renderNavItem)}
          <details
            className="rail-more"
            open={MORE_NAV.some((item) => isRailActive(item.section))}
          >
            <summary className="rail-item"><b>More tools</b></summary>
            <div className="rail-more-items">
              {MORE_NAV.map(renderNavItem)}
            </div>
          </details>
        </nav>
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
