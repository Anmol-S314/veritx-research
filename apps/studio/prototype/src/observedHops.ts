import type { Topology } from './gateway';
// BookSim's watch line prints `f->id`, which in this fork is the GLOBAL FLIT id
// ("Enqueuing flit 61870 (packet 8835)"), not the packet id. `watch_packets`
// selects packets; every flit of a selected packet is logged, so the join key
// is the flit id and each watched flit carries the packet's path.
export type ObservedHopEvent = { cycle: number; subnet: number; router: number; flit: number; port: number; kind: 'receive' | 'send' };

/** Parse only explicitly observed router receipt/send events. Unknown names are never guessed. */
export function decodeObservedHops(text: string, topology: Topology): ObservedHopEvent[] {
  const coordinates = new Map(topology.routers.filter(row => row.coordinates?.length === 2).map(row => [`${row.coordinates[1]}_${row.coordinates[0]}`, row.router_id]));
  const events: ObservedHopEvent[] = [];
  for (const line of text.split('\n')) {
    const match = /^(\d+) \| network_(\d+)\/(?:srota_)?router_(\d+_\d+) \| (Received|Sending) flit (\d+) (?:from|to) channel at (?:input|output) (\d+)\./.exec(line);
    if (!match) continue;
    const router = coordinates.get(match[3]);
    if (router === undefined) continue;
    const kind = match[4] === 'Received' ? 'receive' : 'send';
    events.push({ cycle: Number(match[1]), subnet: Number(match[2]), router, flit: Number(match[5]), port: Number(match[6]), kind });
  }
  return events.sort((a, b) => a.cycle - b.cycle);
}

/** What the run recorded about a flit's own delivery. `dest` is cleared to -1 on
 *  every flit after the head, so the destination is resolved per packet from
 *  whichever flit still carries it. */
export type ObservedFlitFate = { flit: number; packet: number; sourceTerminal: number; destinationTerminal: number; hops: number };

export function decodeFlitFates(text: string): Map<number, ObservedFlitFate> {
  const rows: ObservedFlitFate[] = [];
  const destinations = new Map<number, number>();
  for (const line of text.split('\n')) {
    const match = /^\d+ \| node\d+ \| Retiring flit (\d+) \(packet (\d+), src = (-?\d+), dest = (-?\d+), hops = (\d+)/.exec(line);
    if (!match) continue;
    const packet = Number(match[2]), destination = Number(match[4]);
    if (destination >= 0) destinations.set(packet, destination);
    rows.push({ flit: Number(match[1]), packet, sourceTerminal: Number(match[3]), destinationTerminal: destination, hops: Number(match[5]) });
  }
  const fates = new Map<number, ObservedFlitFate>();
  for (const row of rows) fates.set(row.flit, destinations.has(row.packet) ? { ...row, destinationTerminal: destinations.get(row.packet)! } : row);
  return fates;
}

export function observedWireFlights(events: ObservedHopEvent[], cycle: number, subnet: number, portWires?: Map<string, { wire: number; taps: number[] }>) {
  const inFlight = new Map<number, number>();
  if (!portWires?.size) return inFlight;
  const lastReceipt = new Map<number, number>();
  for (const event of events) {
    if (event.kind === 'receive' && event.cycle <= cycle) {
      lastReceipt.set(event.flit, Math.max(lastReceipt.get(event.flit) ?? -Infinity, event.cycle));
    }
  }
  for (const event of events) {
    if (event.subnet !== subnet || event.kind !== 'send' || event.cycle > cycle) continue;
    const wire = portWires?.get(`${event.router}:${event.port}`);
    if (!wire) continue;
    const landed = (lastReceipt.get(event.flit) ?? -Infinity) >= event.cycle;
    if (!landed) inFlight.set(wire.wire, (inFlight.get(wire.wire) ?? 0) + 1);
  }
  return inFlight;
}

export function observedPositions(events: ObservedHopEvent[], cycle: number, subnet: number) {
  const at = new Map<number, ObservedHopEvent>();
  for (const event of events) {
    if (event.cycle > cycle) break;
    if (event.subnet === subnet) at.set(event.flit, event);
  }
  // A send event means the flit left this router. Do not invent an in-flight position.
  return [...at.values()].filter(event => event.kind === 'receive');
}
