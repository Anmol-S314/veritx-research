import { useMemo, useState } from 'react';
import { Badge, Empty, Notice, Section } from './ui';
import type { LoadedRun } from './project';
import type { Topology } from './gateway';
import { useSimLoad } from './measuredData';
import { portWiresUsable, usePortWires } from './portWires';
import { attributionSummary, flitShares, median, utilizationBins, utilizationRangeFor, type LoadChannel, type UtilizationBin, type UtilizationRange, type UtilizationSeries } from './channelAnalysis';
import { contextTarget } from './contextSelection';

const percent = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? '—' : `${(100 * value).toFixed(digits)} %`;

function niceTickStep(rough: number): number {
  const exponent = Math.floor(Math.log10(Math.max(rough, 1)));
  const base = 10 ** exponent;
  const norm = rough / base;
  const factor = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return factor * base;
}

function UtilizationHistogram({ bins, step, total, active, sustainedMedian, activeMedian, peakMedian, selectedRange, onSelectRange }: {
  bins: UtilizationBin[]; step: number; total: number; active: number;
  sustainedMedian: number | null; activeMedian: number | null; peakMedian: number | null;
  selectedRange: UtilizationRange | null; onSelectRange: (range: UtilizationRange | null) => void;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const selectedIndex = selectedRange ? bins.findIndex(bin => bin.low === selectedRange.low && bin.high === selectedRange.high) : -1;
  const selectedSeries: UtilizationSeries | null = selectedIndex >= 0 ? selectedRange!.series : null;
  const readBin = hovered !== null ? bins[hovered] : selectedIndex >= 0 ? bins[selectedIndex] : null;
  const width = 570, height = 220, left = 38, right = 12, top = 18, bottom = 34;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const maxCount = Math.max(1, ...bins.flatMap(bin => [bin.sustained, bin.peak]));
  const tickStep = niceTickStep(maxCount / 5);
  const niceMax = Math.max(tickStep, Math.ceil(maxCount / tickStep) * tickStep);
  const ticks = Array.from({ length: Math.round(niceMax / tickStep) + 1 }, (_, index) => index * tickStep);
  const groupWidth = plotWidth / bins.length;
  const barWidth = Math.min(18, groupWidth * 0.34);
  const yOf = (value: number) => top + plotHeight - (value / niceMax) * plotHeight;
  const label = (value: number) => step < 0.05 ? `${(100 * value).toFixed(1)}%` : `${(100 * value).toFixed(0)}%`;

  const readout = readBin
    ? <>
      <strong className="mono">{label(readBin.low)}–{label(readBin.high)}</strong>
      <span>{readBin.sustained.toLocaleString()} sustained · {readBin.peak.toLocaleString()} peak-window channels</span>
      {selectedIndex >= 0 && <span>Filtering the measured-channel list below by {selectedSeries === 'peak' ? 'peak-window' : 'sustained'} utilization</span>}
      {selectedIndex >= 0 && <button type="button" className="text-button" onClick={() => onSelectRange(null)}>Clear filter</button>}
    </>
    : <span>Hover a bin for counts. Click the sustained or the peak-window bar to filter the measured-channel list by that measure.</span>;

  return <figure className="load-histogram">
    <div className="load-histogram-head">
      <h3>Sustained vs peak window utilization</h3>
      <div className="load-histogram-key"><span><i className="load-dot sustained" />Sustained</span><span><i className="load-dot peak" />Peak window</span></div>
    </div>
    <div className="load-bin-readout" data-testid="load-bin-readout">{readout}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Histogram of sustained and peak-window utilization across measured channels"
      onMouseLeave={() => setHovered(null)}>
      {ticks.map(value => <g key={value}>
        <line x1={left} x2={width - right} y1={yOf(value)} y2={yOf(value)} className="chart-grid" />
        <text x={left - 6} y={yOf(value) + 3} textAnchor="end" className="chart-tick">{value.toLocaleString()}</text>
      </g>)}
      {bins.map((bin, index) => {
        const center = left + groupWidth * (index + 0.5);
        const sustainedHeight = top + plotHeight - yOf(bin.sustained);
        const peakHeight = top + plotHeight - yOf(bin.peak);
        const isSelected = index === selectedIndex;
        const pick = (series: UtilizationSeries) => onSelectRange(index === selectedIndex && selectedSeries === series ? null : utilizationRangeFor(bin, index, bins, step, series));
        // A click on the bin's empty space has no bar to speak for it. Prefer the
        // measure that actually has channels in this bin, so a reader who clicks
        // where they saw a count never lands on an empty list.
        const pickFromBackground = () => pick(bin.sustained > 0 || bin.peak === 0 ? 'sustained' : 'peak');
        return <g key={index} role="button" tabIndex={0} aria-pressed={isSelected}
          aria-label={`${label(bin.low)} to ${label(bin.high)} sustained utilization: ${bin.sustained} channels, ${bin.peak} peak-window channels`}
          {...contextTarget('utilization-bin', `${bin.low}-${bin.high}`, `Utilization bin ${label(bin.low)}–${label(bin.high)}`, `sustained: ${bin.sustained} channels · peak window: ${bin.peak} channels`)}
          onMouseEnter={() => setHovered(index)} onFocus={() => setHovered(index)} onBlur={() => setHovered(null)}
          onClick={pickFromBackground}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); pickFromBackground(); } }}>
          <title>{label(bin.low)}–{label(bin.high)} sustained: {bin.sustained} channels · peak window: {bin.peak} channels</title>
          <rect x={left + index * groupWidth} y={top} width={groupWidth} height={plotHeight} className="load-bin-hit" />
          <rect x={center - barWidth - 1} y={yOf(bin.sustained)} width={barWidth} height={sustainedHeight} className={`load-bar sustained${isSelected && selectedSeries === 'sustained' ? ' selected' : ''}`} onClick={event => { event.stopPropagation(); pick('sustained'); }} />
          <rect x={center + 1} y={yOf(bin.peak)} width={barWidth} height={peakHeight} className={`load-bar peak${isSelected && selectedSeries === 'peak' ? ' selected' : ''}`} onClick={event => { event.stopPropagation(); pick('peak'); }} />
          {bin.sustained > 0 && <text x={center - barWidth / 2 - 1} y={yOf(bin.sustained) - 3} textAnchor="middle" className="chart-count">{bin.sustained}</text>}
          {bin.peak > 0 && <text x={center + barWidth / 2 + 1} y={yOf(bin.peak) - 3} textAnchor="middle" className="chart-count">{bin.peak}</text>}
          <text x={left + index * groupWidth} y={height - 13} textAnchor="middle" className="chart-tick">{label(bin.low)}</text>
        </g>;
      })}
      <text x={left + plotWidth} y={height - 13} textAnchor="end" className="chart-tick">{label(bins[bins.length - 1]?.high ?? 0)}</text>
      <text x={width - right} y={10} textAnchor="end" className="chart-axis-title">Utilization bins</text>
      <text x={left} y={10} className="chart-axis-title">Channels</text>
    </svg>
    <figcaption className="meta-line">Medians: {percent(sustainedMedian)} sustained over {total.toLocaleString()} channels · {percent(activeMedian)} among {active.toLocaleString()} active · {percent(peakMedian)} peak-window.</figcaption>
  </figure>;
}

function ShareStack({ groups, className }: { groups: { label: string; share: number; flits: number; channels: number }[]; className: string }) {
  return <div className={`share-stack ${className}`} role="img" aria-label="Share of measured flits by group">
    {groups.map((group, index) => group.share > 0
      ? <span key={group.label} className={`share-seg share-${className}-${index}`} style={{ width: `${100 * group.share}%` }} title={`${group.label}: ${group.flits.toLocaleString()} flits (${(100 * group.share).toFixed(1)} %)`} />
      : null)}
  </div>;
}

export function MeasuredLoadShape({ run, topology, selectedRange, onSelectRange }: {
  run: LoadedRun; topology: Topology | null;
  selectedRange: UtilizationRange | null;
  onSelectRange: (range: UtilizationRange | null) => void;
}) {
  const state = useSimLoad(run.detail.run_id);
  const wires = usePortWires(run, topology);
  const portWires = portWiresUsable(wires.map) ? wires.map.ports : undefined;
  const channels: LoadChannel[] = state.data?.channels ?? [];
  const active = channels.filter(channel => channel.flits_total > 0);
  const bins = useMemo(() => utilizationBins(channels), [channels]);
  const shares = useMemo(() => flitShares(channels), [channels]);
  const attribution = useMemo(() => attributionSummary(channels, topology, portWires), [channels, topology, portWires]);
  const sustainedMedian = median(channels.map(channel => channel.utilization));
  const activeMedian = median(active.map(channel => channel.utilization));
  const peakMedian = median(channels.map(channel => channel.peak_window_utilization));
  const totalFlits = attribution.totalFlits || channels.reduce((sum, channel) => sum + channel.flits_total, 0);
  const declaredShare = totalFlits ? (attribution.declaredFlits + attribution.wireFlits) / totalFlits : 0;
  const localShare = totalFlits ? attribution.localFlits / totalFlits : 0;
  const unmatchedShare = totalFlits ? attribution.unattributedFlits / totalFlits : 0;
  const topShare = shares[0]?.share ?? 0;
  const declaredTotal = topology?.channels.length ?? 0;

  return <Section title="Fabric load shape · measured channels" actions={<Badge tone={state.phase === 'ready' ? 'green' : 'amber'}>{state.phase === 'ready' ? `${channels.length} channels` : 'Not recorded'}</Badge>}>
    {state.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the sampled channel counters…</p>}
    {state.phase === 'absent' && <p className="meta-line">This run carries no sampled channel counters, so there is no distribution to draw.</p>}
    {state.phase === 'error' && <Notice tone="red">{state.reason}</Notice>}
    {state.phase === 'ready' && (!channels.length ? <Empty title="No channel rows in this series">The artifact parsed without per-channel counters.</Empty> : <>
      <div className="load-shape-layout">
        <UtilizationHistogram bins={bins.bins} step={bins.step} total={channels.length} active={active.length}
          sustainedMedian={sustainedMedian} activeMedian={activeMedian} peakMedian={peakMedian}
          selectedRange={selectedRange} onSelectRange={onSelectRange} />
        <aside className="load-shape-side">
          <h3>Attribution and concentration</h3>
          {attribution.grid || attribution.wireChannels ? <>
            <div className="load-share-block">
              <div className="load-share-head"><span>Flits by join class</span><strong>{totalFlits.toLocaleString()} flits</strong></div>
              <div className="share-stack" role="img" aria-label="Measured flits split between declared fabric resources (channels or shared wires), local eject ports, and unmatched ports">
                {declaredShare > 0 && <span className="share-seg share-attribution-0" style={{ width: `${100 * declaredShare}%` }} title={`Declared fabric: ${(attribution.declaredFlits + attribution.wireFlits).toLocaleString()} flits (${attribution.declaredFlits.toLocaleString()} channels, ${attribution.wireFlits.toLocaleString()} shared wires)`} />}
                {localShare > 0 && <span className="share-seg share-attribution-1" style={{ width: `${100 * localShare}%` }} title={`Local eject: ${attribution.localFlits.toLocaleString()} flits`} />}
                {unmatchedShare > 0 && <span className="share-seg share-attribution-2" style={{ width: `${100 * unmatchedShare}%` }} title={`Unmatched network: ${attribution.unattributedFlits.toLocaleString()} flits`} />}
              </div>
              <div className="share-legend">
                <span data-testid="attrib-joined"><i className="share-dot share-attribution-0" /><strong>{attribution.wireFlits ? 'Plane D wires' : 'Declared network'}</strong> {(attribution.declaredFlits + attribution.wireFlits).toLocaleString()} · {percent(declaredShare)}</span>
                <span data-testid="attrib-local"><i className="share-dot share-attribution-1" /><strong>Local eject</strong> {attribution.localFlits.toLocaleString()} · {percent(localShare)}</span>
                {attribution.unattributedFlits > 0 && <span data-testid="attrib-joined-not"><i className="share-dot share-attribution-2" /><strong>{attribution.wireFlits ? 'Ports without a verified join' : 'No declared link'}</strong> {attribution.unattributedFlits.toLocaleString()} · {percent(unmatchedShare)}</span>}
              </div>
              {attribution.unattributedFlits > 0 && <p className="meta-line">{attribution.unattributedFlits.toLocaleString()} network flits sit on ports without a verified join; they are shown, not reassigned.</p>}
            </div>
          </> : <Notice tone="amber"><strong>No verified port-to-wire join for this fabric.</strong> {wires.reason ?? 'The histogram and flit ranks remain measured; attribution shares are omitted rather than guessed.'}</Notice>}
          <div className="load-share-block">
            <div className="load-share-head"><span>Flits by channel rank</span><strong>top 10 = {percent(topShare)}</strong></div>
            <ShareStack groups={shares} className="rank" />
            <div className="share-legend">
              {shares.map((group, index) => <span key={group.label}><i className={`share-dot share-rank-${index}`} /><strong>{group.label}</strong> {percent(group.share)}</span>)}
            </div>
          </div>
          <dl className="shape-facts">
            <div><dt>Active channels</dt><dd>{active.length.toLocaleString()} / {channels.length.toLocaleString()}</dd></div>
            <div><dt>Median sustained</dt><dd>{percent(sustainedMedian)} all · {percent(activeMedian)} active</dd></div>
            <div><dt>Declared resources joined</dt><dd>{attribution.grid ? `${attribution.declaredChannels} / ${declaredTotal || attribution.declaredChannels}` : attribution.wireChannels ? `${attribution.wireChannels} of ${topology?.shared_links?.length ?? 0} wires` : '—'}</dd></div>
            <div><dt>Boundary ports</dt><dd>{attribution.grid ? `${attribution.boundaryIdleChannels} idle, no declared link` : '—'}</dd></div>
          </dl>
        </aside>
      </div>
      <p className="meta-line">Bars count channels; both series share one 0–{Math.round(100 * bins.step * bins.bins.length)} % axis.</p>
      </>)}
  </Section>;
}
