import type { ReactElement } from 'react';
import type { CapabilityConsequence, PreflightView } from '../../api';
import { Link } from '../../studio';

export default function ExecutionReadiness({ preflight, projectId }: {
  preflight: PreflightView;
  projectId: string;
}): ReactElement {
  const pf = preflight;
  return (
    <section className="execution-next" aria-label="Execution readiness">
      <div className="form-row">
        <span className={pf.ready ? 'ok' : 'bad'}>
          {pf.ready ? 'Ready to evaluate' : 'Execution blocked'}
        </span>
        <Link className="btn btn-primary" to={`/projects/${projectId}/simulate`}>
          {pf.ready ? 'Evaluate revision' : 'Choose analysis'}
        </Link>
      </div>
      {!pf.ready && pf.reason && <p className="bad">{pf.reason}</p>}
      <details className="subtle">
      <summary>Execution checks</summary>
      <div className="kv-grid">
        <div className="kv"><span>backend</span>
          <span>{pf.backend}</span></div>
        {pf.backend_profile && (
          <div className="kv"><span>profile</span>
            <span>{pf.backend_profile}</span></div>
        )}
      </div>
      <table className="tbl">
        <thead>
          <tr><th>gate</th><th>state</th><th>why</th></tr>
        </thead>
        <tbody>
          {pf.gates.map((g) => (
            <tr key={g.gate}>
              <td><code>{g.gate}</code></td>
              <td className={g.state === 'READY' || g.state === 'QUALIFIED'
                ? 'ok' : 'bad'}>{g.state}</td>
              <td className="muted">{g.reason ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!pf.ready && (
        <div className="form-row">
          <Link className="btn btn-small"
                to={`/projects/${projectId}/design`}>
            Change design →
          </Link>
          <Link className="btn btn-small"
                to={`/projects/${projectId}/simulate`}>
            Choose another analysis →
          </Link>
        </div>
      )}
      </details>
    </section>
  );
}

export function CapabilityConsequences({ consequences }: {
  consequences: CapabilityConsequence[];
}): ReactElement | null {
  if (consequences.length === 0) return null;
  return (
    <section className="card">
      <h4>Capability consequences</h4>
      <p className="muted">
        The compiled artifact is valid. These are downstream execution or
        qualification limits — not design errors.
      </p>
      <ul className="consequence-list">
        {consequences.map((c) => (
          <li key={c.capability_id}>
            <code>{c.capability_id}</code> <strong>{c.choice}</strong> —{' '}
            {c.wiring}
            {c.reason ? ` · ${c.reason}` : ''}
            {c.claim_scope && <p className="muted">{c.claim_scope}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
