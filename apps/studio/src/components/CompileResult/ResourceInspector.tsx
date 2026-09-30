import { useState, type ReactElement } from 'react';
import type { CompileCertificate, ResourcesGroup } from '../../api';
import { fmtNum } from '../badges';
import { Link } from '../../studio';
import { deadlockMessage } from './deadlock';
import { EmptyState } from './EmptyState';
import { useSelection } from './selection';

export default function ResourceInspector({ group, certificate, projectId,
  onJump }: {
  group: ResourcesGroup;
  certificate: CompileCertificate | null;
  projectId: string;
  onJump: (tab: string) => void;
}): ReactElement {
  const classes = group.traffic_class_to_vcs ?? [];
  const [selectedClass, setSelectedClass] = useState<string | null>(
    classes.length > 0 ? classes[0][0] : null);
  const { select } = useSelection();
  const analysis = certificate?.deadlock_analysis ?? null;
  const deadlock = deadlockMessage(analysis ?? undefined);
  const witness = group.deadlock?.witness;

  if (!group.available) {
    return (
      <section className="card">
        <h4>Resources</h4>
        <EmptyState title="No resource assignment exists for this revision.">
          <p>VC assignment was never derived, so there is nothing to inspect.</p>
        </EmptyState>
      </section>
    );
  }

  const selVcs = classes.find(([c]) => c === selectedClass)?.[1] ?? [];
  const escapeVcs = group.escape_vcs ?? [];
  const selEscape = selVcs.filter((v) => escapeVcs.includes(v));
  const selAdaptive = selVcs.filter((v) => !escapeVcs.includes(v));

  return (
    <section className="card">
      <h4>Resources</h4>
      <h5 className="inspector-label">Virtual channels</h5>
      {classes.length === 0 ? (
        <EmptyState title="No traffic classes are bound to VCs.">
          <p>The VC assignment carries no class binding for this design.</p>
        </EmptyState>
      ) : (
        <table className="tbl">
          <thead>
            <tr><th>routing class</th><th>VC binding</th><th>transitions</th></tr>
          </thead>
          <tbody>
            {classes.map(([cls, vcs]) => (
              <tr key={cls}
                  className={cls === selectedClass ? 'row-selected' : ''}
                  style={{ cursor: 'pointer' }}
                  onClick={() => {
                    setSelectedClass(cls);
                    select({ kind: 'routing_class', id: cls });
                  }}>
                <td>{cls}</td>
                <td className="num">{(vcs ?? []).join(', ')}</td>
                <td>{group.transitions_are_identity ? 'identity' : 'non-identity'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selectedClass && (
        <div className="inspector-detail">
          <h5 className="inspector-label">
            Class {selectedClass} — legal VC set {(selVcs ?? []).join(', ')}
          </h5>
          <div className="kv-grid">
            <div className="kv"><span>allowed transitions</span>
              <span>{group.transitions_are_identity
                ? 'identity — a packet stays in its VC'
                : `${(group.allowed_transitions ?? []).length} non-identity pairs`}</span></div>
            <div className="kv"><span>CDG contribution</span>
              <span className="muted">
                {(witness?.cdg_route_classes ?? []).includes(selectedClass)
                  ? `class ${selectedClass} participates in the channel-VC dependency graph`
                  : `class ${selectedClass} is not in the CDG route-class set`
                    + ` (${(witness?.cdg_route_classes ?? []).join(', ') || '—'})`}
              </span></div>
            <div className="kv"><span>escape resource role</span>
              <span>{selEscape.length > 0
                ? `VCs ${selEscape.join(', ')} are designated escape`
                : 'no escape VC in this class'}</span></div>
            <div className="kv"><span>adaptive resource role</span>
              <span>{selAdaptive.length > 0
                ? `VCs ${selAdaptive.join(', ')} carry adaptive traffic`
                : '—'}</span></div>
          </div>
          <div className="form-row">
            <button className="btn btn-small"
                    onClick={() => onJump('routing')}>
              Routes using this class →
            </button>
          </div>
        </div>
      )}
      <div className="kv-grid">
        <div className="kv"><span>derived VC count</span>
          <span className="num">{fmtNum(group.vc_count)}</span></div>
        <div className="kv"><span>escape designation</span>
          <span>{escapeVcs.length > 0
            ? escapeVcs.join(', ')
            : '(none — supported-but-unused)'}</span></div>
      </div>
      <p className="muted">ⓘ derived · no controls</p>

      <h5 className="inspector-label">Channel dependency graph</h5>
      <p className={deadlock.tone}>
        {deadlock.text}
      </p>
      {analysis?.analysis_verdict === 'PASS' && (
        <p className="muted">
          Why it passed: the channel–VC dependency graph over
          the {(witness?.cdg_route_classes ?? []).join(', ') || 'certified'}
          {' '}route classes is acyclic
          ({fmtNum(witness?.node_count)} nodes, {fmtNum(witness?.edge_count)}{' '}
          edges, {fmtNum(witness?.sccs_gt_1)} multi-node components) under
          route-realization scheme {witness?.route_realization_scheme ?? '—'}.
        </p>
      )}
      {analysis?.analysis_verdict === 'FAIL'
        && (analysis.cycle_witness ?? []).length > 0 && (
        <>
          <h5 className="inspector-label">Cycle witness</h5>
          <p className="bad">
            A cycle exists in the channel-VC dependency graph. Select a node
            to inspect the channel on the Fabric.
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
                              onClick={() => {
                                select({ kind: 'channel',
                                         id: node.channel_id as number });
                                onJump('fabric');
                              }}>
                        Inspect
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {analysis?.analysis_verdict === 'UNSUPPORTED' && (
        <p className="muted">
          Missing proof contract:{' '}
          {analysis.unsupported_reason ?? 'the certifier named no reason'}.
          Change an editable upstream owner below to reach a supported
          routing/resource profile.
        </p>
      )}
      <p className="finding-remedies">
        <Link className="btn btn-small"
              to={`/projects/${projectId}/design`}>
          Change concentration →
        </Link>
        <Link className="btn btn-small"
              to={`/projects/${projectId}/workload`}>
          Change communication class →
        </Link>
        <span className="muted">
          Route and VC assignment are compiler-derived and cannot be edited
          here.
        </span>
      </p>

      <h5 className="inspector-label">Arbitration</h5>
      <div className="kv-grid">
        {Object.entries(group.arbitration ?? {}).map(([key, value]) => (
          <div className="kv" key={key}>
            <span>{key}</span>
            <span>{String(value ?? '—')}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
