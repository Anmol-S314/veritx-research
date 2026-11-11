import { memo, useCallback, useMemo, useState } from 'react';
import type { SimLoad, SimSeries, Topology } from './gateway';
import { buildChannelIndex, matchMeasuredChannel } from './channelTopology';
import {
  directionShares, WINDOW_METRICS, windowMetricRecorded, windowMetricRows, windowSummary,
  type WindowMetric, type WindowRow,
} from './channelAnalysis';
import { bucketWindows } from './windowBuckets';
import { contextTarget } from './contextSelection';

const compact = (value: number) => value >= 10_000 ? `${(value / 1000).toFixed(0)}k` : value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toLocaleString();
const percent = (value: number) => `${(100 * value).toFixed(1)} %`;

const ROW_LIMIT = 24;
/** Columns are bucketed so a cell stays wide enough to read at page width.
 *  Each still sums whole windows; the footer and caption name the stride. */
const MAX_COLUMNS = 48;
const RAMP_STEPS = 5;

const bucketSpan = (col: number, stride: number, sourceWindows: number) =>
  `windows ${col * stride + 1}–${Math.min(sourceWindows, (col + 1) * stride)}`;

/** Cell colour follows the counter, so switching metric changes the reading
 *  without changing the matrix structure. */
const METRIC_RGB: Record<WindowMetric, [number, number, number]> = {
  flits: [15, 108, 158],
  queue: [176, 121, 24],
  arb: [163, 41, 40],
  tx: [44, 107, 69],
  occupancy: [123, 94, 167],
};

/** One channel row. Memoised so moving the pointer across a cell only
 *  re-renders the two rows whose hover state changed, not the whole matrix. */
const MatrixRow = memo(function MatrixRow({ row, rowIndex, y, left, width, cellWidth, cellHeight, stride, sourceWindows, hoverCol, isSelected, suffix, unit, metricLabel, cellFill, onSelect, onHover }: {
  row: WindowRow; rowIndex: number; y: number; left: number; width: number; cellWidth: number; cellHeight: number;
  stride: number; sourceWindows: number; hoverCol: number | null; isSelected: boolean; suffix: string;
  unit: string; metricLabel: string;
  cellFill: (value: number) => string; onSelect: (id: string) => void; onHover: (hover: { row: number; col: number }) => void;
}) {
  const amount = (value: number) => unit === 'flits'
    ? `${value.toLocaleString()} flits`
    : `${value.toLocaleString()} ${unit} ${metricLabel.toLowerCase()}`;
  return <g role="button" tabIndex={0} aria-pressed={isSelected}
    aria-label={`Channel ${row.id}, ${amount(row.total)}, active in ${row.activeWindows} windows`}
    {...contextTarget('channel', row.id, `Measured channel CH-${row.id}`, `${amount(row.total)} in the sampled window series · active in ${row.activeWindows} windows`)}
    onClick={() => onSelect(row.id)}
    onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(row.id); } }}>
    <rect x={0} y={y} width={width} height={cellHeight} className="window-row-hit" pointerEvents="all" aria-hidden="true" />
    {hoverCol !== null && <rect x={0} y={y} width={width} height={cellHeight} className="window-row-hover" pointerEvents="none" aria-hidden="true" />}
    <text x={6} y={y + cellHeight / 2 + 3.5} className={`window-row-label${isSelected ? ' selected' : ''}`}>CH-{row.id}</text>
    <text x={left - 8} y={y + cellHeight / 2 + 3.5} textAnchor="end" className="window-row-context">{suffix}</text>
    {row.values.map((value, windowIndex) => <rect key={windowIndex} x={left + windowIndex * cellWidth} y={y + 1} width={cellWidth - 1} height={cellHeight - 2} rx={2}
      fill={cellFill(value)}
      className={`window-cell${hoverCol === windowIndex ? ' hovered' : ''}`}
      onMouseEnter={() => onHover({ row: rowIndex, col: windowIndex })}
      aria-hidden="true">
      <title>{`CH-${row.id} · ${bucketSpan(windowIndex, stride, sourceWindows)}: ${amount(value)}${row.total ? ` (${percent(value / row.total)} of this channel)` : ''}`}</title>
    </rect>)}
    {isSelected && <rect x={left} y={y + 1} width={row.values.length * cellWidth} height={cellHeight - 2} fill="none" className="window-row-outline" aria-hidden="true" />}
    <rect x={0} y={y + 1} width={width} height={cellHeight - 2} className="window-row-focus" aria-hidden="true" />
    <text x={width - 6} y={y + cellHeight / 2 + 3.5} className="window-row-total">{compact(row.total)}</text>
  </g>;
});

export function ChannelWindowMatrix({ series, topology, loadChannels, selected, onSelect, portWires }: {
  series: SimSeries; topology: Topology | null; loadChannels: NonNullable<SimLoad['channels']>; selected: string; onSelect: (id: string) => void;
  portWires?: Map<string, { wire: number; taps: number[] }>;
}) {
  const [order, setOrder] = useState<'time' | 'load'>('time');
  // 'auto' keeps the matrix at MAX_COLUMNS or fewer; a number is an explicit
  // bucket size in original windows. Finer values scroll horizontally.
  const [grain, setGrain] = useState<'auto' | number>('auto');
  const [rowLimit, setRowLimit] = useState<number | 'all'>(ROW_LIMIT);
  const [metric, setMetric] = useState<WindowMetric>('flits');
  const [hover, setHover] = useState<{ row: number | null; col: number } | null>(null);
  const recorded = useMemo(() => Object.fromEntries(WINDOW_METRICS.map(entry => [entry.id, windowMetricRecorded(series, entry.id)])) as Record<WindowMetric, { recorded: number; total: number }>, [series]);
  const metrics = WINDOW_METRICS.filter(entry => recorded[entry.id].recorded > 0);
  const activeMetric = metrics.some(entry => entry.id === metric) ? metric : metrics[0]?.id ?? 'flits';
  const definition = WINDOW_METRICS.find(entry => entry.id === activeMetric) ?? WINDOW_METRICS[0];
  // Bucket once per series/metric/order/grain change: the previous version
  // rebuilt every row and total array on each render (including each hover).
  const matrix = useMemo(() => {
    const limit = rowLimit === 'all' ? Math.max(1, series.channels.length) : rowLimit;
    const raw = windowMetricRows(series, activeMetric, limit, order);
    const auto = bucketWindows(raw.windowTotals, MAX_COLUMNS);
    const stride = grain === 'auto' ? auto.stride : Math.max(1, Math.floor(grain));
    const totals = stride === auto.stride ? auto : bucketWindows(raw.windowTotals, MAX_COLUMNS, 'sum', stride);
    return {
      ...raw,
      sourceWindows: raw.numWindows,
      autoStride: auto.stride,
      stride: totals.stride,
      numWindows: totals.values.length,
      windowTotals: totals.values,
      rows: raw.rows.map(row => ({ ...row, values: bucketWindows(row.values, MAX_COLUMNS, 'sum', stride).values })),
    };
  }, [series, activeMetric, order, grain, rowLimit]);
  const grainChoices = useMemo(() => {
    const powers = [1, 2, 4, 8, 16, 32, 64, 128, 256].filter(value => value <= matrix.sourceWindows || value === 1);
    const values = typeof grain === 'number' ? [...new Set([...powers, grain])].sort((a, b) => a - b) : powers;
    return values;
  }, [matrix.sourceWindows, grain]);
  const summary = useMemo(() => windowSummary(series, activeMetric), [series, activeMetric]);
  const index = useMemo(() => buildChannelIndex(topology, portWires), [topology, portWires]);
  const directions = useMemo(() => directionShares(loadChannels, topology, portWires), [loadChannels, topology, portWires]);
  const shownTotal = matrix.rows.reduce((sum, row) => sum + row.total, 0);
  const seriesTotal = matrix.windowTotals.reduce((sum, value) => sum + value, 0);
  const shownShare = seriesTotal ? shownTotal / seriesTotal : 0;
  const maxCell = Math.max(1, ...matrix.rows.flatMap(row => row.values));
  const maxTotal = Math.max(0, ...matrix.windowTotals);
  const busiestBucket = maxTotal > 0 ? matrix.windowTotals.indexOf(maxTotal) : -1;
  const peakTotal = Math.max(1, maxTotal);
  // State the conclusion the matrix supports, in the same measured terms as
  // the phase facts. This is a reading of the counters, not a new metric.
  const medianActiveLabel = summary.medianActiveWindows === null ? '—'
    : Number.isInteger(summary.medianActiveWindows) ? String(summary.medianActiveWindows) : summary.medianActiveWindows.toFixed(1);
  const medianCoverage = summary.medianActiveWindows !== null && summary.numWindows ? summary.medianActiveWindows / summary.numWindows : null;
  const busiestShare = summary.totalFlits ? summary.busiestFlits / summary.totalFlits : 0;
  const reading = (() => {
    const noun = definition.unit === 'flits' ? 'flits' : definition.unit === 'flit·cyc' ? 'occupancy' : 'cycles';
    if (summary.totalFlits === 0) {
      return `No channel recorded non-zero ${definition.label.toLowerCase()} in this run. The ${matrix.rows.length} rows below are the busiest flit channels, shown for reference; every cell is a measured zero.`;
    }
    const coverage = medianCoverage === null
      ? 'The window series does not cover every channel.'
      : medianCoverage >= 0.9
        ? `The median channel is active in ${medianActiveLabel} of ${summary.numWindows} windows, so the shown rows form a steady band rather than phase-switched blocks.`
        : medianCoverage >= 0.5
          ? `The median channel is active in only ${medianActiveLabel} of ${summary.numWindows} windows; read across a row for its on/off pattern.`
          : `The median channel is idle in most windows (${medianActiveLabel} of ${summary.numWindows} active); this is a sparse, bursty series.`;
    const phase = summary.twoPhaseChannels > 0
      ? `${summary.twoPhaseChannels} of ${summary.activeChannels} active channels switch on in two separate runs.`
      : 'No active channel switches on twice.';
    const concentration = summary.busiestWindow < 0
      ? 'No window carries a non-zero total.'
      : busiestShare < 0.05
        ? `The busiest window (W${summary.busiestWindow + 1}) carries only ${percent(busiestShare)} of series ${noun}, so no single window dominates.`
        : busiestShare > 0.25
          ? `The busiest window (W${summary.busiestWindow + 1}) carries ${percent(busiestShare)} of series ${noun}, so load is concentrated in a few windows.`
          : `The busiest window (W${summary.busiestWindow + 1}) carries ${percent(busiestShare)} of series ${noun}.`;
    return `The ${matrix.rows.length} shown rows carry ${percent(shownShare)} of measured ${noun}. ${coverage} ${phase} ${concentration}`;
  })();
  const cadence = activeMetric === 'flits' ? 'Read this as the offered load that reached the crossbar.'
    : activeMetric === 'queue' ? 'These are summed wait cycles, not elapsed time; a channel can contribute more than one stall cycle per window.'
      : activeMetric === 'arb' ? 'These are summed lost-arbitration cycles, not elapsed time; zero is a real measurement.'
        : activeMetric === 'tx' ? 'Transmit-busy includes cycles an output held a staged flit, so it is not the same as flits moved.'
          : 'Occupancy is a flit-cycle integral; divide by the window span for mean queued flits.';
  const left = 158, right = 58, top = 26, header = 18, cellWidth = 24, cellHeight = 20;
  const rowsTop = top + header;
  const width = left + matrix.numWindows * cellWidth + right;
  const footerTop = rowsTop + matrix.rows.length * cellHeight + 12;
  const baseline = footerTop + 34;
  const height = baseline + 26;
  const cellFill = useCallback((value: number) => {
    if (value <= 0) return '#eef3f7';
    const opacity = Math.min(0.94, 0.14 + 0.8 * Math.sqrt(value / maxCell));
    const [red, green, blue] = METRIC_RGB[activeMetric];
    return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
  }, [maxCell, activeMetric]);
  const suffixFor = (id: string) => {
    const match = matchMeasuredChannel(index, Number(id));
    return match?.local ? 'eject' : match?.wire ? `wire ${match.wire.id}` : match?.channel ? `→R${match.channel.dst_router}` : '—';
  };
  const bucketLabel = (col: number) => bucketSpan(col, matrix.stride, matrix.sourceWindows);
  const readout = (() => {
    if (!hover) return null;
    const total = matrix.windowTotals[hover.col] ?? 0;
    if (hover.row === null) {
      return {
        title: `Fabric total · ${bucketLabel(hover.col)}`,
        detail: `${total.toLocaleString()} ${definition.unit} ${definition.label.toLowerCase()} across ${matrix.activeChannels} active channels${summary.totalFlits ? ` · ${percent(total / summary.totalFlits)} of the series` : ''}`,
      };
    }
    const row = matrix.rows[hover.row];
    const value = row.values[hover.col] ?? 0;
    return {
      title: `CH-${row.id} · ${suffixFor(row.id)} · ${bucketLabel(hover.col)}`,
      detail: `${value.toLocaleString()} ${definition.unit} · ${total ? percent(value / total) : '—'} of this bucket · ${row.total ? percent(value / row.total) : '—'} of this channel`,
    };
  })();

  if (!matrix.rows.length || matrix.numWindows === 0) {
    return <p className="meta-line">The sampled window series carries no active channel rows for {definition.label.toLowerCase()}.</p>;
  }

  return <div className="activity-block" data-testid="window-matrix-block" data-metric={activeMetric}>
    <div className="activity-head">
      <div>
        <h3>Fabric activity over windows</h3>
        <p className="meta-line">Cells are <strong>{definition.label.toLowerCase()}</strong> ({definition.unit}) per bucket. Each column sums up to {matrix.stride} original {matrix.stride === 1 ? 'window' : 'windows'} ({(matrix.stride * (series.sample_period_cycles ?? 1)).toLocaleString()} cycles); the last bucket may be shorter.</p>
      </div>
      <div className="activity-controls">
        <label className="field window-grain">
          <span>Windows / column</span>
          <select aria-label="Original windows per column" title="Columns group this many original windows. Auto keeps the matrix at 48 columns or fewer; finer settings scroll horizontally." value={String(grain)} onChange={event => { const value = event.target.value; setGrain(value === 'auto' ? 'auto' : Number(value)); }}>
            <option value="auto">Auto ({matrix.autoStride})</option>
            {grainChoices.map(value => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="field window-rows">
          <span>Rows</span>
          <select aria-label="Channel rows shown" title="Show the busiest channels for the selected counter, or every active channel." value={String(rowLimit)} onChange={event => { const value = event.target.value; setRowLimit(value === 'all' ? 'all' : Number(value)); }}>
            <option value={24}>Top 24</option>
            <option value={48}>Top 48</option>
            <option value={96}>Top 96</option>
            <option value="all">All active</option>
          </select>
        </label>
        <div className="segmented" role="group" aria-label="Measured window counter">
          {metrics.map(entry => <button type="button" key={entry.id} className={activeMetric === entry.id ? 'active' : ''} aria-pressed={activeMetric === entry.id}
            title={entry.description} onClick={() => setMetric(entry.id)}>{entry.short}</button>)}
        </div>
        <div className="segmented" role="group" aria-label="Channel window ordering">
          <button type="button" className={order === 'time' ? 'active' : ''} aria-pressed={order === 'time'} title="Rows sorted by each channel's value-weighted window centroid, lining up channels active at similar times. Window columns remain chronological." onClick={() => setOrder('time')}>Phase order</button>
          <button type="button" className={order === 'load' ? 'active' : ''} aria-pressed={order === 'load'} title="Rows sorted by total measured value, busiest first. Window columns remain chronological." onClick={() => setOrder('load')}>Load order</button>
        </div>
      </div>
    </div>
    <p className="window-reading" data-testid="window-reading"><strong>What this shows:</strong> {reading} {cadence}</p>
    <div className="window-readout" data-testid="window-readout">
      {readout
        ? <><strong className="mono">{readout.title}</strong><span>{readout.detail}</span></>
        : <span>Hover a cell for its bucket and channel share; hover a footer bar for the fabric total.</span>}
      <span className="window-ramp">0
        {Array.from({ length: RAMP_STEPS }, (_, step) => <i key={step} style={{ background: cellFill((maxCell * step) / (RAMP_STEPS - 1)) }} aria-hidden="true" />)} {compact(maxCell)} {definition.unit}
      </span>
    </div>
    <div className="activity-layout">
      <figure className="window-matrix">
        <div className="window-matrix-scroll">
          <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label={`Measured ${definition.label.toLowerCase()} per window for the top ${matrix.rows.length} channels`} onMouseLeave={() => setHover(null)}
            style={{ width: width > 1600 ? `${width}px` : undefined, maxWidth: width > 1600 ? 'none' : undefined }}>
            <text x={6} y={top + 12} className="window-tick">channel</text>
            <text x={left - 8} y={top + 12} textAnchor="end" className="window-tick">link</text>
            {Array.from({ length: matrix.numWindows }, (_, index) => index).filter(index => index % 4 === 0 || index === matrix.numWindows - 1)
              .map(index => <text key={index} x={left + index * cellWidth + cellWidth / 2} y={top + 12} textAnchor="middle" className="window-tick">W{index * matrix.stride + 1}</text>)}
            <line x1={left - 4} x2={left - 4} y1={rowsTop - 4} y2={baseline} className="window-axis" aria-hidden="true" />
            {busiestBucket >= 0 && <line x1={left + busiestBucket * cellWidth + cellWidth / 2} x2={left + busiestBucket * cellWidth + cellWidth / 2} y1={rowsTop - 4} y2={baseline} className="window-peak-line" aria-hidden="true" />}
            {matrix.rows.map((row, rowIndex) => <MatrixRow key={row.id} row={row} rowIndex={rowIndex}
              y={rowsTop + rowIndex * cellHeight} left={left} width={width} cellWidth={cellWidth} cellHeight={cellHeight}
              stride={matrix.stride} sourceWindows={matrix.sourceWindows} unit={definition.unit} metricLabel={definition.label}
              hoverCol={hover?.row === rowIndex ? hover.col : null} isSelected={selected === row.id}
              suffix={suffixFor(row.id)} cellFill={cellFill} onSelect={onSelect} onHover={setHover} />)}
            {hover && <rect x={left + hover.col * cellWidth} y={rowsTop - 2} width={cellWidth} height={baseline - rowsTop + 2} className="window-col-hover" aria-hidden="true" />}
            <line x1={left - 4} x2={width - right} y1={baseline} y2={baseline} className="window-axis" aria-hidden="true" />
            <text x={6} y={footerTop + 30} className="window-row-label">Fabric total</text>
            <g>
              {matrix.windowTotals.map((value, index) => {
                const barHeight = Math.max(1.5, (value / peakTotal) * 34);
                const isHovered = hover?.row === null && hover.col === index;
                return <rect key={index} x={left + index * cellWidth + 1} y={baseline - barHeight} width={cellWidth - 2} height={barHeight} rx={2}
                  className={`window-total${index === busiestBucket ? ' peak' : ''}${isHovered ? ' hovered' : ''}`}
                  style={{ fill: isHovered ? '#0f6c9e' : index === busiestBucket ? '#b07918' : cellFill(maxCell * 0.55) }}
                  onMouseEnter={() => setHover({ row: null, col: index })}>
                  <title>{`${bucketLabel(index)}: ${value.toLocaleString()} ${definition.unit} across all channels`}</title>
                </rect>;
              })}
              {busiestBucket >= 0 && <text x={left + busiestBucket * cellWidth + cellWidth / 2} y={baseline - 38} textAnchor="middle" className="window-total-label" aria-hidden="true">{compact(maxTotal)}</text>}
            </g>
          </svg>
        </div>
        <figcaption className="meta-line">Cell colour is {definition.label.toLowerCase()} in one displayed bucket (0 → {maxCell.toLocaleString()} {definition.unit}); footer bars are bucket totals. Rows are the {matrix.rows.length} busiest of {matrix.activeChannels} active channels{recorded[activeMetric].recorded < recorded[activeMetric].total ? `; ${recorded[activeMetric].total - recorded[activeMetric].recorded} channels do not record this counter` : ''}, ordered by {order === 'time' ? 'value-weighted window centroid' : 'total measured value'}.</figcaption>
      </figure>
      <aside className="activity-facts">
        <div className="activity-facts-main">
          <h3>Phase structure</h3>
          <dl className="properties">
            <div><dt>Median active windows</dt><dd>{summary.medianActiveWindows === null ? '—' : `${medianActiveLabel} of ${summary.numWindows}`}</dd></div>
            <div><dt>Two-phase channels</dt><dd>{summary.twoPhaseChannels} of {summary.activeChannels} active</dd></div>
            <div><dt>Busiest window</dt><dd>{summary.busiestWindow < 0 ? '—' : `W${summary.busiestWindow + 1}`} · {summary.busiestFlits.toLocaleString()} {definition.unit}</dd></div>
            <div><dt>Busiest window share</dt><dd>{percent(busiestShare)} of series {definition.unit}</dd></div>
            <div><dt>Rows shown</dt><dd>{summary.activeChannels ? `${matrix.rows.length} of ${matrix.activeChannels} · ${percent(shownShare)} of ${definition.unit}` : `${matrix.rows.length} reference rows · no active ${definition.label.toLowerCase()}`}</dd></div>
            {recorded[activeMetric].recorded < recorded[activeMetric].total && <div><dt>Counter coverage</dt><dd>{recorded[activeMetric].recorded} of {recorded[activeMetric].total} channels</dd></div>}
          </dl>
        </div>
        {activeMetric === 'flits' && directions.length > 0 && <div className="direction-block">
          <div className="load-share-head"><span>Flits by output port</span><strong>{directions.reduce((sum, share) => sum + share.channels, 0).toLocaleString()} active ports</strong></div>
          <div className="share-stack direction-stack" role="img" aria-label={`Measured flits by source-port class: ${directions.map(share => `${share.label} ${percent(share.share)}`).join(', ')}`}>
            {directions.map(share => <span key={share.key} className={`share-seg direction-${share.key}`} style={{ width: `${100 * share.share}%` }} />)}
          </div>
          <div className="share-legend direction-legend">
            {directions.map(share => <span key={share.key}><i className={`share-dot direction-${share.key}`} aria-hidden="true" /> {share.label} <strong>{percent(share.share)}</strong> <small>{share.flits.toLocaleString()} · {share.channels} ports</small></span>)}
          </div>
        </div>}
      </aside>
    </div>
  </div>;
}

export function ChannelWindowChart({ id, windows: rawWindows, queueMax: rawQueueMax, latencyMax: rawLatencyMax, samplePeriod }: {
  id: string; windows: number[]; queueMax?: number[] | null; latencyMax?: number[] | null; samplePeriod?: number;
}) {
  const { values: windows, stride } = bucketWindows(rawWindows);
  const queueMax = rawQueueMax ? bucketWindows(rawQueueMax, 80, 'max').values : rawQueueMax;
  const latencyMax = rawLatencyMax ? bucketWindows(rawLatencyMax, 80, 'max').values : rawLatencyMax;
  const n = windows.length;
  const width = 1000, left = 52, right = 16, top = 20, lane1 = 128, lane2 = 52, lane3 = 52, gap = 18, bottom = 34;
  const y2 = top + lane1 + gap;
  const y3 = y2 + lane2 + gap;
  const height = y3 + lane3 + bottom;
  const plotWidth = width - left - right;
  const slot = n ? plotWidth / n : plotWidth;
  const xOf = (index: number) => left + index * slot + slot / 2;
  const peak = Math.max(1, ...windows);
  const mean = n ? windows.reduce((sum, value) => sum + value, 0) / n : 0;
  const queueValues = Array.from({ length: n }, (_, index) => queueMax?.[index] ?? 0);
  const latencyValues = Array.from({ length: n }, (_, index) => latencyMax?.[index] ?? 0);
  const hasQueue = Array.isArray(queueMax) && queueMax.length > 0;
  const hasLatency = Array.isArray(latencyMax) && latencyMax.length > 0;
  const queuePeak = Math.max(1, ...queueValues);
  const latencyPeak = Math.max(1, ...latencyValues);
  const busiest = windows.indexOf(Math.max(...windows));
  const line = (values: number[], max: number, laneTop: number, laneHeight: number) => values.map((value, index) => `${xOf(index)},${laneTop + laneHeight - (value / max) * laneHeight}`).join(' ');
  const area = (values: number[], max: number, laneTop: number, laneHeight: number) => values.length
    ? `${left},${laneTop + laneHeight} ${line(values, max, laneTop, laneHeight)} ${left + plotWidth},${laneTop + laneHeight}`
    : '';
  const ticks = Array.from({ length: n }, (_, index) => index).filter(index => index % 4 === 0 || index === n - 1);

  if (!n) return null;
  return <figure className="window-lanes">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Measured window series for channel ${id}: flits, queue-wait maxima in cycles, and per-hop latency maxima in cycles`}>
      <text x={left - 7} y={top + 9} textAnchor="end" className="chart-axis-title">flits</text>
      <text x={left - 7} y={y2 + 9} textAnchor="end" className="chart-axis-title">queue</text>
      <text x={left - 7} y={y3 + 9} textAnchor="end" className="chart-axis-title">latency</text>
      <text x={width - right} y={top + 9} textAnchor="end" className="chart-tick">peak {peak.toLocaleString()}</text>
      <text x={width - right} y={y2 + 9} textAnchor="end" className="chart-tick">{hasQueue ? `peak ${queuePeak.toLocaleString()} cyc` : 'not recorded'}</text>
      <text x={width - right} y={y3 + 9} textAnchor="end" className="chart-tick">{hasLatency ? `peak ${latencyPeak.toLocaleString()} cyc` : 'not recorded'}</text>
      <line x1={left} x2={left + plotWidth} y1={top + lane1} y2={top + lane1} className="window-axis" />
      <line x1={left} x2={left + plotWidth} y1={y2 + lane2} y2={y2 + lane2} className="window-axis" />
      <line x1={left} x2={left + plotWidth} y1={y3 + lane3} y2={y3 + lane3} className="window-axis" />
      <line x1={xOf(busiest)} x2={xOf(busiest)} y1={top - 2} y2={y3 + lane3} className="window-peak-line">
        <title>Busiest window: W{busiest + 1}</title>
      </line>
      {windows.map((value, index) => {
        const barHeight = (value / peak) * lane1;
        return <rect key={index} x={left + index * slot + 1} y={top + lane1 - barHeight} width={Math.max(1, slot - 2)} height={barHeight} className="series-bar">
          <title>Window {index + 1}: {value.toLocaleString()} flits</title>
        </rect>;
      })}
      {mean > 0 && <line x1={left} x2={left + plotWidth} y1={top + lane1 - (mean / peak) * lane1} y2={top + lane1 - (mean / peak) * lane1} className="series-mean" />}
      {hasQueue ? <>
        <path d={`M ${area(queueValues, queuePeak, y2, lane2)} Z`} className="window-queue-area" />
        <polyline points={line(queueValues, queuePeak, y2, lane2)} className="window-queue-line" />
        {queueValues.map((value, index) => <circle key={index} cx={xOf(index)} cy={y2 + lane2 - (value / queuePeak) * lane2} r={2.4} className="window-queue-point"><title>Window {index + 1}: peak queue wait {value.toLocaleString()} cycles</title></circle>)}
      </> : <text x={left + plotWidth / 2} y={y2 + lane2 / 2 + 3} textAnchor="middle" className="chart-tick">queue maxima not recorded</text>}
      {hasLatency ? <>
        <polyline points={line(latencyValues, latencyPeak, y3, lane3)} className="window-latency-line" />
        {latencyValues.map((value, index) => <circle key={index} cx={xOf(index)} cy={y3 + lane3 - (value / latencyPeak) * lane3} r={2.4} className="window-latency-point"><title>Window {index + 1}: peak {value.toLocaleString()} cycles per hop</title></circle>)}
      </> : <text x={left + plotWidth / 2} y={y3 + lane3 / 2 + 3} textAnchor="middle" className="chart-tick">latency maxima not recorded</text>}
      {ticks.map(index => <text key={index} x={xOf(index)} y={height - 17} textAnchor={index === 0 ? 'start' : index === n - 1 ? 'end' : 'middle'} className="chart-tick">W{index + 1}</text>)}
    </svg>
    <figcaption className="meta-line">{n} displayed buckets · {stride} original windows/bucket · peak {peak.toLocaleString()} · mean {mean.toFixed(1)}{samplePeriod ? ` · ${samplePeriod.toLocaleString()} cycles/window` : ''}. Lower lanes keep the maximum queue wait and per-hop latency per bucket.</figcaption>
  </figure>;
}
