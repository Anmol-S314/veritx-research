/** Telemetry + config plane content for the topology view.
 *
 * Neither plane is a second fabric: telemetry reads the executed run
 * (measured endpoint-pair matrix, plus the sampled link series when the run
 * was executed with the sampler), and config reads authored controls plus
 * derived interface state. Router totals join endpoint IDs through the
 * certified attachment; anything without a backing artifact keeps its
 * ExtensionPoint.
 */
import { useMemo, type ReactElement } from 'react';
import { api, ApiError } from '../../api';
import { useAsync } from '../../studio';
import { compileSummary, type LoomData, type TrafficPair } from './data';
import type { TopologyView } from '../../types';
import { ExtensionPoint, From, Kv, RailSection } from './parts';

export function TelemetryPanel({ data }: { data: LoomData }): ReactElement {
  const traffic = data.traffic.result.state === 'ready'
    ? data.traffic.result.data
    : null;
  const runId = data.latestRun?.run_id ?? null;
  const load = useAsync(
    () => (runId
      ? api.simLoad(runId)
      : Promise.reject(new Error('no executed run on this project'))),
    [runId],
  );

  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;
  const perRouter = useMemo(
    () => traffic && topology
      ? aggregateRouterTraffic(traffic.pairs, topology)
      : null,
    [traffic, topology],
  );
  const activeRouters = perRouter?.rows.filter((row) => row.sent > 0 || row.received > 0) ?? [];
  const quietRouters = perRouter?.rows.filter((row) => row.sent === 0 && row.received === 0) ?? [];

  if (!traffic) {
    return (
      <ExtensionPoint
        title="Telemetry — no measured traffic"
        needs="an executed run with a measured endpoint-pair matrix; router totals also require its certified attachment"
      />
    );
  }

  return (
    <div className="loom-view">
      <RailSection
        title="Measured endpoint matrix · flits"
        note="Rows are source endpoints; columns are destination endpoints. Stronger tint means more measured flits. This is not a router or per-link utilization map."
      >
        <TrafficMatrixHeatmap matrix={traffic.flit_matrix} />
      </RailSection>
      <RailSection
        title="Per-router flits (attachment-derived)"
        note="Measured endpoint-pair flits grouped by router through this revision's certified attachment; no new measurement."
      >
        <From
          origin="MEASURED"
          artifact="traffic_matrix"
          note="pair counts are measured; router grouping uses the certified attachment"
          data={data}
        />
        {topology && <From
          origin="DERIVED"
          artifact="attachment"
          note="endpoint-to-router mapping for the aggregate"
          data={data}
        />}
        {!topology && <p className="muted">Waiting for this revision's certified attachment; router totals are not inferred from endpoint IDs.</p>}
        {perRouter && perRouter.unresolvedPairs.length > 0 && (
          <p className="warn" role="note">
            {perRouter.unresolvedPairs.length} endpoint pair(s), {perRouter.unresolvedFlits.toLocaleString()} flits, have no seat in this revision and are excluded from router totals.
          </p>
        )}
        <table className="tbl">
          <thead>
            <tr><th>router</th><th className="num">sent flits</th><th className="num">received flits</th></tr>
          </thead>
          <tbody>
            {activeRouters.length > 0 ? activeRouters.map((row) => (
              <tr key={row.routerId}>
                <td><code>R{row.routerId}</code></td>
                <td className="num">{row.sent.toLocaleString()}</td>
                <td className="num">{row.received.toLocaleString()}</td>
              </tr>
            )) : (
              <tr><td colSpan={3}>No measured pairs map to this revision.</td></tr>
            )}
          </tbody>
        </table>
        {quietRouters.length > 0 && (
          <details className="subtle">
            <summary>{quietRouters.length} routers with no matrix-attributed flits</summary>
            <p className="muted">{quietRouters.map((row) => `R${row.routerId}`).join(', ')}</p>
          </details>
        )}
      </RailSection>

      <RailSection
        title="Sampled link series (measured)"
        note="Per-link counters from the run's sampled-counters artifact. Only runs executed with the sampler carry it."
      >
        <From
          origin="MEASURED"
          artifact="run"
          note="the run's own counters; absence refuses below instead of rendering zeros"
          data={data}
        />
        {load.result.state === 'loading' && (
          <p className="muted" role="status">reading sampled link series…</p>
        )}
        {load.result.state === 'error' && (
          <p className="warn" role="alert">
            {(() => {
              const e = load.result.error;
              if (!(e instanceof ApiError)) return e.message;
              // Server details already embed their code ("NO_RUN: …").
              return e.message.startsWith(`${e.code}:`) ? e.message : `${e.code}: ${e.message}`;
            })()}
            {' '}— the matrix-derived table above is unaffected.
          </p>
        )}
        {load.result.state === 'ready' && (
          <>
            <Kv label="cycles sampled" value={load.result.data.cycles_sampled.toLocaleString()} mono />
            <Kv label="sample period" value={`${load.result.data.sample_period_cycles} cycles`} mono />
            <Kv label="capacity" value={load.result.data.capacity_formula} mono />
            <table className="tbl">
              <thead>
                <tr><th>channel</th><th className="num">flits</th><th className="num">util</th><th className="num">peak</th></tr>
              </thead>
              <tbody>
                {load.result.data.channels.slice(0, 12).map((c) => (
                  <tr key={c.logical_channel_id}>
                    <td><code>{c.logical_channel_id}</code></td>
                    <td className="num">{c.flits_total.toLocaleString()}</td>
                    <td className="num">{(c.utilization * 100).toFixed(1)}%</td>
                    <td className="num">{(c.peak_window_utilization * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {load.result.data.channels.length > 12 && (
              <p className="muted">…{load.result.data.channels.length - 12} further channels (table capped).</p>
            )}
          </>
        )}
      </RailSection>
    </div>
  );
}

/** Whether the frozen compile-result view declares a control plane (Plane C).
 *
 *  The view exposes the control-plane child as a hash
 *  (``compiled_system.children.legacy_control_plane``) and its binding scope
 *  (``scopes.control_plane``). A non-null child is the multi-plane fact: the
 *  compiler materialized a second subnet. The view carries no Plane C timing
 *  or traffic, so that declared structure is the only claim this returns. */
export function controlPlaneDeclaration(data: LoomData): {
  declared: boolean;
  scope: string | null;
} {
  const result = data.compileResult.result.state === 'ready'
    ? data.compileResult.result.data
    : null;
  const system = result?.compiled_system ?? null;
  const child = system?.children?.legacy_control_plane ?? null;
  return {
    declared: typeof child === 'string' && child.length > 0,
    scope: system?.scopes?.control_plane ?? null,
  };
}

export function ControlPlanePanel({ data }: { data?: LoomData }): ReactElement {
  const declaration = data
    ? controlPlaneDeclaration(data)
    : { declared: false, scope: null };
  return (
    <>
      {declaration.declared && (
        <RailSection
          title="Control plane — declared structure (not drawn)"
          note="Plane C is a second subnet the compiler materializes when the topology declares it. This revision binds its declared structure only; the compile result carries no Plane C timing or traffic, so none is claimed."
        >
          <From
            origin="DERIVED"
            artifact="compile_result"
            note="the control-plane child artifact and its binding scope, as the frozen compile result exposes them"
            data={data ?? null}
          />
          <Kv label="control plane (Plane C)" value={<code>declared</code>} />
          {declaration.scope && (
            <Kv label="binding scope" value={<code>{declaration.scope}</code>} />
          )}
        </RailSection>
      )}
      <ExtensionPoint
        title="Control plane — not visualized"
        needs="an independent, revision-bound control-plane artifact and verified behavior. Configuration fields are not a control-plane diagram."
      >
        {declaration.declared && (
          <p className="muted">
            A control plane is declared in this revision, but a declared
            structure is not a drawn plane — it still needs the revision-bound
            artifact above.
          </p>
        )}
      </ExtensionPoint>
    </>
  );
}

export function aggregateRouterTraffic(
  pairs: TrafficPair[],
  topology: TopologyView,
): {
  rows: { routerId: number; sent: number; received: number }[];
  unresolvedPairs: TrafficPair[];
  unresolvedFlits: number;
} {
  const endpointToRouter = new Map<number, number>();
  for (const endpoint of topology.endpoints) {
    if (!endpointToRouter.has(endpoint.endpoint_id)) {
      endpointToRouter.set(endpoint.endpoint_id, endpoint.router_id);
    }
  }
  const totals = new Map(topology.routers.map((r) => [
    r.router_id, { routerId: r.router_id, sent: 0, received: 0 },
  ]));
  const unresolvedPairs: TrafficPair[] = [];
  let unresolvedFlits = 0;
  for (const pair of pairs) {
    const srcRouter = endpointToRouter.get(pair.src);
    const dstRouter = endpointToRouter.get(pair.dst);
    const src = srcRouter === undefined ? undefined : totals.get(srcRouter);
    const dst = dstRouter === undefined ? undefined : totals.get(dstRouter);
    if (!src || !dst) {
      unresolvedPairs.push(pair);
      unresolvedFlits += pair.flits;
      continue;
    }
    src.sent += pair.flits;
    dst.received += pair.flits;
  }
  return { rows: [...totals.values()], unresolvedPairs, unresolvedFlits };
}

export function TrafficMatrixHeatmap({ matrix }: { matrix: number[][] }): ReactElement {
  const peak = matrix.reduce(
    (current, row) => row.reduce((rowPeak, value) => Math.max(rowPeak, value), current),
    0,
  );
  return (
    <div className="loom-traffic-matrix-scroll" role="region" aria-label="Measured traffic matrix">
      <table className="loom-traffic-matrix">
        <caption>Measured flits by source and destination endpoint</caption>
        <thead>
          <tr>
            <th scope="col">src ↓ / dst →</th>
            {matrix.map((_, dst) => <th scope="col" key={dst}>E{dst}</th>)}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, src) => (
            <tr key={src}>
              <th scope="row">E{src}</th>
              {matrix.map((_, dst) => {
                const count = row[dst] ?? 0;
                const intensity = peak > 0 ? Math.max(0, Math.min(1, count / peak)) : 0;
                return (
                  <td key={dst} aria-label={`Endpoint ${src} to endpoint ${dst}: ${count.toLocaleString()} flits`}>
                    <span className="loom-traffic-heat" style={{ opacity: intensity * 0.22 }} aria-hidden="true" />
                    <span className="loom-traffic-value">{count.toLocaleString()}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ConfigPanel({ data }: { data: LoomData }): ReactElement {
  const summary = compileSummary(data);
  const der = summary?.derived ?? {};
  const groups = data.agents;
  const design = data.design;
  const g = design?.noc_guided ?? null;
  const locked = design?.locked_derived ?? null;
  const vcCount = (der.vc_count as number | undefined)
    ?? locked?.vc_count ?? null;
  const routing = locked?.routing
    ?? ((der.routing_classes as unknown[] | undefined)
      ?.filter((c): c is string => typeof c === 'string').join(', '))
    ?? null;

  if (groups.length === 0) {
    return (
      <ExtensionPoint
        title="Config — no authored agents"
        needs="a draft with agent groups; protocols, widths and domains are read off them"
      />
    );
  }

  return (
    <div className="loom-view">
      <RailSection
        title="Authored controls"
        note="What the draft configures; the compiler may still refuse it."
      >
        <From
          origin="AUTHORED"
          artifact="draft"
          data={data}
        />
        <Kv label="link width" value={g?.link_width != null ? `${g.link_width} bits` : 'unconstrained'} mono />
        <Kv label="arbitration" value={<code>{g?.arbitration ?? 'unconstrained'}</code>} />
        <Kv label="concentration" value={g?.concentration ?? 'unconstrained'} mono />
        <Kv label="family" value={<code>{g?.topology_family ?? '—'}</code>} />
        <p className="muted">Unconstrained means the draft leaves it to the compiler — not zero, not missing.</p>
      </RailSection>

      <RailSection
        title="Interface state per group"
        note="Protocols, widths and domains as authored; VC count and routing as derived."
      >
        <From
          origin="AUTHORED"
          artifact="draft"
          note="interface fields are authored; VC count and routing rows below are DERIVED · compile_result"
          data={data}
        />
        <table className="tbl">
          <thead>
            <tr><th>kind</th><th className="num">count</th><th>protocol</th><th className="num">data / addr</th><th>clock</th><th>power</th></tr>
          </thead>
          <tbody>
            {groups.map((a) => (
              <tr key={a.kind}>
                <td><code>{a.kind}</code></td>
                <td className="num">{a.count}</td>
                <td>{a.protocol ?? '—'}</td>
                <td className="num">{a.data_width ?? '—'} / {a.addr_width ?? '—'}</td>
                <td>{a.clock_domain ?? <span className="muted">undeclared</span>}</td>
                <td>{a.power_domain ?? <span className="muted">undeclared</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Kv label={`routing (${data.revisionId ? data.revisionId.slice(-3) : 'no revision'})`} value={<code>{routing ?? '—'}</code>} />
        <Kv label={`VC count (${data.revisionId ? data.revisionId.slice(-3) : 'no revision'})`} value={vcCount ?? '—'} mono />
        {data.dirty && data.revisionId && (
          <p className="warn" role="note">
            Derived rows describe revision {data.revisionId} — the draft has
            uncompiled changes, so they do not describe the edited graph.
          </p>
        )}
      </RailSection>
    </div>
  );
}
