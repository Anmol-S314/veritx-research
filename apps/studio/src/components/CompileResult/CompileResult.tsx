import { useCallback, useEffect, useState, type ReactElement } from 'react';
import { api } from '../../api';
import type {
  CanonicalRoute, CertificateAbsence, CompileCertificate, CompileResultView,
  ControlPlaneGroup, PreflightView, RevisionDiffView,
} from '../../api';
import { hasClaims } from '../../api';
import type { CompileResultGroup } from '../../router';
import { AsyncView, Link, useAsync } from '../../studio';
import FabricInspector2D from '../FabricInspector2D';
import { SelectionProvider, useSelection } from './selection';
import CompileSummary from './CompileSummary';
import MappingInspector from './MappingInspector';
import FabricInspector from './FabricInspector';
import RoutingInspector from './RoutingInspector';
import ResourceInspector from './ResourceInspector';
import AddressDecodeInspector from './AddressDecodeInspector';
import ProvenanceInspector from './ProvenanceInspector';
import BackendAvailability from './BackendAvailability';
import ExecutionReadiness, {
  CapabilityConsequences,
} from './ExecutionReadiness';
import EngineeringFindings from './EngineeringFindings';
import { RevisionDiffBody } from './RevisionDiff';
import VerifyInspector from './VerifyInspector';

const GROUP_LABEL: Record<string, string> = {
  summary: 'Summary',
  mapping: 'Mapping',
  fabric: 'Fabric',
  routing: 'Routing',
  resources: 'Resources',
  address_decode: 'Address decode',
  provenance: 'Provenance',
  control_plane: 'Control plane',
};

export type CompileVariant = 'compile' | 'verify';

export default function CompileResult({ result, revisionId, projectId,
  variant = 'compile', activeGroup, onGroupChange }: {
  result: CompileResultView;
  revisionId: string;
  projectId: string;
  variant?: CompileVariant;
  activeGroup?: CompileResultGroup;
  onGroupChange?: (group: string) => void;
}): ReactElement {
  return (
    <SelectionProvider>
      <CompileResultBody result={result} revisionId={revisionId}
        projectId={projectId} variant={variant} activeGroup={activeGroup}
        onGroupChange={onGroupChange} />
    </SelectionProvider>
  );
}

function CompileResultBody({ result, revisionId, projectId, variant,
  activeGroup, onGroupChange }: {
  result: CompileResultView;
  revisionId: string;
  projectId: string;
  variant: CompileVariant;
  activeGroup?: CompileResultGroup;
  onGroupChange?: (group: string) => void;
}): ReactElement {
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  useEffect(() => setSelectedGroup(null), [activeGroup]);
  const group = selectedGroup ?? activeGroup ?? 'summary';
  const selectGroup = useCallback((next: string) => {
    setSelectedGroup(next);
    onGroupChange?.(next);
  }, [onGroupChange]);
  const [route, setRoute] = useState<CanonicalRoute | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);
  const { select } = useSelection();

  const queryRoute = useCallback((q: {
    routingClass: string; src: string; dst: string;
  }) => {
    setRouteLoading(true);
    setRouteError(null);
    api.route(revisionId, {
      routingClass: q.routingClass || null,
      src: q.src === '' ? null : Number(q.src),
      dst: q.dst === '' ? null : Number(q.dst),
    }).then((r) => {
      setRoute(r);
      selectGroup('fabric');
    }).catch((err: unknown) => {
      setRoute(null);
      setRouteError(err instanceof Error ? err.message : String(err));
    }).finally(() => setRouteLoading(false));
  }, [revisionId, selectGroup]);

  const jump = useCallback((tab: string) => selectGroup(tab), [selectGroup]);
  const inspectChannel = useCallback((channelId: number) => {
    select({ kind: 'channel', id: channelId });
  }, [select]);

  if (!result.available || !result.groups) {
    if (result.staged) return <StagedResult result={result} />;
    return (
      <section className="card">
        <h3>Compile result</h3>
        <p className="muted">
          {result.reason ?? 'No compile result exists for this revision.'}
        </p>
        <p className="muted">
          No upstream artifact was produced, so there is nothing valid to
          inspect. A failed proof is not a fabric.
        </p>
      </section>
    );
  }
  const groups = result.groups;
  const certificate: CompileCertificate | null = hasClaims(result.certificate)
    ? result.certificate : null;

  if (variant === 'verify') {
    return (
      <div className="compile-result">
        <header className="compile-head">
          <div>
            <h2>{result.display_name ?? 'compiled revision'}</h2>
            <p className="muted">
              compiled {result.compiled_at ?? '—'} ·{' '}
              <code>{result.design_hash?.slice(0, 18) ?? '—'}…</code>
            </p>
          </div>
          {certificate && (
            <span className={`claim-overall claim-${(certificate.overall ?? '').toLowerCase()}`}>
              certificate {certificate.overall ?? '—'}
              {' '}({certificate.claims.filter((c) => c.established).length}
              /{certificate.claim_count} claims established)
            </span>
          )}
        </header>
        {certificate ? (
          <VerifyInspector certificate={certificate} projectId={projectId} />
        ) : (
          <section className="card">
            <h4>Verification</h4>
            <p className="muted">
              {(result.certificate as CertificateAbsence | undefined)?.reason
                ?? 'No certificate exists for this revision.'}
            </p>
          </section>
        )}
        <p className="muted">
          <Link className="link" to={`/projects/${projectId}/compile`}>
            ← Back to the compile console
          </Link>
        </p>
      </div>
    );
  }

  const established = certificate
    ? certificate.claims.filter((c) => c.established).length : 0;
  return (
    <div className="compile-result">
      <header className="compile-head">
        <div>
          <h3>{result.display_name ?? 'Compiled revision'}</h3>
          <p className="muted compile-facts">
            {groups.summary.derived.routers ?? '—'} routers ·{' '}
            {groups.summary.derived.channels ?? '—'} channels ·{' '}
            {groups.summary.derived.endpoints ?? '—'} endpoints
          </p>
        </div>
        {certificate && (
          <span className={`claim-overall claim-${(certificate.overall ?? '').toLowerCase()}`}>
            Certificate {certificate.overall ?? '—'} · {established}/{certificate.claim_count} claims
          </span>
        )}
      </header>

      <EngineeringSummary result={result} revisionId={revisionId}
                          projectId={projectId} certificate={certificate} />

      <details className="subtle compile-inspectors">
      <summary>Engineering details</summary>
      <nav className="group-tabs" aria-label="Compile result groups">
        {(result.group_order ?? Object.keys(groups)).map((id) => (
          <button
            key={id}
            className={`group-tab${group === id ? ' active' : ''}`}
            aria-current={group === id ? 'true' : undefined}
            onClick={() => selectGroup(id)}
          >
            {GROUP_LABEL[id] ?? id}
          </button>
        ))}
      </nav>

      <div className="compile-body">
        {(groups as Record<string, unknown>)[group] == null ? (
          <section className="card" role="status">
            <h4>{GROUP_LABEL[group] ?? group}</h4>
            <p className="muted">
              This revision does not include this inspector group.
            </p>
          </section>
        ) : <>
        {group === 'summary' && (
          <>
            <CompileSummary group={groups.summary} projectId={projectId} />
          </>
        )}
        {group === 'mapping' && (
          <MappingInspector group={groups.mapping} fabric={groups.fabric}
                            onJump={jump} />
        )}
        {group === 'fabric' && (
          <FabricInspector group={groups.fabric} route={route}
                           showRoute={route !== null}
                           mapping={groups.mapping}
                           resources={groups.resources}
                           addressDecode={groups.address_decode}
                           onJump={jump} />
        )}
        {group === 'routing' && (
          <RoutingInspector group={groups.routing} route={route}
                            loading={routeLoading} error={routeError}
                            onQuery={queryRoute}
                            onInspectChannel={inspectChannel}
                            onJump={jump} />
        )}
        {group === 'resources' && (
          <ResourceInspector group={groups.resources}
                             certificate={certificate}
                             projectId={projectId} onJump={jump} />
        )}
        {group === 'address_decode' && (
          <AddressDecodeInspector group={groups.address_decode}
                                  fabric={groups.fabric} onJump={jump} />
        )}
        {group === 'provenance' && (
          <ProvenanceInspector group={groups.provenance}
                               projectId={projectId} onJump={jump} />
        )}
        {group === 'control_plane' && groups.control_plane && (
          <ControlPlaneInspector group={groups.control_plane} />
        )}
        </>}
      </div>
      </details>
    </div>
  );
}

function EngineeringSummary({ result, revisionId, projectId, certificate }: {
  result: CompileResultView;
  revisionId: string;
  projectId: string;
  certificate: CompileCertificate | null;
}): ReactElement {
  const preflight = useAsync(
    () => api.preflight(revisionId), [revisionId]);
  const diff = useAsync(
    () => api.revisionDiff(revisionId), [revisionId]);
  const [showAnalyses, setShowAnalyses] = useState(false);
  return (
    <>
      <AsyncView result={preflight.result} reload={preflight.reload}>
        {(pf: PreflightView) => (
          <>
            <ExecutionReadiness preflight={pf} projectId={projectId} />
            <details className="subtle">
              <summary>Notes and limits</summary>
              <EngineeringFindings result={result} preflight={pf} certificate={certificate} />
              <CapabilityConsequences consequences={result.capability_consequences ?? []} />
            </details>
          </>
        )}
      </AsyncView>
      <details className="subtle" onToggle={(event) => setShowAnalyses(event.currentTarget.open)}>
        <summary>Analysis availability</summary>
        {showAnalyses && <BackendAvailability revisionId={revisionId} />}
      </details>
      <details className="subtle">
        <summary>Changes from previous revision</summary>
        <AsyncView result={diff.result} reload={diff.reload}>
          {(d: RevisionDiffView) => <RevisionDiffBody diff={d} />}
        </AsyncView>
      </details>
      <details className="subtle">
        <summary>Revision identity and more actions</summary>
        <p className="muted">Compiled {result.compiled_at ?? '—'}</p>
        <div className="kv"><span>Design hash</span><code>{result.design_hash ?? '—'}</code></div>
        <div className="kv"><span>Topology hash</span><code>{result.topology_hash ?? '—'}</code></div>
        <div className="form-row">
          <Link className="link" to={`/projects/${projectId}/verify`}>Verification</Link>
          <Link className="link" to={`/projects/${projectId}/optimize`}>Optimize</Link>
          <Link className="link" to={`/projects/${projectId}/evidence`}>Evidence</Link>
        </div>
      </details>
    </>
  );
}

export function ControlPlaneInspector({ group }: {
  group: ControlPlaneGroup;
}): ReactElement {
  if (!group.declared || !group.subnet) {
    return (
      <section className="card">
        <h4>Control plane</h4>
        <p>{group.reason ?? 'No control-plane subnet was declared.'}</p>
        <p className="muted">Scope: {group.scope}. Not editable.</p>
      </section>
    );
  }

  const subnet = group.subnet;
  const binding = group.class_to_subnet;
  return (
    <section className="card">
      <h4>Control plane — declared structure</h4>
      {group.claim && <p>{group.claim}</p>}
      <p className="muted">
        {group.scope}: declared structure only. This is not traffic or timing,
        does not visualize actual traffic, and is not editable. Control-plane
        traffic is not claimed to be simulated.
      </p>
      <div className="kv"><span>Subnet</span><span>{subnet.id}</span></div>
      <div className="kv"><span>k</span><span>{subnet.k}</span></div>
      <div className="kv"><span>c</span><span>{subnet.c}</span></div>
      <div className="kv"><span>VCs</span><span>{subnet.vcs.join(', ')}</span></div>
      <div className="kv"><span>VC count</span><span>{subnet.vc_count}</span></div>
      <div className="kv"><span>Routing</span><span>{subnet.routing}</span></div>
      <div className="kv"><span>Routing class</span><span>{subnet.routing_class}</span></div>
      <div className="kv"><span>Subnet artifact</span><span>{subnet.artifact}</span></div>
      <div className="kv"><span>Subnet artifact hash</span><code>{subnet.artifact_hash}</code></div>
      <h5 className="inspector-label">Hash-bound class → subnet</h5>
      {binding?.available ? (
        <>
          <div className="kv"><span>Binding artifact</span><span>{binding.artifact}</span></div>
          <div className="kv"><span>Binding artifact hash</span><code>{binding.artifact_hash ?? '—'}</code></div>
          <table className="tbl">
            <thead><tr><th>Traffic class</th><th>Subnet</th></tr></thead>
            <tbody>{binding.rows.map((row, index) => (
              <tr key={`${row.traffic_class}-${row.subnet}-${index}`}>
                <td>{row.traffic_class}</td><td>{row.subnet}</td>
              </tr>
            ))}</tbody>
          </table>
        </>
      ) : (
        <p className="muted">
          {binding?.reason ?? 'No class-to-subnet binding is available.'}
        </p>
      )}
    </section>
  );
}

function StagedResult({ result }: { result: CompileResultView }): ReactElement {
  const topology = result.staged_topology ?? null;
  return (
    <div className="compile-result">
      <header className="compile-head">
        <div>
          <h2>{result.display_name ?? 'staged derivation'}</h2>
          <p className="muted">
            stopped at <strong>{result.stopped_at_stage ?? '—'}</strong> ·{' '}
            <code>{result.design_hash?.slice(0, 18) ?? '—'}…</code>
          </p>
        </div>
        <span className="claim-overall claim-staged">
          partial derivation — not a fabric
        </span>
      </header>

      <section className="card">
        <h4>Derived stages</h4>
        <ol className="stage-list">
          {(result.produced_stages ?? []).map((stage) => (
            <li key={stage} className="stage-derived">
              <span aria-hidden="true">✓</span> {stage}
            </li>
          ))}
          {result.stopped_at_stage && (
            <li className="stage-stopped">
              <span aria-hidden="true">✗</span> {result.stopped_at_stage}
              <span className="muted"> — {result.reason}</span>
            </li>
          )}
        </ol>
        <p className="muted">
          A later stage refusal does not invalidate earlier artifacts. The
          stages above are canonical and inspectable; nothing downstream was
          synthesized.
        </p>
      </section>

      {result.capability_consequences
        && result.capability_consequences.length > 0 && (
        <CapabilityConsequences consequences={result.capability_consequences} />
      )}

      {topology ? (
        <section className="card">
          <div className="inspector-head">
            <h4>Fabric — derived topology</h4>
            <span className="muted">
              {topology.family} · {topology.counts.routers} routers ·{' '}
              {topology.counts.channels} channels
            </span>
          </div>
          <FabricInspector2D topology={topology} />
        </section>
      ) : (
        <section className="card">
          <h4>Fabric</h4>
          <p className="muted">
            No topology was derived before the stop.
          </p>
        </section>
      )}

      <section className="card">
        <h4>Unavailable</h4>
        <ul className="muted">
          {(result.unavailable_groups ?? []).map((g) => (
            <li key={g}>{GROUP_LABEL[g] ?? g} — not produced</li>
          ))}
        </ul>
        <p className="muted">
          {(result.certificate as CertificateAbsence | undefined)?.reason
            ?? 'no certificate was issued'}
        </p>
      </section>
    </div>
  );
}
