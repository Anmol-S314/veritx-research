/** ── The Loom selection model ────────────────────────────────────────────
 *
 *  ONE store, ONE owner: the URL. Selection is not React state anywhere in the
 *  workspace, so it cannot drift from the address bar, it survives a tab change
 *  without being carried across in memory, and a pasted URL reproduces exactly
 *  what its sender was looking at. `selectionStore.ts` owns the write side.
 *
 *  Every id is derived from a canonical artifact field — a `router_id`, a
 *  `channel_id`, the compiler's own `(group_index, instance_index)` join key,
 *  an authored domain name, a measured pair, a registry capability id. Never
 *  from a row's position in a rendered table, never from a display label,
 *  never from a CSS selector: all three move when the sort order, the wording
 *  or the markup changes, and a deep link that survives one of those is luck
 *  rather than a guarantee.
 *
 *  Each kind is a distinct TypeScript type, so a `capability:` id cannot be
 *  handed to a function that wants a `node:` id — the compiler says so, and
 *  the wire format says so too.
 */
import type { RunView, ValueProvenanceView } from '../../api';
import type { LoomData, LoomViewId } from './data';

export const SEL_PARAM = 'sel';

// ── ids ──────────────────────────────────────────────────────────────────

/** A vertex of the certified TopologyArtifact. */
export interface NodeId { kind: 'node'; routerId: number }

/** One directed channel of the certified TopologyArtifact. */
export interface ChannelId { kind: 'channel'; channelId: number }

/** The undirected adjacency two routers form. The drawn link is NOT a channel:
 *  a mesh adjacency carries one channel per direction. */
export interface EdgeId { kind: 'edge'; src: number; dst: number }

/** One declared agent instance, keyed by the compiler's own join key rather
 *  than by an `endpoint_id`, which is renumbered on every compilation. */
export interface AgentId {
  kind: 'agent'; groupIndex: number; instanceIndex: number;
}

/** A member of the engine's closed `AgentKind` enum. */
export interface KindId { kind: 'kind'; agentKind: string }

/** A clock or power domain the author named on the draft. */
export interface DomainId {
  kind: 'domain'; axis: 'clock' | 'power'; domain: string;
}

/** One measured cell of the executed trace: an endpoint pair and its counts. */
export interface PairId { kind: 'pair'; src: number; dst: number }

/** One row of the server's capability registry. */
export interface CapabilityId { kind: 'capability'; capabilityId: string }

/** Vertices and edges of the one graph the compiler emits. */
export type GraphId = NodeId | ChannelId | EdgeId;

/** A single record in a table or in a registry. */
export type RecordId = AgentId | KindId | DomainId | PairId | CapabilityId;

export type LoomId = GraphId | RecordId;

export type LoomIdKind = LoomId['kind'];

export function nodeId(routerId: number): NodeId {
  return { kind: 'node', routerId };
}

export function channelId(channel: number): ChannelId {
  return { kind: 'channel', channelId: channel };
}

/** Adjacency is unordered, so the id canonicalises to the ascending pair:
 *  `edge:3-1` and `edge:1-3` are one object and one URL. */
export function edgeId(a: number, b: number): EdgeId {
  return a <= b
    ? { kind: 'edge', src: a, dst: b }
    : { kind: 'edge', src: b, dst: a };
}

export function agentId(groupIndex: number, instanceIndex: number): AgentId {
  return { kind: 'agent', groupIndex, instanceIndex };
}

export function agentKindId(agentKind: string): KindId {
  return { kind: 'kind', agentKind };
}

export function domainId(axis: 'clock' | 'power', domain: string): DomainId {
  return { kind: 'domain', axis, domain };
}

export function pairId(src: number, dst: number): PairId {
  return { kind: 'pair', src, dst };
}

export function capabilityId(capability: string): CapabilityId {
  return { kind: 'capability', capabilityId: capability };
}

export function isGraphId(id: LoomId): id is GraphId {
  return id.kind === 'node' || id.kind === 'channel' || id.kind === 'edge';
}

export function isRecordId(id: LoomId): id is RecordId {
  return !isGraphId(id);
}

/** The wire form: `<kind>:<key>`, where the key is always a canonical artifact
 *  field. Round-trips through `loomIdFromText`. */
export function loomIdText(id: LoomId): string {
  switch (id.kind) {
    case 'node': return `node:${id.routerId}`;
    case 'channel': return `channel:${id.channelId}`;
    case 'edge': return `edge:${id.src}-${id.dst}`;
    case 'agent': return `agent:g${id.groupIndex}-i${id.instanceIndex}`;
    case 'kind': return `kind:${id.agentKind}`;
    case 'domain': return `domain:${id.axis}:${id.domain}`;
    case 'pair': return `pair:${id.src}->${id.dst}`;
    case 'capability': return `capability:${id.capabilityId}`;
  }
}

/** What kind of thing an id names. Presentation vocabulary only: no status and
 *  no verdict is decided here. */
const NOUN: Record<LoomIdKind, string> = {
  node: 'router',
  channel: 'directed channel',
  edge: 'router adjacency',
  agent: 'agent instance',
  kind: 'agent kind',
  domain: 'domain',
  pair: 'measured pair',
  capability: 'capability',
};

export function nounOf(id: LoomId): string {
  return NOUN[id.kind];
}

// ── parsing ──────────────────────────────────────────────────────────────

/** An id from a URL is untrusted input, so every field is validated rather
 *  than cast. An unparseable id is dropped and reported — never coerced into
 *  something that would render as a real object. */
function uint(token: string): number | null {
  if (!/^\d{1,9}$/.test(token)) return null;
  const value = Number(token);
  return Number.isSafeInteger(value) ? value : null;
}

const EDGE_BODY = /^(\d+)-(\d+)$/;
const AGENT_BODY = /^g(\d+)-i(\d+)$/;
const PAIR_BODY = /^(\d+)->(\d+)$/;

export function loomIdFromText(text: string): LoomId | null {
  const sep = text.indexOf(':');
  if (sep < 0) return null;
  const kind = text.slice(0, sep);
  const key = text.slice(sep + 1);
  switch (kind) {
    case 'node': {
      const routerId = uint(key);
      return routerId === null ? null : nodeId(routerId);
    }
    case 'channel': {
      const channel = uint(key);
      return channel === null ? null : channelId(channel);
    }
    case 'edge': {
      const parts = EDGE_BODY.exec(key);
      if (!parts) return null;
      const a = uint(parts[1]);
      const b = uint(parts[2]);
      if (a === null || b === null || a === b) return null;
      return edgeId(a, b);
    }
    case 'agent': {
      const parts = AGENT_BODY.exec(key);
      if (!parts) return null;
      const groupIndex = uint(parts[1]);
      const instanceIndex = uint(parts[2]);
      if (groupIndex === null || instanceIndex === null) return null;
      return agentId(groupIndex, instanceIndex);
    }
    case 'kind':
      return key ? agentKindId(key) : null;
    case 'domain': {
      const cut = key.indexOf(':');
      if (cut < 0) return null;
      const axis = key.slice(0, cut);
      const domain = key.slice(cut + 1);
      if (axis !== 'clock' && axis !== 'power') return null;
      return domain ? domainId(axis, domain) : null;
    }
    case 'pair': {
      const parts = PAIR_BODY.exec(key);
      if (!parts) return null;
      const src = uint(parts[1]);
      const dst = uint(parts[2]);
      if (src === null || dst === null || src === dst) return null;
      return pairId(src, dst);
    }
    case 'capability':
      return key ? capabilityId(key) : null;
    default:
      return null;
  }
}

// ── the selection ────────────────────────────────────────────────────────

/** A graph is a set; a record is one thing.
 *
 *  Node, channel and adjacency are the vertices and edges of the ONE graph the
 *  compiler emits, and the questions an engineer asks of a graph — what a cut
 *  separates, which channels a set of routers spans — are questions about sets,
 *  so they get a set. Every other selectable thing is a single record in a
 *  table or a registry whose artifact carries no aggregate over a set of its
 *  own instances, so a set of those would be a UI invention with nothing behind
 *  it. The type states which is which, so a record selection cannot arrive
 *  holding two entries.
 *
 *  Not a selection: a view's own filters, its mode toggles, and the catalog's
 *  compare basket. Those change what a panel shows; none of them names an
 *  object for an inspector, and a basket of three kinds has no meaning that
 *  any artifact carries.
 */
export type LoomSelection =
  | { mode: 'empty' }
  | { mode: 'record'; id: RecordId }
  | { mode: 'graph'; ids: GraphId[] };

const GRAPH_RANK: Record<GraphId['kind'], number> = { node: 0, channel: 1, edge: 2 };

function graphOrder(a: GraphId, b: GraphId): number {
  const rank = GRAPH_RANK[a.kind] - GRAPH_RANK[b.kind];
  if (rank !== 0) return rank;
  const left = loomIdText(a);
  const right = loomIdText(b);
  return left < right ? -1 : left > right ? 1 : 0;
}

/** Fold a loose id list into the canonical selection. A record displaces any
 *  graph ids: the URL cannot say "this router and this capability". */
export function selectionOf(ids: readonly LoomId[]): LoomSelection {
  const record = ids.find(isRecordId);
  if (record) return { mode: 'record', id: record };
  const held = new Map<string, GraphId>();
  for (const id of ids) {
    if (isGraphId(id)) held.set(loomIdText(id), id);
  }
  const unique = [...held.values()].sort(graphOrder);
  return unique.length === 0
    ? { mode: 'empty' }
    : { mode: 'graph', ids: unique };
}

export function selectionIds(selection: LoomSelection): LoomId[] {
  if (selection.mode === 'record') return [selection.id];
  return selection.mode === 'graph' ? selection.ids : [];
}

export function hasId(selection: LoomSelection, id: LoomId): boolean {
  const key = loomIdText(id);
  return selectionIds(selection).some((held) => loomIdText(held) === key);
}

/** The one held id of a given kind, whichever mode holds it. A record
 *  inspector calls this with its own kind and gets that kind or null. */
export function pickId<K extends LoomIdKind>(
  selection: LoomSelection,
  kind: K,
): Extract<LoomId, { kind: K }> | null {
  const held = selectionIds(selection).find((id) => id.kind === kind);
  return (held as Extract<LoomId, { kind: K }> | undefined) ?? null;
}

/** Replacing the selection with one object. The held set is named so the
 *  intent reads as "this object replaces whatever was selected", which is what
 *  a plain click means on both a graph and a table. */
export function selectOne(_current: LoomSelection, id: LoomId): LoomSelection {
  return selectionOf([id]);
}

/** The additive gesture on a graph: add, or remove when already held. */
export function toggleGraph(current: LoomSelection, id: GraphId): LoomSelection {
  const key = loomIdText(id);
  const held = selectionIds(current);
  return selectionOf(
    held.some((x) => loomIdText(x) === key)
      ? held.filter((x) => loomIdText(x) !== key)
      : [...held, id],
  );
}

export function removeId(current: LoomSelection, id: LoomId): LoomSelection {
  const key = loomIdText(id);
  return selectionOf(selectionIds(current).filter((x) => loomIdText(x) !== key));
}

// ── URL codec ────────────────────────────────────────────────────────────

export interface RejectedId { text: string; why: string }

export interface ParsedSelection {
  selection: LoomSelection;
  /** Ids this URL named that are not part of a valid selection. Dropped and
   *  counted, never coerced. */
  rejected: RejectedId[];
}

/** Read one query parameter WITHOUT decoding it. `URLSearchParams` would decode
 *  the whole value first, which turns an escaped `%2C` back into the separator
 *  and makes a comma inside a key forge a second id. Each id is therefore
 *  decoded on its own, after the split. */
function rawParam(search: string, name: string): string | null {
  const query = search.startsWith('?') ? search.slice(1) : search;
  for (const part of query.split('&')) {
    if (!part) continue;
    const eq = part.indexOf('=');
    const key = eq < 0 ? part : part.slice(0, eq);
    let decoded: string;
    try {
      decoded = decodeURIComponent(key);
    } catch {
      continue;
    }
    if (decoded !== name) continue;
    return eq < 0 ? '' : part.slice(eq + 1);
  }
  return null;
}

/** Fold an id list into the canonical selection and report EVERY id the fold
 *  discarded. A URL can name a record and a graph set, or two records; either
 *  way one id does not survive, and saying so is the difference between a
 *  selection and a silent narrowing. */
function foldAccepted(accepted: LoomId[]): ParsedSelection {
  const seen = new Set<string>();
  const distinct = accepted.filter((id) => {
    const key = loomIdText(id);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const selection = selectionOf(distinct);
  const kept = new Set(selectionIds(selection).map(loomIdText));
  const dropped = distinct.filter((id) => !kept.has(loomIdText(id)));
  if (dropped.length === 0) return { selection, rejected: [] };
  return {
    selection,
    rejected: dropped.map((id) => ({
      text: loomIdText(id),
      why: selection.mode === 'record'
        ? (isGraphId(id)
          ? 'dropped: a record selection and a graph selection cannot both be the selection'
          : 'dropped: one selection names one record; the first one named is kept')
        : 'dropped: it is not one of the objects this selection holds',
    })),
  };
}

export function selectionFromQuery(search: string): ParsedSelection {
  const raw = rawParam(search, SEL_PARAM);
  if (raw === null || raw === '') {
    return { selection: { mode: 'empty' }, rejected: [] };
  }
  const accepted: LoomId[] = [];
  const rejected: RejectedId[] = [];
  for (const part of raw.split(',')) {
    if (!part) continue;
    let text: string;
    try {
      text = decodeURIComponent(part);
    } catch {
      rejected.push({ text: part, why: 'the id is not valid percent-encoding' });
      continue;
    }
    const id = loomIdFromText(text);
    if (id) accepted.push(id);
    else rejected.push({ text, why: 'not a canonical Loom id' });
  }
  const folded = foldAccepted(accepted);
  return { selection: folded.selection, rejected: [...rejected, ...folded.rejected] };
}

/** Percent-encode an id for the query, keeping the namespace colon legible: a
 *  deep link gets pasted into a chat window and read by a person as well as
 *  parsed. A comma inside an id stays `%2C`, which is exactly what stops it
 *  forging a separator. */
function encodeId(text: string): string {
  return encodeURIComponent(text).replace(/%3A/gi, ':');
}

/** Each id is encoded on its own and the parts are joined with a bare comma,
 *  so the separator is unambiguous. */
export function selectionQuery(selection: LoomSelection): string {
  const ids = selectionIds(selection);
  if (ids.length === 0) return '';
  return `${SEL_PARAM}=${ids.map((id) => encodeId(loomIdText(id))).join(',')}`;
}

export function loomHref(
  projectId: string,
  view: LoomViewId,
  selection: LoomSelection,
): string {
  const query = selectionQuery(selection);
  return `/projects/${projectId}/loom/${view}${query ? `?${query}` : ''}`;
}

// ── which views carry which objects ──────────────────────────────────────

/** Where a kind of object can be inspected. Purely routing: which view has a
 *  panel for the id, never anything about the id's standing. */
export const PRIMARY_VIEW: Record<LoomIdKind, LoomViewId> = {
  node: 'topology',
  channel: 'topology',
  edge: 'floorplan',
  agent: 'agents',
  kind: 'catalog',
  domain: 'domains',
  pair: 'access',
  capability: 'capability',
};

/** Exactly what each view renders, no more. A selection outside this set is NOT
 *  dropped on a tab change: it stays in the URL, and the selection bar names
 *  the view that does carry it. */
export const VIEW_KINDS: Record<LoomViewId, LoomIdKind[]> = {
  topology: ['node', 'channel', 'agent'],
  agents: ['agent'],
  catalog: ['kind'],
  domains: ['domain', 'channel'],
  access: ['pair'],
  floorplan: ['edge'],
  workload: [],
  simulation: ['channel', 'pair'],
  capability: ['capability'],
};

export function carriedKinds(view: LoomViewId): LoomIdKind[] {
  return VIEW_KINDS[view];
}

// ── provenance ───────────────────────────────────────────────────────────

/** Which artifact an id is read out of, and — for every kind but one — the
 *  origin the served vocabulary is expected to map that artifact to. The
 *  expectation is CHECKED against the server's `origin_artifacts`, never
 *  assumed: a mapping the server does not make leaves the origin unresolved
 *  rather than invented. */
const SELECTION_SOURCE: Record<LoomIdKind, {
  artifactKind: string;
  origin: string | null;
  read: (id: LoomId) => string;
}> = {
  node: {
    artifactKind: 'topology',
    origin: 'DERIVED',
    read: (id) => `topology.routers[router_id=${(id as NodeId).routerId}]`,
  },
  channel: {
    artifactKind: 'topology',
    origin: 'DERIVED',
    read: (id) => `topology.channels[channel_id=${(id as ChannelId).channelId}]`,
  },
  edge: {
    artifactKind: 'topology',
    origin: 'DERIVED',
    read: (id) => {
      const edge = id as EdgeId;
      return `topology.channels between R${edge.src} and R${edge.dst}`;
    },
  },
  agent: {
    artifactKind: 'draft',
    origin: 'AUTHORED',
    read: (id) => {
      const agent = id as AgentId;
      return `draft.agents[group_index=${agent.groupIndex}]`
        + `.instance[${agent.instanceIndex}]`;
    },
  },
  kind: {
    artifactKind: 'draft',
    origin: 'AUTHORED',
    read: (id) => `draft.agents[kind=${(id as KindId).agentKind}]`,
  },
  domain: {
    artifactKind: 'draft',
    origin: 'AUTHORED',
    read: (id) => {
      const domain = id as DomainId;
      return `draft.agents[].${domain.axis}_domain=${domain.domain}`;
    },
  },
  pair: {
    artifactKind: 'traffic_matrix',
    origin: 'MEASURED',
    read: (id) => {
      const pair = id as PairId;
      return `traffic_matrix.pairs[src=${pair.src}][dst=${pair.dst}]`;
    },
  },
  capability: {
    // A capability status is produced by RUNNING the compiler:
    // capability_truth.derive_all_stages() invokes the topology families, the
    // profile selector and the execution handlers and reports the authority
    // string each one returned. That makes it DERIVED, and the served
    // `origin_artifacts` map now says so. `origin` stays an EXPECTATION that
    // is checked against that map below, never a value the client supplies.
    artifactKind: 'capability',
    origin: 'DERIVED',
    read: (id) => (
      `loom_capabilities.capabilities[id=${(id as CapabilityId).capabilityId}]`
    ),
  },
};

export interface OriginResolution {
  origin: string | null;
  why: string | null;
}

/** Resolve the origin from the SERVED vocabulary. The client holds no
 *  origin→artifact table of its own: one is exactly how a second authority
 *  appears, and this is where it would appear. */
export function resolveOrigin(
  vocabulary: ValueProvenanceView | null,
  error: string | null,
  artifactKind: string,
  declared: string | null,
): OriginResolution {
  if (!vocabulary) {
    return {
      origin: null,
      why: error
        ? `the served provenance vocabulary is unreadable (${error}), `
          + 'so no origin can be resolved'
        : 'the provenance vocabulary has not been read yet',
    };
  }
  if (!vocabulary.artifact_kinds.includes(artifactKind)) {
    return {
      origin: null,
      why: `'${artifactKind}' is not an artifact kind in the served vocabulary`,
    };
  }
  const owners = vocabulary.origins.filter((origin) => (
    (vocabulary.origin_artifacts[origin] ?? []).includes(artifactKind)
  ));
  if (declared && owners.includes(declared)) return { origin: declared, why: null };
  if (owners.length > 0) {
    return {
      origin: null,
      why: `the served vocabulary maps a '${artifactKind}' artifact to `
        + `${owners.join(' / ')}, not to ${declared ?? 'any origin this client declares'}`,
    };
  }
  return {
    origin: null,
    why: `the served vocabulary assigns no origin to a '${artifactKind}' artifact`,
  };
}

export interface SelectionFreshness {
  state: string;
  /** Who decided it. `server` means the gateway computed it; `identity` means
   *  two ids the server owns were compared; `none` means no freshness verdict
   *  applies to this artifact kind. */
  basis: 'server' | 'identity' | 'none';
  note: string | null;
}

/** How loud a freshness row is drawn. Colour only — the state beside it is
 *  always the word this module or the server produced, and a state neither of
 *  them recognises falls to `muted`, never to green. */
export function freshnessTone(state: string): 'ok' | 'warn' | 'bad' | 'muted' {
  switch (state) {
    case 'CURRENT': return 'ok';
    case 'STALE': return 'warn';
    case 'FOREIGN_REVISION': return 'bad';
    default: return 'muted';
  }
}

export interface SelectionProvenance {
  id: LoomId;
  text: string;
  noun: string;
  origin: string | null;
  originWhy: string | null;
  artifactKind: string;
  artifactRef: string;
  /** The revision the object was read from, and what that revision is. */
  revisionId: string | null;
  revisionWhy: string | null;
  freshness: SelectionFreshness;
  /** The run that produced a measured object, and only for a measured object:
   *  a derived value has no run behind it. */
  runId: string | null;
}

type ProvenanceBase = Omit<
  SelectionProvenance, 'revisionId' | 'revisionWhy' | 'freshness'
>;

function notApplicable(why: string): SelectionFreshness {
  return { state: 'NOT_APPLICABLE', basis: 'none', note: why };
}

function unknownFreshness(why: string): SelectionFreshness {
  return { state: 'UNKNOWN', basis: 'none', note: why };
}

/** Where one selected object came from, and whether it still answers the
 *  question on screen.
 *
 *  Freshness for anything MEASURED is the server's own verdict from the run
 *  view, carried with the server's sentence — the client never recomputes it,
 *  because a stale-result warning that can disagree with the server about
 *  staleness is worse than no warning at all. For a revision-scoped artifact
 *  the comparison is an identity one the client can make without inventing a
 *  verdict: the artifact's own `revision_id` against the project's active
 *  revision. For authored intent and for the registry, no freshness verdict
 *  applies, and the reason is stated rather than the state assumed. */
export function provenanceOf(id: LoomId, data: LoomData): SelectionProvenance {
  const source = SELECTION_SOURCE[id.kind];
  const vocabulary = data.provenance.result.state === 'ready'
    ? data.provenance.result.data : null;
  const vocabularyError = data.provenance.result.state === 'error'
    ? data.provenance.result.error.message : null;
  const origin = resolveOrigin(
    vocabulary, vocabularyError, source.artifactKind, source.origin,
  );

  const base: ProvenanceBase = {
    id,
    text: loomIdText(id),
    noun: nounOf(id),
    origin: origin.origin,
    originWhy: origin.why,
    artifactKind: source.artifactKind,
    artifactRef: source.read(id),
    runId: null,
  };

  if (id.kind === 'pair') return measuredProvenance(base, data);
  if (id.kind === 'capability') {
    return {
      ...base,
      revisionId: null,
      revisionWhy: 'the capability registry is not revision-scoped',
      freshness: notApplicable(
        'the registry describes the installed system, not a revision of this design',
      ),
    };
  }
  if (id.kind === 'agent' || id.kind === 'kind' || id.kind === 'domain') {
    return {
      ...base,
      revisionId: data.basedOnRevisionId,
      revisionWhy: data.basedOnRevisionId === null
        ? 'this draft is not based on any compiled revision'
        : 'the revision this draft is based on',
      freshness: notApplicable(
        'authored intent is read from the draft, which is not a revision-scoped '
          + 'artifact'
          + (data.dirty ? '; the draft itself reports uncompiled changes' : ''),
      ),
    };
  }
  return topologyProvenance(base, data);
}

function topologyProvenance(
  base: ProvenanceBase,
  data: LoomData,
): SelectionProvenance {
  const state = data.topology.result.state;
  const topology = state === 'ready' ? data.topology.result.data : null;
  if (state === 'error') {
    return {
      ...base,
      revisionId: null,
      revisionWhy: 'the topology read failed',
      freshness: unknownFreshness(
        `the certified topology is unreadable (${data.topology.result.error.message}), `
          + 'so the revision this object was read from cannot be named',
      ),
    };
  }
  if (!topology) {
    return {
      ...base,
      revisionId: null,
      revisionWhy: state === 'loading'
        ? 'the topology is still being read'
        : 'this project has no certified topology',
      freshness: unknownFreshness(
        'no certified topology on this project, so there is no revision-scoped '
          + 'object to compare against',
      ),
    };
  }
  const read = topology.revision_id;
  const active = data.revisionId;
  const comparable = read !== null && active !== null;
  return {
    ...base,
    revisionId: read,
    revisionWhy: 'topology.revision_id, read off the certified TopologyView',
    freshness: {
      state: !comparable
        ? 'UNKNOWN'
        : read === active ? 'CURRENT' : 'FOREIGN_REVISION',
      basis: 'identity',
      note: !comparable
        ? 'either the topology or the project view carries no revision id'
        : read === active
          ? 'the artifact names the revision this project has active'
          : `the artifact was read from ${read}, not from the active revision ${active}`,
    },
  };
}

function measuredProvenance(
  base: ProvenanceBase,
  data: LoomData,
): SelectionProvenance {
  const state = data.run.result.state;
  const run: RunView | null = state === 'ready' ? data.run.result.data : null;
  if (state === 'error') {
    return {
      ...base,
      revisionId: null,
      revisionWhy: 'the run read failed',
      freshness: unknownFreshness(
        `the run is unreadable (${data.run.result.error.message}), `
          + 'so no freshness verdict exists',
      ),
    };
  }
  if (!run) {
    return {
      ...base,
      revisionId: null,
      revisionWhy: state === 'loading'
        ? 'the run is still being read'
        : 'this project has no run',
      freshness: unknownFreshness(
        'a measured cell exists only from an executed trace, '
          + 'and none has been read',
      ),
    };
  }
  return {
    ...base,
    revisionId: run.revision_id,
    revisionWhy: `the revision run ${run.run_id} executed against`,
    freshness: run.freshness
      ? {
        state: run.freshness.state,
        basis: 'server',
        note: run.freshness.meaning,
      }
      : unknownFreshness(
        'the run view carried no freshness field, and this client does not '
          + 'compute one',
      ),
    runId: run.run_id,
  };
}

/** Whether the current artifacts actually hold this id. An id they do not hold
 *  is reported as unresolvable rather than answered from a neighbouring row. */
export function resolveAgainstData(
  id: LoomId,
  data: LoomData,
): { present: boolean; why: string } {
  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data : null;
  const traffic = data.traffic.result.state === 'ready'
    ? data.traffic.result.data : null;
  switch (id.kind) {
    case 'node': {
      if (!topology) return { present: false, why: 'no certified topology' };
      return topology.routers.some((r) => r.router_id === id.routerId)
        ? { present: true, why: '' }
        : {
          present: false,
          why: `router ${id.routerId} is not in this revision's topology`,
        };
    }
    case 'channel': {
      if (!topology) return { present: false, why: 'no certified topology' };
      return topology.channels.some((c) => c.channel_id === id.channelId)
        ? { present: true, why: '' }
        : {
          present: false,
          why: `channel ${id.channelId} is not in this revision's topology`,
        };
    }
    case 'edge': {
      if (!topology) return { present: false, why: 'no certified topology' };
      const joined = topology.channels.some(
        (c) => (c.src_router === id.src && c.dst_router === id.dst)
          || (c.src_router === id.dst && c.dst_router === id.src),
      );
      return joined
        ? { present: true, why: '' }
        : {
          present: false,
          why: `no channel joins R${id.src} and R${id.dst} in this revision`,
        };
    }
    case 'agent': {
      const declared = data.agents[id.groupIndex];
      if (!declared) {
        return {
          present: false,
          why: `the draft declares no agent group ${id.groupIndex}`,
        };
      }
      return id.instanceIndex < declared.count
        ? { present: true, why: '' }
        : {
          present: false,
          why: `group ${id.groupIndex} declares ${declared.count} instance(s), `
            + `not instance ${id.instanceIndex}`,
        };
    }
    case 'kind':
      return data.agents.some((g) => g.kind === id.agentKind)
        ? { present: true, why: '' }
        : { present: false, why: `no agent group of kind '${id.agentKind}'` };
    case 'domain': {
      const field = id.axis === 'clock' ? 'clock_domain' : 'power_domain';
      return data.agents.some((g) => g[field] === id.domain)
        ? { present: true, why: '' }
        : { present: false, why: `no agent names the ${id.axis} domain '${id.domain}'` };
    }
    case 'pair': {
      if (!traffic) return { present: false, why: 'no measured matrix' };
      return traffic.pairs.some((p) => p.src === id.src && p.dst === id.dst)
        ? { present: true, why: '' }
        : {
          present: false,
          why: `the executed trace carries no traffic from ${id.src} to ${id.dst}`,
        };
    }
    case 'capability':
      // The registry is not a project artifact, so only the view that read it
      // can resolve it — never here.
      return { present: true, why: '' };
  }
}