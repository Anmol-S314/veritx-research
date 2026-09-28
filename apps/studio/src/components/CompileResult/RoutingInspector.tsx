import { useState, type ReactElement } from 'react';
import type { CanonicalRoute, RoutingGroup } from '../../api';
import { useSelection } from './selection';

/** Routing inspector: source endpoint/router, destination endpoint/router,
 * routing class → server-walked canonical DERIVED EXPECTED route with an
 * overlay on Fabric, hop count, channel sequence, VC/resource context and
 * the expected route identity.
 *
 * Runtime route observation stays separate and is never merged into the
 * derived route.
 */
export default function RoutingInspector({ group, route, loading, error,
  onQuery, onInspectChannel, onJump }: {
  group: RoutingGroup;
  route: CanonicalRoute | null;
  loading: boolean;
  error: string | null;
  onQuery: (q: { routingClass: string; src: string; dst: string }) => void;
  onInspectChannel: (channelId: number) => void;
  onJump: (tab: string) => void;
}): ReactElement {
  const [routingClass, setRoutingClass] = useState(group.default_class ?? '');
  const [src, setSrc] = useState('');
  const [dst, setDst] = useState('');
  const { select } = useSelection();
  const observation = group.observation;
  const routers = [...new Set((group.channel_hops ?? [])
    .map((h) => h.src_router))].sort((a, b) => a - b);
  return (
    <section className="card">
      <h4>Routing</h4>
      <div className="inspector-controls">
        <label>class
          <select value={routingClass}
                  onChange={(e) => setRoutingClass(e.target.value)}
                  aria-label="Routing class">
            {(group.routing_classes ?? []).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>source
          <select value={src} onChange={(e) => setSrc(e.target.value)}
                  aria-label="Source router">
            <option value="">first</option>
            {routers.map((r) => (
              <option key={r} value={String(r)}>router {r}</option>
            ))}
          </select>
        </label>
        <label>destination
          <select value={dst} onChange={(e) => setDst(e.target.value)}
                  aria-label="Destination router">
            <option value="">last</option>
            {routers.map((r) => (
              <option key={r} value={String(r)}>router {r}</option>
            ))}
          </select>
        </label>
        <button className="btn"
                onClick={() => {
                  select({ kind: 'routing_class', id: routingClass });
                  onQuery({ routingClass, src, dst });
                }}>
          Overlay route on fabric
        </button>
      </div>

      <h5 className="inspector-label">CANONICAL DERIVED ROUTE</h5>
      {loading ? (
        <p className="muted">loading…</p>
      ) : error ? (
        <p className="bad">{error}</p>
      ) : route ? (
        <RoutePath route={route} onInspectChannel={onInspectChannel}
                   onJump={onJump} />
      ) : (
        <p className="muted">
          No route selected. The route is walked server-side from the table
          frozen at certification time — this view never runs pathfinding.
        </p>
      )}
      <p className="muted">
        ⓘ this is a DERIVED EXPECTED state. It is not an observation.
      </p>

      <p className="muted">
        ROUTE_LEGAL is a certificate claim, shown under Verify. A route
        rendering here does not by itself establish it.
      </p>

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

function RoutePath({ route, onInspectChannel, onJump }: {
  route: CanonicalRoute;
  onInspectChannel: (channelId: number) => void;
  onJump: (tab: string) => void;
}): ReactElement {
  return (
    <>
      <div className="kv-grid">
        <div className="kv"><span>expected route identity</span>
          <span><code>{route.routing_class}</code> r{route.src} → r{route.dst}
          </span></div>
        <div className="kv"><span>hop count</span>
          <span className="num">{route.hops.length}</span></div>
      </div>
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
        <details open>
          <summary>channel sequence ({route.hops.length})</summary>
          <table className="tbl">
            <thead>
              <tr><th>channel</th><th>from</th><th>to</th><th></th></tr>
            </thead>
            <tbody>
              {route.hops.map((hop) => (
                <tr key={hop.channel_id}>
                  <td className="num">{hop.channel_id}</td>
                  <td className="num">r{hop.src_router}.p{hop.src_port}</td>
                  <td className="num">r{hop.dst_router}.p{hop.dst_port}</td>
                  <td>
                    <button className="btn btn-small"
                            onClick={() => {
                              onInspectChannel(hop.channel_id);
                              onJump('fabric');
                            }}>
                      Inspect channel
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </>
  );
}
