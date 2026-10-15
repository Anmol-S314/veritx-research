/** Virtualized measured traffic matrix (tracker M3-16).
 *
 *  Renders only the cells inside the scroll viewport (plus a small overscan),
 *  so a large initiator×target matrix — 10k cells and up — draws a bounded
 *  number of elements. The SVG is full-size; the container scrolls it. Cell
 *  fill is measured packets, never a permission; the diagonal is self-traffic.
 */
import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { matrixWindow, windowCellCount } from '../../graph/matrixWindow';

export interface MeasuredMatrixSelection { src: number; dst: number }

const FALLBACK = { width: 560, height: 320 };

export function MeasuredMatrix({ matrix, selected, onSelect }: {
  matrix: number[][];
  selected?: MeasuredMatrixSelection | null;
  onSelect?: (src: number, dst: number) => void;
}): ReactElement {
  const nodes = matrix.length;
  const CELL = 26;
  const PAD = 34;
  const ref = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState({ left: 0, top: 0 });
  const [viewport, setViewport] = useState(FALLBACK);

  const measure = (): void => {
    const el = ref.current;
    setViewport({
      width: (el?.clientWidth || 0) > 0 ? el!.clientWidth : FALLBACK.width,
      height: (el?.clientHeight || 0) > 0 ? el!.clientHeight : FALLBACK.height,
    });
  };
  useEffect(measure, []);

  const max = useMemo(() => Math.max(1, ...matrix.flat(), 1), [matrix]);
  const shade = (value: number): string => (value <= 0 ? 'transparent'
    : `color-mix(in srgb, var(--info) ${Math.round(14 + 86 * Math.min(1, value / max))}%, transparent)`);

  const totalW = PAD + nodes * CELL + 8;
  const totalH = PAD + nodes * CELL + 22;
  const win = matrixWindow(nodes, nodes, CELL, scroll, viewport, 3);
  const rows = Array.from({ length: win.rows.end - win.rows.start }, (_, k) => win.rows.start + k);
  const cols = Array.from({ length: win.cols.end - win.cols.start }, (_, k) => win.cols.start + k);

  return (
    <div>
      <div
        ref={ref}
        data-testid="measured-matrix-scroll"
        className="loom-matrix-scroll"
        style={{ overflow: 'auto', maxHeight: 360, border: '1px solid var(--border)', borderRadius: 6 }}
        onScroll={(e) => {
          setScroll({ left: e.currentTarget.scrollLeft, top: e.currentTarget.scrollTop });
          measure();
        }}
      >
        <svg
          width={totalW}
          height={totalH}
          role="img"
          aria-label={`Measured traffic matrix, ${nodes} sources by ${nodes} destinations`}
          data-testid="measured-matrix-svg"
        >
          {cols.map((d) => (
            <text key={`d${d}`} x={PAD + d * CELL + CELL / 2} y={PAD - 10} textAnchor="middle" className="cv-label-sm">{d}</text>
          ))}
          {rows.map((s) => (
            <text key={`s${s}`} x={PAD - 6} y={PAD + s * CELL + CELL / 2 + 3} textAnchor="end" className="cv-label-sm">{s}</text>
          ))}
          {rows.flatMap((s) => cols.map((d) => {
            const on = selected?.src === s && selected?.dst === d;
            const value = matrix[s]?.[d] ?? 0;
            return (
              <rect
                key={`${s}-${d}`}
                className="loom-matrix-cell"
                data-testid={`mx-${s}-${d}`}
                x={PAD + d * CELL}
                y={PAD + s * CELL}
                width={CELL - 1}
                height={CELL - 1}
                fill={s === d ? 'var(--border)' : shade(value)}
                stroke={on ? 'var(--accent)' : 'var(--border)'}
                strokeWidth={on ? 2 : 0.5}
                style={s === d || value <= 0 || !onSelect ? undefined : { cursor: 'pointer' }}
                onClick={s === d || value <= 0 || !onSelect ? undefined : () => onSelect(s, d)}
              >
                <title>{`${s} → ${d}: ${value.toLocaleString()} packets`}</title>
              </rect>
            );
          }))}
        </svg>
      </div>
      <span className="muted" data-testid="measured-matrix-window" style={{ display: 'block', fontSize: 11, marginTop: 2 }}>
        {windowCellCount(win)} of {nodes * nodes} cells drawn (scroll to pan)
      </span>
    </div>
  );
}
