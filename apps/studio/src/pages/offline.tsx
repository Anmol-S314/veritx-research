import { useState, type ReactElement } from 'react';
import { FIXTURES, FIXTURE_ORDER, type FixtureId } from '../fixtures';
import { Hash } from '../components/badges';
import DesignEditor from '../components/DesignEditor';
import VerifyView from '../components/VerifyView';
import EvaluateView from '../components/EvaluateView';
import OptimizeView from '../components/OptimizeView';

type Section = 'design' | 'verify' | 'evaluate' | 'optimize';

const SECTIONS: { id: Section; label: string }[] = [
  { id: 'design', label: 'Design' },
  { id: 'verify', label: 'Verify' },
  { id: 'evaluate', label: 'Evaluate' },
  { id: 'optimize', label: 'Optimize' },
];

export default function OfflineDemo(): ReactElement {
  const [fixtureId, setFixtureId] = useState<FixtureId>('compiled-mesh');
  const [section, setSection] = useState<Section>('design');
  const fixture = FIXTURES[fixtureId];

  return (
    <div className="page">
      <div className="offline-banner">
        <strong>OFFLINE DEMO</strong>
        <span>
          The gateway is unreachable. This view renders contract-validated
          fixtures only — no live compile, no live evaluation, and nothing here
          is presented as a live result. Start the gateway for LIVE mode.
        </span>
      </div>
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
      <nav className="sections" aria-label="Offline sections">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            className={`section-tab${section === s.id ? ' active' : ''}`}
            onClick={() => setSection(s.id)}
          >
            {s.label}
          </button>
        ))}
      </nav>
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
      </main>
      <footer className="statusbar">
        <span>
          study view v2 · other views v1 ·{' '}
          <Hash value={fixture.design?.design_hash} label="design" />
        </span>
      </footer>
    </div>
  );
}
