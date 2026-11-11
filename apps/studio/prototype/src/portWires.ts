import { useEffect, useState } from 'react';
import { gatewayReason, type Topology } from './gateway';
import { fetchVerifiedArtifact } from './RawArtifacts';
import type { LoadedRun } from './project';

// BookSim's measured channel id packs subnet, source router and the router's
// LOCAL output-port index. For SROTA that index is not a compass direction and
// not the topology artifact's src_port: it is the driver's port, and one port
// carries every tap of one shared wire. The order is a property of the native
// builder, so it is read from the executed routing dump instead of assumed.
export type WirePort = { wire: number; taps: number[] };
export type PortWireMap = {
  ports: Map<string, WirePort>;
  locals: Map<string, number>;
  problems: string[];
};

type DumpRow = { src: number; dst: number; next: number; port: number; drop: number };

export function parseRoutingDump(text: string): DumpRow[] {
  const rows: DumpRow[] = [];
  const KEYS = ['src_router', 'dst_node', 'next_router', 'port', 'drop', 'vc_start', 'vc_end'] as const;
  for (const [index, raw] of text.split(/\r?\n/).entries()) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const fields = line.split(/\s+/);
    if (fields.length !== 14) throw new Error(`Dump line ${index + 1}: expected 14 fields, got ${fields.length}.`);
    const values = new Map<string, number>();
    for (let position = 0; position < 7; position += 1) {
      const key = fields[position * 2], text = fields[position * 2 + 1];
      if (key !== KEYS[position]) throw new Error(`Dump line ${index + 1}: expected ${KEYS[position]} at field ${position * 2}, found ${key}.`);
      // drop = -1 is the native marker for a local eject; every other field is a count.
      const minimum = key === 'drop' ? -1 : 0;
      if (!/^-?\d+$/.test(text) || !Number.isSafeInteger(Number(text)) || Number(text) < minimum) throw new Error(`Dump line ${index + 1}: ${key} is not an integer >= ${minimum}.`);
      values.set(key, Number(text));
    }
    rows.push({ src: values.get('src_router')!, dst: values.get('dst_node')!, next: values.get('next_router')!, port: values.get('port')!, drop: values.get('drop')! });
  }
  return rows;
}

/** Build driver-port -> shared wire, or refuse. A wire is bound only when every
 *  landing the executed dump reveals on that port is a tap of exactly one
 *  declared wire, every wire is driven by exactly one port, and the local
 *  terminals account for the remaining ports. */
export function buildPortWireMap(topology: Topology, rows: DumpRow[]): PortWireMap {
  const problems: string[] = [];
  const ports = new Map<string, WirePort>();
  const locals = new Map<string, number>();
  const routers = new Set(topology.routers.map(router => router.router_id));
  const capacity = new Map(topology.routers.map(router => [router.router_id, router.seat_capacity]));
  if (!rows.length) return { ports, locals, problems: ['The routing dump carries no executed rows.'] };
  const byPort = new Map<string, DumpRow[]>();
  for (const row of rows) {
    if (!routers.has(row.src) || !routers.has(row.next)) { problems.push(`Dump names router ${row.src} or ${row.next}, which the topology does not declare.`); continue; }
    const key = `${row.src}:${row.port}`;
    byPort.set(key, [...(byPort.get(key) ?? []), row]);
  }
  const wired = new Map<number, string>();
  for (const [key, group] of byPort) {
    const local = group.every(row => row.drop < 0);
    if (local) {
      if (group.some(row => row.next !== group[0].src)) { problems.push(`Port ${key} ejects to router ${group.find(row => row.next !== group[0].src)!.next} but is reported as local.`); continue; }
      const terminal = Number(key.split(':')[1]);
      if (terminal >= (capacity.get(group[0].src) ?? 0)) { problems.push(`Port ${key} is local but exceeds the declared seat capacity.`); continue; }
      locals.set(key, terminal);
      continue;
    }
    const candidates = (topology.shared_links ?? []).filter(wire => wire.src_router === group[0].src && group.every(row => row.drop < wire.taps.length && wire.taps[row.drop] === row.next));
    if (candidates.length !== 1) { problems.push(`Port ${key} lands on ${candidates.length} declared wires; expected exactly one.`); continue; }
    const wire = candidates[0];
    if (wired.has(wire.shared_link_id)) { problems.push(`Wire ${wire.shared_link_id} is driven by both port ${wired.get(wire.shared_link_id)} and ${key}.`); continue; }
    wired.set(wire.shared_link_id, key);
    ports.set(key, { wire: wire.shared_link_id, taps: wire.taps });
  }
  for (const router of topology.routers) {
    const count = [...locals.keys()].filter(key => key.startsWith(`${router.router_id}:`)).length;
    if (count !== router.seat_capacity) problems.push(`Router ${router.router_id} reports ${count} local eject ports; the topology declares ${router.seat_capacity} seats.`);
  }
  const missing = (topology.shared_links ?? []).filter(wire => !wired.has(wire.shared_link_id));
  if (missing.length) problems.push(`${missing.length} declared wire(s) are never driven by a dumped port: ${missing.slice(0, 6).map(wire => wire.shared_link_id).join(', ')}.`);
  return { ports, locals, problems };
}

export function portWiresUsable(map: PortWireMap | null): map is PortWireMap {
  return !!map && map.problems.length === 0 && map.ports.size > 0;
}

type WireState = { phase: 'idle' | 'loading' | 'ready' | 'absent' | 'invalid'; map: PortWireMap | null; reason?: string };
const cache = new Map<string, Promise<{ map: PortWireMap; reason?: string } | null>>();

function load(run: LoadedRun, topology: Topology) {
  const files = run.artifacts?.bundle?.files ?? {};
  const path = Object.keys(files).find(name => name.endsWith('/routing.dump') || name === 'routing.dump');
  if (!path) return Promise.resolve(null);
  const key = `${run.detail.run_id}|${path}`;
  const cached = cache.get(key);
  if (cached) return cached;
  const pending = fetchVerifiedArtifact(run.detail.run_id, path, files[path])
    .then(bytes => {
      const rows = parseRoutingDump(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
      return { map: buildPortWireMap(topology, rows) };
    })
    .catch(error => { cache.delete(key); throw error; });
  cache.set(key, pending);
  return pending;
}

/** Verified driver-port -> wire join for this run, or an explicit refusal. */
export function usePortWires(run: LoadedRun, topology: Topology | null): WireState {
  const [state, setState] = useState<WireState>({ phase: 'idle', map: null });
  useEffect(() => {
    let live = true;
    setState({ phase: 'loading', map: null });
    if (!topology || !(topology.shared_links ?? []).length) { setState({ phase: 'absent', map: null, reason: 'This revision declares no shared wires, so the port-to-wire join does not apply.' }); return; }
    load(run, topology)
      .then(result => { if (!live) return; setState(!result ? { phase: 'absent', map: null, reason: 'This bundle carries no executed routing dump, so ports are not joined to wires.' } : result.map.problems.length ? { phase: 'invalid', map: result.map, reason: result.map.problems.join(' ') } : { phase: 'ready', map: result.map }); })
      .catch(error => { if (live) setState({ phase: 'invalid', map: null, reason: gatewayReason(error) }); });
    return () => { live = false; };
  }, [run.detail.run_id, topology]);
  return state;
}
