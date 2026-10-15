import type { DieOutline, FloorplanIntent, GraphEdge, PhysicalDelayModel, PhysicalKeepout, PhysicalPlacement, PhysicalUnit, Rect } from './project';

export function estimateManhattanRouteDelayPs(route: ManhattanPhysicalRoute, model: PhysicalDelayModel): number | null {
  if (route.status !== 'routed' || route.length === undefined) return null;
  const estimate = route.length * model.wireDelayPsPerUnit + model.fixedDelayPs;
  return Number.isFinite(estimate) && estimate >= 0 ? Number(estimate.toPrecision(12)) : null;
}

export interface ManhattanPhysicalRoute {
  edgeId: string;
  status: 'routed' | 'unresolved';
  points?: Array<{ x: number; y: number }>;
  length?: number;
  error?: string;
  provenance: 'LOCAL_MANHATTAN_PLACEMENT_PREVIEW';
}

/** Deterministic centerline-geometry preview; does not avoid obstacles or model physical routing. */
export function routeAllManhattanPhysicalEdges(edges: GraphEdge[], placements: PhysicalPlacement[], constraints?: { die?: DieOutline; keepouts?: PhysicalKeepout[] }): ManhattanPhysicalRoute[] {
  const byNode = new Map(placements.map((placement) => [placement.nodeId, placement]));
  return edges.map((edge) => {
    const a = byNode.get(edge.src);
    const b = byNode.get(edge.dst);
    const unresolved = (error: string): ManhattanPhysicalRoute => ({ edgeId: edge.id, status: 'unresolved', error, provenance: 'LOCAL_MANHATTAN_PLACEMENT_PREVIEW' });
    if (!a || !b) return unresolved(`Missing physical placement for ${!a && !b ? `${edge.src} and ${edge.dst}` : !a ? edge.src : edge.dst}.`);
    if (edge.src === edge.dst) return unresolved('Self-loop physical routes are not supported by this preview.');
    const ax = a.x + a.width / 2;
    const ay = a.y + a.height / 2;
    const bx = b.x + b.width / 2;
    const by = b.y + b.height / 2;
    const dx = bx - ax;
    const dy = by - ay;
    let start: { x: number; y: number };
    let bend: { x: number; y: number };
    let end: { x: number; y: number };
    if (Math.abs(dx) >= Math.abs(dy)) {
      start = { x: dx >= 0 ? a.x + a.width : a.x, y: ay };
      end = { x: dx >= 0 ? b.x : b.x + b.width, y: by };
      bend = { x: end.x, y: start.y };
    } else {
      start = { x: ax, y: dy >= 0 ? a.y + a.height : a.y };
      end = { x: bx, y: dy >= 0 ? b.y : b.y + b.height };
      bend = { x: start.x, y: end.y };
    }
    const authoredWaypoints = edge.physical?.waypoints;
    const points = authoredWaypoints === undefined
      ? [start, bend, end].filter((point, index, all) => index === 0 || point.x !== all[index - 1]!.x || point.y !== all[index - 1]!.y)
      : [start, ...authoredWaypoints, end].reduce<Array<{ x: number; y: number }>>((path, target) => {
        const current = path[path.length - 1]!;
        const corner = { x: target.x, y: current.y };
        for (const point of [corner, target]) if (point.x !== path[path.length - 1]!.x || point.y !== path[path.length - 1]!.y) path.push(point);
        return path;
      }, [start]);
    const length = points.slice(1).reduce((sum, point, index) => sum + Math.abs(point.x - points[index]!.x) + Math.abs(point.y - points[index]!.y), 0);
    if (![...points.flatMap((point) => [point.x, point.y]), length].every(Number.isFinite)) return unresolved('Physical route geometry is not finite.');
    if (constraints?.die && points.some((point) => point.x < constraints.die!.originX || point.y < constraints.die!.originY
      || point.x > constraints.die!.originX + constraints.die!.width || point.y > constraints.die!.originY + constraints.die!.height))
      return unresolved('Physical route leaves the authored die outline.');
    const segments = points.slice(1).map((point, index) => [points[index]!, point] as const);
    const segmentHits = (a: { x: number; y: number }, b: { x: number; y: number }, rect: Rect): boolean => {
      if (a.y === b.y) return a.y > rect.y && a.y < rect.y + rect.height
        && Math.max(Math.min(a.x, b.x), rect.x) < Math.min(Math.max(a.x, b.x), rect.x + rect.width);
      if (a.x === b.x) return a.x > rect.x && a.x < rect.x + rect.width
        && Math.max(Math.min(a.y, b.y), rect.y) < Math.min(Math.max(a.y, b.y), rect.y + rect.height);
      return true;
    };
    for (const [a, b] of segments) {
      const blockingPlacement = placements.find((placement) => placement.nodeId !== edge.src && placement.nodeId !== edge.dst
        && segmentHits(a, b, placement));
      if (blockingPlacement) return unresolved(`Route intersects placed node ${blockingPlacement.nodeId}.`);
      const blockingKeepout = (constraints?.keepouts ?? []).find((keepout) => segmentHits(a, b, keepout));
      if (blockingKeepout) return unresolved(`Route intersects keepout ${blockingKeepout.id}.`);
    }
    // Endpoint rectangles are exempt: generated paths begin/end on their boundary.
    return { edgeId: edge.id, status: 'routed', points, length, provenance: 'LOCAL_MANHATTAN_PLACEMENT_PREVIEW' };
  });
}

/** Convert explicit physical units; canvas pixels are never accepted here. */
export function convertPhysicalLength(value: number, from: PhysicalUnit, to: PhysicalUnit): number {
  if (!Number.isFinite(value)) throw new Error('physical length must be finite');
  if (from === to) return value;
  return from === 'mm' && to === 'um' ? value * 1000 : value / 1000;
}

export function convertDieOutline(die: DieOutline, from: PhysicalUnit, to: PhysicalUnit): DieOutline {
  return {
    originX: convertPhysicalLength(die.originX, from, to),
    originY: convertPhysicalLength(die.originY, from, to),
    width: convertPhysicalLength(die.width, from, to),
    height: convertPhysicalLength(die.height, from, to),
  };
}

export function convertFloorplanIntent(floorplan: FloorplanIntent, to: PhysicalUnit): FloorplanIntent {
  const from = floorplan.unit;
  if (from === to) return floorplan;
  return {
    unit: to,
    ...(floorplan.gridStep !== undefined ? { gridStep: convertPhysicalLength(floorplan.gridStep, from, to) } : {}),
    ...(floorplan.delayModel ? { delayModel: {
      wireDelayPsPerUnit: from === to ? floorplan.delayModel.wireDelayPsPerUnit : from === 'mm' ? floorplan.delayModel.wireDelayPsPerUnit / 1000 : floorplan.delayModel.wireDelayPsPerUnit * 1000,
      fixedDelayPs: floorplan.delayModel.fixedDelayPs,
    } } : {}),
    ...(floorplan.die ? { die: convertDieOutline(floorplan.die, from, to) } : {}),
    ...(floorplan.placements ? { placements: floorplan.placements.map((placement) => ({
      ...placement,
      x: convertPhysicalLength(placement.x, from, to),
      y: convertPhysicalLength(placement.y, from, to),
      width: convertPhysicalLength(placement.width, from, to),
      height: convertPhysicalLength(placement.height, from, to),
    })) } : {}),
    ...(floorplan.keepouts ? { keepouts: floorplan.keepouts.map((keepout) => ({
      ...keepout,
      x: convertPhysicalLength(keepout.x, from, to),
      y: convertPhysicalLength(keepout.y, from, to),
      width: convertPhysicalLength(keepout.width, from, to),
      height: convertPhysicalLength(keepout.height, from, to),
    })) } : {}),
  };
}
