/** Matrix windowing math (M3-16) and the virtualized measured matrix. */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { matrixWindow, visibleRange, windowCellCount } from '../graph/matrixWindow';
import { MeasuredMatrix } from '../pages/loom/MeasuredMatrix';

afterEach(cleanup);

describe('M3-16: visibleRange', () => {
  it('covers the viewport plus overscan from the top', () => {
    expect(visibleRange(0, 260, 26, 40, 2)).toEqual({ start: 0, end: 12 });
  });

  it('shifts with the scroll offset and clamps to the count', () => {
    expect(visibleRange(260, 260, 26, 40, 2)).toEqual({ start: 8, end: 22 });
    expect(visibleRange(900, 260, 26, 40, 2)).toEqual({ start: 32, end: 40 });
  });

  it('is empty for a zero count or a non-positive item size', () => {
    expect(visibleRange(0, 260, 26, 0)).toEqual({ start: 0, end: 0 });
    expect(visibleRange(0, 260, 0, 40)).toEqual({ start: 0, end: 0 });
  });

  it('computes a window and its cell budget', () => {
    const win = matrixWindow(40, 40, 26, { left: 0, top: 0 }, { width: 260, height: 260 }, 2);
    expect(win.cols).toEqual({ start: 0, end: 12 });
    expect(win.rows).toEqual({ start: 0, end: 12 });
    expect(windowCellCount(win)).toBe(144);
  });
});

const grid = (n: number): number[][] => Array.from({ length: n }, () => Array.from({ length: n }, () => 1));

describe('M3-16: virtualized measured matrix', () => {
  it('draws only the visible window of a large matrix', () => {
    render(<MeasuredMatrix matrix={grid(40)} />);
    const drawn = document.querySelectorAll('.loom-matrix-cell').length;
    expect(drawn).toBeGreaterThan(0);
    expect(drawn).toBeLessThan(40 * 40);
    expect(screen.getByTestId('mx-0-0')).toBeTruthy();
    expect(screen.queryByTestId('mx-39-39')).toBeNull();
    expect(screen.getByTestId('measured-matrix-window').textContent).toContain('of 1600 cells drawn');
  });

  it('keeps the full matrix reachable by scrolling', () => {
    render(<MeasuredMatrix matrix={grid(40)} />);
    const scroller = screen.getByTestId('measured-matrix-scroll');
    Object.defineProperty(scroller, 'scrollLeft', { configurable: true, value: 900 });
    Object.defineProperty(scroller, 'scrollTop', { configurable: true, value: 900 });
    fireEvent.scroll(scroller);
    expect(screen.getByTestId('mx-38-38')).toBeTruthy();
  });

  it('reports a clicked cell', () => {
    const onSelect = vi.fn();
    render(<MeasuredMatrix matrix={grid(4)} selected={{ src: 1, dst: 2 }} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId('mx-1-2'));
    expect(onSelect).toHaveBeenCalledWith(1, 2);
  });
});
