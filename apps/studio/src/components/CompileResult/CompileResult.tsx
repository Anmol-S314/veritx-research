import { useCallback, useState, type ReactElement } from 'react';
import { api } from '../../api';
import type {
  CanonicalRoute, CertificateAbsence, CompileCertificate, CompileResultView,
  PreflightView, RevisionDiffView,
} from '../../api';
import { hasClaims } from '../../api';
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
import { EpistemicChip, ScientificValue } from '../ScientificValue';
import EngineeringFindings from './EngineeringFindings';
import CompileActions from './CompileActions';
import { RevisionDiffBody } from './RevisionDiff';
import VerifyInspector from './VerifyInspector';

/**
 * Compile Result as an ENGINEERING CONSOLE (not a set of read-only
 * artifact presentations). Seven inspector groups under one result; every
 * important finding supports inspection, diagnosis and a legitimate next
 * action.
 *
 * Two variants share the frozen payload:
 *
 *  * `compile` — the console: compact certificate status in the header,
 *    engineering summary, seven inspectors, preflight, diff, actions.
 *    The full certificate inspector is NOT rendered here.
 *  * `verify` — the Verify page owns complete obligation/certificate
 *    investigation.
 */

const GROUP_LABEL: Record<string, string> = {
  summary: 'Summary',
  mapping: 'Mapping',
  fabric: 'Fabric',
  routing: 'Routing',
  resources: 'Resources',
  address_decode: 'Address decode',
  provenance: 'Provenance',
};

export type CompileVariant = 'compile' | 'verify';

export default function CompileResult({ result, revisionId, projectId,
  variant = 'compile' }: {
  result: CompileResultView;
  revisionId: string;
  projectId: string;
  variant?: CompileVariant;
}): ReactElement {
  return (
    <SelectionProvider>
      <CompileResultBody result={result} revisionId={revisionId}
                         projectId={projectId} variant={variant} />
    </SelectionProvider>
  );
}

function CompileResultBody({ result, revisionId, projectId, variant }: {
  result: CompileResultView;
  revisionId: string;
  projectId: string;
  variant: CompileVariant;
}): ReactElement {
  const [group, setGroup] = useState('summary');
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
      setGroup('fabric');
    }).catch((err: unknown) => {
      setRoute(null);
      setRouteError(err instanceof Error ? err.message : String(err));
    }).finally(() => setRouteLoading(false));
  }, [revisionId]);

  const jump = useCallback((tab: string) => setGroup(tab), []);
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

  // Decision summary first (§8): what was built, is it valid, can it
  // run. Deep inspectors live under Engineering Details below.
  const established = certificate
    ? certificate.claims.filter((c) => c.established).length : 0;
  const obligationsPassed = certificate
    ? certificate.obligations.filter(
      (o) => o.status === 'PASS').length : 0;
  return (
    <div className="compile-result">
      <header className="compile-head">
        <div>
          <h2>{result.display_name ?? 'compiled revision'} · COMPILED</h2>
          <p className="muted">
            compiled {result.compiled_at ?? '—'} ·{' '}
            <code>{result.design_hash?.slice(0, 18) ?? '—'}…</code>
          </p>
          <p className="compile-facts">
            <ScientificValue value={groups.summary.derived.routers}
              unit="routers" epistemic="DERIVED" />{' · '}
            <ScientificValue value={groups.summary.derived.channels}
              unit="channels" epistemic="DERIVED" />{' · '}
            <ScientificValue value={groups.summary.derived.endpoints}
              unit="endpoints" epistemic="DERIVED" />{' · '}
            <ScientificValue
              value={groups.summary.declared.link_width}
              unit="bits" epistemic="DECLARED" />{' '}
            <ScientificValue
              value={(groups.summary.derived.routing_classes ?? []).length}
              unit="traffic classes" epistemic="DERIVED" />
            <span className="muted compile-source">
              derived from TopologyArtifact · link width declared in
              design intent
            </span>
          </p>
        </div>
        {certificate && (
          <span className={`claim-overall claim-${(certificate.overall ?? '').toLowerCase()}`}>
            certificate {certificate.overall ?? '—'}{' '}
            ({established}/{certificate.claim_count} claims ·{' '}
            {obligationsPassed}/{certificate.obligation_count} obligations){' '}
            <EpistemicChip value="VERIFIED" />
          </span>
        )}
      </header>

      <EngineeringSummary result={result} revisionId={revisionId}
                          projectId={projectId} certificate={certificate} />

      <h3>Engineering Details</h3>
      <nav className="group-tabs" aria-label="Compile result groups">
        {(result.group_order ?? Object.keys(groups)).map((id) => (
          <button
            key={id}
            className={`group-tab${group === id ? ' active' : ''}`}
            aria-current={group === id ? 'true' : undefined}
            onClick={() => setGroup(id)}
          >
            {GROUP_LABEL[id] ?? id}
          </button>
        ))}
      </nav>

      <div className="compile-body">
        {group === 'summary' && (
          <>
            <CompileSummary group={groups.summary} projectId={projectId} />
            <CapabilityConsequences consequences={
              (result as { capability_consequences?:
                CompileResultView['capability_consequences'] })
                .capability_consequences ?? []} />
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
      </div>
    </div>
  );
}

/** The top-level Engineering Summary (P1): what was built, what differs
 * from intent, what is derived, what was proven, executability, support
 * limits, what to change and what to do next. */
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
  const derived = result.groups?.summary.derived;
  const declared = result.groups?.summary.declared;
  return (
    <>
      <section className="card" aria-label="Compiled design">
        <h4>Compiled design</h4>
        <div className="stat-strip">
          <div className="stat">
            <span className="k">design identity</span>
            <code className="v" title={result.design_hash ?? ''}>
              {result.design_hash?.slice(0, 18)}…
            </code>
          </div>
          <div className="stat">
            <span className="k">fabric identity</span>
            <code className="v" title={result.topology_hash ?? ''}>
              {result.topology_hash?.slice(0, 18) ?? '—'}…
            </code>
          </div>
          <div className="stat">
            <span className="k">certificate</span>
            <span className="v">{certificate
              ? `${certificate.overall} · `
                + `${certificate.claims.filter((c) => c.established).length}`
                + `/${certificate.claim_count} claims`
              : 'none'}</span>
            <span className="s">claims established</span>
          </div>
          <div className="stat">
            <span className="k">built</span>
            <span className="v">{derived?.routers ?? '—'} routers ·{' '}
              {derived?.channels ?? '—'} channels ·{' '}
              {derived?.endpoints ?? '—'} endpoints</span>
            <span className="s">from {declared?.topology_family ?? '—'}
              {declared?.concentration != null
                ? ` ×${declared.concentration}` : ''}</span>
          </div>
        </div>
      </section>

      <BackendAvailability revisionId={revisionId} />
      <AsyncView result={preflight.result} reload={preflight.reload}>
        {(pf: PreflightView) => (
          <>
            <ExecutionReadiness preflight={pf} projectId={projectId} />
            <EngineeringFindings result={result} preflight={pf}
                                 certificate={certificate} />
            <AsyncView result={diff.result} reload={diff.reload}>
              {(d: RevisionDiffView) => (
                <>
                  <details>
                    <summary>
                      Changes from parent{' '}
                      {d.has_basis
                        ? `(${d.design_changes.length} design · ` +
                          `${d.derived_changes.length} derived · ` +
                          `${d.capability_changes.length} capability)`
                        : '(no predecessor)'}
                    </summary>
                    <RevisionDiffBody diff={d} />
                  </details>
                  <CompileActions projectId={projectId}
                                  certificate={certificate} preflight={pf}
                                  hasPredecessor={d.has_basis} />
                </>
              )}
            </AsyncView>
          </>
        )}
      </AsyncView>
    </>
  );
}

/**
 * A staged refusal (Phase-2 §24).
 *
 * Shows what DID derive, names the stage that stopped, and lists the groups
 * that therefore do not exist. Empty downstream panels are never rendered
 * as successful, and the wording is capability language, not "failed".
 */
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
