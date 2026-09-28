import type { ReactElement } from 'react';
import { api } from '../api';
import { AsyncView, useAsync } from '../studio';
import { Hash, fmtNum } from '../components/badges';

/**
 * §34 Validation Lab — three concepts kept separate:
 * CURRENT VALIDATION (run against current source/binaries),
 * RECORDED CAMPAIGNS (historical results with source SHA/date), and
 * ADVERSARIAL (mutation / metamorphic / intervention / tamper).
 * Qualification status is rendered from the backend authorities
 * (/validation, /qualification) — never hardcoded in React.
 */
export function ValidationLabPage(): ReactElement {
  const validation = useAsync(() => api.validation(), []);
  const qualification = useAsync(() => api.qualification(), []);

  return (
    <div className="page validation-lab-page">
      <h2>Validation Lab</h2>
      <p className="muted">
        Current validation, recorded campaigns, and adversarial campaigns —
        three different facts. Historical counters always show campaign
        source/revision/date, never as a live test of the current binary.
      </p>

      <h3>Current validation</h3>
      <p className="muted">Experiments run against the current source/binaries.</p>
      <AsyncView result={validation.result} reload={validation.reload}>
        {(view) => (
          <table className="live-table">
            <thead>
              <tr><th>Experiment</th><th>Status</th><th>Workload</th><th>Profile</th><th>Checks</th></tr>
            </thead>
            <tbody>
              {view.experiments.map((e) => (
                <tr key={e.id}>
                  <td title={e.title ?? e.id}><strong>{e.id}</strong><br /><span className="muted">{e.title}</span></td>
                  <td>{e.passed ? 'PASS' : 'FAIL'}{e.status ? ` · ${e.status}` : ''}</td>
                  <td>{e.workload ?? '—'}</td>
                  <td>{e.profile_id ?? '—'}</td>
                  <td className="num">{e.checks.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </AsyncView>

      <h3>Recorded campaigns</h3>
      <p className="muted">
        Historical campaign results with source/revision/date. Findings
        document: rendered from the backend view below.
      </p>
      <AsyncView result={validation.result} reload={validation.reload}>
        {(view) => (
          <div>
            <p className="muted">findings: {view.findings_document}</p>
            <ul>
              {view.prose_campaigns.map((c) => (
                <li key={c.document}><code>{c.document}</code></li>
              ))}
            </ul>
          </div>
        )}
      </AsyncView>
      <h4>Release qualification (tracked authority)</h4>
      <AsyncView result={qualification.result} reload={qualification.reload}>
        {(view) => (
          <div>
            <p className="muted">
              validation SHA: <Hash value={view.validation_sha} />
            </p>
            <table className="live-table">
              <thead>
                <tr><th>Engine</th><th>Role</th><th>Integration</th><th>Numerical</th><th>Qualified domains</th><th>Limitations</th></tr>
              </thead>
              <tbody>
                {Object.entries(view.engines).map(([name, q]) => (
                  <tr key={name}>
                    <td><strong>{name}</strong></td>
                    <td>{q.role}</td>
                    <td>{q.integration}</td>
                    <td>{q.numerical}</td>
                    <td>{q.qualified_domains.join(', ') || '—'}</td>
                    <td className="muted">{q.limitations.join('; ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncView>

      <h3>Adversarial</h3>
      <p className="muted">Mutation, metamorphic, engine, and intervention campaigns — verbatim from the backend.</p>
      <AsyncView result={validation.result} reload={validation.reload}>
        {(view) => (
          <div className="card-grid">
            <div className="card">
              <h4>Mutation ({view.mutations.caught}/{view.mutations.total} caught)</h4>
              <p className="muted">{view.mutations.document}</p>
              <ul>
                {view.mutations.mutations.map((m) => (
                  <li key={m.name ?? 'unknown'}>
                    {m.name}: {m.caught ? 'caught' : 'NOT CAUGHT'}
                    {m.detail ? <span className="muted"> — {m.detail}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
            <div className="card">
              <h4>Metamorphic ({view.metamorphic.passed}/{view.metamorphic.total} passed)</h4>
              <p className="muted">{view.metamorphic.document}</p>
              <ul>
                {view.metamorphic.probes.map((p) => (
                  <li key={p.name ?? 'unknown'}>
                    {p.name}: {p.passed ? 'pass' : 'FAIL'}
                    {p.invariant ? <span className="muted"> — invariant: {p.invariant}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
            <div className="card">
              <h4>Engines</h4>
              <p className="muted">{view.engines.document}</p>
              <ul>
                {view.engines.engines.map((g) => (
                  <li key={g.name ?? 'unknown'}>
                    {g.name}: {g.passed ? 'pass' : 'FAIL'} ({fmtNum(g.checks.length)} checks)
                  </li>
                ))}
              </ul>
            </div>
            <div className="card">
              <h4>Intervention</h4>
              <p className="muted">{view.intervention.document} · supported: {String(view.intervention.supported)}</p>
            </div>
          </div>
        )}
      </AsyncView>
    </div>
  );
}
