import { useState, type ReactElement } from 'react';
import { api, type CanonicalRoute, type ResourcesGroup, type RoutingGroup } from '../api';
import type { DesignView, TopologyView } from '../types';
import { fabricModel, type FabricEdge, type FabricModel, type FabricNode } from '../fabricLayout';
import { useAsync } from '../studio';

export type InspectorMode = 'physical' | 'classes' | 'routes' | 'vc' | 'overlay' | 'diff';

const MODES: { id: InspectorMode; label: string }[] = [
  { id: 'physical', label: 'Physical graph' },
  { id: 'classes', label: 'Traffic classes' },
  { id: 'routes', label: 'Routes' },
  { id: 'vc', label: 'VC resources' },
  { id: 'overlay', label: 'Traffic overlay' },
  { id: 'diff', label: 'Diff A/B' },
];

export interface OverlayLink {
  a: number;
  b: number;
  load: number;
  trafficClass?: string | null;
}

export default function TopologyInspector({ design, revisionId, topology,
  routing, resources, compareTopology, compareRevisionId, overlayTraffic,
  evidenceLabel }: {
  design: DesignView;
  revisionId: string | null;
  topology: TopologyView;
  routing?: RoutingGroup | null;
  resources?: ResourcesGroup | null;
  compareTopology?: TopologyView | null;
  compareRevisionId?: string | null;
  overlayTraffic?: OverlayLink[] | null;
  evidenceLabel?: string | null;
}): ReactElement {
  const [mode, setMode] = useState<InspectorMode>('physical');
  const model = fabricModel(design, topology);
  const compiled = useAsync(
    () => (revisionId && (routing === undefined || resources === undefined)
      ? api.compileResult(revisionId).catch(() => null)
      : Promise.resolve(null)),
    [revisionId, routing === undefined, resources === undefined],
  );
  const compiledGroups = compiled.result.state === 'ready'
    ? compiled.result.data?.groups ?? null : null;
  const routingLive = routing !== undefined ? routing : compiledGroups?.routing ?? null;
  const resourcesLive = resources !== undefined ? resources : compiledGroups?.resources ?? null;
  const groupsFailed = compiled.result.state === 'error';
  const otherTopo = useAsync(
    () => (compareTopology === undefined && compareRevisionId
      ? api.topology(compareRevisionId).catch(() => null)
      : Promise.resolve(null)),
    [compareTopology === undefined, compareRevisionId],
  );
  const otherLive = compareTopology !== undefined
    ? compareTopology
    : (otherTopo.result.state === 'ready' ? otherTopo.result.data : null);
  return (
    <div className="topology-inspector">
      <div className="canvas-toolbar">
        <div className="overlay-tabs" role="tablist" aria-label="Topology inspector modes">
          {MODES.map((m) => (
            <button
              key={m.id}
              role="tab"
              aria-selected={mode === m.id}
              className={`overlay-tab${mode === m.id ? ' active' : ''}`}
              onClick={() => setMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <FamilyMaturity family={topology.family} />
      {groupsFailed && (
        <p className="warn">Compile groups unavailable ({compiled.result.state === 'error' ? compiled.result.error.message : 'unknown'}) — routes/VC render from caller-supplied groups only, or not at all. Nothing is inferred.</p>
      )}
      {mode === 'physical' && <PhysicalMode model={model} />}
      {mode === 'classes' && (
        <ClassesMode model={model} topology={topology} resources={resourcesLive} />
      )}
      {mode === 'routes' && (
        <RoutesMode model={model} topology={topology} revisionId={revisionId}
                    routing={routingLive} />
      )}
      {mode === 'vc' && <VcMode resources={resourcesLive} />}
      {mode === 'overlay' && (
        <OverlayMode model={model} links={overlayTraffic ?? null}
                     evidenceLabel={evidenceLabel ?? null} />
      )}
      {mode === 'diff' && (
        <DiffMode model={model} topology={topology} other={otherLive} />
      )}
    </div>
  );
}

function FamilyMaturity({ family }: { family: string }): ReactElement {
  const note: Record<string, string> = {
    mesh: 'Qualified fabric: intent, materialization, verification, projection, execution, qualification.',
    concentrated_mesh: 'Canonical fabric with a native concentrated-mesh execution profile.',
    torus: 'Wraparound channels are drawn as arcs. Routing proof/profile coverage is stated on the Compile page — this graph alone proves no route.',
    ring: 'Test-fixture family: materialized for compiler exercise, not user intent.',
  };
  return (
    <p className="muted">
      family <code>{family}</code> · {note[family] ?? 'explicit materialized graph.'}
    </p>
  );
}

const CELL = 96;
const MARGIN = 56;

function layoutOf(model: FabricModel): { W: number; H: number } {
  return {
    W: Math.max(1, model.cols) * CELL + MARGIN * 2,
    H: Math.max(1, model.rows) * CELL + MARGIN * 2,
  };
}

function posOf(node: FabricNode): { x: number; y: number } {
  return {
    x: MARGIN + node.col * CELL + CELL / 2,
    y: MARGIN + node.row * CELL + CELL / 2,
  };
}

function edgeKind(edge: FabricEdge, a: FabricNode | undefined,
  b: FabricNode | undefined, family: string): 'local' | 'wrap' | 'long' {
  if (edge.kind === 'wrap') return 'wrap';
  if (!a || !b) return 'local';
  const span = Math.abs(a.col - b.col) + Math.abs(a.row - b.row);
  if (span <= 1) return 'local';
  return family === 'torus' ? 'wrap' : 'long';
}

function GraphSvg({ model, family, highlightRouters, highlightPairs, linkTint,
  linkWidthOf, caption }: {
  model: FabricModel;
  family: string;
  highlightRouters?: Set<number>;
  highlightPairs?: Set<string>;
  linkTint?: (a: number, b: number) => string | null;
  linkWidthOf?: (a: number, b: number) => number | null;
  caption: string;
}): ReactElement {
  const { W, H } = layoutOf(model);
  const byId = new Map(model.nodes.map((n) => [n.id, n]));
  const pairKey = (a: number, b: number): string =>
    `${Math.min(a, b)}-${Math.max(a, b)}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="canvas" role="img" aria-label={caption}>
      {model.edges.map((edge, k) => {
        const na = byId.get(edge.a);
        const nb = byId.get(edge.b);
        if (!na || !nb) return null;
        const pa = posOf(na);
        const pb = posOf(nb);
        const kind = edgeKind(edge, na, nb, family);
        const hot = highlightPairs?.has(pairKey(edge.a, edge.b)) ?? false;
        const tint = linkTint?.(edge.a, edge.b) ?? null;
        const w = linkWidthOf?.(edge.a, edge.b) ?? 2;
        const cls = `cv-link${kind === 'wrap' ? ' cv-link-wrap' : ''}${hot ? ' cv-clickable' : ''}`;
        const style = {
          stroke: hot ? 'var(--accent)' : tint ?? undefined,
          strokeWidth: hot ? w + 1.5 : w,
        };
        const title = kind === 'wrap'
          ? 'wraparound channel'
          : kind === 'long'
            ? 'long/express link (materialized point-to-point channel)'
            : 'local link';
        if (kind !== 'local') {
          const midX = (pa.x + pb.x) / 2;
          const midY = (pa.y + pb.y) / 2;
          const cx = MARGIN + (model.cols * CELL) / 2;
          const cy = MARGIN + (model.rows * CELL) / 2;
          let nx = midX - cx;
          let ny = midY - cy;
          const len = Math.hypot(nx, ny) || 1;
          nx /= len;
          ny /= len;
          return (
            <path key={k} d={`M ${pa.x} ${pa.y} Q ${midX + nx * 34} ${midY + ny * 34} ${pb.x} ${pb.y}`}
                   className={cls} fill="none" style={style}>
              <title>{title}</title>
            </path>
          );
        }
        return (
          <line key={k} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                className={cls} style={style}>
            <title>{title}</title>
          </line>
        );
      })}
      {model.nodes.map((node) => {
        const p = posOf(node);
        const hot = highlightRouters?.has(node.id) ?? false;
        return (
          <g key={node.id}>
            <rect x={p.x - 26} y={p.y - 26} width={52} height={52} rx={5}
                  className="cv-router"
                  style={hot ? { stroke: 'var(--accent)', strokeWidth: 2.5 } : undefined}>
              <title>router {node.id} ({node.row},{node.col}) · {node.seats} seats</title>
            </rect>
            <text x={p.x} y={p.y + 4} textAnchor="middle" className="cv-label">
              r{node.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function degreeSummary(model: FabricModel): ReactElement {
  const deg = new Map<number, number>();
  for (const e of model.edges) {
    deg.set(e.a, (deg.get(e.a) ?? 0) + 1);
    deg.set(e.b, (deg.get(e.b) ?? 0) + 1);
  }
  const vals = model.nodes.map((n) => deg.get(n.id) ?? 0);
  const max = Math.max(...vals, 0);
  const min = Math.min(...vals, 0);
  const mean = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : 0;
  return (
    <p className="muted">
      degree min {min} · max {max} (radix bound lives here) · mean {mean.toFixed(2)} ·{' '}
      {model.edges.length} undirected links from {model.counts.channels} directed channels
    </p>
  );
}

function PhysicalMode({ model }: { model: FabricModel }): ReactElement {
  return (
    <div>
      <GraphSvg model={model} family={model.family ?? ''}
                caption={`Physical graph: ${model.counts.routers} routers`} />
      {degreeSummary(model)}
      <div className="canvas-legend">
        <span><i className="sw sw-router" /> router (seat cap. from artifact)</span>
        <span><i className="sw sw-link" /> link</span>
      </div>
    </div>
  );
}

const CLASS_COLORS = ['#4c9aff', '#ff8b00', '#36b37e', '#ff5630', '#6554c0', '#00b8d9'];

function ClassesMode({ model, topology, resources }: {
  model: FabricModel; topology: TopologyView; resources: ResourcesGroup | null;
}): ReactElement {
  const mapping = resources?.traffic_class_to_vcs ?? [];
  const tint = (a: number, b: number): string | null => {
    void a; void b;
    return null; 
  };
  const endpointsByRouter = new Map<number, number>();
  for (const e of topology.endpoints) {
    endpointsByRouter.set(e.router_id, (endpointsByRouter.get(e.router_id) ?? 0) + 1);
  }
  return (
    <div>
      <GraphSvg model={model} family={model.family ?? ''} linkTint={tint}
                caption="Traffic classes: endpoint-colored graph" />
      <p className="muted">
        Color is endpoint-level: {topology.counts.endpoints} endpoints over{' '}
        {topology.counts.routers} routers. Per-packet class is execution data,
        not a graph property — the overlay mode shows it only from run evidence.
      </p>
      <h5 className="inspector-label">CLASS → VC SUBSET (DERIVED)</h5>
      {mapping.length ? (
        <table className="tbl">
          <thead><tr><th>class</th><th>VCs</th><th></th></tr></thead>
          <tbody>
            {mapping.map(([cls, vcs], i) => (
              <tr key={cls}>
                <td>
                  <span style={{ display: 'inline-block', width: 10, height: 10,
                    background: CLASS_COLORS[i % CLASS_COLORS.length],
                    marginRight: 6 }} />
                  <code>{cls}</code>
                </td>
                <td className="num">{vcs.join(', ')}</td>
                <td className="muted">compiler-derived subset</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">
          No class→VC table on this revision{resources ? '' : ' (resources group not loaded)'}.
          Single-class fabrics carry one VC subset by construction.
        </p>
      )}
    </div>
  );
}

function RoutesMode({ model, topology, revisionId, routing }: {
  model: FabricModel; topology: TopologyView; revisionId: string | null;
  routing: RoutingGroup | null;
}): ReactElement {
  const classes = routing?.routing_classes ?? [];
  const routers = topology.routers.map((r) => r.router_id).sort((a, b) => a - b);
  const [cls, setCls] = useState(classes[0] ?? '');
  const [src, setSrc] = useState('');
  const [dst, setDst] = useState('');
  const [asked, setAsked] = useState(false);
  const query = useAsync<CanonicalRoute | null>(
    () => {
      if (!asked || !revisionId || !cls) return Promise.resolve(null);
      return api.route(revisionId, {
        routingClass: cls,
        src: src === '' ? null : Number(src),
        dst: dst === '' ? null : Number(dst),
      });
    },
    [asked, revisionId, cls, src, dst],
  );
  const route = query.result.state === 'ready' ? query.result.data : null;
  const pairKey = (a: number, b: number): string =>
    `${Math.min(a, b)}-${Math.max(a, b)}`;
  const pairs = new Set((route?.hops ?? []).map((h) => pairKey(h.src_router, h.dst_router)));
  const nodes = new Set(route?.routers ?? []);
  return (
    <div>
      <div className="inspector-controls">
        <label>class
          <select value={cls} onChange={(e) => setCls(e.target.value)} aria-label="Traffic class">
            {!classes.length && <option value="">—</option>}
            {classes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>source
          <select value={src} onChange={(e) => setSrc(e.target.value)} aria-label="Source router">
            <option value="">first</option>
            {routers.map((r) => <option key={r} value={String(r)}>router {r}</option>)}
          </select>
        </label>
        <label>destination
          <select value={dst} onChange={(e) => setDst(e.target.value)} aria-label="Destination router">
            <option value="">last</option>
            {routers.map((r) => <option key={r} value={String(r)}>router {r}</option>)}
          </select>
        </label>
        <button className="btn" disabled={!revisionId || !cls}
                onClick={() => setAsked(true)}>
          Show path
        </button>
      </div>
      <GraphSvg model={model} family={model.family ?? ''} highlightRouters={nodes}
                highlightPairs={pairs} caption="Route overlay: derived expected path" />
      {query.result.state === 'error' && (
        <p className="bad">{query.result.error.message}</p>
      )}
      {route ? (
        <p className="muted">
          <code>{route.routing_class}</code> r{route.src} → r{route.dst} ·{' '}
          {route.hops.length} hops · DERIVED EXPECTED path, not an observation.
        </p>
      ) : (
        <p className="muted">
          Select a class and endpoints. The path is walked server-side from the
          table frozen at certification — this view never runs pathfinding.
        </p>
      )}
      {!routing && (
        <p className="muted">Routing group not loaded on this revision.</p>
      )}
    </div>
  );
}

function VcMode({ resources }: { resources: ResourcesGroup | null }): ReactElement {
  if (!resources) {
    return (
      <p className="muted">
        VC resources not loaded on this revision. VC count, class→VC subsets,
        escape VCs and allowed transitions are compiler-derived state shown
        under Compile → Resources when available.
      </p>
    );
  }
  return (
    <div>
      <div className="kv-grid">
        <div className="kv"><span>VC count (derived)</span>
          <span className="num">{resources.vc_count ?? '—'}</span></div>
        <div className="kv"><span>escape VCs</span>
          <span className="num">{(resources.escape_vcs ?? []).join(', ') || 'none'}</span></div>
        <div className="kv"><span>transitions</span>
          <span>{resources.transitions_are_identity ? 'identity only' : 'see table'}</span></div>
      </div>
      {!!resources.vc_to_routing_class?.length && (
        <details open>
          <summary>VC → routing class ({resources.vc_to_routing_class.length})</summary>
          <table className="tbl">
            <thead><tr><th>VC</th><th>role</th></tr></thead>
            <tbody>
              {resources.vc_to_routing_class.map(([vc, role]) => (
                <tr key={vc}><td className="num">{vc}</td><td><code>{role}</code></td></tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <p className="muted">
        VC assignment is derived correctness state, not an editable knob. Adaptive,
        escape and tap roles appear here only when the compiled design carries them.
      </p>
    </div>
  );
}

function OverlayMode({ model, links, evidenceLabel }: {
  model: FabricModel; links: OverlayLink[] | null; evidenceLabel: string | null;
}): ReactElement {
  if (!links?.length) {
    return (
      <p className="muted">
        No traffic evidence attached. Per-link load is execution data — run an
        evaluation and open this mode from the run to color the graph by measured
        traffic. Nothing is estimated here.
      </p>
    );
  }
  const max = Math.max(...links.map((l) => l.load), 1);
  const byPair = new Map(links.map((l) => [
    `${Math.min(l.a, l.b)}-${Math.max(l.a, l.b)}`, l,
  ]));
  return (
    <div>
      <GraphSvg
        model={model}
        family={model.family ?? ''}
        linkTint={(a, b) => {
          const l = byPair.get(`${Math.min(a, b)}-${Math.max(a, b)}`);
          if (!l?.trafficClass) return null;
          const classes = [...new Set(links.map((x) => x.trafficClass).filter(Boolean))];
          const i = classes.indexOf(l.trafficClass);
          return CLASS_COLORS[Math.max(0, i) % CLASS_COLORS.length];
        }}
        linkWidthOf={(a, b) => {
          const l = byPair.get(`${Math.min(a, b)}-${Math.max(a, b)}`);
          return l ? 1 + 4 * (l.load / max) : 1;
        }}
        caption="Traffic overlay from run evidence"
      />
      <p className="muted">
        Link width ∝ measured load (max {max}) · color = traffic class · source:{' '}
        {evidenceLabel ?? 'attached run evidence'}.
      </p>
    </div>
  );
}

function DiffMode({ model, topology, other }: {
  model: FabricModel; topology: TopologyView; other: TopologyView | null;
}): ReactElement {
  if (!other) {
    return (
      <p className="muted">
        Select a second revision or candidate to compare. The diff shows
        added/removed links, degree changes and traffic-weighted hot paths —
        never a merged graph.
      </p>
    );
  }
  const key = (a: number, b: number): string => `${Math.min(a, b)}-${Math.max(a, b)}`;
  const pairsOf = (t: TopologyView): Set<string> => {
    const seen = new Map<string, { a: number; b: number }>();
    for (const c of t.channels) {
      const k = key(c.src_router, c.dst_router);
      if (!seen.has(k)) seen.set(k, { a: c.src_router, b: c.dst_router });
    }
    return new Set(seen.keys());
  };
  const aPairs = pairsOf(topology);
  const bPairs = pairsOf(other);
  const added = [...bPairs].filter((k) => !aPairs.has(k));
  const removed = [...aPairs].filter((k) => !bPairs.has(k));
  const deg = (t: TopologyView): Map<number, number> => {
    const d = new Map<number, number>();
    for (const k of pairsOf(t)) {
      const [x, y] = k.split('-').map(Number);
      d.set(x, (d.get(x) ?? 0) + 1);
      d.set(y, (d.get(y) ?? 0) + 1);
    }
    return d;
  };
  const da = deg(topology);
  const db = deg(other);
  const changed = [...new Set([...da.keys(), ...db.keys()])]
    .filter((r) => (da.get(r) ?? 0) !== (db.get(r) ?? 0))
    .sort((x, y) => x - y);
  const hot = new Set([...added, ...removed]);
  return (
    <div>
      <div className="kv-grid">
        <div className="kv"><span>base links</span><span className="num">{aPairs.size}</span></div>
        <div className="kv"><span>other links</span><span className="num">{bPairs.size}</span></div>
        <div className="kv"><span>added</span><span className="num">{added.length}</span></div>
        <div className="kv"><span>removed</span><span className="num">{removed.length}</span></div>
      </div>
      <GraphSvg model={model} family={model.family ?? ''} highlightPairs={hot}
                caption="Diff: changed links highlighted" />
      {changed.length > 0 && (
        <table className="tbl">
          <thead><tr><th>router</th><th>base degree</th><th>other degree</th></tr></thead>
          <tbody>
            {changed.map((r) => (
              <tr key={r}>
                <td className="num">r{r}</td>
                <td className="num">{da.get(r) ?? 0}</td>
                <td className="num">{db.get(r) ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted">
        Comparing topology <code>{topology.topology_hash.slice(0, 12)}…</code> (base)
        with <code>{other.topology_hash.slice(0, 12)}…</code>. Qualification and
        measurement belong to each side separately — the diff itself proves nothing.
      </p>
    </div>
  );
}
