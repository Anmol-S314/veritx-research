import { useId } from 'react';
import { chartLogScale, chartScale } from './chartScale';
import { formatMetric, metricValue, seriesColor, type WorkbenchMetric, type WorkbenchObservation, type WorkbenchView } from './analysisWorkbench';

const W = 860, H = 396, L = 76, R = 26, T = 42, B = 66;
const BAR_H = 430, BAR_L = 72, BAR_R = 24, BAR_T = 44, BAR_B = 92;

const axisTitle = (metric: WorkbenchMetric | undefined, fallback: string): string => {
  if (!metric) return fallback;
  const unit = metric.unit ? ` (${metric.unit})` : '';
  const direction = metric.direction ? ` · ${metric.direction === 'MIN' ? 'lower' : 'higher'} is better` : '';
  return `${metric.label}${unit}${direction}`;
};

const shortLabel = (value: string, keep = 18): string => value.length <= keep ? value : `${value.slice(0, keep - 1)}…`;

export function EvidencePlot({
  view, xKey, yKey, mode, observations, metrics, frontIds, selectedId, hoveredId,
  onHover, onSelect, onClear, includeZero, logY, title,
}: {
  view: WorkbenchView;
  xKey: string;
  yKey: string;
  mode: 'curve' | 'scatter' | 'bars';
  observations: WorkbenchObservation[];
  metrics: Map<string, WorkbenchMetric>;
  frontIds: Set<string>;
  selectedId: string | null;
  hoveredId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  onClear: () => void;
  includeZero: boolean;
  logY: boolean;
  title: string;
}) {
  const helpId = useId();
  const xMetric = metrics.get(xKey), yMetric = metrics.get(yKey);
  if (mode === 'bars') {
    return <BarPlot {...{ view, yKey, observations, metrics, frontIds, selectedId, hoveredId, onHover, onSelect, title, helpId }} />;
  }
  const points = observations.filter(observation => metricValue(observation, xKey) !== null && metricValue(observation, yKey) !== null);
  if (!points.length || !xMetric || !yMetric) return null;
  const seriesNames = [...new Set(points.flatMap(point => point.series ? [point.series] : []))];
  const colourBySeries = seriesNames.length > 0;
  const hasSeries = mode === 'curve' && xKey === view.seriesAxis && colourBySeries;
  const focusSeries = points.find(point => point.id === selectedId)?.series;
  const selected = points.find(point => point.id === selectedId);
  const preview = points.find(point => point.id === hoveredId) ?? selected;
  const xs = chartScale(points.map(point => metricValue(point, xKey)!), includeZero);
  const useLogY = logY && points.every(point => (metricValue(point, yKey) ?? 0) > 0);
  const ys = useLogY ? chartLogScale(points.map(point => metricValue(point, yKey)!)) : chartScale(points.map(point => metricValue(point, yKey)!), includeZero);
  const yDigits = useLogY ? 3 : (ys as ReturnType<typeof chartScale>).digits;
  const y = (value: number) => T + (1 - (useLogY
    ? (Math.log10(value) - Math.log10(ys.min)) / Math.max(1e-9, Math.log10(ys.max) - Math.log10(ys.min))
    : (value - ys.min) / Math.max(1e-9, ys.max - ys.min))) * (H - T - B);
  const x = (value: number) => L + (value - xs.min) / Math.max(1e-9, xs.max - xs.min) * (W - L - R);
  const ticks = useLogY ? ys.ticks : ys.ticks;
  const label = `${title}: ${yMetric.label} versus ${xMetric.label}`;
  const orderedSeries = seriesNames.map(name => ({
    name,
    points: points.filter(point => point.series === name).sort((a, b) => metricValue(a, xKey)! - metricValue(b, xKey)!),
  }));

  return <>
    <svg className="curve-svg interactive-plot wb-plot" viewBox={`0 0 ${W} ${H}`} role="group" aria-label={label} aria-describedby={helpId}>
      <desc id={helpId}>Measured observations only. Tab through points; Enter or Space selects one. {hasSeries ? 'Selecting a point isolates its arm; the inspector arm list can also isolate a curve.' : 'The axes determine the plotted comparison.'}</desc>
      {ticks.map(tick => <g key={`y${tick}`}>
        <line x1={L} x2={W - R} y1={y(tick)} y2={y(tick)} className="grid-line" />
        <text x={L - 10} y={y(tick) + 4} textAnchor="end" className="curve-label">{tick.toLocaleString(undefined, { maximumFractionDigits: yDigits })}</text>
      </g>)}
      {xs.ticks.map(tick => <g key={`x${tick}`}>
        <line x1={x(tick)} x2={x(tick)} y1={T} y2={H - B} className="grid-line" />
        <text x={x(tick)} y={H - B + 20} textAnchor="middle" className="curve-label">{tick.toLocaleString(undefined, { maximumFractionDigits: xs.digits })}</text>
      </g>)}
      <line x1={L} x2={W - R} y1={H - B} y2={H - B} className="curve-axis" />
      <line x1={L} x2={L} y1={T} y2={H - B} className="curve-axis" />
      {preview && <g aria-hidden="true" className="plot-crosshair">
        <line x1={L} x2={W - R} y1={y(metricValue(preview, yKey)!)} y2={y(metricValue(preview, yKey)!)} />
        <line x1={x(metricValue(preview, xKey)!)} x2={x(metricValue(preview, xKey)!)} y1={T} y2={H - B} />
      </g>}
      {hasSeries && orderedSeries.map(series => {
        const dim = focusSeries !== undefined && focusSeries !== series.name;
        return <polyline key={`line-${series.name}`} fill="none"
          stroke={seriesColor(series.name, seriesNames)}
          strokeWidth={focusSeries === series.name ? 3 : 1.7}
          opacity={dim ? 0.16 : 0.9}
          points={series.points.map(point => `${x(metricValue(point, xKey)!)},${y(metricValue(point, yKey)!)}`).join(' ')} />;
      })}
      {points.map(point => {
        const px = metricValue(point, xKey)!, py = metricValue(point, yKey)!;
        const isSelected = point.id === selectedId, isHovered = point.id === hoveredId;
        const front = frontIds.has(point.id);
        const dim = hasSeries && focusSeries !== undefined && point.series !== focusSeries;
        const colour = colourBySeries ? seriesColor(point.series, seriesNames) : front ? '#246847' : '#8a9aa8';
        const radius = hasSeries ? (isSelected ? 5.5 : isHovered ? 4.5 : front ? 3.2 : 2.7)
          : (isSelected ? 7 : isHovered ? 6 : front ? 5.5 : 4.5);
        return <g key={point.id} className={`wb-point ${front ? 'front' : ''} ${isSelected ? 'selected' : ''} ${dim ? 'dim' : ''}`}
          transform={`translate(${x(px)},${y(py)})`} opacity={dim ? 0.18 : 1}
          role="button" tabIndex={0} aria-label={`Inspect ${point.label}`} aria-pressed={isSelected}
          onPointerEnter={() => onHover(point.id)} onPointerLeave={() => onHover(null)}
          onFocus={() => onHover(point.id)} onBlur={() => onHover(null)}
          onClick={() => onSelect(point.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(point.id); } }}>
          <title>{`${point.label}${point.sublabel ? ` · ${point.sublabel}` : ''}: ${xMetric.label} ${formatMetric(xMetric, px)}; ${yMetric.label} ${formatMetric(yMetric, py)}${point.series ? `; series ${point.series}` : ''}${front ? '; non-dominated' : ''}${point.excluded ? `; excluded: ${point.excluded}` : ''}`}</title>
          <circle className="point-target" r={13} />
          {(isSelected || isHovered) && <circle className="point-ring" r={11} />}
          <circle className="point-mark" r={radius} fill={colour} stroke={isSelected ? '#083d5a' : front ? '#1d242c' : colourBySeries ? colour : '#536170'} strokeWidth={isSelected ? 1.8 : front ? 2.1 : 1.2} />
        </g>;
      })}
      {preview && <text x={Math.min(W - R - 4, Math.max(L + 4, x(metricValue(preview, xKey)!)))} y={Math.max(T + 14, y(metricValue(preview, yKey)!) - 18)}
        textAnchor={x(metricValue(preview, xKey)!) > W / 2 ? 'end' : 'start'} className="curve-label strong point-label" pointerEvents="none">{preview.label}</text>}
      <text x={(L + W - R) / 2} y={H - 12} textAnchor="middle" className="curve-axis-title">{axisTitle(xMetric, 'Observation')}</text>
      <text x={L} y={22} className="curve-axis-title">{axisTitle(yMetric, 'Value')}{useLogY ? ' · log scale' : ''}</text>
    </svg>
    {colourBySeries && seriesNames.length > 1 && <div className="wb-series-key" aria-label="Colour key">
      {seriesNames.map(name => <span key={name}><i style={{ background: seriesColor(name, seriesNames) }} />{name}</span>)}
    </div>}
    {hasSeries && focusSeries && <div className="wb-series-focus" role="group" aria-label="Focused arm">
      <span><i style={{ background: seriesColor(focusSeries, seriesNames) }} /><span className="mono">{focusSeries}</span> focused</span>
      <button type="button" className="text-button" onClick={onClear}>Show all arms</button>
    </div>}
  </>;
}

function BarPlot({
  view, yKey, observations, metrics, frontIds, selectedId, hoveredId, onHover, onSelect, title, helpId,
}: {
  view: WorkbenchView;
  yKey: string;
  observations: WorkbenchObservation[];
  metrics: Map<string, WorkbenchMetric>;
  frontIds: Set<string>;
  selectedId: string | null;
  hoveredId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  title: string;
  helpId: string;
}) {
  const yMetric = metrics.get(yKey);
  const points = observations.filter(observation => metricValue(observation, yKey) !== null);
  if (!points.length || !yMetric) return null;
  const seriesNames = [...new Set(points.flatMap(point => point.series ? [point.series] : []))];
  const colourBySeries = Boolean(view.barColorBySeries) && seriesNames.length > 0;
  const ordered = view.barSort === 'value'
    ? [...points].sort((a, b) => {
      const av = metricValue(a, yKey)!, bv = metricValue(b, yKey)!;
      return yMetric.direction === 'MIN' ? av - bv : bv - av;
    })
    : points;
  const values = ordered.map(point => metricValue(point, yKey)!);
  const useLog = Boolean(view.barLog) && values.every(value => value > 0);
  const ys = useLog ? chartLogScale(values) : chartScale([...values, 0], true);
  const yDigits = useLog ? 3 : (ys as ReturnType<typeof chartScale>).digits;
  const base = useLog ? ys.min : 0;
  const y = (value: number) => BAR_T + (1 - (useLog
    ? (Math.log10(value) - Math.log10(ys.min)) / Math.max(1e-9, Math.log10(ys.max) - Math.log10(ys.min))
    : (value - ys.min) / Math.max(1e-9, ys.max - ys.min))) * (BAR_H - BAR_T - BAR_B);
  const slot = (W - BAR_L - BAR_R) / Math.max(1, ordered.length);
  const width = Math.min(58, slot * 0.66);
  const ranked = view.barSort === 'value';
  const label = `${title}: ${yMetric.label} by ${view.xLabel ?? 'observation'}${ranked ? ', ranked' : ''}`;
  return <>
    <svg className="curve-svg interactive-plot wb-plot wb-bar-plot" viewBox={`0 0 ${W} ${BAR_H}`} role="group" aria-label={label} aria-describedby={helpId}>
      <desc id={helpId}>Measured observations only. {ranked ? 'Bars are ordered by value, best first. ' : ''}Tab through bars; Enter or Space selects one.</desc>
      {ys.ticks.map(tick => <g key={`y${tick}`}>
        <line x1={BAR_L} x2={W - BAR_R} y1={y(tick)} y2={y(tick)} className="grid-line" />
        <text x={BAR_L - 10} y={y(tick) + 4} textAnchor="end" className="curve-label">{tick.toLocaleString(undefined, { maximumFractionDigits: yDigits })}</text>
      </g>)}
      {view.threshold && <g>
        <line x1={BAR_L} x2={W - BAR_R} y1={y(view.threshold.value)} y2={y(view.threshold.value)} className="wb-threshold" />
        <text x={W - BAR_R} y={y(view.threshold.value) - 6} textAnchor="end" className="curve-label strong">{view.threshold.label}</text>
      </g>}
      <line x1={BAR_L} x2={W - BAR_R} y1={y(base)} y2={y(base)} className="curve-axis" />
      {ordered.map((point, index) => {
        const value = metricValue(point, yKey)!;
        const cx = BAR_L + slot * (index + 0.5);
        const top = Math.min(y(base), y(value)), height = Math.abs(y(value) - y(base));
        const selected = point.id === selectedId, hovered = point.id === hoveredId, front = frontIds.has(point.id);
        const tone = point.tone ?? (front ? 'green' : 'neutral');
        const colour = colourBySeries ? seriesColor(point.series, seriesNames) : undefined;
        return <g key={point.id} className={`wb-bar ${selected ? 'selected' : ''} ${hovered ? 'hovered' : ''}`}
          role="button" tabIndex={0} aria-label={`Inspect ${point.label}`} aria-pressed={selected}
          onPointerEnter={() => onHover(point.id)} onPointerLeave={() => onHover(null)}
          onFocus={() => onHover(point.id)} onBlur={() => onHover(null)}
          onClick={() => onSelect(point.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(point.id); } }}>
          <title>{`${point.label}: ${yMetric.label} ${formatMetric(yMetric, value)}${point.series ? `; ${point.series}` : ''}${ranked ? `; rank ${index + 1} of ${ordered.length}${yMetric.direction ? ` (${yMetric.direction === 'MIN' ? 'lowest' : 'highest'} first)` : ''}` : ''}`}</title>
          <rect className="wb-bar-target" x={cx - slot / 2} y={BAR_T} width={slot} height={BAR_H - BAR_T - BAR_B} />
          <rect className={`wb-bar-mark tone-${tone}`} x={cx - width / 2} y={top} width={width} height={Math.max(1, height)} rx={2} style={colour ? { fill: colour } : undefined} />
          {(selected || hovered) && <rect className="wb-bar-ring" x={cx - width / 2 - 3} y={top - 3} width={width + 6} height={Math.max(1, height) + 6} rx={4} />}
          <text x={cx} y={BAR_H - BAR_B + 20} textAnchor="middle" className="curve-label">{shortLabel(point.label)}</text>
          {ordered.length <= 14 && <text x={cx} y={value >= base ? top - 6 : top + height + 13} textAnchor="middle" className="curve-label strong">{value.toLocaleString(undefined, { maximumFractionDigits: yMetric.digits ?? 1 })}{yMetric.unit === '%' ? '%' : ''}</text>}
        </g>;
      })}
      <text x={(BAR_L + W - BAR_R) / 2} y={BAR_H - 10} textAnchor="middle" className="curve-axis-title">{view.xLabel ?? 'Observation'}</text>
      <text x={BAR_L} y={22} className="curve-axis-title">{axisTitle(yMetric, 'Value')}{useLog ? ' · log scale' : ''}</text>
    </svg>
    {!colourBySeries && frontIds.size > 0 && frontIds.size < points.length && <div className="wb-series-key" aria-label="Bar colour key">
      <span><i style={{ background: '#246847' }} />Non-dominated across all objectives</span>
      <span><i style={{ background: '#9aabb8' }} />Measured</span>
    </div>}
    {colourBySeries && seriesNames.length > 1 && <div className="wb-series-key" aria-label="Colour key">
      {seriesNames.map(name => <span key={name}><i style={{ background: seriesColor(name, seriesNames) }} />{name}</span>)}
    </div>}
  </>;
}
