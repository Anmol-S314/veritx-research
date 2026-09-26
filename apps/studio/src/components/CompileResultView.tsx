import { useCallback, useState, type ReactElement } from 'react';
import { api } from '../api';
import type {
  AddressDecodeGroup, CanonicalRoute, CapabilityConsequence,
  CompileCertificate, CompileResultView, CompileSummaryGroup, FabricGroup,
  MappingGroup, ProvenanceGroup, ResourcesGroup, RoutingGroup,
} from '../api';
import { Hash, fmtNum, humanize } from './badges';
import ArtifactChain from './ArtifactChain';
import FabricInspector2D from './FabricInspector2D';

/**
 * Compile Result (Gate 8 §50–§63).
 *
 * Seven inspector groups under ONE Compile Result — not one page per
 * artifact. Every group is read-only: an inspector reveals canonical
 * properties, it never edits them. The payload is frozen at certification
 * time, so nothing here is re-derived from the request.
 *
 * Two rules are visible in the rendering:
 *
 *  * the certificate shows the four product claims AND every obligation
 *    the verifier issued, because the four are a subset of the ten;
 *  * expected and observed are never merged — the canonical route is
 *    labelled DERIVED EXPECTED, and the runtime observation is reported
 *    as unavailable until an evaluation run produces one.
 */

const CLAIM_STATUS_CLASS: Record<string, string> = {
  PASS: 'ok', FAIL: 'bad', UNSUPPORTED: 'muted',
};

function ClaimTable({ summary }: { summary: CompileSummaryGroup }): ReactElement {
  return (
    <table className="tbl">
      <thead>
        <tr><th>claim</th><th>status</th><th>scope</th></tr>
      </thead>
      <tbody>
        {summary.verified.map((claim) => (
          <tr key={claim.claim}>
            <td><code>{claim.claim}</code></td>
            <td className={CLAIM_STATUS_CLASS[claim.certificate_status] ?? 'muted'}>
              {claim.certificate_status}
            </td>
            <td className="muted">{claim.scope}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SummaryGroup({ group }: { group: CompileSummaryGroup }): ReactElement {
  const d = group.declared;
  const derived = group.derived;
  return (
    <>
      <section className="card">
        <h4>Declared</h4>
        <div className="kv-grid">
          <div className="kv"><span>topology family</span>
            <span>{d.topology_family ?? '—'}</span></div>
          {/* §16: the product name for the implementation field `radix`. */}
          <div className="kv"><span>side length</span>
            <span className="num">{fmtNum(d.side_length)}</span></div>
          <div className="kv"><span>concentration</span>
            <span className="num">{fmtNum(d.concentration)}</span></div>
          <div className="kv"><span>link width</span>
            <span className="num">{fmtNum(d.link_width)} bits</span></div>
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
                <span>{humanize(agent.kind)}</span>
                <span className="num">{agent.count}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <h4>Derived</h4>
        <div className="kv-grid">
          <div className="kv"><span>routers</span>
            <span className="num">{fmtNum(derived.routers)}</span></div>
          <div className="kv"><span>directed channels</span>
            <span className="num">{fmtNum(derived.channels)}</span></div>
          <div className="kv"><span>seats</span>
            <span className="num">{fmtNum(derived.seats)}</span></div>
          <div className="kv"><span>endpoints</span>
            <span className="num">{fmtNum(derived.endpoints)}</span></div>
          <div className="kv"><span>VC count</span>
            <span className="num">{fmtNum(derived.vc_count)}</span></div>
          <div className="kv"><span>routing</span>
            <span>{(derived.routing_classes ?? []).join(', ') || '—'}</span></div>
        </div>
      </section>

      <section className="card">
        <h4>Verified</h4>
        <ClaimTable summary={group} />
      </section>
    </>
  );
}

function MappingGroupView({ group }: { group: MappingGroup }): ReactElement {
  const [filter, setFilter] = useState('');
  const [agentFilter, setAgentFilter] = useState('');
  const [idleOnly, setIdleOnly] = useState(false);
  const needle = filter.trim().toLowerCase();
  const kinds = [...new Set(group.rows.map((r) => r.agent_kind ?? ''))]
    .filter(Boolean).sort();
  const rows = group.rows.filter((row) => {
    if (agentFilter && row.agent_kind !== agentFilter) return false;
    if (!needle) return true;
    const coords = row.coordinates
      ? `tp${row.coordinates.tp} pp${row.coordinates.pp} `
        + `ep${row.coordinates.ep} dp${row.coordinates.dp}`
      : '';
    return String(row.rank).includes(needle)
      || (row.agent_kind ?? '').toLowerCase().includes(needle)
      || String(row.instance_index ?? '').includes(needle)
      || coords.toLowerCase().includes(needle);
  });
  const idle = group.idle_agents;
  return (
    <section className="card">
      <div className="inspector-head">
        <h4>Mapping</h4>
        <input
          className="inspector-filter"
          placeholder="search rank, coordinate, agent or instance…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div className="inspector-controls">
        <label>agent
          <select value={agentFilter}
                  onChange={(e) => setAgentFilter(e.target.value)}>
            <option value="">all</option>
            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={idleOnly}
                 onChange={(e) => setIdleOnly(e.target.checked)} />
          idle agents only
        </label>
      </div>
      {group.parallelism && (
        <p className="muted">
          parallelism TP{group.parallelism.tp}/PP{group.parallelism.pp}/
          EP{group.parallelism.ep}/DP{group.parallelism.dp} ·{' '}
          {group.rank_count} ranks
        </p>
      )}
      {!idleOnly && (
        <>
          <table className="tbl">
            <thead>
              <tr>
                <th>rank</th><th>tp</th><th>pp</th><th>ep</th><th>dp</th>
                <th>agent</th><th>group</th><th>instance</th><th>endpoint</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.rank}-${row.endpoint_id}`}>
                  <td className="num">{row.rank}</td>
                  <td className="num">{row.coordinates?.tp ?? '—'}</td>
                  <td className="num">{row.coordinates?.pp ?? '—'}</td>
                  <td className="num">{row.coordinates?.ep ?? '—'}</td>
                  <td className="num">{row.coordinates?.dp ?? '—'}</td>
                  <td>{humanize(row.agent_kind ?? '—')}</td>
                  <td className="num">{row.group_index}</td>
                  <td className="num">{row.instance_index}</td>
                  <td className="num">{row.endpoint_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            {rows.length} of {group.rows.length} rows · ⓘ derived · no editing
          </p>
        </>
      )}
      {idle && idle.count > 0 && (
        <>
          <h5 className="inspector-label">Idle attached agents</h5>
          <p className="muted">
            {idle.count} of {idle.attached} attached agents are not mapped to
            a rank. That is a design fact — the fabric is larger than the
            workload needs.
          </p>
          <table className="tbl">
            <thead><tr><th>agent</th><th>attached</th></tr></thead>
            <tbody>
              {Object.entries(idle.by_kind).map(([kind, count]) => (
                <tr key={kind}>
                  <td>{humanize(kind)}</td>
                  <td className="num">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function FabricGroupView({ group, route, showRoute }: {
  group: FabricGroup;
  route: CanonicalRoute | null;
  showRoute: boolean;
}): ReactElement {
  if (!group.available || !group.topology) {
    return (
      <section className="card">
        <h4>Fabric</h4>
        <p className="muted">No materialized topology for this revision.</p>
      </section>
    );
  }
  const counts = group.counts;
  const aggregate = group.detail_level === 'AGGREGATE';
  return (
    <section className="card">
      <div className="inspector-head">
        <h4>Fabric</h4>
        <span className="muted">
          detail {group.detail_level}
          {group.detail_thresholds
            ? ` (full ≤ ${group.detail_thresholds.full_detail_max}, `
              + `routers ≤ ${group.detail_thresholds.router_detail_max})`
            : ''}
        </span>
      </div>
      {aggregate ? (
        // Gate 8 §57: above the router threshold no per-router DOM is
        // created. The aggregate is the honest representation, and it says
        // why rather than silently dropping detail.
        <div className="fabric-aggregate">
          <p>
            <strong>{counts?.routers}</strong> routers ·{' '}
            <strong>{counts?.channels}</strong> channels ·{' '}
            <strong>{counts?.attached}</strong> attached ·{' '}
            <strong>{counts?.unused_seats}</strong> unused seats
          </p>
          <p className="muted">
            Above {group.detail_thresholds?.router_detail_max} routers the
            per-router graph is not drawn; the aggregate occupancy summary
            is. Nothing is hidden — the counts are the artifact's.
          </p>
        </div>
      ) : (
        <FabricInspector2D
          topology={group.topology}
          route={route}
          showRoute={showRoute}
        />
      )}
      <p className="muted">
        routers {counts?.routers} · channels {counts?.channels} · seats{' '}
        {counts?.seats} · attached {counts?.attached} · unused{' '}
        {counts?.unused_seats} ·{' '}
        <code>{group.topology.topology_hash.slice(0, 18)}…</code>
      </p>
    </section>
  );
}

function RoutingGroupView({ group, route, loading, error, onQuery }: {
  group: RoutingGroup;
  route: CanonicalRoute | null;
  loading: boolean;
  error: string | null;
  onQuery: (q: { routingClass: string; src: string; dst: string }) => void;
}): ReactElement {
  const [routingClass, setRoutingClass] = useState(group.default_class ?? '');
  const [src, setSrc] = useState('');
  const [dst, setDst] = useState('');
  const observation = group.observation;
  const routers = [...new Set((group.channel_hops ?? [])
    .map((h) => h.src_router))].sort((a, b) => a - b);
  return (
    <section className="card">
      <h4>Routing</h4>
      <div className="inspector-controls">
        <label>class
          <select value={routingClass}
                  onChange={(e) => setRoutingClass(e.target.value)}>
            {(group.routing_classes ?? []).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>source
          <select value={src} onChange={(e) => setSrc(e.target.value)}>
            <option value="">first</option>
            {routers.map((r) => (
              <option key={r} value={String(r)}>router {r}</option>
            ))}
          </select>
        </label>
        <label>destination
          <select value={dst} onChange={(e) => setDst(e.target.value)}>
            <option value="">last</option>
            {routers.map((r) => (
              <option key={r} value={String(r)}>router {r}</option>
            ))}
          </select>
        </label>
        <button className="btn"
                onClick={() => onQuery({ routingClass, src, dst })}>
          Overlay route on fabric
        </button>
      </div>

      <h5 className="inspector-label">CANONICAL DERIVED ROUTE</h5>
      {loading ? (
        <p className="muted">loading…</p>
      ) : error ? (
        <p className="bad">{error}</p>
      ) : route ? (
        <RoutePath route={route} />
      ) : (
        <p className="muted">
          No route selected. The route is walked server-side from the table
          frozen at certification time — this view never runs pathfinding.
        </p>
      )}
      <p className="muted">
        ⓘ this is a DERIVED EXPECTED state. It is not an observation.
      </p>

      {/* Gate 8 §29: a path existing is not the same as ROUTE_LEGAL. */}
      <p className="muted">
        ROUTE_LEGAL is a certificate claim, shown in the Verification
        section. A route rendering here does not by itself establish it.
      </p>

      {/* Gate 8 §59: expected and observed are never merged into one line. */}
      <h5 className="inspector-label">ROUTE OBSERVATION</h5>
      {observation?.available ? (
        <p className="good">✓ {observation.claim}</p>
      ) : (
        <p className="muted">
          Not available — {observation?.reason ?? 'no runtime execution'}.
          {observation?.source ? ` Source: ${observation.source}.` : ''}
        </p>
      )}
      {observation && (
        <p className="muted">
          ⓘ {observation.limit} · scope {observation.scope}
        </p>
      )}
    </section>
  );
}

function RoutePath({ route }: { route: CanonicalRoute }): ReactElement {
  return (
    <>
      <p className="route-path">
        {route.routers.map((r, i) => (
          <span key={`${r}-${i}`}>
            {i > 0 && <span className="route-arrow"> → </span>}
            <code>r{r}</code>
          </span>
        ))}
        {route.terminal && (
          <>
            <span className="route-arrow"> → </span>
            <code>{route.terminal}</code>
          </>
        )}
      </p>
      {!route.terminates && route.reason && (
        <p className="bad">route does not terminate: {route.reason}</p>
      )}
      {route.hops.length > 0 && (
        <details>
          <summary>channel sequence ({route.hops.length})</summary>
          <table className="tbl">
            <thead>
              <tr><th>channel</th><th>from</th><th>to</th></tr>
            </thead>
            <tbody>
              {route.hops.map((hop) => (
                <tr key={hop.channel_id}>
                  <td className="num">{hop.channel_id}</td>
                  <td className="num">r{hop.src_router}.p{hop.src_port}</td>
                  <td className="num">r{hop.dst_router}.p{hop.dst_port}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </>
  );
}

function ResourcesGroupView({ group }: { group: ResourcesGroup }): ReactElement {
  const witness = group.deadlock?.witness;
  return (
    <section className="card">
      <h4>Resources</h4>
      <h5 className="inspector-label">Virtual channels</h5>
      <table className="tbl">
        <thead>
          <tr><th>routing class</th><th>VC binding</th><th>transitions</th></tr>
        </thead>
        <tbody>
          {(group.traffic_class_to_vcs ?? []).map(([cls, vcs]) => (
            <tr key={cls}>
              <td>{cls}</td>
              <td className="num">{(vcs ?? []).join(', ')}</td>
              <td>{group.transitions_are_identity ? 'identity' : 'non-identity'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="kv-grid">
        <div className="kv"><span>derived VC count</span>
          <span className="num">{fmtNum(group.vc_count)}</span></div>
        <div className="kv"><span>escape designation</span>
          <span>{(group.escape_vcs ?? []).length > 0
            ? (group.escape_vcs ?? []).join(', ')
            : '(none — supported-but-unused)'}</span></div>
      </div>
      <p className="muted">ⓘ derived · no controls</p>

      <h5 className="inspector-label">Channel dependency graph</h5>
      <p className={CLAIM_STATUS_CLASS[group.deadlock?.status ?? ''] ?? 'muted'}>
        DEADLOCK_FREE {group.deadlock?.status}
        {group.deadlock?.method ? ` · ${group.deadlock.method}` : ''}
      </p>
      {witness && (
        <div className="kv-grid">
          <div className="kv"><span>acyclic</span>
            <span>{String(witness.acyclic)}</span></div>
          <div className="kv"><span>components &gt; 1</span>
            <span className="num">{fmtNum(witness.sccs_gt_1)}</span></div>
          <div className="kv"><span>nodes</span>
            <span className="num">{fmtNum(witness.node_count)}</span></div>
          <div className="kv"><span>edges</span>
            <span className="num">{fmtNum(witness.edge_count)}</span></div>
          <div className="kv"><span>route realization</span>
            <span>{witness.route_realization_scheme ?? '—'}</span></div>
        </div>
      )}
      <p className="muted">
        The witness is derived. Change editable upstream intent — topology
        family · concentration · arbitration · communication classes.
      </p>

      <h5 className="inspector-label">Arbitration</h5>
      <div className="kv-grid">
        {Object.entries(group.arbitration ?? {}).map(([key, value]) => (
          <div className="kv" key={key}>
            <span>{humanize(key)}</span>
            <span>{String(value ?? '—')}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function AddressDecodeGroupView({ group }: {
  group: AddressDecodeGroup;
}): ReactElement {
  return (
    <section className="card">
      <h4>Address decode</h4>
      <table className="tbl">
        <thead>
          <tr>
            <th>range</th><th>base</th><th>size</th>
            <th>target</th><th>endpoint</th>
          </tr>
        </thead>
        <tbody>
          {group.rows.map((row) => (
            <tr key={`${row.name}-${row.base}`}>
              <td>{row.name}</td>
              <td className="num">0x{(row.base ?? 0).toString(16)}</td>
              <td className="num">{fmtNum(row.size)}</td>
              {/* Gate 7 §23: the stable semantic target, not the
                  positional legacy index. */}
              <td>
                {humanize(row.target_agent_kind ?? '—')}
                {row.target_agent_instance != null
                  ? ` #${row.target_agent_instance}` : ''}
              </td>
              <td className="num">{row.target_endpoint_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="kv-grid">
        <div className="kv"><span>address transform</span>
          <span>{group.address_transform ?? '—'}</span></div>
        <div className="kv"><span>unmatched policy</span>
          <span>{group.unmatched_address_policy ?? '—'}</span></div>
      </div>
    </section>
  );
}

function ProvenanceGroupView({ group }: { group: ProvenanceGroup }): ReactElement {
  return (
    <section className="card">
      <h4>Provenance</h4>
      <div className="kv"><span>design identity</span>
        <Hash value={group.design_hash} /></div>
      <div className="kv"><span>resolved fabric</span>
        <Hash value={group.resolved_fabric_hash} /></div>
      <div className="kv"><span>certificate</span>
        <Hash value={group.certificate_id} /></div>
      <div className="kv"><span>compiler semantics</span>
        <span>v{group.compiler_semantics_version ?? '—'}</span></div>
      {group.artifact_chain && (
        <>
          <h5 className="inspector-label">Artifact chain</h5>
          <ArtifactChain chain={group.artifact_chain} />
        </>
      )}
      <details>
        <summary>artifact hashes ({Object.keys(group.artifact_hashes).length})</summary>
        <table className="tbl">
          <tbody>
            {Object.entries(group.artifact_hashes).map(([key, value]) => (
              <tr key={key}>
                <td className="muted">{humanize(key)}</td>
                <td><Hash value={value} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

const GROUP_LABEL: Record<string, string> = {
  summary: 'Summary',
  mapping: 'Mapping',
  fabric: 'Fabric',
  routing: 'Routing',
  resources: 'Resources',
  address_decode: 'Address decode',
  provenance: 'Provenance',
};

export default function CompileResultViewPanel({ result, revisionId }: {
  result: CompileResultView;
  revisionId: string;
}): ReactElement {
  const [group, setGroup] = useState('summary');
  // The canonical route is shared: Routing selects it, Fabric overlays it.
  // It is always walked server-side from the frozen table.
  const [route, setRoute] = useState<CanonicalRoute | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);

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

  if (!result.available || !result.groups) {
    return (
      <section className="card">
        <h3>Compile result</h3>
        <p className="muted">
          {result.reason ?? 'No compile result exists for this revision.'}
        </p>
        <p className="muted">
          A failed proof is not a fabric: no topology, routing, VC assignment
          or certificate is drawn for a refused compilation.
        </p>
      </section>
    );
  }
  const groups = result.groups;
  const certificate = result.certificate;
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
            <SummaryGroup group={groups.summary} />
            <CapabilityConsequences consequences={groups.summary
              ? (result as { capability_consequences?: CapabilityConsequence[] })
                .capability_consequences ?? [] : []} />
          </>
        )}
        {group === 'mapping' && <MappingGroupView group={groups.mapping} />}
        {group === 'fabric' && (
          <FabricGroupView group={groups.fabric} route={route}
                           showRoute={route !== null} />
        )}
        {group === 'routing' && (
          <RoutingGroupView group={groups.routing} route={route}
                            loading={routeLoading} error={routeError}
                            onQuery={queryRoute} />
        )}
        {group === 'resources' && (
          <ResourcesGroupView group={groups.resources} />
        )}
        {group === 'address_decode' && (
          <AddressDecodeGroupView group={groups.address_decode} />
        )}
        {group === 'provenance' && (
          <ProvenanceGroupView group={groups.provenance} />
        )}
      </div>

      {certificate && <CertificateSection certificate={certificate} />}
    </div>
  );
}

/** The four product claims over the ten canonical obligations. */
function CertificateSection({ certificate }: {
  certificate: CompileCertificate;
}): ReactElement {
  const analysis = certificate.deadlock_analysis;
  return (
    <section className="card">
      <h4>Verification</h4>
      <table className="tbl">
        <thead>
          <tr><th>claim</th><th>status</th><th>scope</th><th>contributing</th></tr>
        </thead>
        <tbody>
          {certificate.claims.map((claim) => (
            <tr key={claim.claim}>
              <td><code>{claim.claim}</code></td>
              <td className={CLAIM_STATUS_CLASS[claim.certificate_status] ?? 'muted'}>
                {claim.certificate_status}
              </td>
              <td className="muted">{claim.scope}</td>
              <td className="muted">
                {claim.contributing_obligations.map((o) => (
                  <code key={o}>{o} </code>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* A non-PASS deadlock claim must not read as a detected deadlock. */}
      {analysis && !analysis.detected_deadlock && (
        <p className="muted">
          Deadlock analysis: <strong>{analysis.analysis_verdict}</strong>
          {analysis.unsupported_reason
            ? ` — ${analysis.unsupported_reason}`
            : ' — no cycle witness exists'}
          . The certificate claim is not established; no deadlock was
          detected.
        </p>
      )}
      {analysis?.detected_deadlock && analysis.cycle_witness.length > 0 && (
        <>
          <h5 className="inspector-label">Cycle witness</h5>
          <p className="bad">
            A cycle exists in the channel-VC dependency graph.
          </p>
          <table className="tbl">
            <thead><tr><th>step</th><th>channel</th><th>VC</th></tr></thead>
            <tbody>
              {analysis.cycle_witness.map((node, i) => (
                <tr key={i}>
                  <td className="num">{i}</td>
                  <td className="num">ch {node.channel_id}</td>
                  <td className="num">vc {node.vc}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <RecoveryLinks owners={['fabric', 'router_behavior']} />
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
        <RecoveryLinks owners={['fabric', 'system']} />
      )}
    </section>
  );
}

/** Gate 8 §42: a failure points at editable upstream owners. It never
 * offers a manual route/VC edit, because those are compiler-derived. */
function RecoveryLinks({ owners }: { owners: string[] }): ReactElement {
  return (
    <p className="finding-remedies">
      {owners.map((owner) => (
        <span key={owner} className="btn btn-small" role="note">
          editable upstream: {owner}
        </span>
      ))}
      <span className="muted">
        Route and VC assignment are compiler-derived and cannot be edited
        here.
      </span>
    </p>
  );
}

/** Gate 8 §43/§46: downstream capability state, from the registry. */
function CapabilityConsequences({ consequences }: {
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
