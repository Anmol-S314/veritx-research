import { useState } from 'react';
import type { AddressWindow } from './agentMap';
import { formatBytes, formatHex } from './agentMap';
import type { AgentGroup } from './agentMap';

const LOW_END = 1n << 32n;
const W = 900;
const LEFT = 190;
const RIGHT = 880;
const TOP = 42;
const ROW = 32;
const BAR_H = 16;

type Window = { id: string; label: string; start: bigint; end: bigint };

/** Windows come from the live request's BigInt address ranges. The view is
 *  linear inside one selected window; no region is invented or rescaled. */
export function LiveAddressMap({ windows, agents, selected, onSelect }: {
  windows: AddressWindow[];
  agents: AgentGroup[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const ends = windows.map(window => window.base + window.size);
  const lowWindows = windows.filter(window => window.base < LOW_END && window.base + window.size > 0n);
  const highWindows = windows.filter(window => window.base + window.size > LOW_END);
  const options: Window[] = [];
  if (lowWindows.length) options.push({ id: 'low', label: 'Low 4 GiB', start: 0n, end: LOW_END });
  if (highWindows.length) {
    const start = highWindows.reduce((min, window) => window.base < min ? window.base : min, highWindows[0].base);
    const end = highWindows.reduce((max, window) => window.base + window.size > max ? window.base + window.size : max, highWindows[0].base + highWindows[0].size);
    options.push({ id: 'high', label: 'High declared', start, end: end > start ? end : start + 1n });
  }
  if (windows.length && options.length > 1) {
    const start = windows.reduce((min, window) => window.base < min ? window.base : min, windows[0].base);
    const end = ends.reduce((max, value) => value > max ? value : max, ends[0]);
    options.push({ id: 'full', label: 'Full declared range', start, end: end > start ? end : start + 1n });
  }
  const fallback = options[0] ?? { id: 'empty', label: 'No windows', start: 0n, end: 1n };
  const [windowId, setWindowId] = useState(fallback.id);
  const active = options.find(entry => entry.id === windowId) ?? fallback;
  const span = active.end > active.start ? active.end - active.start : 1n;
  const ratio = (value: bigint) => {
    if (value <= active.start) return 0;
    if (value >= active.end) return 1;
    return Number(((value - active.start) * 100000n) / span) / 100000;
  };
  const x = (value: bigint) => LEFT + ratio(value) * (RIGHT - LEFT);
  const intersect = (window: AddressWindow) => window.base < active.end && window.base + window.size > active.start;
  const visible = [...windows].filter(intersect).sort((a, b) => a.base < b.base ? -1 : a.base > b.base ? 1 : 0);
  const outside = windows.length - visible.length;
  const conflicts: { a: string; b: string; start: bigint; size: bigint }[] = [];
  for (let i = 0; i < windows.length; i += 1) {
    for (let j = i + 1; j < windows.length; j += 1) {
      const a = windows[i], b = windows[j];
      const start = a.base > b.base ? a.base : b.base;
      const end = a.base + a.size < b.base + b.size ? a.base + a.size : b.base + b.size;
      if (start < end && start < active.end && end > active.start) conflicts.push({ a: a.id, b: b.id, start, size: end - start });
    }
  }
  const conflicted = new Set(conflicts.flatMap(conflict => [conflict.a, conflict.b]));
  const height = TOP + Math.max(1, visible.length) * ROW + 24;
  const ticks = [0n, 1n, 2n, 3n, 4n].map(index => active.start + span * index / 4n);

  return <div className="address-map">
    <div className="incidence-head">
      <div className="segmented" role="group" aria-label="Address window">
        {options.map(option => <button key={option.id} className={option.id === active.id ? 'active' : ''} aria-pressed={option.id === active.id} onClick={() => setWindowId(option.id)}>{option.label}</button>)}
      </div>
      <span className="mono muted">{formatHex(active.start)} – {formatHex(active.end)}</span>
    </div>
    <div className="address-map-scroll">
      <svg className="address-map-canvas" viewBox={`0 0 ${W} ${height}`} role="group" aria-label={`Declared address windows in the ${active.label} view; select a window to inspect it`}>
        <text className="address-axis-label" x={8} y={16}>Window offset</text>
        {ticks.map(value => <g key={value.toString()}>
          <line className="address-grid" x1={x(value)} y1={TOP - 8} x2={x(value)} y2={height - 16} />
          <text className="address-tick" x={x(value)} y={16} textAnchor="middle">{formatBytes(value - active.start)}</text>
        </g>)}
        {visible.map((window, index) => {
          const y = TOP + index * ROW;
          const start = window.base > active.start ? window.base : active.start;
          const end = window.base + window.size < active.end ? window.base + window.size : active.end;
          const x1 = x(start);
          const width = Math.max(3, x(end) - x1);
          const conflict = conflicted.has(window.id);
          const target = agents[window.targetAgentIdx]?.kind ?? `agent ${window.targetAgentIdx}`;
          return <g key={window.id} className={`address-row${window.id === selected ? ' selected' : ''}${conflict ? ' conflict' : ''}`}
            role="button" tabIndex={0} aria-label={`Window ${window.name || 'unnamed'}, ${formatHex(window.base)}, ${formatBytes(window.size)}`}
            onClick={() => onSelect(window.id)}
            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(window.id); } }}>
            <title>{`${window.name || 'unnamed'} · base ${formatHex(window.base)} · ${formatBytes(window.size)} · ${target}`}</title>
            <rect className="address-lane" x={LEFT} y={y} width={RIGHT - LEFT} height={ROW - 4} />
            <text className="address-name" x={8} y={y + 12}>{window.name || 'unnamed'}</text>
            <text className="address-meta" x={8} y={y + 25}>{formatBytes(window.size)} · {formatHex(window.base)}</text>
            <rect className="address-bar" x={x1} y={y + 6} width={width} height={BAR_H} rx={2} />
            {window.id === selected && <rect className="address-selected" x={x1 - 1.5} y={y + 4.5} width={width + 3} height={BAR_H + 3} rx={3} />}
          </g>;
        })}
        {conflicts.map(conflict => {
          const x1 = x(conflict.start > active.start ? conflict.start : active.start);
          const x2 = x(conflict.start + conflict.size < active.end ? conflict.start + conflict.size : active.end);
          return <g key={`${conflict.a}:${conflict.b}`} className="address-conflict">
            <rect x={x1} y={TOP - 4} width={Math.max(2, x2 - x1)} height={height - TOP - 12} />
            <text x={(x1 + x2) / 2} y={height - 5} textAnchor="middle">{formatBytes(conflict.size)} overlap</text>
          </g>;
        })}
      </svg>
    </div>
    <div className="legend">
      <span><i className="legend-dot blue" />Declared window</span>
      <span><i className="legend-dot red" />Window in an overlap</span>
      <span><i className="legend-dot amber" />Selected window outline</span>
      <span>{conflicts.length} overlap{conflicts.length === 1 ? '' : 's'} in this view{outside > 0 ? ` · ${outside} window${outside === 1 ? '' : 's'} outside this view` : ''}</span>
    </div>
  </div>;
}
