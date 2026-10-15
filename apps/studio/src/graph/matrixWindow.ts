/** Matrix windowing for large initiator×target grids (tracker M3-16).
 *
 *  Pure index math: given a scroll offset, a viewport extent and an item size,
 *  return the half-open index range that is actually visible (plus a small
 *  overscan so a fast scroll never shows a blank edge). No DOM, no layout.
 */
export interface Range { start: number; end: number }
export interface MatrixWindow { rows: Range; cols: Range }

/** Visible index range `[start, end)` for one axis. Offsets and sizes are in
 *  pixels; a non-positive item size or an empty count yields an empty range. */
export function visibleRange(
  offset: number, viewport: number, itemSize: number, count: number, overscan = 2,
): Range {
  if (count <= 0 || !Number.isFinite(itemSize) || itemSize <= 0) return { start: 0, end: 0 };
  const start = Math.max(0, Math.floor(offset / itemSize) - overscan);
  const end = Math.min(count, Math.ceil((offset + Math.max(0, viewport)) / itemSize) + overscan);
  return { start, end: Math.max(start, end) };
}

/** Visible rows and columns for a cell-sized matrix. `scroll` and `viewport`
 *  are pixels; the result is clamped to the matrix bounds. */
export function matrixWindow(
  rowCount: number, colCount: number, cell: number,
  scroll: { left: number; top: number },
  viewport: { width: number; height: number },
  overscan = 2,
): MatrixWindow {
  return {
    rows: visibleRange(scroll.top, viewport.height, cell, rowCount, overscan),
    cols: visibleRange(scroll.left, viewport.width, cell, colCount, overscan),
  };
}

/** The number of cells a window would render — the budget the virtualization
 *  is meant to hold down. */
export const windowCellCount = (window: MatrixWindow): number =>
  (window.rows.end - window.rows.start) * (window.cols.end - window.cols.start);
