import type { Topology } from './gateway';
import type { ObservedFlitFate, ObservedHopEvent } from './observedHops';
import { readNativeConfig, walkCertified, type Decision, type FabricHop, type SharedRouteTable } from './sharedRoutes';

// Observed flits are checked against the CERTIFIED route set, never against one
// projected shape: the runtime chooses the shape, so either certified choice is
// legal and the point of this module is to say which one ran.
//
// Two different claims are made, and they are counted separately:
//   * ROUTE  — the router sequence the hardware recorded is a certified route.
//   * WIRE   — each recorded send entered the declared wire we think it did.
// The WIRE claim needs a certified port-to-wire map. The `routing.dump` that
// supplies one is written by the subnet-0 routing function, so a subnet-1
// (Plane C) flit can pass ROUTE and can never pass WIRE here. Reporting that as
// a mismatch would be a fabricated failure, so it is reported as unverified.
export type ObservedFlit = {
  flit: number;
  packet?: number;
  subnet: number;
  plane: number;
  sourceRouter: number;
  destinationRouter: number;
  receipts: { router: number; start: number; end: number }[];
  observedWires: (number | null)[];
  verdict: 'verified' | 'mismatch' | 'unverified' | 'local';
  wireVerified: boolean;
  shape?: string;
  expected?: string;
  reason?: string;
};
export type ObservedVerification = {
  flits: ObservedFlit[];
  verified: number;
  mismatched: number;
  unverified: number;
  local: number;
  wireVerified: number;
  shapes: { shape: string; flits: number }[];
  firstMismatch: string | null;
};

const routeLabel = (hops: FabricHop[], sourceRouter: number) =>
  [sourceRouter, ...hops.map(hop => hop.to)].map(router => `R${router}`).join(' > ');
const wireLabel = (hops: FabricHop[]) =>
  hops.map(hop => hop.wire === undefined ? hop.key : String(hop.wire)).join(' > ');

type UnionMatch =
  | { ok: true; shape: string }
  | { ok: false; reason: string };

/** Check a recorded router sequence against the certified decision UNION.
 *
 * A rank-policy artifact declares decisions and a rank per decision, but no
 * shape binding: `shape_of_partition` is absent and the partition is the hop
 * RANK, not the shape. Two decisions for the same pair can share a partition
 * (R5 -> R0 and R5 -> R9 are both rank 0), so "walk the artifact under shape
 * X" describes no legal route — and comparing against it reported a false
 * mismatch for a path the union admits.
 *
 * The obligation is therefore MEMBERSHIP, hop by hop, which is exactly what
 * the rank differential test asserts against the simulator's own dump. Each
 * recorded hop must be a certified decision from that router to the
 * destination terminal, and (on Plane D) must enter the wire the capture
 * recorded. Nothing here may invent a shape: the realized rank sequence is
 * reported as-is.
 */
function matchUnionRoute({
  decisionPairs, wireOf, observedRoute, wires, destinations, shapePolicy, partitionCount,
}: {
  decisionPairs: Map<string, Decision[]>;
  wireOf: (from: number, option: Decision) => number | null;
  observedRoute: number[];
  wires: (number | null)[];
  destinations: number[];
  shapePolicy: Record<string, string> | null;
  partitionCount: number;
}): UnionMatch {
  let failure: { reason: string; depth: number } | null = null;
  for (const destination of destinations) {
    const ranks: number[] = [];
    let problem: string | null = null;
    for (let index = 0; index < observedRoute.length - 1; index += 1) {
      const from = observedRoute[index], to = observedRoute[index + 1];
      const options = (decisionPairs.get(`${from}:${destination}`) ?? []).filter(option => option.next_router === to);
      if (!options.length) {
        const declared = [...new Set((decisionPairs.get(`${from}:${destination}`) ?? []).map(option => `R${option.next_router}`))];
        problem = `recorded ${observedRoute.map(router => `R${router}`).join(' > ')} (wires ${wires.map(wire => wire ?? '?').join(' > ')}) leaves the certified union at R${from} > R${to}; certified next routers from R${from} for terminal ${destination}: ${declared.length ? declared.join(', ') : 'none'}`;
        break;
      }
      const wired = options.find(option => wireOf(from, option) === wires[index]);
      if (!wired) {
        const certified = options.map(option => String(wireOf(from, option) ?? '?')).join(', ');
        problem = `recorded wire ${wires[index] ?? '?'} on R${from} > R${to} is not the wire the certified decision enters (certified: ${certified})`;
        break;
      }
      ranks.push(wired.vc_partition);
    }
    if (!problem) {
      const uniform = ranks.every(rank => rank === ranks[0]);
      const shape = !uniform ? 'UNION'
        : shapePolicy?.[String(ranks[0])] ?? (partitionCount > 1 ? `RANK_${ranks[0]}` : 'DETERMINISTIC');
      return { ok: true, shape };
    }
    // Without a retirement record the destination terminal is unknown, so every
    // terminal on the last router is tried. Report the divergence that got
    // furthest: it names the hop that actually left the union.
    if (!failure || ranks.length > failure.depth) failure = { reason: problem, depth: ranks.length };
  }
  return { ok: false, reason: failure?.reason ?? 'no certified decision exists for this router pair' };
}

/** Group observed events per flit and check each executed hop. */
export function verifyObserved(
  events: ObservedHopEvent[],
  topology: Topology,
  table: SharedRouteTable | null,
  configText: string,
  portWires: Map<string, { wire: number; taps: number[] }>,
  fates?: Map<number, ObservedFlitFate>,
): ObservedVerification {
  const empty: ObservedVerification = { flits: [], verified: 0, mismatched: 0, unverified: 0, local: 0, wireVerified: 0, shapes: [], firstMismatch: null };
  if (!events.length) return empty;
  const config = readNativeConfig(configText);
  const terminalsOf = new Map<number, number[]>();
  for (const [terminal, router] of table?.terminal_to_router ?? []) terminalsOf.set(router, [...(terminalsOf.get(router) ?? []), terminal]);
  const byFlit = new Map<number, ObservedHopEvent[]>();
  for (const event of events) byFlit.set(event.flit, [...(byFlit.get(event.flit) ?? []), event]);
  // A deterministic v3 route artifact carries ONE `decision` per pair and no
  // shape policy at all; only a shape-policy artifact declares
  // `shape_of_partition`. SharedFabricProjection already treats that case as
  // the neutral 'DETERMINISTIC' shape. Do the same here: an empty shape list
  // would otherwise leave zero candidates and report every subnet-0 flit as
  // 'no certified decision exists for this router pair' — a fabricated failure
  // against a route the artifact does certify.
  const declaredShapes = [...new Set(Object.values(table?.shape_of_partition ?? {}))];
  const shapes = declaredShapes.length ? declaredShapes : ['DETERMINISTIC'];
  // A shape binding is what makes "walk this artifact under shape X" a legal
  // question. Without one (rank policy), only membership can be checked.
  const shapePolicy = declaredShapes.length ? (table!.shape_of_partition as Record<string, string>) : null;
  const partitionCount = Object.keys(table?.partition_to_vcs ?? {}).length;
  const decisionPairs = new Map<string, Decision[]>();
  for (const [src, dst, options] of table?.choices ?? []) decisionPairs.set(`${src}:${dst}`, options);
  for (const [src, dst, option] of table?.decisions ?? []) decisionPairs.set(`${src}:${dst}`, [...(decisionPairs.get(`${src}:${dst}`) ?? []), option]);
  const wireOf = (from: number, option: Decision): number | null => {
    if (option.tap === null || option.tap === undefined) return null;
    const wire = (topology.shared_links ?? []).find(link => link.src_router === from && link.taps[option.tap!] === option.next_router);
    return wire ? wire.shared_link_id : null;
  };
  const flits: ObservedFlit[] = [];
  for (const [flit, rows] of [...byFlit].sort((a, b) => a[0] - b[0])) {
    const ordered = [...rows].sort((a, b) => a.cycle - b.cycle);
    const subnets = [...new Set(ordered.map(row => row.subnet))];
    const plane = ordered[0].subnet === 0 ? 0 : 1;
    const base = { flit, subnet: ordered[0].subnet, plane, wireVerified: false, observedWires: [] as (number | null)[] };
    const raw = ordered.filter(row => row.kind === 'receive').map(row => ({ router: row.router, start: row.cycle, end: row.cycle }));
    const local = (reason: string, sourceRouter = -1, destinationRouter = -1): ObservedFlit =>
      ({ ...base, receipts: raw, sourceRouter, destinationRouter, verdict: 'unverified', reason });
    if (subnets.length > 1) { flits.push(local('one flit id appears on more than one native subnet')); continue; }
    // A flit is received again at every router it waits at, and a packet's flits
    // are logged independently, so consecutive receipts at one router are ONE
    // visit rather than a hop.
    const visits: { router: number; start: number; end: number }[] = [];
    for (const receipt of raw) {
      const last = visits[visits.length - 1];
      if (last && last.router === receipt.router) last.end = receipt.start;
      else visits.push({ ...receipt });
    }
    if (!visits.length) { flits.push(local('no router receipt was recorded for this flit id')); continue; }
    const sourceRouter = visits[0].router, destinationRouter = visits[visits.length - 1].router;
    const fate = fates?.get(flit);
    const packet = fate ? { packet: fate.packet } : {};
    // One receipt is ambiguous on its own: a locally delivered flit and a capture
    // that lost the rest of the path look identical. The retirement record
    // separates them, so use it instead of guessing.
    if (visits.length === 1) {
      if (fate && fate.destinationTerminal >= 0 && table) {
        let local: FabricHop[] | null = null;
        try { local = walkCertified({ topology, table, config, sourceTerminal: fate.sourceTerminal, destinationTerminal: fate.destinationTerminal, plane, shape: plane === 1 ? 'XY' : shapes[0] }); } catch { local = null; }
        if (local && local.length === 0 && fate.hops === 1 && terminalsOf.get(sourceRouter)?.includes(fate.sourceTerminal)) {
          flits.push({ ...base, ...packet, receipts: visits, sourceRouter, destinationRouter, verdict: 'local', wireVerified: false, shape: plane === 1 ? 'XY' : undefined });
          continue;
        }
      }
      flits.push({ ...base, ...packet, receipts: visits, sourceRouter, destinationRouter, verdict: 'unverified', reason: fate ? 'one router receipt and the recorded delivery does not explain it as a local flit' : 'only one router receipt: a local flit and a truncated capture are indistinguishable' });
      continue;
    }
    const wires: (number | null)[] = [];
    let problem: string | null = null;
    for (let index = 0; index < visits.length - 1; index += 1) {
      const from = visits[index], to = visits[index + 1];
      const send = ordered.find(row => row.kind === 'send' && row.router === from.router && row.cycle >= from.end && row.cycle <= to.start);
      if (!send) { problem = `no send event at R${from.router} between cycle ${from.end} and ${to.start}`; break; }
      // Subnet 1 has no certified port-to-wire map here, so its wire identity is
      // unknown rather than wrong.
      if (plane !== 0) { wires.push(null); continue; }
      const wire = portWires.get(`${from.router}:${send.port}`);
      if (!wire) { problem = `R${from.router} port ${send.port} has no verified wire binding`; wires.push(null); break; }
      if (!wire.taps.includes(to.router)) { problem = `wire ${wire.wire} from R${from.router} has no tap landing at R${to.router}`; wires.push(wire.wire); break; }
      wires.push(wire.wire);
    }
    if (problem || !table) {
      flits.push({ ...base, receipts: visits, observedWires: wires, sourceRouter, destinationRouter, verdict: 'unverified', reason: problem ?? 'no certified routing table is available in this bundle' });
      continue;
    }
    // The retirement record names the exact endpoints, so the certified route is
    // looked up for that pair instead of every terminal on both routers.
    const endpoints = fate && fate.destinationTerminal >= 0
      ? [[fate.sourceTerminal, fate.destinationTerminal] as [number, number]]
      : (terminalsOf.get(sourceRouter) ?? []).flatMap(source => (terminalsOf.get(destinationRouter) ?? []).map(destination => [source, destination] as [number, number]));
    const candidates: { shape: string; hops: FabricHop[] }[] = [];
    {
      for (const [source, destination] of endpoints) {
        const options = plane === 1 ? ['XY'] : shapes;
        for (const shape of options) {
          try { candidates.push({ shape, hops: walkCertified({ topology, table, config, sourceTerminal: source, destinationTerminal: destination, plane, shape }) }); } catch { /* an unrealizable candidate is simply not a match */ }
        }
      }
    }
    const observedRoute = visits.map(visit => visit.router);
    const hopCount = fate ? fate.hops : visits.length;
    // No shape binding: the runtime may take ANY certified decision at each
    // router, so the claim is membership, not equality with one shape's walk.
    if (table && !shapePolicy && plane === 0) {
      const union = matchUnionRoute({
        decisionPairs, wireOf, observedRoute, wires,
        destinations: [...new Set(endpoints.map(([, destination]) => destination))],
        shapePolicy, partitionCount,
      });
      if (union.ok && hopCount === visits.length) {
        flits.push({ ...base, ...packet, receipts: visits, observedWires: wires, sourceRouter, destinationRouter, verdict: 'verified', wireVerified: true, shape: union.shape });
        continue;
      }
      flits.push({
        ...base, ...packet, receipts: visits, observedWires: wires, sourceRouter, destinationRouter, verdict: 'mismatch',
        shape: union.ok ? union.shape : undefined,
        expected: union.ok ? `${observedRoute.map(router => `R${router}`).join(' > ')} (${hopCount} recorded hops)` : `a certified hop out of R${observedRoute[0]}`,
        reason: union.ok
          ? `the native hop counter reports ${hopCount} hops but ${visits.length} router receipts were recorded for a route of ${observedRoute.length - 1}`
          : union.reason,
      });
      continue;
    }
    const routeMatches = (hops: FabricHop[]) => {
      const route = [sourceRouter, ...hops.map(hop => hop.to)];
      return route.length === observedRoute.length && route.every((router, index) => router === observedRoute[index]);
    };
    const wireMatches = (hops: FabricHop[]) => plane !== 0
      ? true
      : hops.length === wires.length && hops.every((hop, index) => hop.wire === wires[index]);
    const matched = candidates.find(candidate => routeMatches(candidate.hops) && wireMatches(candidate.hops));
    // The native hop counter counts the eject as a hop, so a matched route must
    // also agree with it; disagreement is a real inconsistency in the capture.
    if (matched && hopCount === visits.length) {
      flits.push({ ...base, ...packet, receipts: visits, observedWires: wires, sourceRouter, destinationRouter, verdict: 'verified', wireVerified: plane === 0, shape: matched.shape });
      continue;
    }
    if (matched) {
      flits.push({ ...base, ...packet, receipts: visits, observedWires: wires, sourceRouter, destinationRouter, verdict: 'mismatch', shape: matched.shape, expected: `${routeLabel(matched.hops, sourceRouter)} (${hopCount} recorded hops)`, reason: `the native hop counter reports ${hopCount} hops but ${visits.length} router receipts were recorded for a route of ${matched.hops.length}` });
      continue;
    }
    // Report the first place the recorded route leaves the certified set.
    const sameRoute = candidates.find(candidate => routeMatches(candidate.hops));
    const expected = sameRoute ?? candidates[0];
    flits.push({
      ...base, ...packet, receipts: visits, observedWires: wires, sourceRouter, destinationRouter, verdict: 'mismatch',
      expected: expected ? routeLabel(expected.hops, sourceRouter) : 'no certified route',
      reason: expected
        ? `recorded ${observedRoute.map(router => `R${router}`).join(' > ')} (wires ${wires.map(wire => wire ?? '?').join(' > ')}); certified ${routeLabel(expected.hops, sourceRouter)} (wires ${wireLabel(expected.hops)})`
        : 'no certified decision exists for this router pair',
    });
  }
  const count = (verdict: ObservedFlit['verdict']) => flits.filter(flit => flit.verdict === verdict).length;
  const shapeCounts = new Map<string, number>();
  for (const flit of flits) if (flit.shape) shapeCounts.set(flit.shape, (shapeCounts.get(flit.shape) ?? 0) + 1);
  const firstMismatch = flits.find(flit => flit.verdict === 'mismatch');
  return {
    flits,
    verified: count('verified'), mismatched: count('mismatch'), unverified: count('unverified'), local: count('local'),
    wireVerified: flits.filter(flit => flit.wireVerified).length,
    shapes: [...shapeCounts].map(([shape, value]) => ({ shape, flits: value })),
    firstMismatch: firstMismatch ? `flit ${firstMismatch.flit}: expected ${firstMismatch.expected}; ${firstMismatch.reason}` : null,
  };
}
