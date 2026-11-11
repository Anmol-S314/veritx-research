/** Measured traffic over the certified fabric: which links carry flits,
 * which never do, and packets moving along the real routes.
 *
 * Counts are measured (counted from the executed trace) and attribution is
 * derived (each pair's flits walked over the route table frozen at
 * certification). No per-cycle series exists, so nothing here claims to be
 * occupancy over time — a channel at zero flits is idle over the whole run,
 * which is a fact about the run, not a snapshot.
 */
import { useEffect, useMemo, useState, type ReactElement } from 'react';
import { Link, useAsync } from '../../studio';
import type { CanonicalRoute } from '../../api';
import {
  expectedChannelLoad, loomPlan, pairKey, resolveRouterPairs,
  ROUTE_SWEEP_CONCURRENCY, sweepRoutes, type LoomData,
} from './data';
import { Kv, Panes, RailSection, From, SummaryStrip, ExtensionPoint } from './parts';
import { HottestLinkBreakdown } from './SimLinkBreakdown';

interface Flow { src: number; dst: number; flits: number; route: CanonicalRoute }

/** Upper bound on how many pairs are attributed and animated. Each pair costs
 *  one route request, so this is a work budget rather than a display limit: a
 *  measured matrix is usually inside it, and any shortfall is stated rather than
 *  hidden. Requests resolve in bounded batches so a large matrix does not flood
 *  the gateway. */
const MAX_ROUTE_PAIRS = 4096;

export default function TrafficLoom({ data }: { data: LoomData }): ReactElement {
  const traffic = data.traffic.result.state === 'ready' ? data.traffic.result.data : null;
  const topology = data.topology.result.state === 'ready' ? data.topology.result.data : null;
  const runId = data.latestRun?.run_id ?? null;
  const [playing, setPlaying] = useState(false);
  const [tick, setTick] = useState(0);

  // The busiest pairs, so route resolution stays bounded.
  const plan = useMemo(() => loomPlan(data), [data]);
  const routingClass = plan.routingClass;
  const sortedPairs = useMemo(() => (traffic
    ? [...traffic.pairs].sort((a, b) => b.flits - a.flits)
    : []), [traffic]);
  const topPairs = useMemo(() => sortedPairs.slice(0, MAX_ROUTE_PAIRS), [sortedPairs]);

  // Endpoint pairs become router pairs through the certified attachment only.
  // Pairs with no certified seat are counted, never queried as though an
  // endpoint id were a router id.
  const resolved = useMemo(
    () => resolveRouterPairs(topPairs, topology),
    [topPairs, topology],
  );

  const routes = useAsync(() => {
    if (!resolved.routable.length || !data.revisionId || !routingClass) {
      return Promise.resolve(null);
    }
    // One query per unique router pair — endpoint pairs sharing routers fan
    // out from the same answer — so concentration keeps this far below one
    // request per traced pair. Batched like the old per-pair walk.
    return sweepRoutes(
      data.revisionId, routingClass, resolved.routable,
      undefined, ROUTE_SWEEP_CONCURRENCY,
    );
  }, [resolved, data.revisionId, routingClass]);

  const routeMap = routes.result.state === 'ready'
    ? routes.result.data?.routes ?? new Map<string, CanonicalRoute>()
    : new Map<string, CanonicalRoute>();
  const sweepFailed = routes.result.state === 'ready' ? routes.result.data?.failed ?? 0 : 0;
  const sweepUnterminated = routes.result.state === 'ready' ? routes.result.data?.unterminated ?? 0 : 0;
  const unattributed = resolved.unresolvable.length + sweepFailed + sweepUnterminated;

  const load = useMemo(
    () => expectedChannelLoad(traffic, routeMap, topology),
    [traffic, routeMap, topology],
  );

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setTick((v) => (v + 1) % 1000), 120);
    return () => clearInterval(t);
  }, [playing]);

  if (!traffic) {
    return (
      <Panes stage={
        <ExtensionPoint
          title="No measured traffic to show"
          needs="an executed run whose trace was counted into a pair matrix; nothing here is estimated"
        />
      } />
    );
  }
  if (!topology) {
    return <Panes stage={<ExtensionPoint title="No certified fabric" needs="a compiled revision with a TopologyView to attribute flits onto" />} />;
  }

  const used = new Set(load.map((l) => l.channelId));
  const busiest = load.length ? Math.max(...load.map((l) => l.flits)) : 0;
  const idle = topology.channels.filter((c) => !used.has(c.channel_id)).length;
  const pos = new Map<number, { x: number; y: number }>();
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
  for (const r of topology.routers) {
    const x = r.coordinates?.[0] ?? 0;
    const y = (r.coordinates?.[1] ?? 0) + (x / 100);
    pos.set(r.router_id, { x, y });
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  const sx = (x: number): number => 40 + ((x - minX) / Math.max(1, maxX - minX)) * 520;
  const sy = (y: number): number => 40 + ((y - minY) / Math.max(1, maxY - minY)) * 420;
  const flows: Flow[] = topPairs
    .map((p) => ({ src: p.src, dst: p.dst, flits: p.flits, route: routeMap.get(pairKey(p.src, p.dst)) as CanonicalRoute | undefined }))
    .filter((f): f is Flow => Boolean(f.route));

  return (
    <Panes
      left={
        <>
          <RailSection title="Run">
            <From origin="MEASURED" artifact="run" data={data} />
            <Kv label="run" value={<code>{runId ?? '—'}</code>} />
            <Kv label="backend" value={<code>{data.latestRun?.backend ?? '—'}</code>} />
            <Kv label="status" value={data.latestRun?.status ?? '—'} />
          </RailSection>
          <RailSection title="Flits on the fabric">
            <From origin="MEASURED" artifact="traffic_matrix" data={data} />
            <Kv label="pairs counted" value={String(traffic.distinct_pairs)} mono />
            <Kv label="packets" value={traffic.packets.toLocaleString()} mono />
            <Kv label="flits" value={traffic.flits.toLocaleString()} mono />
            <Kv label="channels carrying" value={`${used.size} of ${topology.channels.length}`} mono />
            <Kv label="channels idle" value={String(idle)} mono />
            <p className="muted">
              Attribution is derived: each pair's measured flits are walked over
              the route table frozen at certification, resolved through the
              certified attachment.
            </p>
            {unattributed > 0 && (
              <p className="warn">
                {unattributed} traced pair(s) resolved to no route
                ({resolved.unresolvable.length} unseated
                {sweepFailed > 0 && `, ${sweepFailed} failed`}
                {sweepUnterminated > 0 && `, ${sweepUnterminated} unterminated`}),
                so idle channels may carry unattributed load.
              </p>
            )}
            {unattributed === 0 && (
              <p className="muted">A channel with no flits carried none in this run.</p>
            )}
            {sortedPairs.length > topPairs.length && (
              <p className="muted">
                Showing the {topPairs.length} busiest of {sortedPairs.length} measured
                pairs (route-request budget); channels used by the remainder may
                read as idle here.
              </p>
            )}
          </RailSection>
          <RailSection title="Playback">
            <div className="row" style={{ gap: 8 }}>
              <button type="button" className="btn" onClick={() => setPlaying((p) => !p)}>
                {playing ? 'pause' : 'play'}
              </button>
              <span className="muted">packets along the real routes</span>
            </div>
            {routes.result.state === 'loading' && <p className="muted" role="status">resolving routes… ({resolved.routable.length} pairs)</p>}
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            { k: 'Channels used', v: String(used.size), tone: 'info' },
            { k: 'Channels idle', v: String(idle) },
            { k: 'Busiest link', v: busiest ? `${busiest.toLocaleString()} flits` : '—', tone: 'warn' },
            { k: 'Attribution', v: routes.result.state === 'ready' ? 'route-resolved' : 'pending' },
          ]} />
          <svg width="100%" height={520} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }}>
            {topology.channels.map((c) => {
              const a = pos.get(c.src_router);
              const b = pos.get(c.dst_router);
              if (!a || !b) return null;
              const load_ = load.find((l) => l.channelId === c.channel_id);
              const heat = load_ && busiest ? load_.flits / busiest : 0;
              return (
                <line key={c.channel_id}
                  x1={sx(a.x)} y1={sy(a.y)} x2={sx(b.x)} y2={sy(b.y)}
                  stroke={heat > 0 ? `rgba(224,101,90,${0.25 + 0.7 * heat})` : 'var(--border)'}
                  strokeWidth={heat > 0 ? 1.5 + 6 * heat : 1}
                  data-testid={`channel-${c.channel_id}`}>
                  <title>{`channel ${c.channel_id}: ${load_ ? `${load_.flits.toLocaleString()} flits` : 'idle'}`}</title>
                </line>
              );
            })}
            {/* packets in flight, positioned along their real hop path */}
            {flows.map((f, fi) => {
              const hops = f.route.hops;
              if (!hops.length) return null;
              const phase = (tick / 40 + fi * 0.17) % 1;
              const idx = Math.min(hops.length - 1, Math.floor(phase * hops.length));
              const hop = hops[idx];
              const a = pos.get(hop.src_router);
              const b = pos.get(hop.dst_router);
              if (!a || !b) return null;
              const t = (phase * hops.length) % 1;
              return (
                <circle key={`${f.src}-${f.dst}`}
                  cx={sx(a.x + (b.x - a.x) * t)} cy={sy(a.y + (b.y - a.y) * t)}
                  r={4} fill="var(--accent)" opacity={0.9}
                  data-testid={`flit-${f.src}-${f.dst}`}>
                  <title>{`${f.src} → ${f.dst}: ${f.flits.toLocaleString()} flits`}</title>
                </circle>
              );
            })}
            {topology.routers.map((r) => {
              const p = pos.get(r.router_id);
              if (!p) return null;
              return (
                <g key={r.router_id} transform={`translate(${sx(p.x)},${sy(p.y)})`}>
                  <circle r={15} fill="var(--bg-raise)" stroke="var(--border)" />
                  <text textAnchor="middle" y={4} fontSize={9} fill="var(--text)" fontFamily="monospace">
                    R{r.router_id}
                  </text>
                </g>
              );
            })}
          </svg>
          <p className="loom-note">
            Red links carry measured flits, grey links carried none in this run.
            Packets animate along the certified route for each measured pair.
          </p>
        </div>
      }
      right={
        <>
          <RailSection title="Busiest links">
            <From origin="DERIVED" artifact="traffic_matrix" note="measured pair counts walked over the frozen route table" data={data} />
            <table className="tbl">
              <thead><tr><th>link</th><th className="num">flits</th><th className="num">pairs</th></tr></thead>
              <tbody>
                {[...load].sort((a, b) => b.flits - a.flits).slice(0, 12).map((l) => (
                  <tr key={l.channelId}>
                    <td><code>{l.srcRouter}→{l.dstRouter}</code></td>
                    <td className="num">{l.flits.toLocaleString()}</td>
                    <td className="num">{l.pairs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {load.length === 0 && <p className="muted">No pair resolved a terminating route yet.</p>}
          </RailSection>
          <HottestLinkBreakdown data={data} runId={runId} />
          {data.projectId && (
            <p className="muted">
              <Link className="link" to={`/projects/${data.projectId}/loom/simulation`}>
                Simulation view →
              </Link>
            </p>
          )}
        </>
      }
    />
  );
}
