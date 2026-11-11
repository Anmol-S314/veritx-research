import type { Topology } from './gateway';

export type ConnectionLayer = 'channels' | 'shared';

export type IncidenceMatrix = {
  ids: number[];
  /** Symmetric counts; `counts[i][j]` is the number of declared resources
   *  between `ids[i]` and `ids[j]`. Diagonal is always zero. */
  counts: number[][];
  max: number;
  pairs: number;
};

/** Declared connection incidence only. Channels are directed resources and are
 *  folded into undirected pairs for the matrix; shared wires contribute one
 *  driver→tap incidence per tap. Neither becomes permission or traffic. */
export function incidenceMatrix(topology: Topology, layer: ConnectionLayer): IncidenceMatrix {
  const ids = [...new Set(topology.routers.map(router => router.router_id))].sort((a, b) => a - b);
  const index = new Map(ids.map((id, i) => [id, i]));
  const counts = ids.map(() => ids.map(() => 0));
  const add = (a: number, b: number): void => {
    const i = index.get(a);
    const j = index.get(b);
    if (i === undefined || j === undefined || i === j) return;
    counts[i][j] += 1;
    counts[j][i] += 1;
  };
  if (layer === 'channels') {
    for (const channel of topology.channels) add(channel.src_router, channel.dst_router);
  } else {
    for (const wire of topology.shared_links ?? []) {
      for (const tap of wire.taps) add(wire.src_router, tap);
    }
  }
  let max = 0;
  let pairs = 0;
  for (let i = 0; i < ids.length; i += 1) {
    for (let j = i + 1; j < ids.length; j += 1) {
      const value = counts[i][j];
      if (value > 0) pairs += 1;
      if (value > max) max = value;
    }
  }
  return { ids, counts, max, pairs };
}
