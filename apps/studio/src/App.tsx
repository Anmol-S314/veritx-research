import { useEffect, useState, type ReactElement } from 'react';
import { ContextHeader, Link, StudioProvider, useStudio } from './studio';
import { navigate, parseRoute, usePathname } from './router';
import {
  Overview, ProjectPicker, RunDetail, Runs, Trust, Workload,
} from './pages';
import { Compile, Design, Review, Simulate, Verify } from './pages/design';
import { Compare, Optimize } from './pages/optimize';
import { Serving } from './pages/serving';
import { Performance } from './pages/performance';
import { Synthesize } from './pages/synthesize';
import { Candidates } from './pages/candidates';
import { Reproduce } from './pages/reproduce';
import { CapabilitiesPage } from './pages/capabilities';
import { ImplementationLabPage } from './pages/implementation-lab';
import { Evidence, ValidationLab } from './pages/evidence';
import OfflineDemo from './pages/offline';
import BrandMark from './components/BrandMark';

type Theme = 'dark' | 'light';

// Studio vNext IA (§2/§48): four work groups, no numbered sequence.
// Verification and Evidence are trust surfaces, not sequential steps.
// `to` is the canonical path; `aliases` keep pre-vNext deep links alive.
interface NavItem {
  section: string;
  label: string;
  tiny?: string;
  aliases?: string[];
  placeholder?: string;
}
interface NavGroup { group: string; items: NavItem[] }
const NAV: NavGroup[] = [
  { group: 'BUILD', items: [
    { section: 'overview', label: 'Overview' },
    { section: 'design', label: 'Design', tiny: 'edit' },
    { section: 'compile', label: 'Compile' },
  ]},
  { group: 'ANALYZE', items: [
    { section: 'evaluate', label: 'Evaluate', aliases: ['simulate'] },
    { section: 'performance', label: 'Performance',
      placeholder: 'Wave-E schedule, makespan, critical path, request latency, utilization, sensitivity.' },
    { section: 'serving', label: 'Serving', tiny: 'LLM' },
  ]},
  { group: 'EXPLORE', items: [
    { section: 'optimize', label: 'Optimize' },
    { section: 'synthesize', label: 'Synthesize',
      placeholder: 'MILP / SA / BO / RHO / GRPO topology synthesis over candidate graph producers.' },
    { section: 'candidates', label: 'Candidates',
      placeholder: 'Global candidate library across parameter-search and synthesis studies.' },
    { section: 'compare', label: 'Compare', aliases: ['decide'] },
  ]},
  { group: 'TRUST', items: [
    { section: 'runs', label: 'Runs' },
    { section: 'verification', label: 'Verification', aliases: ['verify'] },
    { section: 'evidence', label: 'Evidence' },
    { section: 'reproduce', label: 'Reproduce',
      placeholder: 'Per-backend reproduction: BookSim, ASTRA, Ramulator, serving where deterministic.' },
    { section: 'capabilities', label: 'Capabilities',
      placeholder: 'Capability explorer: every VERITX capability with its maturity stage.' },
    { section: 'validation', label: 'Validation lab' },
    { section: 'implementation', label: 'Implementation lab',
      placeholder: 'Energy & power, RTL, UVM/SVA, CDC, PIM, hardware multicast, multiplane research.' },
  ]},
] as const;

/** Resolve a raw route section (canonical or legacy alias) to its item. */
function resolveNav(section: string): NavItem | null {
  for (const g of NAV) {
    for (const item of g.items) {
      if (item.section === section) return { ...item };
      if (item.aliases?.includes(section)) return { ...item };
    }
  }
  return null;
}

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
        // Legacy aliases resolve to their canonical section first.
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
          case 'simulate': return <Simulate projectId={pid} />;
          case 'serving': return <Serving projectId={pid} />;
          case 'evidence': return <Evidence projectId={pid} />;
          case 'validation': return <ValidationLab projectId={pid} />;
          case 'compare':
          case 'decide': return <Compare projectId={pid} />;
          case 'optimize': return <Optimize projectId={pid} />;
          case 'performance': return <Performance projectId={pid} />;
          case 'synthesize': return <Synthesize projectId={pid} />;
          case 'candidates': return <Candidates projectId={pid} />;
          case 'reproduce': return <Reproduce projectId={pid} />;
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
    if (!onProjectRoute) return false;
    if (activeSection === section) return true;
    return section === 'compare' && activeSection === 'optimize';
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

      <aside className="sidebar">
        <nav className="rail" aria-label="Primary navigation">
          {NAV.map((navGroup) => (
            <div key={navGroup.group}>
              <div className="rail-group">{navGroup.group}</div>
              {navGroup.items.map((item) => (
                pid ? (
                  <Link
                    key={item.section}
                    className={`rail-item${isRailActive(item.section) ? ' active' : ''}`}
                    to={`/projects/${pid}/${item.section}`}
                    ariaLabel={item.label}
                  >
                    <b>{item.label}</b>
                    {item.tiny && <em>{item.tiny}</em>}
                  </Link>
                ) : (
                  <span
                    key={item.section}
                    className="rail-item disabled"
                    aria-disabled="true"
                  >
                    <b>{item.label}</b>
                    {item.tiny && <em>{item.tiny}</em>}
                  </span>
                )
              ))}
            </div>
          ))}
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
