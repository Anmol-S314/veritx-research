/** Orthogonal/Manhattan link routing with waypoints.
 * Pure geometry for the canvas — never a routing claim. */
export interface Pt { x: number; y: number }

export function manhattan(a: Pt, b: Pt): Pt[] {
  if (a.x === b.x || a.y === b.y) return [a, b];
  const mid: Pt = { x: b.x, y: a.y };
  return [a, mid, b];
}

export interface RouteObstacle { x: number; y: number; width: number; height: number }

/** Route orthogonally around rectangular canvas obstacles. This is a drawing
 * heuristic only; it does not describe a physical route or implementation. */
export function manhattanAvoiding(a: Pt, b: Pt, obstacles: RouteObstacle[], clearance = 8): Pt[] {
  const rects = obstacles.map((rect) => ({
    left: rect.x - clearance, right: rect.x + rect.width + clearance,
    top: rect.y - clearance, bottom: rect.y + rect.height + clearance,
  }));
  const blocked = (p: Pt, q: Pt): boolean => rects.some((r) => {
    if (p.x === q.x) return p.x > r.left && p.x < r.right
      && Math.max(Math.min(p.y, q.y), r.top) < Math.min(Math.max(p.y, q.y), r.bottom);
    if (p.y === q.y) return p.y > r.top && p.y < r.bottom
      && Math.max(Math.min(p.x, q.x), r.left) < Math.min(Math.max(p.x, q.x), r.right);
    return true;
  });
  const simplify = (points: Pt[]): Pt[] => {
    const out: Pt[] = [];
    for (const point of points) {
      if (out.length && out[out.length - 1].x === point.x && out[out.length - 1].y === point.y) continue;
      if (out.length >= 2) {
        const before = out[out.length - 2]; const last = out[out.length - 1];
        if ((before.x === last.x && last.x === point.x) || (before.y === last.y && last.y === point.y)) out.pop();
      }
      out.push(point);
    }
    return out;
  };
  const clear = (points: Pt[]): boolean => points.every((point, index) =>
    index === points.length - 1 || !blocked(point, points[index + 1]));
  const direct = [simplify(manhattan(a, b)), simplify([a, { x: a.x, y: b.y }, b])];
  const directClear = direct.filter(clear);
  if (directClear.length) return directClear[0];

  const xs = new Set<number>(); const ys = new Set<number>();
  for (const rect of rects) { xs.add(rect.left); xs.add(rect.right); ys.add(rect.top); ys.add(rect.bottom); }
  const xCorridors = [...xs].sort((x, y) => Math.min(Math.abs(x - a.x), Math.abs(x - b.x)) - Math.min(Math.abs(y - a.x), Math.abs(y - b.x)));
  const yCorridors = [...ys].sort((y, z) => Math.min(Math.abs(y - a.y), Math.abs(y - b.y)) - Math.min(Math.abs(z - a.y), Math.abs(z - b.y)));
  const candidates: Pt[][] = [];
  for (const x of xCorridors) candidates.push(simplify([a, { x, y: a.y }, { x, y: b.y }, b]));
  for (const y of yCorridors) candidates.push(simplify([a, { x: a.x, y }, { x: b.x, y }, b]));
  candidates.sort((p, q) => manhattanLength(p) - manhattanLength(q));
  return candidates.find(clear) ?? direct[0];
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
