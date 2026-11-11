import type { Topology } from './gateway';
import type { InjectionRow } from './trace';

export type Decision = { resource: { kind: string; resource_id: number }; next_router: number; tap: number | null; vc_partition: number };
export type SharedRouteTable = {
  artifact_id: string; routing_class: string;
  choices?: [number, number, Decision[]][]; decisions?: [number, number, Decision][];
  shape_of_partition?: Record<string, string>;
  terminal_to_router: [number, number][];
};
export type FabricHop = { key: string; from: number; to: number; latency: number; tap: number | null; wire?: number; plane: number };
export type FabricPacket = { row: InjectionRow; hops: FabricHop[]; plane: number; duration: number; sourceRouter: number; destinationRouter: number };

export function readNativeConfig(text: string) {
  const fields = new Map([...text.replace(/\/\/[^\n]*/g, '').matchAll(/(\w+)\s*=\s*([^;]+);/g)].map(match => [match[1], match[2].trim()]));
  const k = Number(fields.get('k')), c = Number(fields.get('c'));
  const mapping = fields.get('class_subnet');
  if (fields.get('topology') !== 'srota' || !Number.isInteger(k) || k < 1 || !Number.isInteger(c) || c < 1 || !mapping) throw new Error('Missing native SROTA topology or class/subnet binding.');
  const classSubnet = mapping.replace(/[{}]/g, '').split(',').map(Number);
  if (!classSubnet.length || classSubnet.some(value => !Number.isInteger(value) || value < 0 || value > 1)) throw new Error('Unsupported native class/subnet assignment.');
  const classes = Number(fields.get('classes'));
  if (!Number.isInteger(classes) || classes < 1) throw new Error('Missing native class count.');
  return { k, c, classes, classSubnet, control: !!(Number(fields.get('srota_planes')) & 2) };
}

export type WalkInput = { topology: Topology; table: SharedRouteTable; config: ReturnType<typeof readNativeConfig>; sourceTerminal: number; destinationTerminal: number; plane: number; shape: string };

/** Walk the certified v3 decisions for one (source terminal, destination
 *  terminal), retaining ONE correlated adaptive shape for the whole route.
 *  Wire resource ids are native port identities, NOT topology array indexes:
 *  bind by driver + tap. Throws instead of guessing. */
export function walkCertified({ topology, table, config, sourceTerminal, destinationTerminal, plane, shape }: WalkInput): FabricHop[] {
  const terminalRouter = new Map(table.terminal_to_router);
  const decisions = new Map((table.choices ?? table.decisions?.map(([src, dst, decision]) => [src, dst, [decision]] as [number, number, Decision[]]) ?? []).map(([src, dst, options]) => [`${src}:${dst}`, options]));
  const byCoordinate = new Map(topology.routers.map(router => [router.coordinates.join(','), router.router_id]));
  const router = new Map(topology.routers.map(item => [item.router_id, item]));
  const src = terminalRouter.get(sourceTerminal), dst = terminalRouter.get(destinationTerminal);
  if (src === undefined || dst === undefined) throw new Error('Endpoint absent from the certified terminal map');
  const hops: FabricHop[] = [];
  let current = src;
  const visited = new Set<number>();
  while (current !== dst) {
    if (visited.has(current)) throw new Error('Routing loop');
    visited.add(current);
    if (plane === 1) {
      if (!config.control) throw new Error('Plane C not enabled in executed config');
      // Native srota_planec_xy: private, one-cell XY channels, independent of Plane D wires.
      const [x, y] = router.get(current)!.coordinates, [dx, dy] = router.get(dst)!.coordinates;
      const next = byCoordinate.get(`${x !== dx ? x + Math.sign(dx - x) : x},${x === dx ? y + Math.sign(dy - y) : y}`);
      if (next === undefined) throw new Error('Control neighbour missing from native grid');
      hops.push({ key: `C:${current}:${next}`, plane, from: current, to: next, latency: 1, tap: null });
      current = next;
      continue;
    }
    const options = decisions.get(`${current}:${destinationTerminal}`) ?? [];
    // An absent map and an empty map mean the same thing: this artifact declares
    // no shape policy, so the shape argument selects nothing. Testing truthiness
    // alone would treat `{}` as a selector and reject every option.
    const partitionShapes = table.shape_of_partition && Object.keys(table.shape_of_partition).length ? table.shape_of_partition : undefined;
    const decision = options.find(option => !partitionShapes || partitionShapes[String(option.vc_partition)] === shape);
    if (!decision) throw new Error(`No certified ${shape} decision at R${current}`);
    if (decision.resource.kind !== 'SHARED_LINK') throw new Error('Unsupported non-shared Plane D resource');
    const wires = (topology.shared_links ?? []).filter(wire => wire.src_router === current && decision.tap !== null && wire.taps[decision.tap] === decision.next_router);
    if (wires.length !== 1) throw new Error('Certified decision does not bind to exactly one shared wire');
    const wire = wires[0];
    hops.push({ key: `D:${wire.shared_link_id}`, plane, from: current, to: decision.next_router, latency: wire.latency_cycles * (decision.tap! + 1), tap: decision.tap, wire: wire.shared_link_id });
    current = decision.next_router;
  }
  return hops;
}

export function projectSharedTrace(topology: Topology, table: SharedRouteTable, configText: string, rows: InjectionRow[], shape: string) {
  const config = readNativeConfig(configText);
  if (topology.routers.length !== config.k ** 2 || topology.routers.some(router => router.coordinates.length !== 2 || router.seat_capacity !== config.c)) throw new Error('Native grid/concentration differs from the revision topology.');
  const packets: FabricPacket[] = [];
  const rejected: { row: number; reason: string }[] = [];
  for (const row of rows) {
    try {
      // Match BookSim GetIntArray resize semantics (last assignment repeats).
      const trafficClass = Number(row.trafficClass);
      if (!/^\d+$/.test(row.trafficClass) || !Number.isSafeInteger(trafficClass) || trafficClass >= config.classes) throw new Error('Unknown numeric native traffic class');
      const plane = config.classSubnet[Math.min(trafficClass, config.classSubnet.length - 1)];
      const hops = walkCertified({ topology, table, config, sourceTerminal: row.source, destinationTerminal: row.destination, plane, shape });
      packets.push({ row, hops, plane, duration: Math.max(1, hops.reduce((sum, hop) => sum + hop.latency, 0)), sourceRouter: new Map(table.terminal_to_router).get(row.source)!, destinationRouter: new Map(table.terminal_to_router).get(row.destination)! });
    } catch (error) { rejected.push({ row: row.line, reason: String(error) }); }
  }
  return { packets, rejected, config };
}

/** Different taps consume the SAME shared resource. Never split its contention into tap edges. */
export function sharedResourceLoads(packets: FabricPacket[]) {
  const loads = new Map<string, { hop: FabricHop; flits: number; packets: number; taps: Map<number, number> }>();
  for (const packet of packets) for (const hop of packet.hops) {
    const load = loads.get(hop.key) ?? { hop, flits: 0, packets: 0, taps: new Map<number, number>() };
    load.flits += packet.row.flits; load.packets++;
    if (hop.tap !== null) load.taps.set(hop.tap, (load.taps.get(hop.tap) ?? 0) + packet.row.flits);
    loads.set(hop.key, load);
  }
  return [...loads.values()].sort((a, b) => b.flits - a.flits);
}
