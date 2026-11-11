// Spec-grounded static analysis for the declared agent map and NoC controls.
//
// These checks are deliberately separate from the compiler's own proof. The
// compiler re-derives routing, VC assignment, attachment and address decode
// when it compiles; this module explains WHAT it will be asked to prove and
// which declared controls have no RTL representation yet. A PASS here is not
// a substitute for a compiled certificate.

import {
  addressCoverage, agentsFromRequest, designDocument, targetCoverage, validateWindows, windowsFromRequest,
  type AddressCoverage, type AddressIssue, type AddressWindow, type AgentGroup, type TargetCoverage,
} from './agentMap';
import type { CompileResult, Topology } from './gateway';

export type CheckStatus = 'PASS' | 'WARN' | 'FAIL' | 'N/A';
export type CheckGroup = 'address' | 'agents' | 'routing' | 'topology' | 'certificate' | 'rtl';

export type AnalysisCheck = {
  id: string;
  group: CheckGroup;
  title: string;
  status: CheckStatus;
  detail: string;
  citation: string;
  evidence?: string;
};

export type CdgResult = {
  nodes: string[];
  edges: [string, string][];
  cycle: string[] | null;
  acyclic: boolean;
  model: string;
};

export type AddressDecodeRow = {
  name?: string;
  base?: number | string;
  size?: number | string;
  target_agent_kind?: string;
  target_agent_instance?: number;
  target_endpoint_id?: number;
  legacy_target_agent_group?: number;
};

export type AddressDecodeGroup = {
  available?: boolean;
  rows?: AddressDecodeRow[];
  address_transform?: string;
  unmatched_address_policy?: string;
};

type CertificateClaim = {
  obligation?: string;
  claim?: string;
  status?: string;
  certificate_status?: string;
  method?: string;
  meaning?: string;
  scope?: string;
};

export type RtlReachRow = {
  control: string;
  declared: string;
  compile: string;
  preview: string;
  status: 'reaches-preview' | 'compiled-only' | 'refused' | 'not-declared';
  note: string;
  citation: string;
};

const record = (value: unknown): Record<string, any> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {};

const stringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.map(item => String(item)) : [];

const srotaIntent = (request: unknown): Record<string, any> | null => {
  const topology = record(record(designDocument(request)).topology);
  return topology.kind === 'srota' ? topology : null;
};

export function decodeGroup(compileResult: CompileResult | null): AddressDecodeGroup | undefined {
  return record(record(compileResult?.groups).address_decode) as AddressDecodeGroup;
}

export function srotaCdg(request: unknown): CdgResult {
  const intent = srotaIntent(request);
  if (!intent) {
    return { nodes: [], edges: [], cycle: null, acyclic: true, model: 'Not a Srota topology; the Srota O1TURN abstraction does not apply.' };
  }
  const shapes = new Set(stringList(intent.path_shapes));
  const policy = String(intent.vc_policy ?? 'none');
  const side = Math.max(2, Number(intent.side_length ?? 4) || 4);
  const nodes: string[] = [];
  const edges: [string, string][] = [];

  // Valiant turns twice: leg 1 is row-first, then the intermediate re-injects
  // row-first, adding a column→row edge. Under a non-rank policy that closes a
  // cycle; the compiler refuses it. Under rank, the second leg has ranks 2/3,
  // so the abstraction defers below.
  if (shapes.has('valiant') && policy !== 'rank') {
    const nodes: string[] = [];
    const edges: [string, string][] = [];
    for (let index = 0; index < side; index += 1) nodes.push(`row[${index}]`, `col[${index}]`);
    for (let row = 0; row < side; row += 1) {
      for (let col = 0; col < side; col += 1) {
        edges.push([`row[${row}]`, `col[${col}]`]);
        edges.push([`col[${col}]`, `row[${row}]`]);
      }
    }
    return {
      nodes, edges, cycle: ['row[0]', 'col[0]', 'row[0]'], acyclic: false,
      model: `Valiant turns twice; under vc_policy=${policy} its second leg adds column→row and the compiler refuses it.`,
    };
  }

  // The compiler's rank policy separates direct shapes by hop rank, and a
  // Valiant second leg by ranks 2/3. Reconstructing that partition here would
  // be a second implementation of the proof, so this abstraction stops at the
  // policy boundary and defers to the compiler's concrete CDG.
  if (policy === 'rank') {
    return {
      nodes: [], edges: [], cycle: null, acyclic: true,
      model: 'Rank policy: the compiler proves the concrete (resource, VC) graph; this abstract row/column graph would not be the same claim.',
    };
  }

  // The `shape` policy gives row-first and column-first disjoint VC sets, so
  // the two directions live in different graphs. Each partition still uses
  // both physical dimensions; only the VC set differs.
  if (policy === 'shape') {
    for (let index = 0; index < side; index += 1) {
      nodes.push(`row[${index}]@vc0`, `col[${index}]@vc0`, `row[${index}]@vc1`, `col[${index}]@vc1`);
    }
    if (shapes.has('row') || shapes.has('valiant')) {
      for (let row = 0; row < side; row += 1) {
        for (let col = 0; col < side; col += 1) edges.push([`row[${row}]@vc0`, `col[${col}]@vc0`]);
      }
    }
    if (shapes.has('column')) {
      for (let col = 0; col < side; col += 1) {
        for (let row = 0; row < side; row += 1) edges.push([`col[${col}]@vc1`, `row[${row}]@vc1`]);
      }
    }
    return { nodes, edges, cycle: null, acyclic: true, model: `Shape policy: disjoint VC sets (row-first=vc0, column-first=vc1) at k=${side}.` };
  }

  // `oneshape` separates shapes in TIME, which this graph cannot represent.
  // The shape check records that the compiler refuses it for both direct
  // shapes; the abstract graph must not claim a concurrent cycle it cannot
  // observe.
  if (policy === 'oneshape' && shapes.has('row') && shapes.has('column')) {
    return {
      nodes: [], edges: [], cycle: null, acyclic: true,
      model: 'One-shape-per-epoch: row-first and column-first are separated in time. This abstraction cannot represent temporal separation; the compiler refuses oneshape for both direct shapes.',
    };
  }

  // `none` (or a single shape) shares one VC set in this abstraction.
  for (let index = 0; index < side; index += 1) nodes.push(`row[${index}]`, `col[${index}]`);
  if (shapes.has('row') || shapes.has('valiant')) {
    for (let row = 0; row < side; row += 1) {
      for (let col = 0; col < side; col += 1) edges.push([`row[${row}]`, `col[${col}]`]);
    }
  }
  if (shapes.has('column')) {
    for (let col = 0; col < side; col += 1) {
      for (let row = 0; row < side; row += 1) edges.push([`col[${col}]`, `row[${row}]`]);
    }
  }
  const cycle = shapes.has('column') && (shapes.has('row') || shapes.has('valiant'))
    ? ['row[0]', 'col[0]', 'row[0]']
    : null;
  return {
    nodes, edges, cycle, acyclic: cycle === null,
    model: `Shared VC set at k=${side}; row-first contributes row→column, column-first contributes column→row.`,
  };
}

export function srotaShapeChecks(request: unknown): AnalysisCheck[] {
  const intent = srotaIntent(request);
  if (!intent) return [];
  const shapes = stringList(intent.path_shapes);
  const shapeSet = new Set(shapes);
  const policy = String(intent.vc_policy ?? 'none');
  const mecsRow = intent.mecs_row === true;
  const mecsCol = intent.mecs_col === true;
  const islands = Array.isArray(intent.island_columns) ? intent.island_columns.map(Number).filter(Number.isFinite) : [];
  const checks: AnalysisCheck[] = [];
  const cite = 'ROUTE-001 §3.4, §4.5, §5.4; RT-R7/RT-R8';

  if (policy === 'rank') {
    checks.push({
      id: 'srota-rank-express', group: 'routing', title: 'Rank policy has the full express layer',
      status: mecsRow && mecsCol ? 'PASS' : 'FAIL',
      detail: mecsRow && mecsCol
        ? 'The rank + Valiant envelope requires both MECS directions; both are enabled.'
        : 'The rank policy requires mecs_row and mecs_col for every shape set, not only Valiant. A nearest-neighbour dimension has no tap, so the rank walk does not describe it.',
      citation: 'ROUTE-001 §3.4.1; routing.py rank branch',
    });
  }

  checks.push({
    id: 'srota-shapes-declared', group: 'routing', title: 'At least one path shape is declared',
    status: shapes.length ? 'PASS' : 'FAIL',
    detail: shapes.length ? `Declared: ${shapes.join(', ')}.` : 'No path shape is declared, so the FIU has no route to select.',
    citation: cite,
  });

  if (shapeSet.has('valiant')) {
    const rankOk = policy === 'rank';
    const mecsOk = mecsRow && mecsCol;
    checks.push({
      id: 'srota-valiant-policy', group: 'routing', title: 'Valiant uses the hop-rank VC policy',
      status: rankOk ? 'PASS' : 'FAIL',
      detail: rankOk
        ? 'Rank policy is the only policy the derived SROTA route accepts with Valiant; the second leg occupies ranks 2/3.'
        : `Valiant is declared under vc_policy=${policy}. The compiler refuses it: 'shape' and 'oneshape' exit for Valiant, and the second turn needs its own rank set.`,
      citation: cite,
    });
    checks.push({
      id: 'srota-valiant-mecs', group: 'routing', title: 'Valiant has the full express layer',
      status: mecsOk ? 'PASS' : 'FAIL',
      detail: mecsOk ? 'Row and column MECS are both enabled; the rank walk has taps in both dimensions.' : 'The rank + Valiant envelope requires mecs_row and mecs_col; a nearest-neighbour dimension has no tap.',
      citation: 'ROUTE-001 §3.4.1, §5.4; VC-002 §4.1.3',
    });
  }

  if (shapeSet.has('row') && shapeSet.has('column')) {
    const separated = policy === 'shape' || policy === 'rank';
    checks.push({
      id: 'srota-direct-separation', group: 'routing', title: 'The two direct shapes are VC-separated',
      status: separated ? 'PASS' : 'FAIL',
      detail: separated
        ? `vc_policy=${policy} separates the direct shapes (${policy === 'shape' ? 'one VC set per shape' : 'hop-rank sets 0/1'}), so the union is not one graph.`
        : `Both direct shapes share one VC set under vc_policy=${policy}. Row-first adds row→column and column-first adds column→row; their union closes the RT-R7 two-node cycle.`,
      citation: 'ROUTE-001 §4.5.1, §4.5.3; VC-002 §4.1.2',
    });
    checks.push({
      id: 'srota-derived-vcs', group: 'routing', title: 'Derived VC count matches the separation',
      status: separated ? 'PASS' : 'WARN',
      detail: separated
        ? (policy === 'shape' ? 'The shape policy derives 2 VCs; each direct shape owns one contiguous set.' : 'The rank policy derives one VC per rank; direct shapes share ranks 0/1.')
        : 'With no separation the derived route path refuses the pair, so no VC count is certified.',
      citation: 'VC-002 §3.2, §4.1.3; ROUTE-001 §7.1',
    });
  } else if (shapeSet.size === 1 && shapeSet.has('row')) {
    checks.push({
      id: 'srota-row-only', group: 'routing', title: 'Single row-first shape is the certified baseline',
      status: 'PASS',
      detail: `Only row-first is declared. One turn direction exists, so the CDG is acyclic. ${policy === 'rank' ? 'The rank policy derives its rank partitions.' : `vc_policy=${policy} derives 1 VC.`}`,
      citation: 'ROUTE-001 §3.1, §4.3; presets.py srota32',
    });
  } else if (shapeSet.size === 1 && shapeSet.has('column')) {
    const rankOk = policy === 'rank' && mecsRow && mecsCol;
    checks.push({
      id: 'srota-column-only', group: 'routing', title: 'Column-only has a derived route',
      status: rankOk ? 'PASS' : 'FAIL',
      detail: rankOk
        ? 'The rank branch adds row-first and covers this set; the compiler\'s concrete rank proof is authoritative.'
        : 'Column-only is acyclic in the doc, but the compiler\'s derived SROTA shared-resource rule covers single row-first and the row+column pair only. It refuses this set rather than routing it as if the row-first proof covered it.',
      citation: 'ROUTE-001 §3.3; routing.py _derive_shared_resource_route',
    });
  } else if (shapes.length && !shapeSet.has('valiant')) {
    checks.push({
      id: 'srota-derived-rule', group: 'routing', title: 'Declared shape set has a derived route',
      status: 'FAIL',
      detail: `The derived SROTA rule covers {row} and {row,column} (with shape or rank) and Valiant under rank. It does not cover {${shapes.join(',')}}.`,
      citation: 'routing.py _derive_shared_resource_route',
    });
  }

  if (islands.length) {
    const columnOk = shapeSet.has('column');
    const mecsOk = mecsRow && mecsCol;
    const policyOk = policy === 'shape' || policy === 'rank';
    checks.push({
      id: 'srota-island-shape', group: 'routing', title: 'Island-bound flows have column-first',
      status: columnOk && mecsOk && policyOk ? 'PASS' : 'FAIL',
      detail: columnOk && mecsOk && policyOk
        ? `${islands.length} island column(s) declared; column-first is enabled, both MECS directions exist and vc_policy=${policy} separates the shapes, so the I-ISL route rule is expressible.`
        : `Island columns ${islands.join(', ')} need column-first, both MECS directions and a shape/rank VC policy (srota_isl_route=colfirst); the declared shapes/policy do not provide them.`,
      citation: 'TOPO-003 §4.1, §4.4; ROUTE-001 §13.1',
    });
  }

  if (policy === 'oneshape' && shapeSet.has('row') && shapeSet.has('column')) {
    checks.push({
      id: 'srota-oneshape', group: 'routing', title: 'One-shape-per-epoch is not the certified pair',
      status: 'WARN',
      detail: 'The document records one-shape-per-epoch as the cheapest RT-R7 resolution, but the current derived route path does not certify `oneshape` for both direct shapes. It refuses the pair; use `shape` or `rank`.',
      citation: 'ROUTE-001 §4.5.3 option 1; routing.py',
    });
  }

  return checks;
}

export type PortReading = {
  label: string;
  meshStage: number;
  expressStage: number;
  ports: number;
  crosspoints: number;
  muxBits: number;
};

export function portBudgetReadings(request: unknown): PortReading[] {
  const intent = srotaIntent(request);
  if (!intent) return [];
  const concentration = Number(intent.concentration ?? 1);
  const mecsRow = intent.mecs_row === true;
  const mecsCol = intent.mecs_col === true;
  const express = (mecsRow ? 2 : 0) + (mecsCol ? 2 : 0);
  const make = (label: string, meshStage: number, expressStage: number): PortReading => {
    const ports = meshStage + expressStage;
    return { label, meshStage, expressStage, ports, crosspoints: ports * ports, muxBits: ports * ports * 512 };
  };
  return [
    make('one inject + one eject per router', 2 + 4, express),
    make(`${concentration} inject + ${concentration} eject (per tile)`, 2 * concentration + 4, express),
    make(`${concentration} inject + ${concentration} eject, MECS shares mesh ports`, 2 * concentration + 4, 0),
  ];
}

export function portBudgetChecks(request: unknown): AnalysisCheck[] {
  const intent = srotaIntent(request);
  if (!intent) return [];
  const side = Number(intent.side_length ?? 0);
  const concentration = Number(intent.concentration ?? 1);
  const mecsRow = intent.mecs_row === true;
  const mecsCol = intent.mecs_col === true;
  const readings = portBudgetReadings(request);
  const distinct = new Set(readings.map(reading => reading.ports));
  const meshOverLimit = 2 * concentration + 4 > 6;
  const checks: AnalysisCheck[] = [{
    id: 'port-budget', group: 'topology', title: 'Port budget reconciles with the ≤6-port stage split',
    status: meshOverLimit || distinct.size > 1 ? 'WARN' : 'PASS',
    detail: `k=${side}, c=${concentration}, MECS row=${mecsRow ? 'on' : 'off'}, column=${mecsCol ? 'on' : 'off'}. Readings: ${readings.map(reading => `${reading.label} → mesh ${reading.meshStage}, express ${reading.expressStage}, P=${reading.ports}`).join('; ')}. The documented reference fixes P=12. The mesh stage is ≤6 ports only if the local side is at most 2 ports; at c=${concentration} the per-tile local side alone is ${2 * concentration}.`,
    citation: 'VC-002 §4.1.3, §8; ROUTE-001 §7.1; VC-R5',
    evidence: `crosspoints at P=12: 144 · mux bits at 512b: ${(144 * 512).toLocaleString()}`,
  }];
  if (distinct.size > 1) {
    checks.push({
      id: 'port-budget-open', group: 'topology', title: 'VC-R5 is still open for this configuration',
      status: 'WARN',
      detail: `The readings disagree (${readings.map(reading => reading.ports).join(' / ')}). VC_PORT_COUNT, VC_STAGE_SPLIT, every 6-wide allocator signal and the P×P crossbar all change together once the enumeration is decided. The analysis cannot pick one for you.`,
      citation: 'VC-002 §16 VC-R5; ROUTE-001 §8.3, §8.4.1',
    });
  }
  return checks;
}

export function reachabilityChecks(topology: Topology | null): AnalysisCheck[] {
  if (!topology) return [];
  const routers = topology.routers.map(router => router.router_id);
  const adjacency = new Map<number, number[]>(routers.map(id => [id, []]));
  for (const channel of topology.channels) {
    adjacency.get(channel.src_router)?.push(channel.dst_router);
  }
  // MECS express channels are shared links: one driver, passive taps. A tap is
  // a reachable router even though there is no point-to-point channel object.
  for (const link of topology.shared_links ?? []) {
    for (const tap of link.taps) {
      adjacency.get(link.src_router)?.push(tap);
    }
  }
  // The return graph is derived from the declared direction, never by
  // assuming a shared link is reciprocal.
  const reverse = new Map<number, number[]>(routers.map(id => [id, []]));
  for (const [src, targets] of adjacency) {
    for (const dst of targets) reverse.get(dst)?.push(src);
  }
  const reach = (start: number, graph: Map<number, number[]>): Set<number> => {
    const seen = new Set<number>([start]);
    const queue = [start];
    while (queue.length) {
      const current = queue.shift() as number;
      for (const next of graph.get(current) ?? []) {
        if (!seen.has(next)) { seen.add(next); queue.push(next); }
      }
    }
    return seen;
  };
  const forward = routers.length ? reach(routers[0], adjacency) : new Set<number>();
  const backward = routers.length ? reach(routers[0], reverse) : new Set<number>();
  const unreachable = routers.filter(id => !forward.has(id));
  const cannotReturn = routers.filter(id => !backward.has(id));
  const checks: AnalysisCheck[] = [{
    id: 'topology-strong', group: 'topology', title: 'Every router is strongly connected',
    status: !routers.length ? 'N/A' : unreachable.length || cannotReturn.length ? 'FAIL' : 'PASS',
    detail: !routers.length
      ? 'No materialized routers are declared.'
      : unreachable.length || cannotReturn.length
        ? `${unreachable.length} router(s) are not reachable from R${routers[0]}; ${cannotReturn.length} cannot reach R${routers[0]}. Example: ${[...new Set([...unreachable, ...cannotReturn])].slice(0, 6).map(id => `R${id}`).join(', ')}.`
        : `${routers.length} routers reach and return from R${routers[0]}.`,
    citation: 'TOPO-003 §10; ROUTE-001 §4.4',
  }];
  const byPair = new Map<string, { width: number; latency: number }[]>();
  for (const channel of topology.channels) {
    const key = `${channel.src_router}:${channel.dst_router}`;
    const list = byPair.get(key) ?? [];
    list.push({ width: channel.width_bits, latency: channel.latency_cycles });
    byPair.set(key, list);
  }
  const unpaired = topology.channels.filter(channel => {
    const backs = byPair.get(`${channel.dst_router}:${channel.src_router}`) ?? [];
    return !backs.some(back => back.width === channel.width_bits && back.latency === channel.latency_cycles);
  });
  checks.push({
    id: 'topology-reciprocal', group: 'topology', title: 'Declared channels have matching return paths',
    status: topology.channels.length === 0 ? 'N/A' : unpaired.length ? 'WARN' : 'PASS',
    detail: topology.channels.length === 0
      ? (topology.shared_links?.length ? `No point-to-point channels; ${topology.shared_links.length} shared link(s) carry the fabric. Reciprocity is not the applicable test; strong connectivity above includes every tap.` : 'No channels are declared.')
      : unpaired.length
        ? `${unpaired.length} of ${topology.channels.length} channels have no return channel with the same width and latency. The preview emitter refuses a non-reciprocal graph.`
        : `${topology.channels.length} channels are reciprocally paired with equal width and latency.`,
    citation: 'TOPO-003 §7.4; rtl_export.py reciprocal-channel gate',
  });
  const sharedLinks = topology.shared_links ?? [];
  const routerIds = new Set(routers);
  const invalidTaps = sharedLinks.flatMap(link => link.taps.filter(tap => !routerIds.has(tap)).map(tap => `link ${link.shared_link_id} → R${tap}`));
  checks.push({
    id: 'topology-shared-taps', group: 'topology', title: 'Every shared-link tap names a declared router',
    status: sharedLinks.length === 0 ? 'N/A' : invalidTaps.length ? 'FAIL' : 'PASS',
    detail: sharedLinks.length === 0
      ? 'No shared link is declared.'
      : invalidTaps.length
        ? `${invalidTaps.length} tap(s) reference a router that is not declared: ${invalidTaps.slice(0, 8).join(', ')}.`
        : `${sharedLinks.length} shared link(s) with ${sharedLinks.reduce((sum, link) => sum + link.taps.length, 0)} tap(s) all name declared routers. The drop cell's match logic compares the tap index to the header destination.`,
    citation: 'TOPO-003 §3.1, §3.3, §9.2; ROUTE-001 §4.3',
  });
  const endpointRouters = [...new Set(topology.endpoints.map(endpoint => endpoint.router_id))];
  const isolated = endpointRouters.filter(id => (adjacency.get(id) ?? []).length === 0 && (reverse.get(id) ?? []).length === 0);
  checks.push({
    id: 'topology-endpoints', group: 'topology', title: 'Every attached endpoint sits on a connected router',
    status: !endpointRouters.length ? 'N/A' : isolated.length ? 'FAIL' : 'PASS',
    detail: !endpointRouters.length
      ? 'No endpoint seats are declared.'
      : isolated.length
        ? `${isolated.length} endpoint-bearing router(s) have no incident channel or shared-link tap: ${isolated.slice(0, 8).map(id => `R${id}`).join(', ')}.`
        : `${endpointRouters.length} endpoint-bearing routers all have an incident channel or shared-link tap.`,
    citation: 'TOPO-003 §7.5; attachment.validate_against',
  });
  return checks;
}

export function islandChecks(request: unknown, topology: Topology | null): AnalysisCheck[] {
  const intent = srotaIntent(request);
  if (!intent || !topology) return [];
  const islands = (topology.island_columns ?? []).map(Number).filter(Number.isFinite);
  if (!islands.length) return [{
    id: 'island-none', group: 'topology', title: 'No QoS island is declared',
    status: 'N/A', detail: 'I-ISL confinement is not applicable; no island column is declared.', citation: 'TOPO-003 §4.1',
  }];
  const targetKinds = new Set(['hbm_controller', 'ucie_port', 'peripheral']);
  const coordinates = new Map(topology.routers.map(router => [router.router_id, router.coordinates ?? []]));
  const targets = topology.endpoints.filter(endpoint => targetKinds.has(endpoint.kind));
  const offIsland = targets.filter(endpoint => {
    const coordinate = coordinates.get(endpoint.router_id) ?? [];
    return !islands.includes(Number(coordinate[0]));
  });
  const checks: AnalysisCheck[] = [{
    id: 'island-placement', group: 'topology', title: 'Every shared-resource target terminates on an island column',
    status: !targets.length ? 'WARN' : offIsland.length ? 'FAIL' : 'PASS',
    detail: !targets.length
      ? 'No target endpoint (hbm_controller, ucie_port, peripheral) is declared, so island confinement cannot be checked.'
      : offIsland.length
        ? `${offIsland.length} target endpoint(s) are outside the declared island columns ${islands.join(', ')}: ${offIsland.slice(0, 6).map(endpoint => `${endpoint.kind}@R${endpoint.router_id}`).join(', ')}. I-ISL requires exactly one island router, final before attach.`
        : `${targets.length} target endpoints terminate on the island columns ${islands.join(', ')}.`,
    citation: 'TOPO-003 §4.1 invariant I-ISL; §4.1.2',
  }];
  for (const column of islands) {
    const onColumn = topology.routers.filter(router => Number((router.coordinates ?? [])[0]) === column);
    checks.push({
      id: `island-column-${column}`, group: 'topology', title: `Island column ${column} exists`,
      status: onColumn.length ? 'PASS' : 'FAIL',
      detail: onColumn.length ? `${onColumn.length} router(s) carry column ${column}.` : `No router has x-coordinate ${column}; the island cannot be placed.`,
      citation: 'TOPO-003 §4.1, §10.1',
    });
  }
  return checks;
}

export function agentChecks(request: unknown, topology: Topology | null, windows: AddressWindow[], issues: AddressIssue[]): AnalysisCheck[] {
  const agents = agentsFromRequest(request);
  const checks: AnalysisCheck[] = [];
  const errorCount = issues.filter(issue => issue.severity === 'error').length;
  checks.push({
    id: 'address-window-valid', group: 'address', title: 'Address windows satisfy the compile schema',
    status: errorCount ? 'FAIL' : windows.length ? 'PASS' : 'WARN',
    detail: errorCount
      ? `${errorCount} blocking issue(s). The compiler's AddressDecodeArtifact refuses overlapping, unaligned or out-of-range ranges; fix them before save.`
      : windows.length
        ? `${windows.length} window(s) pass name, range, target, policy and overlap checks.`
        : 'No address window is declared. The compiler will resolve an empty decode table; target agents have no system address.',
    citation: 'compile_model.py AddressRange; address_decode.py _validate_entries',
  });
  if (!topology) return checks;
  const seatsFor = (agent: AgentGroup, groupIndex: number): number =>
    topology.endpoints.filter(endpoint => endpoint.kind === agent.kind
      && (endpoint.group_index === undefined || endpoint.group_index === groupIndex)).length;
  const mismatches: string[] = [];
  for (const [groupIndex, agent] of agents.entries()) {
    const seats = seatsFor(agent, groupIndex);
    if (seats < agent.count) mismatches.push(`${agent.kind}[${groupIndex}]: ${agent.count} declared, ${seats} attached`);
  }
  checks.push({
    id: 'agent-seats', group: 'agents', title: 'Every declared agent has an attached seat',
    status: !agents.length ? 'WARN' : mismatches.length ? 'FAIL' : 'PASS',
    detail: !agents.length
      ? 'The request declares no agent groups.'
      : mismatches.length
        ? `Attachment is incomplete: ${mismatches.join('; ')}. The compiler refuses an agent universe that the topology does not realize.`
        : `${agents.reduce((sum, agent) => sum + agent.count, 0)} declared agent(s) match the ${topology.endpoints.length} attached endpoint seat(s).`,
    citation: 'attachment.validate_against; TOPO-003 §7.2',
  });
  const coverage = targetCoverage(agents, windows);
  const missing = coverage.filter(entry => entry.missingInstances.length);
  checks.push({
    id: 'target-coverage', group: 'address', title: 'Every target instance has an address window',
    status: !coverage.length ? 'WARN' : missing.length ? 'WARN' : 'PASS',
    detail: !coverage.length
      ? 'No window targets a declared agent group, so no target instance is addressable.'
      : missing.length
        ? `Unaddressed target instances: ${missing.map(entry => `${entry.kind}[${entry.missingInstances.join(',')}]`).join('; ')}. A target with no window cannot be reached by a system address even if it is attached.`
        : `${coverage.length} target group(s) cover all declared instances.`,
    citation: 'address_decode.py select_endpoint; TOPO-003 §10.1',
  });
  return checks;
}

export function controlChecks(request: unknown): AnalysisCheck[] {
  const doc = designDocument(request);
  const controls = record(doc.noc_controls ?? doc.noc_config);
  const arbitration = controls.arbitration;
  if (arbitration === undefined || arbitration === null) {
    return [{
      id: 'arbitration', group: 'rtl', title: 'Arbitration is executable',
      status: 'PASS',
      detail: 'No allocator override is declared; the compiler default (iSLIP) is used.',
      citation: 'VC-002 §4.1.2; router behavior',
    }];
  }
  const supported = String(arbitration).trim().toLowerCase() === 'islip';
  return [{
    id: 'arbitration', group: 'rtl', title: 'Arbitration is executable',
    status: supported ? 'PASS' : 'FAIL',
    detail: supported
      ? 'iSLIP is the authored router execution.'
      : `Declared arbitration=${String(arbitration)}. The authored router execution proves iSLIP only; the compiler refuses to substitute another allocator, so evaluation and RTL readiness are blocked.`,
    citation: 'VC-002 §4.1.2; product/catalog_evaluation.py',
  }];
}

export function certificateChecks(compileResult: CompileResult | null): AnalysisCheck[] {
  if (!compileResult) return [{
    id: 'certificate-missing', group: 'certificate', title: 'No compiled certificate',
    status: 'WARN', detail: 'Compile the draft to obtain the compiler\'s attachment, route and deadlock proofs.', citation: 'compile_result_view.py',
  }];
  const claims = ((compileResult.certificate?.claims ?? []) as CertificateClaim[]);
  const failed = claims.filter(claim => {
    const status = claim.status ?? claim.certificate_status;
    return status && status !== 'PASS';
  });
  const checks: AnalysisCheck[] = [{
    id: 'certificate-overall', group: 'certificate', title: 'Compiler certificate',
    status: compileResult.certificate?.overall === 'PASS' ? 'PASS' : failed.length ? 'FAIL' : 'WARN',
    detail: compileResult.certificate?.overall === 'PASS'
      ? `${claims.length} claim(s) pass, including attachment, route completeness/legality and deadlock freedom.`
      : failed.length
        ? `${failed.length} claim(s) are not PASS: ${failed.map(claim => `${claim.obligation ?? claim.claim ?? 'claim'}=${claim.status ?? claim.certificate_status ?? 'unknown'}`).join(', ')}.`
        : 'The compile result carries no certificate claims.',
    citation: 'compile_result_view.py; ROUTE-001 §16',
  }];
  const resources = record(record(compileResult.groups).resources);
  const deadlock = record(resources.deadlock);
  const evidence = record(deadlock.evidence);
  const witness = record(deadlock.witness);
  const status = String(deadlock.status ?? 'unknown');
  const cycle = Array.isArray(evidence.cycle)
    ? evidence.cycle.length
    : witness.acyclic === false ? 1 : 0;
  const nodes = evidence.nodes ?? witness.node_count;
  const edges = evidence.edges ?? witness.edge_count;
  const proofMethod = evidence.proof_method ?? deadlock.method ?? witness.route_realization_scheme;
  const routingClass = evidence.routing_class ?? (Array.isArray(witness.cdg_route_classes) ? witness.cdg_route_classes.join(', ') : undefined);
  checks.push({
    id: 'deadlock-proof', group: 'certificate', title: 'Deadlock proof',
    status: status === 'PASS' ? 'PASS' : status === 'unknown' ? 'WARN' : 'FAIL',
    detail: status === 'PASS'
      ? `${String(deadlock.method ?? 'method not named')} · ${String(proofMethod ?? 'proof method not named')} · ${String(nodes ?? '?')} nodes, ${String(edges ?? '?')} edges, cycle ${cycle ? 'found' : 'none'}.`
      : `Status ${status}; the proof is not a pass. ${String(evidence.reason ?? '')}`.trim(),
    citation: 'ROUTE-001 §4.4, §16; shared_resource_cdg.py',
    evidence: typeof routingClass === 'string' ? `routing class ${routingClass}` : undefined,
  });
  const decode = decodeGroup(compileResult);
  checks.push({
    id: 'decode-resolved', group: 'address', title: 'Resolved address decode',
    status: decode?.available ? (decode.rows?.length ? 'PASS' : 'WARN') : 'WARN',
    detail: decode?.available
      ? `${decode.rows?.length ?? 0} decoded range(s); transform ${decode.address_transform ?? '—'}; unmatched policy ${decode.unmatched_address_policy ?? '—'}.`
      : 'The compile result exposes no address decode. An empty address_map is resolved as an empty table, not as an error.',
    citation: 'compile_result_view.py _address_decode; address_decode.py',
  });
  return checks;
}

export function rtlReachRows(request: unknown, compileResult: CompileResult | null): RtlReachRow[] {
  const doc = designDocument(request);
  const topology = record(doc.topology);
  const controls = record(doc.noc_controls ?? doc.noc_config);
  const resources = record(record(compileResult?.groups).resources);
  const vcCount = typeof resources.vc_count === 'number' ? resources.vc_count : undefined;
  const decode = decodeGroup(compileResult);
  const decodeRows = decode?.rows?.length ?? 0;
  const srota = topology.kind === 'srota';
  const rows: RtlReachRow[] = [
    {
      control: 'Agent address map', declared: `${decodeRows || (Array.isArray(record(doc.address_map).ranges) ? record(doc.address_map).ranges.length : 0)} range(s)`,
      compile: decode?.available ? `${decodeRows} resolved row(s) in the active revision` : 'not compiled yet', preview: 'addr_decode.sv (preview emitter)',
      status: 'reaches-preview',
      note: 'The decoder maps a system address to a one-hot attached endpoint, with IDENTITY transform and ERROR on unmatched. It is not a firewall and does not implement protocol permissions. The preview manifest reports address_decode.status; a running gateway must include this emitter before the file appears.',
      citation: 'address_decode.py; rtl_export.py addr_decode',
    },
    {
      control: 'Link width', declared: controls.link_width ? `${controls.link_width} b` : 'not declared',
      compile: 'packet format check', preview: 'fixed 64-bit flit payload',
      status: 'compiled-only',
      note: 'The certified emitter is a fixed 64-bit packet preview. A 512-bit Srota flit is not emitted by it.',
      citation: 'rtl_export.py LIMITATIONS; ROUTE-001 §8.1',
    },
    {
      control: 'Virtual channels', declared: vcCount !== undefined ? `${vcCount}` : 'compiler-derived',
      compile: vcCount !== undefined ? `${vcCount} VC(s)` : 'not compiled', preview: 'fixed 2 VCs (free/escape)',
      status: vcCount === 2 ? 'reaches-preview' : 'compiled-only',
      note: vcCount === 2 ? 'The preview emitter implements exactly the 2-VC free/escape scheme.' : 'The preview emitter only implements 2 VCs. A different derived count is refused rather than substituted.',
      citation: 'gen_rtl.py CERTIFIED_VC_COUNT; VC-002 §3.2',
    },
    {
      control: 'Input buffer depth', declared: controls.input_buffer_depth_flits_per_vc ? `${controls.input_buffer_depth_flits_per_vc} flits/VC` : 'not declared',
      compile: 'router behavior', preview: '--buf parameter',
      status: 'reaches-preview',
      note: 'The depth reaches the emitter, but it is a per-VC depth in a 2-VC free/escape router, not the Srota 2-flit staging latch plus shared side buffer.',
      citation: 'VC-002 §2.2, §2.3; gen_rtl.py --buf',
    },
    {
      control: 'Routing law', declared: srota ? `Srota ${stringList(topology.path_shapes).join('+') || '—'} / ${String(topology.vc_policy ?? '—')}` : String(topology.kind ?? '—'),
      compile: 'derived route artifact', preview: 'generic free/escape route table',
      status: 'compiled-only',
      note: 'The preview emitter does not realize O1TURN-XY/MECS, the FIU shape choice, or the Srota route law. Its route table is a topology-only preview.',
      citation: 'rtl_export.py LIMITATIONS; ROUTE-001 §2, §3',
    },
    {
      control: 'Path shapes & VC policy', declared: srota ? `${stringList(topology.path_shapes).join(', ')} / ${String(topology.vc_policy ?? 'none')}` : 'not applicable',
      compile: srota ? 'shape/rank partition proof' : 'not applicable', preview: 'not emitted',
      status: srota ? 'compiled-only' : 'not-declared',
      note: 'The routing registers ROUTE_PATH_EN, ROUTE_EPOCH_LEN, ROUTE_VALIANT_MODE and ROUTE_CONGESTION_THRESH have no field in the compile schema or the preview emitter.',
      citation: 'ROUTE-001 §14.1; RT-R7/RT-R8',
    },
    {
      control: 'Side buffer & watermark', declared: srota ? `enable=${topology.sidebuf_enable === true}, watermark=${topology.sidebuf_watermark ?? '—'}` : 'not applicable',
      compile: srota ? 'declared intent' : 'not applicable', preview: 'not emitted',
      status: srota ? 'compiled-only' : 'not-declared',
      note: 'The preview router has no shared side buffer, no alloc_loss gating and no sidebuf_pending bypass inhibit, so F6 is not implemented by it.',
      citation: 'VC-002 §2.3, §4.1.4, §7.4; ROUTE-001 §9.4',
    },
    {
      control: 'Telemetry plane', declared: srota ? `period=${topology.tel_period ?? '—'}, latency=${topology.tel_latency ?? '—'}` : 'not applicable',
      compile: srota ? 'declared intent' : 'not applicable', preview: 'not emitted',
      status: srota ? 'compiled-only' : 'not-declared',
      note: 'Plane T, the congestion vector and the injection-time adaptive overlay are not in the preview.',
      citation: 'ROUTE-001 §5, §8.1; TOPO-003 §13',
    },
    {
      control: 'QoS islands', declared: Array.isArray(topology.island_columns) && topology.island_columns.length ? `${topology.island_columns.join(', ')}` : 'none',
      compile: 'I-ISL route rule', preview: 'not emitted',
      status: Array.isArray(topology.island_columns) && topology.island_columns.length ? 'compiled-only' : 'not-declared',
      note: 'Island ingress rate accounting and the island drop class are not represented by the preview router.',
      citation: 'TOPO-003 §4, §7.5; ROUTE-001 §13.1',
    },
    {
      control: 'Agent data width', declared: Array.isArray(doc.agents) ? [...new Set((doc.agents as AgentGroup[]).map(agent => `${agent.kind}:${agent.data_width ?? '—'}b`))].join(' · ') : '—',
      compile: 'attachment interface descriptor', preview: 'not emitted',
      status: 'compiled-only',
      note: 'The preview flit is fixed at 64 bits and has no endpoint adaptation. Agent data width does not change it.',
      citation: 'attachment.py AgentInterfaceDescriptor; rtl_export.py LIMITATIONS',
    },
    {
      control: 'Agent address width', declared: Array.isArray(doc.agents) ? [...new Set((doc.agents as AgentGroup[]).map(agent => `${agent.kind}:${agent.addr_width ?? '—'}b`))].join(' · ') : '—',
      compile: 'decode range check', preview: 'addr_decode address port',
      status: 'reaches-preview',
      note: 'The decode module uses a 64-bit address port by default; a narrower agent must be adapted at its boundary.',
      citation: 'address_decode.py ADDRESS_DOMAIN_BITS; addr_decode.sv',
    },
    {
      control: 'Access permissions / firewall', declared: 'not representable',
      compile: 'no field in AddressRange', preview: 'not emitted',
      status: 'not-declared',
      note: 'The compile schema has no per-initiator read/write/secure permission field. The address map selects a target endpoint; it does not authorize the access. Adding a firewall requires a new address-map field, compiler enforcement and an RTL check this prototype does not fake.',
      citation: 'compile_model.py AddressRange; ROUTE-001 §13.1 (island class only)',
    },
    {
      control: 'Address translation', declared: 'IDENTITY only',
      compile: 'AddressTransform.IDENTITY', preview: 'no translation',
      status: 'compiled-only',
      note: 'The resolved decode forwards the original address unchanged and refuses an unmatched address. There is no translation, truncation or remap stage.',
      citation: 'address_decode.py AddressTransform; unmatched_address_policy',
    },
    {
      control: 'Multicast groups', declared: controls.mcast_groups !== undefined && controls.mcast_groups !== null ? `${controls.mcast_groups} group(s)` : 'not declared',
      compile: 'NoC control', preview: 'not emitted',
      status: controls.mcast_groups ? 'compiled-only' : 'not-declared',
      note: 'Multicast is a consumption model of the row-express/column-drop mechanism, not a third path shape. The preview router has no multicast group table.',
      citation: 'ROUTE-001 §13.2; TOPO-003 §9.2',
    },
    {
      control: 'Pipeline & arbitration', declared: `${controls.route_compute_cycles ?? '—'} / ${controls.vc_alloc_cycles ?? '—'} / ${controls.switch_alloc_cycles ?? '—'} / ${controls.switch_traversal_cycles ?? '—'} cycles · ${controls.arbitration ?? 'iSLIP'}`,
      compile: 'router behavior check', preview: 'fixed free/escape pipeline',
      status: 'compiled-only',
      note: 'The preview router does not implement the Srota ST0/ST1/ST2 stages, the three-level arbiter or the golden-rotation schedule.',
      citation: 'ROUTE-001 §9, §11.2; VC-002 §4.1',
    },
  ];
  return rows;
}

export type FabricAnalysis = {
  checks: AnalysisCheck[];
  issues: AddressIssue[];
  cdg: CdgResult;
  coverage: AddressCoverage;
  targets: TargetCoverage[];
  rtlRows: RtlReachRow[];
  counts: Record<CheckStatus, number>;
};

export function buildFabricAnalysis(request: unknown, topology: Topology | null, compileResult: CompileResult | null): FabricAnalysis {
  const agents = agentsFromRequest(request);
  const windows = windowsFromRequest(request, agents);
  const issues = validateWindows(windows, agents);
  const checks = [
    ...agentChecks(request, topology, windows, issues),
    ...srotaShapeChecks(request),
    ...portBudgetChecks(request),
    ...reachabilityChecks(topology),
    ...islandChecks(request, topology),
    ...controlChecks(request),
    ...certificateChecks(compileResult),
  ];
  const counts: Record<CheckStatus, number> = { PASS: 0, WARN: 0, FAIL: 0, 'N/A': 0 };
  for (const check of checks) counts[check.status] += 1;
  return {
    checks,
    issues,
    cdg: srotaCdg(request),
    coverage: addressCoverage(windows),
    targets: targetCoverage(agents, windows),
    rtlRows: rtlReachRows(request, compileResult),
    counts,
  };
}
