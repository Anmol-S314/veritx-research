import { useEffect, useState, type ReactElement } from 'react';
import { FIXTURES, FIXTURE_ORDER, type FixtureId } from './fixtures';
import { api } from './api';
import { Hash } from './components/badges';
import DesignEditor from './components/DesignEditor';
import VerifyView from './components/VerifyView';
import EvaluateView from './components/EvaluateView';
import OptimizeView from './components/OptimizeView';
import LiveView from './components/LiveView';

type Section = 'design' | 'verify' | 'evaluate' | 'optimize' | 'runs' | 'trust';
type Theme = 'dark' | 'light';

const SECTIONS: { id: Section; label: string }[] = [
  { id: 'design', label: 'Design' },
  { id: 'verify', label: 'Verify' },
  { id: 'evaluate', label: 'Evaluate' },
  { id: 'optimize', label: 'Optimize' },
  { id: 'runs', label: 'Runs' },
  { id: 'trust', label: 'Trust' },
];

const LIVE_SECTIONS: Section[] = ['runs', 'trust'];

export default function App(): ReactElement {
  const [fixtureId, setFixtureId] = useState<FixtureId>('compiled-mesh');
  const [section, setSection] = useState<Section>('design');
  const [theme, setTheme] = useState<Theme>('dark');
  const [live, setLive] = useState<'checking' | 'live' | 'offline'>('checking');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    let alive = true;
    api
      .health()
      .then(() => alive && setLive('live'))
      .catch(() => alive && setLive('offline'));
    return () => {
      alive = false;
    };
  }, []);

  const fixture = FIXTURES[fixtureId];
  const isLive = LIVE_SECTIONS.includes(section);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">SROTA</span>
          <span className="brand-sub">Studio · Fabric Compiler Console</span>
          <span
            className={`fixture-mode ${live === 'live' ? 'live' : ''}`}
            title={
              live === 'live'
                ? 'Gateway reachable. Runs and Trust read live evidence.'
                : 'Gateway unreachable. Fixture-backed sections remain.'
            }
          >
            {live === 'live'
              ? 'LIVE GATEWAY'
              : live === 'offline'
                ? 'FIXTURE MODE · GATEWAY OFFLINE'
                : 'CHECKING GATEWAY…'}
          </span>
        </div>
        <nav className="sections" aria-label="Studio sections">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={`section-tab${section === s.id ? ' active' : ''}`}
              onClick={() => setSection(s.id)}
            >
              {s.label}
            </button>
          ))}
          <span
            className="section-tab disabled"
            title="Generate (RTL / SystemC / UVM) is deferred under P3 — no new work there."
          >
            Generate · deferred
          </span>
        </nav>
        <div className="top-actions">
          <button
            className="btn"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title="Toggle dark / light theme"
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>

      {!isLive && (
        <div className="fixture-bar">
          <span className="fixture-label">Fixture</span>
          <div className="fixture-tabs" role="tablist" aria-label="Fixtures">
            {FIXTURE_ORDER.map((id) => (
              <button
                key={id}
                role="tab"
                aria-selected={fixtureId === id}
                className={`fixture-tab${fixtureId === id ? ' active' : ''}`}
                onClick={() => setFixtureId(id)}
              >
                {id}
              </button>
            ))}
          </div>
          <span className="fixture-title">
            {fixture.title} — {fixture.description}
          </span>
        </div>
      )}

      <main className="content">
        {section === 'design' &&
          (fixture.design ? (
            <DesignEditor key={fixtureId} design={fixture.design} />
          ) : (
            <p className="muted">No DesignView in this fixture.</p>
          ))}
        {section === 'verify' && <VerifyView compilation={fixture.compilation} />}
        {section === 'evaluate' && (
          <EvaluateView
            key={fixtureId}
            evaluation={fixture.evaluation}
            requirements={fixture.requirements}
            fixtureId={fixtureId}
          />
        )}
        {section === 'optimize' && (
          <OptimizeView optimization={fixture.optimization} design={fixture.design} />
        )}
        {section === 'runs' && <LiveView view="runs" />}
        {section === 'trust' && <LiveView view="trust" />}
      </main>

      <footer className="statusbar">
        <span>
          study view v2 · other views v1 ·{' '}
          <Hash value={fixture.design?.design_hash} label="design" />
        </span>
        <span>
          fixtures validate against <code>contracts/srota/v1/*.schema.json</code>{' '}
          + <code>contracts/srota/v2/optimization.study.view.schema.json</code> (
          <code>npm run validate</code>)
        </span>
      </footer>
    </div>
  );
}
