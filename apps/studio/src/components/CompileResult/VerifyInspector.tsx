import type { ReactElement } from 'react';
import type { CompileCertificate } from '../../api';
import { Link } from '../../studio';
import { EpistemicChip } from '../ScientificValue';
import { deadlockMessage } from './deadlock';
import { useSelection } from './selection';

const CLAIM_STATUS_CLASS: Record<string, string> = {
  PASS: 'ok', FAIL: 'bad', UNSUPPORTED: 'muted',
};

/** The Verify page owns full certificate inspection: the four product
 * claims, the deadlock analysis in its own vocabulary, every obligation
 * the verifier issued, and the cycle witness when one exists. */
export default function VerifyInspector({ certificate, projectId }: {
  certificate: CompileCertificate;
  projectId: string;
}): ReactElement {
  const analysis = certificate.deadlock_analysis;
  const deadlock = deadlockMessage(analysis ?? undefined);
  const { select } = useSelection();
  const established = certificate.claims.filter((c) => c.established).length;
  const passed = certificate.obligations.filter(
    (o) => o.status === 'PASS').length;
  const byObligation = new Map(
    certificate.obligations.map((o) => [o.obligation, o.status]));
  const FOUR_ROWS: { obligation: string; label: string }[] = [
    { obligation: 'ATTACHMENT_COMPLETE', label: 'Attachment complete' },
    { obligation: 'ROUTE_COMPLETE', label: 'Routing complete' },
    { obligation: 'ROUTE_LEGAL', label: 'Routing legal' },
    { obligation: 'DEADLOCK_FREE', label: 'Deadlock free' },
  ];
  return (
    <section className="card" aria-label="Verification">
      <h4>Verification</h4>
      <p className={certificate.overall === 'PASS' ? 'ok' : 'muted'}>
        <strong>{certificate.overall ?? '—'}</strong>{' '}
        {established}/{certificate.claim_count} product claims established ·{' '}
        {passed}/{certificate.obligation_count} obligations passed.{' '}
        <EpistemicChip value="VERIFIED" />
      </p>
      <table className="tbl four-claims">
        <thead>
          <tr><th>claim</th><th>status</th></tr>
        </thead>
        <tbody>
          {FOUR_ROWS.map((row) => (
            <tr key={row.obligation}>
              <td><strong>{row.label}</strong>{' '}
                <code className="muted">{row.obligation}</code></td>
              <td className={CLAIM_STATUS_CLASS[
                byObligation.get(row.obligation) ?? ''] ?? 'muted'}>
                {byObligation.get(row.obligation) ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h5 className="inspector-label">Technical proof</h5>
      <table className="tbl">
        <thead>
          <tr><th>claim</th><th>status</th><th>scope</th><th>contributing</th></tr>
        </thead>
        <tbody>
          {certificate.claims.map((claim) => (
            <tr key={claim.claim}>
              <td><code>{claim.claim}</code></td>
              <td className={CLAIM_STATUS_CLASS[claim.certificate_status] ?? 'muted'}>
                {claim.certificate_status ?? claim.status ?? 'UNKNOWN'}
              </td>
              <td className="muted">{claim.scope}</td>
              <td className="muted">
                {(claim.contributing_obligations ?? []).map((o) => (
                  <code key={o}>{o} </code>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h5 className="inspector-label">Deadlock</h5>
      {analysis ? (
        <>
          <p className={deadlock.tone}>
            Deadlock analysis: {deadlock.text}
            {analysis.unsupported_reason
              ? ` Contract: ${analysis.unsupported_reason}` : ''}
          </p>
          <div className="kv-grid">
            <div className="kv"><span>CDG SCCs &gt; 1 node</span>
              <span className="num">
                {analysis.sccs_gt_1 ?? '—'}</span></div>
            <div className="kv"><span>CDG nodes / edges</span>
              <span className="num">
                {analysis.node_count ?? '—'} /{' '}
                {analysis.edge_count ?? '—'}</span></div>
            <div className="kv"><span>route classes</span>
              <span>{(analysis.cdg_route_classes ?? []).join(', ') || '—'}</span></div>
            <div className="kv"><span>escape VCs</span>
              <span className="num">
                {(analysis.escape_vcs ?? []).join(', ') || '—'}</span></div>
            <div className="kv"><span>VC count</span>
              <span className="num">{analysis.vc_count ?? '—'}</span></div>
            <div className="kv"><span>route realization</span>
              <span>{analysis.route_realization_scheme ?? '—'}</span></div>
          </div>
        </>
      ) : (
        <p className="muted">No CDG analysis carried.</p>
      )}
      {analysis?.analysis_verdict === 'FAIL'
        && analysis.cycle_witness.length > 0 && (
        <>
          <h5 className="inspector-label">Cycle witness</h5>
          <p className="bad">
            A cycle exists in the channel-VC dependency graph.
          </p>
          <table className="tbl">
            <thead><tr><th>step</th><th>channel</th><th>VC</th><th></th></tr></thead>
            <tbody>
              {analysis.cycle_witness.map((node, i) => (
                <tr key={i}>
                  <td className="num">{i}</td>
                  <td className="num">
                    {node.channel_id != null ? `ch ${node.channel_id}` : '—'}
                  </td>
                  <td className="num">
                    {node.vc != null ? `vc ${node.vc}` : '—'}
                  </td>
                  <td>
                    {node.channel_id != null && (
                      <button className="btn btn-small"
                              onClick={() => select(
                                { kind: 'channel',
                                  id: node.channel_id as number })}>
                        Select channel
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="finding-remedies">
            <Link className="btn btn-small"
                  to={`/projects/${projectId}/compile`}>
              Inspect the cycle on the Fabric →
            </Link>
            <Link className="btn btn-small"
                  to={`/projects/${projectId}/design`}>
              Change the upstream design →
            </Link>
          </p>
        </>
      )}

      <details>
        <summary>
          All obligations ({certificate.obligation_count})
        </summary>
        <table className="tbl">
          <thead>
            <tr><th>obligation</th><th>status</th><th>method</th>
              <th>meaning</th></tr>
          </thead>
          <tbody>
            {certificate.obligations.map((o) => {
              const meta = certificate.technical_only.find(
                (t) => t.obligation === o.obligation);
              return (
                <tr key={o.obligation}>
                  <td><code>{o.obligation}</code></td>
                  <td className={CLAIM_STATUS_CLASS[o.status] ?? 'muted'}>
                    {o.status}
                  </td>
                  <td className="muted">{o.method}</td>
                  <td className="muted">{meta?.meaning ?? 'product claim'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="muted">
          Vocabulary — obligation status:{' '}
          {certificate.vocabulary.obligation_status.join(' · ')}; CDG analysis:{' '}
          {certificate.vocabulary.cdg_analysis_verdict.join(' · ')}.
        </p>
      </details>

      {certificate.claims.some((c) => !c.established) && (
        <p className="finding-remedies">
          <Link className="btn btn-small"
                to={`/projects/${projectId}/design`}>
            Change the upstream design →
          </Link>
          <span className="muted">
            Route and VC assignment are compiler-derived and cannot be edited
            here.
          </span>
        </p>
      )}
    </section>
  );
}
