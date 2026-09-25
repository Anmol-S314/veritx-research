import { useEffect, useState, type ReactElement } from 'react';
import { ContextHeader, Link, StudioProvider, useStudio } from './studio';
import { navigate, parseRoute, usePathname } from './router';
import {
  Overview, ProjectPicker, RunDetail, Runs, Trust, Workload,
} from './pages';
import { CompileVerify, Design, Simulate } from './pages/design';
import { Compare, Optimize } from './pages/optimize';
import OfflineDemo from './pages/offline';
import BrandMark from './components/BrandMark';

type Theme = 'dark' | 'light';

const RAIL = [
  { section: 'overview', no: '01', label: 'Overview' },
  { section: 'workload', no: '02', label: 'Workload' },
  { section: 'design', no: '03', label: 'Design' },
  { section: 'compile', no: '04', label: 'Verify' },
  { section: 'simulate', no: '05', label: 'Simulate' },
  { section: 'decide', no: '06', label: 'Compare' },
  { section: 'optimize', no: '07', label: 'Optimize' },
] as const;

function Shell(): ReactElement {
  const { mode, projects, activeProjectId, setActiveProjectId } = useStudio();
  const path = usePathname();
  const route = parseRoute(path);
  const [theme, setTheme] = useState<Theme>('dark');

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

  const contextProjectId = route.projectId
    ?? (projects.some((p) => p.project.project_id === activeProjectId)
      ? activeProjectId
      : '');
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
        switch (route.section) {
          case 'workload': return <Workload projectId={pid} />;
          case 'design': return <Design projectId={pid} />;
          case 'compile': return <CompileVerify projectId={pid} />;
          case 'simulate': return <Simulate projectId={pid} />;
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
          {RAIL.map((item) =>
            pid ? (
              <Link
                key={item.section}
                className={`rail-item${isRailActive(item.section) ? ' active' : ''}`}
                to={`/projects/${pid}/${item.section}`}
                ariaLabel={item.label}
              >
                <span>{item.no}</span>
                <b>{item.label}</b>
              </Link>
            ) : (
              <span
                key={item.section}
                className="rail-item disabled"
                aria-disabled="true"
              >
                <span>{item.no}</span>
                <b>{item.label}</b>
              </span>
            ),
          )}
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
