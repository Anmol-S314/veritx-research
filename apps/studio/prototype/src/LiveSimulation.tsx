import { useEffect, useMemo, useState } from 'react';
import { gateway, gatewayReason, type CanonicalRoute, type SimLink, type SimLoad, type Topology } from './gateway';
import { useProject, type LoadedProject, type LoadedRun } from './project';
import { Badge, Button, Empty, Notice, PageLink, Section } from './ui';
import { TopologyGraph } from './TopologyGraph';
import { cappedClass } from './format';
import { revisionLabel, runVersionLabels, runVersionOrder } from './runLabel';
import { resolveRoutes } from './routeResolution';
import { aggregateRouterLoad, type RouterLoad } from './routerLoad';
import { buildChannelIndex, channelMatchLabel, matchMeasuredChannel } from './channelTopology';
import { attributionSummary, channelCosts, median, utilizationInRange, type UtilizationRange } from './channelAnalysis';
import { useSimLoad, useSimSeries } from './measuredData';
import { useRunTopology } from './runTopology';
import { contextTarget } from './contextSelection';
export { useRunTopology } from './runTopology';
import { revealChannelDetail, useChannelSelection } from './channelSelection';
import { portWiresUsable, usePortWires } from './portWires';
import { ChannelWindowChart, ChannelWindowMatrix } from './ChannelActivity';
import { fetchVerifiedArtifact } from './RawArtifacts';
import { decodeInjectionTrace, selectInjectionTrace } from './trace';
import { FlitPlayback } from './TraceView';
import { ObservedPlayback } from './ObservedPlayback';
import { SharedFabricProjection } from './SharedFabricProjection';
import type { SharedRouteTable } from './sharedRoutes';

// The Studio Loom simulation workspace, ported to the live gateway. Everything here is either
// measured (pair counts, sampled counters) or derived and labelled (route attribution).

type Pair = { src: number; dst: number; packets: number; flits: number };
type ChannelLoad = { channelId: number; srcRouter: number; srcPort: number; dstRouter: number; dstPort: number; flits: number; pairs: number };
const SWEEP_LIMIT = 60;
const channelKey = (srcRouter: number, srcPort: number, dstRouter: number, dstPort: number) => `${srcRouter}:${srcPort}->${dstRouter}:${dstPort}`;

export function ObservedRunPlayback({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const topology = useRunTopology(project, run);
  const files = run.artifacts?.bundle?.files ?? {};
  const path = Object.keys(files).find(name => name.endsWith('/observed_hops.log') || name === 'observed_hops.log');
  const checksum = path ? files[path] : '';
  const wires = usePortWires(run, topology);
  const [capture, setCapture] = useState<{ text?: string; error?: string }>({});
  const [fabric, setFabric] = useState<{ table: SharedRouteTable | null; config: string }>({ table: null, config: '' });
  useEffect(() => {
    let live = true;
    setCapture({});
    if (path) void fetchVerifiedArtifact(run.detail.run_id, path, checksum).then(bytes => { if (live) setCapture({ text: new TextDecoder('utf-8', { fatal: true }).decode(bytes) }); }).catch(error => { if (live) setCapture({ error: gatewayReason(error) }); });
    return () => { live = false; };
  }, [path, checksum, run.detail.run_id]);
  useEffect(() => {
    let live = true;
    const configPath = Object.keys(files).find(name => name.endsWith('/config.cfg'));
    if (!configPath) { setFabric({ table: null, config: '' }); return; }
    void Promise.all([gateway.compileResult(run.detail.revision_id), fetchVerifiedArtifact(run.detail.run_id, configPath, files[configPath])])
      .then(([compiled, bytes]) => { if (live) setFabric({ table: (compiled.groups?.routing as { shared_route?: SharedRouteTable } | undefined)?.shared_route ?? null, config: new TextDecoder('utf-8', { fatal: true }).decode(bytes) }); })
      .catch(() => { if (live) setFabric({ table: null, config: '' }); });
    return () => { live = false; };
  }, [run.detail.run_id, run.detail.revision_id, files]);
  const sample = (run.detail as { observed_hop_capture?: { sample?: { declared_packets?: number; stride?: number; sampled_packets?: number } } }).observed_hop_capture?.sample;
  return <Section title="Observed flit capture" actions={<><Badge tone="blue" title="Recorded router receipt/send events, separate from projected playback.">Bounded stride sample</Badge>{sample?.stride ? <Badge>every {sample.stride}th of {sample.declared_packets?.toLocaleString() ?? '—'} packets</Badge> : null}</>}>
    {!path ? <Notice tone="amber">This historical bundle has no observed watch capture. Run a new sampled evaluation to capture the stride sample of native packet ids.</Notice> : capture.error ? <Notice tone="red">{capture.error}</Notice> : capture.text !== undefined && topology ? <ObservedPlayback text={capture.text} topology={topology} table={fabric.table} config={fabric.config} portWires={portWiresUsable(wires.map) ? wires.map.ports : undefined} /> : <p>Reading verified observed events…</p>}
  </Section>;
}

// The bundle records requested injections, not observed hops. This is the same projected playback
// as the Trace Viewer, placed on the Topology Overlay so simulation and visualization live together.
export function RunFlitPlayback({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const { health } = useProject();
  const topology = useRunTopology(project, run);
  const files = run.artifacts?.bundle?.files ?? {};
  const tracePath = selectInjectionTrace(Object.keys(files));
  const traceChecksum = tracePath ? files[tracePath] : '';
  const [state, setState] = useState<{ phase: 'loading' | 'ready' | 'absent' | 'error'; decoded?: ReturnType<typeof decodeInjectionTrace>; reason?: string }>({ phase: 'loading' });
  useEffect(() => {
    let live = true;
    if (!tracePath) {
      setState({ phase: 'absent', reason: 'This run bundle carries no injection trace (workload.trace). Aggregate pair counts have no cycle timing, so no playback is drawn.' });
      return;
    }
    if (!health?.features?.artifact_bytes) {
      setState({ phase: 'absent', reason: 'The gateway does not serve verified artifact bytes, so the sealed trace cannot be decoded.' });
      return;
    }
    setState({ phase: 'loading' });
    fetchVerifiedArtifact(run.detail.run_id, tracePath, traceChecksum)
      .then(bytes => {
        const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        const decoded = decodeInjectionTrace(text, 20000);
        if (live) setState({ phase: 'ready', decoded });
      })
      .catch(error => { if (live) setState({ phase: 'error', reason: gatewayReason(error) }); });
    return () => { live = false; };
  }, [run.detail.run_id, tracePath, traceChecksum, health?.features?.artifact_bytes]);
  return <Section title="Flit playback · projected" actions={<><PageLink page="analysis/trace">Trace rows</PageLink><Badge tone={state.phase === 'ready' ? 'green' : 'amber'} title="Requested injections on the revision's declared routes at declared channel latency; not observed hops.">{state.phase === 'ready' ? 'Trace injections' : 'No trace'}</Badge></>}>
    {state.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the sealed injection trace…</p>}
    {state.phase === 'absent' && <Notice tone="amber">{state.reason}</Notice>}
    {state.phase === 'error' && <Notice tone="red">{state.reason}</Notice>}
    {state.phase === 'ready' && state.decoded && <>
      <div className="topology-playback">
        {topology?.shared_links?.length ? <SharedFabricProjection run={run} topology={topology} decoded={state.decoded} mode="playback" /> : <FlitPlayback decoded={state.decoded} topology={topology} revisionId={run.detail.revision_id} />}
      </div>
    </>}
  </Section>;
}

export function RouteSweep({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const matrix = run.matrix;
  const pairs = matrix?.pairs ?? [];
  const topology = useRunTopology(project, run);
  const candidates = useMemo(() => pairs.filter(p => p.src !== p.dst && p.flits > 0).sort((a, b) => b.flits - a.flits).slice(0, SWEEP_LIMIT), [pairs]);
  const routerOf = useMemo(() => {
    const map = new Map<number, number>();
    for (const endpoint of topology?.endpoints ?? []) if (!map.has(endpoint.endpoint_id)) map.set(endpoint.endpoint_id, endpoint.router_id);
    return map;
  }, [topology]);
  const resolvable = useMemo(() => {
    const out: { pair: Pair; srcRouter: number; dstRouter: number }[] = [];
    let unresolvable = 0;
    for (const pair of candidates) {
      const srcRouter = routerOf.get(pair.src), dstRouter = routerOf.get(pair.dst);
      if (srcRouter === undefined || dstRouter === undefined) { unresolvable += 1; continue; }
      if (srcRouter === dstRouter) { unresolvable += 1; continue; }
      out.push({ pair, srcRouter, dstRouter });
    }
    return { routable: out, unresolvable };
  }, [candidates, routerOf]);
  const groups = useMemo(() => {
    const map = new Map<string, { srcRouter: number; dstRouter: number; pairs: Pair[] }>();
    for (const item of resolvable.routable) {
      const key = `${item.srcRouter}:${item.dstRouter}`;
      const group = map.get(key) ?? { srcRouter: item.srcRouter, dstRouter: item.dstRouter, pairs: [] };
      group.pairs.push(item.pair);
      map.set(key, group);
    }
    return [...map.values()];
  }, [resolvable]);
  const [phase, setPhase] = useState<'idle' | 'running' | 'done'>('idle');
  const [progress, setProgress] = useState(0);
  const [routes, setRoutes] = useState<Map<string, CanonicalRoute>>(new Map());
  const [failed, setFailed] = useState(0);
  const [unterminated, setUnterminated] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => { setPhase('idle'); setProgress(0); setRoutes(new Map()); setFailed(0); setUnterminated(0); setError(''); }, [run.detail.run_id]);

  const sweep = async () => {
    if (phase === 'running' || !groups.length) return;
    setPhase('running'); setProgress(0); setRoutes(new Map()); setFailed(0); setUnterminated(0); setError('');
    const keyOf = (group: { srcRouter: number; dstRouter: number }) => `${group.srcRouter}:${group.dstRouter}`;
    try {
      // No routing class is sent: the gateway answers with the run revision's declared class.
      const resolved = await resolveRoutes(run.detail.revision_id, groups.map(keyOf), 4, (done, total) => setProgress(Math.round((100 * done) / total)));
      const failedKeys = new Set(resolved.failed), unterminatedKeys = new Set(resolved.unterminated);
      setRoutes(resolved.routes);
      setFailed(groups.filter(group => failedKeys.has(keyOf(group))).reduce((n, group) => n + group.pairs.length, 0));
      setUnterminated(groups.filter(group => unterminatedKeys.has(keyOf(group))).reduce((n, group) => n + group.pairs.length, 0));
    } catch (error) { setError(gatewayReason(error)); }
    setPhase('done');
  };

  const loads = useMemo(() => {
    if (phase !== 'done') return [] as ChannelLoad[];
    const byChannel = new Map<number, ChannelLoad>();
    for (const item of resolvable.routable) {
      const route = routes.get(`${item.srcRouter}:${item.dstRouter}`);
      if (!route?.terminates) continue;
      for (const hop of route.hops) {
        const entry = byChannel.get(hop.channel_id) ?? { channelId: hop.channel_id, srcRouter: hop.src_router, srcPort: hop.src_port, dstRouter: hop.dst_router, dstPort: hop.dst_port, flits: 0, pairs: 0 };
        entry.flits += item.pair.flits;
        entry.pairs += 1;
        byChannel.set(hop.channel_id, entry);
      }
    }
    return [...byChannel.values()].sort((a, b) => b.flits - a.flits);
  }, [phase, resolvable, routes]);
  const loadByKey = useMemo(() => new Map(loads.map(l => [channelKey(l.srcRouter, l.srcPort, l.dstRouter, l.dstPort), l.flits])), [loads]);
  const attributed = loads.reduce((n, l) => n + l.flits, 0);
  const top = loads.length;
  const routedPairs = resolvable.routable.filter(item => routes.get(`${item.srcRouter}:${item.dstRouter}`)?.terminates).length;
  const routingClasses = [...new Set([...routes.values()].map(r => r.routing_class))].join(', ');

  if (topology?.shared_links?.length) return <Section title="Route sweep · expected shared-resource load" actions={<Badge tone="blue">Derived projection</Badge>}><SharedFabricProjection run={run} topology={topology} mode="sweep" /></Section>;
  return <Section title="Route sweep · expected channel load" actions={<>
    <Badge tone={phase === 'done' ? 'green' : 'amber'} title="Measured endpoint-pair flits projected through declared routes; attribution, not recorded per-link counters.">{phase === 'done' ? 'Derived' : 'Not run'}</Badge>
    {phase === 'done' && routingClasses && <Badge>{routingClasses}</Badge>}
    {phase === 'done' && <Badge>{routedPairs}/{resolvable.routable.length} routed · {top} channels · {attributed.toLocaleString()} flits</Badge>}
    {phase === 'done' && (unterminated > 0 || failed > 0) && <Badge tone="amber">{unterminated} unterminated · {failed} failed</Badge>}
  </>}>
    {!matrix && <Empty title="No traffic matrix in this run">Pair counts are required to attribute flits to channels; nothing is invented.</Empty>}
    {matrix && !topology && <Notice tone="amber"><strong>No topology for this revision.</strong> Pair counts alone cannot be placed on channels.</Notice>}
    {matrix && topology && <>
      <div className="toolbar toolbar-start">
        <Button primary disabled={phase === 'running' || !groups.length} onClick={sweep}>{phase === 'running' ? `Resolving ${progress}%` : `Sweep ${groups.length} router pair${groups.length === 1 ? '' : 's'}`}</Button>
        <span className="muted">{candidates.length} of {pairs.length} pairs (top by flits, max {SWEEP_LIMIT}) · {resolvable.unresolvable} unresolved</span>
      </div>
      {phase === 'running' && <div className="sweep-progress" role="progressbar" aria-label="Route sweep progress" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${progress}%` }} /></div>}
      {error && <Notice tone="red">{error}</Notice>}
      {phase === 'done' && <>
        {loads.length ? <>
          <div className="route-sweep-visual"><TopologyGraph topology={topology!} load={loadByKey} /></div>
          <details className="origin derived-load-fold">
            <summary>Derived channel load · {loads.length} channel{loads.length === 1 ? '' : 's'} · peak {Math.max(...loads.map(l => l.flits)).toLocaleString()} flits</summary>
            <div className="legend"><span>Line width and opacity scale with attributed flits</span></div>
            <div className={`table-scroll${cappedClass(loads.length)}`}><table><thead><tr><th>Channel</th><th>From → to</th><th>Pairs</th><th>Attributed flits</th><th title="Share of attributed flits on swept routes only; failed pairs carry no attribution.">Share</th></tr></thead><tbody>
              {loads.map(load => <tr key={load.channelId}><th className="mono">CH-{load.channelId}</th><td className="mono">{load.srcRouter}:{load.srcPort} → {load.dstRouter}:{load.dstPort}</td><td className="numeric">{load.pairs}</td><td className="numeric">{load.flits.toLocaleString()}</td><td className="numeric">{attributed ? `${(100 * load.flits / attributed).toFixed(1)} %` : '—'}</td></tr>)}
            </tbody></table></div>
          </details>
        </> : <Empty title="No channel carried an attributed flit">Every swept route failed or did not terminate. No load is drawn.</Empty>}
      </>}
    </>}
  </Section>;
}

// Measured channel inspection without a dropdown: the channel table is the selector. It is sorted
// by measured utilization, filterable, and bounded; selecting a row drives the window series and
// the measured queue/arbitration/transmit split beside it.
type RouterMetric = 'meanUtilization' | 'peakUtilization' | 'flits' | 'queueCycles' | 'weightedHopLatency';

const ROUTER_METRICS: { id: RouterMetric; label: string }[] = [
  { id: 'meanUtilization', label: 'Sustained util.' },
  { id: 'peakUtilization', label: 'Peak util.' },
  { id: 'flits', label: 'Egress flits' },
  { id: 'queueCycles', label: 'Queue cycles' },
  { id: 'weightedHopLatency', label: 'Hop latency' },
];

const routerMetricValue = (row: RouterLoad, metric: RouterMetric): number => {
  const value = row[metric];
  return typeof value === 'number' ? value : 0;
};

const routerMetricText = (row: RouterLoad, metric: RouterMetric): string => {
  if (metric === 'meanUtilization') return `${(100 * row.meanUtilization).toFixed(1)} %`;
  if (metric === 'peakUtilization') return `${(100 * row.peakUtilization).toFixed(1)} %`;
  if (metric === 'flits') return row.flits.toLocaleString();
  if (metric === 'queueCycles') return row.queueCycles.toLocaleString();
  return row.weightedHopLatency === null ? '—' : `${row.weightedHopLatency.toFixed(2)} cyc`;
};

function routerHeat(value: number, min: number, max: number, metric: RouterMetric): string {
  const share = value <= 0 ? 0 : max > min ? Math.max(0, Math.min(1, (value - min) / (max - min))) : 0;
  const opacity = 0.12 + 0.78 * share;
  if (metric === 'queueCycles') return `rgba(138, 109, 59, ${opacity})`;
  if (metric === 'weightedHopLatency') return `rgba(36, 104, 71, ${opacity})`;
  return `rgba(15, 108, 158, ${opacity})`;
}

export function MeasuredRouterTotals({ run, topology }: { run: LoadedRun; topology: Topology | null }) {
  const state = useSimLoad(run.detail.run_id);
  const [metric, setMetric] = useState<RouterMetric>('flits');
  const [selectedRouter, setSelectedRouter] = useState<number | null>(null);
  const wires = usePortWires(run, topology);
  const portWires = portWiresUsable(wires.map) ? wires.map.ports : undefined;
  const rows = useMemo(() => aggregateRouterLoad(state.data?.channels, topology, portWires), [state.data, topology, portWires]);
  const defaultRouter = useMemo(() => rows.length ? [...rows].sort((a, b) => b.meanUtilization - a.meanUtilization)[0].router : null, [rows]);
  // Start on the hottest router so the detail panel is useful immediately;
  // clicking the cell again still deselects it. The default is derived rather
  // than read from `hottest` so it also refreshes if the topology arrives
  // after the counters, without resetting a user's pick on every render.
  useEffect(() => {
    if (defaultRouter !== null) setSelectedRouter(defaultRouter);
  }, [run.detail.run_id, metric, defaultRouter]);
  const metricValues = rows.map(row => routerMetricValue(row, metric));
  const positiveValues = metricValues.filter(value => value > 0);
  const min = positiveValues.length ? Math.min(...positiveValues) : 0;
  const max = Math.max(0, ...metricValues);
  const coverage = useMemo(() => attributionSummary(state.data?.channels ?? [], topology, portWires), [state.data, topology, portWires]);
  // Keep zero-value routers out of a "Top by …" list: they are not ranked,
  // they are simply idle for this metric and would pad the panel with rows
  // that look like measurements of zero.
  const top = [...rows].filter(row => metric !== 'weightedHopLatency' || row.weightedHopLatency !== null)
    .filter(row => routerMetricValue(row, metric) > 0)
    .sort((a, b) => routerMetricValue(b, metric) - routerMetricValue(a, metric)).slice(0, 6);
  const selected = rows.find(row => row.router === selectedRouter) ?? null;

  const coordinates = new Map<number, [number, number]>();
  for (const router of topology?.routers ?? []) {
    if (Array.isArray(router.coordinates) && router.coordinates.length >= 2) coordinates.set(router.router_id, [Number(router.coordinates[0]), Number(router.coordinates[1])]);
  }
  const positioned = rows.every(row => coordinates.has(row.router));
  const columns = Math.max(1, Math.ceil(Math.sqrt(rows.length)));
  const points = rows.map((row, index) => {
    const [x, y] = positioned ? coordinates.get(row.router)! : [index % columns, Math.floor(index / columns)];
    return { row, x, y };
  });
  const maxX = Math.max(0, ...points.map(point => point.x));
  const maxY = Math.max(0, ...points.map(point => point.y));

  return <Section title="Per-router measured load" actions={<>
    <Badge tone={state.phase === 'ready' ? 'green' : 'amber'}>{state.phase === 'ready' ? `${rows.length} routers` : 'Not recorded'}</Badge>
    {state.phase === 'ready' && <Badge title="Measured channel coverage. Only unambiguous neighbour joins contribute ingress; shared-wire destinations and cross-plane ingress are not counted.">{coverage.declaredChannels} joined · {coverage.localChannels} eject · {coverage.boundaryIdleChannels} idle · {coverage.unattributedFlits.toLocaleString()} unattributed</Badge>}
  </>}>
    {state.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading router-grouped channel counters…</p>}
    {state.phase === 'absent' && <><p className="meta-line">This run carries no sampled channel counters; no per-router totals are derived.</p><PageLink page="analysis/summary">Open evaluation launcher</PageLink></>}
    {state.phase === 'error' && <Notice tone="red">{state.reason}</Notice>}
    {state.phase === 'ready' && (rows.length ? <>
      <div className="router-performance-layout">
        <div className="router-heatmap">
          <div className="toolbar toolbar-center">
            <div className="segmented" role="group" aria-label="Router heatmap metric">
              {ROUTER_METRICS.map(item => <button type="button" key={item.id} className={metric === item.id ? 'active' : ''} aria-pressed={metric === item.id} onClick={() => setMetric(item.id)}>{item.label}</button>)}
            </div>
          </div>
          <div className="router-heatmap-scroll">
            <div className="router-heatmap-grid" style={{ gridTemplateColumns: `repeat(${maxX + 1},minmax(0,88px))`, gridTemplateRows: `repeat(${maxY + 1},minmax(0,88px))` }} role="group" aria-label={`Router heatmap by ${ROUTER_METRICS.find(item => item.id === metric)?.label}`}>
              {points.map(({ row, x, y }) => {
                const value = routerMetricValue(row, metric);
                const share = value <= 0 ? 0 : max > min ? (value - min) / (max - min) : 0;
                return <button type="button" key={row.router} className={`router-heatmap-cell${selectedRouter === row.router ? ' selected' : ''}`}
                  style={{ gridColumn: x + 1, gridRow: y + 1, background: routerHeat(value, min, max, metric), color: share > 0.62 ? '#fff' : '#1d242c' }}
                  aria-label={`Router ${row.router}, ${ROUTER_METRICS.find(item => item.id === metric)?.label} ${routerMetricText(row, metric)}`} aria-pressed={selectedRouter === row.router}
                  {...contextTarget('router', row.router, `Router R${row.router}`, `${routerMetricText(row, metric)} ${ROUTER_METRICS.find(item => item.id === metric)?.label} · ${row.channels} measured source-port channels`)}
                  onClick={() => setSelectedRouter(current => current === row.router ? null : row.router)}>
                  <span className="router-heat-id">R{row.router}</span>
                  <span className="router-heat-value">{routerMetricText(row, metric)}</span>
                </button>;
              })}
            </div>
          </div>
        </div>
        <aside className="router-hotspots">
          <h3>Top by {ROUTER_METRICS.find(item => item.id === metric)?.label}</h3>
          {top.map(row => <button type="button" key={row.router} className={`router-hotspot${selectedRouter === row.router ? ' selected' : ''}`} {...contextTarget('router', row.router, `Router R${row.router}`, `${routerMetricText(row, metric)} ${ROUTER_METRICS.find(item => item.id === metric)?.label} · ${row.channels} measured source-port channels`)} onClick={() => setSelectedRouter(row.router)}>
            <span className="mono">R{row.router}</span>
            <span className="router-hotspot-track"><i style={{ width: `${100 * routerMetricValue(row, metric) / max}%`, background: routerHeat(routerMetricValue(row, metric), min, max, metric) }} /></span>
            <span className="numeric">{routerMetricText(row, metric)}</span>
          </button>)}
          {selected && <div className="router-detail">
            <h3 className="mono">R{selected.router}</h3>
            <dl className="properties">
              <div><dt>Egress / ingress</dt><dd>{selected.flits.toLocaleString()} / {selected.ingressFlits ? selected.ingressFlits.toLocaleString() : '—'}</dd></div>
              <div><dt>Declared / local egress</dt><dd>{selected.declaredFlits.toLocaleString()} / {selected.localFlits.toLocaleString()}</dd></div>
              <div><dt>Unattributed egress</dt><dd>{selected.unattributedFlits ? selected.unattributedFlits.toLocaleString() : '—'}</dd></div>
              <div><dt>Sustained / peak util.</dt><dd>{(100 * selected.meanUtilization).toFixed(1)} / {(100 * selected.peakUtilization).toFixed(1)} %</dd></div>
              <div><dt>Queue / arb cycles</dt><dd>{selected.queueCycles.toLocaleString()} / {selected.arbCycles.toLocaleString()}</dd></div>
              <div><dt>Hop latency</dt><dd>{selected.weightedHopLatency === null ? '—' : `${selected.weightedHopLatency.toFixed(2)} cyc`}</dd></div>
              <div><dt>Peak queue / stalls</dt><dd>{selected.peakQueued.toLocaleString()} / {selected.stalledChannels}</dd></div>
            </dl>
          </div>}
        </aside>
      </div>
      <details className="origin">
        <summary>All {rows.length} router totals</summary>
        <div className={`table-scroll${cappedClass(rows.length)}`}><table><thead><tr><th>Router</th><th>Channels</th><th>Egress flits</th><th>Local eject</th><th>Ingress flits</th><th>Sustained / peak util.</th><th>Queue cyc</th><th>Arb wait</th><th>Hop latency</th><th>Peak queue</th><th>Stalled</th></tr></thead><tbody>
          {rows.map(row => <tr key={row.router} className={selectedRouter === row.router ? 'selected' : ''} {...contextTarget('router', row.router, `Router R${row.router}`, `${row.flits.toLocaleString()} egress flits · ${row.channels} measured source-port channels`)}>
            <th className="mono">R{row.router}</th>
            <td className="numeric">{row.channels}</td>
            <td className="numeric">{row.flits.toLocaleString()}</td>
            <td className="numeric">{row.localFlits ? row.localFlits.toLocaleString() : '—'}</td>
            <td className="numeric">{row.ingressFlits ? row.ingressFlits.toLocaleString() : '—'}</td>
            <td className="numeric">{(100 * row.meanUtilization).toFixed(1)} / {(100 * row.peakUtilization).toFixed(1)} %</td>
            <td className="numeric">{row.queueCycles.toLocaleString()}</td>
            <td className="numeric">{row.arbCycles.toLocaleString()}</td>
            <td className="numeric">{row.weightedHopLatency === null ? '—' : `${row.weightedHopLatency.toFixed(2)} cyc`}</td>
            <td className="numeric">{row.peakQueued.toLocaleString()}</td>
            <td className="numeric">{row.stalledChannels || '—'}</td>
          </tr>)}
        </tbody></table></div>
      </details>
    </> : <p className="meta-line">The measured series carries no channel rows.</p>)}
  </Section>;
}

export function MeasuredLinks({ run, topology, utilizationRange, onClearRange }: {
  run: LoadedRun; topology: Topology | null;
  utilizationRange?: UtilizationRange | null;
  onClearRange?: () => void;
}) {
  const load = useSimLoad(run.detail.run_id);
  const series = useSimSeries(run.detail.run_id);
  // Shared with the delay-cost scatter, so a pick there lands here.
  const [selected, setSelected] = useChannelSelection(run.detail.run_id);
  const [filter, setFilter] = useState('');
  const [showIdle, setShowIdle] = useState(false);
  const [subnet, setSubnet] = useState('all');
  const [link, setLink] = useState<{ phase: 'idle' | 'loading' | 'ready' | 'error'; data?: SimLink; reason?: string }>({ phase: 'idle' });

  useEffect(() => {
    setSelected(''); setFilter(''); setShowIdle(false); setLink({ phase: 'idle' });
  }, [run.detail.run_id]);

  useEffect(() => {
    if (load.phase !== 'ready') return;
    const all = load.data?.channels ?? [];
    const inScope = (id: string) => subnet === 'all' || Math.floor(Number(id) / 100_000_000) === Number(subnet);
    // A channel picked in another section may sit outside the current subnet
    // scope; widen the scope instead of discarding the pick.
    if (selected && all.some(entry => String(entry.logical_channel_id) === selected)) {
      if (!inScope(selected)) setSubnet('all');
      return;
    }
    const busiest = [...all].sort((a, b) => b.utilization - a.utilization)[0];
    setSelected(busiest ? String(busiest.logical_channel_id) : '');
  }, [load.phase, load.data, selected, subnet, setSelected]);

  useEffect(() => {
    if (!selected) { setLink({ phase: 'idle' }); return; }
    let live = true;
    setLink({ phase: 'loading' });
    gateway.simLink(run.detail.run_id, selected)
      .then(data => { if (live) setLink({ phase: 'ready', data }); })
      .catch(error => { if (live) setLink({ phase: 'error', reason: gatewayReason(error) }); });
    return () => { live = false; };
  }, [selected, run.detail.run_id]);

  const portWiresState = usePortWires(run, topology);
  const channelIndex = useMemo(() => buildChannelIndex(topology, portWiresUsable(portWiresState.map) ? portWiresState.map.ports : undefined), [topology, portWiresState.map]);
  const subnets = [...new Set((load.data?.channels ?? []).map(entry => Math.floor(Number(entry.logical_channel_id) / 100_000_000)))].sort();
  const channels = useMemo(() => [...(load.data?.channels ?? [])].filter(entry => subnet === 'all' || Math.floor(Number(entry.logical_channel_id) / 100_000_000) === Number(subnet)).sort((a, b) => b.utilization - a.utilization), [load.data, subnet]);
  const scopedSeries = series.data ? { ...series.data, channels: series.data.channels.filter(entry => subnet === 'all' || Math.floor(Number(entry.logical_channel_id) / 100_000_000) === Number(subnet)) } : null;
  const activeChannels = channels.filter(entry => entry.utilization > 0 || entry.flits_total > 0);
  const query = filter.trim().toLowerCase();
  // A search deliberately looks at every channel, including idle ones. With no
  // search, the default is the active set so 400 zero rows do not bury the signal.
  const source = query ? channels : showIdle ? channels : activeChannels;
  const inRange = (entry: NonNullable<SimLoad['channels']>[number]) => utilizationInRange(entry.utilization, utilizationRange ?? null);
  const visible = source.filter(inRange).filter(entry => !query || `ch-${entry.logical_channel_id} ${entry.logical_channel_id}`.includes(query));
  const contexts = useMemo(() => new Map(channels.map(entry => [entry.logical_channel_id, matchMeasuredChannel(channelIndex, Number(entry.logical_channel_id))])), [channels, channelIndex]);
  // A pick from the list or the matrix must bring the detail panel into view
  // when the two columns stack or the detail sits below the fold.
  const pickChannel = (id: string) => { setSelected(id); revealChannelDetail(); };
  const selectedSeries = series.data?.channels?.find(entry => String(entry.logical_channel_id) === selected);
  const windows = selectedSeries?.flits_per_window ?? [];
  const selectedRow = channels.find(entry => String(entry.logical_channel_id) === selected);
  const selectedMatch = selected ? matchMeasuredChannel(channelIndex, Number(selected)) : null;
  const selectedCost = selectedRow ? channelCosts([selectedRow])[0] : undefined;
  const fabricMedianCost = useMemo(() => median(channelCosts(load.data?.channels ?? []).map(cost => cost.queuePerFlit).filter((value): value is number => value !== null)), [load.data]);
  const flitRank = selectedRow ? 1 + channels.filter(entry => entry.flits_total > selectedRow.flits_total).length : null;
  const breakdown = link.data?.breakdown;
  const splitTotal = breakdown ? breakdown.queue_cycles + breakdown.arb_wait_cycles + (breakdown.tx_busy_cycles ?? 0) : 0;
  const splitRows: [string, number, string][] = breakdown
    ? [['Queue', breakdown.queue_cycles, 'queue'], ['Arbitration', breakdown.arb_wait_cycles, 'arbitration'], ['Transmit', breakdown.tx_busy_cycles ?? 0, 'transmit']]
    : [];
  const utilization = link.data?.utilization ?? selectedRow?.utilization;
  const flits = link.data?.total_flits ?? selectedRow?.flits_total;
  const meanLatency = breakdown?.per_hop_latency_mean_cycles ?? selectedRow?.per_hop_latency_mean_cycles;
  const peakLatency = breakdown?.peak_per_hop_latency_cycles ?? selectedRow?.peak_per_hop_latency_cycles;
  const peakQueue = breakdown?.peak_queued_flits ?? selectedRow?.peak_queued_flits;
  const meanQueued = breakdown?.mean_queued_flits_per_output ?? selectedRow?.mean_queued_flits_per_output;
  const selectedLink = selectedMatch?.channel;
  const selectedContext = selectedMatch ? channelMatchLabel(selectedMatch) : '';
  const linkLabel = (entry: NonNullable<SimLoad['channels']>[number]) => {
    const match = contexts.get(entry.logical_channel_id);
    return match?.local ? `S${match.measured.subnet} · eject` : match?.wire ? `S${match.measured.subnet} · wire ${match.wire.id}` : match?.channel ? `S${match.measured.subnet} · R${match.measured.router}→R${match.channel.dst_router}` : match ? `S${match.measured.subnet} · R${match.measured.router} p${match.measured.port}` : '—';
  };

  return <Section id="measured-channel-activity" title="Measured channel activity" actions={<Badge tone={load.phase === 'ready' ? 'green' : 'amber'}>{load.phase === 'ready' ? 'Measured' : 'Not recorded'}</Badge>}>
    {load.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading sampled counters for this run…</p>}
    {load.phase === 'absent' && <p className="meta-line">This run carries no sampled series; channel counters and the queue / arbitration / transmit split are not available.</p>}
    {load.phase === 'error' && <Notice tone="red">{load.reason}</Notice>}
    {load.phase === 'ready' && load.data && <>
      <div className="stat-strip">
        <div className="stat"><span>Windows</span><strong>{load.data.num_windows ?? '—'}</strong><small>original sample windows</small></div>
        <div className="stat"><span>Cycles sampled</span><strong>{(load.data.cycles_sampled ?? 0).toLocaleString()}</strong><small>recorded counter window</small></div>
        <div className="stat"><span>Window</span><strong>{load.data.sample_period_cycles ?? '—'} cyc</strong><small>per original window</small></div>
        <div className="stat"><span>Link capacity</span><strong>{load.data.link_capacity_flits_per_cycle ?? '—'} flits/cyc</strong><small>declared width</small></div>
      </div>
      {series.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the sampled window series…</p>}
      {subnets.length > 1 && <label className="field">Measured native subnet<select aria-label="Measured native subnet" value={subnet} onChange={event => { const next = event.target.value; setSubnet(next); const first = [...(load.data?.channels ?? [])].filter(entry => next === 'all' || Math.floor(Number(entry.logical_channel_id) / 100_000_000) === Number(next)).sort((a, b) => b.utilization - a.utilization)[0]; setSelected(first ? String(first.logical_channel_id) : ''); }}><option value="all">All subnets · totals remain separate per port</option>{subnets.map(value => <option key={value} value={value}>{value}{topology?.family === 'srota' ? value === 0 ? ' · Plane D' : value === 1 ? ' · Plane C' : '' : ''}</option>)}</select></label>}
      {series.phase === 'ready' && scopedSeries && <ChannelWindowMatrix series={scopedSeries} topology={topology} loadChannels={channels} selected={selected} onSelect={pickChannel} portWires={portWiresUsable(portWiresState.map) ? portWiresState.map.ports : undefined} />}
      {series.phase === 'absent' && <p className="meta-line">The window series is absent; aggregate channel counters and the selected link split remain available.</p>}
      {series.phase === 'error' && <Notice tone="red">{series.reason}</Notice>}
      {channels.length ? <div className="measured-layout">
        <div className="measured-list">
          <div className="measured-list-tools">
            <label className="search-field"><input aria-label="Filter measured channels" placeholder="Find a measured channel…" value={filter} onChange={event => setFilter(event.target.value)} /></label>
            <Button aria-pressed={showIdle} onClick={() => setShowIdle(current => !current)}>{showIdle ? 'Active only' : `Show idle (${channels.length - activeChannels.length})`}</Button>
          </div>
          {utilizationRange && <div className="active-filter" data-testid="utilization-filter">
            <Badge tone="blue">Utilization {(100 * utilizationRange.low).toFixed(1)}–{(100 * utilizationRange.high).toFixed(1)} %</Badge>
            <span>{visible.length.toLocaleString()} channel{visible.length === 1 ? '' : 's'} shown in this bin</span>
            {onClearRange && <button type="button" className="text-button" onClick={onClearRange}>Clear filter</button>}
          </div>}
          {visible.length ? <div className="table-scroll measured-channels">
            <table aria-label="Measured channels"><thead><tr><th>Channel</th><th>Link</th><th>Flits</th><th>Utilization</th></tr></thead><tbody>
              {visible.map(entry => <tr key={entry.logical_channel_id} {...contextTarget('channel', entry.logical_channel_id, `Measured channel CH-${entry.logical_channel_id}`, `${entry.flits_total.toLocaleString()} flits · ${(100 * entry.utilization).toFixed(1)} % utilization · ${linkLabel(entry)}`)} className={String(entry.logical_channel_id) === selected ? 'selected' : ''} tabIndex={0} role="button" aria-pressed={String(entry.logical_channel_id) === selected} onClick={() => pickChannel(String(entry.logical_channel_id))} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); pickChannel(String(entry.logical_channel_id)); } }}>
                <th className="mono">CH-{entry.logical_channel_id}</th>
                <td className="mono muted">{linkLabel(entry)}</td>
                <td className="numeric">{entry.flits_total.toLocaleString()}</td>
                <td className="numeric"><span className="mini-meter"><span style={{ width: `${Math.min(100, 100 * entry.utilization)}%` }} /></span>{(100 * entry.utilization).toFixed(1)} %</td>
              </tr>)}
            </tbody></table>
          </div> : <Empty title={utilizationRange ? 'No channel in this utilization bin' : query ? 'No channel matches' : 'No active channels'}>
            {utilizationRange ? 'Clear the utilization filter or pick another histogram bin.' : query ? 'Try a channel number such as CH-42.' : 'Every measured channel reports zero flits. Use Show idle to inspect them.'}
          </Empty>}
          <p className="meta-line">{query ? `${visible.length} match${visible.length === 1 ? '' : 'es'}` : `${showIdle ? channels.length : activeChannels.length} of ${channels.length} channels`}</p>
        </div>
        <div className="measured-detail" id="measured-channel-detail">
          <div className="measured-detail-head">
            <div><span className="meta-line">Selected measured channel</span><h3 className="mono">CH-{selected || '—'}</h3></div>
            <Badge tone={selectedRow ? 'blue' : 'neutral'}>{selectedRow ? `${(100 * (utilization ?? 0)).toFixed(1)} % utilized` : 'Select a channel'}</Badge>
          </div>
          {selected && <p className="meta-line channel-context">{selectedContext}{selectedLink ? ` · ${selectedLink.width_bits}-bit · ${selectedLink.latency_cycles}-cycle declared link` : selectedMatch?.local ? ' · delivered to endpoints' : selectedMatch?.unmatched ? ' · no declared inter-router link' : ''}</p>}
          {selected && <div className="stat-strip link-stats detail-stats">
            <div className="stat"><span>Utilization</span><strong>{utilization == null ? '—' : `${(100 * utilization).toFixed(1)} %`}</strong><small>{flitRank ? `rank ${flitRank} of ${channels.length} by flits` : 'measured'}</small></div>
            <div className="stat"><span>Total flits</span><strong>{flits == null ? '—' : flits.toLocaleString()}</strong><small>measured channel total</small></div>
            <div className="stat"><span>Peak window</span><strong>{selectedRow ? `${(100 * selectedRow.peak_window_utilization).toFixed(1)} %` : '—'}</strong><small>busiest sampled window</small></div>
            <div className="stat"><span>Queue / flit</span><strong>{selectedCost?.queuePerFlit == null ? '—' : `${selectedCost.queuePerFlit.toFixed(2)} cyc`}</strong><small>fabric median {fabricMedianCost == null ? '—' : `${fabricMedianCost.toFixed(2)} cyc`}</small></div>
            <div className="stat"><span>Mean hop latency</span><strong>{meanLatency == null ? '—' : `${meanLatency.toFixed(2)} cyc`}</strong><small>measured mean</small></div>
            <div className="stat"><span>Peak hop latency</span><strong>{peakLatency == null ? '—' : `${peakLatency.toFixed(0)} cyc`}</strong><small>{selectedCost?.tailRatio == null ? 'tail not available' : `${selectedCost.tailRatio.toFixed(1)}× mean`}</small></div>
            <div className="stat"><span>Peak queue</span><strong>{peakQueue == null ? '—' : `${peakQueue.toLocaleString()} flits`}</strong><small>mean queued/output {meanQueued == null ? '—' : meanQueued.toFixed(2)}</small></div>
            <div className="stat"><span>Stalls</span><strong>{link.data?.stalls_total ?? (selectedRow?.has_stalls ? 'reported' : '—')}</strong><small>{selectedRow?.has_stalls ? 'stall indicator set' : 'no stall indicator'}</small></div>
          </div>}
          {selected && windows.length > 0 && <ChannelWindowChart id={selected} windows={windows} queueMax={selectedSeries?.queue_max_per_window} latencyMax={selectedSeries?.latency_max_per_window} samplePeriod={series.data?.sample_period_cycles} />}
          {selected && !windows.length && <p className="meta-line">{series.phase === 'absent' ? 'No sampled window series for this run; only aggregate link totals are available.' : 'The series carries no window rows for this channel.'}</p>}
          {selected && link.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the selected link…</p>}
          {selected && link.phase === 'error' && <Notice tone="red">{link.reason}</Notice>}
          {selected && link.phase === 'ready' && link.data && <>
            {breakdown ? <>
              <div className="split-stack" role="img" aria-label="Measured queue, arbitration, and transmit cycle split">
                {splitRows.map(([, value, key]) => <span key={key} className={`split-seg split-${key}`} style={{ width: `${splitTotal ? (value / splitTotal) * 100 : 0}%` }} />)}
              </div>
              <div className="split-legend">
                {splitRows.map(([label, value, key]) => <span key={key}><i className={`split-dot split-${key}`} /> <strong>{label}</strong> {value.toLocaleString()} cyc · {splitTotal ? `${(100 * value / splitTotal).toFixed(0)} %` : '—'}</span>)}
              </div>
              <p className="meta-line">Measured busy cycles {splitTotal.toLocaleString()} · mean queued/output {breakdown.mean_queued_flits_per_output?.toFixed(2) ?? '—'} flits · peak queue {breakdown.peak_queued_flits ?? '—'} flits · peak arbitration wait {breakdown.peak_arb_wait_cycles ?? '—'} cyc · peak per-hop latency {breakdown.peak_per_hop_latency_cycles ?? '—'} cyc.</p>
            </> : <p className="inline-note amber">{link.data.breakdown_absence || 'The measured queue, arbitration, and transmit split is absent from this run.'}</p>}
          </>}
        </div>
      </div> : <Empty title="No channel rows in this series">The artifact parsed without per-channel counters.</Empty>}
    </>}
  </Section>;
}

export function RunHistory({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const { loadRun } = useProject();
  const runs = useMemo(() => runVersionOrder(project.detail.runs ?? []), [project.detail.runs]);
  const labels = useMemo(() => runVersionLabels(project.detail.runs ?? []), [project.detail.runs]);
  return <Section title="Run history in this project" actions={<Badge title="Grouped by revision; selecting a run changes every Analysis surface. Runs are never merged.">{runs.length} runs</Badge>}>
    {runs.length ? <div className={`table-scroll${cappedClass(runs.length)}`}><table><thead><tr><th>Run</th><th>Revision</th><th>Status</th><th>Backend</th><th>Requirements</th><th>Completed</th><th /></tr></thead><tbody>
      {runs.map(item => <tr key={item.run_id} className={item.run_id === run.detail.run_id ? 'selected' : ''}>
        <th><span className="mono run-version">{labels.get(item.run_id) ?? '—'}</span><br /><small>{item.display_name ?? ''}</small><br /><small className="mono" title={item.run_id}>{item.run_id.slice(0, 13)}…</small></th>
        <td className="mono">{revisionLabel(item.revision_id)}{item.revision_id === project.detail.active_revision_id && <> <Badge tone="blue">active</Badge></>}</td>
        <td><Badge tone={item.status === 'EVALUATED' ? 'green' : item.status === 'FAILED' ? 'red' : 'amber'}>{item.status}</Badge></td>
        <td className="mono">{item.backend ?? '—'}</td>
        <td>{item.requirements_pass === true ? 'Pass' : item.requirements_pass === false ? 'Fail' : 'Not evaluated'}</td>
        <td className="mono">{item.completed_at ? item.completed_at.replace('T', ' ').replace('+00:00', 'Z') : '—'}</td>
        <td>{item.run_id === run.detail.run_id ? <span className="muted">Selected</span> : <Button onClick={() => loadRun(item.run_id)}>Open</Button>}</td>
      </tr>)}
    </tbody></table></div> : <Empty title="No runs in this project">Launch an evaluation to create one.</Empty>}
  </Section>;
}
