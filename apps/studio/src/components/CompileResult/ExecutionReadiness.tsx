import type { ReactElement } from 'react';
import type { CapabilityConsequence, PreflightView } from '../../api';
import { Link } from '../../studio';

/** CAN I RUN THIS? — the preflight gate as a first-class Compile result
 * (P5). The verdict is the server's; Studio never recomputes it. Every
 * blocked gate shows its exact reason (Why?) and, where legitimate, the
 * upstream control that can change the outcome. */
export default function ExecutionReadiness({ preflight, projectId }: {
  preflight: PreflightView;
  projectId: string;
}): ReactElement {
  const pf = preflight;
  return (
    <section className="card" aria-label="Execution readiness">
      <h4>Can I run this?</h4>
      <div className={`readiness readiness-${pf.ready ? 'ready' : 'blocked'}`}>
        {pf.ready ? 'READY — this revision can be submitted'
          : 'BLOCKED — this revision cannot run yet'}
      </div>
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
      {pf.ready && (
        <div className="form-row">
          <Link className="btn btn-small"
                to={`/projects/${projectId}/simulate`}>
            Evaluate workload →
          </Link>
        </div>
      )}
    </section>
  );
}

/** Capability consequences shared by the engineering summary. */
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
