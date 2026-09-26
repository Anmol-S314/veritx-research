import { useEffect, useState, type ReactElement } from 'react';
import { ContextHeader, Link, StudioProvider, useStudio } from './studio';
import { navigate, parseRoute, usePathname } from './router';
import {
  Overview, ProjectPicker, RunDetail, Runs, Trust, Workload,
} from './pages';
import { Compile, Design, Review, Simulate, Verify } from './pages/design';
import { Compare, Optimize } from './pages/optimize';
import { Serving } from './pages/serving';
import { Evidence, ValidationLab } from './pages/evidence';
import OfflineDemo from './pages/offline';
import BrandMark from './components/BrandMark';

type Theme = 'dark' | 'light';

// The handoff IA (00–09). Two groups, matching the prototype: the
// revision workflow and the record/validation surfaces. Numbers are part
// of the product language — do not collapse them into generic tabs.
const RAIL: { section: string; no: string; label: string; group: string
  tiny?: string }[] = [
  { section: 'overview', no: '00', label: 'Overview', group: 'workflow' },
  { section: 'design', no: '01', label: 'Design', group: 'workflow', tiny: 'edit' },
  { section: 'compile', no: '02', label: 'Compile', group: 'workflow' },
  { section: 'verify', no: '03', label: 'Verify', group: 'workflow' },
  { section: 'simulate', no: '04', label: 'Evaluate', group: 'workflow' },
  { section: 'optimize', no: '05', label: 'Optimize', group: 'workflow' },
  { section: 'serving', no: '06', label: 'Serving', group: 'workflow', tiny: 'LLM' },
  { section: 'evidence', no: '07', label: 'Evidence', group: 'records' },
  { section: 'decide', no: '08', label: 'Compare', group: 'records' },
  { section: 'validation', no: '09', label: 'Validation lab', group: 'records' },
] as const;

function Shell(): ReactElement {
  const { mode, projects, activeProjectId, setActiveProjectId } = useStudio();
  const path = usePathname();
  const route = parseRoute(path);
  // Light mode is authoritative (STUDIO-WIREFRAMES.md §3/§5). Dark remains
  // available as an explicit opt-in and is not required for parity.
  const [theme, setTheme] = useState<Theme>('light');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Keep one open project across every route: opening a project records it,
  // global routes (/runs, /trust, run detail) keep reading it back. A
  // project that no longer exists drops the context instead of pointing at
  // a ghost.
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

  // A project id in the URL is trusted only once the project list has
  // loaded and confirms it. Otherwise a stale link dead-ends on a 404 with
  // a Retry that can never succeed.
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
      case 'project': {
        if (staleProject) return <ProjectPicker />;
        switch (route.section) {
          case 'workload': return <Workload projectId={pid} />;
          case 'design': return <Design projectId={pid} />;
          case 'review': return <Review projectId={pid} />;
          case 'compile': return <Compile projectId={pid} />;
          case 'verify': return <Verify projectId={pid} />;
          case 'simulate': return <Simulate projectId={pid} />;
          case 'serving': return <Serving projectId={pid} />;
          case 'evidence': return <Evidence projectId={pid} />;
          case 'validation': return <ValidationLab projectId={pid} />;
          case 'decide': return <Compare projectId={pid} />;
          case 'optimize': return <Optimize projectId={pid} />;
          default: return <Overview projectId={pid} />;
        }
      }
      case 'notfound':
        return <p className="muted">Not found: {path}</p>;
      default:
        return <ProjectPicker />;
    }
  };

  const isRailActive = (section: string): boolean => {
    if (!onProjectRoute) return false;
    if (route.section === section) return true;
    return section === 'decide' && route.section === 'optimize';
  };

  let lastGroup = '';

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

      <aside className="sidebar">
        <nav className="rail" aria-label="Primary navigation">
          {RAIL.map((item) => {
            const groupHeader = item.group !== lastGroup
              ? (
                <div className="rail-group" key={`g-${item.group}`}>
                  {item.group === 'workflow' ? 'Workflow' : 'Records & validation'}
                </div>
              )
              : null;
            lastGroup = item.group;
            const itemEl = pid ? (
              <Link
                key={item.section}
                className={`rail-item${isRailActive(item.section) ? ' active' : ''}`}
                to={`/projects/${pid}/${item.section}`}
                ariaLabel={item.label}
              >
                <span>{item.no}</span>
                <b>{item.label}</b>
                {item.tiny && <em>{item.tiny}</em>}
              </Link>
            ) : (
              <span
                key={item.section}
                className="rail-item disabled"
                aria-disabled="true"
              >
                <span>{item.no}</span>
                <b>{item.label}</b>
                {item.tiny && <em>{item.tiny}</em>}
              </span>
            );
            return groupHeader
              ? [groupHeader, itemEl]
              : itemEl;
          })}
        </nav>
        <div className="rail-bottom">
          <Link
            className={`rail-icon${route.kind === 'runs' || route.kind === 'run' ? ' active' : ''}`}
            to="/runs"
            ariaLabel="Runs"
          >
            R
          </Link>
          <Link
            className={`rail-icon${route.kind === 'trust' ? ' active' : ''}`}
            to="/trust"
            ariaLabel="Trust"
          >
            T
          </Link>
        </div>
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
