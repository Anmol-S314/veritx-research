/** Loom selection contract tests (fixtures only — no engine, no network).
 *
 *  Selection is the one thing every tab shares, so it is the one thing that can
 *  quietly break everywhere. Four guarantees are pinned here:
 *
 *  1. IDENTITY. Every id is built from a canonical artifact field and
 *     round-trips through its own wire form. An id is never a row position, a
 *     display label or a selector, so a pasted URL keeps resolving when the
 *     sort order, the wording or the markup move.
 *  2. ONE OWNER. Selection is the URL. There is no second copy in component
 *     state anywhere in the workspace, which is a static invariant because a
 *     second copy is what drifts.
 *  3. STRUCTURE. A graph selection is a set and a record selection is one
 *     thing, and an id from the URL cannot make a record selection hold two
 *     entries or corrupt a graph one.
 *  4. PROVENANCE. The origin of a selected object comes from the SERVED
 *     vocabulary, and freshness for anything measured is the server's verdict.
 *     An origin the server does not assign stays unresolved instead of being
 *     filled in with one of the four words.
 */
import { describe, expect, it } from 'vitest';
import {
  agentId, agentKindId, capabilityId, carriedKinds, channelId, domainId,
  edgeId, hasId, loomHref, loomIdFromText, loomIdText, nodeId, pairId,
  pickId, PRIMARY_VIEW, provenanceOf, removeId, resolveAgainstData,
  resolveOrigin, selectOne, selectionFromQuery, selectionIds, selectionOf,
  selectionQuery, toggleGraph, VIEW_KINDS,
  type GraphId, type LoomId, type LoomSelection,
} from '../pages/loom/selection';
import type { LoomData, Query } from '../pages/loom/data';
import type { RunView, ValueProvenanceView } from '../api/types';
import type { TopologyView } from '../types';
import { SERVED_PROVENANCE } from './servedProvenance.fixture';

const ready = <T,>(data: T): Query<T> => ({ result: { state: 'ready', data } });
const absent = <T,>(data: T | null): Query<T> => ({
  result: { state: 'ready', data: data as T },
});
const failed = <T,>(message: string): Query<T> => ({
  result: { state: 'error', error: new Error(message) },
});

const VOCABULARY = SERVED_PROVENANCE;

const TOPOLOGY: TopologyView = {
  contract_version: 1,
  revision_id: 'r-7',
  design_hash: 'sha256:d',
  topology_hash: 'sha256:t',
  attachment_hash: 'sha256:a',
  family: 'mesh',
  routers: [
    { router_id: 0, coordinates: [0, 0], seat_capacity: 1 },
    { router_id: 1, coordinates: [0, 1], seat_capacity: 1 },
    { router_id: 2, coordinates: [1, 0], seat_capacity: 1 },
  ],
  channels: [
    { channel_id: 0, src_router: 0, src_port: 1, dst_router: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 1, src_router: 0, src_port: 2, dst_router: 2, dst_port: 1, width_bits: 64, latency_cycles: 1 },
  ],
  physical_links: [],
  endpoints: [
    { endpoint_id: 40, kind: 'compute_tile', group_index: 0, instance_index: 0, router_id: 0, port_id: 0 },
  ],
  counts: { routers: 3, channels: 2, seats: 3, endpoints: 1 },
};

function loom(over: Partial<LoomData> = {}): LoomData {
  return {
    projectId: 'p-1',
    project: null,
    design: null,
    designHash: null,
    revisionId: 'r-7',
    basedOnRevisionId: 'r-7',
    dirty: false,
    draftRequest: null,
    reloadDraft: () => {},
    agents: [
      {
        kind: 'compute_tile', count: 2, data_width: 256, addr_width: 64,
        protocol: 'AXI', clock_domain: 'clk_a', power_domain: 'pd_0',
      },
    ],
    topology: ready(TOPOLOGY),
    compileResult: absent(null),
    latestRun: null,
    run: absent(null),
    traffic: absent(null),
    trafficUnavailable: null,
    lowering: absent(null),
    provenance: ready(VOCABULARY),
    ...over,
  };
}

const RUN: RunView = {
  contract_version: 1,
  run_id: 'run-7',
  project_id: 'p-1',
  revision_id: 'r-7',
  display_name: null,
  design_hash: 'sha256:d',
  backend: 'BOOKSIM_STANDALONE',
  status: 'EVALUATED',
  qualification: 'CERTIFIED',
  requirements_pass: true,
  started_at: null,
  completed_at: null,
  bundle_id: null,
  workload_id: null,
  completion_cycles: null,
  qualification_basis: null,
  evaluation: null,
  requirements: null,
  evaluation_plan: null,
  analyses: null,
  producer: null,
  evidence: null,
  reason: null,
  freshness: {
    state: 'CURRENT',
    meaning: 'This result was produced from the design currently on screen.',
    run_revision_id: 'r-7',
    active_revision_id: 'r-7',
    draft_dirty: false,
    draft_design_hash: 'sha256:d',
    run_design_hash: 'sha256:d',
  },
};

describe('ids are canonical and round-trip', () => {
  const cases: LoomId[] = [
    nodeId(3),
    channelId(41),
    edgeId(12, 18),
    agentId(0, 5),
    agentKindId('verification.deadlock_certificate'),
    domainId('clock', 'clk_a'),
    domainId('power', 'pd_0'),
    pairId(2, 9),
    capabilityId('topology.srota'),
  ];

  it('writes and re-reads every kind', () => {
    for (const id of cases) {
      expect(loomIdFromText(loomIdText(id))).toEqual(id);
    }
  });

  it('namespaces the kinds so one can never be read as another', () => {
    expect(loomIdText(nodeId(3))).toBe('node:3');
    expect(loomIdText(edgeId(12, 18))).toBe('edge:12-18');
    expect(loomIdText(agentId(0, 5))).toBe('agent:g0-i5');
    expect(loomIdText(capabilityId('topology.srota')))
      .toBe('capability:topology.srota');
    // A capability id is never a node id, however it is read.
    expect(loomIdFromText('node:topology.srota')).toBeNull();
  });

  it('canonicalises an unordered adjacency so either end names one object', () => {
    expect(loomIdText(edgeId(18, 12))).toBe('edge:12-18');
    expect(edgeId(18, 12)).toEqual(edgeId(12, 18));
    expect(hasId(selectionOf([edgeId(12, 18)]), edgeId(18, 12))).toBe(true);
  });

  it('rejects a malformed id instead of coercing it', () => {
    for (const bad of [
      'node:', 'node:-1', 'node:1.5', 'node:01a', 'channel:',
      'edge:4', 'edge:4-', 'edge:7-7', 'agent:g0', 'agent:g-i',
      'domain:', 'domain:thermal:pd_0', 'pair:3-4', 'pair:2->2',
      'capability:', 'router:3', 'selection:node:3', ':3',
    ]) {
      expect(loomIdFromText(bad)).toBeNull();
    }
  });

  it('never lets a self-pair or a self-adjacency through', () => {
    // Self-traffic crosses no channel and a router is not adjacent to itself,
    // so neither is an object any artifact holds.
    expect(loomIdFromText('pair:4->4')).toBeNull();
    expect(loomIdFromText('edge:9-9')).toBeNull();
  });
});

describe('the URL is the store', () => {
  it('round-trips a graph set through the query string', () => {
    const selection = selectionOf([edgeId(3, 4), nodeId(1), channelId(7)]);
    const query = selectionQuery(selection);
    expect(query).toMatch(/^sel=/);
    expect(selectionFromQuery(`?${query}`).selection).toEqual(selection);
  });

  it('round-trips a single record', () => {
    const selection = selectionOf([agentKindId('compute_tile')]);
    expect(selectionFromQuery(selectionQuery(selection)).selection)
      .toEqual(selection);
  });

  it('writes nothing at all for an empty selection', () => {
    expect(selectionQuery({ mode: 'empty' })).toBe('');
    expect(selectionFromQuery('').selection).toEqual({ mode: 'empty' });
  });

  it('keeps the tab while carrying the selection', () => {
    const selection = selectionOf([nodeId(4), nodeId(5)]);
    expect(loomHref('p-1', 'floorplan', selection)).toBe(
      '/projects/p-1/loom/floorplan?sel=node:4,node:5',
    );
  });

  it('orders graph ids so the same set yields the same address', () => {
    const a = selectionOf([channelId(2), nodeId(9), edgeId(1, 2)]);
    const b = selectionOf([edgeId(1, 2), nodeId(9), channelId(2)]);
    expect(selectionQuery(a)).toBe(selectionQuery(b));
  });

  it('does not let an encoded comma inside a key forge a second id', () => {
    // A capability id carrying a comma must survive as ONE id, not split into
    // two selections by the separator.
    const weird = capabilityId('a,b');
    const parsed = selectionFromQuery(`?${selectionQuery(selectionOf([weird]))}`);
    expect(parsed.rejected).toEqual([]);
    expect(parsed.selection).toEqual(selectionOf([weird]));
  });

  it('drops an unparseable id and says why, rather than resolving it', () => {
    const parsed = selectionFromQuery('?sel=node:1,node:zzz,router:4');
    expect(selectionIds(parsed.selection).map(loomIdText)).toEqual(['node:1']);
    expect(parsed.rejected.map((r) => r.text)).toEqual(['node:zzz', 'router:4']);
    expect(parsed.rejected[0].why).toMatch(/not a canonical Loom id/);
  });

  it('refuses to hold a record and a graph set at once', () => {
    const parsed = selectionFromQuery('?sel=node:1,kind:nic');
    expect(parsed.selection).toEqual(selectionOf([agentKindId('nic')]));
    expect(parsed.rejected.map((r) => r.text)).toEqual(['node:1']);
    expect(parsed.rejected[0].why).toMatch(/cannot both be the selection/);
  });

  it('refuses to hold two records, and names the one it kept', () => {
    // Two record ids is the same defect as one record plus a graph set: the
    // selection is one thing. Silently keeping the first would be a selection
    // the address bar does not describe.
    const parsed = selectionFromQuery('?sel=kind:nic,pair:1->2');
    expect(parsed.selection).toEqual(selectionOf([agentKindId('nic')]));
    expect(parsed.rejected.map((r) => r.text)).toEqual(['pair:1->2']);
    expect(parsed.rejected[0].why).toMatch(/one selection names one record/);
  });

  it('reports no rejection for a graph set with a repeated id', () => {
    // The same id twice is the same set, not a contradiction.
    const parsed = selectionFromQuery('?sel=node:1,node:1,node:2');
    expect(parsed.selection).toEqual(selectionOf([nodeId(1), nodeId(2)]));
    expect(parsed.rejected).toEqual([]);
  });
});

describe('a graph is a set, a record is one thing', () => {
  it('accumulates graph objects and collapses duplicates', () => {
    let selection: LoomSelection = { mode: 'empty' };
    selection = toggleGraph(selection, nodeId(1));
    selection = toggleGraph(selection, nodeId(2));
    selection = toggleGraph(selection, nodeId(1));
    expect(selectionIds(selection).map(loomIdText)).toEqual(['node:2']);
  });

  it('removes on a second additive gesture', () => {
    const held = selectionOf([nodeId(1), nodeId(2)]);
    expect(toggleGraph(held, nodeId(1))).toEqual(selectionOf([nodeId(2)]));
  });

  it('drops the whole set when a record is selected plainly', () => {
    const held = selectionOf([nodeId(1), nodeId(2)]);
    expect(selectOne(held, agentId(0, 0))).toEqual(selectionOf([agentId(0, 0)]));
  });

  it('removes one object without disturbing the rest', () => {
    const held = selectionOf([nodeId(1), nodeId(2), channelId(3)]);
    const after = removeId(held, nodeId(2));
    expect(after.mode).toBe('graph');
    expect(selectionIds(after).map(loomIdText)).toEqual(['node:1', 'channel:3']);
  });

  it('picks one kind out of either mode', () => {
    expect(pickId(selectionOf([nodeId(5)]), 'node')?.routerId).toBe(5);
    expect(pickId(selectionOf([channelId(5)]), 'channel')?.channelId).toBe(5);
    expect(pickId(selectionOf([nodeId(5)]), 'kind')).toBeNull();
  });
});

describe('every kind has a home and every home is listed', () => {
  const all: GraphId[] = [nodeId(0), channelId(0), edgeId(0, 1)];

  it('routes every kind to a view that carries it', () => {
    for (const id of [...all, agentId(0, 0), agentKindId('nic'), domainId('clock', 'c'), pairId(0, 1), capabilityId('x')]) {
      const home = PRIMARY_VIEW[id.kind];
      expect(carriedKinds(home)).toContain(id.kind);
    }
  });

  it('names a view for every kind it declares', () => {
    for (const [view, kinds] of Object.entries(VIEW_KINDS)) {
      for (const kind of kinds) expect(PRIMARY_VIEW[kind]).toBeDefined();
      expect(view.length).toBeGreaterThan(0);
    }
  });
});

describe('origin is resolved from the served vocabulary', () => {
  it('accepts a mapping the server actually makes', () => {
    expect(resolveOrigin(VOCABULARY, null, 'topology', 'DERIVED'))
      .toEqual({ origin: 'DERIVED', why: null });
    expect(resolveOrigin(VOCABULARY, null, 'draft', 'AUTHORED').origin)
      .toBe('AUTHORED');
    expect(resolveOrigin(VOCABULARY, null, 'traffic_matrix', 'MEASURED').origin)
      .toBe('MEASURED');
  });

  it('refuses a mapping the server does not make', () => {
    const wrong = resolveOrigin(VOCABULARY, null, 'topology', 'MEASURED');
    expect(wrong.origin).toBeNull();
    expect(wrong.why).toMatch(/DERIVED/);
  });

  it('refuses an artifact kind the server does not declare', () => {
    const unknown = resolveOrigin(VOCABULARY, null, 'heatmap', 'DERIVED');
    expect(unknown.origin).toBeNull();
    expect(unknown.why).toMatch(/not an artifact kind/);
  });

  it('refuses rather than guessing when the vocabulary is unreadable', () => {
    const missing = resolveOrigin(null, 'HTTP 503', 'topology', 'DERIVED');
    expect(missing.origin).toBeNull();
    expect(missing.why).toMatch(/unreadable/);
    expect(resolveOrigin(null, null, 'topology', 'DERIVED').origin).toBeNull();
  });

  it('resolves a capability to DERIVED because the server says so', () => {
    // `capability` used to be a declared artifact kind that NO origin mapped
    // to, so the UI rendered ORIGIN ?. The registry is produced by RUNNING the
    // compiler, so the server now maps it to DERIVED — and the client follows
    // the map, not the memory. If the server ever stops mapping it, this test
    // fails and the UI goes back to saying so.
    const resolved = resolveOrigin(VOCABULARY, null, 'capability', 'DERIVED');
    expect(resolved.origin).toBe('DERIVED');
    expect(resolved.why).toBeNull();
    const provenance = provenanceOf(capabilityId('topology.srota'), loom());
    expect(provenance.origin).toBe('DERIVED');
    expect(provenance.artifactKind).toBe('capability');
  });

  it('still reports an unmapped kind instead of filling it in', () => {
    const gap = resolveOrigin(VOCABULARY, null, 'not_a_kind', null);
    expect(gap.origin).toBeNull();
    expect(gap.why).toMatch(/not an artifact kind/);
  });
});

describe('provenance names the artifact and the revision', () => {
  it('calls a router and a channel compiler-derived', () => {
    const router = provenanceOf(nodeId(3), loom());
    expect(router.origin).toBe('DERIVED');
    expect(router.artifactKind).toBe('topology');
    expect(router.artifactRef).toBe('topology.routers[router_id=3]');
    expect(router.revisionId).toBe('r-7');
    expect(router.freshness.state).toBe('CURRENT');
    expect(router.freshness.basis).toBe('identity');
    expect(router.runId).toBeNull();

    const channel = provenanceOf(channelId(3), loom());
    expect(channel.origin).toBe('DERIVED');
    expect(channel.artifactRef).toBe('topology.channels[channel_id=3]');
  });

  it('calls an agent instance and a domain authored intent', () => {
    const agent = provenanceOf(agentId(0, 5), loom());
    expect(agent.origin).toBe('AUTHORED');
    expect(agent.artifactKind).toBe('draft');
    expect(agent.runId).toBeNull();
    // A draft is not a revision-scoped artifact, so no freshness verdict is
    // claimed for it and the reason is given.
    expect(agent.freshness.state).toBe('NOT_APPLICABLE');

    const domain = provenanceOf(domainId('power', 'pd_0'), loom());
    expect(domain.origin).toBe('AUTHORED');
    expect(domain.artifactRef).toContain('power_domain=pd_0');
  });

  it('carries the server verdict and the server sentence for a measurement', () => {
    const provenance = provenanceOf(pairId(0, 1), loom({ run: ready(RUN) }));
    expect(provenance.origin).toBe('MEASURED');
    expect(provenance.runId).toBe('run-7');
    expect(provenance.revisionId).toBe('r-7');
    expect(provenance.freshness.state).toBe('CURRENT');
    expect(provenance.freshness.basis).toBe('server');
    expect(provenance.freshness.note).toBe(RUN.freshness?.meaning);
  });

  it('carries a STALE verdict through without softening it', () => {
    const stale = {
      ...RUN,
      freshness: { ...RUN.freshness!, state: 'STALE' as const },
    };
    const provenance = provenanceOf(pairId(0, 1), loom({ run: ready(stale) }));
    expect(provenance.freshness.state).toBe('STALE');
  });

  it('will not compute a freshness verdict the server did not send', () => {
    const without: RunView = { ...RUN, freshness: undefined };
    const provenance = provenanceOf(pairId(0, 1), loom({ run: ready(without) }));
    expect(provenance.freshness.state).toBe('UNKNOWN');
    expect(provenance.freshness.note).toMatch(/does not compute one/);
  });

  it('says UNKNOWN rather than CURRENT when the run cannot be read', () => {
    const loading = provenanceOf(pairId(0, 1), loom({ run: failed<RunView | null>('boom') }));
    expect(loading.freshness.state).toBe('UNKNOWN');
    expect(loading.freshness.note).toMatch(/unreadable/);
  });

  it('does not call a revision-scoped object CURRENT on a failed read', () => {
    const provenance = provenanceOf(nodeId(3), loom({
      topology: failed<TopologyView | null>('HTTP 500'),
    }));
    expect(provenance.freshness.state).toBe('UNKNOWN');
    expect(provenance.revisionId).toBeNull();
  });

  it('reports a topology read against another revision as FOREIGN_REVISION', () => {
    const provenance = provenanceOf(nodeId(3), loom({
      topology: ready({ ...TOPOLOGY, revision_id: 'r-3' }),
    }));
    expect(provenance.revisionId).toBe('r-3');
    expect(provenance.freshness.state).toBe('FOREIGN_REVISION');
  });

  it('leaves an origin unresolved while the vocabulary is still loading', () => {
    const provenance = provenanceOf(nodeId(3), loom({
      provenance: ready(null as unknown as ValueProvenanceView),
    }));
    expect(provenance.origin).toBeNull();
    expect(provenance.originWhy).toMatch(/has not been read/);
  });
});

describe('an id the artifacts do not hold is stated, not drawn', () => {
  it('resolves an id the revision has', () => {
    const data = loom();
    expect(resolveAgainstData(nodeId(1), data).present).toBe(true);
    expect(resolveAgainstData(channelId(1), data).present).toBe(true);
    expect(resolveAgainstData(edgeId(0, 1), data).present).toBe(true);
    expect(resolveAgainstData(agentId(0, 1), data).present).toBe(true);
  });

  it('names why a router, an instance or a domain is unresolvable', () => {
    const data = loom();
    expect(resolveAgainstData(nodeId(99), data).why).toMatch(/not in this revision/);
    expect(resolveAgainstData(channelId(99), data).why).toMatch(/not in this revision/);
    expect(resolveAgainstData(edgeId(1, 2), data).why).toMatch(/no channel joins/);
    expect(resolveAgainstData(agentId(0, 9), data).why).toMatch(/declares 2 instance/);
    expect(resolveAgainstData(agentId(7, 0), data).why).toMatch(/no agent group 7/);
    expect(resolveAgainstData(domainId('clock', 'nope'), data).why)
      .toMatch(/no agent names/);
  });

  it('answers a measured pair only from an executed trace', () => {
    const without = loom();
    expect(resolveAgainstData(pairId(0, 1), without).present).toBe(false);
    expect(resolveAgainstData(pairId(0, 1), without).why).toMatch(/no measured matrix/);
  });
});