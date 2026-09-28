import type { ReactElement } from 'react';
import type { CompileSummaryGroup } from '../../api';
import { fmtNum } from '../badges';
import { Link } from '../../studio';
import { EpistemicChip, ScientificValue } from '../ScientificValue';

const CLAIM_STATUS_CLASS: Record<string, string> = {
  PASS: 'ok', FAIL: 'bad', UNSUPPORTED: 'muted',
};

/** Summary inspector: declared → derived differences with meaningful
 * consequences, plus a COMPACT verified-claims summary.
 *
 * The full certificate inspector lives on the Verify page; Summary never
 * repeats it (P0 BUG 1). Claim rows here are status + scope only.
 */
export default function CompileSummary({ group, projectId }: {
  group: CompileSummaryGroup;
  projectId: string;
}): ReactElement {
  const d = group.declared;
  const derived = group.derived;
  const idleDerived = (derived.seats ?? 0) - (derived.endpoints ?? 0);
  return (
    <>
      <section className="card">
        <h4>Declared → derived</h4>
        <div className="kv-grid">
          <div className="kv"><span>declared concentration</span>
            <ScientificValue value={d.concentration}
              epistemic="DECLARED" source="design intent" /></div>
          <div className="kv"><span>derived routers / seats</span>
            <span>
              <ScientificValue value={derived.routers} unit="routers"
                epistemic="DERIVED" source="TopologyArtifact" />{' / '}
              <ScientificValue value={derived.seats} unit="seats"
                epistemic="DERIVED" source="TopologyArtifact" />
            </span></div>
          <div className="kv"><span>declared side length</span>
            <ScientificValue value={d.side_length}
              epistemic="DECLARED" source="design intent" /></div>
          <div className="kv"><span>derived channels / endpoints</span>
            <span>
              <ScientificValue value={derived.channels} unit="channels"
                epistemic="DERIVED" source="TopologyArtifact" />{' / '}
              <ScientificValue value={derived.endpoints} unit="endpoints"
                epistemic="DERIVED" source="TopologyArtifact" />
            </span></div>
          <div className="kv"><span>declared link width</span>
            <ScientificValue value={d.link_width} unit="bits"
              epistemic="DECLARED" source="design intent" /></div>
          <div className="kv"><span>derived VC count / routing</span>
            <span>
              <ScientificValue value={derived.vc_count} unit="VCs"
                epistemic="DERIVED" source="TopologyArtifact" />{' '}
              <span>{(derived.routing_classes ?? []).join(', ') || '—'}</span>{' '}
              <EpistemicChip value="DERIVED" />
            </span></div>
        </div>
        {idleDerived > 0 && (
          <p className="muted">
            Consequence: the fabric is larger than the workload needs —{' '}
            {idleDerived.toLocaleString('en-US')} of{' '}
            {(derived.seats ?? 0).toLocaleString('en-US')} seats carry no
            endpoint. See Mapping for the idle agents.
          </p>
        )}
      </section>

      <section className="card">
        <h4>Declared</h4>
        <div className="kv-grid">
          <div className="kv"><span>topology family</span>
            <span>{d.topology_family ?? '—'}</span></div>
          <div className="kv"><span>arbitration</span>
            <span>{d.arbitration ?? '— (semantic default)'}</span></div>
          {d.parallelism && (
            <div className="kv"><span>parallelism</span>
              <span className="num">
                TP{d.parallelism.tp}/PP{d.parallelism.pp}/
                EP{d.parallelism.ep}/DP{d.parallelism.dp}
              </span></div>
          )}
          <div className="kv"><span>requirements</span>
            <span className="num">{fmtNum(d.requirements)}</span></div>
        </div>
        {d.agents && d.agents.length > 0 && (
          <div className="kv-grid">
            {d.agents.map((agent) => (
              <div className="kv" key={agent.kind}>
                <span>{agent.kind}</span>
                <span className="num">{agent.count}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h4>Verified claims</h4>
        <ul className="claim-compact">
          {group.verified.map((claim) => (
            <li key={claim.claim}>
              <code>{claim.claim}</code>{' '}
              <span className={CLAIM_STATUS_CLASS[claim.certificate_status] ?? 'muted'}>
                {claim.certificate_status}
              </span>{' '}
              <span className="muted">· {claim.scope}</span>
            </li>
          ))}
        </ul>
        <p className="muted">
          Certificate {group.certificate_overall ?? '—'}. The complete
          obligation/certificate investigation lives on the Verify page.{' '}
          <Link className="link" to={`/projects/${projectId}/verify`}>
            Inspect verification →
          </Link>
        </p>
      </section>
    </>
  );
}
