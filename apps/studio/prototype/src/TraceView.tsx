import { useEffect, useMemo, useState } from 'react';
import type { CanonicalRoute, Topology } from './gateway';
import { undirectedLinks, topologyLayout } from './TopologyGraph';
import { resolveRoutes } from './routeResolution';
import type { InjectionRow } from './trace';

// A trace view has to show something. Both artifacts below are tables in the bundle, so each gets a
// shape: requested injections over time, and the executed first hop for one destination node.

function niceStep(value: number) {
  if (!(value > 0)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  return Math.max(1, (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10) * magnitude);
}

type TraceMetric = 'flits' | 'packets';
type TraceBucket = { index: number; start: number; end: number; packets: number; flits: number; classes: Map<string, { packets: number; flits: number }> };

export function InjectionTimeline({ decoded }: { decoded: { rows: InjectionRow[]; total: number; dialect: string } }) {
  const rows = decoded.rows;
  const [metric, setMetric] = useState<TraceMetric>('flits');
  const [hiddenClasses, setHiddenClasses] = useState<Set<string>>(() => new Set());
  const [hoveredBucket, setHoveredBucket] = useState<number | null>(null);
  const [selectedBucket, setSelectedBucket] = useState<number | null>(null);
  if (!rows.length) return null;
  const minCycle = Math.min(...rows.map(r => r.cycle));
  const maxCycle = Math.max(...rows.map(r => r.cycle));
  const flits = rows.reduce((n, r) => n + r.flits, 0);
  const palette = ['#0f6c9e', '#8a6d3b', '#246847', '#6b4f9e', '#a32928'];
  const classInfo = [...new Set(rows.map(row => row.trafficClass))].sort().map((trafficClass, index) => {
    const matching = rows.filter(row => row.trafficClass === trafficClass);
    return {
      trafficClass, packets: matching.length, flits: matching.reduce((sum, row) => sum + row.flits, 0),
      first: matching.reduce((first, row) => Math.min(first, row.cycle), Number.POSITIVE_INFINITY),
      last: matching.reduce((last, row) => Math.max(last, row.cycle), 0),
      color: palette[index % palette.length],
    };
  });
  const sourceStats = [...rows.reduce((map, row) => {
    const current = map.get(row.source) ?? { node: row.source, packets: 0, flits: 0, first: row.cycle, last: row.cycle };
    current.packets += 1; current.flits += row.flits;
    current.first = Math.min(current.first, row.cycle); current.last = Math.max(current.last, row.cycle);
    map.set(row.source, current); return map;
  }, new Map<number, { node: number; packets: number; flits: number; first: number; last: number }>()).values()];
  const destinationStats = [...rows.reduce((map, row) => {
    const current = map.get(row.destination) ?? { node: row.destination, packets: 0, flits: 0, first: row.cycle, last: row.cycle };
    current.packets += 1; current.flits += row.flits;
    current.first = Math.min(current.first, row.cycle); current.last = Math.max(current.last, row.cycle);
    map.set(row.destination, current); return map;
  }, new Map<number, { node: number; packets: number; flits: number; first: number; last: number }>()).values()];
  const buckets = 48;
  const span = Math.max(1, maxCycle - minCycle + 1);
  const size = Math.max(1, Math.ceil(span / buckets));
  const bucketCount = Math.min(buckets, Math.ceil(span / size));
  const bucketRows: TraceBucket[] = Array.from({ length: bucketCount }, (_, index) => ({
    index, start: minCycle + index * size, end: Math.min(maxCycle, minCycle + (index + 1) * size - 1), packets: 0, flits: 0, classes: new Map(),
  }));
  for (const row of rows) {
    const bucket = bucketRows[Math.min(bucketCount - 1, Math.floor((row.cycle - minCycle) / size))];
    bucket.packets += 1; bucket.flits += row.flits;
    const current = bucket.classes.get(row.trafficClass) ?? { packets: 0, flits: 0 };
    current.packets += 1; current.flits += row.flits;
    bucket.classes.set(row.trafficClass, current);
  }
  const metricLabel = metric === 'flits' ? 'flits' : 'packets';
  const classValue = (bucket: TraceBucket, trafficClass: string) => {
    const value = bucket.classes.get(trafficClass);
    return value ? (metric === 'flits' ? value.flits : value.packets) : 0;
  };
  const visibleClasses = classInfo.filter(item => !hiddenClasses.has(item.trafficClass));
  const visibleValue = (bucket: TraceBucket) => visibleClasses.reduce((sum, item) => sum + classValue(bucket, item.trafficClass), 0);
  const visiblePackets = (bucket: TraceBucket) => visibleClasses.reduce((sum, item) => sum + (bucket.classes.get(item.trafficClass)?.packets ?? 0), 0);
  const peak = Math.max(1, ...bucketRows.map(visibleValue));
  const visibleTotal = bucketRows.reduce((sum, bucket) => sum + visibleValue(bucket), 0);
  const average = bucketCount > 0 ? visibleTotal / bucketCount : 0;
  const peakRatio = average > 0 ? peak / average : null;
  const activeBuckets = bucketRows.filter(bucket => visibleValue(bucket) > 0).length;
  const distinctPairs = new Set(rows.map(row => `${row.source}:${row.destination}`)).size;
  const width = 760, height = 232, left = 58, right = 16, top = 22, bottom = 44;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const barWidth = plotWidth / bucketCount;
  const tick = (value: number) => value.toLocaleString();
  const xTicks = [...new Set(Array.from({ length: 6 }, (_, index) => Math.round(minCycle + (maxCycle - minCycle) * index / 5)))];
  const yStep = Math.max(1, Math.ceil(niceStep(peak / 5)));
  const yMax = Math.max(peak, Math.ceil(peak / yStep) * yStep);
  const yTicks = Array.from({ length: Math.round(yMax / yStep) + 1 }, (_, index) => index * yStep);
  const xForCycle = (cycle: number) => left + ((cycle - minCycle) / Math.max(1, maxCycle - minCycle)) * plotWidth;
  const activeIndex = hoveredBucket ?? selectedBucket;
  const activeBucket = activeIndex === null ? null : bucketRows[activeIndex];
  const sourceValue = (item: { flits: number; packets: number }) => metric === 'flits' ? item.flits : item.packets;
  const formatValue = (value: number) => Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1);
  const summarize = (items: typeof sourceStats) => {
    const values = items.map(sourceValue).sort((a, b) => a - b);
    const total = values.reduce((sum, value) => sum + value, 0);
    const middle = values.length >> 1;
    const median = values.length === 0 ? 0 : values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
    const min = values[0] ?? 0;
    const max = values[values.length - 1] ?? 0;
    const top = items.length ? items.reduce((best, item) => sourceValue(item) > sourceValue(best) ? item : best, items[0]) : null;
    return { active: items.length, total, min, median, max, top, topShare: total > 0 ? 100 * max / total : 0, uniform: items.length > 0 && max === min };
  };
  const sourceSummary = summarize(sourceStats);
  const destinationSummary = summarize(destinationStats);
  const topSources = [...sourceStats].sort((a, b) => sourceValue(b) - sourceValue(a)).slice(0, 5);
  const topDestinations = [...destinationStats].sort((a, b) => sourceValue(b) - sourceValue(a)).slice(0, 5);
  const sourcePeak = Math.max(1, ...topSources.map(sourceValue));
  const destinationPeak = Math.max(1, ...topDestinations.map(sourceValue));
  const sizes = [...rows.reduce((map, row) => map.set(row.flits, (map.get(row.flits) ?? 0) + 1), new Map<number, number>()).entries()].sort((a, b) => a[0] - b[0]);
  const sizeRows = sizes.map(([flitCount, count]) => ({
    flitCount, count,
    flitShare: flits > 0 ? 100 * flitCount * count / flits : 0,
    packetShare: rows.length > 0 ? 100 * count / rows.length : 0,
  }));
  const dominantSize = sizeRows.reduce((best, row) => row.flitShare > best.flitShare ? row : best, sizeRows[0] ?? { flitCount: 0, count: 0, flitShare: 0, packetShare: 0 });
  const averagePacketSize = rows.length > 0 ? flits / rows.length : 0;
  const toggleClass = (trafficClass: string) => setHiddenClasses(previous => {
    const next = new Set(previous);
    if (next.has(trafficClass)) next.delete(trafficClass);
    else if (classInfo.length - next.size > 1) next.add(trafficClass);
    return next;
  });
  const activity = (item: { node: number; packets: number; flits: number; first: number; last: number }, peakValue: number) => {
    const value = sourceValue(item);
    return <div className="activity-row" key={item.node}>
      <span className="mono">node {item.node}</span>
      <span className="flow-track"><i style={{ width: `${100 * value / peakValue}%` }} /></span>
      <span className="numeric">{value.toLocaleString()}</span>
      <small>{item.packets.toLocaleString()} pkt · {item.first.toLocaleString()}–{item.last.toLocaleString()} cyc</small>
    </div>;
  };
  const balanceIdentical = sourceSummary.uniform && destinationSummary.uniform
    && sourceSummary.active === destinationSummary.active
    && sourceSummary.median === destinationSummary.median
    && sourceSummary.topShare === destinationSummary.topShare;

  return <figure className="trace-figure">
    <div className="trace-timeline-card">
      <div className="trace-chart-head">
        <div>
          <h3>Requested injections over time</h3>
          <p>{metricLabel} per {size.toLocaleString()}-cycle bucket, stacked by traffic class · {tick(minCycle)}–{tick(maxCycle)} cycles · {bucketCount} buckets</p>
        </div>
        <div className="segmented trace-metric-toggle" role="group" aria-label="Timeline value">
          <button type="button" className={metric === 'flits' ? 'active' : ''} aria-pressed={metric === 'flits'} onClick={() => setMetric('flits')}>Flits</button>
          <button type="button" className={metric === 'packets' ? 'active' : ''} aria-pressed={metric === 'packets'} onClick={() => setMetric('packets')}>Packets</button>
        </div>
      </div>
      <div className="trace-class-legend" role="group" aria-label="Toggle chart traffic classes">
        {classInfo.map(item => {
          const hidden = hiddenClasses.has(item.trafficClass);
          const lastVisible = !hidden && visibleClasses.length === 1;
          return <button type="button" key={item.trafficClass} className={`trace-class-chip${hidden ? ' off' : ''}`} aria-pressed={!hidden} disabled={lastVisible} onClick={() => toggleClass(item.trafficClass)} title={lastVisible ? 'At least one class must remain visible' : `${hidden ? 'Show' : 'Hide'} class ${item.trafficClass} in the chart`}>
            <i style={{ background: item.color }} />class {item.trafficClass}
            <strong>{(metric === 'flits' ? item.flits : item.packets).toLocaleString()}</strong> {metricLabel}
            <small>{(metric === 'flits' ? item.packets : item.flits).toLocaleString()} {metric === 'flits' ? 'pkt' : 'flits'}</small>
          </button>;
        })}
      </div>
      <div className="trace-bucket-detail" aria-live="polite">
        {activeBucket ? <>
          <div className="trace-bucket-detail-head">
            <strong>Cycles {tick(activeBucket.start)}–{tick(activeBucket.end)}</strong>
            <span>{visibleValue(activeBucket).toLocaleString()} {metricLabel}{metric === 'flits' ? ` · ${visiblePackets(activeBucket).toLocaleString()} packets` : ''}{hiddenClasses.size ? ' · visible classes' : ''}</span>
            <span className="badge">{selectedBucket === activeBucket.index ? 'selected' : 'hover'}</span>
            {selectedBucket !== null && <button type="button" className="text-button" onClick={() => setSelectedBucket(null)}>Clear selection</button>}
          </div>
          <div className="trace-bucket-classes">{visibleClasses.filter(item => classValue(activeBucket, item.trafficClass) > 0).map(item => <span key={item.trafficClass}><i style={{ background: item.color }} />class {item.trafficClass} <strong>{classValue(activeBucket, item.trafficClass).toLocaleString()}</strong> {metricLabel}</span>)}</div>
        </> : <span className="muted">Hover or select a bar to inspect its cycle window and class split.</span>}
      </div>
            <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Requested ${metricLabel} per ${size} cycles, stacked by traffic class, ${decoded.total} packets from cycle ${minCycle} to ${maxCycle}`} onMouseLeave={() => setHoveredBucket(null)}>
        <text className="trace-axis-title" x={14} y={top + plotHeight / 2} textAnchor="middle" transform={`rotate(-90 14 ${top + plotHeight / 2})`}>{metricLabel} / bucket</text>
        {yTicks.map(value => {
          const y = top + plotHeight - (value / yMax) * plotHeight;
          return <g key={`y-${value}`}>
            <line className="trace-grid" x1={left} x2={width - right} y1={y} y2={y} />
            <text className="trace-axis-label" x={left - 8} y={y + 3} textAnchor="end">{tick(value)}</text>
          </g>;
        })}
        {xTicks.map(cycle => {
          const x = xForCycle(cycle);
          return <g key={`x-${cycle}`}>
            <line className="trace-grid trace-grid-vertical" x1={x} x2={x} y1={top} y2={top + plotHeight} />
            <line className="trace-axis-tick" x1={x} x2={x} y1={top + plotHeight} y2={top + plotHeight + 4} />
            <text className="trace-axis-label" x={x} y={height - 22} textAnchor={cycle === minCycle ? 'start' : cycle === maxCycle ? 'end' : 'middle'}>{tick(cycle)}</text>
          </g>;
        })}
        <line className="timeline-axis" x1={left} y1={top + plotHeight} x2={width - right} y2={top + plotHeight} />
        {bucketRows.map(bucket => {
          const isActive = activeIndex === bucket.index;
          if (isActive) {
            return <rect key={`selected-${bucket.index}`} className="trace-bucket-selected" x={left + bucket.index * barWidth + 1} y={top} width={barWidth - 2} height={plotHeight} />;
          }
          return null;
        })}
        {bucketRows.map(bucket => {
          let y = top + plotHeight;
          const total = visibleValue(bucket);
          return <g key={bucket.index} className={`trace-bucket${selectedBucket === bucket.index ? ' selected' : ''}`} role="button" tabIndex={0} aria-label={`Cycles ${tick(bucket.start)} to ${tick(bucket.end)}: ${total.toLocaleString()} ${metricLabel} in ${visiblePackets(bucket).toLocaleString()} packets`} onMouseEnter={() => setHoveredBucket(bucket.index)} onMouseLeave={() => setHoveredBucket(null)} onFocus={() => setHoveredBucket(bucket.index)} onBlur={() => setHoveredBucket(null)} onClick={() => setSelectedBucket(current => current === bucket.index ? null : bucket.index)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedBucket(current => current === bucket.index ? null : bucket.index); } }}>
            <rect className="trace-bucket-hit" x={left + bucket.index * barWidth} y={top} width={barWidth} height={plotHeight} />
            {visibleClasses.map(item => {
              const value = classValue(bucket, item.trafficClass);
              if (!value) return null;
              const h = (value / yMax) * plotHeight;
              y -= h;
              return <rect key={item.trafficClass} className="trace-bucket-seg" x={left + bucket.index * barWidth + barWidth * 0.12} y={y} width={Math.max(1, barWidth * 0.76)} height={h} fill={item.color} />;
            })}
          </g>;
        })}
        {activeIndex !== null && <line className="trace-crosshair" x1={left + (activeIndex + 0.5) * barWidth} x2={left + (activeIndex + 0.5) * barWidth} y1={top} y2={top + plotHeight} />}
        <text className="trace-axis-title" x={left + plotWidth / 2} y={height - 5} textAnchor="middle">injection cycle</text>
      </svg>
      <div className="trace-chart-summary">
        <span>Mean <strong>{average.toFixed(1)}</strong> {metricLabel}/bucket</span>
        <span>Peak / mean <strong>{peakRatio === null ? '—' : `${peakRatio.toFixed(2)}×`}</strong></span>
        <span>Active buckets <strong>{activeBuckets}/{bucketCount}</strong></span>
        <span>Node pairs <strong>{distinctPairs}</strong></span>
      </div>
      <div className="trace-class-windows" aria-label="Traffic class active windows">
        <span className="trace-class-windows-label">Class windows</span>
        {classInfo.map(item => <span key={item.trafficClass} className={hiddenClasses.has(item.trafficClass) ? 'off' : ''}>
          <i style={{ background: item.color }} />class {item.trafficClass}
          <strong>{item.first.toLocaleString()}–{item.last.toLocaleString()} cyc</strong>
          <small>{flits > 0 ? `${(100 * item.flits / flits).toFixed(1)} % flits` : '—'}</small>
        </span>)}
      </div>
      <p className="trace-chart-caption">Requested injections, not delivered traffic.{decoded.total > rows.length ? ` Charts cover the ${rows.length.toLocaleString()} decoded rows of ${decoded.total.toLocaleString()}.` : ''}</p>
    </div>
    <div className="trace-profile">
      <div className="trace-profile-card">
        <h3>{balanceIdentical ? 'Source and destination balance' : 'Source balance'} <small>requested {metricLabel}</small></h3>
        <div className="balance-grid">
          <div><span>Observed</span><strong>{sourceSummary.active}</strong><small>source nodes</small></div>
          <div><span>Median</span><strong>{formatValue(sourceSummary.median)}</strong><small>{formatValue(sourceSummary.min)}–{formatValue(sourceSummary.max)}</small></div>
          <div><span>Top share</span><strong>{sourceSummary.topShare.toFixed(2)} %</strong><small>{sourceSummary.top ? `node ${sourceSummary.top.node}` : '—'}</small></div>
        </div>
        {sourceSummary.uniform
          ? <p className="trace-insight">{balanceIdentical
            ? <><strong>Balanced.</strong> All {sourceSummary.active} sources carry and all {destinationSummary.active} destinations receive {formatValue(sourceSummary.max)} {metricLabel}.</>
            : <><strong>No source hotspot.</strong> All {sourceSummary.active} observed sources carry {formatValue(sourceSummary.max)} {metricLabel}.</>}</p>
          : <>
            <div className="activity-bars">{topSources.map(item => activity(item, sourcePeak))}</div>
            <p className="trace-insight">Top 5 of {sourceSummary.active}; largest share {sourceSummary.topShare.toFixed(2)} %.</p>
          </>}
      </div>
      {!balanceIdentical && <div className="trace-profile-card">
        <h3>Destination balance <small>requested {metricLabel}</small></h3>
        <div className="balance-grid">
          <div><span>Observed</span><strong>{destinationSummary.active}</strong><small>destination nodes</small></div>
          <div><span>Median</span><strong>{formatValue(destinationSummary.median)}</strong><small>{formatValue(destinationSummary.min)}–{formatValue(destinationSummary.max)}</small></div>
          <div><span>Top share</span><strong>{destinationSummary.topShare.toFixed(2)} %</strong><small>{destinationSummary.top ? `node ${destinationSummary.top.node}` : '—'}</small></div>
        </div>
        {destinationSummary.uniform
          ? <p className="trace-insight"><strong>No destination hotspot.</strong> All {destinationSummary.active} observed destinations receive {formatValue(destinationSummary.max)} {metricLabel}.</p>
          : <>
            <div className="activity-bars">{topDestinations.map(item => activity(item, destinationPeak))}</div>
            <p className="trace-insight">Top 5 of {destinationSummary.active}; largest share {destinationSummary.topShare.toFixed(2)} %.</p>
          </>}
      </div>}
      <div className="trace-profile-card">
        <h3>Packet size mix</h3>
        <div className="size-bars">{sizeRows.map(row => <div className="size-bar-row" key={row.flitCount}>
          <span className="mono">{row.flitCount} f</span>
          <span className="flow-track"><i style={{ width: `${row.flitShare}%` }} /></span>
          <span className="numeric">{row.count.toLocaleString()}</span>
          <small>{row.flitShare.toFixed(1)} % flits · {row.packetShare.toFixed(1)} % packets</small>
        </div>)}</div>
        <p className="trace-insight"><strong>Average {averagePacketSize.toFixed(2)} flits/packet.</strong> {dominantSize.flitCount}-flit packets carry {dominantSize.flitShare.toFixed(1)} % of requested flits.</p>
      </div>
    </div>
  </figure>;
}

// Projected packet playback. The bundle records requested injections, not observed hops, so the
// animation places each request on the revision's declared route and moves it at declared channel
// latency. It is explicitly a no-contention projection, never a recorded packet trace.
type Scheduled = { id: number; start: number; flits: number; routers: number[]; latencies: number[]; duration: number };

export function FlitPlayback({ decoded, topology, revisionId, maxPairs = 120 }: { decoded: { rows: InjectionRow[]; total: number }; topology?: Topology | null; revisionId?: string; maxPairs?: number }) {
  const rows = decoded.rows;
  const routerOf = useMemo(() => {
    const map = new Map<number, number>();
    for (const endpoint of topology?.endpoints ?? []) if (!map.has(endpoint.endpoint_id)) map.set(endpoint.endpoint_id, endpoint.router_id);
    return map;
  }, [topology]);
  const pairSelection = useMemo(() => {
    const weight = new Map<string, number>();
    for (const row of rows) {
      const src = routerOf.get(row.source), dst = routerOf.get(row.destination);
      if (src === undefined || dst === undefined || src === dst) continue;
      const key = `${src}:${dst}`;
      weight.set(key, (weight.get(key) ?? 0) + row.flits);
    }
    const ranked = [...weight.entries()].sort((a, b) => b[1] - a[1]);
    return { keys: ranked.slice(0, maxPairs).map(([key]) => key), total: ranked.length };
  }, [rows, routerOf, maxPairs]);
  const pairKeys = pairSelection.keys;
  const pairSet = useMemo(() => new Set(pairKeys), [pairKeys]);
  const [routes, setRoutes] = useState<Map<string, CanonicalRoute>>(new Map());
  const [resolving, setResolving] = useState({ done: 0, total: 0 });
  useEffect(() => {
    let live = true;
    setRoutes(new Map()); setResolving({ done: 0, total: pairKeys.length });
    if (!revisionId || !pairKeys.length) return;
    void resolveRoutes(revisionId, pairKeys, 3, (done, total) => { if (live) setResolving({ done, total }); })
      .then(result => { if (live) setRoutes(result.routes); });
    return () => { live = false; };
  }, [pairKeys, revisionId]);

  const schedule = useMemo(() => {
    if (!topology) return [] as Scheduled[];
    const latencyOf = new Map(topology.channels.map(channel => [channel.channel_id, channel.latency_cycles]));
    const out: Scheduled[] = [];
    rows.forEach((row, index) => {
      const src = routerOf.get(row.source), dst = routerOf.get(row.destination);
      if (src === undefined || dst === undefined || src === dst) return;
      if (!pairSet.has(`${src}:${dst}`)) return;
      const route = routes.get(`${src}:${dst}`);
      if (!route?.terminates || route.hops.length === 0) return;
      const latencies = route.hops.map(hop => latencyOf.get(hop.channel_id) ?? 1);
      out.push({ id: index, start: row.cycle, flits: row.flits, routers: route.routers, latencies, duration: latencies.reduce((n, value) => n + value, 0) });
    });
    return out;
  }, [rows, routes, routerOf, topology, pairSet]);

  const minCycle = rows.length ? Math.min(...rows.map(row => row.cycle)) : 0;
  const maxEnd = schedule.length ? Math.max(...schedule.map(packet => packet.start + packet.duration)) : minCycle + 1;
  const [cycle, setCycle] = useState(minCycle);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  useEffect(() => { setCycle(minCycle); setPlaying(false); }, [decoded, minCycle]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setCycle(value => Math.min(maxEnd, value + speed * 4)), 33);
    return () => window.clearInterval(timer);
  }, [playing, speed, maxEnd]);
  useEffect(() => { if (cycle >= maxEnd) setPlaying(false); }, [cycle, maxEnd]);

  if (!topology) return null;
  const { points } = topologyLayout(topology);
  const links = undirectedLinks(topology);
  const active = schedule.filter(packet => cycle >= packet.start && cycle < packet.start + packet.duration + 12);
  const hopAt = (packet: Scheduled) => {
    let remaining = cycle - packet.start;
    for (let i = 0; i < packet.latencies.length; i += 1) {
      if (remaining < packet.latencies[i]) return i;
      remaining -= packet.latencies[i];
    }
    // The marker holds at its destination for 12 cycles; keep the final hop highlighted.
    return packet.latencies.length - 1;
  };
  const position = (packet: Scheduled) => {
    let remaining = cycle - packet.start;
    for (let i = 0; i < packet.latencies.length; i += 1) {
      const latency = packet.latencies[i];
      if (remaining < latency) {
        const a = points.get(packet.routers[i]), b = points.get(packet.routers[i + 1]);
        if (!a || !b) return null;
        const t = latency ? remaining / latency : 0;
        return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
      }
      remaining -= latency;
    }
    // Hold at the destination briefly so a one-cycle hop is still visible; the caption says so.
    const end = points.get(packet.routers[packet.routers.length - 1]);
    return end ?? null;
  };
  // Concurrent projected flits on each undirected link at this cycle. This is a pressure view of
  // the projection only: no queue, arbitration, or observed timing is implied.
  const stress = new Map<string, number>();
  for (const packet of active) {
    const index = hopAt(packet);
    const a = packet.routers[index], b = packet.routers[index + 1];
    if (a === undefined || b === undefined) continue;
    const key = a < b ? `${a}-${b}` : `${b}-${a}`;
    stress.set(key, (stress.get(key) ?? 0) + packet.flits);
  }
  const peakStress = Math.max(1, ...stress.values());
  const resolvingRoutes = resolving.done < resolving.total;


  return <figure className="trace-figure playback">
    <div className="playback-controls">
      <button type="button" className="button primary" onClick={() => { if (cycle >= maxEnd) setCycle(minCycle); setPlaying(value => !value); }}>{playing ? 'Pause' : 'Play'}</button>
      <button type="button" className="button" onClick={() => { setPlaying(false); setCycle(minCycle); }}>Reset</button>
      <input type="range" aria-label="Playback cycle" min={minCycle} max={maxEnd} step={1} value={Math.round(cycle)} onChange={e => { setPlaying(false); setCycle(Number(e.target.value)); }} />
      <span className="mono">cycle {Math.round(cycle).toLocaleString()} / {maxEnd.toLocaleString()}</span>
      <label className="field field-inline"><span>Speed</span>
        <select value={speed} onChange={e => setSpeed(Number(e.target.value))}>{[1, 2, 4, 8].map(value => <option key={value} value={value}>{value}×</option>)}</select>
      </label>
      <span className="muted">{active.length} visible · {schedule.length.toLocaleString()} projected packets · peak link {peakStress.toLocaleString()} flits{pairSelection.total > pairKeys.length ? ` · top ${pairKeys.length} of ${pairSelection.total} router pairs` : ''}</span>
    </div>
    {resolvingRoutes && <p className="meta-line"><span className="pulse-dot" aria-hidden="true" />Resolving declared routes for {pairKeys.length} router pair{pairKeys.length === 1 ? '' : 's'}{pairSelection.total > pairKeys.length ? ` (top by requested flits; ${pairSelection.total} in the trace)` : ''} · {resolving.done}/{resolving.total}</p>}
    <svg className="playback-canvas" viewBox="0 0 800 620" role="img" aria-label={`Projected flit playback at cycle ${Math.round(cycle)}`}>
      <g className="gateway-links">{links.map(([a, b]) => {
        const p = points.get(a), q = points.get(b);
        return p && q ? <line key={`${a}-${b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} /> : null;
      })}</g>
      <g className="playback-stress">{links.map(([a, b]) => {
        const value = stress.get(a < b ? `${a}-${b}` : `${b}-${a}`) ?? 0;
        if (!value) return null;
        const p = points.get(a), q = points.get(b);
        if (!p || !q) return null;
        const share = value / peakStress;
        return <line key={`stress-${a}-${b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} className={`playback-stress-line${share > 0.6 ? ' hot' : ''}`} style={{ strokeWidth: 2 + 6 * share, opacity: 0.35 + 0.6 * share }} />;
      })}</g>
      <g className="playback-nodes">{[...points.entries()].map(([id, p]) => <circle key={id} cx={p.x} cy={p.y} r={topology.routers.length > 40 ? 5 : 7} />)}</g>
      <g className="playback-packets">{active.map(packet => {
        const at = position(packet);
        return at ? <circle key={packet.id} cx={at.x} cy={at.y} r={2.5 + Math.min(3, packet.flits / 3)}>
          <title>{`packet ${packet.id + 1} · ${packet.flits} flits · started cycle ${packet.start}`}</title>
        </circle> : null;
      })}</g>
    </svg>
    <figcaption>Projected from requested injections on declared routes at declared channel latency, with no queueing or arbitration simulated; link width is concurrent projected flits, not measured utilization.</figcaption>
  </figure>;
}
