import { useState, type ReactElement } from 'react';
import { FIXTURES, FIXTURE_ORDER, type FixtureId } from '../fixtures';
import { Hash, TierBadge } from '../components/badges';
import type { DesignView } from '../types';
import FabricView from '../components/FabricView';
import VerifyView from '../components/VerifyView';
import EvaluateView from '../components/EvaluateView';
import OptimizeView from '../components/OptimizeView';

type Section = 'design' | 'verify' | 'evaluate' | 'optimize';

/** Offline fixture design: read-only. Fixtures demonstrate the contract
 * shape; nothing here edits or compiles. */
function FixtureDesign({ design }: { design: DesignView }): ReactElement {
  const w = design.workload;
  const g = design.noc_guided;
  const locked = design.locked_derived;
  return (
    <div className="design-grid">
      <div className="design-main">
        <section className="card">
          <h3>
            E1 · Workload <TierBadge tier="GUIDED" />
          </h3>
          <div className="kv"><span>model</span><span>{w.model_family} · {w.model_name ?? '—'}</span></div>
          <div className="kv"><span>TP / PP / EP / DP</span><span>{w.parallelism.tp} / {w.parallelism.pp} / {w.parallelism.ep} / {w.parallelism.dp}</span></div>
          <div className="kv"><span>serving mode</span><span>{w.serving_mode ?? '—'}</span></div>
        </section>
        <section className="card">
          <h3>
            E2 · Requirements <TierBadge tier="GUIDED" />
          </h3>
          <table className="tbl">
            <thead>
              <tr><th>Traffic class</th><th>QoS class</th><th>Latency ceiling</th><th>Bandwidth floor</th><th>Binding</th></tr>
            </thead>
            <tbody>
              {design.requirements.map((r, i) => (
                <tr key={i}>
                  <td>{r.traffic_class ?? '—'}</td>
                  <td>{r.qos_class}</td>
                  <td>{r.latency_ceiling_cycles ?? '—'}</td>
                  <td>{r.bandwidth_floor_gbps ?? '—'}</td>
                  <td>{r.binding ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="card">
          <h3>
            E3 · Agents <TierBadge tier="GUIDED" />
          </h3>
          {design.agents.map((a, i) => (
            <div className="kv" key={i}><span>{a.kind}</span><span>{a.count}×</span></div>
          ))}
        </section>
        <section className="card">
          <h3>E5 · NoC configuration</h3>
          <div className="kv"><span>topology</span><span>{g.topology_family ?? '—'}</span></div>
          <div className="kv"><span>radix</span><span>{g.radix ?? '—'}</span></div>
          <div className="kv"><span>concentration</span><span>{g.concentration ?? '—'}</span></div>
          <div className="kv"><span>link width</span><span>{g.link_width ?? '—'} bits</span></div>
          <div className="kv"><span>arbitration</span><span>{g.arbitration ?? '—'}</span></div>
          <div className="kv"><span>RCU</span><span>{String(g.rcu_enabled ?? '—')}</span></div>
          {locked && (
            <>
              <h4 className="locked-head">
                Derived properties <TierBadge tier="LOCKED" />
              </h4>
              <div className="kv"><span>routing</span><span>{locked.routing}</span></div>
              <div className="kv"><span>VC count</span><span>{locked.vc_count}</span></div>
              <div className="kv"><span>certificate</span><span>{locked.certificate_overall}</span></div>
            </>
          )}
        </section>
      </div>
      <aside className="design-side">
        <section className="card">
          <h3>Topology / traffic view</h3>
          <p className="muted">
            Fixture intent preview — not a certified fabric.
          </p>
          <FabricView design={design} revisionId={null} />
        </section>
      </aside>
    </div>
  );
}

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
            <FixtureDesign key={fixtureId} design={fixture.design} />
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
