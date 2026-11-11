import type { Topology } from './gateway';

/** The watch log records the head flit's route-compute, VC-allocation,
 *  switch-allocation and crossbar events by name. These are the phases those
 *  lines identify. Nothing is inferred when a line is absent. */
export type ObservedPhaseKind =
  | 'source' | 'ingress' | 'buffer' | 'route' | 'vc' | 'switch'
  | 'crossbar' | 'link' | 'eject' | 'tail';

export type ObservedPhase = {
  kind: ObservedPhaseKind;
  start: number;
  end: number;
  router?: number;
  port?: number;
};

export type ObservedPacketPath = {
  packet: number;
  subnet: number;
  source: number;
  destination: number;
  headFlit: number;
  flits: number;
  requestTime: number;
  enqueueCycle: number;
  injectionCycle: number | null;
  headRetireCycle: number | null;
  retireCycle: number | null;
  /** Request-to-tail-retire cycles, the recorded plat when present. */
  total: number | null;
  hops: number;
  phases: ObservedPhase[];
  complete: boolean;
};

export type ObservedPacketCapture = {
  packets: ObservedPacketPath[];
  firstCycle: number;
  lastCycle: number;
  subnets: number[];
};

export type ObservedPhaseGroup = 'source' | 'queue' | 'arbitration' | 'transmission' | 'drain';

export type ObservedGroupTotals = Record<ObservedPhaseGroup, number> & { total: number };

export const PHASE_LABELS: Record<ObservedPhaseKind, string> = {
  source: 'Source wait',
  ingress: 'Source channel',
  buffer: 'Input buffer wait',
  route: 'Route compute',
  vc: 'VC allocation',
  switch: 'Switch allocation',
  crossbar: 'Crossbar traversal',
  link: 'Link flight',
  eject: 'Ejection',
  tail: 'Body drain',
};

/** The five buckets the cycle budget reports. Route and crossbar are work the
 *  router performs; link flight and ejection move the flit; the tail is the
 *  packet's body flits retiring after the head. */
export const PHASE_GROUP: Record<ObservedPhaseKind, ObservedPhaseGroup> = {
  source: 'source', ingress: 'transmission', buffer: 'queue', route: 'transmission',
  vc: 'arbitration', switch: 'arbitration', crossbar: 'transmission',
  link: 'transmission', eject: 'transmission', tail: 'drain',
};

export const GROUP_LABELS: Record<ObservedPhaseGroup, string> = {
  source: 'Source wait',
  queue: 'Router queue',
  arbitration: 'Arbitration',
  transmission: 'Transmission',
  drain: 'Body drain',
};

export function packetGroupTotals(path: ObservedPacketPath): ObservedGroupTotals {
  const totals: ObservedGroupTotals = { source: 0, queue: 0, arbitration: 0, transmission: 0, drain: 0, total: 0 };
  for (const phase of path.phases) {
    const cycles = Math.max(0, phase.end - phase.start);
    totals[PHASE_GROUP[phase.kind]] += cycles;
    totals.total += cycles;
  }
  return totals;
}

type RouterMark = { begin?: number; end?: number };
type Left = { cycle: number; node: number; time: number };
type Arrival = { cycle: number; router: number; port: number; subnet: number };
type Departure = { cycle: number; router: number; port: number; subnet: number };

const messageOf = (line: string): { cycle: number; name: string; message: string } | null => {
  const first = line.indexOf(' | ');
  if (first < 0) return null;
  const second = line.indexOf(' | ', first + 3);
  if (second < 0) return null;
  const cycle = Number(line.slice(0, first));
  if (!Number.isFinite(cycle)) return null;
  return { cycle, name: line.slice(first + 3, second), message: line.slice(second + 3) };
};

const routerOf = (name: string, ids: Map<string, number>): number | null => {
  const parts = name.split('/');
  const last = parts[parts.length - 1] ?? '';
  const match = /^(?:srota_)?router_(\d+)_(\d+)$/.exec(last);
  if (!match) return null;
  return ids.get(`${match[1]}_${match[2]}`) ?? null;
};

const subnetOf = (name: string): number => {
  const match = /^network_(\d+)\//.exec(name);
  return match ? Number(match[1]) : 0;
};

const mark = (map: Map<string, RouterMark>, key: string, edge: 'begin' | 'end', cycle: number) => {
  const current = map.get(key) ?? {};
  if (edge === 'begin') current.begin = current.begin === undefined ? cycle : Math.min(current.begin, cycle);
  else current.end = current.end === undefined ? cycle : Math.max(current.end, cycle);
  map.set(key, current);
};

/** Decode the bounded watch capture into one path per sampled packet. The
 *  head flit supplies the router pipeline; the packet's tail retire closes the
 *  row, so body-flit serialization is visible instead of hidden. */
export function decodeObservedPackets(text: string, topology: Topology): ObservedPacketCapture {
  const ids = new Map(topology.routers.filter(row => row.coordinates?.length === 2)
    .map(row => [`${row.coordinates[1]}_${row.coordinates[0]}`, row.router_id]));
  const packetEnqueue = new Map<number, Left>();
  const flitEnqueue = new Map<number, { cycle: number; time: number; node: number; packet: number }>();
  const injections = new Map<number, { cycle: number; subnet: number; node: number }>();
  const receives = new Map<number, Arrival[]>();
  const sends = new Map<number, Departure[]>();
  const route = new Map<string, RouterMark>();
  const vc = new Map<string, RouterMark>();
  const sw = new Map<string, RouterMark>();
  const crossbar = new Map<string, RouterMark>();
  const ejects = new Map<number, { cycle: number; node: number }>();
  const flitRetire = new Map<number, { cycle: number; packet: number; src: number; dest: number; hops: number }>();
  const packetRetire = new Map<number, { cycle: number; plat: number; nlat: number; src: number; dest: number }>();
  const packetFlits = new Map<number, number[]>();

  for (const raw of text.split(/\r?\n/)) {
    const parsed = messageOf(raw.trim());
    if (!parsed) continue;
    const { cycle, name, message } = parsed;
    let match: RegExpExecArray | null;

    if ((match = /^Enqueuing packet (\d+) at time (\d+)\.$/.exec(message))) {
      const packet = Number(match[1]);
      const node = Number(/^node(-?\d+)$/.exec(name)?.[1] ?? 0);
      if (!packetEnqueue.has(packet)) packetEnqueue.set(packet, { cycle, node, time: Number(match[2]) });
      continue;
    }
    if ((match = /^Enqueuing flit (\d+) \(packet (\d+)\) at time (\d+)\.$/.exec(message))) {
      const flit = Number(match[1]), packet = Number(match[2]);
      if (!flitEnqueue.has(flit)) flitEnqueue.set(flit, { cycle, time: Number(match[3]), node: Number(/^node(-?\d+)$/.exec(name)?.[1] ?? 0), packet });
      const list = packetFlits.get(packet) ?? []; list.push(flit); packetFlits.set(packet, list);
      continue;
    }
    if ((match = /^Injecting flit (\d+) into subnet (\d+) at time (\d+) with priority \d+\.$/.exec(message))) {
      injections.set(Number(match[1]), { cycle, subnet: Number(match[2]), node: Number(/^node(-?\d+)$/.exec(name)?.[1] ?? 0) });
      continue;
    }
    if ((match = /^Received flit (\d+) from channel at input (\d+)\.$/.exec(message))) {
      const router = routerOf(name, ids);
      if (router === null) continue;
      const flit = Number(match[1]);
      const list = receives.get(flit) ?? [];
      list.push({ cycle, router, port: Number(match[2]), subnet: subnetOf(name) });
      receives.set(flit, list);
      continue;
    }
    if ((match = /^Sending flit (\d+) to channel at output (\d+)\.$/.exec(message))) {
      const router = routerOf(name, ids);
      if (router === null) continue;
      const flit = Number(match[1]);
      const list = sends.get(flit) ?? [];
      list.push({ cycle, router, port: Number(match[2]), subnet: subnetOf(name) });
      sends.set(flit, list);
      continue;
    }
    if ((match = /^(Beginning|Completed) (routing|VC allocation|switch allocation) for VC \d+ at input \d+ \(front: (\d+)\)\.$/.exec(message))) {
      const router = routerOf(name, ids);
      if (router === null) continue;
      const flit = Number(match[3]);
      const edge = match[1] === 'Beginning' ? 'begin' : 'end';
      const key = `${router}:${flit}`;
      const target = match[2] === 'routing' ? route : match[2] === 'VC allocation' ? vc : sw;
      mark(target, key, edge, cycle);
      continue;
    }
    if ((match = /^(Beginning|Completed) crossbar traversal for flit (\d+) from input \d+\.\d+ to output \d+\.\d+\.$/.exec(message))) {
      const router = routerOf(name, ids);
      if (router === null) continue;
      mark(crossbar, `${router}:${Number(match[2])}`, match[1] === 'Beginning' ? 'begin' : 'end', cycle);
      continue;
    }
    if ((match = /^Ejecting flit (\d+) \(packet (\d+)\) from VC \d+\.$/.exec(message))) {
      ejects.set(Number(match[1]), { cycle, node: Number(/^node(-?\d+)$/.exec(name)?.[1] ?? 0) });
      continue;
    }
    if ((match = /^Retiring flit (\d+) \(packet (\d+), src = (-?\d+), dest = (-?\d+), hops = (\d+), flat = (\d+)\)\.$/.exec(message))) {
      flitRetire.set(Number(match[1]), {
        cycle, packet: Number(match[2]), src: Number(match[3]), dest: Number(match[4]), hops: Number(match[5]),
      });
      continue;
    }
    if ((match = /^Retiring packet (\d+) \(plat = (\d+), nlat = (\d+), frag = (-?\d+), src = (-?\d+), dest = (-?\d+)\)\.$/.exec(message))) {
      packetRetire.set(Number(match[1]), {
        cycle, plat: Number(match[2]), nlat: Number(match[3]), src: Number(match[5]), dest: Number(match[6]),
      });
    }
  }

  const packetIds = new Set<number>([...packetEnqueue.keys(), ...packetRetire.keys(), ...packetFlits.keys()]);
  // Retiring rows may name a packet whose enqueue line fell outside the
  // capture; keep it as a packet candidate and let completeness decide.
  for (const row of flitRetire.values()) packetIds.add(row.packet);

  const packets: ObservedPacketPath[] = [];
  for (const packet of packetIds) {
    const knownFlits = [...(packetFlits.get(packet) ?? [])];
    if (!knownFlits.length) for (const [flit, row] of flitRetire) if (row.packet === packet) knownFlits.push(flit);
    const headFlit = knownFlits.length ? Math.min(...knownFlits) : null;
    if (headFlit === null) continue;

    const enqueue = packetEnqueue.get(packet);
    const headEnqueue = flitEnqueue.get(headFlit);
    const injection = injections.get(headFlit);
    const tail = packetRetire.get(packet);
    const headRetire = flitRetire.get(headFlit);
    const requestTime = enqueue?.time ?? headEnqueue?.time ?? 0;
    const enqueueCycle = enqueue?.cycle ?? headEnqueue?.cycle ?? requestTime;
    const injectionCycle = injection?.cycle ?? null;
    const retireCycle = tail?.cycle ?? (() => {
      let last = -Infinity;
      for (const row of flitRetire.values()) if (row.packet === packet) last = Math.max(last, row.cycle);
      return Number.isFinite(last) ? last : null;
    })();
    const destination = tail?.dest ?? headRetire?.dest ?? -1;
    const source = enqueue?.node ?? headEnqueue?.node ?? headRetire?.src ?? -1;
    const hops = flitRetire.get(headFlit)?.hops ?? 0;
    const arrivals = [...(receives.get(headFlit) ?? [])].sort((a, b) => a.cycle - b.cycle || a.router - b.router);
    const departures = [...(sends.get(headFlit) ?? [])].sort((a, b) => a.cycle - b.cycle || a.router - b.router);
    const subnet = injection?.subnet ?? arrivals[0]?.subnet ?? 0;
    const phases: ObservedPhase[] = [];
    // The packet retire line is the only proof that the body drained. A head
    // flit retire alone is not a complete packet path.
    let complete = tail !== undefined;
    const push = (kind: ObservedPhaseKind, start: number | undefined, end: number | undefined, meta: { router?: number; port?: number } = {}) => {
      if (start === undefined || end === undefined || !Number.isFinite(start) || !Number.isFinite(end)) return;
      const high = Math.max(start, end);
      if (high === start) return;
      phases.push({ kind, start, end: high, ...meta });
    };

    let cursor = requestTime;
    if (injectionCycle !== null && injectionCycle >= requestTime) {
      push('source', requestTime, injectionCycle);
      cursor = injectionCycle;
    } else {
      complete = false;
    }

    if (injectionCycle !== null && arrivals.length) {
      push('ingress', cursor, arrivals[0].cycle, { router: arrivals[0].router, port: -1 });
      cursor = Math.max(cursor, arrivals[0].cycle);
    } else if (!arrivals.length) {
      complete = false;
    }

    const usedDepartures = new Set<number>();
    for (let index = 0; index < arrivals.length; index += 1) {
      const arrival = arrivals[index];
      let departure: Departure | undefined;
      for (let candidate = 0; candidate < departures.length; candidate += 1) {
        if (usedDepartures.has(candidate)) continue;
        if (departures[candidate].router !== arrival.router) continue;
        if (departures[candidate].cycle < arrival.cycle) continue;
        departure = departures[candidate];
        usedDepartures.add(candidate);
        break;
      }
      const nextArrival = arrivals[index + 1];
      const eject = ejects.get(headFlit)?.cycle;
      const sendCycle = departure?.cycle ?? nextArrival?.cycle ?? eject ?? retireCycle ?? undefined;
      if (sendCycle === undefined) { complete = false; break; }
      const key = `${arrival.router}:${headFlit}`;
      const routeMark = route.get(key);
      const vcMark = vc.get(key);
      const swMark = sw.get(key);
      const xbarMark = crossbar.get(key);
      const phaseStart = Math.max(cursor, arrival.cycle);
      const bufferEnd = routeMark?.begin ?? vcMark?.begin ?? swMark?.begin ?? xbarMark?.begin ?? sendCycle;
      push('buffer', phaseStart, bufferEnd, { router: arrival.router, port: arrival.port });
      cursor = Math.max(phaseStart, bufferEnd);
      if (routeMark?.end !== undefined) {
        push('route', cursor, routeMark.end, { router: arrival.router });
        cursor = Math.max(cursor, routeMark.end);
      }
      const vcEnd = vcMark?.end ?? swMark?.begin ?? xbarMark?.begin ?? sendCycle;
      push('vc', cursor, vcEnd, { router: arrival.router });
      cursor = Math.max(cursor, vcEnd);
      const swEnd = swMark?.end ?? xbarMark?.begin ?? sendCycle;
      push('switch', cursor, swEnd, { router: arrival.router });
      cursor = Math.max(cursor, swEnd);
      push('crossbar', cursor, sendCycle, { router: arrival.router, port: departure?.port });
      cursor = Math.max(cursor, sendCycle);
      if (nextArrival) {
        push('link', cursor, nextArrival.cycle, { router: arrival.router, port: departure?.port });
        cursor = Math.max(cursor, nextArrival.cycle);
      } else {
        const ejectCycle = eject ?? headRetire?.cycle ?? sendCycle;
        push('eject', cursor, ejectCycle, { router: arrival.router, port: departure?.port });
        cursor = Math.max(cursor, ejectCycle);
      }
    }

    const headRetireCycle = headRetire?.cycle ?? null;
    if (retireCycle !== null && retireCycle >= cursor) {
      push('tail', cursor, retireCycle);
    }
    const total = retireCycle === null ? null : retireCycle - requestTime;
    const covered = phases.reduce((sum, phase) => sum + (phase.end - phase.start), 0);
    if (total === null || covered !== total) complete = false;
    packets.push({
      packet, subnet, source, destination, headFlit,
      flits: knownFlits.length,
      requestTime, enqueueCycle, injectionCycle, headRetireCycle, retireCycle, total, hops, phases, complete,
    });
  }

  packets.sort((a, b) => a.requestTime - b.requestTime || a.packet - b.packet);
  const cycles = packets.flatMap(row => [row.requestTime, row.retireCycle ?? row.requestTime]);
  return {
    packets,
    firstCycle: cycles.length ? Math.min(...cycles) : 0,
    lastCycle: cycles.length ? Math.max(...cycles) : 0,
    subnets: [...new Set(packets.map(row => row.subnet))].sort((a, b) => a - b),
  };
}
