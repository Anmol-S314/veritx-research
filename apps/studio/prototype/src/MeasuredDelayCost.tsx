import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Badge, Empty, Notice, Section } from './ui';
import type { LoadedRun } from './project';
import type { Topology } from './gateway';
import { useSimLoad } from './measuredData';
import { channelCosts, median, type ChannelCost } from './channelAnalysis';
import { buildChannelIndex, matchMeasuredChannel } from './channelTopology';
import { portWiresUsable, usePortWires } from './portWires';
import { revealChannelDetail, useChannelSelection } from './channelSelection';
import { contextTarget } from './contextSelection';

const cyc = (value: number | null | undefined, digits = 2) => value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(digits)} cyc`;

type Costed = ChannelCost & { queuePerFlit: number };

type DelayDomain = { xMin: number; xMax: number; yMin: number; yMax: number };

function DelayScatter({ costs, totalChannels, medianCost, medianFlits, shortLink, selectedId, onPick }: {
  costs: Costed[]; totalChannels: number; medianCost: number | null; medianFlits: number | null; shortLink: (id: number) => string;
  selectedId: number | null; onPick: (id: number) => void;
}) {
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ x: number; y: number; domain: DelayDomain; moved: boolean } | null>(null);
  const suppressClickRef = useRef(false);
  const width = 920, height = 360, left = 66, right = 26, top = 30, bottom = 58;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const maxFlits = Math.max(1, ...costs.map(cost => cost.channel.flits_total));
  const maxCost = Math.max(0, ...costs.map(cost => cost.queuePerFlit));
  const yStep = maxCost > 12 ? 5 : maxCost > 5 ? 2 : 1;
  const niceMax = Math.max(yStep, Math.ceil(maxCost / yStep) * yStep);
  const baseDomain = useMemo<DelayDomain>(() => ({
    xMin: 0,
    xMax: maxFlits + Math.max(1, maxFlits * 0.08),
    yMin: 0,
    yMax: niceMax + Math.max(0.1, niceMax * 0.08),
  }), [maxFlits, niceMax]);
  const [domain, setDomain] = useState<DelayDomain>(baseDomain);
  const clipId = `delay-clip-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  useEffect(() => { setDomain(baseDomain); }, [baseDomain]);

  const isZoomed = domain.xMin > 1e-6 || domain.xMax < baseDomain.xMax - 1e-6 || domain.yMin > 1e-6 || domain.yMax < baseDomain.yMax - 1e-6;
  const uMin = Math.sqrt(domain.xMin), uMax = Math.sqrt(domain.xMax);
  const xOf = (flits: number) => left + ((Math.sqrt(Math.max(0, flits)) - uMin) / Math.max(1e-6, uMax - uMin)) * plotWidth;
  const yOf = (cost: number) => top + plotHeight - ((cost - domain.yMin) / Math.max(1e-6, domain.yMax - domain.yMin)) * plotHeight;
  const visibleCosts = costs.filter(cost => cost.channel.flits_total >= domain.xMin && cost.channel.flits_total <= domain.xMax && cost.queuePerFlit >= domain.yMin && cost.queuePerFlit <= domain.yMax);
  const pointPositions = (() => {
    const groups = new Map<string, Costed[]>();
    for (const cost of visibleCosts) {
      const key = `${cost.channel.flits_total}:${cost.queuePerFlit.toFixed(4)}`;
      const group = groups.get(key);
      if (group) group.push(cost);
      else groups.set(key, [cost]);
    }
    const positions = new Map<number, { x: number; y: number }>();
    for (const group of groups.values()) {
      group.forEach((cost, index) => {
        const x = xOf(cost.channel.flits_total), y = yOf(cost.queuePerFlit);
        if (index === 0) positions.set(cost.id, { x, y });
        else if (group.length === 2) positions.set(cost.id, { x, y: y + 15 });
        else {
          const angle = (2 * Math.PI * index) / group.length + Math.PI / 4;
          positions.set(cost.id, { x: x + Math.cos(angle) * 14, y: y + Math.sin(angle) * 14 });
        }
      });
    }
    return positions;
  })();
  const posOf = (cost: Costed) => pointPositions.get(cost.id) ?? { x: xOf(cost.channel.flits_total), y: yOf(cost.queuePerFlit) };
  const hovered = hoveredId === null ? null : visibleCosts.find(cost => cost.id === hoveredId) ?? null;
  const omitted = Math.max(0, totalChannels - costs.length);
  const topCost = [...costs].sort((a, b) => b.queuePerFlit - a.queuePerFlit).slice(0, 5);
  const busiest = [...costs].sort((a, b) => b.channel.flits_total - a.channel.flits_total).slice(0, 3);
  const costIds = new Set(topCost.map(cost => cost.id));
  const busiestIds = new Set(busiest.map(cost => cost.id));
  const labelledCost = topCost.filter(cost => visibleCosts.some(visible => visible.id === cost.id)).slice(0, 2);
  const samePoint = (a: Costed, b: Costed) => Math.abs(a.channel.flits_total - b.channel.flits_total) < Math.max(1, maxFlits * 0.02)
    && Math.abs(a.queuePerFlit - b.queuePerFlit) < Math.max(0.05, niceMax * 0.02);
  const labelPoints = labelledCost.filter((cost, index) => !labelledCost.slice(0, index).some(previous => samePoint(previous, cost)));
  const busiestOne = busiest.find(cost => visibleCosts.some(visible => visible.id === cost.id)
    && !labelPoints.some(label => label.id === cost.id)
    && !labelledCost.some(label => label.id === cost.id));
  const pointLabel = (cost: Costed, index: number) => {
    const point = posOf(cost);
    const nearRight = point.x > width - right - 90;
    return {
      x: nearRight ? point.x - 12 : point.x + 12,
      y: Math.min(top + plotHeight - 4, Math.max(top + 10, point.y + (index === 0 ? -6 : 12))),
      anchor: nearRight ? 'end' as const : 'start' as const,
    };
  };
  const xTicks = [...new Set([
    0, 100, 500, 1000, 2000, 5000, 10000, maxFlits,
    domain.xMin,
    ...(isZoomed ? [domain.xMax] : []),
  ].filter(value => value >= domain.xMin && value <= domain.xMax))].sort((a, b) => a - b);
  const yTicks = [...new Set([
    ...Array.from({ length: Math.round(niceMax / yStep) + 1 }, (_, index) => index * yStep),
    domain.yMin, domain.yMax,
  ].filter(value => value >= domain.yMin && value <= domain.yMax))].sort((a, b) => a - b);
  const tickText = (value: number) => Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);

  const zoomAt = (px: number, py: number, factor: number) => {
    if (px < left || px > width - right || py < top || py > top + plotHeight) return;
    setDomain(current => {
      const currentUMin = Math.sqrt(current.xMin), currentUMax = Math.sqrt(current.xMax);
      const uAt = currentUMin + ((px - left) / plotWidth) * (currentUMax - currentUMin);
      const yAt = current.yMax - ((py - top) / plotHeight) * (current.yMax - current.yMin);
      const uMinNew = Math.max(0, uAt - (uAt - currentUMin) * factor);
      const uMaxNew = uAt + (currentUMax - uAt) * factor;
      let xMin = uMinNew * uMinNew, xMax = uMaxNew * uMaxNew;
      let yMin = yAt - (yAt - current.yMin) * factor;
      let yMax = yAt + (current.yMax - yAt) * factor;
      xMin = Math.max(0, Math.min(xMin, baseDomain.xMax));
      xMax = Math.min(baseDomain.xMax, Math.max(xMax, xMin + Math.max(1, maxFlits * 0.01)));
      yMin = Math.max(0, Math.min(yMin, baseDomain.yMax));
      yMax = Math.min(baseDomain.yMax, Math.max(yMax, yMin + 0.1));
      return { xMin, xMax, yMin, yMax };
    });
  };
  const zoomOut = () => zoomAt(left + plotWidth / 2, top + plotHeight / 2, 1.3);
  const zoomIn = () => {
    const focus = costs.find(cost => cost.id === selectedId) ?? topCost[0] ?? costs[0];
    if (focus) {
      const px = xOf(focus.channel.flits_total), py = yOf(focus.queuePerFlit);
      if (px >= left && px <= width - right && py >= top && py <= top + plotHeight) {
        zoomAt(px, py, 0.77);
        return;
      }
    }
    zoomAt(left + plotWidth / 2, top + plotHeight / 2, 0.77);
  };
  const fitData = () => {
    const xs = costs.map(cost => cost.channel.flits_total);
    const ys = costs.map(cost => cost.queuePerFlit);
    const xMinRaw = Math.min(...xs), xMaxRaw = Math.max(...xs);
    const yMinRaw = Math.min(...ys), yMaxRaw = Math.max(...ys);
    const xPad = Math.max(1, (xMaxRaw - xMinRaw) * 0.08);
    const yPad = Math.max(0.1, (yMaxRaw - yMinRaw) * 0.12);
    setDomain({
      xMin: Math.max(0, xMinRaw - xPad),
      xMax: Math.min(baseDomain.xMax, Math.max(xMinRaw + 1, xMaxRaw + xPad)),
      yMin: Math.max(0, yMinRaw - yPad),
      yMax: Math.min(baseDomain.yMax, Math.max(yMinRaw + 0.1, yMaxRaw + yPad)),
    });
  };
  const resetZoom = () => setDomain(baseDomain);
  const zoomRef = useRef(zoomAt);
  zoomRef.current = zoomAt;

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY === 0) return;
      const rect = svg.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const px = (event.clientX - rect.left) * (width / rect.width);
      const py = (event.clientY - rect.top) * (height / rect.height);
      event.preventDefault();
      zoomRef.current(px, py, Math.min(2, Math.max(0.5, Math.exp(event.deltaY * 0.0015))));
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [width, height]);

  const pointer = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { px: (event.clientX - rect.left) * (width / rect.width), py: (event.clientY - rect.top) * (height / rect.height) };
  };
  const startPan = (event: React.PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    const { px, py } = pointer(event);
    if (px < left || px > width - right || py < top || py > top + plotHeight) return;
    dragRef.current = { x: event.clientX, y: event.clientY, domain, moved: false };
  };
  const movePan = (event: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const dx = (event.clientX - drag.x) * (width / rect.width);
    const dy = (event.clientY - drag.y) * (height / rect.height);
    if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
    if (!drag.moved) {
      drag.moved = true;
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragging(true);
    }
    const uSpan = Math.sqrt(drag.domain.xMax) - Math.sqrt(drag.domain.xMin);
    const ySpan = drag.domain.yMax - drag.domain.yMin;
    let uMinNew = Math.sqrt(drag.domain.xMin) - (dx / plotWidth) * uSpan;
    let uMaxNew = Math.sqrt(drag.domain.xMax) - (dx / plotWidth) * uSpan;
    if (uMinNew < 0) { uMaxNew -= uMinNew; uMinNew = 0; }
    const uLimit = Math.sqrt(maxFlits);
    if (uMaxNew > uLimit) { uMinNew -= uMaxNew - uLimit; uMaxNew = uLimit; }
    let yMinNew = drag.domain.yMin + (dy / plotHeight) * ySpan;
    let yMaxNew = drag.domain.yMax + (dy / plotHeight) * ySpan;
    if (yMinNew < 0) { yMaxNew -= yMinNew; yMinNew = 0; }
    if (yMaxNew > niceMax) { yMinNew -= yMaxNew - niceMax; yMaxNew = niceMax; }
    setDomain({ xMin: uMinNew * uMinNew, xMax: uMaxNew * uMaxNew, yMin: Math.max(0, yMinNew), yMax: Math.min(niceMax, yMaxNew) });
  };
  const endPan = (event: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.moved) {
      suppressClickRef.current = true;
      window.setTimeout(() => { suppressClickRef.current = false; }, 0);
    }
    dragRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const pick = (id: number) => { if (!suppressClickRef.current) onPick(id); };

  return <figure className={`delay-scatter${dragging ? ' dragging' : ''}`}>
    <div className="load-histogram-head">
      <h3>Queue cycles per delivered flit</h3>
      <div className="load-histogram-key"><span><i className="delay-key all" />All channels</span><span><i className="delay-key cost" />Top 5 cost</span><span><i className="delay-key flit" />Top 3 busiest</span></div>
    </div>
    <div className="delay-readout" data-testid="delay-readout">
      {hovered
        ? <>
          <strong className="mono">CH-{hovered.id}</strong>
          <span>{shortLink(hovered.id)}</span>
          <span>{hovered.channel.flits_total.toLocaleString()} flits</span>
          <strong className="mono">{hovered.queuePerFlit.toFixed(2)} cyc/flit</strong>
          <span>{hovered.tailRatio === null ? 'no latency tail' : `${hovered.tailRatio.toFixed(1)}× peak ÷ mean tail`}</span>
          <span>{(hovered.channel.queue_cycles_total ?? 0).toLocaleString()} queue cycles</span>
        </>
        : <span>Scroll over the plot to zoom, drag to pan, and click a dot to open that channel. Rings mark the five costliest and three busiest channels; dashed guides mark the fabric medians.</span>}
    </div>
    <div className="delay-zoom-tools">
      <span>Scroll to zoom · drag to pan{isZoomed ? ` · view ${tickText(domain.xMin)}–${tickText(domain.xMax)} flits, ${domain.yMin.toFixed(2)}–${domain.yMax.toFixed(2)} cyc/flit` : ''}</span>
      <span className="delay-zoom-actions">
        <button type="button" className="text-button" onClick={fitData}>Fit data</button>
        <button type="button" className="text-button" onClick={zoomOut} aria-label="Zoom out">−</button>
        <button type="button" className="text-button" onClick={zoomIn} aria-label="Zoom in">+</button>
        <button type="button" className="text-button" onClick={resetZoom} disabled={!isZoomed}>Reset</button>
      </span>
    </div>
    <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Scatter of queue cycles per delivered flit against delivered flits, one point per active measured channel"
      onPointerDown={startPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan}>
      <defs><clipPath id={clipId}><rect x={left} y={top} width={plotWidth} height={plotHeight} /></clipPath></defs>
      {yTicks.map(value => <g key={value}>
        <line x1={left} x2={width - right} y1={yOf(value)} y2={yOf(value)} className="chart-grid" />
        <text x={left - 7} y={yOf(value) + 3} textAnchor="end" className="chart-tick">{tickText(value)}</text>
      </g>)}
      {xTicks.map((value, index) => <text key={value} x={xOf(value)} y={height - 24} textAnchor={index === 0 ? 'start' : index === xTicks.length - 1 ? 'end' : 'middle'} className="chart-tick">{tickText(value)}</text>)}
      <g clipPath={`url(#${clipId})`}>
        {medianCost !== null && medianCost >= domain.yMin && medianCost <= domain.yMax && <>
          <line x1={left} x2={width - right} y1={yOf(medianCost)} y2={yOf(medianCost)} className="delay-median" />
          <text x={width - right - 2} y={yOf(medianCost) - 4} textAnchor="end" className="delay-median-label">median cost {medianCost.toFixed(2)}</text>
        </>}
        {medianFlits !== null && medianFlits >= domain.xMin && medianFlits <= domain.xMax && <>
          <line x1={xOf(medianFlits)} x2={xOf(medianFlits)} y1={top} y2={top + plotHeight} className="delay-median-x" />
          {!isZoomed && <text x={xOf(medianFlits) - 4} y={top + plotHeight - 6} textAnchor="end" className="delay-median-label">median volume {medianFlits.toLocaleString()}</text>}
        </>}
        {hovered && <>
          <line x1={left} x2={posOf(hovered).x} y1={posOf(hovered).y} y2={posOf(hovered).y} className="delay-crosshair" />
          <line x1={posOf(hovered).x} x2={posOf(hovered).x} y1={posOf(hovered).y} y2={top + plotHeight} className="delay-crosshair" />
        </>}
        {visibleCosts.map(cost => {
          const { x, y } = posOf(cost);
          const isHovered = cost.id === hoveredId;
          const isSelected = cost.id === selectedId;
          return <g key={cost.id} role="button" tabIndex={0} aria-pressed={isSelected}
            aria-label={`Select channel ${cost.id}, ${cost.queuePerFlit.toFixed(2)} queue cycles per flit`}
            {...contextTarget('channel', cost.id, `Measured channel CH-${cost.id}`, `${cost.channel.flits_total.toLocaleString()} flits · ${cost.queuePerFlit.toFixed(2)} queue cycles/flit · ${shortLink(cost.id)}`)}
            className="delay-point"
            onClick={() => pick(cost.id)}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); pick(cost.id); } }}
            onMouseEnter={() => setHoveredId(cost.id)} onMouseLeave={() => setHoveredId(null)}>
            <circle cx={x} cy={y} r={isHovered || isSelected ? 7 : 5.5} className={`delay-dot${isHovered || isSelected ? ' hovered' : ''}`} />
            {costIds.has(cost.id) && <circle cx={x} cy={y} r={9.5} className="delay-ring cost" />}
            {busiestIds.has(cost.id) && <circle cx={x} cy={y} r={9.5} className="delay-ring flit" />}
            {isSelected && <circle cx={x} cy={y} r={13} className="delay-ring picked" />}
            {isHovered && <circle cx={x} cy={y} r={12} className="delay-ring hovered" />}
            <circle cx={x} cy={y} r={16} className="delay-hit" />
            <title>{`CH-${cost.id} · ${shortLink(cost.id)} · ${cost.channel.flits_total.toLocaleString()} flits · ${cost.queuePerFlit.toFixed(2)} cyc/flit${cost.tailRatio === null ? '' : ` · ${cost.tailRatio.toFixed(1)}× tail`}`}</title>
          </g>;
        })}
        {labelPoints.map((cost, index) => {
          const label = pointLabel(cost, index);
          return <text key={cost.id} x={label.x} y={label.y} textAnchor={label.anchor} className="delay-label">CH-{cost.id} · {cost.queuePerFlit.toFixed(1)}</text>;
        })}
        {busiestOne && (() => {
          const label = pointLabel(busiestOne, 1);
          return <text x={label.x} y={label.y} textAnchor={label.anchor} className="delay-label">CH-{busiestOne.id} · {busiestOne.channel.flits_total.toLocaleString()} flits</text>;
        })()}
      </g>
      <text x={left} y={14} className="chart-axis-title">cyc / flit</text>
      <text x={left + plotWidth / 2} y={height - 4} textAnchor="middle" className="chart-axis-title">Delivered flits (square-root scale)</text>
    </svg>
    <figcaption className="meta-line">One dot per source-port channel with queue counters and at least one delivered flit.{omitted > 0 ? ` ${omitted.toLocaleString()} channel${omitted === 1 ? '' : 's'} without a delivered flit or queue counter are not plotted.` : ''} Vertical axis: measured queue cycles ÷ delivered flits; dashed line: fabric median.</figcaption>
  </figure>;
}

export function MeasuredDelayCost({ run, topology }: { run: LoadedRun; topology: Topology | null }) {
  const state = useSimLoad(run.detail.run_id);
  // Selecting a point here drives the measured-channel detail panel below.
  const [selectedChannel, selectChannel] = useChannelSelection(run.detail.run_id);
  const selectedId = selectedChannel && Number.isFinite(Number(selectedChannel)) ? Number(selectedChannel) : null;
  const pickChannel = (id: number) => { selectChannel(String(id)); revealChannelDetail(); };
  const channels = state.data?.channels ?? [];
  const costs = useMemo(() => channelCosts(channels), [channels]);
  const withCost = useMemo(() => costs.filter((cost): cost is Costed => cost.queuePerFlit !== null), [costs]);
  const wires = usePortWires(run, topology);
  const index = useMemo(() => buildChannelIndex(topology, portWiresUsable(wires.map) ? wires.map.ports : undefined), [topology, wires.map]);
  const shortLink = (id: number) => {
    const match = matchMeasuredChannel(index, id);
    return match?.local ? 'eject' : match?.wire ? `wire ${match.wire.id}` : match?.channel ? `R${match.measured.router}→R${match.channel.dst_router}` : 'no link';
  };
  const medianCost = median(withCost.map(cost => cost.queuePerFlit));
  const medianFlits = median(withCost.map(cost => cost.channel.flits_total));
  const rankedCost = [...withCost].sort((a, b) => b.queuePerFlit - a.queuePerFlit);
  const worstCost = rankedCost[0];
  const tail10 = costs.filter(cost => (cost.tailRatio ?? 0) >= 10).length;
  const widestTail = [...costs].filter(cost => (cost.tailRatio ?? 0) > 0).sort((a, b) => (b.tailRatio ?? 0) - (a.tailRatio ?? 0))[0];
  const busiest = [...withCost].sort((a, b) => b.channel.flits_total - a.channel.flits_total)[0];
  const bandSize = Math.min(10, rankedCost.length, withCost.length);
  const bandLabel = bandSize === 10 ? 'ten' : String(bandSize);
  const costTen = new Set(rankedCost.slice(0, bandSize).map(cost => cost.id));
  const busiestTen = new Set([...withCost].sort((a, b) => b.channel.flits_total - a.channel.flits_total).slice(0, bandSize).map(cost => cost.id));
  const overlap = [...costTen].filter(id => busiestTen.has(id)).length;
  const topCost = rankedCost.slice(0, 6);
  const maxTopCost = topCost[0]?.queuePerFlit ?? 1;
  const reading = (() => {
    if (!worstCost || medianCost === null) return 'No channel has a measured queue counter and a delivered flit.';
    const ratio = medianCost > 0 ? worstCost.queuePerFlit / medianCost : null;
    const worst = `The costliest channel is CH-${worstCost.id}: ${cyc(worstCost.queuePerFlit)} per delivered flit${ratio === null ? '' : `, ${ratio.toFixed(1)}× the fabric median of ${cyc(medianCost)}`}.`;
    const overlapText = busiest?.id === worstCost.id
      ? 'It is also the busiest channel, so cost and volume overlap; inspect it first.'
      : overlap === 0
        ? `It is not among the ${bandLabel} busiest, so high per-flit cost on a low-volume port is not a congestion verdict by itself.`
        : overlap >= Math.ceil(bandSize / 2)
          ? `It is also among the ${bandLabel} busiest, so cost and volume overlap; inspect that channel first.`
          : `Only ${overlap} of the ${bandLabel} costliest are also among the ${bandLabel} busiest, so cost and volume mostly separate.`;
    const tailText = tail10 > 0
      ? ` ${tail10} channel${tail10 === 1 ? '' : 's'} exceed a 10× peak-to-mean latency tail.`
      : ' No channel exceeds a 10× peak-to-mean latency tail.';
    return `${worst} ${overlapText}${tailText}`;
  })();

  return <Section id="measured-delay-cost" title="Measured delay cost per channel" actions={<Badge tone={state.phase === 'ready' ? 'green' : 'amber'}>{state.phase === 'ready' ? `${withCost.length} costed` : 'Not recorded'}</Badge>}>
    {state.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading queue and latency counters…</p>}
    {state.phase === 'absent' && <p className="meta-line">This run carries no sampled queue counters, so no delay cost is derived.</p>}
    {state.phase === 'error' && <Notice tone="red">{state.reason}</Notice>}
    {state.phase === 'ready' && (!withCost.length
      ? <Empty title="No queue split in this series">Queue cycles per delivered flit cannot be derived without a measured queue counter. The run is left as it is.</Empty>
      : <>
        <div className="stat-strip">
          <div className="stat" {...contextTarget('metric', 'median-queue-cost', 'Median queue cost', `${medianCost === null ? 'not measured' : `${medianCost.toFixed(2)} queue cycles per delivered flit`} across ${withCost.length} costed channels`)}><span>Median queue cost</span><strong>{medianCost === null ? '—' : `${medianCost.toFixed(2)} cyc`}</strong><small>per delivered flit · {withCost.length} channels</small></div>
          <div className="stat"><span>Costliest channel</span><strong>CH-{worstCost?.id ?? '—'}</strong><small>{worstCost ? `${cyc(worstCost.queuePerFlit)} · ${worstCost.channel.flits_total.toLocaleString()} flits` : 'No costed channel'}</small></div>
          <div className="stat"><span>Widest latency tail</span><strong>{widestTail ? `CH-${widestTail.id}` : '—'}</strong><small>{widestTail?.tailRatio ? `${widestTail.tailRatio.toFixed(1)}× mean · peak ${widestTail.channel.peak_per_hop_latency_cycles ?? '—'} cyc` : 'No measured tail'}</small></div>
          <div className="stat"><span>Channels ≥ 10× tail</span><strong>{tail10}</strong><small>of {channels.length} active channels</small></div>
        </div>
        <p className="window-reading" data-testid="delay-reading"><strong>What this shows:</strong> {reading}</p>
        <div className="delay-layout">
          <DelayScatter costs={withCost} totalChannels={channels.length} medianCost={medianCost} medianFlits={medianFlits} shortLink={shortLink} selectedId={selectedId} onPick={pickChannel} />
          <aside className="delay-list">
            <h3>Most queue cycles per flit</h3>
            {topCost.map(cost => <button type="button" className={`delay-row${cost.id === selectedId ? ' selected' : ''}`} key={cost.id}
              aria-pressed={cost.id === selectedId}
              {...contextTarget('channel', cost.id, `Measured channel CH-${cost.id}`, `${cost.channel.flits_total.toLocaleString()} flits · ${cost.queuePerFlit.toFixed(2)} queue cycles/flit · ${shortLink(cost.id)}`)}
              onClick={() => pickChannel(cost.id)}>
              <span className="mono">CH-{cost.id}</span>
              <span className="delay-row-main">
                <span className="delay-track"><i style={{ width: `${100 * cost.queuePerFlit / maxTopCost}%` }} /></span>
                <small>{shortLink(cost.id)} · {cost.tailRatio === null ? 'no tail' : `${cost.tailRatio.toFixed(1)}× tail`}</small>
              </span>
              <span className="delay-row-value">{cost.queuePerFlit.toFixed(2)}<small>cyc/flit</small></span>
            </button>)}
          </aside>
        </div>
      </>)}
  </Section>;
}
