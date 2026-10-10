/** Orthogonal/Manhattan link routing with waypoints.
 * Pure geometry for the canvas — never a routing claim. */
export interface Pt { x: number; y: number }

export function manhattan(a: Pt, b: Pt): Pt[] {
  if (a.x === b.x || a.y === b.y) return [a, b];
  const mid: Pt = { x: b.x, y: a.y };
  return [a, mid, b];
}

/** Manhattan length in canvas units (sums segments). */
export function manhattanLength(pts: Pt[]): number {
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    total += Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y);
  }
  return total;
}

/** Crude wire-delay estimate flagged TODO (no PDK): length × k. */
export function wireDelayPs(manhattanUnits: number): number {
  return manhattanUnits * 0.5;
}

export function pathFor(pts: Pt[]): string {
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
}
