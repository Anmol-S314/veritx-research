import { useEffect, useMemo, useState } from 'react';
import type { LoadedProject, LoadedRun } from './project';
import { useProject } from './project';
import { fetchVerifiedArtifact } from './RawArtifacts';
import { selectInjectionTrace, scanInjectionTrace, type InjectionSpan } from './trace';
import { decodeObservedPackets, packetGroupTotals, GROUP_LABELS, type ObservedPacketCapture, type ObservedPhaseGroup } from './observedPackets';
import { fabricWorkBudget, runClockBudget, sampledBudget, samplingAdvice } from './cycleBudget';
import { useSimSeries } from './measuredData';
import { useRunTopology } from './runTopology';
import { Badge, Notice, PageLink, Section } from './ui';

type Loaded<T> = { phase: 'loading' | 'ready' | 'absent' | 'error'; data?: T; text?: string; reason?: string };

const percent = (value: number) => `${(100 * value).toFixed(1)} %`;
const cycles = (value: number | null | undefined) => value === null || value === undefined ? '—' : `${value.toLocaleString()} cyc`;
const numberAs = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;

const GROUP_CLASS: Record<ObservedPhaseGroup, string> = {
  source: 'budget-source', queue: 'budget-queue', arbitration: 'budget-arb',
  transmission: 'budget-tx', drain: 'budget-drain',
};

const GROUPS: ObservedPhaseGroup[] = ['source', 'queue', 'arbitration', 'transmission', 'drain'];

function StackedBar({ segments, total, label }: {
  segments: { key: string; label: string; value: number; className: string }[];
  total: number;
  label: string;
}) {
  const shown = segments.filter(segment => segment.value > 0);
  if (!shown.length || total <= 0) return <div className="budget-bar empty" role="img" aria-label={`${label}: no measured cycles`}><span>No measured cycles</span></div>;
  return <div className="budget-bar" role="img" aria-label={`${label}: ${shown.map(segment => `${segment.label} ${segment.value.toLocaleString()} cycles`).join(', ')}`}>
    {shown.map(segment => <span key={segment.key} className={`budget-seg ${segment.className}`}
      style={{ width: `${100 * segment.value / total}%` }}
      title={`${segment.label}: ${segment.value.toLocaleString()} cycles (${percent(segment.value / total)})`} />)}
  </div>;
}

function Legend({ segments }: { segments: { key: string; label: string; value: number; className: string }[] }) {
  return <div className="budget-legend">
    {segments.map(segment => <span key={segment.key}><i className={`budget-key ${segment.className}`} aria-hidden="true" /> {segment.label} <strong>{segment.value.toLocaleString()}</strong></span>)}
  </div>;
}

export function CycleBudget({ project, run }: { project: LoadedProject; run: LoadedRun }) {
  const { health } = useProject();
  const topology = useRunTopology(project, run);
  const series = useSimSeries(run.detail.run_id);
  const files = run.artifacts?.bundle?.files ?? {};
  const metrics = run.detail.evaluation?.metrics ?? {};
  const available = !!health?.features?.artifact_bytes;
  const tracePath = selectInjectionTrace(Object.keys(files));
  const traceChecksum = tracePath ? files[tracePath] : '';
  const observedPath = Object.keys(files).find(name => name.endsWith('/observed_hops.log') || name === 'observed_hops.log');
  const observedChecksum = observedPath ? files[observedPath] : '';
  const [trace, setTrace] = useState<Loaded<InjectionSpan>>({ phase: 'loading' });
  const [observed, setObserved] = useState<Loaded<ObservedPacketCapture>>({ phase: 'loading' });

  useEffect(() => {
    let live = true;
    setTrace({ phase: 'loading' });
    if (!tracePath) {
      setTrace({ phase: 'absent', reason: 'This bundle carries no requested-injection trace, so the injection span is not available.' });
      return () => { live = false; };
    }
    if (!available) {
      setTrace({ phase: 'absent', reason: 'The gateway does not serve verified artifact bytes, so the sealed trace cannot be read.' });
      return () => { live = false; };
    }
    fetchVerifiedArtifact(run.detail.run_id, tracePath, traceChecksum)
      .then(bytes => {
        if (!live) return;
        const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        setTrace({ phase: 'ready', data: scanInjectionTrace(text) });
      })
      .catch(error => { if (live) setTrace({ phase: 'error', reason: error instanceof Error ? error.message : String(error) }); });
    return () => { live = false; };
  }, [run.detail.run_id, tracePath, traceChecksum, available]);

  useEffect(() => {
    let live = true;
    setObserved({ phase: 'loading' });
    if (!observedPath) {
      setObserved({ phase: 'absent', reason: 'This bundle has no watched packet capture, so no sampled per-packet budget is drawn.' });
      return () => { live = false; };
    }
    if (!available) {
      setObserved({ phase: 'absent', reason: 'The gateway does not serve verified artifact bytes, so the watch log cannot be read.' });
      return () => { live = false; };
    }
    fetchVerifiedArtifact(run.detail.run_id, observedPath, observedChecksum)
      .then(bytes => {
        if (!live) return;
        const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        setObserved({ phase: 'ready', text });
      })
      .catch(error => { if (live) setObserved({ phase: 'error', reason: error instanceof Error ? error.message : String(error) }); });
    return () => { live = false; };
  }, [run.detail.run_id, observedPath, observedChecksum, available]);

  const capture = useMemo(() => observed.text && topology ? decodeObservedPackets(observed.text, topology) : null, [observed.text, topology]);
  const sampled = useMemo(() => sampledBudget(capture?.packets ?? []), [capture]);
  const watchedLastInjection = useMemo(() => {
    const values = (capture?.packets ?? []).map(path => path.injectionCycle).filter((value): value is number => typeof value === 'number' && value >= 0);
    return values.length ? Math.max(...values) : null;
  }, [capture]);
  const completion = numberAs(metrics.completion_cycles);
  const clock = useMemo(() => runClockBudget(trace.data ?? null, completion), [trace.data, completion]);
  const work = useMemo(() => fabricWorkBudget(series.data), [series.data]);
  const advice = samplingAdvice(series.data, completion);
  const sample = (run.detail as { observed_hop_capture?: { sample?: { declared_packets?: number; stride?: number; sampled_packets?: number } } }).observed_hop_capture?.sample;
  // The trace stops at the last request, but packets can still be waiting in
  // the source queue. The watched sample's latest injection is one real point
  // after that request, so it splits the tail into a measured backlog lower
  // bound and a network-drain upper bound. It is a sample, not the run's last
  // injection.
  const watchedTail = clock.completion !== null && clock.lastInjection !== null && watchedLastInjection !== null
    ? (() => {
      const split = Math.min(clock.completion, Math.max(clock.lastInjection, watchedLastInjection));
      return { split, backlog: Math.max(0, split - clock.lastInjection), drain: Math.max(0, clock.completion - split) };
    })()
    : null;

  const clockSegments = useMemo(() => {
    const segments = [
      { key: 'lead', label: 'Lead-in', value: clock.leadIn ?? 0, className: 'budget-lead' },
      { key: 'injection', label: 'Injection span (requests)', value: clock.injectionSpan ?? 0, className: 'budget-inject' },
    ];
    if (watchedTail) {
      segments.push(
        { key: 'backlog', label: 'Post-request backlog (watched)', value: watchedTail.backlog, className: 'budget-backlog' },
        { key: 'drain', label: 'Drain upper bound', value: watchedTail.drain, className: 'budget-drain' },
      );
    } else {
      segments.push({ key: 'tail', label: 'Post-request tail', value: Math.max(0, clock.drain ?? 0), className: 'budget-drain' });
    }
    if (clock.completion === null) return segments;
    const known = segments.reduce((sum, segment) => sum + segment.value, 0);
    if (known < clock.completion) segments.push({ key: 'gap', label: 'Unattributed clock', value: clock.completion - known, className: 'budget-gap' });
    return segments;
  }, [clock, watchedTail]);

  const workSegments = useMemo(() => work ? [
    { key: 'queue', label: GROUP_LABELS.queue, value: work.queueCycles, className: GROUP_CLASS.queue },
    { key: 'arb', label: 'Arbitration wait', value: work.arbCycles, className: GROUP_CLASS.arbitration },
    { key: 'tx', label: 'Transmit busy', value: work.txBusyCycles, className: GROUP_CLASS.transmission },
  ] : [], [work]);

  const longest = sampled.longest;
  const longestTotals = longest ? packetGroupTotals(longest) : null;
  const packetSegments = longestTotals ? GROUPS.map(group => ({
    key: group, label: GROUP_LABELS[group], value: longestTotals[group], className: GROUP_CLASS[group],
  })) : [];
  const watchedRows = useMemo(() => [...(capture?.packets ?? [])].sort((a, b) => (b.total ?? -1) - (a.total ?? -1)), [capture]);

  return <Section id="cycle-budget" title="Cycle budget" actions={<>
    <Badge tone={completion === null ? 'amber' : 'green'}>{completion === null ? 'No completion' : `${completion.toLocaleString()} cycles`}</Badge>
    {capture && <Badge tone="blue">{capture.packets.length} watched packets</Badge>}
    {work && <Badge>{work.windows} window{work.windows === 1 ? '' : 's'}</Badge>}
  </>}>
    {advice && <Notice tone="amber">{advice}</Notice>}
    {clock.completion !== null && !clock.consistent && <Notice tone="red"><strong>The trace outlasts the recorded completion.</strong> The last requested injection is at cycle {clock.lastInjection?.toLocaleString()} but the run reports completion at {clock.completion.toLocaleString()}. The two artifacts cannot be aligned without an explanation.</Notice>}

    <div className="budget-grid">
      <div className="budget-panel">
        <div className="budget-head">
          <div><h3>Run clock</h3><p className="meta-line">Elapsed cycles from request timestamps and the recorded last ejection.</p></div>
          <Badge tone={trace.phase === 'ready' ? 'blue' : 'amber'}>{trace.phase === 'ready' ? 'Trace + stats' : 'Partial'}</Badge>
        </div>
        {trace.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the sealed injection trace…</p>}
        {trace.phase === 'error' && <Notice tone="red">{trace.reason}</Notice>}
        {trace.phase === 'ready' && clock.completion !== null && <>
          <StackedBar segments={clockSegments} total={clock.completion} label="Run clock budget" />
          <Legend segments={clockSegments} />
          <dl className="properties budget-facts">
            <div><dt>First request</dt><dd>{cycles(clock.firstInjection)}</dd></div>
            <div><dt>Last request</dt><dd>{cycles(clock.lastInjection)}</dd></div>
            <div><dt>Injection span (requests)</dt><dd>{cycles(clock.injectionSpan)}</dd></div>
            <div><dt>Post-request tail</dt><dd>{cycles(clock.drain)}</dd></div>
            {watchedLastInjection !== null && <div><dt>Last watched injection</dt><dd>{cycles(watchedLastInjection)}</dd></div>}
            {watchedTail && <div><dt>Backlog / drain bound</dt><dd>{cycles(watchedTail.backlog)} / ≤{cycles(watchedTail.drain)}</dd></div>}
            <div><dt>Completion</dt><dd>{cycles(clock.completion)}</dd></div>
            <div><dt>Declared traffic</dt><dd>{clock.declaredPackets.toLocaleString()} packets · {clock.declaredFlits.toLocaleString()} flits</dd></div>
            <div><dt>Reported p50 / p95 / p99</dt><dd>{cycles(numberAs(metrics.p50))} / {cycles(numberAs(metrics.p95))} / {cycles(numberAs(metrics.p99))}</dd></div>
          </dl>
          <p className="meta-line">The injection span is the trace's request window, and it overlaps delivery: packets are crossing the fabric while later requests are still being offered. The post-request tail starts at the last request, so it contains source backlog as well as network drain. {watchedTail
            ? `The latest watched injection is at ${watchedLastInjection!.toLocaleString()}, splitting the tail into at least ${watchedTail.backlog.toLocaleString()} backlog cycles and at most ${watchedTail.drain.toLocaleString()} network-drain cycles. This is a sampled split; an unwatched packet may inject later.`
            : 'No watched injection is available to split the tail, and all-packet injection times are not recorded.'}</p>
        </>}
        {trace.phase !== 'ready' && clock.completion !== null && <>
          <StackedBar segments={[{ key: 'completion', label: 'Completion', value: clock.completion, className: 'budget-inject' }]} total={clock.completion} label="Completion clock only" />
          <p className="meta-line">Only the completion timestamp is available; the injection and drain boundaries need the trace. {trace.reason}</p>
        </>}
        {clock.completion === null && trace.phase !== 'loading' && <Notice tone="amber">This run reports no completion cycle, so a clock budget cannot be drawn.</Notice>}
      </div>

      <div className="budget-panel">
        <div className="budget-head">
          <div><h3>Measured fabric work</h3><p className="meta-line">Queue, arbitration and transmit counters summed over channels and windows.</p></div>
          <Badge tone={work?.hasQueue || work?.hasArb || work?.hasTx ? 'green' : 'amber'}>{work ? (work.hasQueue || work.hasArb || work.hasTx ? 'Measured split' : 'Counters absent') : series.phase === 'loading' ? 'Reading…' : 'Not recorded'}</Badge>
        </div>
        {series.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the sampled series…</p>}
        {series.phase === 'error' && <Notice tone="red">{series.reason}</Notice>}
        {series.phase === 'absent' && <p className="meta-line">This run carries no sampled window series, so the measured work split is unavailable. Series sampling is opt-in.</p>}
        {work && <>
          <StackedBar segments={workSegments} total={work.totalWork} label="Measured fabric work" />
          <Legend segments={workSegments} />
          <dl className="properties budget-facts">
            <div><dt>Measured work</dt><dd>{work.totalWork.toLocaleString()} flit·cycles</dd></div>
            <div><dt>Queue / flit</dt><dd>{work.flits ? `${(work.queueCycles / work.flits).toFixed(2)} cyc` : '—'}</dd></div>
            <div><dt>Arbitration / flit</dt><dd>{work.flits ? `${(work.arbCycles / work.flits).toFixed(2)} cyc` : '—'}</dd></div>
            <div><dt>Transmit / flit</dt><dd>{work.flits ? `${(work.txBusyCycles / work.flits).toFixed(2)} cyc` : '—'}</dd></div>
            <div><dt>Measured flits</dt><dd>{work.flits.toLocaleString()} over {work.channels.toLocaleString()} channels</dd></div>
            <div><dt>Window</dt><dd>{work.samplePeriod ? `${work.samplePeriod.toLocaleString()} cyc` : 'not stated'}{work.windows ? ` · ${work.windows.toLocaleString()} windows` : ''}</dd></div>
            <div><dt>Occupancy integral</dt><dd>{work.occupancy.toLocaleString()} flit·cycles</dd></div>
          </dl>
          <p className="meta-line">These are sums of per-channel counters, not elapsed wall time and not a partition of the completion clock. Queue, arbitration and transmit events are measured separately and can overlap; use the shares to compare runs, not to add them to the request span. Measured flits count every recorded output traversal, including local eject, so they can exceed the declared flit count.</p>
        </>}
      </div>

      <div className="budget-panel budget-wide">
        <div className="budget-head">
          <div><h3>Longest watched packet</h3><p className="meta-line">Head-flit pipeline from the bounded watch sample, closed by the packet's tail retire.</p></div>
          <Badge tone={longest ? 'blue' : 'amber'}>{longest ? `P${longest.packet}` : observed.phase === 'loading' ? 'Reading…' : 'No complete path'}</Badge>
        </div>
        {observed.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the watched packet capture…</p>}
        {observed.phase === 'error' && <Notice tone="red">{observed.reason}</Notice>}
        {observed.phase === 'absent' && <p className="meta-line">{observed.reason}</p>}
        {longest && longestTotals && <>
          <div className="budget-packet-head">
            <span className="mono">P{longest.packet}</span>
            <span>N{longest.source} → N{longest.destination}</span>
            <span>{longest.hops} hops · {longest.flits} flits</span>
            <span className="mono">request {longest.requestTime.toLocaleString()} → retire {longest.retireCycle?.toLocaleString()}</span>
          </div>
          <StackedBar segments={packetSegments} total={longestTotals.total} label={`Packet ${longest.packet} phase budget`} />
          <Legend segments={packetSegments} />
          {longestTotals.source > 0 && longestTotals.total > longestTotals.source && <>
            <p className="meta-line">Network path with source wait excluded ({cycles(longestTotals.total - longestTotals.source)}):</p>
            <StackedBar segments={packetSegments.filter(segment => segment.key !== 'source')} total={longestTotals.total - longestTotals.source} label={`Packet ${longest.packet} network phase budget`} />
          </>}
          <dl className="properties budget-facts">
            <div><dt>Packet latency</dt><dd>{cycles(longest.total)}</dd></div>
            <div><dt>Source wait</dt><dd>{cycles(longestTotals.source)} <small>{percent(longestTotals.total ? longestTotals.source / longestTotals.total : 0)}</small></dd></div>
            <div><dt>Router queue</dt><dd>{cycles(longestTotals.queue)} <small>{percent(longestTotals.total ? longestTotals.queue / longestTotals.total : 0)}</small></dd></div>
            <div><dt>Arbitration</dt><dd>{cycles(longestTotals.arbitration)} <small>{percent(longestTotals.total ? longestTotals.arbitration / longestTotals.total : 0)}</small></dd></div>
            <div><dt>Transmission</dt><dd>{cycles(longestTotals.transmission)} <small>{percent(longestTotals.total ? longestTotals.transmission / longestTotals.total : 0)}</small></dd></div>
            <div><dt>Body drain</dt><dd>{cycles(longestTotals.drain)} <small>{percent(longestTotals.total ? longestTotals.drain / longestTotals.total : 0)}</small></dd></div>
            <div><dt>Watched sample</dt><dd>{sampled.completeCount} complete of {sampled.count}{sample?.stride ? ` · every ${sample.stride}th packet` : ''}</dd></div>
            <div><dt>Sample p50 / p95</dt><dd>{cycles(sampled.median)} / {cycles(sampled.p95)}</dd></div>
          </dl>
          <p className="meta-line">This is the longest of the watched packets, not the run's worst packet. Body flits are not drawn individually; the closing drain segment runs from the head's retire to the packet's tail retire. <PageLink page="analysis/trace">Open the per-packet Gantt</PageLink></p>
        </>}
        {observed.phase === 'ready' && !longest && <p className="meta-line">The capture decoded {capture?.packets.length ?? 0} packets but no path has every boundary needed for a complete budget. Incomplete paths stay out of the totals.</p>}
      </div>
    </div>

    {watchedRows.length > 0 && <details className="origin">
      <summary>Watched packets · per-packet budget ({watchedRows.length})</summary>
      <p className="meta-line">Only complete paths enter the sample totals. A dash is a phase the capture did not record.</p>
      <div className={`table-scroll${watchedRows.length > 12 ? ' capped' : ''}`}><table aria-label="Watched packet cycle budget">
        <thead><tr><th>Packet</th><th>Route</th><th>Request → retire</th><th>Total</th><th>Source</th><th>Queue</th><th>Arb</th><th>Tx</th><th>Drain</th><th>Path</th></tr></thead>
        <tbody>
          {watchedRows.map(path => {
            const totals = packetGroupTotals(path);
            return <tr key={path.packet}>
              <th className="mono">P{path.packet}</th>
              <td className="mono">N{path.source} → N{path.destination}</td>
              <td className="numeric mono">{path.requestTime.toLocaleString()} → {path.retireCycle?.toLocaleString() ?? '—'}</td>
              <td className="numeric">{cycles(path.total)}</td>
              <td className="numeric">{cycles(totals.source)}</td>
              <td className="numeric">{cycles(totals.queue)}</td>
              <td className="numeric">{cycles(totals.arbitration)}</td>
              <td className="numeric">{cycles(totals.transmission)}</td>
              <td className="numeric">{cycles(totals.drain)}</td>
              <td><Badge tone={path.complete ? 'green' : 'amber'}>{path.complete ? 'complete' : 'incomplete'}</Badge></td>
            </tr>;
          })}
        </tbody>
      </table></div>
    </details>}
  </Section>;
}
