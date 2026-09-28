import type { ReactElement } from 'react';
import {
  api,
  type FederationBackendView,
  type HealthView,
  type QualificationView,
} from '../api';
import { AsyncView, Link, useAsync } from '../studio';
import { Hash } from './badges';

// ── Trust / backends (§35) ────────────────────────────────────────────
// One row per producer: registration, installed binary, manifest, binary
// SHA, source revision, profiles, current readiness. Three facts stay
// separate: Release qualification (tracked authority) vs Current runtime
// readiness (this host, right now) vs Numerical validation (oracles).
// Readiness is adjudicated per canonical context by the evaluation plan;
// this page never declares a design READY.

function BackendCard({ backend, health }: {
  backend: FederationBackendView;
  health: HealthView | null;
}): ReactElement {
  const presence = health?.backends[backend.backend_id];
  return (
    <div className="card">
      <h4>{backend.backend_id}</h4>
      <div className="kv">
        <span>registration</span>
        <span className={backend.registered ? 'good' : 'bad'}>
          {backend.registered ? 'REGISTERED' : 'NOT REGISTERED'}
        </span>
      </div>
      <div className="kv">
        <span>installed binary</span>
        <span className={backend.runtime_available ? 'good' : 'muted'}>
          {backend.runtime_available ? 'PRESENT' : 'ABSENT'}
          {presence ? ` · state ${presence.state}` : ''}
        </span>
      </div>
      <div className="kv">
        <span>build manifest</span>
        <span className="muted">
          {presence == null
            ? 'unknown — health probe did not report'
            : presence.manifest_present
              ? 'present'
              : 'absent — provenance incomplete until rebuilt with manifest'}
        </span>
      </div>
      <div className="kv"><span>binary SHA</span><Hash value={backend.availability_detail || null} /></div>
      <p className="muted">
        Source revision, profile pins and per-question qualification ride
        on each run's producer record and evaluation plan — never on this
        table.
      </p>
      {backend.capabilities.length > 0 && (
        <details>
          <summary>declared capabilities ({backend.capabilities.length})</summary>
          <table className="tbl">
            <thead><tr><th>question</th><th>support</th><th>fidelity</th></tr></thead>
            <tbody>
              {backend.capabilities.map((c) => (
                <tr key={c.question}>
                  <td><code>{c.question}</code></td>
                  <td className={c.support === 'SUPPORTED' ? 'good' : 'muted'}>{c.support}</td>
                  <td className="muted">{c.fidelity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {backend.capabilities.flatMap((c) => c.limitations).length > 0 && (
        <p className="muted">
          known limitations:{' '}
          {[...new Set(backend.capabilities.flatMap((c) => c.limitations))].join('; ')}
        </p>
      )}
    </div>
  );
}

function ReleaseQualification({ data }: { data: QualificationView }): ReactElement {
  return (
    <section className="card">
      <h3>Release qualification — tracked authority</h3>
      <p className="muted">
        What the release process qualified, against which source and
        binaries. This is a historical fact about a release, not a claim
        that this host is ready right now.
      </p>
      <table className="live-table">
        <thead>
          <tr><th>engine</th><th>role</th><th>integration</th><th>limitations</th></tr>
        </thead>
        <tbody>
          {Object.entries(data.engines).map(([name, e]) => (
            <tr key={name}>
              <td>{name}</td>
              <td className="muted">{e.role}</td>
              <td>{e.integration}</td>
              <td className="muted">{e.limitations.join('; ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Source: docs/production/ENGINE-QUALIFICATION.json
        {data.validation_sha ? ` · validation ${data.validation_sha}` : ''}.
      </p>
    </section>
  );
}

function RuntimeReadiness({ health }: { health: HealthView | null }): ReactElement {
  return (
    <section className="card">
      <h3>Current runtime readiness — this host, right now</h3>
      <p className="muted">
        Install facts only: binary present/absent per producer. Whether a
        design can run is adjudicated per canonical context by the
        evaluation plan — never by this table.
      </p>
      {health == null ? (
        <p className="muted">Health probe unavailable — readiness unknown, never assumed.</p>
      ) : (
        <table className="tbl">
          <thead><tr><th>producer</th><th>state</th><th>binary</th><th>manifest</th></tr></thead>
          <tbody>
            {Object.entries(health.backends).map(([name, b]) => (
              <tr key={name}>
                <td>{name}</td>
                <td className={b.state === 'PRESENT' ? 'good' : 'muted'}>{b.state}</td>
                <td className={b.binary_present ? 'good' : 'bad'}>
                  {b.binary_present ? 'present' : 'absent'}
                </td>
                <td className="muted">{b.manifest_present ? 'present' : 'absent'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function NumericalValidation({ data }: { data: QualificationView }): ReactElement {
  return (
    <section className="card">
      <h3>Numerical validation — oracle state</h3>
      <p className="muted">
        Whether each engine's numbers have been validated against an
        independent oracle. NOT ESTABLISHED means the engine executes but
        its timing is not hardware truth.
      </p>
      <table className="live-table">
        <thead>
          <tr><th>engine</th><th>numerical</th><th>independence</th><th>qualified domains</th></tr>
        </thead>
        <tbody>
          {Object.entries(data.engines).map(([name, e]) => (
            <tr key={name}>
              <td>{name}</td>
              <td className={e.numerical === 'NOT_ESTABLISHED' ? 'bad' : 'good'}>
                {e.numerical}
              </td>
              <td className="muted">{e.independence}</td>
              <td className="muted">{e.qualified_domains.join('; ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** Trust backends page section: per-producer truth with the three facts
 * kept separate. Exported for the vNext TRUST group; the legacy Trust
 * page in pages/index.tsx is untouched. */
export function TrustBackends(): ReactElement {
  const qual = useAsync(api.qualification, []);
  const federation = useAsync(api.federationBackends, []);
  const health = useAsync(api.health, []);
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Trust · backends</h2>
          <p className="muted">
            One row per producer. Release qualification, current runtime
            readiness and numerical validation are three separate facts —
            never one generic badge.
          </p>
        </div>
        <div className="head-actions">
          <Link className="btn" to="/trust">Legacy trust page</Link>
        </div>
      </div>
      <AsyncView result={qual.result} reload={qual.reload}>
        {(q) => (
          <>
            <ReleaseQualification data={q} />
            <NumericalValidation data={q} />
          </>
        )}
      </AsyncView>
      <AsyncView result={health.result} reload={health.reload}>
        {(h) => <RuntimeReadiness health={h} />}
      </AsyncView>
      <AsyncView result={federation.result} reload={federation.reload}>
        {(fed) => (
          <AsyncView result={health.result} reload={health.reload}>
            {(h) => (
              <div className="stack-lg">
                {fed.backends.map((b) => (
                  <BackendCard key={b.backend_id} backend={b} health={h} />
                ))}
              </div>
            )}
          </AsyncView>
        )}
      </AsyncView>
    </div>
  );
}
