import { api } from '../../api';
import type {
  CanonicalRoute,
  CompileResultView,
  PreflightView,
  ProjectView,
  RunIntegrityView,
  RunSummary,
  RunView,
  TrafficMatrixView,
  WorkloadLoweringView,
} from '../../api';
import { useAsync, type Async } from '../../studio';
import { designViewFromDraft } from '../../components/FabricView';
import type { DesignView, TopologyEndpoint, TopologyView } from '../../types';

/** The Loom views, in the order the tab strip presents them. */
export type LoomViewId =
  | 'topology' | 'agents' | 'catalog' | 'domains' | 'access' | 'floorplan'
  | 'workload' | 'simulation' | 'capability';

export const LOOM_VIEWS: { id: LoomViewId; label: string }[] = [
  { id: 'topology', label: 'Logical topology' },
  { id: 'agents', label: 'Agent matrix' },
  { id: 'catalog', label: 'IP catalog' },
  { id: 'domains', label: 'Clock & power' },
  { id: 'access', label: 'I–T mapping' },
  { id: 'floorplan', label: 'Physical floorplan' },
  { id: 'workload', label: 'Workload profiling' },
  { id: 'simulation', label: 'Simulation' },
  // Cross-cutting truth, not a step of the design flow: it reads what the
  // server says the system can do, so it follows the flow rather than joining it.
  { id: 'capability', label: 'Capabilities' },
];

export function isLoomView(value: string): value is LoomViewId {
  return LOOM_VIEWS.some((v) => v.id === value);
}

/** The whole authored agent contract today (veritx_dse Agent dataclass):
 *  seven fields, nothing else. Columns a dense NoC matrix would like to show —
 *  outstanding-transaction limits, ordering rules, address windows — are not
 *  part of it and are never invented. */
export interface AuthoredAgent {
  kind: string;
  count: number;
  data_width: number | null;
  addr_width: number | null;
  protocol: string | null;
  clock_domain: string | null;
  power_domain: string | null;
}

/** The shape `useAsync` returns, narrowed so views only touch `result`. */
export type Query<T> = { result: Async<T> };

/** Every query the workspace drives. `null` means "this input does not exist
 *  yet", which is a different answer from "loading" and from "failed"; the
 *  views render those three states differently. */
export interface LoomData {
  projectId: string;
  project: ProjectView | null;
  design: DesignView | null;
  designHash: string | null;
  agents: AuthoredAgent[];
  revisionId: string | null;
  dirty: boolean;
  topology: Query<TopologyView | null>;
  compileResult: Query<CompileResultView | null>;
  latestRun: RunSummary | null;
  run: Query<RunView | null>;
  traffic: Query<TrafficMatrixView | null>;
  lowering: Query<WorkloadLoweringView | null>;
}

const NONE = <T,>(): Promise<T | null> => Promise.resolve(null);

function readAgents(request: Record<string, unknown> | null): AuthoredAgent[] {
  const raw = request?.agents;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return [];
    const a = entry as Record<string, unknown>;
    if (typeof a.kind !== 'string' || typeof a.count !== 'number') return [];
    const text = (v: unknown): string | null =>
      typeof v === 'string' ? v : null;
    const num = (v: unknown): number | null =>
      typeof v === 'number' ? v : null;
    return [{
      kind: a.kind,
      count: a.count,
      data_width: num(a.data_width),
      addr_width: num(a.addr_width),
      protocol: text(a.protocol),
      clock_domain: text(a.clock_domain),
      power_domain: text(a.power_domain),
    }];
  });
}

export function useLoom(projectId: string): LoomData {
  const project = useAsync(
    () => (projectId ? api.project(projectId) : NONE<ProjectView>()),
    [projectId],
  );
  const view = project.result.state === 'ready' ? project.result.data : null;
  const revisionId = view?.active_revision_id ?? null;
  const runId = (view?.latest_active_run ?? view?.latest_static_evaluation)?.run_id ?? null;

  const draft = useAsync(
    () => (projectId ? api.draft(projectId) : NONE<never>()),
    [projectId],
  );
  const draftData = draft.result.state === 'ready' ? draft.result.data : null;

  const topology = useAsync<TopologyView | null>(
    () => (revisionId ? api.topology(revisionId) : NONE<TopologyView>()),
    [revisionId],
  );
  // A failed read stays failed: collapsing it to null would make a broken
  // gateway look like an empty project. Views render loading / ready(value)
  // / ready(null, genuinely absent) / error as four different states.
  const compileResult = useAsync<CompileResultView | null>(
    () => (revisionId ? api.compileResult(revisionId) : NONE<CompileResultView>()),
    [revisionId],
  );
  const run = useAsync<RunView | null>(
    () => (runId ? api.run(runId) : NONE<RunView>()),
    [runId],
  );
  const traffic = useAsync<TrafficMatrixView | null>(
    () => (runId ? api.trafficMatrix(runId) : NONE<TrafficMatrixView>()),
    [runId],
  );
  const workloadId = draftData?.workload_id ?? null;
  const lowering = useAsync<WorkloadLoweringView | null>(
    () => (workloadId ? api.workloadLowering(workloadId) : NONE<WorkloadLoweringView>()),
    [workloadId],
  );

  return {
    projectId,
    project: view,
    design: designViewFromDraft(draftData?.request ?? null),
    designHash: draftData?.design_hash ?? null,
    agents: readAgents(draftData?.request ?? null),
    revisionId,
    dirty: Boolean(draftData?.dirty),
    topology,
    compileResult,
    latestRun: (view?.latest_active_run ?? view?.latest_static_evaluation) ?? null,
    run,
    traffic,
    lowering,
  };
}

/** Attachment state of one agent row, decided by the join — never inferred.
 *
 *  - ATTACHED: declared by the draft and seated by the certified attachment.
 *  - UNATTACHED: declared by the draft, with no certified seat.
 *  - ORPHAN_ARTIFACT: seated by the attachment with no matching declaration.
 *    The seat is real; the declaration is missing. Never merged into intent.
 *  - INTEGRITY_ERROR: seated but contradictory — a kind mismatch at the same
 *    (group, instance) key, or a second endpoint claiming an instance that is
 *    already seated. Displayed, never reconciled. */
export type AgentScope =
  | 'ATTACHED' | 'UNATTACHED' | 'ORPHAN_ARTIFACT' | 'INTEGRITY_ERROR';

export interface AgentRow {
  /** The endpoint identity the compiler assigned — `endpoint_id` from the
   *  certified attachment, not a synthesized label. `-1` only when the row
   *  has no endpoint at all (UNATTACHED); it is a sentinel, never an id. */
  endpointId: number;
  /** Human handle built from the machine triple; never used as identity. */
  label: string;
  kind: string;
  groupIndex: number;
  instanceIndex: number;
  routerId: number | null;
  portId: number | null;
  /** Authored group fields, joined by `group_index`. */
  dataWidth: number | null;
  addrWidth: number | null;
  protocol: string | null;
  clockDomain: string | null;
  powerDomain: string | null;
  /** True exactly when `scope === 'ATTACHED'`. Kept so existing seated /
   *  unseated filters keep working; new code should read `scope`. */
  attached: boolean;
  scope: AgentScope;
  /** Why this row is ORPHAN_ARTIFACT or INTEGRITY_ERROR. Null otherwise —
   *  an attached or unattached row needs no explanation. */
  integrityNote: string | null;
}

/** Canonical machine identity of one declared instance, in the backend's own
 *  `agent_group[g]/kind[i]` form (`AgentInstance.instance_id`). The label is
 *  derived, never keyed from — identity is the (group, instance) pair. */
export function declaredLabel(groupIndex: number, kind: string, instanceIndex: number): string {
  return `agent_group[${groupIndex}]/${kind}[${instanceIndex}]`;
}

/** Every declared agent instance joined against every certified seat: a FULL
 *  OUTER JOIN of draft intent and the certified attachment.
 *
 *  Two sources, deliberately kept apart: the draft's `agents` rows are what
 *  the author declared (intent), and `topology.endpoints` is what the
 *  compiler seated (materialized fact). The join key is the positional
 *  (group_index, instance_index) pair — the same key the backend uses when it
 *  expands `range(group.count)` into `AgentInstance`s. `kind` is compared,
 *  never assumed: a seated kind that disagrees with the declared group at the
 *  same key is an integrity finding, not a match.
 *
 *  Row counts: rows with scope ATTACHED or UNATTACHED are exactly the
 *  declared census — their count always equals `sum(draft.agents.count)`.
 *  ORPHAN_ARTIFACT and INTEGRITY_ERROR rows are extra: they exist so an
 *  attachment the declaration cannot explain is displayed, never dropped. */
export function agentRows(data: LoomData): AgentRow[] {
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data
    : null;
  const groups = data.agents;

  const groupOf = (index: number): AuthoredAgent | undefined => groups[index];

  const declaredRow = (
    group: AuthoredAgent, groupIndex: number, instanceIndex: number,
    seat: { endpoint: TopologyEndpoint } | null,
  ): AgentRow => {
    if (seat === null) {
      return {
        endpointId: -1,
        label: declaredLabel(groupIndex, group.kind, instanceIndex),
        kind: group.kind,
        groupIndex,
        instanceIndex,
        routerId: null,
        portId: null,
        dataWidth: group.data_width,
        addrWidth: group.addr_width,
        protocol: group.protocol,
        clockDomain: group.clock_domain,
        powerDomain: group.power_domain,
        attached: false,
        scope: 'UNATTACHED',
        integrityNote: null,
      };
    }
    const e = seat.endpoint;
    if (e.kind !== group.kind) {
      return {
        endpointId: e.endpoint_id,
        label: declaredLabel(groupIndex, e.kind, instanceIndex),
        kind: e.kind,
        groupIndex,
        instanceIndex,
        routerId: e.router_id,
        portId: e.port_id,
        dataWidth: group.data_width,
        addrWidth: group.addr_width,
        protocol: group.protocol,
        clockDomain: group.clock_domain,
        powerDomain: group.power_domain,
        attached: false,
        scope: 'INTEGRITY_ERROR',
        integrityNote: `kind mismatch: group ${groupIndex} declares '${group.kind}' but the attachment seats '${e.kind}' at instance ${instanceIndex}`,
      };
    }
    return {
      endpointId: e.endpoint_id,
      label: declaredLabel(groupIndex, e.kind, instanceIndex),
      kind: e.kind,
      groupIndex,
      instanceIndex,
      routerId: e.router_id,
      portId: e.port_id,
      dataWidth: group.data_width,
      addrWidth: group.addr_width,
      protocol: group.protocol,
      clockDomain: group.clock_domain,
      powerDomain: group.power_domain,
      attached: true,
      scope: 'ATTACHED',
      integrityNote: null,
    };
  };

  // A seated endpoint the declaration cannot explain. ORPHAN_ARTIFACT means
  // the (group, instance) key has no declared counterpart at all — the seat
  // is real but outside intent. INTEGRITY_ERROR is reserved for
  // contradictions: a seat that collides with a declared instance of another
  // kind, or a second seat claiming an already-seated instance.
  const extraRow = (
    e: TopologyEndpoint,
    scope: 'ORPHAN_ARTIFACT' | 'INTEGRITY_ERROR',
    note: string,
  ): AgentRow => {
    const group = groupOf(e.group_index);
    return {
      endpointId: e.endpoint_id,
      label: declaredLabel(e.group_index, e.kind, e.instance_index),
      kind: e.kind,
      groupIndex: e.group_index,
      instanceIndex: e.instance_index,
      routerId: e.router_id,
      portId: e.port_id,
      dataWidth: group?.data_width ?? null,
      addrWidth: group?.addr_width ?? null,
      protocol: group?.protocol ?? null,
      clockDomain: group?.clock_domain ?? null,
      powerDomain: group?.power_domain ?? null,
      attached: false,
      scope,
      integrityNote: note,
    };
  };

  // No certified topology: expand the declared groups so the table is still a
  // census of intent, with every row marked unattached.
  if (!topology) {
    return groups.flatMap((group, groupIndex) =>
      Array.from({ length: group.count }, (_, instanceIndex) =>
        declaredRow(group, groupIndex, instanceIndex, null)));
  }

  // Index endpoints by their (group, instance) key. Duplicates are an
  // attachment-integrity problem: the first claim is joined normally and
  // every further claim is surfaced, never silently merged.
  const byKey = new Map<string, TopologyEndpoint[]>();
  for (const e of topology.endpoints) {
    const key = `${e.group_index}:${e.instance_index}`;
    const list = byKey.get(key) ?? [];
    list.push(e);
    byKey.set(key, list);
  }

  const rows: AgentRow[] = [];
  groups.forEach((group, groupIndex) => {
    for (let instanceIndex = 0; instanceIndex < group.count; instanceIndex += 1) {
      const claimants = byKey.get(`${groupIndex}:${instanceIndex}`) ?? [];
      const [first, ...duplicates] = claimants;
      rows.push(declaredRow(group, groupIndex, instanceIndex, first ? { endpoint: first } : null));
      for (const dup of duplicates) {
        rows.push(extraRow(dup, 'INTEGRITY_ERROR',
          `duplicate seat: endpoint ${dup.endpoint_id} also claims group ${groupIndex} instance ${instanceIndex}, already seated by endpoint ${first.endpoint_id}`));
      }
    }
  });

  // Seats with no matching declaration: group_index out of range, or an
  // instance_index the declared group never had. Consumed keys are removed
  // above; what remains is unexplained by intent.
  const consumed = new Set<string>();
  groups.forEach((group, groupIndex) => {
    for (let instanceIndex = 0; instanceIndex < group.count; instanceIndex += 1) {
      consumed.add(`${groupIndex}:${instanceIndex}`);
    }
  });
  for (const [key, endpoints] of byKey) {
    if (consumed.has(key)) continue;
    for (const e of endpoints) {
      const inRangeGroup = e.group_index >= 0 && e.group_index < groups.length;
      rows.push(extraRow(e, 'ORPHAN_ARTIFACT', inRangeGroup
        ? `orphan seat: group ${e.group_index} declares ${groups[e.group_index].count} instance(s) but the attachment seats instance ${e.instance_index} of '${e.kind}'`
        : `orphan seat: the attachment references group ${e.group_index}, but the draft declares ${groups.length} group(s)`));
    }
  }
  return rows;
}

/** Which declaration scope the agent table is a census of, and — when the
 *  draft has uncompiled changes — what the frozen revision declared instead.
 *
 *  The agent rows always expand the CURRENT DRAFT, so their declared count
 *  equals `sum(draft.agents.count)`. When the draft is dirty the topology
 *  belongs to an older declaration; the frozen scope is shown alongside
 *  rather than merged, so a mismatch reads as two scopes instead of a
 *  corrupt join. */
export interface DeclaredScope {
  draftGroups: { kind: string; count: number }[];
  draftTotal: number;
  dirty: boolean;
  revisionId: string | null;
  revisionGroups: { kind: string; count: number }[] | null;
  revisionTotal: number | null;
}

export function declaredScope(data: LoomData): DeclaredScope {
  const draftGroups = data.agents.map((g) => ({ kind: g.kind, count: g.count }));
  const frozen = data.project?.active_revision?.design?.agents ?? null;
  return {
    draftGroups,
    draftTotal: draftGroups.reduce((n, g) => n + g.count, 0),
    dirty: data.dirty,
    revisionId: data.revisionId,
    revisionGroups: frozen
      ? frozen.map((a) => ({ kind: a.kind, count: a.count }))
      : null,
    revisionTotal: frozen
      ? frozen.reduce((n, a) => n + a.count, 0)
      : null,
  };
}

/** A clock or power domain the author declared, with the seats that carry it.
 *  The domain table is intent; membership is read off the certified
 *  attachment, so a domain with no certified members says so. */
export interface DomainRow {
  kind: 'clock' | 'power';
  id: string;
  /** Agents (instances, not groups) that name this domain. */
  agentCount: number;
  /** Of those, how many the compiler actually seated. */
  attachedCount: number;
  /** Routers that carry at least one attached agent in this domain. */
  routers: number[];
}

/** One boundary where a channel joins two different clock domains, derived
 *  from the certified attachment and the authored domain assignment. This is
 *  a derived crossing list, not a synchronizer recommendation. */
export interface Crossing {
  channelId: number;
  srcRouter: number;
  dstRouter: number;
  srcDomain: string;
  dstDomain: string;
  widthBits: number;
  latencyCycles: number;
}

const UNDECLARED = 'undeclared';

function domainLabel(value: string | null): string {
  return value && value.trim() ? value : UNDECLARED;
}

/** Domain census + derived crossings.
 *
 *  Crossings are computed from two artifacts only: the certified attachment
 *  (which agent sits on which router) and the authored `clock_domain` field.
 *  Routers with no agent, or agents with no declared domain, collapse to
 *  `undeclared` — that keeps the crossing count honest instead of hiding a
 *  channel behind an assumption. */
export function domainsOf(data: LoomData): {
  rows: DomainRow[];
  crossings: Crossing[];
  routersWithoutAgents: number;
} {
  // Declared census only: orphan and integrity rows are seated facts with no
  // valid authored assignment, so they cannot join a domain census. Their
  // seats still count as occupied below, read straight off the attachment.
  const agents = agentRows(data).filter(
    (r) => r.scope === 'ATTACHED' || r.scope === 'UNATTACHED');
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data
    : null;
  const seatedRouters = new Set(
    (topology?.endpoints ?? []).map((e) => e.router_id));

  const clockOfRouter = new Map<number, Set<string>>();
  const powerOfRouter = new Map<number, Set<string>>();
  const tally = (kind: 'clock' | 'power') => {
    const byDomain = new Map<string, DomainRow>();
    for (const a of agents) {
      const id = kind === 'clock' ? domainLabel(a.clockDomain) : domainLabel(a.powerDomain);
      const row = byDomain.get(id) ?? {
        kind, id, agentCount: 0, attachedCount: 0, routers: [],
      };
      row.agentCount += 1;
      if (a.attached && a.routerId != null) {
        row.attachedCount += 1;
        if (!row.routers.includes(a.routerId)) row.routers.push(a.routerId);
      }
      byDomain.set(id, row);
      if (kind === 'clock' && a.attached && a.routerId != null) {
        const set = clockOfRouter.get(a.routerId) ?? new Set<string>();
        set.add(id);
        clockOfRouter.set(a.routerId, set);
      }
      if (kind === 'power' && a.attached && a.routerId != null) {
        const set = powerOfRouter.get(a.routerId) ?? new Set<string>();
        set.add(id);
        powerOfRouter.set(a.routerId, set);
      }
    }
    return [...byDomain.values()].sort((x, y) => (
      x.id === UNDECLARED ? 1 : y.id === UNDECLARED ? -1 : x.id.localeCompare(y.id)
    ));
  };

  const clockRows = tally('clock');
  const powerRows = tally('power');

  const crossings: Crossing[] = [];
  for (const c of topology?.channels ?? []) {
    if (c.src_router === c.dst_router) continue;
    const src = clockOfRouter.get(c.src_router);
    const dst = clockOfRouter.get(c.dst_router);
    const srcLabel = src ? [...src].sort().join('+') : UNDECLARED;
    const dstLabel = dst ? [...dst].sort().join('+') : UNDECLARED;
    if (srcLabel === dstLabel) continue;
    crossings.push({
      channelId: c.channel_id,
      srcRouter: c.src_router,
      dstRouter: c.dst_router,
      srcDomain: srcLabel,
      dstDomain: dstLabel,
      widthBits: c.width_bits,
      latencyCycles: c.latency_cycles,
    });
  }
  crossings.sort((x, y) => x.channelId - y.channelId);

  const unused = (topology?.routers ?? []).filter(
    (r) => !seatedRouters.has(r.router_id),
  ).length;

  return {
    rows: [...clockRows, ...powerRows],
    crossings,
    routersWithoutAgents: unused,
  };
}

/** One measured src→dst pair walked over the certified route table. */
export interface ChannelLoad {
  channelId: number;
  srcRouter: number;
  dstRouter: number;
  widthBits: number;
  latencyCycles: number;
  /** Sum of measured flits on every traced pair whose canonical route uses
   *  this channel. Measured volume × derived route — never a backend
   *  per-channel counter. */
  flits: number;
  /** How many traced pairs contributed. */
  pairs: number;
}

/** Expected per-channel load.
 *
 *  Two independent facts are combined: the traffic matrix counts what the run
 *  actually emitted per (src, dst), and the frozen route table says which
 *  channels a pair would cross. The product is DERIVED EXPECTED load — it is
 *  explicitly not a measured per-link utilization, and it inherits the
 *  route-table scope (derived expected, not observed). */
export function expectedChannelLoad(
  traffic: TrafficMatrixView | null,
  routes: Map<string, CanonicalRoute>,
  topology: TopologyView | null,
): ChannelLoad[] {
  if (!traffic) return [];
  // Defense at the attribution seam: only a terminating route may move
  // measured flits onto channels. sweepRoutes already enforces this; the
  // check here keeps direct callers (and future ones) honest too.
  const channelById = new Map(topology?.channels.map((c) => [c.channel_id, c]) ?? []);
  const byChannel = new Map<number, ChannelLoad>();
  for (const pair of traffic.pairs) {
    if (pair.src === pair.dst || pair.flits <= 0) continue;
    const route = routes.get(pairKey(pair.src, pair.dst));
    if (!route) continue;
    if (!route.terminates) continue;
    for (const hop of route.hops) {
      const channel = channelById.get(hop.channel_id);
      const entry = byChannel.get(hop.channel_id) ?? {
        channelId: hop.channel_id,
        srcRouter: hop.src_router,
        dstRouter: hop.dst_router,
        widthBits: channel?.width_bits ?? 0,
        latencyCycles: channel?.latency_cycles ?? 0,
        flits: 0,
        pairs: 0,
      };
      entry.flits += pair.flits;
      entry.pairs += 1;
      byChannel.set(hop.channel_id, entry);
    }
  }
  return [...byChannel.values()].sort((x, y) => y.flits - x.flits);
}

export interface LoomPlan {
  routingClass: string | null;
  routers: { router_id: number; coordinates: number[] }[];
  initiatorRouters: number[];
  targetRouters: number[];
}

/** Routing class from the certified compile groups, plus which routers carry
 *  which endpoint kinds — the only mapping the topology artifact supports. */
export function loomPlan(data: LoomData): LoomPlan {
  const groups = data.compileResult.result.state === 'ready'
    ? data.compileResult.result.data?.groups ?? null
    : null;
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data
    : null;
  const routers = topology?.routers ?? [];
  const withKind = new Map<number, Set<string>>();
  for (const e of topology?.endpoints ?? []) {
    if (!withKind.has(e.router_id)) withKind.set(e.router_id, new Set());
    withKind.get(e.router_id)?.add(e.kind);
  }
  const kindsOf = (routerId: number): string[] => [...(withKind.get(routerId) ?? [])];
  const carries = (routerId: number, ...needles: string[]): boolean =>
    kindsOf(routerId).some((k) => needles.some((n) => k.includes(n)));
  return {
    routingClass: groups?.routing?.routing_classes?.[0] ?? null,
    routers,
    initiatorRouters: routers
      .filter((r) => carries(r.router_id, 'compute', 'nic'))
      .map((r) => r.router_id),
    targetRouters: routers
      .filter((r) => carries(r.router_id, 'hbm', 'ucie', 'peripheral'))
      .map((r) => r.router_id),
  };
}

export interface PhysicalEdge {
  /** null when the compiler carried no physical-link row for this adjacency. */
  id: number | null;
  a: number;
  b: number;
  lengthMm: number | null;
  channelIds: number[];
}

/** Adjacent router pairs from the certified channels — always present once the
 *  design compiles — with the physical-link id and length attached only where
 *  the compiler emitted one. */
export function channelAdjacency(topology: TopologyView | null): PhysicalEdge[] {
  if (!topology) return [];
  const byPair = new Map<string, PhysicalEdge>();
  for (const c of topology.channels) {
    if (c.src_router === c.dst_router) continue;
    const a = Math.min(c.src_router, c.dst_router);
    const b = Math.max(c.src_router, c.dst_router);
    const key = `${a}-${b}`;
    const edge = byPair.get(key) ?? { id: null, a, b, lengthMm: null, channelIds: [] };
    edge.channelIds.push(c.channel_id);
    byPair.set(key, edge);
  }
  const byChannel = new Map<number, PhysicalEdge>();
  for (const edge of byPair.values()) {
    for (const id of edge.channelIds) byChannel.set(id, edge);
  }
  for (const link of topology.physical_links) {
    const edge = link.channel_ids
      .map((id) => byChannel.get(id))
      .find(Boolean);
    if (!edge) continue;
    edge.id = link.physical_link_id;
    edge.lengthMm = link.length_mm ?? null;
  }
  return [...byPair.values()].sort((x, y) => x.a - y.a || x.b - y.b);
}

export function pairKey(src: number, dst: number): string {
  return `${src}->${dst}`;
}

/** Declared/derived compile summary, when the revision compiled one. */
export function compileSummary(data: LoomData): {
  declared: Record<string, unknown>;
  derived: Record<string, unknown>;
  certificate_overall: string | null;
} | null {
  const result = data.compileResult.result.state === 'ready'
    ? data.compileResult.result.data
    : null;
  const summary = result?.groups?.summary;
  if (!summary) return null;
  return {
    declared: summary.declared as Record<string, unknown>,
    derived: summary.derived as Record<string, unknown>,
    certificate_overall: summary.certificate_overall,
  };
}

export interface Parallelism {
  tp: number;
  pp: number;
  ep: number;
  dp: number;
}

/** Parallelism lives in the compile summary when the revision exists, and as
 *  flat tp/pp/ep/dp fields on the draft's workload. Both are engine output;
 *  neither is synthesized when absent. */
export function parallelismOf(data: LoomData): Parallelism | null {
  const result = data.compileResult.result.state === 'ready'
    ? data.compileResult.result.data
    : null;
  const mapped = result?.groups?.mapping?.parallelism ?? null;
  if (mapped) return mapped;
  const workload = data.design?.workload as unknown as Record<string, unknown> | undefined;
  if (!workload) return null;
  if (workload.parallelism && typeof workload.parallelism === 'object') {
    return workload.parallelism as unknown as Parallelism;
  }
  const num = (k: string): number | null =>
    typeof workload[k] === 'number' ? (workload[k] as number) : null;
  if (num('tp') === null) return null;
  return { tp: num('tp') ?? 0, pp: num('pp') ?? 0, ep: num('ep') ?? 0, dp: num('dp') ?? 0 };
}

export interface TrafficPair {
  src: number;
  dst: number;
  packets: number;
  flits: number;
}

/** Busiest measured src→dst pairs of the executed trace, descending. */
export function busiestPairs(traffic: TrafficMatrixView | null, limit = 5): TrafficPair[] {
  if (!traffic) return [];
  return traffic.pairs
    .slice()
    .sort((x, y) => y.flits - x.flits)
    .slice(0, limit);
}

/** One traced (endpoint) pair resolved to the router pair the frozen route
 *  table answers. The canonical route query walks routers, while the trace
 *  counts endpoints — the certified attachment is the only bridge, resolved
 *  here and nowhere else. */
export interface RouterPair {
  pair: TrafficPair;
  srcRouter: number;
  dstRouter: number;
  /** Same router on both ends: the route is a trivial local ejection, not a
   *  network path. Resolved, but contributes no channel load. */
  local: boolean;
}

/** Split traced endpoint pairs into the router pairs the route table can
 *  answer and the pairs it cannot.
 *
 *  A pair is unresolvable when either endpoint has no certified seat — a
 *  trace from another revision, or an attachment the revision never had.
 *  Unresolvable pairs are counted, never queried: asking the route table
 *  about an endpoint id as though it were a router id is the exact confusion
 *  this function exists to prevent (it only coincides for concentration 1
 *  with identity placement).
 *
 *  Self-traffic never reaches the route table: same-endpoint pairs cross no
 *  channel by construction. */
export function resolveRouterPairs(
  pairs: TrafficPair[],
  topology: TopologyView | null,
): { routable: RouterPair[]; unresolvable: TrafficPair[] } {
  if (!topology) return { routable: [], unresolvable: pairs.slice() };
  const routerOf = new Map<number, number>();
  for (const e of topology.endpoints) {
    if (!routerOf.has(e.endpoint_id)) routerOf.set(e.endpoint_id, e.router_id);
  }
  const routable: RouterPair[] = [];
  const unresolvable: TrafficPair[] = [];
  for (const pair of pairs) {
    if (pair.src === pair.dst) continue;
    const srcRouter = routerOf.get(pair.src);
    const dstRouter = routerOf.get(pair.dst);
    if (srcRouter === undefined || dstRouter === undefined) {
      unresolvable.push(pair);
      continue;
    }
    routable.push({
      pair, srcRouter, dstRouter, local: srcRouter === dstRouter,
    });
  }
  return { routable, unresolvable };
}

/** How many traced pairs the route sweep actually resolved. Denominators in
 *  this workspace always state the resolved count beside the traced count. */
export interface RouteSweep {
  routes: Map<string, CanonicalRoute>;
  requested: number;
  resolved: number;
  failed: number;
  /** Queried but answered without a terminating path: the pair's flits
   *  attribute to no channel. Counted, never presented as load. */
  unterminated: number;
  /** Pairs whose endpoint has no certified seat, so no route was requested. */
  unresolvable: number;
  /** Unique router pairs actually queried (concentration shares routers). */
  routerQueries: number;
  /** The per-pair walk can be large, so it is bounded; this is the bound. */
  limit: number;
  state: 'idle' | 'loading' | 'ready' | 'error';
  error: string | null;
}

export const ROUTE_SWEEP_LIMIT = 512;

/** The traced src→dst pairs a sweep will walk, busiest first so a bounded
 *  sweep still covers the load that matters. */
export function sweepPairs(traffic: TrafficMatrixView | null): TrafficPair[] {
  if (!traffic) return [];
  return traffic.pairs
    .filter((p) => p.src !== p.dst && p.flits > 0)
    .sort((x, y) => y.flits - x.flits)
    .slice(0, ROUTE_SWEEP_LIMIT);
}

/** Walk resolved router pairs over the frozen route table.
 *
 *  The query carries ROUTER ids — never the traced endpoint ids. Under
 *  concentration several endpoint pairs share one router pair, so router
 *  pairs are queried once and fanned out; every traced pair still gets its
 *  own attribution entry. A route that does not terminate is not a route:
 *  it is counted and its flits attribute to nothing. The sweep is sequential
 *  rather than firing thousands of requests, and partial resolution is
 *  reported, never presented as complete. */
export async function sweepRoutes(
  revisionId: string,
  routingClass: string,
  pairs: RouterPair[],
  onProgress?: (done: number, total: number) => void,
): Promise<{
  routes: Map<string, CanonicalRoute>;
  resolved: number;
  failed: number;
  unterminated: number;
  unresolvable: number;
  routerQueries: number;
}> {
  const routes = new Map<string, CanonicalRoute>();
  let failed = 0;
  let unterminated = 0;
  // One query per unique router pair; the map fans the answer back out to
  // every traced endpoint pair that shares it.
  const byRouter = new Map<string, RouterPair[]>();
  for (const rp of pairs) {
    const key = pairKey(rp.srcRouter, rp.dstRouter);
    const list = byRouter.get(key) ?? [];
    list.push(rp);
    byRouter.set(key, list);
  }
  const groups = [...byRouter.values()];
  let done = 0;
  for (const group of groups) {
    const { srcRouter, dstRouter } = group[0];
    try {
      const route = await api.route(revisionId, {
        routingClass,
        src: srcRouter,
        dst: dstRouter,
      });
      if (route.terminates) {
        for (const rp of group) {
          routes.set(pairKey(rp.pair.src, rp.pair.dst), route);
        }
      } else {
        unterminated += group.length;
      }
    } catch {
      failed += group.length;
    }
    done += group.length;
    onProgress?.(done, pairs.length);
  }
  return {
    routes,
    resolved: routes.size,
    failed,
    unterminated,
    unresolvable: 0,
    routerQueries: groups.length,
  };
}

export type ProblemSeverity = 'bad' | 'warn' | 'info' | 'ok';

export interface Problem {
  id: string;
  severity: ProblemSeverity;
  title: string;
  detail: string;
  /** Where the evidence came from — every problem names its artifact. */
  source: string;
  /** In-workspace deep link, when the finding has a place to land. */
  view?: LoomViewId;
}

/** Every blocking or advisory finding the engine actually emitted, gathered in
 *  one place.
 *
 *  Nothing here is Studio's opinion. Each entry restates a verdict that exists
 *  in an artifact — a preflight gate, a requirement entry, a conservation
 *  check, the deadlock proof, the certificate, or a staleness comparison
 *  between the draft and the compiled revision. Silence means those artifacts
 *  said nothing, which is stated rather than shown as green. */
export function problemsOf(data: LoomData, inputs: {
  preflight: PreflightView | null;
  integrity: RunIntegrityView | null;
  /** A read that failed is missing evidence, not a clean bill. Each failure
   *  becomes an explicit advisory finding naming the operation that failed. */
  preflightError?: string | null;
  integrityError?: string | null;
}): Problem[] {
  const out: Problem[] = [];
  const revisionId = data.revisionId;
  const push = (p: Problem): void => { out.push(p); };

  if (inputs.preflightError) {
    push({
      id: 'preflight-unreadable',
      severity: 'warn',
      title: 'Preflight verdicts unavailable',
      detail: `The preflight read failed (${inputs.preflightError}). The list below may be missing blocking gates. This is a read failure, not a clean bill.`,
      source: `GET /revisions/${revisionId ?? '?'}/preflight`,
      view: 'simulation',
    });
  }
  if (inputs.integrityError) {
    push({
      id: 'integrity-unreadable',
      severity: 'warn',
      title: 'Run integrity verdicts unavailable',
      detail: `The integrity read failed (${inputs.integrityError}). Conservation findings below may be incomplete. This is a read failure, not a clean bill.`,
      source: `GET /runs/${data.latestRun?.run_id ?? '?'}/integrity`,
      view: 'simulation',
    });
  }

  // Staleness is a comparison, so it needs both sides. Without a revision
  // there is nothing for the draft to be stale against — that is its own
  // finding, raised below.
  if (data.dirty && revisionId) {
    push({
      id: 'stale-draft',
      severity: 'warn',
      title: 'Draft has uncompiled changes',
      detail: 'The draft design hash differs from the revision on screen. '
        + 'Every certified number below belongs to the compiled revision, not '
        + 'to the edits now in the draft.',
      source: 'draft.dirty vs revision',
      view: 'topology',
    });
  }

  const preflight = inputs.preflight;
  if (preflight) {
    for (const gate of preflight.gates) {
      if (gate.state === 'READY' || gate.state === 'QUALIFIED') continue;
      push({
        id: `preflight-${gate.gate}`,
        severity: 'bad',
        title: `Preflight gate ${gate.gate}: ${gate.state}`,
        detail: gate.reason ?? 'The gate did not report a reason.',
        source: `preflight.${gate.gate}`,
        view: 'simulation',
      });
    }
  }

  const run = data.run.result.state === 'ready' ? data.run.result.data : null;
  for (const entry of run?.requirements?.entries ?? []) {
    if (entry.verdict === 'SATISFIED') continue;
    push({
      id: `req-${entry.requirement_index}-${entry.traffic_class ?? 'fabric'}`,
      severity: entry.verdict === 'UNMEASURABLE' ? 'warn' : 'bad',
      title: `Requirement ${entry.traffic_class ?? 'fabric'}: ${entry.verdict}`,
      detail: entry.reason ?? 'No reason recorded by the RequirementReport.',
      source: `RequirementReport[${entry.requirement_index}]`,
      view: 'simulation',
    });
  }

  const integrity = inputs.integrity;
  const conservation = integrity
    ? [integrity.packet_conservation, integrity.flit_conservation]
      .filter((c): c is NonNullable<typeof c> => c != null)
    : [];
  for (const c of conservation) {
    if (c.verdict === 'CONSERVED' || c.verdict === 'NOT_MEASURED') continue;
    push({
      id: `conservation-${c.verdict}`,
      severity: 'bad',
      title: `${c.verdict === 'VIOLATED' ? 'Conservation violated' : 'Conservation unmeasured'}`,
      detail: 'The run\'s conservation check did not pass; measured counters '
        + 'below are not a complete account of the traffic.',
      source: 'RunIntegrityView',
      view: 'simulation',
    });
  }

  const resources = data.compileResult.result.state === 'ready'
    ? data.compileResult.result.data?.groups?.resources
    : null;
  const deadlock = resources?.deadlock;
  if (deadlock && deadlock.status !== 'PASS') {
    push({
      id: 'deadlock',
      severity: 'bad',
      title: `Deadlock proof ${deadlock.status}`,
      detail: `Method ${deadlock.method ?? 'unknown'}. The channel dependency `
        + 'graph did not come back acyclic.',
      source: 'compileResult.groups.resources.deadlock',
      view: 'topology',
    });
  }

  const certificate = data.compileResult.result.state === 'ready'
    ? data.compileResult.result.data?.groups?.summary?.certificate_overall
    : null;
  if (certificate && certificate !== 'PASS') {
    push({
      id: 'certificate',
      severity: 'bad',
      title: `Certificate ${certificate}`,
      detail: 'The revision was certified against obligations that did not all pass.',
      source: 'compileResult.groups.summary',
      view: 'topology',
    });
  }

  const traffic = data.traffic.result.state === 'ready' ? data.traffic.result.data : null;
  if (traffic && traffic.revision_id && revisionId && traffic.revision_id !== revisionId) {
    push({
      id: 'trace-revision',
      severity: 'warn',
      title: 'Trace belongs to a different revision',
      detail: `The counted matrix is from revision ${traffic.revision_id}, `
        + `not ${revisionId}. Its pairs may not exist on the fabric on screen.`,
      source: 'trafficMatrix.revision_id',
      view: 'access',
    });
  }

  if (!revisionId) {
    push({
      id: 'no-revision',
      severity: data.dirty ? 'info' : 'warn',
      title: 'No compiled revision',
      detail: 'This project has no certified revision, so no topology, route, '
        + 'domain crossing or timing figure exists to show.',
      source: 'project.active_revision_id',
      view: 'topology',
    });
  }

  const order: Record<ProblemSeverity, number> = { bad: 0, warn: 1, info: 2, ok: 3 };
  return out.sort((a, b) => order[a.severity] - order[b.severity]);
}
