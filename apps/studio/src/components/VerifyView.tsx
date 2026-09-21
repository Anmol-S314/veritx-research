import { useState, type ReactElement } from 'react';
import type { CompilationView, Obligation } from '../types';
import { Empty, Hash, StatusBadge } from './badges';

function FailureReason({ ob }: { ob: Obligation }): ReactElement | null {
  const reason = (ob.evidence as Record<string, unknown>)?.['reason'];
  if (ob.status === 'PASS' || typeof reason !== 'string') return null;
  return <div className="fail-reason">Failure reason: {reason}</div>;
}

/** All 10 P1A obligations from the CompilationView. Click → full evidence. */
export default function VerifyView({
  compilation,
}: {
  compilation: CompilationView | null;
}): ReactElement {
  const [selected, setSelected] = useState<string | null>(null);

  if (!compilation) {
    return <Empty title="No compilation" body="This fixture carries no CompilationView." />;
  }
  const obs = compilation.obligations ?? [];
  const sel: Obligation | undefined = obs.find((o) => o.obligation === selected);

  return (
    <div>
      <div className={`verdict-banner verdict-${compilation.status.toLowerCase()}`}>
        <StatusBadge status={compilation.status} />
        <span className="verdict-text">
          {compilation.status === 'COMPILED' &&
            `Fabric compiled. Certificate ${compilation.certificate_overall ?? ''} — ${obs.filter((o) => o.status === 'PASS').length}/${obs.length} obligations PASS.`}
          {compilation.status === 'INVALID' &&
            (compilation.error ?? 'Design INVALID — no bundle produced.')}
          {compilation.status === 'UNSUPPORTED' &&
            (compilation.error ?? 'Design UNSUPPORTED — typed refusal, no bundle.')}
        </span>
      </div>

      <div className="verify-grid">
        <div className="card">
          <h3>Obligations ({obs.length})</h3>
          {obs.length === 0 && (
            <p className="muted">No obligations carried by this outcome.</p>
          )}
          <ul className="ob-list">
            {obs.map((o) => (
              <li key={o.obligation}>
                <button
                  className={`ob-row ob-${o.status.toLowerCase()}${selected === o.obligation ? ' selected' : ''}`}
                  onClick={() => setSelected(o.obligation)}
                >
                  <StatusBadge status={o.status} />
                  <code>{o.obligation}</code>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h3>Obligation detail</h3>
          {!sel && <p className="muted">Select an obligation to inspect status, method, evidence, and bound identities.</p>}
          {sel && (
            <div>
              <div className="kv">
                <span>obligation</span>
                <code>{sel.obligation}</code>
              </div>
              <div className="kv">
                <span>status</span>
                <StatusBadge status={sel.status} />
              </div>
              <div className="kv">
                <span>method</span>
                <code>{sel.method}</code>
              </div>
              <FailureReason ob={sel} />
              <h4>Evidence</h4>
              <pre className="evidence">{JSON.stringify(sel.evidence, null, 2)}</pre>
              <h4>Bound identities</h4>
              <div className="kv">
                <span>certificate_id</span>
                <Hash value={compilation.certificate_id} />
              </div>
              <div className="kv">
                <span>resolved_fabric_hash</span>
                <Hash value={compilation.resolved_fabric_hash} />
              </div>
              <div className="kv">
                <span>design_hash</span>
                <Hash value={compilation.design_hash} />
              </div>
              {compilation.artifact_hashes && Object.keys(compilation.artifact_hashes).length > 0 && (
                <div className="kv">
                  <span>bundle artifacts</span>
                  <span className="artifact-list">
                    {Object.entries(compilation.artifact_hashes).map(([k, v]) => (
                      <Hash key={k} value={v} label={k} />
                    ))}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
