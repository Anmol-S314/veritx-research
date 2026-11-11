import { useId, useState } from 'react';
import { chartLogScale, chartScale } from './chartScale';
import { num } from './format';

export type ScatterPoint = { id: string; label: string; x: number; y: number; front: boolean };

/** Shared SVG interaction for repository comparisons and engine-owned studies.
 * Membership is supplied by the caller; this component only plots evidence. */
export function InteractiveScatter({ points, xLabel, yLabel, label, selected, onSelect, className = '', logY = false }: {
  points: ScatterPoint[]; xLabel: string; yLabel: string; label: string;
  selected: string | null; onSelect: (id: string) => void; className?: string; logY?: boolean;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const [includeZero, setIncludeZero] = useState(false);
  const [frontOnly, setFrontOnly] = useState(false);
  const helpId = useId();
  const visible = points.filter(point => !frontOnly || point.front);
  const preview = visible.find(point => point.id === hover) ?? visible.find(point => point.id === selected);
  const xs = chartScale(visible.map(point => point.x), includeZero), ys = chartScale(visible.map(point => point.y), includeZero);
  const useLogY = logY && visible.every(point => point.y > 0);
  const logYs = chartLogScale(visible.map(point => point.y));
  const yTicks = useLogY ? logYs.ticks : ys.ticks;
  const W = 760, H = 350, L = 70, R = 30, T = 48, B = 62;
  const x = (value: number) => L + (value - xs.min) / (xs.max - xs.min) * (W - L - R);
  const y = (value: number) => H - B - (useLogY ? (Math.log10(value) - Math.log10(logYs.min)) / (Math.log10(logYs.max) - Math.log10(logYs.min)) : (value - ys.min) / (ys.max - ys.min)) * (H - T - B);
  return <div className={`interactive-scatter ${className}`}>
    <div className="plot-toolbar">
      <div className="plot-key"><span><i className="plot-key-front" />Non-dominated</span><span><i className="plot-key-other" />Other eligible</span></div>
      <div className="segmented" role="group" aria-label="Plot scale">
        <button type="button" aria-pressed={!includeZero} className={!includeZero ? 'active' : ''} onClick={() => setIncludeZero(false)}>Fit data</button>
        <button type="button" aria-pressed={includeZero} className={includeZero ? 'active' : ''} onClick={() => setIncludeZero(true)}>Include zero</button>
      </div>
      <label className="check-row"><input type="checkbox" checked={frontOnly} onChange={event => setFrontOnly(event.target.checked)} />Front only</label>
    </div>
    <div className="plot-readout" aria-live="polite" aria-atomic="true">
      {preview ? <><strong>{preview.label}</strong><span>{num(preview.x, '', 6)} · {xLabel.split(' · ')[0]}</span><span>{num(preview.y, '', 6)} · {yLabel.split(' · ')[0]}</span></> : <span>No point selected.</span>}
    </div>
    <svg className="curve-svg interactive-plot" viewBox={`0 0 ${W} ${H}`} role="group" aria-label={label} aria-describedby={helpId}>
      <desc id={helpId}>Interactive plot. Tab through candidates; Enter or Space selects one. Tab through every point, including overlapping observations.</desc>
      {yTicks.map(tick => <g key={`y${tick}`}><line x1={L} x2={W - R} y1={y(tick)} y2={y(tick)} className="grid-line" /><text x={L - 10} y={y(tick) + 4} textAnchor="end" className="curve-label">{num(tick, '', useLogY ? 3 : ys.digits)}</text></g>)}
      {xs.ticks.map(tick => <g key={`x${tick}`}><line x1={x(tick)} x2={x(tick)} y1={T} y2={H - B} className="grid-line" /><text x={x(tick)} y={H - B + 20} textAnchor="middle" className="curve-label">{num(tick, '', xs.digits)}</text></g>)}
      <line x1={L} x2={W - R} y1={H - B} y2={H - B} className="curve-axis" />
      <line x1={L} x2={L} y1={T} y2={H - B} className="curve-axis" />
      {preview && <g aria-hidden="true" className="plot-crosshair"><line x1={L} x2={W - R} y1={y(preview.y)} y2={y(preview.y)} /><line x1={x(preview.x)} x2={x(preview.x)} y1={T} y2={H - B} /></g>}
      {visible.map(point => {
        const active = point.id === preview?.id;
        return <g key={point.id} className={`plot-point ${point.front ? 'front' : ''} ${active ? 'active' : ''}`} role="button" tabIndex={0}
          aria-label={`Inspect ${point.label}`} aria-pressed={point.id === selected}
          onPointerEnter={() => setHover(point.id)} onPointerLeave={() => setHover(null)}
          onFocus={() => setHover(point.id)} onBlur={() => setHover(null)}
          onClick={() => onSelect(point.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(point.id); } }}>
          <title>{`${point.label}: ${xLabel} ${point.x}; ${yLabel} ${point.y}; ${point.front ? 'non-dominated' : 'dominated'}`}</title>
          <circle className="point-target" cx={x(point.x)} cy={y(point.y)} r={13} />
          {active && <circle className="point-ring" cx={x(point.x)} cy={y(point.y)} r={11} />}
          <circle className="point-mark" cx={x(point.x)} cy={y(point.y)} r={active ? 6 : point.front ? 5.5 : 4.5} />
        </g>;
      })}
      {preview && <text x={Math.min(W - R - 4, Math.max(L + 4, x(preview.x)))} y={Math.max(T + 13, y(preview.y) - 17)} textAnchor={x(preview.x) > W / 2 ? 'end' : 'start'} className="curve-label strong point-label" pointerEvents="none">{preview.label}</text>}
      <text x={W / 2} y={H - 13} textAnchor="middle" className="curve-axis-title">{xLabel}</text>
      <text x={L} y={24} className="curve-axis-title">{yLabel}{useLogY ? ' · log scale' : ''}</text>
    </svg>
    <p className="plot-hint">{visible.length} of {points.length} eligible points shown · actual observations, no interpolation. {useLogY && 'Vertical axis is logarithmic; Include zero applies to the horizontal axis.'}</p>
  </div>;
}
