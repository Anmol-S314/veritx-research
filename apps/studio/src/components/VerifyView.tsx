import { useState, type ReactElement } from 'react';
import type { CompilationView, Obligation } from '../types';
import { Empty, Hash, StatusBadge } from './badges';

/** Human meaning of each LOCKED obligation. Presentation only — the
 * backend decides PASS/FAIL; this decides how the proof reads. */
const OBLIGATION_MEANING: Record<string, string> = {
  TOPOLOGY_CONNECTED:
    'Every router can reach every other router — the fabric is one network, not fragments.',
  ATTACHMENT_COMPLETE:
    'Every agent instance has a real seat on a real router port.',
  ADDRESS_DECODE_VALID:
    'Every attached endpoint has a non-overlapping address window.',
  ROUTE_COMPLETE:
    'A route exists for every source–destination router pair and routing class.',
  ROUTE_LEGAL:
    'Every route step follows a physical channel of the certified topology.',
  VC_ASSIGNMENT_VALID:
    'Virtual channels are assigned consistently with the resolved routes.',
  DEADLOCK_FREE:
    'The channel–VC dependency graph has no cycle a packet can wait on forever.',
  MAPPING_VALID:
    'Every logical rank maps to an agent instance that is actually attached.',
  PACKET_FORMAT_VALID:
    'Flit layout fits the physical channel width for every VC resource.',
  FABRIC_DAG_VALID:
    'The whole artifact chain revalidates as one consistent fabric.',
};

/** Key evidence cells chosen per obligation from the certificate's own
 * evidence dict. Values render as-is; a field the backend did not emit
 * simply shows nothing — never a zero or a guess. */
const OBLIGATION_KEY_EVIDENCE: Record<string, { label: string; field: string; format?: 'num' }[]> = {
  TOPOLOGY_CONNECTED: [
    { label: 'routers', field: 'routers', format: 'num' },
    { label: 'directed channels', field: 'directed_channels', format: 'num' },
    { label: 'connected components', field: 'components', format: 'num' },
  ],
  ATTACHMENT_COMPLETE: [
    { label: 'endpoints', field: 'endpoints', format: 'num' },
  ],
  ADDRESS_DECODE_VALID: [
    { label: 'address windows', field: 'entries', format: 'num' },
  ],
  ROUTE_COMPLETE: [
    { label: 'routers', field: 'routers', format: 'num' },
    { label: 'routing classes', field: 'routing_classes' },
    { label: 'required route entries', field: 'expected_entries', format: 'num' },
    { label: 'actual route entries', field: 'entries', format: 'num' },
  ],
  ROUTE_LEGAL: [
    { label: 'routing classes', field: 'routing_classes' },
  ],
  VC_ASSIGNMENT_VALID: [
    { label: 'VC count', field: 'vc_count', format: 'num' },
    { label: 'VC → routing class', field: 'vc_to_routing_class' },
  ],
  DEADLOCK_FREE: [
    { label: 'CDG cycles > 1 node', field: 'sccs_gt_1', format: 'num' },
    { label: 'topology identity', field: 'topology_hash' },
    { label: 'router behavior identity', field: 'router_behavior_hash' },
  ],
  MAPPING_VALID: [
    { label: 'placements', field: 'placements', format: 'num' },
  ],
  PACKET_FORMAT_VALID: [
    { label: 'flit width', field: 'flit_width_bits', format: 'num' },
    { label: 'VC count', field: 'vc_count', format: 'num' },
  ],
  FABRIC_DAG_VALID: [
    { label: 'resolved fabric identity', field: 'resolved_fabric_hash' },
    { label: 'fabric identity', field: 'fabric_hash' },
  ],
};

function KeyEvidence({ ob }: { ob: Obligation }): ReactElement | null {
  const spec = OBLIGATION_KEY_EVIDENCE[ob.obligation];
  if (!spec) return null;
  const ev = (ob.evidence ?? {}) as Record<string, unknown>;
  const rows = spec.filter((s) => {
    const v = ev[s.field];
    return v !== undefined && v !== null;
  });
  if (rows.length === 0) return null;
  return (
    <table className="tbl key-evidence">
      <tbody>
        {rows.map(({ label, field, format }) => {
          const value = ev[field];
          return (
            <tr key={field}>
              <td>{label}</td>
              <td className="num">
                {typeof value === 'string' && value.startsWith('sha256:')
                  ? <Hash value={value} />
                  : format === 'num' && typeof value === 'number'
                    ? value.toLocaleString('en-US')
                    : String(value)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

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
  const passed = obs.filter((o) => o.status === 'PASS').length;
  const byObligation = new Map(obs.map((o) => [o.obligation, o]));
  const FOUR_ROWS: { obligation: string; label: string }[] = [
    { obligation: 'ATTACHMENT_COMPLETE', label: 'Attachment complete' },
    { obligation: 'ROUTE_COMPLETE', label: 'Routing complete' },
    { obligation: 'ROUTE_LEGAL', label: 'Routing legal' },
    { obligation: 'DEADLOCK_FREE', label: 'Deadlock free' },
  ];
  const deadlockOb = byObligation.get('DEADLOCK_FREE');
  const deadlockEv = (deadlockOb?.evidence ?? {}) as Record<string, unknown>;

  return (
    <div>
      <div className={`verdict-banner verdict-${compilation.status.toLowerCase()}`}>
        <StatusBadge status={compilation.status} />
        <span className="verdict-text">
          {compilation.status === 'COMPILED' &&
            `CERTIFIED — certificate ${compilation.certificate_overall ?? ''} — ${passed}/${obs.length} obligations PASS.`}
          {compilation.status === 'INVALID' &&
            (compilation.error ?? 'Design INVALID — no bundle produced.')}
          {compilation.status === 'UNSUPPORTED' &&
            (compilation.error ?? 'Design UNSUPPORTED — typed refusal, no bundle.')}
        </span>
      </div>

      {compilation.status === 'COMPILED' && (
        <div className="card">
          <h3>Certificate</h3>
          <table className="tbl four-claims">
            <thead><tr><th>claim</th><th>status</th></tr></thead>
            <tbody>
              {FOUR_ROWS.map((row) => {
                const ob = byObligation.get(row.obligation);
                return (
                  <tr key={row.obligation}>
                    <td><strong>{row.label}</strong>{' '}
                      <code className="muted">{row.obligation}</code></td>
                    <td><StatusBadge status={ob?.status ?? 'UNKNOWN'} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {compilation.status === 'COMPILED' && deadlockOb && (
        <div className="card">
          <h3>Deadlock proof</h3>
          <p className="muted">
            Channel–VC dependency graph must be acyclic. SCCs over one
            node, escape resources, route classes and VC transitions are
            the evidence — a cycle witness appears only on failure.
          </p>
          <div className="kv-grid">
            <div className="kv"><span>CDG SCCs &gt; 1 node</span>
              <span className="num">
                {typeof deadlockEv['sccs_gt_1'] === 'number'
                  ? (deadlockEv['sccs_gt_1'] as number).toLocaleString('en-US')
                  : '—'}</span></div>
            <div className="kv"><span>route classes</span>
              <span>{Array.isArray(deadlockEv['routing_classes'])
                ? (deadlockEv['routing_classes'] as unknown[]).join(', ')
                : '—'}</span></div>
            <div className="kv"><span>VC count</span>
              <span className="num">
                {typeof deadlockEv['vc_count'] === 'number'
                  ? (deadlockEv['vc_count'] as number).toLocaleString('en-US')
                  : '—'}</span></div>
            <div className="kv"><span>topology identity</span>
              <span className="num">
                {typeof deadlockEv['topology_hash'] === 'string'
                  ? (deadlockEv['topology_hash'] as string).slice(0, 18) + '…'
                  : '—'}</span></div>
          </div>
          <button
            className="btn btn-small"
            onClick={() => setSelected('DEADLOCK_FREE')}>
            Inspect the deadlock obligation →
          </button>
        </div>
      )}

      <div className="verify-grid">
        <div className="card">
          <h3>Technical proof — obligations ({obs.length})</h3>
          {obs.length === 0 && (
            <p className="muted">
              No obligation list carried by this outcome. A build-time refusal
              (INVALID/UNSUPPORTED) fails before certification, so no bundle and
              no certificate exist — the error above is the evidence.
            </p>
          )}
          <ul className="ob-list">
            {obs.map((o) => (
              <li key={o.obligation}>
                <button
                  className={`ob-row ob-${o.status.toLowerCase()}${selected === o.obligation ? ' selected' : ''}`}
                  onClick={() => setSelected(o.obligation)}
                >
                  <StatusBadge status={o.status} />
                  <span className="ob-text">
                    <code>{o.obligation}</code>
                    {OBLIGATION_MEANING[o.obligation] && (
                      <small className="muted">
                        {OBLIGATION_MEANING[o.obligation]}
                      </small>
                    )}
                  </span>
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
              {OBLIGATION_MEANING[sel.obligation] && (
                <p className="muted">{OBLIGATION_MEANING[sel.obligation]}</p>
              )}
              <FailureReason ob={sel} />
              <h4>Key evidence</h4>
              <KeyEvidence ob={sel} />
              <h4>Full evidence</h4>
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
