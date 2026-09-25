import { useEffect, useState, type ReactElement } from 'react';
import { StudioProvider, useStudio } from './studio';
import { navigate, parseRoute, usePathname } from './router';
import {
  Overview, ProjectPicker, RunDetail, Runs, Trust, Workload,
} from './pages';
import { CompileVerify, Design, Simulate } from './pages/design';
import { Compare, Optimize } from './pages/optimize';
import OfflineDemo from './pages/offline';

type Theme = 'dark' | 'light';

const NAV = [
  { section: 'overview', label: 'Overview' },
  { section: 'workload', label: 'Workload' },
  { section: 'design', label: 'Design' },
  { section: 'compile', label: 'Compile & Verify' },
  { section: 'simulate', label: 'Simulate' },
  { section: 'decide', label: 'Compare / Optimize' },
] as const;

function Shell(): ReactElement {
  const { mode, projects } = useStudio();
  const path = usePathname();
  const route = parseRoute(path);
  const [theme, setTheme] = useState<Theme>('dark');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    if (route.kind !== 'root' || mode !== 'live') return;
    if (projects.length > 0) {
      navigate(`/projects/${projects[0].project.project_id}/overview`);
    }
  }, [route.kind, mode, projects]);

  const projectNav = NAV.map((item) => ({
    ...item,
    disabled: !route.projectId,
    to: route.projectId
      ? `/projects/${route.projectId}/${item.section}`
      : '#',
  }));

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
        const pid = route.projectId ?? '';
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

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">VERITX</span>
          <span className="brand-sub">Studio · Fabric Compiler Console</span>
          <span
            className={`fixture-mode ${mode === 'live' ? 'live' : ''}`}
            title={
              mode === 'live'
                ? 'Gateway reachable. All sections read live resources.'
                : mode === 'offline'
                  ? 'Gateway unreachable. Offline Demo (fixtures) only.'
                  : 'Checking gateway…'
            }
          >
            {mode === 'live'
              ? 'LIVE'
              : mode === 'offline'
                ? 'OFFLINE DEMO'
                : 'CHECKING…'}
          </span>
        </div>
        <nav className="sections" aria-label="Sections">
          {projectNav.map((item) => (
            <button
              key={item.section}
              className="section-tab"
              disabled={item.disabled}
              onClick={() => navigate(item.to)}
            >
              {item.label}
            </button>
          ))}
          <button className="section-tab" onClick={() => navigate('/runs')}>Runs</button>
          <button className="section-tab" onClick={() => navigate('/trust')}>Trust</button>
        </nav>
        <div className="top-actions">
          {projects.length > 0 && (
            <select
              className="project-select"
              value={route.projectId ?? ''}
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
            <button className="btn" onClick={() => navigate('/')}>
              New / open
            </button>
          )}
          <button
            className="btn"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>
      <main className="content">{renderBody()}</main>
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
