import type { MappingRow, ParallelCoordinates } from './gateway';

export type ParallelAxis = 'tp' | 'dp' | 'ep' | 'pp';
export const PARALLEL_AXES: ParallelAxis[] = ['tp', 'dp', 'ep', 'pp'];

export function axisDegree(parallelism: ParallelCoordinates | null | undefined, axis: ParallelAxis): number {
  return Math.max(1, parallelism?.[axis] ?? 1);
}

// Stable hue per group coordinate. Distinct for small degrees, still distinct
// for a 32-way TP group; no group is assigned a colour from a truncated list.
export function parallelColor(coordinate: number, degree: number): string {
  const safeDegree = Math.max(1, degree);
  const hue = Math.round(((coordinate % safeDegree) + safeDegree) % safeDegree * 360 / safeDegree);
  return `hsl(${hue} 58% 42%)`;
}

export type ParallelGroup = {
  coordinate: number;
  ranks: number;
  routers: number[];
};

export function parallelGroups(
  rows: MappingRow[],
  endpointRouter: Map<number, number>,
  axis: ParallelAxis,
): ParallelGroup[] {
  const groups = new Map<number, { ranks: number; routers: Set<number> }>();
  for (const row of rows) {
    const coordinate = row.coordinates?.[axis];
    if (typeof coordinate !== 'number') continue;
    const group = groups.get(coordinate) ?? { ranks: 0, routers: new Set<number>() };
    group.ranks += 1;
    const router = endpointRouter.get(row.endpoint_id);
    if (router !== undefined) group.routers.add(router);
    groups.set(coordinate, group);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([coordinate, group]) => ({
      coordinate,
      ranks: group.ranks,
      routers: [...group.routers].sort((a, b) => a - b),
    }));
}
