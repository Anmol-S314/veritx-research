/** Shared graph-authoring panels embedded inside the Loom views (P0–P6).
 *
 * Everything here is authoring data held in the local graph store: presets
 * seed a node/edge graph, edits validate before they apply, and the adapter
 * previews the lowering the compiler would receive. Nothing here is a
 * compiled fabric, a measured trace, or a generated artifact — the certified
 * views on the same page stay the only readers of those.
 *
 * Loom contract notes: these sections use plain elements only (no Kv, table
 * or SummaryStrip), so they carry no From line; they state no origin words
 * and no counts of their own beyond the graph the editor holds.
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactElement } from 'react';
import { useAsync, ErrorBox, JobProgress, Link, type Async } from '../../studio';
import { useCompileJob } from '../../hooks/useCompileJob';
import { api, ApiError } from '../../api';
import type { FabricPresetCatalogEntry } from '../../api/types';
import type { TopologyView } from '../../types';
import { graphToDraftRequest, graphToTopologyIR, presetGraphToProject } from '../../graph/adapter';
import { nextEdgeId, nextNodeId } from '../../graph/ids';
import { editableDocument } from '../../canonicalDraft';
import type { GraphCommand } from '../../graph/history';
import { allowAllFirewallRules, canonicalFirewall, inspectFirewallRules, setFirewallColumn, setFirewallRow, type FirewallRule } from '../../graph/firewall';
import { download, exportSvgPng, nodesToCsv, csvToNodePatches } from '../../graph/io';
import { PRESETS } from '../../graph/presets';
import { MAX_PROJECT_JSON_BYTES, serializeProject, supportsXYRouting, validateCustomRoutingRules, validateProject, type CustomRoutingRule, type GraphEdge, type GraphNode, type JsonValue, type PhysicalUnit } from '../../graph/project';
import { convertFloorplanIntent, estimateManhattanRouteDelayPs, routeAllManhattanPhysicalEdges } from '../../graph/floorplan';
import { manhattanAvoiding, pathFor, previewConnectivityPath, previewCustomPath, previewOddEvenPath, previewWestFirstPath, previewXYPath, validateAllowedRouteReachability, validateWorkloadRoutingCompatibility } from '../../graph/routing';
import { parseProjectDocument, serializeProjectDocument, wrapProjectDocument } from '../../project/document';
import { useGraphStore, type GraphStore } from '../../graph/store';
import { buildMockTrace, topCongested, type TraceFrame } from '../../graph/trace';
import { parseTraceStream, type TraceWarning } from '../../graph/traceParser';
import { autoRankMappings, buildWorkloadRunIntent, COMMUNICATION_KINDS, emptyWorkload, moeWorkloadSkeleton, nextCommunicationId, nextPhaseId, PHASE_KINDS, parseWorkloadJson, RANK_ASSIGNMENT_POLICIES, RANK_ASSIGNMENT_POLICY_LABELS, requiredRankCount, serializeWorkloadJson, validateWorkload, type RankAssignmentPolicy, type WorkloadCommunication, type WorkloadRankConstraint, type WorkloadRankMapping, type WorkloadTrafficClassMapping } from '../../graph/workload';
import { classifyWorkloadBackend, DECLARED_BACKENDS, findDeclaredBackend } from '../../graph/workloadBackend';

export function useAuthoring(projectId: string): GraphStore {
  return useGraphStore('mesh-8x8', projectId);
}

function omitUndefined(value: unknown): JsonValue {
  if (value === null || typeof value === 'string' || typeof value === 'boolean' || typeof value === 'number') return value;
  if (Array.isArray(value)) return value.map(omitUndefined);
  if (typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined).map(([key, item]) => [key, omitUndefined(item)]));
  }
  return null;
}

function Verdict({ store }: { store: GraphStore }): ReactElement {
  const issues = useMemo(() => validateProject(store.doc), [store.doc]);
  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity === 'warning');
  if (errors.length > 0) {
    return (
      <p className="t-bad" role="alert">
        ✗ {errors.length} error(s): {errors.slice(0, 2).map((i) => `${i.path} ${i.message}`).join(' · ')}
      </p>
    );
  }
  if (warnings.length > 0) {
    return (
      <p className="t-warn" role="status">
        ▲ {warnings.length} warning(s) — editable, blocked at compile: {warnings.slice(0, 2).map((i) => i.message).join(' · ')}
      </p>
    );
  }
  return (
    <p className="t-ok">
      ✓ graph validates — {store.doc.nodes.length} nodes / {store.doc.edges.length} edges
      {' · '}{store.isCustom ? 'custom' : `preset ${store.doc.presetHint ?? '—'}`}
    </p>
  );
}

/** The certified readback: does the compiled fabric actually match the graph
 *  that was applied? Routers and undirected link pairs are compared, since a
 *  directed channel count is always 2× the authored links. A mismatch is
 *  stated, never smoothed over. */
function Readback({ store, revisionId, result }: {
  store: GraphStore;
  revisionId: string | null;
  result: Async<TopologyView>;
}): ReactElement | null {
  const ir = useMemo(() => graphToTopologyIR(store.doc), [store.doc]);
  if (!revisionId) return null;
  const loweredLinks = ir.doc ? (ir.doc.links as unknown[]).length : 0;
  const loweredNodes = store.doc.nodes.length;
  return (
    <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
      <p><strong>Certified readback</strong> — <code>{revisionId}</code></p>
      {result.state === 'loading' && <p className="muted" role="status">reading certified topology…</p>}
      {result.state === 'error' && (
        <p className="t-warn" role="alert">
          ✗ {(result.error instanceof ApiError) ? result.error.message : result.error.message}
        </p>
      )}
      {result.state === 'ready' && (
        (() => {
          const t = result.data;
          const pairs = new Set(t.channels
            .filter((c) => c.src_router !== c.dst_router)
            .map((c) => {
              const a = Math.min(c.src_router, c.dst_router);
              const b = Math.max(c.src_router, c.dst_router);
              return `${a}-${b}`;
            }));
          const nodesMatch = t.counts.routers === loweredNodes;
          const linksMatch = pairs.size === loweredLinks;
          return (
            <>
              <div className="kv">
                <span>graph → routers</span>
                <span className="num">{loweredNodes} → {t.counts.routers} {nodesMatch ? '✓' : '✗'}</span>
              </div>
              <div className="kv">
                <span>graph → link pairs</span>
                <span className="num">{loweredLinks} → {pairs.size} {linksMatch ? '✓' : '✗'}</span>
              </div>
              <div className="kv">
                <span>directed channels</span>
                <span className="num">{t.counts.channels}</span>
              </div>
              <div className="kv">
                <span>family</span>
                <span className="num">{t.family}</span>
              </div>
              <p className="muted">
                certified TopologyView bound to <code>{(t.topology_hash ?? '').slice(0, 18)}</code>
                {' · '}endpoints {t.counts.endpoints} / seats {t.counts.seats}
              </p>
              {(nodesMatch && linksMatch)
                ? <p className="t-ok">✓ the compiled fabric is the graph you applied</p>
                : (
                  <p className="t-warn" role="note">
                    ● the compiled fabric diverges from the applied graph. The
                    revision is authoritative; the graph above is intent only.
                  </p>
                )}
            </>
          );
        })()
      )}
    </div>
  );
}

/** Local graph workspace: preset seed, validation, project.json import/export,
 * topology projection preview and fail-closed draft-apply status. */
export function GraphStatus(props: Parameters<typeof GraphStatusEditor>[0]): ReactElement {
  return <GraphStatusEditor key={props.projectId ?? 'local'} {...props} />;
}

function GraphStatusEditor({ store, projectId, draftRequest, onApplied }: {
  store: GraphStore;
  projectId?: string;
  draftRequest?: Record<string, unknown> | null;
  onApplied?: () => void;
}): ReactElement {
  const [error, setError] = useState<string | null>(null);
  const [applyState, setApplyState] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [catalog, setCatalog] = useState<FabricPresetCatalogEntry[] | null>(null);
  const [shipped, setShipped] = useState('');
  const [seeding, setSeeding] = useState(false);
  const adapted = useMemo(
    () => graphToDraftRequest(store.doc, draftRequest ?? {}),
    [store.doc, draftRequest],
  );
  const ir = useMemo(() => graphToTopologyIR(store.doc), [store.doc]);
  /** The certified readback: what the compiler actually materialized for
   *  the revision this graph produced. Fetched by revision id on demand —
   *  never the local graph re-labelled. */
  const [readbackRev, setReadbackRev] = useState<string | null>(null);
  const [readbackNonce, setReadbackNonce] = useState(0);
  const readback = useAsync<TopologyView>(
    () => (readbackRev
      ? api.topology(readbackRev)
      : Promise.reject(new Error('no compiled revision to read back'))),
    [readbackRev, readbackNonce],
  );
  const readbackLoad = (revisionId: string): void => {
    setReadbackRev(revisionId);
    setReadbackNonce((n) => n + 1);
  };
  const compileJob = useCompileJob(projectId, (job) => {
    if (job.state === 'COMPLETED' && job.result?.revision_id) {
      setApplyState(`Compile attempt recorded · ${job.result.revision_id}. Inspect its certificate.`);
      readbackLoad(job.result.revision_id);
    }
    onApplied?.();
  });

  useEffect(() => {
    let live = true;
    api.fabricPresets()
      .then((v) => { if (live) { setCatalog(v.presets); } })
      .catch(() => { if (live) setCatalog([]); });
    return () => { live = false; };
  }, []);

  const seedShipped = async (): Promise<void> => {
    if (!shipped) return;
    setSeeding(true);
    setError(null);
    try {
      const g = await api.presetGraph(shipped);
      const out = presetGraphToProject(g);
      if (!out.doc) {
        setError(out.refused ?? 'preset seeding refused');
        return;
      }
      const issues = validateProject(out.doc).filter((i) => i.severity === 'error');
      if (issues.length) {
        setError(`seeded graph invalid: ${issues.slice(0, 2).map((i) => `${i.path} ${i.message}`).join(' · ')}`);
        return;
      }
      const err = store.loadJson(JSON.stringify(out.doc));
      if (err) { setError(err); return; }
      setApplyState(`Local topology seeded from ${g.preset_id} (${g.generation}, ${g.family}, ${g.routers.length} routers). Graph node roles and positions are editor annotations.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSeeding(false);
    }
  };

  const apply = async (andCompile: boolean): Promise<void> => {
    if (!projectId || !draftRequest) return;
    setApplying(true);
    setError(null);
    setApplyState(null);
    try {
      if (!adapted.doc) {
        setError(adapted.refused ?? 'graph application refused');
        return;
      }
      const saved = await api.putDraft(projectId, editableDocument(adapted.doc));
      setApplyState(`✓ draft saved · design ${(saved.design_hash ?? '—').slice(0, 18)}… · dirty=${String(saved.dirty)}`);
      onApplied?.();
      if (andCompile) {
        if (!saved.design_hash) throw new Error('Saved draft has no identity; refresh before compiling.');
        await compileJob.submit(saved.design_hash);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <select aria-label="graph preset" value={store.doc.presetHint ?? 'custom'}
          onChange={(e) => {
            const found = PRESETS.find((p) => p.hint === e.target.value);
            if (found) store.loadPreset(found.id);
          }}>
          {!store.doc.presetHint && <option value="custom">custom</option>}
          {PRESETS.map((p) => <option key={p.id} value={p.hint}>{p.label}</option>)}
        </select>
        <button type="button" className="btn" onClick={() => store.undo()} disabled={!store.canUndo}>Undo</button>
        <button type="button" className="btn" onClick={() => store.redo()} disabled={!store.canRedo}>Redo</button>
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <select aria-label="shipped preset" value={shipped} onChange={(e) => setShipped(e.target.value)}>
          <option value="">shipped preset…</option>
          {(catalog ?? []).map((p) => (
            <option key={p.preset_id} value={p.preset_id}>
              {p.preset_id} ({p.generation ?? '?'})
            </option>
          ))}
        </select>
        <button type="button" className="btn" disabled={!shipped || seeding}
          onClick={() => { void seedShipped(); }}>
          {seeding ? 'Seeding…' : 'Seed from engine'}
        </button>
        {catalog !== null && catalog.length === 0 && <span className="muted">catalog unreadable</span>}
      </div>
      <Verdict store={store} />
      <p className="muted" role="note">
        Applying writes the explicit router/link topology into the canonical V4/V5 draft and preserves its other intent. Graph node roles and canvas positions remain editor annotations, not compiler endpoint bindings or physical placement.
      </p>
      {adapted.refused && (
        <div id="graph-status-apply-refusal" className="t-warn" role="alert">
          <p>Graph application is unavailable: {adapted.refused}</p>
          {projectId && <Link className="link" to={`/projects/${projectId}/design`}>Open Design to edit the canonical draft</Link>}
          <p className="muted">{ir.doc
            ? `Local topology projection: ${store.doc.nodes.length} nodes, ${(ir.doc.links as unknown[]).length} link pairs. This is not a compiler submission.`
            : `Local topology preview unavailable: ${ir.refused}`}</p>
        </div>
      )}
      {projectId && draftRequest && (
        <div className="row" style={{ gap: 8, marginTop: 8 }}>
          <button type="button" className="btn" disabled={applying || !adapted.doc}
            aria-describedby="graph-status-apply-refusal"
            onClick={() => { void apply(false); }}>
            {adapted.doc ? 'Apply graph to draft' : 'Apply graph to draft unavailable'}
          </button>
          <button type="button" className="btn" disabled={applying || compileJob.active || !adapted.doc}
            aria-describedby="graph-status-apply-refusal"
            onClick={() => { void apply(true); }}>
            {adapted.doc ? 'Apply + compile' : 'Apply + compile unavailable'}
          </button>
        </div>
      )}
      {applyState && <p className="t-ok">{applyState}</p>}
      <JobProgress job={compileJob.job} />
      {compileJob.error && <ErrorBox error={compileJob.error} onRetry={compileJob.retry} />}
      <Readback store={store} revisionId={readbackRev} result={readback.result} />
      {projectId && (
        <p className="muted">
          <Link className="link" to={`/projects/${projectId}/compile`}>Open Compile →</Link>
          {' · '}
          <Link className="link" to={`/projects/${projectId}/evaluate`}>Open Evaluate →</Link>
        </p>
      )}
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <button type="button" className="btn" onClick={() => {
          try { download('project.json', serializeProjectDocument(wrapProjectDocument(store.doc))); setError(null); }
          catch (e) { setError(e instanceof Error ? e.message : String(e)); }
        }}>Save project.json</button>
        <label className="btn" style={{ cursor: 'pointer' }}>Load project.json
          <input type="file" accept=".json" hidden onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            try {
              if (f.size > MAX_PROJECT_JSON_BYTES) throw new Error(`project file exceeds ${MAX_PROJECT_JSON_BYTES} byte limit`);
              const text = await f.text();
              parseProjectDocument(text);
              const err = store.loadJson(text);
              setError(err);
            } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
            e.target.value = '';
          }} />
        </label>
        {store.dirty && <span className="muted">● unsaved changes (kept locally)</span>}
      </div>
      {error && <p className="t-bad" role="alert">✗ {error}</p>}
      {store.error && <p className="t-bad" role="alert">✗ {store.error}</p>}
    </div>
  );
}

/** P1a: small editable canvas. Geometry only — certified FabricCanvas is untouched. */
export function NodeEditor({ store }: { store: GraphStore }): ReactElement {
  const [sel, setSel] = useState<string | null>(null);
  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(new Set());
  const [selectedEdges, setSelectedEdges] = useState<Set<string>>(new Set());
  const [marquee, setMarquee] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const marqueeStart = useRef<{ x: number; y: number } | null>(null);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dragPoint, setDragPoint] = useState<{ id: string; x: number; y: number } | null>(null);
  const [snapToGrid, setSnapToGrid] = useState(true);
  const [panMode, setPanMode] = useState(false);
  const [viewOverride, setViewOverride] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const panStart = useRef<{ clientX: number; clientY: number; view: { x: number; y: number; width: number; height: number } } | null>(null);
  const [src, setSrc] = useState('');
  const [dst, setDst] = useState('');
  const [hasClipboard, setHasClipboard] = useState(false);
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([]);
  const clip = useRef<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const byId = new Map(store.doc.nodes.map((n) => [n.id, n]));
  const routeEdge = (edge: GraphEdge): { x: number; y: number }[] => {
    const a = byId.get(edge.src); const b = byId.get(edge.dst);
    if (!a || !b) return [];
    const obstacles = store.doc.nodes.filter((node) => node.id !== edge.src && node.id !== edge.dst)
      .map((node) => ({ x: node.x - 34, y: node.y - 20, width: 68, height: 40 }));
    return manhattanAvoiding({ x: a.x, y: a.y }, { x: b.x, y: b.y }, obstacles);
  };
  const run = (c: GraphCommand): void => { store.run(c); };
  const selectNode = (id: string, additive = false): void => {
    setSelEdge(null);
    setSelectedEdges(new Set());
    if (!additive) {
      setSel(id); setSrc(id); setSelectedNodes(new Set([id]));
      return;
    }
    const next = new Set(selectedNodes);
    if (next.has(id)) next.delete(id); else next.add(id);
    const active = next.has(id) ? id : ([...next].pop() ?? null);
    setSelectedNodes(next); setSel(active); setSrc(active ?? '');
  };
  const worldPoint = (clientX: number, clientY: number, rect: DOMRect): { x: number; y: number } => ({
    x: view.x + (clientX - rect.left) * view.width / Math.max(1, rect.width),
    y: view.y + (clientY - rect.top) * view.height / Math.max(1, rect.height),
  });
  const finishMarquee = (clientX: number, clientY: number, rect: DOMRect): void => {
    const start = marqueeStart.current;
    if (!start) return;
    const end = worldPoint(clientX, clientY, rect);
    const left = Math.min(start.x, end.x); const right = Math.max(start.x, end.x);
    const top = Math.min(start.y, end.y); const bottom = Math.max(start.y, end.y);
    const nodes = store.doc.nodes.filter((node) => node.x >= left && node.x <= right && node.y >= top && node.y <= bottom);
    const edges = store.doc.edges.filter((edge) => {
      const a = byId.get(edge.src); const b = byId.get(edge.dst);
      if (!a || !b) return false;
      const points = routeEdge(edge);
      return points.some((point, index) => {
        if (index === points.length - 1) return false;
        const next = points[index + 1];
        if (point.x === next.x) return point.x >= left && point.x <= right && Math.max(Math.min(point.y, next.y), top) <= Math.min(Math.max(point.y, next.y), bottom);
        return point.y >= top && point.y <= bottom && Math.max(Math.min(point.x, next.x), left) <= Math.min(Math.max(point.x, next.x), right);
      });
    });
    const nodeIds = new Set(nodes.map((node) => node.id));
    const edgeIds = new Set(edges.map((edge) => edge.id));
    const activeNode = [...nodes].pop()?.id ?? null;
    const activeEdge = [...edges].pop()?.id ?? null;
    setSelectedNodes(nodeIds); setSelectedEdges(edgeIds);
    setSel(activeNode); setSelEdge(activeEdge);
    setSrc(activeNode ?? '');
    marqueeStart.current = null; setMarquee(null);
  };
  const finishDrag = (): void => {
    const node = dragPoint ? byId.get(dragPoint.id) : null;
    if (dragPoint && node && (node.x !== dragPoint.x || node.y !== dragPoint.y)) {
      store.run({ type: 'move_node', id: dragPoint.id, x: dragPoint.x, y: dragPoint.y });
    }
    setDragging(null);
    setDragPoint(null);
  };
  // Fit the canvas to the graph instead of a fixed scale.
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of store.doc.nodes) {
    minX = Math.min(minX, n.x);
    minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x);
    maxY = Math.max(maxY, n.y);
  }
  if (!Number.isFinite(minX)) { minX = 0; minY = 0; maxX = 800; maxY = 600; }
  const pad = 80;
  const fitView = { x: minX - pad, y: minY - pad, width: maxX - minX + pad * 2, height: maxY - minY + pad * 2 };
  const initialView = useRef(fitView).current;
  const view = viewOverride ?? fitView;
  const box = `${view.x} ${view.y} ${view.width} ${view.height}`;

  const addNode = (): void => {
    // A lone node fails connectivity validation, so a new node arrives
    // already wired to the selected node (or the first one) in one command.
    const anchor = (sel && byId.get(sel)) ? sel : store.doc.nodes[0]?.id;
    if (!anchor) return;
    const a = byId.get(anchor);
    const id = nextNodeId(store.doc.nodes);
    const err = store.run({
      type: 'paste',
      nodes: [{ id, x: (a?.x ?? 400) + 120, y: (a?.y ?? 300) + 60, role: 'compute_tile', ports: 5, clock: 'clk_core' }],
      edges: [{ id: nextEdgeId(store.doc.edges), src: anchor, dst: id, width: 512, pipelineStages: 1, vcClass: 0 }],
    });
    if (!err) { setSel(id); setSelEdge(null); setSelectedNodes(new Set([id])); setSrc(id); }
  };

  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button type="button" className="btn" onClick={addNode}>+ node (wired)</button>
        <button type="button" className="btn" aria-pressed={snapToGrid} onClick={() => setSnapToGrid((enabled) => !enabled)}>
          Snap to grid: {snapToGrid ? 'on' : 'off'}
        </button>
        <button type="button" className="btn" aria-pressed={panMode} onClick={() => { setPanMode((enabled) => !enabled); setDragging(null); setDragPoint(null); }}>
          Pan canvas: {panMode ? 'on' : 'off'}
        </button>
        <button type="button" className="btn" onClick={() => setViewOverride(null)}>Fit to content</button>
        <button type="button" className="btn" onClick={() => setViewOverride(initialView)}>Reset view</button>
        <button type="button" className="btn" disabled={selectedNodes.size === 0} onClick={() => {
          const copied = store.doc.nodes.filter((n) => selectedNodes.has(n.id));
          const ids = new Set(copied.map((n) => n.id));
          clip.current = {
            nodes: copied.map((n) => ({ ...n })),
            edges: store.doc.edges.filter((e) => ids.has(e.src) && ids.has(e.dst)).map((e) => ({ ...e })),
          };
          setHasClipboard(copied.length > 0);
        }}>Copy</button>
        <button type="button" className="btn" disabled={!hasClipboard} onClick={() => {
          const c = clip.current;
          if (!c || c.nodes.length === 0) return;
          const usedNodes = new Set(store.doc.nodes.map((n) => n.id));
          const usedEdges = new Set(store.doc.edges.map((e) => e.id));
          const uniqueId = (base: string, used: Set<string>): string => {
            let suffix = 1;
            let candidate = `${base}-copy${suffix}`;
            while (used.has(candidate)) candidate = `${base}-copy${++suffix}`;
            used.add(candidate);
            return candidate;
          };
          const idMap = new Map(c.nodes.map((n) => [n.id, uniqueId(n.id, usedNodes)]));
          const edgeMap = new Map(c.edges.map((e) => [e.id, uniqueId(e.id, usedEdges)]));
          const anchor = (sel && byId.has(sel)) ? sel : store.doc.nodes[0]?.id;
          if (!anchor) return;
          const copiedNodes = c.nodes.map((n) => ({
            ...n, id: idMap.get(n.id)!, x: n.x + 60, y: n.y + 60,
          }));
          const copiedEdges = c.edges.map((e) => ({
            ...e, id: edgeMap.get(e.id)!, src: idMap.get(e.src)!, dst: idMap.get(e.dst)!,
          }));
          const bridge = {
            id: uniqueId('e-paste-bridge', usedEdges), src: anchor,
            dst: copiedNodes[0].id, width: 512, pipelineStages: 1, vcClass: 0,
          };
          const err = store.run({ type: 'paste', nodes: copiedNodes, edges: [...copiedEdges, bridge] });
          if (!err) {
            setSelectedNodes(new Set(copiedNodes.map((n) => n.id)));
            setSel(copiedNodes[0].id);
            setSelEdge(null);
            setSrc(copiedNodes[0].id);
          }
        }}>Paste</button>
        <button type="button" className="btn" disabled={!sel && selectedNodes.size === 0} onClick={() => {
          const ids = selectedNodes.size > 0 ? [...selectedNodes] : (sel ? [sel] : []);
          if (ids.length) setPendingDeleteIds(ids);
        }}>Delete</button>
        {selectedNodes.size > 1 && <label>Batch role
          <select aria-label="Batch role" defaultValue="" onChange={(event) => {
            const role = event.currentTarget.value;
            const updates = [...selectedNodes].map((id) => ({ id, patch: { role } }));
            if (role && updates.length > 1) store.run({ type: 'update_nodes', updates });
            event.currentTarget.value = '';
          }}>
            <option value="" disabled>Set selected roles…</option>
            {['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU'].map((role) => <option key={role}>{role}</option>)}
          </select>
        </label>}
      </div>
      {pendingDeleteIds.length > 0 && (() => {
        const ids = new Set(pendingDeleteIds);
        const nodes = pendingDeleteIds.map((id) => byId.get(id)).filter((node): node is GraphNode => node !== undefined);
        if (nodes.length !== pendingDeleteIds.length) return null;
        const affected = store.doc.edges.filter((edge) => ids.has(edge.src) || ids.has(edge.dst));
        return (
          <section role="dialog" aria-label="Confirm node deletion" className="row" style={{ gap: 8, marginBottom: 8 }}>
            <span>Delete {nodes.length} node{nodes.length === 1 ? '' : 's'} ({nodes.map((node) => node.id).join(', ')})? Affected edges: {affected.length ? affected.map((edge) => edge.id).join(', ') : 'none'}.</span>
            <button type="button" className="btn" onClick={() => setPendingDeleteIds([])}>Cancel deletion</button>
            <button type="button" className="btn" onClick={() => {
              const err = store.run({ type: 'delete_nodes', ids: pendingDeleteIds });
              if (!err) {
                setSel(null); setSelEdge(null); setSelectedNodes(new Set()); setSelectedEdges(new Set());
                setSrc(''); setDst(''); setPendingDeleteIds([]);
              }
            }}>Confirm delete node</button>
          </section>
        );
      })()}
      <svg data-testid="authoring-canvas" width="100%" height={300} viewBox={box}
        onWheel={(ev) => {
          ev.preventDefault();
          const rect = ev.currentTarget.getBoundingClientRect();
          const sx = view.width / Math.max(1, rect.width);
          const sy = view.height / Math.max(1, rect.height);
          if (ev.ctrlKey || ev.metaKey) {
            const factor = ev.deltaY < 0 ? 0.9 : 1.1;
            const ratioX = Math.max(0, Math.min(1, (ev.clientX - rect.left) / Math.max(1, rect.width)));
            const ratioY = Math.max(0, Math.min(1, (ev.clientY - rect.top) / Math.max(1, rect.height)));
            const width = Math.max(20, Math.min(100000, view.width * factor));
            const height = Math.max(20, Math.min(100000, view.height * factor));
            const anchorX = view.x + ratioX * view.width;
            const anchorY = view.y + ratioY * view.height;
            setViewOverride({ x: anchorX - ratioX * width, y: anchorY - ratioY * height, width, height });
          } else {
            setViewOverride({ ...view, x: view.x + ev.deltaX * sx, y: view.y + ev.deltaY * sy });
          }
        }}
        onMouseDown={(ev) => {
          if ((panMode && ev.button === 0) || ev.button === 1) {
            ev.preventDefault();
            panStart.current = { clientX: ev.clientX, clientY: ev.clientY, view };
          } else if (ev.button === 0 && ev.target === ev.currentTarget) {
            const point = worldPoint(ev.clientX, ev.clientY, ev.currentTarget.getBoundingClientRect());
            marqueeStart.current = point;
            setMarquee({ x1: point.x, y1: point.y, x2: point.x, y2: point.y });
          }
        }}
        onMouseMove={(ev) => {
          const start = panStart.current;
          if (start) {
            const rect = ev.currentTarget.getBoundingClientRect();
            setViewOverride({
              ...start.view,
              x: start.view.x - (ev.clientX - start.clientX) * start.view.width / Math.max(1, rect.width),
              y: start.view.y - (ev.clientY - start.clientY) * start.view.height / Math.max(1, rect.height),
            });
            return;
          }
          const startPoint = marqueeStart.current;
          if (startPoint) {
            const point = worldPoint(ev.clientX, ev.clientY, ev.currentTarget.getBoundingClientRect());
            setMarquee({ x1: startPoint.x, y1: startPoint.y, x2: point.x, y2: point.y });
            return;
          }
          if (!dragging) return;
          const r = ev.currentTarget.getBoundingClientRect();
          const vb = box.split(' ').map(Number);
          const sx = (vb[2] || 1) / Math.max(1, r.width);
          const sy = (vb[3] || 1) / Math.max(1, r.height);
          const rawX = (vb[0] || 0) + (ev.clientX - r.left) * sx;
          const rawY = (vb[1] || 0) + (ev.clientY - r.top) * sy;
          const snap = (value: number): number => snapToGrid ? Math.round(value / 20) * 20 : Math.round(value);
          setDragPoint({ id: dragging, x: snap(rawX), y: snap(rawY) });
        }}
        onMouseUp={(ev) => {
          finishMarquee(ev.clientX, ev.clientY, ev.currentTarget.getBoundingClientRect());
          panStart.current = null; finishDrag();
        }}
        onMouseLeave={(ev) => {
          finishMarquee(ev.clientX, ev.clientY, ev.currentTarget.getBoundingClientRect());
          panStart.current = null; finishDrag();
        }}
        style={{ background: 'var(--bg-raise)', border: '1px solid var(--border)', borderRadius: 8, cursor: panMode ? 'grab' : undefined }}>
        {store.doc.edges.map((e) => {
          const a = byId.get(e.src);
          const b = byId.get(e.dst);
          if (!a || !b) return null;
          const route = routeEdge(e);
          return (
            <g key={e.id}>
              {/* fat invisible hit area so a thin link is still clickable */}
              <path d={pathFor(route)}
                fill="none" stroke="transparent" strokeWidth={14} style={{ cursor: 'pointer' }}
                role="button" tabIndex={0} aria-label={`edge ${e.id} ${e.src} to ${e.dst}`} aria-pressed={selectedEdges.has(e.id)}
                onClick={(ev) => {
                  ev.stopPropagation(); setSel(null); setSelectedNodes(new Set()); setSrc('');
                  const next = ev.shiftKey ? new Set(selectedEdges) : new Set<string>();
                  if (ev.shiftKey && next.has(e.id)) next.delete(e.id); else next.add(e.id);
                  setSelectedEdges(next); setSelEdge(next.has(e.id) ? e.id : ([...next].pop() ?? null));
                }}
                onKeyDown={(ev) => {
                  if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault(); setSel(null); setSelectedNodes(new Set()); setSelectedEdges(new Set([e.id])); setSelEdge(e.id);
                  }
                }}
                data-testid={`edge-hit-${e.id}`} />
              <path d={pathFor(route)}
                fill="none"
                stroke={selectedEdges.has(e.id) || selEdge === e.id ? 'var(--warn, #d9a441)' : 'var(--accent)'}
                strokeWidth={selectedEdges.has(e.id) || selEdge === e.id ? 6 : 3} opacity={0.85} />
            </g>
          );
        })}
        {store.doc.nodes.map((n) => {
          const select = (additive = false): void => { selectNode(n.id, additive); };
          const isSelected = selectedNodes.has(n.id);
          const position = dragPoint?.id === n.id ? dragPoint : n;
          return (
          <g key={n.id} transform={`translate(${position.x},${position.y})`} role="button" tabIndex={0}
            aria-label={`${n.id} ${n.role}`} aria-pressed={isSelected}
            onMouseDown={(event) => { if (event.button === 0 && !panMode) { event.stopPropagation(); setDragging(n.id); setDragPoint({ id: n.id, x: n.x, y: n.y }); } }}
            onClick={(event) => select(event.shiftKey)} onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(event.shiftKey); }
            }} style={{ cursor: dragging === n.id ? 'grabbing' : 'grab' }}>
            <rect x={-34} y={-20} width={68} height={40} rx={6}
              fill={isSelected ? 'var(--accent-dim)' : 'var(--bg-card)'}
              stroke={isSelected ? 'var(--accent)' : 'var(--border)'} strokeWidth={isSelected ? 2 : 1} />
            <text textAnchor="middle" y={-1} fontSize={11} fill="var(--text)" fontFamily="monospace">{n.id.slice(0, 9)}</text>
            <text textAnchor="middle" y={13} fontSize={9} fill="var(--muted)" fontFamily="monospace">{n.role.slice(0, 10)}</text>
            {Array.from({ length: n.ports }, (_, index) => {
              const leftCount = Math.ceil(n.ports / 2);
              const onLeft = index < leftCount;
              const sideIndex = onLeft ? index : index - leftCount;
              const sideCount = onLeft ? leftCount : n.ports - leftCount;
              const cy = -15 + (sideIndex + 1) * 30 / (sideCount + 1);
              return <circle key={`${n.id}-port-${index}`} data-testid={`port-${n.id}-${index + 1}`}
                role="img" aria-label={`${n.id} port ${index + 1}`} cx={onLeft ? -34 : 34} cy={cy} r={3}
                fill="var(--accent)" stroke="var(--bg-card)" strokeWidth={1} />;
            })}
          </g>
          );
        })}
        {marquee && <rect data-testid="selection-marquee"
          x={Math.min(marquee.x1, marquee.x2)} y={Math.min(marquee.y1, marquee.y2)}
          width={Math.abs(marquee.x2 - marquee.x1)} height={Math.abs(marquee.y2 - marquee.y1)}
          fill="var(--accent)" fillOpacity={0.12} stroke="var(--accent)" strokeDasharray="4 3"
          pointerEvents="none" />}
      </svg>
      {selEdge && (() => {
        const e = store.doc.edges.find((x) => x.id === selEdge);
        if (!e) return null;
        const num = (v: string, min: number): number => Math.max(min, Number(v) | 0);
        return (
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <span><code>{e.id}</code> <span className="muted">{e.src} → {e.dst}</span></span>
            <label>width <input aria-label={`edge width ${e.id}`} type="number" min={1} defaultValue={e.width} key={`${e.id}-w${e.width}`} style={{ width: 70 }}
              onBlur={(ev) => run({ type: 'update_edge', id: e.id, patch: { width: num(ev.target.value, 1) } })} /></label>
            <label>stages <input aria-label={`edge stages ${e.id}`} type="number" min={1} defaultValue={e.pipelineStages} key={`${e.id}-s${e.pipelineStages}`} style={{ width: 70 }}
              onBlur={(ev) => run({ type: 'update_edge', id: e.id, patch: { pipelineStages: num(ev.target.value, 1) } })} /></label>
            <label>vc class <input aria-label={`edge vc ${e.id}`} type="number" min={0} defaultValue={e.vcClass} key={`${e.id}-v${e.vcClass}`} style={{ width: 70 }}
              onBlur={(ev) => run({ type: 'update_edge', id: e.id, patch: { vcClass: num(ev.target.value, 0) } })} /></label>
            <label>{e.src} port <input aria-label={`edge src port ${e.id}`} type="number" min={0} max={Math.max(0, (store.doc.nodes.find((node) => node.id === e.src)?.ports ?? 1) - 1)} value={e.srcPort ?? ''} style={{ width: 70 }}
              onChange={(ev) => run({ type: 'update_edge', id: e.id, patch: { srcPort: ev.target.value === '' ? undefined : num(ev.target.value, 0) } })} /></label>
            <label>{e.dst} port <input aria-label={`edge dst port ${e.id}`} type="number" min={0} max={Math.max(0, (store.doc.nodes.find((node) => node.id === e.dst)?.ports ?? 1) - 1)} value={e.dstPort ?? ''} style={{ width: 70 }}
              onChange={(ev) => run({ type: 'update_edge', id: e.id, patch: { dstPort: ev.target.value === '' ? undefined : num(ev.target.value, 0) } })} /></label>
            <button type="button" className="btn" onClick={() => { run({ type: 'delete_edge', id: e.id }); setSelEdge(null); }}>delete link</button>
          </div>
        );
      })()}
      {sel && byId.get(sel) && (
        <div className="row" style={{ gap: 8, marginTop: 8 }}>
          <span><code>{sel}</code></span>
          <label>X <input aria-label="node x" type="number" defaultValue={byId.get(sel)?.x} key={`${sel}-x`} style={{ width: 80 }}
            onBlur={(e) => run({ type: 'move_node', id: sel, x: Math.round(Number(e.target.value) / 20) * 20, y: byId.get(sel)?.y ?? 0 })} /></label>
          <label>Y <input aria-label="node y" type="number" defaultValue={byId.get(sel)?.y} key={`${sel}-y`} style={{ width: 80 }}
            onBlur={(e) => run({ type: 'move_node', id: sel, x: byId.get(sel)?.x ?? 0, y: Math.round(Number(e.target.value) / 20) * 20 })} /></label>
          <label>Role
            <select aria-label="node role" value={byId.get(sel)?.role} onChange={(e) => run({ type: 'update_node', id: sel, patch: { role: e.target.value } })}>
              {['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU'].map((r) => <option key={r} value={r}>{r === 'NPU' ? 'NPU (local only)' : r}</option>)}
            </select>
          </label>
          <label>ports
            <input aria-label="node ports" type="number" min={1} defaultValue={byId.get(sel)?.ports} key={`${sel}-p${byId.get(sel)?.ports}`} style={{ width: 70 }}
              onBlur={(e) => run({ type: 'update_node', id: sel, patch: { ports: Math.max(1, Number(e.target.value) | 0) } })} />
          </label>
          <label>clock
            <input aria-label="node clock" defaultValue={byId.get(sel)?.clock ?? ''} key={`${sel}-c${byId.get(sel)?.clock ?? ''}`} style={{ width: 90 }}
              onBlur={(e) => run({ type: 'update_node', id: sel, patch: { clock: e.target.value.trim() || null } })} />
          </label>
          <label>vc depth
            <input aria-label="node vc depth" type="number" min={1} defaultValue={String(((byId.get(sel)?.vc ?? {}) as Record<string, unknown>).depth ?? 4)} key={`${sel}-d${String(((byId.get(sel)?.vc ?? {}) as Record<string, unknown>).depth ?? 4)}`} style={{ width: 70 }}
              onBlur={(e) => run({ type: 'update_node', id: sel, patch: { vc: { ...((byId.get(sel)?.vc ?? {}) as object), depth: Math.max(1, Number(e.target.value) | 0) } } })} />
          </label>
        </div>
      )}
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <select aria-label="edge source" value={src} onChange={(e) => setSrc(e.target.value)}>
          <option value="">src…</option>
          {store.doc.nodes.map((n) => <option key={n.id} value={n.id}>{n.id}</option>)}
        </select>
        <select aria-label="edge target" value={dst} onChange={(e) => setDst(e.target.value)}>
          <option value="">dst…</option>
          {store.doc.nodes.map((n) => <option key={n.id} value={n.id}>{n.id}</option>)}
        </select>
        <button type="button" className="btn" disabled={!src || !dst || src === dst} onClick={() => {
          if (src && dst && src !== dst) {
            store.run({ type: 'add_edge', edge: { id: nextEdgeId(store.doc.edges), src, dst, width: 512, pipelineStages: 1, vcClass: 0 } });
          }
        }}>Wire link</button>
      </div>
      <p className="muted">Link routing is Manhattan geometry on the canvas. Port capacity and connectivity validate on every edit; a refused edit changes nothing.</p>
    </div>
  );
}

/** P2: node table over graph nodes — plain rows, paged, with batch VC + CSV. */
export function NodeTable({ store }: { store: GraphStore }): ReactElement {
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const [vcDepth, setVcDepth] = useState(8);
  const [error, setError] = useState<string | null>(null);
  const PAGE = 40;
  const rows = store.doc.nodes.filter((n) => !q || `${n.id} ${n.role} ${n.clock ?? ''}`.toLowerCase().includes(q.toLowerCase()));
  const slice = rows.slice(page * PAGE, page * PAGE + PAGE);
  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <input aria-label="filter nodes" placeholder="filter id / role / clock…" value={q}
          onChange={(e) => { setQ(e.target.value); setPage(0); }} />
        <button type="button" className="btn" onClick={() => download('nodes.csv', nodesToCsv(store.doc), 'text/csv')}>Export CSV</button>
        <label className="btn" style={{ cursor: 'pointer' }}>Import CSV
          <input type="file" accept=".csv" hidden onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            try {
              const patches = csvToNodePatches(await f.text());
              for (const p of patches) {
                const { id, ...patch } = p;
                store.run({ type: 'update_node', id, patch });
              }
              setError(null);
            } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
            e.target.value = '';
          }} />
        </label>
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <input aria-label="vc template depth" type="number" value={vcDepth} style={{ width: 80 }}
          onChange={(e) => setVcDepth(Math.max(1, Number(e.target.value) | 0))} />
        <button type="button" className="btn" onClick={() => {
          for (const n of rows) store.run({ type: 'update_node', id: n.id, patch: { vc: { ...((n.vc ?? {}) as object), depth: vcDepth } } });
        }}>Batch apply VC depth → {rows.length} rows</button>
        <span className="muted">{rows.length} rows · page {page + 1} of {Math.max(1, Math.ceil(rows.length / PAGE))}</span>
      </div>
      {error && <p className="t-bad" role="alert">✗ {error}</p>}
      <div>
        {slice.map((n) => (
          <div className="row" key={n.id} style={{ gap: 8, padding: '3px 0', borderTop: '1px solid var(--border)' }}>
            <code>{n.id}</code>
            <select aria-label={`role ${n.id}`} value={n.role}
              onChange={(e) => store.run({ type: 'update_node', id: n.id, patch: { role: e.target.value } })}>
              {['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU'].map((r) => <option key={r} value={r}>{r === 'NPU' ? 'NPU (local only)' : r}</option>)}
            </select>
            <label>ports <input aria-label={`ports ${n.id}`} type="number" defaultValue={n.ports} key={`${n.id}-p${n.ports}`} style={{ width: 60 }}
              onBlur={(e) => store.run({ type: 'update_node', id: n.id, patch: { ports: Math.max(1, Number(e.target.value) | 0) } })} /></label>
            <label>clock <input aria-label={`clock ${n.id}`} defaultValue={n.clock ?? ''} key={`${n.id}-c${n.clock ?? ''}`} style={{ width: 100 }}
              onBlur={(e) => store.run({ type: 'update_node', id: n.id, patch: { clock: e.target.value.trim() || null } })} /></label>
            <span className="muted">vc {String(((n.vc ?? {}) as Record<string, unknown>).depth ?? '—')}</span>
          </div>
        ))}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <button type="button" className="btn" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Prev</button>
        <button type="button" className="btn" disabled={(page + 1) * PAGE >= rows.length} onClick={() => setPage((p) => p + 1)}>Next</button>
      </div>
    </div>
  );
}

type Cell = 'none' | 'RO' | 'RW';

/** P3: firewall authoring. Intent only — no firewall engine executes it. */
export function FirewallEditor({ store }: { store: GraphStore }): ReactElement {
  const ids = store.doc.nodes.map((n) => n.id);
  const xySupported = supportsXYRouting(store.doc);
  const [expanded, setExpanded] = useState(false);
  const [bulkSource, setBulkSource] = useState(ids[0] ?? '');
  const [bulkTarget, setBulkTarget] = useState(ids[0] ?? '');
  const [selectedCell, setSelectedCell] = useState<{ src: string; dst: string } | null>(null);
  const [customRouteDraft, setCustomRouteDraft] = useState<CustomRoutingRule[]>(store.doc.routing?.policy === 'custom' ? store.doc.routing.rules : []);
  const [routeApplyMessage, setRouteApplyMessage] = useState<string | null>(null);
  const cap = expanded ? 24 : 12;
  const vis = ids.slice(0, cap);
  const rawRules = store.doc.firewall?.rules;
  const isFirewallRule = (value: unknown): value is FirewallRule => value !== null
    && typeof value === 'object' && !Array.isArray(value)
    && typeof (value as Record<string, unknown>).src === 'string'
    && Boolean((value as Record<string, unknown>).src)
    && typeof (value as Record<string, unknown>).dst === 'string'
    && Boolean((value as Record<string, unknown>).dst)
    && ['RO', 'RW'].includes(String((value as Record<string, unknown>).perm));
  const rawRuleArray: unknown[] = Array.isArray(rawRules) ? rawRules as unknown[] : [];
  const saved: FirewallRule[] = rawRuleArray.filter(isFirewallRule);
  const allowedRouteChecks = useMemo(() => validateAllowedRouteReachability(store.doc), [store.doc]);
  const allowedRouteFailures = allowedRouteChecks.filter((check) => check.error !== null);
  const ruleIssues = [
    ...(Array.isArray(rawRules) ? inspectFirewallRules(rawRules, ids)
      : rawRules === undefined
        ? (store.doc.firewall ? [{ index: 0, previousIndex: null, kind: 'invalid' as const, message: 'firewall.rules is required' }] : [])
        : [{ index: 0, previousIndex: null, kind: 'invalid' as const, message: 'firewall.rules must be an array' }]),
    ...(store.doc.firewall && store.doc.firewall.default !== 'deny'
      ? [{ index: 0, previousIndex: null, kind: 'invalid' as const, message: 'firewall.default must be deny' }]
      : []),
  ];
  const cellOf = (a: string, b: string): Cell => {
    const r = saved.find((x) => x.src === a && x.dst === b);
    return r?.perm === 'RW' ? 'RW' : r?.perm === 'RO' ? 'RO' : 'none';
  };
  const cellLabel = (a: string, b: string): string => cellOf(a, b) === 'none' ? 'DENY' : cellOf(a, b);
  const write = (rules: FirewallRule[]): void => {
    store.run({ type: 'set_firewall', firewall: canonicalFirewall(rules) as unknown as { [key: string]: import('../../graph/project').JsonValue } });
  };
  const cycle = (a: string, b: string): void => {
    const cur = cellOf(a, b);
    const next = cur === 'none' ? 'RO' : cur === 'RO' ? 'RW' : 'none';
    const rules = saved.filter((x) => !(x.src === a && x.dst === b));
    if (next !== 'none') rules.push({ src: a, dst: b, perm: next });
    write(rules);
  };
  const setRow = (src: string, perm: Cell): void => write(setFirewallRow(saved, ids, src, perm));
  const setColumn = (dst: string, perm: Cell): void => write(setFirewallColumn(saved, ids, dst, perm));
  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button type="button" className="btn" onClick={() => write([])}>Deny by default</button>
        <button type="button" className="btn" onClick={() => write(allowAllFirewallRules(ids))}>Allow all (all graph nodes)</button>
        <label>Routing policy
          <select aria-label="routing policy" value={store.doc.routing?.policy ?? ''} onChange={(event) => {
            const policy = event.target.value;
            const routing = policy === 'xy' ? { policy: 'xy' as const }
              : policy === 'west_first' ? { policy: 'west_first' as const }
                : policy === 'odd_even' ? { policy: 'odd_even' as const }
                  : policy === 'custom' ? { policy: 'custom' as const, rules: [] } : undefined;
            const refused = store.run({ type: 'set_routing', routing });
            if (!refused && policy === 'custom') setCustomRouteDraft([]);
            setRouteApplyMessage(refused);
          }}>
            <option value="">Unselected</option>
            <option value="xy" disabled={!xySupported}>XY (canonical mesh only)</option>
            <option value="west_first" disabled={!xySupported}>West-First (canonical mesh only)</option>
            <option value="odd_even" disabled={!xySupported}>Odd-Even (canonical mesh only)</option>
            <option value="custom">Custom next-hop table</option>
          </select>
        </label>
        {ids.length > cap && (
          <button type="button" className="btn" onClick={() => setExpanded((s) => !s)}>
            {expanded ? 'Collapse' : `Expand (${ids.length} nodes)`}
          </button>
        )}
        <span className="muted">{saved.length} rules · default deny · keyed on node id</span>
      </div>
      {ruleIssues.length > 0 && <ul role="alert" aria-label="Firewall rule conflicts" className="t-warn">
        {ruleIssues.map((issue) => <li key={`${issue.previousIndex ?? 'invalid'}-${issue.index}-${issue.kind}-${issue.message}`}>{issue.previousIndex === null ? `Invalid rule at index ${issue.index}` : `${issue.kind} rules at indices ${issue.previousIndex} and ${issue.index}`}: {issue.message}</li>)}
      </ul>}
      {store.doc.firewall && <details aria-label="Allowed route reachability">
        <summary>Allowed route reachability: {allowedRouteChecks.length - allowedRouteFailures.length} valid / {allowedRouteFailures.length} errors</summary>
        {allowedRouteChecks.length === 0 ? <p>No explicitly allowed source/target pairs.</p> : <ul>
          {allowedRouteChecks.map((check, index) => <li key={`reachability-${index}`}>
            {check.src} → {check.dst} ({check.perm}): {check.error ?? check.route?.nodePath.join(' → ')}{check.error ? '' : ` · ${check.route?.hops.length ?? 0} hops`}
          </li>)}
        </ul>}
      </details>}
      {store.doc.routing?.policy === 'custom' && <fieldset aria-label="Custom routing table">
        <legend>Custom next-hop rules</legend>
        <p className="muted">Each rule selects one next hop for an ordered source/destination pair. Loops are rejected; incomplete tables remain explicit and preview as missing rather than guessed.</p>
        {customRouteDraft.map((rule, index) => <div className="row" key={`custom-route-${index}`} style={{ gap: 8 }}>
          <label>Source <input aria-label={`route source ${index}`} value={rule.src} onChange={(event) => setCustomRouteDraft((draft) => draft.map((entry, row) => row === index ? { ...entry, src: event.target.value } : entry))} /></label>
          <label>Destination <input aria-label={`route destination ${index}`} value={rule.dst} onChange={(event) => setCustomRouteDraft((draft) => draft.map((entry, row) => row === index ? { ...entry, dst: event.target.value } : entry))} /></label>
          <label>Next hop <input aria-label={`route next hop ${index}`} value={rule.nextHop} onChange={(event) => setCustomRouteDraft((draft) => draft.map((entry, row) => row === index ? { ...entry, nextHop: event.target.value } : entry))} /></label>
          <button type="button" className="btn" aria-label={`remove route rule ${index}`} onClick={() => setCustomRouteDraft((draft) => draft.filter((_, row) => row !== index))}>Remove rule</button>
        </div>)}
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn" onClick={() => setCustomRouteDraft((draft) => [...draft, { src: '', dst: '', nextHop: '' }])}>+ Next-hop rule</button>
          <button type="button" className="btn" disabled={validateCustomRoutingRules(store.doc.nodes, store.doc.edges, customRouteDraft).length > 0} onClick={() => {
            const refused = store.run({ type: 'set_routing', routing: { policy: 'custom', rules: customRouteDraft } });
            setRouteApplyMessage(refused ?? `Applied ${customRouteDraft.length} custom next-hop rule(s).`);
          }}>Apply custom routing table</button>
        </div>
        {validateCustomRoutingRules(store.doc.nodes, store.doc.edges, customRouteDraft).length > 0 && <ul role="alert" aria-label="Custom routing validation issues" className="t-warn">
          {validateCustomRoutingRules(store.doc.nodes, store.doc.edges, customRouteDraft).map((message) => <li key={message}>{message}</li>)}
        </ul>}
        {routeApplyMessage && <p role="status">{routeApplyMessage}</p>}
      </fieldset>}
      <div className="row" style={{ gap: 6, marginBottom: 8 }}>
        <label>Bulk source <select aria-label="bulk source node" value={ids.includes(bulkSource) ? bulkSource : ids[0] ?? ''} onChange={(e) => setBulkSource(e.target.value)}>{ids.map((id) => <option key={id}>{id}</option>)}</select></label>
        <label>Bulk target <select aria-label="bulk target node" value={ids.includes(bulkTarget) ? bulkTarget : ids[0] ?? ''} onChange={(e) => setBulkTarget(e.target.value)}>{ids.map((id) => <option key={id}>{id}</option>)}</select></label>
        {(['RO', 'RW', 'none'] as const).map((perm) => <button type="button" key={`row-${perm}`} className="btn" disabled={!ids.includes(bulkSource)} onClick={() => setRow(bulkSource, perm)}>Set row {perm === 'none' ? 'DENY' : perm}</button>)}
        {(['RO', 'RW', 'none'] as const).map((perm) => <button type="button" key={`column-${perm}`} className="btn" disabled={!ids.includes(bulkTarget)} onClick={() => setColumn(bulkTarget, perm)}>Set column {perm === 'none' ? 'DENY' : perm}</button>)}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${vis.length + 1}, minmax(44px, auto))`, gap: 2, overflow: 'auto' }}>
        <span />
        {vis.map((b) => <span key={b} className="muted" style={{ fontSize: 10 }}><code>{b.slice(0, 6)}</code></span>)}
        {vis.map((a) => (
          <>
            <span key={`${a}-h`} className="muted" style={{ fontSize: 10 }}><code>{a.slice(0, 6)}</code></span>
            {vis.map((b) => (
              a === b
                ? <span key={`${a}${b}`} className="muted" style={{ textAlign: 'center' }}>—</span>
                : (
                  <button type="button" key={`${a}${b}`} className="btn" style={{ minWidth: 44, padding: '2px 4px' }}
                    aria-label={`${a} to ${b}: ${cellLabel(a, b)}`} onClick={() => { setSelectedCell({ src: a, dst: b }); cycle(a, b); }}>
                    {cellLabel(a, b)}
                  </button>
                )
            ))}
          </>
        ))}
      </div>
      {selectedCell && <div role="group" aria-label="Firewall cell inspector">
        <strong>Selected cell</strong>: <code>{selectedCell.src} → {selectedCell.dst}</code>
        {(() => {
          const rule = saved.find((entry) => entry.src === selectedCell.src && entry.dst === selectedCell.dst);
          const path = previewConnectivityPath(ids, store.doc.edges, selectedCell.src, selectedCell.dst);
          const xyPath = store.doc.routing?.policy === 'xy'
            ? previewXYPath(store.doc, selectedCell.src, selectedCell.dst) : null;
          const westFirstPath = store.doc.routing?.policy === 'west_first'
            ? previewWestFirstPath(store.doc, selectedCell.src, selectedCell.dst) : null;
          const oddEvenPath = store.doc.routing?.policy === 'odd_even'
            ? previewOddEvenPath(store.doc, selectedCell.src, selectedCell.dst) : null;
          const customPath = store.doc.routing?.policy === 'custom'
            ? previewCustomPath(store.doc, selectedCell.src, selectedCell.dst) : null;
          return <>
            <p>Matched rule: {rule ? JSON.stringify({ src: rule.src, dst: rule.dst, perm: rule.perm }) : 'none (default deny)'}</p>
            <p>Permission: {rule?.perm ?? 'deny'} · precedence: {rule ? 'explicit rule' : 'default deny'}</p>
            {xyPath
              ? xyPath.route
                ? <p>XY routed path: {xyPath.route.hops.map((hop) => `${hop.src} —${hop.edgeId}→ ${hop.dst} [ports ${hop.srcPort ?? 'unassigned'}→${hop.dstPort ?? 'unassigned'}; VC ${hop.vcClass}]`).join(' · ') || 'same router'} · provenance {xyPath.route.provenance}</p>
                : <p>XY route preview refused: {xyPath.error}</p>
              : westFirstPath
                ? westFirstPath.route
                  ? <p>West-First routed path: {westFirstPath.route.hops.map((hop) => `${hop.src} —${hop.edgeId}→ ${hop.dst} [ports ${hop.srcPort ?? 'unassigned'}→${hop.dstPort ?? 'unassigned'}; VC ${hop.vcClass}]`).join(' · ') || 'same router'} · provenance {westFirstPath.route.provenance}</p>
                  : <p>West-First route preview refused: {westFirstPath.error}</p>
                  : oddEvenPath
                    ? oddEvenPath.route
                      ? <p>Odd-Even routed path: {oddEvenPath.route.hops.map((hop) => `${hop.src} —${hop.edgeId}→ ${hop.dst} [ports ${hop.srcPort ?? 'unassigned'}→${hop.dstPort ?? 'unassigned'}; VC ${hop.vcClass}]`).join(' · ') || 'same router'} · provenance {oddEvenPath.route.provenance}</p>
                      : <p>Odd-Even route preview refused: {oddEvenPath.error}</p>
                    : customPath
                      ? customPath.route
                  ? <p>Custom routed path: {customPath.route.hops.map((hop) => `${hop.src} —${hop.edgeId}→ ${hop.dst} [ports ${hop.srcPort ?? 'unassigned'}→${hop.dstPort ?? 'unassigned'}; VC ${hop.vcClass}]`).join(' · ') || 'same router'} · provenance {customPath.route.provenance}</p>
                  : <p>Custom route preview unavailable: {customPath.error}</p>
                : path ? <p>Topology connectivity only (not routed): {path.hops.map((hop) => `${hop.src} —${hop.edgeId}→ ${hop.dst} [ports ${hop.srcPort ?? 'unassigned'}→${hop.dstPort ?? 'unassigned'}; VC ${hop.vcClass}]`).join(' · ') || 'same node'} · provenance {path.provenance}</p>
                  : <p>No topology connectivity path exists for this pair.</p>}
          </>;
        })()}
      </div>}
      <p className="muted">Cells cycle DENY → RO → RW → DENY; absent rules mean default deny. Quadratic sizing: the grid caps at {cap} nodes per side.</p>
    </div>
  );
}

interface Phase { id: string; name?: string; kind: string; startCycle?: number; durationCycles?: number; tokens: number; batch: number; tp: number; ep: number; pp: number; dp: number }
interface WorkloadDoc { modelFamily: string; modelName?: string; paramsB?: number; hiddenSize?: number; layerCount?: number; seqLen: number; batch: number; precision: string; phases: Phase[]; communications?: WorkloadCommunication[]; rankMappings?: WorkloadRankMapping[]; rankConstraints?: WorkloadRankConstraint[]; trafficClassMappings?: WorkloadTrafficClassMapping[]; defaultTrafficClassMapping?: Omit<WorkloadTrafficClassMapping, 'trafficClass'> }

const STARTER: WorkloadDoc = {
  modelFamily: 'dense-47B', paramsB: 47, seqLen: 4096, batch: 8, precision: 'fp16',
  phases: [
    { id: 'ph-prefill', kind: 'prefill', tokens: 4096, batch: 8, tp: 8, ep: 8, pp: 1, dp: 1 },
    { id: 'ph-decode', kind: 'decode', tokens: 512, batch: 8, tp: 8, ep: 1, pp: 1, dp: 1 },
  ],
};

function readWorkload(store: GraphStore): WorkloadDoc | null {
  const w = store.doc.workload as unknown as WorkloadDoc | undefined;
  if (!w || !Array.isArray(w.phases)) return null;
  return w;
}

function validTrafficClassMapping(value: unknown): value is WorkloadTrafficClassMapping {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return typeof row.trafficClass === 'string' && Number.isSafeInteger(row.vcClass)
    && typeof row.qosClass === 'string';
}

function validRankConstraint(value: unknown): value is WorkloadRankConstraint {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return Number.isSafeInteger(row.rank) && typeof row.rank === 'number'
    && (row.pinnedNodeId === undefined || typeof row.pinnedNodeId === 'string')
    && (row.requiredRole === undefined || typeof row.requiredRole === 'string')
    && (row.allowedNodeIds === undefined || (Array.isArray(row.allowedNodeIds) && row.allowedNodeIds.every((id) => typeof id === 'string')));
}

/** P5: phase editor writing workload.phases[] — this view and playback read it. */
export function WorkloadEditor({ store }: { store: GraphStore }): ReactElement {
  const [mappingFilter, setMappingFilter] = useState('');
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [rankPolicy, setRankPolicy] = useState<RankAssignmentPolicy>('graph-order');
  const [backendId, setBackendId] = useState<string>(DECLARED_BACKENDS[0]!.id);
  const w = readWorkload(store);
  if (!w) {
    return (
      <div>
        <p className="muted">No workload block on the graph yet. Cycles live in workload.phases[], never hardcoded in views.</p>
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn" onClick={() => store.run({ type: 'set_workload', workload: emptyWorkload() as unknown as { [key: string]: import('../../graph/project').JsonValue } })}>Create empty custom workload</button>
          <button type="button" className="btn" onClick={() => store.run({ type: 'set_workload', workload: STARTER as unknown as { [key: string]: import('../../graph/project').JsonValue } })}>Load dense example</button>
        </div>
        <p className="muted">Empty custom starts with no assumed model shape, phases, communication operations or rank mappings. Required sequence, batch and precision values are visible and editable; validation remains blocked until you author a phase.</p>
        <p className="muted">Dense example assumptions are shown as editable fields when loaded: 47B label, seq 4096, batch 8, fp16, prefill TP8/EP8 and decode TP8/EP1. No communications, phase cycle timing, or measured behavior is implied.</p>
      </div>
    );
  }
  const graphVcClasses = [...new Set(store.doc.edges.map((edge) => edge.vcClass))].sort((a, b) => a - b);
  const workloadIssues = validateWorkload(w, store.doc.nodes.length, store.doc.nodes.map((node) => node.id), graphVcClasses);
  const rankDemand = requiredRankCount(w);
  const mappedRanks = new Set((w.rankMappings ?? []).map((mapping) => mapping.rank)).size;
  const declaredPayload = (w.communications ?? []).reduce((sum, op) => sum + (Number.isSafeInteger(op.payloadBytes) && op.payloadBytes > 0 ? op.payloadBytes : 0), 0);
  const runIntent = buildWorkloadRunIntent(w, store.doc.nodes.map((node) => node.id), graphVcClasses);
  const routingCompatibilityIssues = validateWorkloadRoutingCompatibility(store.doc, w);
  const runIntentIssues = [...runIntent.issues, ...routingCompatibilityIssues];
  const backend = findDeclaredBackend(backendId) ?? DECLARED_BACKENDS[0]!;
  const backendVerdict = classifyWorkloadBackend(w, store.doc.nodes.map((node) => node.id), backend, graphVcClasses);
  const backendStateLabel = { supported: 'SUPPORTED', unsupported: 'UNSUPPORTED', blocked: 'BLOCKED' }[backendVerdict.state];
  const rankConstraints = Array.isArray(w.rankConstraints) ? w.rankConstraints.filter(validRankConstraint) : [];
  const trafficClassMappings = Array.isArray(w.trafficClassMappings) ? w.trafficClassMappings.filter(validTrafficClassMapping) : [];
  const set = (patch: Partial<WorkloadDoc>): void => {
    store.run({ type: 'set_workload', workload: omitUndefined({ ...w, ...patch }) as { [key: string]: JsonValue } });
  };
  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <label>Import workload JSON <input aria-label="import workload JSON" type="file" accept="application/json,.json" onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          try {
            const parsed = parseWorkloadJson(await file.text(), store.doc.nodes.map((node) => node.id), graphVcClasses);
            if (parsed.workload) {
              const out = store.run({ type: 'set_workload', workload: parsed.workload as unknown as { [key: string]: import('../../graph/project').JsonValue } });
              setImportMessage(out ? `Import refused: ${out}` : `Imported ${file.name}`);
            } else setImportMessage(`Import rejected: ${parsed.issues.join('; ')}`);
          } catch (error) {
            setImportMessage(`Import failed: ${error instanceof Error ? error.message : String(error)}`);
          }
          e.target.value = '';
        }} /></label>
        <button type="button" className="btn" onClick={() => download('workload.json', serializeWorkloadJson(w))}>Export workload JSON</button>
        <button type="button" className="btn" disabled={!runIntent.json || runIntentIssues.length > 0} onClick={() => { if (runIntent.json && runIntentIssues.length === 0) download('workload-run-intent.json', runIntent.json); }}>Export validated run intent</button>
        <span className="muted" role="status">Run-intent status: {runIntent.json && runIntentIssues.length === 0 ? 'READY (intent only)' : `BLOCKED · ${runIntentIssues.length} issue(s)`}</span>
        {importMessage && <span className="muted" role="status">{importMessage}</span>}
        <label>Model family <input aria-label="model family" value={w.modelFamily} onChange={(e) => set({ modelFamily: e.target.value })} /></label>
        <label>Model name (optional) <input aria-label="model name" value={w.modelName ?? ''} onChange={(e) => set({ modelName: e.target.value || undefined })} /></label>
        <label>Parameters (B, optional) <input aria-label="parameter count billions" type="number" min={0} step="any" value={w.paramsB ?? ''} onChange={(e) => set({ paramsB: e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
        <label>Hidden size (optional) <input aria-label="hidden size" type="number" min={1} value={w.hiddenSize ?? ''} onChange={(e) => set({ hiddenSize: e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
        <label>Layers (optional) <input aria-label="layer count" type="number" min={1} value={w.layerCount ?? ''} onChange={(e) => set({ layerCount: e.target.value === '' ? undefined : Number(e.target.value) })} /></label>
        <label>Seq <input aria-label="seq len" type="number" value={w.seqLen} style={{ width: 90 }} onChange={(e) => set({ seqLen: Number(e.target.value) | 0 })} /></label>
        <label>Batch <input aria-label="batch" type="number" value={w.batch} style={{ width: 70 }} onChange={(e) => set({ batch: Number(e.target.value) | 0 })} /></label>
        <label>Precision
          <select aria-label="precision" value={w.precision} onChange={(e) => set({ precision: e.target.value })}>
            <option>fp16</option><option>fp8</option><option>int8</option><option>bf16</option>
          </select>
        </label>
      </div>
      {routingCompatibilityIssues.length > 0 && <p className="t-warn" role="status"><strong>Routing/VC preflight (authored preview only):</strong> {routingCompatibilityIssues.join('; ')}</p>}
      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
        <label>Run backend
          <select aria-label="workload backend" value={backendId} onChange={(event) => setBackendId(event.target.value)}>
            {DECLARED_BACKENDS.map((entry) => <option key={entry.id} value={entry.id}>{entry.displayName}</option>)}
          </select>
        </label>
        <span className="muted" role="status" aria-label="workload backend preflight">
          <strong>Backend preflight ({backend.displayName}, declared): {backendStateLabel}.</strong>{' '}
          {backendVerdict.reasons.length > 0
            ? backendVerdict.reasons.map((reason) => `${reason.code}: ${reason.message}`).join(' · ')
            : 'All authored features are representable by the declared backend. This is a preflight only — no metrics are produced or implied.'}
        </span>
      </div>
      <p className="t-warn" role="status"><strong>Run status: BLOCKED.</strong> The local Loom workload block has no execution-backend/run-input binding here. This workspace will not infer metrics from its MOCK playback.</p>
      {w.modelFamily === 'custom' && <p className="muted">Empty custom workload: no assumed model shape, phases, communication operations or rank mappings. Required sequence, batch and precision values remain visible/editable.</p>}
      {w.modelFamily === 'dense-47B' && <p className="muted">Dense example assumptions are editable above: 47B label, seq 4096, batch 8, fp16, prefill TP8/EP8 and decode TP8/EP1. No communications, phase cycle timing, or measured behavior is implied.</p>}
      <fieldset aria-label="Workload summary">
        <legend>Workload intent summary</legend>
        <div className="kv"><span>model shape</span><span>{w.modelFamily}{w.modelName ? ` · ${w.modelName}` : ''} · {w.paramsB === undefined ? 'parameter count unknown' : `${w.paramsB}B`} · hidden {w.hiddenSize ?? 'unknown'} · layers {w.layerCount ?? 'unknown'}</span></div>
        <div className="kv"><span>sequence/batch</span><span>seq {w.seqLen} · batch {w.batch} · precision {w.precision}</span></div>
        <div className="kv"><span>parallelism demand</span><span>TP {Math.max(0, ...w.phases.map((p) => p.tp))} / EP {Math.max(0, ...w.phases.map((p) => p.ep))} / PP {Math.max(0, ...w.phases.map((p) => p.pp))} / DP {Math.max(0, ...w.phases.map((p) => p.dp))}</span></div>
        <div className="kv"><span>phases / operations</span><span>{w.phases.length} / {(w.communications ?? []).length} · {w.phases.map((phase) => phase.name || phase.kind).join(', ')}</span></div>
        <div className="kv"><span>declared payload sum (one entry each)</span><span>{declaredPayload} B</span></div>
        <div className="kv"><span>unique mapped ranks / rank demand</span><span>{mappedRanks} / {rankDemand}</span></div>
        <p className="muted">Summary is declared workload intent, not measured communication volume or run support.</p>
      </fieldset>
      {workloadIssues.length > 0
        ? <ul className="t-warn" role="alert" aria-label="Workload validation issues">
            {workloadIssues.map((issue) => <li key={issue.objectRef}>{issue.message}</li>)}
          </ul>
        : <p className="t-ok">✓ {w.phases.length} phases validate against the {store.doc.nodes.length}-node graph</p>}
      <div>
        {w.phases.map((p, i) => (
          <div className="row" key={p.id} style={{ gap: 8, padding: '4px 0', borderTop: '1px solid var(--border)' }}>
            <code>{p.id}</code>
            <label>Phase name <input aria-label={`name ${p.id}`} value={p.name ?? ''} onChange={(e) => {
              const phases = w.phases.slice();
              phases[i] = { ...p, name: e.target.value || undefined };
              set({ phases });
            }} /></label>
            <select aria-label={`kind ${p.id}`} value={p.kind} onChange={(e) => {
              const phases = w.phases.slice();
              phases[i] = { ...p, kind: e.target.value };
              set({ phases });
            }}>
              {PHASE_KINDS.map((k) => <option key={k}>{k}</option>)}
            </select>
            <label>Tokens <input aria-label={`tokens ${p.id}`} type="number" min={1} value={p.tokens} onChange={(e) => {
              const phases = w.phases.slice();
              phases[i] = { ...p, tokens: Number(e.target.value) | 0 };
              set({ phases });
            }} /></label>
            <label>Phase batch <input aria-label={`phase batch ${p.id}`} type="number" min={1} value={p.batch} onChange={(e) => {
              const phases = w.phases.slice();
              phases[i] = { ...p, batch: Number(e.target.value) | 0 };
              set({ phases });
            }} /></label>
            {(['tp', 'ep', 'pp', 'dp'] as const).map((k) => (
              <label key={k}>{k.toUpperCase()} <input aria-label={`${k} ${p.id}`} type="number" min={1} value={p[k]} style={{ width: 56 }} onChange={(e) => {
                const phases = w.phases.slice();
                phases[i] = { ...p, [k]: Math.max(1, Number(e.target.value) | 0) };
                set({ phases });
              }} /></label>
            ))}
            <label>Start cycle <input aria-label={`start cycle ${p.id}`} type="number" min={0} value={p.startCycle ?? ''} onChange={(e) => {
              const phases = w.phases.slice();
              phases[i] = { ...p, startCycle: e.target.value === '' ? undefined : Number(e.target.value) };
              set({ phases });
            }} /></label>
            <label>Duration (cycles) <input aria-label={`duration cycles ${p.id}`} type="number" min={1} value={p.durationCycles ?? ''} onChange={(e) => {
              const phases = w.phases.slice();
              phases[i] = { ...p, durationCycles: e.target.value === '' ? undefined : Number(e.target.value) };
              set({ phases });
            }} /></label>
            <button type="button" className="btn" aria-label={`move ${p.id} up`} disabled={i === 0} onClick={() => {
              const phases = w.phases.slice();
              [phases[i - 1], phases[i]] = [phases[i]!, phases[i - 1]!];
              set({ phases });
            }}>↑</button>
            <button type="button" className="btn" aria-label={`move ${p.id} down`} disabled={i === w.phases.length - 1} onClick={() => {
              const phases = w.phases.slice();
              [phases[i], phases[i + 1]] = [phases[i + 1]!, phases[i]!];
              set({ phases });
            }}>↓</button>
            <button type="button" className="btn" onClick={() => set({ phases: w.phases.filter((x) => x.id !== p.id) })}>Remove</button>
          </div>
        ))}
      </div>
      <p className="muted">Authored phase cycle timeline (not an executed schedule).</p>
      <svg viewBox={`0 0 600 ${Math.max(1, w.phases.length) * 30 + 12}`} role="img" aria-label="Authored phase cycle timeline" style={{ width: '100%' }}>
        {(() => {
          const endCycles = w.phases.map((phase) => (phase.startCycle ?? 0) + (phase.durationCycles ?? 0)).filter(Number.isFinite);
          const extent = Math.max(1, ...endCycles);
          return w.phases.map((phase, index) => {
            const y = index * 30 + 8;
            const label = phase.name || phase.kind;
            const configured = Number.isFinite(phase.startCycle) && phase.startCycle! >= 0
              && Number.isFinite(phase.durationCycles) && phase.durationCycles! > 0;
            const x = configured ? 150 + phase.startCycle! / extent * 430 : 150;
            const width = configured ? Math.max(2, phase.durationCycles! / extent * 430) : 0;
            return <g key={phase.id}>
              <text x={4} y={y + 14} fontSize={11} fill="var(--text)">{label.slice(0, 20)}</text>
              <line x1={150} y1={y + 18} x2={580} y2={y + 18} stroke="var(--border)" />
              {configured ? <rect x={x} y={y + 4} width={width} height={16} rx={3} fill="var(--accent)" />
                : <text x={154} y={y + 14} fontSize={10} fill="var(--muted)">timing not set</text>}
            </g>;
          });
        })()}
      </svg>
      <fieldset style={{ marginTop: 12 }}>
        <legend>Rank to graph-node mapping</legend>
        <label>Filter mappings <input aria-label="filter rank mappings" value={mappingFilter} onChange={(e) => setMappingFilter(e.target.value)} /></label>
        {(w.rankMappings ?? []).filter((mapping) => `${mapping.rank} ${mapping.role} ${mapping.nodeId}`.toLowerCase().includes(mappingFilter.toLowerCase())).map((mapping) => {
          const mappings = w.rankMappings ?? [];
          const index = mappings.indexOf(mapping);
          const update = (patch: Partial<WorkloadRankMapping>): void => {
            const next = mappings.slice();
            next[index] = { ...mapping, ...patch };
            set({ rankMappings: next });
          };
          return (
            <div className={`row${selectedRank === mapping.rank ? ' selected' : ''}`} key={`${mapping.rank}-${index}`} style={{ gap: 8, padding: '4px 0' }} onClick={() => setSelectedRank(mapping.rank)}>
              <label>Rank <input aria-label={`mapping rank ${mapping.rank}`} type="number" min={0} value={mapping.rank} onChange={(e) => update({ rank: Number(e.target.value) })} /></label>
              <label>Role <input aria-label={`mapping role ${mapping.rank}`} value={mapping.role} onChange={(e) => update({ role: e.target.value })} /></label>
              <label>Graph node
                <select aria-label={`mapping node ${mapping.rank}`} value={mapping.nodeId} onChange={(e) => update({ nodeId: e.target.value })}>
                  <option value="">Choose graph node</option>
                  {store.doc.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
                </select>
              </label>
              <button type="button" className="btn" onClick={() => set({ rankMappings: mappings.filter((_, j) => j !== index) })}>Remove mapping</button>
            </div>
          );
        })}
        <p className="muted">Authored graph placement with rank assignments. Select a row or node to cross-probe the matching rank.</p>
        <svg viewBox="0 0 420 260" role="img" aria-label="Rank mapping overlay on authored graph" style={{ width: '100%', border: '1px solid var(--border)', borderRadius: 6 }}>
          {(() => {
            const nodes = store.doc.nodes;
            const xs = nodes.map((node) => node.x);
            const ys = nodes.map((node) => node.y);
            const minX = Math.min(0, ...xs); const maxX = Math.max(1, ...xs);
            const minY = Math.min(0, ...ys); const maxY = Math.max(1, ...ys);
            const assignments = w.rankMappings ?? [];
            return nodes.map((node) => {
              const assigned = assignments.filter((mapping) => mapping.nodeId === node.id);
              const selected = assigned.some((mapping) => mapping.rank === selectedRank);
              const x = 24 + ((node.x - minX) / Math.max(1, maxX - minX)) * 372;
              const y = 24 + ((node.y - minY) / Math.max(1, maxY - minY)) * 212;
              const label = assigned.map((mapping) => `r${mapping.rank}:${mapping.role}`).join(', ') || 'unmapped';
              return <g key={node.id} role="button" tabIndex={0} aria-label={`${node.id}: ${label}`} onClick={() => setSelectedRank(assigned[0]?.rank ?? null)} onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedRank(assigned[0]?.rank ?? null); }
              }} style={{ cursor: 'pointer' }}>
                <rect x={x - 18} y={y - 12} width={36} height={24} rx={4} fill={selected ? 'var(--accent)' : assigned.length ? 'var(--info)' : 'var(--bg-card)'} stroke="var(--border)" />
                <text x={x} y={y + 4} textAnchor="middle" fontSize={9} fill="var(--text)">{node.id.slice(0, 8)}</text>
                <title>{`${node.id}: ${label}`}</title>
              </g>;
            });
          })()}
        </svg>
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn" disabled={store.doc.nodes.length === 0} onClick={() => {
            const mappings = w.rankMappings ?? [];
            const used = new Set(mappings.map((mapping) => mapping.rank));
            let rank = 0;
            while (used.has(rank)) rank++;
            set({ rankMappings: [...mappings, { rank, role: 'worker', nodeId: store.doc.nodes[0]!.id }] });
          }}>+ Rank mapping</button>
          <label>Assignment policy
            <select aria-label="rank assignment policy" value={rankPolicy} onChange={(event) => setRankPolicy(event.target.value as RankAssignmentPolicy)}>
              {RANK_ASSIGNMENT_POLICIES.map((policy) => <option key={policy} value={policy}>{policy}</option>)}
            </select>
          </label>
          <button type="button" className="btn" disabled={!autoRankMappings(w, store.doc.nodes.map((node) => node.id), rankPolicy)} onClick={() => {
            const rankMappings = autoRankMappings(w, store.doc.nodes.map((node) => node.id), rankPolicy);
            if (rankMappings) set({ rankMappings });
          }}>Auto-map ranks</button>
        </div>
        <p className="muted">Auto-map replaces the current table in one undoable edit. Chosen policy: {RANK_ASSIGNMENT_POLICY_LABELS[rankPolicy]}; roles are generic ranks, not inferred TP/EP placement.</p>
        <p className="muted">Assignments reference stable authored graph node IDs; no automatic placement or execution is implied.</p>
      </fieldset>
      <fieldset style={{ marginTop: 12 }} aria-label="Rank mapping constraints">
        <legend>Rank mapping constraints</legend>
        <p className="muted">Pins, allowed graph-node sets and required roles are authored constraints. A mismatch is a validation issue; no eligibility policy is inferred.</p>
        {rankConstraints.map((constraint, index) => {
          const constraints = rankConstraints;
          const update = (patch: Partial<WorkloadRankConstraint>): void => {
            const next = constraints.slice();
            next[index] = { ...constraint, ...patch };
            set({ rankConstraints: next });
          };
          return <div className="row" key={`${constraint.rank}-${index}`} style={{ gap: 8, padding: '4px 0', borderTop: '1px solid var(--border)' }}>
            <label>Constraint rank <input aria-label={`constraint rank ${index}`} type="number" min={0} value={constraint.rank} onChange={(event) => update({ rank: Number(event.target.value) })} /></label>
            <label>Pinned graph node
              <select aria-label={`pinned node ${index}`} value={constraint.pinnedNodeId ?? ''} onChange={(event) => update({ pinnedNodeId: event.target.value || undefined })}>
                <option value="">Not pinned</option>
                {store.doc.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
              </select>
            </label>
            <label>Required role <input aria-label={`required role ${index}`} value={constraint.requiredRole ?? ''} onChange={(event) => update({ requiredRole: event.target.value || undefined })} /></label>
            <span>Allowed nodes {store.doc.nodes.map((node) => <label key={node.id} style={{ display: 'inline-flex', marginInline: 4 }}>
              <input type="checkbox" aria-label={`allowed node ${index} ${node.id}`} checked={(constraint.allowedNodeIds ?? []).includes(node.id)} onChange={(event) => {
                const allowed = new Set(constraint.allowedNodeIds ?? []);
                if (event.target.checked) allowed.add(node.id); else allowed.delete(node.id);
                update({ allowedNodeIds: [...allowed].sort() });
              }} />{node.id}
            </label>)}</span>
            <button type="button" className="btn" aria-label={`remove constraint ${index}`} onClick={() => set({ rankConstraints: constraints.filter((_, row) => row !== index) })}>Remove constraint</button>
          </div>;
        })}
        <button type="button" className="btn" onClick={() => {
          const constraints = rankConstraints;
          const rank = (w.rankMappings ?? []).find((mapping) => !constraints.some((constraint) => constraint.rank === mapping.rank))?.rank
            ?? Math.max(0, ...constraints.map((constraint) => constraint.rank + 1));
          set({ rankConstraints: [...constraints, { rank }] });
        }}>+ Rank constraint</button>
      </fieldset>
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <button type="button" className="btn" onClick={() => set({
          phases: [...w.phases, { id: nextPhaseId(w.phases), kind: 'decode', tokens: 512, batch: w.batch, tp: 1, ep: 1, pp: 1, dp: 1 }],
        })}>+ Phase</button>
        <button type="button" className="btn" onClick={() => store.run({ type: 'set_workload', workload: emptyWorkload() as unknown as { [key: string]: import('../../graph/project').JsonValue } })}>Reset to empty custom</button>
        <button type="button" className="btn" onClick={() => store.run({ type: 'set_workload', workload: undefined })}>Clear</button>
      </div>
      <fieldset style={{ marginTop: 12 }} aria-label="Traffic class VC and QoS mappings">
        <legend>Traffic class → VC/QoS mappings</legend>
        <p className="muted">VC classes offered here are the distinct classes authored on this graph's edges (none implies none available). No registry limit or backend QoS execution is inferred.</p>
        <label>Default VC class
          <select aria-label="default traffic class VC" value={w.defaultTrafficClassMapping?.vcClass ?? ''} onChange={(event) => {
            if (event.target.value === '') set({ defaultTrafficClassMapping: undefined });
            else set({ defaultTrafficClassMapping: { vcClass: Number(event.target.value), qosClass: w.defaultTrafficClassMapping?.qosClass ?? '' } });
          }}>
            <option value="">No default mapping</option>
            {graphVcClasses.map((vcClass) => <option key={vcClass} value={vcClass}>{vcClass}</option>)}
          </select>
        </label>
        {w.defaultTrafficClassMapping && <label>Default QoS class
          <input aria-label="default traffic class QoS" value={w.defaultTrafficClassMapping.qosClass} onChange={(event) => set({ defaultTrafficClassMapping: { ...w.defaultTrafficClassMapping!, qosClass: event.target.value } })} />
        </label>}
        {trafficClassMappings.map((mapping, index) => {
          const mappings = trafficClassMappings;
          const update = (patch: Partial<WorkloadTrafficClassMapping>): void => {
            const next = mappings.slice(); next[index] = { ...mapping, ...patch }; set({ trafficClassMappings: next });
          };
          return <div className="row" key={`${mapping.trafficClass}-${index}`} style={{ gap: 8 }}>
            <label>Traffic class <input aria-label={`mapped traffic class ${index}`} value={mapping.trafficClass} onChange={(event) => update({ trafficClass: event.target.value })} /></label>
            <label>VC class
              <select aria-label={`mapped VC class ${index}`} value={mapping.vcClass} onChange={(event) => update({ vcClass: Number(event.target.value) })}>
                {graphVcClasses.map((vcClass) => <option key={vcClass} value={vcClass}>{vcClass}</option>)}
              </select>
            </label>
            <label>QoS class <input aria-label={`mapped QoS class ${index}`} value={mapping.qosClass} onChange={(event) => update({ qosClass: event.target.value })} /></label>
            <button type="button" className="btn" aria-label={`remove traffic class mapping ${index}`} onClick={() => set({ trafficClassMappings: mappings.filter((_, row) => row !== index) })}>Remove mapping</button>
          </div>;
        })}
        <button type="button" className="btn" disabled={graphVcClasses.length === 0} onClick={() => set({ trafficClassMappings: [...(w.trafficClassMappings ?? []), { trafficClass: '', vcClass: graphVcClasses[0]!, qosClass: '' }] })}>+ Traffic class mapping</button>
      </fieldset>
      <fieldset style={{ marginTop: 12 }}>
        <legend>Communication operations</legend>
        {(w.communications ?? []).map((op, i) => {
          const update = (patch: Partial<WorkloadCommunication>): void => {
            const communications = (w.communications ?? []).slice();
            communications[i] = { ...op, ...patch };
            set({ communications });
          };
          return (
            <div className="row" key={op.id} style={{ gap: 8, padding: '4px 0' }}>
              <code>{op.id}</code>
              <label>Operation
                <select aria-label={`operation kind ${op.id}`} value={op.kind} onChange={(e) => update({ kind: e.target.value as WorkloadCommunication['kind'] })}>
                  {COMMUNICATION_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
                </select>
              </label>
              {op.kind === 'custom' && <label>Custom operation name
                <input aria-label={`custom operation name ${op.id}`} value={op.customName ?? ''} onChange={(e) => update({ customName: e.target.value })} />
              </label>}
              {op.kind === 'point-to-point' && <>
                <label>Source node
                  <select aria-label={`source node ${op.id}`} value={op.sourceNodeId ?? ''} onChange={(e) => update({ sourceNodeId: e.target.value })}>
                    <option value="">Choose source</option>
                    {store.doc.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
                  </select>
                </label>
                <label>Target node
                  <select aria-label={`target node ${op.id}`} value={op.targetNodeId ?? ''} onChange={(e) => update({ targetNodeId: e.target.value })}>
                    <option value="">Choose target</option>
                    {store.doc.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
                  </select>
                </label>
              </>}
              <label>Dimension
                <select aria-label={`operation dimension ${op.id}`} value={op.dimension} onChange={(e) => update({ dimension: e.target.value as WorkloadCommunication['dimension'] })}>
                  {['tp', 'ep', 'pp', 'dp', 'custom'].map((dimension) => <option key={dimension}>{dimension}</option>)}
                </select>
              </label>
              {op.dimension === 'custom' && <label>Dimension name
                <input aria-label={`custom dimension name ${op.id}`} value={op.dimensionName ?? ''} onChange={(e) => update({ dimensionName: e.target.value })} />
              </label>}
              <label>Payload bytes
                <input aria-label={`payload bytes ${op.id}`} type="number" min={1} value={op.payloadBytes} onChange={(e) => update({ payloadBytes: Number(e.target.value) })} />
              </label>
              <label>Traffic class
                <input aria-label={`traffic class ${op.id}`} value={op.trafficClass} onChange={(e) => update({ trafficClass: e.target.value })} />
              </label>
              <button type="button" className="btn" onClick={() => set({ communications: (w.communications ?? []).filter((_, j) => j !== i) })}>Remove</button>
            </div>
          );
        })}
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn" onClick={() => set({ communications: [...(w.communications ?? []), {
            id: nextCommunicationId(w.communications ?? []), kind: 'allreduce', dimension: 'tp', payloadBytes: 1, trafficClass: 'default',
          }] })}>+ Communication operation</button>
          <button type="button" className="btn" onClick={() => {
            const template = moeWorkloadSkeleton(w);
            store.run({ type: 'set_workload', workload: template as unknown as { [key: string]: import('../../graph/project').JsonValue } });
          }}>MoE TP/EP skeleton</button>
        </div>
        <p className="muted">The MoE skeleton is intentionally incomplete: TP and EP custom operation slots carry no assumed collective, dispatch/combine semantics, payload or traffic class. Fill these before treating it as valid. These are authored intent, not a lowering.</p>
      </fieldset>
    </div>
  );
}

/** P6: mock-trace playback keyed on node_id/edge_id. Mock-labelled, never measured. */
export function SimPlayback({ store }: { store: GraphStore }): ReactElement {
  const w = readWorkload(store);
  const phases = w?.phases.map(({ kind, name, startCycle, durationCycles }) => ({ kind, name, startCycle, durationCycles })) ?? [];
  const mockTrace = useMemo(() => buildMockTrace(store.doc, phases), [store.doc, w]);
  const [importedTrace, setImportedTrace] = useState<{ fileName: string; projectSnapshot: string; frames: TraceFrame[]; warnings: TraceWarning[] } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [parseProgress, setParseProgress] = useState(0);
  const [isParsing, setIsParsing] = useState(false);
  const [frame, setFrame] = useState(0);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>('');
  const [metric, setMetric] = useState<'utilization' | 'stalls'>('utilization');
  const [scaleMode, setScaleMode] = useState<'auto' | 'fixed'>('auto');
  const [fixedMax, setFixedMax] = useState(100);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const currentProjectSnapshot = useMemo(() => serializeProject(store.doc), [store.doc]);
  const importedTraceMatchesProject = importedTrace?.projectSnapshot === currentProjectSnapshot;
  const activeImportedTrace = importedTraceMatchesProject ? importedTrace : null;
  const trace = useMemo(() => activeImportedTrace ?? { fileName: null, frames: mockTrace.frames, warnings: [] }, [activeImportedTrace, mockTrace]);
  const f = trace.frames[Math.min(frame, trace.frames.length - 1)];
  const top = topCongested(trace, frame, 5);
  const displayedValues = metric === 'stalls' ? (f?.stalls ?? {}) : (f?.edgeUtil ?? {});
  const autoMax = useMemo(() => {
    let maximum = 1;
    for (const item of trace.frames) {
      const values = metric === 'stalls' ? item.stalls : item.edgeUtil;
      for (const value of Object.values(values)) maximum = Math.max(maximum, value);
    }
    return maximum;
  }, [trace, metric]);
  const maxValue = scaleMode === 'auto' ? autoMax : Math.max(1, fixedMax);

  const importTrace = async (file: File): Promise<void> => {
    setFrame(0); setPlaying(false); setSelectedEdgeId(null); setSelectedNodeId('');
    setImportedTrace(null); setImportError(null); setParseProgress(0); setIsParsing(true);
    const validPrefix: TraceFrame[] = [];
    try {
      if (!file.stream) throw new Error('This browser does not support streaming trace files.');
      const parsed = await parseTraceStream(file.stream(), store.doc, {
        onFrame: frame_ => validPrefix.push(frame_),
        onProgress: progress => { if (progress.recordsIndexed % 100 === 0) setParseProgress(progress.recordsIndexed); },
      });
      setImportedTrace({ fileName: file.name, projectSnapshot: serializeProject(store.doc), frames: parsed.frames, warnings: parsed.warnings });
      setParseProgress(parsed.frames.length);
    } catch (error) {
      if (validPrefix.length) setImportedTrace({ fileName: file.name, projectSnapshot: serializeProject(store.doc), frames: validPrefix, warnings: [] });
      setImportError(error instanceof Error ? error.message : String(error));
      setParseProgress(validPrefix.length);
    } finally {
      setIsParsing(false);
    }
  };

  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => setFrame(current => Math.min(trace.frames.length - 1, current + 1)), 250 / speed);
    return () => clearInterval(timer);
  }, [playing, speed, trace.frames.length]);
  useEffect(() => {
    if (playing && frame >= trace.frames.length - 1) setPlaying(false);
  }, [playing, frame, trace.frames.length]);

  const toggle = (): void => {
    if (playing) setPlaying(false);
    else {
      if (frame >= trace.frames.length - 1) setFrame(0);
      setPlaying(true);
    }
  };
  const step = (): void => {
    setPlaying(false);
    setFrame(current => Math.min(trace.frames.length - 1, current + 1));
  };
  const selectedSeries = useMemo(() => selectedEdgeId ? trace.frames.flatMap(item => {
    const value = metric === 'stalls' ? item.stalls[selectedEdgeId] : item.edgeUtil[selectedEdgeId];
    return value === undefined ? [] : [value];
  }) : [], [trace, metric, selectedEdgeId]);
  const selectedCurrent = selectedEdgeId ? displayedValues[selectedEdgeId] : undefined;
  const selectedStats = useMemo(() => selectedSeries.reduce((stats, value) => ({
    min: Math.min(stats.min, value), max: Math.max(stats.max, value), sum: stats.sum + value, count: stats.count + 1,
  }), { min: Infinity, max: -Infinity, sum: 0, count: 0 }), [selectedSeries]);
  const selectedMin = selectedStats.count ? selectedStats.min : undefined;
  const selectedMax = selectedStats.count ? selectedStats.max : undefined;
  const selectedAvg = selectedStats.count ? selectedStats.sum / selectedStats.count : undefined;
  const selectedNodeSeries = useMemo(() => selectedNodeId ? trace.frames.flatMap(item => {
    const value = item.nodeLoad[selectedNodeId];
    return value === undefined ? [] : [value];
  }) : [], [trace, selectedNodeId]);
  const selectedNodeCurrent = selectedNodeId ? f?.nodeLoad[selectedNodeId] : undefined;
  const selectedNodeStats = useMemo(() => selectedNodeSeries.reduce((stats, value) => ({
    min: Math.min(stats.min, value), max: Math.max(stats.max, value), sum: stats.sum + value, count: stats.count + 1,
  }), { min: Infinity, max: -Infinity, sum: 0, count: 0 }), [selectedNodeSeries]);
  const formatUtilization = (value: number): string => activeImportedTrace ? `${value} (unit unverified)` : `${value}%`;
  const formatMetricValue = (value: number): string => activeImportedTrace
    ? `${value} (unit unverified)` : metric === 'utilization' ? `${value}% (MOCK)` : `${value} stalls (MOCK)`;
  const formatMetricAverage = (value: number): string => activeImportedTrace
    ? `${value.toFixed(2)} (unit unverified)`
    : metric === 'utilization' ? `${value.toFixed(2)}% (MOCK)` : `${value.toFixed(2)} stalls (MOCK)`;

  return (
    <div>
      {importedTrace && !importedTraceMatchesProject && <p className="warn" role="alert">Imported trace is bound to an earlier project snapshot and is not rendered against the changed graph. Re-import it for this project.</p>}
      <p className="muted"><strong>{activeImportedTrace ? 'USER-PROVIDED TRACE' : 'MOCK trace'}</strong> — {activeImportedTrace ? `file ${activeImportedTrace.fileName}; producer/backend provenance is not verified.` : 'playback geometry only.'} Queue latency, router power and buffer figures have no per-cycle artifact behind them and are not shown.</p>
      <label className="loom-field">Import JSONL trace (stable node_id/edge_id required)
        <input aria-label="Import trace JSONL" type="file" accept=".jsonl,.ndjson,.txt" onChange={e => { const file = e.currentTarget.files?.[0]; if (file) void importTrace(file); }} />
      </label>
      {isParsing && <p className="muted" role="status">Indexing trace: {parseProgress} records indexed…</p>}
      {importError && <p className="bad" role="alert">Trace import stopped: {importError}. {parseProgress > 0 ? `${parseProgress} valid frames retained.` : ''}</p>}
      {importedTrace && <button type="button" className="btn" onClick={() => { setFrame(0); setPlaying(false); setSelectedEdgeId(null); setSelectedNodeId(''); setImportedTrace(null); setImportError(null); }}>Use mock playback instead</button>}
      {activeImportedTrace?.warnings.map((warning, i) => <p className="warn" key={`${warning.line}-${i}`}>line {warning.line}: {warning.message}</p>)}
      <div className="row" style={{ gap: 8, margin: '8px 0' }}>
        <button type="button" className="btn" onClick={toggle}>{playing ? 'Pause' : 'Play'}</button>
        <button type="button" className="btn" onClick={step} disabled={frame >= trace.frames.length - 1}>Step</button>
        <label>Speed{' '}
          <select aria-label="playback speed" value={speed} onChange={e => setSpeed(Number(e.target.value))}>
            <option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option>
          </select>
        </label>
        <input aria-label="scrub" type="range" min={0} max={trace.frames.length - 1} value={frame}
          onChange={(e) => setFrame(Number(e.target.value))} style={{ flex: 1 }} />
        <span className="muted">cycle {f?.cycle} · phase <code>{f?.phase}</code> ({frame + 1}/{trace.frames.length})</span>
        <select aria-label="metric" value={metric} onChange={(e) => setMetric(e.target.value as typeof metric)}>
          <option value="utilization">utilization</option>
          <option value="stalls">stalls</option>
        </select>
        <label>Scale{' '}
          <select aria-label="metric scale" value={scaleMode} onChange={e => setScaleMode(e.target.value as typeof scaleMode)}>
            <option value="auto">Auto</option><option value="fixed">Fixed</option>
          </select>
        </label>
        {scaleMode === 'fixed' && <label>Max{' '}
          <input aria-label="fixed metric maximum" type="number" min={1} value={fixedMax} onChange={e => setFixedMax(Math.max(1, Number(e.target.value) || 1))} style={{ width: '4.5rem' }} />
        </label>}
      </div>
      <p className="muted">Metric {metric}; {scaleMode === 'auto' ? 'trace-wide auto' : 'fixed'} scale 0–{maxValue}{activeImportedTrace ? ' (unit unverified)' : metric === 'utilization' ? '% (MOCK)' : ' stalls (MOCK)'}. Missing values are shown as —, not zero.</p>
      <svg width="100%" height={220} style={{ background: 'var(--bg-raise)', border: '1px solid var(--border)', borderRadius: 8 }}>
        {store.doc.edges.slice(0, 16).map((e, i) => {
          const hasValue = Object.prototype.hasOwnProperty.call(displayedValues, e.id);
          const v = hasValue ? displayedValues[e.id] : 0;
          const h = hasValue ? (v / maxValue) * 180 : 0;
          return (
            <g key={e.id} transform={`translate(${50 + i * 60},200)`} role="button" tabIndex={0} aria-label={`Inspect edge ${e.id}`} onClick={() => setSelectedEdgeId(e.id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedEdgeId(e.id); } }}>
              {hasValue ? <rect x={-20} y={-h} width={40} height={h} fill={v > (metric === 'utilization' ? 55 : maxValue * 0.75) ? '#e0655a' : 'var(--accent)'} stroke={selectedEdgeId === e.id ? 'white' : 'none'} strokeWidth={selectedEdgeId === e.id ? 2 : 0} opacity={0.85}>
                <title>{e.id}: {formatMetricValue(v)}</title>
              </rect> : <text textAnchor="middle" y={-8} fontSize={11} fill="var(--muted)">—</text>}
              <text textAnchor="middle" y={14} fontSize={9} fill="var(--muted)" fontFamily="monospace">{e.id.slice(0, 7)}</text>
            </g>
          );
        })}
      </svg>
      {selectedEdgeId && <section aria-label="Edge metric inspector">
        <strong>Edge inspector: <code>{selectedEdgeId}</code></strong>
        <p className="muted">Source: {activeImportedTrace ? 'USER-PROVIDED (producer unverified)' : 'MOCK'} · metric {metric} · {selectedSeries.length} samples</p>
        <p>current {selectedCurrent === undefined ? '—' : formatMetricValue(selectedCurrent)} · min {selectedMin === undefined ? '—' : formatMetricValue(selectedMin)} · max {selectedMax === undefined ? '—' : formatMetricValue(selectedMax)} · avg {selectedAvg === undefined ? '—' : `${formatMetricAverage(selectedAvg)}`}</p>
      </section>}
      <label className="loom-field">Inspect node
        <select aria-label="Inspect node" value={selectedNodeId} onChange={event => setSelectedNodeId(event.target.value)}>
          <option value="">Choose node…</option>{store.doc.nodes.map(node => <option key={node.id} value={node.id}>{node.id}</option>)}
        </select>
      </label>
      {selectedNodeId && <section aria-label="Node metric inspector">
        <strong>Node inspector: <code>{selectedNodeId}</code></strong>
        <p className="muted">Source: {activeImportedTrace ? 'USER-PROVIDED (producer unverified)' : 'MOCK'} · metric nodeLoad · {selectedNodeStats.count} samples</p>
        <p>current {selectedNodeCurrent === undefined ? '—' : selectedNodeCurrent} · min {selectedNodeStats.count ? selectedNodeStats.min : '—'} · max {selectedNodeStats.count ? selectedNodeStats.max : '—'} · avg {selectedNodeStats.count ? (selectedNodeStats.sum / selectedNodeStats.count).toFixed(2) : '—'} (trace-declared unit not available)</p>
      </section>}
      {store.doc.edges.length > 16 && <p className="muted">bars capped at 16 edges; the list below ranks all {store.doc.edges.length}.</p>}
      <p><strong>Top congested</strong></p>
      <div>
        {top.map((t) => (
          <button type="button" className="row" key={t.edge} aria-label={`Inspect congested edge ${t.edge}`} onClick={() => setSelectedEdgeId(t.edge)} style={{ gap: 12 }}>
            <code>{t.edge}</code><span>util {formatUtilization(t.util)}</span><span>stalls {f?.stalls[t.edge] ?? '—'}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** P4: abstract tile projection. No die, PDK, STA or power model behind it. */
export function FloorplanPreview({ store }: { store: GraphStore }): ReactElement {
  const [heat, setHeat] = useState(true);
  const [dieDraft, setDieDraft] = useState({ originX: '', originY: '', width: '', height: '' });
  const [floorplanMessage, setFloorplanMessage] = useState<string | null>(null);
  const [placementDraft, setPlacementDraft] = useState({ nodeId: '', x: '', y: '', width: '', height: '' });
  const [keepoutDraft, setKeepoutDraft] = useState({ id: '', x: '', y: '', width: '', height: '' });
  const [gridStepDraft, setGridStepDraft] = useState('0.1');
  const [anchorXDraft, setAnchorXDraft] = useState('');
  const [anchorYDraft, setAnchorYDraft] = useState('');
  const [groupAnchorXDraft, setGroupAnchorXDraft] = useState('');
  const [groupAnchorYDraft, setGroupAnchorYDraft] = useState('');
  const [groupSelection, setGroupSelection] = useState<Set<string>>(new Set());
  const [selectedPhysicalNode, setSelectedPhysicalNode] = useState<string | null>(null);
  const [showPhysicalRoutes, setShowPhysicalRoutes] = useState(false);
  const [wireDelayDraft, setWireDelayDraft] = useState('');
  const [fixedDelayDraft, setFixedDelayDraft] = useState('');
  const [timingDrafts, setTimingDrafts] = useState<Record<string, string>>({});
  const [waypointDrafts, setWaypointDrafts] = useState<Record<string, { x: string; y: string }>>({});
  const [placementDrag, setPlacementDrag] = useState<{ nodeId: string; mode: 'move' | 'resize'; startX: number; startY: number; original: import('../../graph/project').PhysicalPlacement } | null>(null);
  const [dragPlacement, setDragPlacement] = useState<import('../../graph/project').PhysicalPlacement | null>(null);
  const physicalViewRef = useRef<SVGSVGElement>(null);
  const ref = useRef<SVGSVGElement>(null);
  const floorplan = store.doc.floorplan;
  const physicalPlacements = floorplan?.placements ?? [];
  const physicalKeepouts = floorplan?.keepouts ?? [];
  const routePlacements = physicalPlacements.map((placement) => dragPlacement?.nodeId === placement.nodeId ? dragPlacement : placement);
  const physicalRoutes = routeAllManhattanPhysicalEdges(store.doc.edges, routePlacements, floorplan?.die ? { die: floorplan.die, keepouts: floorplan.keepouts } : undefined);
  const selectedPhysicalPlacement = physicalPlacements.find((placement) => placement.nodeId === selectedPhysicalNode);
  const selectedPhysicalLocked = selectedPhysicalPlacement?.locked === true;
  const unplacedNodes = store.doc.nodes.filter((node) => !physicalPlacements.some((placement) => placement.nodeId === node.id));
  const numericPlacement = { x: Number(placementDraft.x), y: Number(placementDraft.y), width: Number(placementDraft.width), height: Number(placementDraft.height) };
  const draftNodeId = placementDraft.nodeId || unplacedNodes[0]?.id || '';
  const editingPlacement = Boolean(selectedPhysicalNode && selectedPhysicalNode === draftNodeId && physicalPlacements.some((placement) => placement.nodeId === selectedPhysicalNode));
  const gridStep = Number.isFinite(Number(gridStepDraft)) && Number(gridStepDraft) > 0 ? Number(gridStepDraft) : 0.1;
  const snapPhysical = (value: number): number => Number((Math.round(value / gridStep) * gridStep).toPrecision(12));
  const placementDraftValid = Boolean(floorplan?.die && (editingPlacement || unplacedNodes.some((node) => node.id === draftNodeId)))
    && Object.values(numericPlacement).every(Number.isFinite) && numericPlacement.width > 0 && numericPlacement.height > 0;
  useEffect(() => {
    setGridStepDraft(String(floorplan?.gridStep ?? 0.1));
    setWireDelayDraft(floorplan?.delayModel ? String(floorplan.delayModel.wireDelayPsPerUnit) : '');
    setFixedDelayDraft(floorplan?.delayModel ? String(floorplan.delayModel.fixedDelayPs) : '');
    setTimingDrafts(Object.fromEntries((floorplan?.timingConstraints ?? []).map((constraint) => [constraint.edgeId, String(constraint.targetDelayPs)])));
    if (selectedPhysicalPlacement) {
      setAnchorXDraft(String(selectedPhysicalPlacement.x));
      setAnchorYDraft(String(selectedPhysicalPlacement.y));
    }
    const die = floorplan?.die;
    setDieDraft(die ? {
      originX: String(die.originX), originY: String(die.originY), width: String(die.width), height: String(die.height),
    } : { originX: '', originY: '', width: '', height: '' });
  }, [floorplan]);
  const numericDie = {
    originX: Number(dieDraft.originX), originY: Number(dieDraft.originY),
    width: Number(dieDraft.width), height: Number(dieDraft.height),
  };
  const dieDraftValid = Boolean(floorplan?.unit) && Object.values(numericDie).every(Number.isFinite)
    && numericDie.width > 0 && numericDie.height > 0;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of store.doc.nodes) {
    minX = Math.min(minX, n.x);
    minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x);
    maxY = Math.max(maxY, n.y);
  }
  const sx = (x: number): number => 30 + ((x - minX) / Math.max(1, maxX - minX)) * 520;
  const sy = (y: number): number => 30 + ((y - minY) / Math.max(1, maxY - minY)) * 320;
  const byId = new Map(store.doc.nodes.map((n) => [n.id, n]));
  return (
    <div>
      <fieldset aria-label="Physical floorplan coordinate intent">
        <legend>Physical coordinate system and die outline</legend>
        <p className="muted">Authored die bounds only. Graph canvas x/y is not physical placement; no node-to-die mapping, delay, PDK, or signoff is inferred.</p>
        <label>Die coordinate unit
          <select aria-label="die coordinate unit" value={floorplan?.unit ?? ''} onChange={(event) => {
            const selected = event.target.value as PhysicalUnit | '';
            if (!selected) { store.run({ type: 'set_floorplan', floorplan: undefined }); return; }
            if (floorplan && selected !== floorplan.unit && store.doc.edges.some((edge) => (edge.physical?.waypoints?.length ?? 0) > 0)) {
              setFloorplanMessage('Reset all manual edge waypoints before converting physical units; waypoint coordinates cannot be converted independently of their edge routes.');
              return;
            }
            const nextFloorplan = floorplan ? convertFloorplanIntent(floorplan, selected) : { unit: selected };
            const refused = store.run({ type: 'set_floorplan', floorplan: nextFloorplan });
            setFloorplanMessage(refused);
          }}>
            <option value="">Choose physical unit</option><option value="um">µm</option><option value="mm">mm</option>
          </select>
        </label>
        <div className="row" style={{ gap: 8 }}>
          <label>Origin X <input aria-label="die origin x" type="number" step="any" value={dieDraft.originX} disabled={!floorplan} onChange={(event) => setDieDraft((draft) => ({ ...draft, originX: event.target.value }))} /></label>
          <label>Origin Y <input aria-label="die origin y" type="number" step="any" value={dieDraft.originY} disabled={!floorplan} onChange={(event) => setDieDraft((draft) => ({ ...draft, originY: event.target.value }))} /></label>
          <label>Width <input aria-label="die width" type="number" step="any" min="0" value={dieDraft.width} disabled={!floorplan} onChange={(event) => setDieDraft((draft) => ({ ...draft, width: event.target.value }))} /></label>
          <label>Height <input aria-label="die height" type="number" step="any" min="0" value={dieDraft.height} disabled={!floorplan} onChange={(event) => setDieDraft((draft) => ({ ...draft, height: event.target.value }))} /></label>
          <button type="button" className="btn" disabled={!dieDraftValid} onClick={() => {
            if (!floorplan) return;
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, die: numericDie } });
            setFloorplanMessage(refused ?? `Die outline saved in ${floorplan.unit}.`);
          }}>Apply die outline</button>
          {floorplan?.die && <button type="button" className="btn" disabled={physicalPlacements.length > 0} onClick={() => {
            const refused = store.run({ type: 'set_floorplan', floorplan: { unit: floorplan.unit } });
            setFloorplanMessage(refused ?? 'Die outline cleared.');
          }}>Clear die outline</button>}
        </div>
        {floorplan?.die && <p role="status">Die outline: origin ({floorplan.die.originX}, {floorplan.die.originY}), {floorplan.die.width} × {floorplan.die.height} {floorplan.unit}</p>}
        {floorplanMessage && <p role="status">{floorplanMessage}</p>}
      </fieldset>
      <fieldset aria-label="Physical keepout regions">
        <legend>Physical keepouts (authored intent)</legend>
        <p className="muted">Keepouts are saved in project physical units and reject placements that intersect them. This is not a physical-tool blockage result.</p>
        <div className="row" style={{ gap: 8 }}>
          <label>Keepout ID <input aria-label="keepout id" value={keepoutDraft.id} onChange={(event) => setKeepoutDraft({ ...keepoutDraft, id: event.target.value })} /></label>
          <label>X <input aria-label="keepout x" type="number" step="any" value={keepoutDraft.x} onChange={(event) => setKeepoutDraft({ ...keepoutDraft, x: event.target.value })} /></label>
          <label>Y <input aria-label="keepout y" type="number" step="any" value={keepoutDraft.y} onChange={(event) => setKeepoutDraft({ ...keepoutDraft, y: event.target.value })} /></label>
          <label>Width <input aria-label="keepout width" type="number" min="0" step="any" value={keepoutDraft.width} onChange={(event) => setKeepoutDraft({ ...keepoutDraft, width: event.target.value })} /></label>
          <label>Height <input aria-label="keepout height" type="number" min="0" step="any" value={keepoutDraft.height} onChange={(event) => setKeepoutDraft({ ...keepoutDraft, height: event.target.value })} /></label>
          <button type="button" className="btn" disabled={!floorplan?.die || !keepoutDraft.id.trim() || physicalKeepouts.some((item) => item.id === keepoutDraft.id.trim()) || ![keepoutDraft.x, keepoutDraft.y, keepoutDraft.width, keepoutDraft.height].every((value) => Number.isFinite(Number(value))) || Number(keepoutDraft.width) <= 0 || Number(keepoutDraft.height) <= 0}
            onClick={() => {
              if (!floorplan) return;
              const keepout = { id: keepoutDraft.id.trim(), x: Number(keepoutDraft.x), y: Number(keepoutDraft.y), width: Number(keepoutDraft.width), height: Number(keepoutDraft.height) };
              const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, keepouts: [...physicalKeepouts, keepout] } });
              setFloorplanMessage(refused ?? `Saved keepout ${keepout.id}.`);
            }}>Add keepout</button>
        </div>
        <ul>{physicalKeepouts.map((keepout) => <li key={keepout.id}><code>{keepout.id}</code> ({keepout.x}, {keepout.y}) {keepout.width} × {keepout.height} {floorplan?.unit}
          <button type="button" className="btn btn-small" aria-label={`remove keepout ${keepout.id}`} onClick={() => floorplan && setFloorplanMessage(store.run({ type: 'set_floorplan', floorplan: { ...floorplan, keepouts: physicalKeepouts.filter((item) => item.id !== keepout.id) } }) ?? `Removed keepout ${keepout.id}.`)}>Remove</button>
        </li>)}</ul>
      </fieldset>
      <fieldset aria-label="Physical node placements">
        <legend>Physical node rectangles</legend>
        <p className="muted">Rectangles use explicit die-unit coordinates stored per graph node ID. They are independent of canvas x/y; selection here does not cross-probe a certified topology.</p>
        <div className="row" style={{ gap: 8 }}>
          <label>Node <select aria-label="physical placement node" value={draftNodeId} onChange={(event) => { setSelectedPhysicalNode(null); setPlacementDraft((draft) => ({ ...draft, nodeId: event.target.value })); }}>
            {editingPlacement && <option value={selectedPhysicalNode!}>{selectedPhysicalNode} · placed</option>}
            {unplacedNodes.map((node) => <option key={node.id} value={node.id}>{node.id} · unplaced · {node.role}</option>)}
          </select></label>
          <label>Physical X <input aria-label="placement x" type="number" step="any" value={placementDraft.x} onChange={(event) => setPlacementDraft((draft) => ({ ...draft, x: event.target.value }))} /></label>
          <label>Physical Y <input aria-label="placement y" type="number" step="any" value={placementDraft.y} onChange={(event) => setPlacementDraft((draft) => ({ ...draft, y: event.target.value }))} /></label>
          <label>Physical width <input aria-label="placement width" type="number" min="0" step="any" value={placementDraft.width} onChange={(event) => setPlacementDraft((draft) => ({ ...draft, width: event.target.value }))} /></label>
          <label>Physical height <input aria-label="placement height" type="number" min="0" step="any" value={placementDraft.height} onChange={(event) => setPlacementDraft((draft) => ({ ...draft, height: event.target.value }))} /></label>
          <label>Physical grid step <input aria-label="physical grid step" type="number" min="0.000001" step="any" disabled={!floorplan} value={gridStepDraft} onChange={(event) => setGridStepDraft(event.target.value)} onBlur={() => {
            const step = Number(gridStepDraft);
            if (!floorplan || !Number.isFinite(step) || step <= 0) { setFloorplanMessage('Physical grid step must be finite and positive.'); setGridStepDraft(String(floorplan?.gridStep ?? 0.1)); return; }
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, gridStep: step } });
            setFloorplanMessage(refused ?? `Physical grid step saved as ${step} ${floorplan.unit}.`);
          }} /></label>
          <button type="button" className="btn" disabled={!placementDraftValid || (editingPlacement && selectedPhysicalLocked)} onClick={() => {
            if (!floorplan || !placementDraftValid || !draftNodeId) return;
            const snapped = Object.fromEntries(Object.entries(numericPlacement).map(([key, value]) => [key, snapPhysical(value)])) as typeof numericPlacement;
            const row = { nodeId: draftNodeId, ...snapped };
            const nextPlacements = editingPlacement
              ? physicalPlacements.map((placement) => placement.nodeId === draftNodeId ? row : placement)
              : [...physicalPlacements, row];
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements: nextPlacements } });
            setFloorplanMessage(refused ?? `${editingPlacement ? 'Updated' : 'Placed'} physical rectangle for ${draftNodeId}.`);
            if (!refused) {
              setSelectedPhysicalNode(draftNodeId);
              setAnchorXDraft(String(snapped.x)); setAnchorYDraft(String(snapped.y));
              setPlacementDraft({ nodeId: draftNodeId, x: String(snapped.x), y: String(snapped.y), width: String(snapped.width), height: String(snapped.height) });
            }
          }}>{editingPlacement ? 'Update physical rectangle' : 'Place physical rectangle'}</button>
        </div>
        {!floorplan?.die && <p className="muted">Set an explicit die outline before placing physical rectangles.</p>}
        <div role="group" aria-label="Unplaced node bin">
          <strong>Unplaced nodes</strong>
          <p className="muted">Set physical rectangle width/height above, then drag a node into the die outline.</p>
          {unplacedNodes.map((node) => <button type="button" className="btn btn-small" key={node.id} draggable aria-label={`drag unplaced node ${node.id}`}
            onDragStart={(event) => { event.dataTransfer.setData('text/plain', node.id); event.dataTransfer.effectAllowed = 'move'; }}>
            ⠿ {node.id} · {node.role}
          </button>)}
          {unplacedNodes.length === 0 && <span className="muted">All graph nodes have explicit physical rectangles.</span>}
        </div>
        <fieldset aria-label="Physical group placement operations">
          <legend>Group alignment</legend>
          {physicalPlacements.map((placement) => <label key={placement.nodeId}>
            <input type="checkbox" aria-label={`select physical placement ${placement.nodeId}`} disabled={placement.locked === true}
              checked={groupSelection.has(placement.nodeId)} onChange={(event) => setGroupSelection((selected) => {
                const next = new Set(selected);
                if (event.target.checked) next.add(placement.nodeId); else next.delete(placement.nodeId);
                return next;
              })} /> {placement.nodeId}{placement.locked ? ' · locked' : ''}
          </label>)}
          <label>Group anchor X <input aria-label="group anchor x" type="number" step={gridStep} value={groupAnchorXDraft} onChange={(event) => setGroupAnchorXDraft(event.target.value)} /></label>
          <button type="button" className="btn btn-small" aria-label="align selected placements to group anchor x"
            disabled={!floorplan || !groupAnchorXDraft.trim() || !Number.isFinite(Number(groupAnchorXDraft)) || !physicalPlacements.some((placement) => groupSelection.has(placement.nodeId) && !placement.locked)}
            onClick={() => {
              if (!floorplan) return;
              const x = snapPhysical(Number(groupAnchorXDraft));
              const placements = physicalPlacements.map((placement) => groupSelection.has(placement.nodeId) && !placement.locked ? { ...placement, x } : placement);
              const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements } });
              setFloorplanMessage(refused ?? `Aligned selected unlocked placements to X=${x} ${floorplan.unit}.`);
              if (!refused) setGroupAnchorXDraft(String(x));
            }}>Align selected X</button>
          <label>Group anchor Y <input aria-label="group anchor y" type="number" step={gridStep} value={groupAnchorYDraft} onChange={(event) => setGroupAnchorYDraft(event.target.value)} /></label>
          <button type="button" className="btn btn-small" aria-label="align selected placements to group anchor y"
            disabled={!floorplan || !groupAnchorYDraft.trim() || !Number.isFinite(Number(groupAnchorYDraft)) || !physicalPlacements.some((placement) => groupSelection.has(placement.nodeId) && !placement.locked)}
            onClick={() => {
              if (!floorplan) return;
              const y = snapPhysical(Number(groupAnchorYDraft));
              const placements = physicalPlacements.map((placement) => groupSelection.has(placement.nodeId) && !placement.locked ? { ...placement, y } : placement);
              const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements } });
              setFloorplanMessage(refused ?? `Aligned selected unlocked placements to Y=${y} ${floorplan.unit}.`);
              if (!refused) setGroupAnchorYDraft(String(y));
            }}>Align selected Y</button>
        </fieldset>
        {selectedPhysicalNode && <div className="row" role="status">
          <span>Selected physical node: {selectedPhysicalNode} (local authored graph ID; no certified-topology cross-probe).</span>
          <label>Anchor X <input aria-label="physical anchor x" type="number" step={gridStep} value={anchorXDraft} disabled={selectedPhysicalLocked} onChange={(event) => setAnchorXDraft(event.target.value)} /></label>
          <button type="button" className="btn btn-small" aria-label={`align ${selectedPhysicalNode} to anchor x`} disabled={selectedPhysicalLocked || !anchorXDraft.trim() || !Number.isFinite(Number(anchorXDraft)) || !floorplan} onClick={() => {
            if (!floorplan || !selectedPhysicalPlacement) return;
            const x = snapPhysical(Number(anchorXDraft));
            const placements = physicalPlacements.map((placement) => placement.nodeId === selectedPhysicalNode ? { ...placement, x } : placement);
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements } });
            setFloorplanMessage(refused ?? `Aligned ${selectedPhysicalNode} to X=${x} ${floorplan.unit}.`);
            if (!refused) { setAnchorXDraft(String(x)); setPlacementDraft((draft) => ({ ...draft, x: String(x) })); }
          }}>Align X</button>
          <label>Anchor Y <input aria-label="physical anchor y" type="number" step={gridStep} value={anchorYDraft} disabled={selectedPhysicalLocked} onChange={(event) => setAnchorYDraft(event.target.value)} /></label>
          <button type="button" className="btn btn-small" aria-label={`align ${selectedPhysicalNode} to anchor y`} disabled={selectedPhysicalLocked || !anchorYDraft.trim() || !Number.isFinite(Number(anchorYDraft)) || !floorplan} onClick={() => {
            if (!floorplan || !selectedPhysicalPlacement) return;
            const y = snapPhysical(Number(anchorYDraft));
            const placements = physicalPlacements.map((placement) => placement.nodeId === selectedPhysicalNode ? { ...placement, y } : placement);
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements } });
            setFloorplanMessage(refused ?? `Aligned ${selectedPhysicalNode} to Y=${y} ${floorplan.unit}.`);
            if (!refused) { setAnchorYDraft(String(y)); setPlacementDraft((draft) => ({ ...draft, y: String(y) })); }
          }}>Align Y</button>
          <button type="button" className="btn btn-small" aria-label={`${selectedPhysicalLocked ? 'unlock' : 'lock'} physical placement ${selectedPhysicalNode}`} onClick={() => {
            if (!floorplan || !selectedPhysicalPlacement) return;
            const placements = physicalPlacements.map((placement) => {
              if (placement.nodeId !== selectedPhysicalNode) return placement;
              if (!selectedPhysicalLocked) return { ...placement, locked: true };
              const unlocked = { ...placement };
              delete unlocked.locked;
              return unlocked;
            });
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements } });
            setFloorplanMessage(refused ?? `${selectedPhysicalLocked ? 'Unlocked' : 'Locked'} ${selectedPhysicalNode}.`);
          }}>{selectedPhysicalLocked ? 'Unlock placement' : 'Lock placement'}</button>
          <button type="button" className="btn btn-small" aria-label={`remove physical placement ${selectedPhysicalNode}`} disabled={selectedPhysicalLocked} onClick={() => {
            if (!floorplan) return;
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements: physicalPlacements.filter((placement) => placement.nodeId !== selectedPhysicalNode) } });
            setFloorplanMessage(refused ?? `Removed physical rectangle for ${selectedPhysicalNode}.`);
            if (!refused) setSelectedPhysicalNode(null);
          }}>Remove placement</button>
        </div>}
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn" aria-label="route all Manhattan physical links" disabled={!floorplan?.die}
            onClick={() => setShowPhysicalRoutes((visible) => !visible)}>{showPhysicalRoutes ? 'Hide' : 'Preview'} all Manhattan physical links</button>
          <span role="status">{physicalRoutes.filter((route) => route.status === 'routed').length}/{physicalRoutes.length} edges routed; {physicalRoutes.filter((route) => route.status === 'unresolved').length} unresolved · preview only; no obstacle avoidance, PDK or signoff</span>
        </div>
        <details>
          <summary>Manual physical edge waypoints (authored intent)</summary>
          <p className="muted">Waypoints replace each edge's automatic Manhattan preview. Segments use deterministic X-then-Y bends. Reset removes the override; this is not obstacle-avoiding physical routing.</p>
          {store.doc.edges.map((edge) => {
            const draft = waypointDrafts[edge.id] ?? { x: '', y: '' };
            const waypoints = edge.physical?.waypoints ?? [];
            return <div className="row" key={edge.id} aria-label={`Manual waypoints for ${edge.id}`}>
              <code>{edge.id}</code><span>{waypoints.length ? `${waypoints.length} authored waypoint(s)` : 'automatic route'}</span>
              {waypoints.map((waypoint, index) => (
                <span className="row" key={`${edge.id}-wp${index}`} style={{ gap: 4, alignItems: 'center' }}>
                  <label>wp{index} X
                    <input aria-label={`waypoint ${index} x ${edge.id}`} type="number" step="any" defaultValue={waypoint.x}
                      key={`${edge.id}-wp${index}-x-${waypoint.x}`}
                      onBlur={(event) => {
                        const value = Number(event.target.value);
                        if (!Number.isFinite(value) || value === waypoint.x) return;
                        const next = waypoints.map((w, i) => (i === index ? { ...w, x: value } : w));
                        store.run({ type: 'update_edge', id: edge.id, patch: { physical: { ...edge.physical, waypoints: next } } });
                      }} />
                  </label>
                  <label>wp{index} Y
                    <input aria-label={`waypoint ${index} y ${edge.id}`} type="number" step="any" defaultValue={waypoint.y}
                      key={`${edge.id}-wp${index}-y-${waypoint.y}`}
                      onBlur={(event) => {
                        const value = Number(event.target.value);
                        if (!Number.isFinite(value) || value === waypoint.y) return;
                        const next = waypoints.map((w, i) => (i === index ? { ...w, y: value } : w));
                        store.run({ type: 'update_edge', id: edge.id, patch: { physical: { ...edge.physical, waypoints: next } } });
                      }} />
                  </label>
                  <button type="button" className="btn btn-small" aria-label={`remove waypoint ${index} ${edge.id}`}
                    onClick={() => {
                      const next = waypoints.filter((_, i) => i !== index);
                      const patch = next.length > 0 ? { ...edge.physical, waypoints: next } : undefined;
                      store.run({ type: 'update_edge', id: edge.id, patch: { physical: patch } });
                    }}>remove</button>
                </span>
              ))}
              <label>Waypoint X <input aria-label={`waypoint x ${edge.id}`} type="number" step="any" value={draft.x} onChange={(event) => setWaypointDrafts((previous) => ({ ...previous, [edge.id]: { ...draft, x: event.target.value } }))} /></label>
              <label>Waypoint Y <input aria-label={`waypoint y ${edge.id}`} type="number" step="any" value={draft.y} onChange={(event) => setWaypointDrafts((previous) => ({ ...previous, [edge.id]: { ...draft, y: event.target.value } }))} /></label>
              <button type="button" className="btn btn-small" aria-label={`add waypoint ${edge.id}`} disabled={!draft.x.trim() || !draft.y.trim() || !Number.isFinite(Number(draft.x)) || !Number.isFinite(Number(draft.y))}
                onClick={() => {
                  const nextWaypoints = [...waypoints, { x: Number(draft.x), y: Number(draft.y) }];
                  const refused = store.run({ type: 'update_edge', id: edge.id, patch: { physical: { ...edge.physical, waypoints: nextWaypoints } } });
                  setFloorplanMessage(refused ?? `Added manual waypoint to ${edge.id}.`);
                  if (!refused) setWaypointDrafts((previous) => ({ ...previous, [edge.id]: { x: '', y: '' } }));
                }}>Add waypoint</button>
              {waypoints.length > 0 && <button type="button" className="btn btn-small" aria-label={`reset route ${edge.id} to automatic`} onClick={() => {
                const physical = { ...edge.physical }; delete physical.waypoints;
                const patch = Object.values(physical).every((value) => value === undefined) ? undefined : physical;
                const refused = store.run({ type: 'update_edge', id: edge.id, patch: { physical: patch } });
                setFloorplanMessage(refused ?? `Reset ${edge.id} to automatic Manhattan preview.`);
              }}>Reset to automatic</button>}
            </div>;
          })}
        </details>
        <fieldset aria-label="Physical delay estimate inputs">
          <legend>Estimated wire delay model</legend>
          <p className="muted">Explicit linear estimate: Manhattan preview length × wire delay per physical unit + fixed endpoint delay. Inputs are user-authored; no PDK/engine values are assumed.</p>
          <label>Wire delay (ps per {floorplan?.unit ?? 'unit'}) <input aria-label="wire delay per physical unit" type="number" min="0" step="any" value={wireDelayDraft} onChange={(event) => setWireDelayDraft(event.target.value)} /></label>
          <label>Fixed endpoint delay (ps) <input aria-label="fixed endpoint delay" type="number" min="0" step="any" value={fixedDelayDraft} onChange={(event) => setFixedDelayDraft(event.target.value)} /></label>
          <button type="button" className="btn btn-small" aria-label="apply physical delay estimate inputs"
            disabled={!floorplan || !wireDelayDraft.trim() || !fixedDelayDraft.trim() || !Number.isFinite(Number(wireDelayDraft)) || !Number.isFinite(Number(fixedDelayDraft)) || Number(wireDelayDraft) < 0 || Number(fixedDelayDraft) < 0}
            onClick={() => {
              if (!floorplan) return;
              const delayModel = { wireDelayPsPerUnit: Number(wireDelayDraft), fixedDelayPs: Number(fixedDelayDraft) };
              const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, delayModel } });
              setFloorplanMessage(refused ?? 'Saved explicit estimated-delay formula inputs; no engine timing result is implied.');
            }}>Apply estimate inputs</button>
          <p role="status">{floorplan?.delayModel ? `Estimated delay is derived from the authored formula in ps (${floorplan.delayModel.wireDelayPsPerUnit} ps/${floorplan.unit} + ${floorplan.delayModel.fixedDelayPs} ps fixed).` : 'Estimated delay unavailable until both formula inputs are explicitly authored.'}</p>
        </fieldset>
        <details aria-label="Physical Manhattan route details">
          <summary>Manhattan route lengths and unresolved edges</summary>
          <ul>{physicalRoutes.map((route) => {
            const delay = floorplan?.delayModel ? estimateManhattanRouteDelayPs(route, floorplan.delayModel) : null;
            const constraint = floorplan?.timingConstraints?.find((item) => item.edgeId === route.edgeId);
            const draft = timingDrafts[route.edgeId] ?? '';
            return <li key={route.edgeId}>
              {route.edgeId}: {route.status === 'routed' ? `${route.length} ${floorplan?.unit ?? ''} (estimated)${delay !== null ? ` · Estimated delay ${delay} ps` : ''} · ${route.points?.map((point) => `(${point.x}, ${point.y})`).join(' → ')}` : route.error}
              <label>Target delay (ps) <input aria-label={`target delay ${route.edgeId}`} type="number" min="0" step="any" value={draft} onChange={(event) => setTimingDrafts((current) => ({ ...current, [route.edgeId]: event.target.value }))} /></label>
              <button type="button" className="btn btn-small" aria-label={`apply target delay ${route.edgeId}`} disabled={!floorplan || !draft.trim() || !Number.isFinite(Number(draft)) || Number(draft) < 0}
                onClick={() => {
                  if (!floorplan) return;
                  const timingConstraints = [...(floorplan.timingConstraints ?? []).filter((item) => item.edgeId !== route.edgeId), { edgeId: route.edgeId, targetDelayPs: Number(draft) }];
                  const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, timingConstraints } });
                  setFloorplanMessage(refused ?? `Saved ${route.edgeId} target delay ${Number(draft)} ps.`);
                }}>Apply target</button>
              <span>{!constraint ? ' · no target' : delay === null ? ' · Not evaluated (route/model unavailable)' : ` · Estimated ${delay <= constraint.targetDelayPs ? 'PASS' : 'FAIL'} against ${constraint.targetDelayPs} ps target`}</span>
            </li>;
          })}</ul>
        </details>
        <svg ref={physicalViewRef} aria-label="Physical placement view" viewBox="0 0 600 360" width="100%" height={360}
          onPointerMove={(event) => {
            if (!placementDrag || !floorplan?.die) return;
            const rect = physicalViewRef.current?.getBoundingClientRect();
            const svgDx = (event.clientX - placementDrag.startX) * (600 / (rect?.width || 600));
            const svgDy = (event.clientY - placementDrag.startY) * (360 / (rect?.height || 360));
            const dx = svgDx / 540 * floorplan.die.width;
            const dy = svgDy / 300 * floorplan.die.height;
            setDragPlacement(placementDrag.mode === 'move'
              ? { ...placementDrag.original, x: snapPhysical(placementDrag.original.x + dx), y: snapPhysical(placementDrag.original.y + dy) }
              : { ...placementDrag.original, width: Math.max(gridStep, snapPhysical(placementDrag.original.width + dx)), height: Math.max(gridStep, snapPhysical(placementDrag.original.height + dy)) });
          }}
          onPointerUp={() => {
            if (placementDrag && dragPlacement && floorplan) {
              const placements = physicalPlacements.map((placement) => placement.nodeId === placementDrag.nodeId ? dragPlacement : placement);
              const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements } });
              setFloorplanMessage(refused ?? `${placementDrag.mode === 'move' ? 'Moved' : 'Resized'} ${placementDrag.nodeId} on the ${gridStep} ${floorplan.unit} grid.`);
            }
            setPlacementDrag(null); setDragPlacement(null);
          }}
          onPointerCancel={() => { setPlacementDrag(null); setDragPlacement(null); }}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            const nodeId = event.dataTransfer.getData('text/plain');
            const node = unplacedNodes.find((candidate) => candidate.id === nodeId);
            if (!node || !floorplan?.die) { setFloorplanMessage('Drop a listed unplaced node inside an authored die outline.'); return; }
            const rect = physicalViewRef.current?.getBoundingClientRect();
            const svgX = (event.clientX - (rect?.left ?? 0)) * (600 / (rect?.width || 600));
            const svgY = (event.clientY - (rect?.top ?? 0)) * (360 / (rect?.height || 360));
            if (svgX < 30 || svgX > 570 || svgY < 20 || svgY > 320) { setFloorplanMessage('Drop the node inside the die outline.'); return; }
            const width = snapPhysical(Number(placementDraft.width));
            const height = snapPhysical(Number(placementDraft.height));
            if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) { setFloorplanMessage('Set positive physical width and height before dropping a node.'); return; }
            const placement = {
              nodeId,
              x: snapPhysical(floorplan.die.originX + ((svgX - 30) / 540) * floorplan.die.width),
              y: snapPhysical(floorplan.die.originY + ((svgY - 20) / 300) * floorplan.die.height),
              width, height,
            };
            const refused = store.run({ type: 'set_floorplan', floorplan: { ...floorplan, placements: [...physicalPlacements, placement] } });
            setFloorplanMessage(refused ?? `Placed ${nodeId} at explicit physical drop coordinates.`);
            if (!refused) {
              setSelectedPhysicalNode(nodeId); setAnchorXDraft(String(placement.x)); setAnchorYDraft(String(placement.y));
              setPlacementDraft({ nodeId, x: String(placement.x), y: String(placement.y), width: String(placement.width), height: String(placement.height) });
            }
          }}
          style={{ background: 'var(--bg-raise)', border: '1px solid var(--border)', borderRadius: 8, touchAction: 'none' }}>
          {floorplan?.die && <>
            <rect x={30} y={20} width={540} height={300} fill="none" stroke="var(--muted)" strokeWidth={2} />
            {physicalKeepouts.map((keepout) => <rect key={`keepout-${keepout.id}`} aria-label={`Physical keepout ${keepout.id}`} x={30 + ((keepout.x - floorplan.die!.originX) / floorplan.die!.width) * 540} y={20 + ((keepout.y - floorplan.die!.originY) / floorplan.die!.height) * 300} width={(keepout.width / floorplan.die!.width) * 540} height={(keepout.height / floorplan.die!.height) * 300} fill="rgba(220, 70, 70, .12)" stroke="var(--danger, #c44)" strokeDasharray="4 2" />)}
            {showPhysicalRoutes && physicalRoutes.filter((route) => route.status === 'routed').map((route) => <polyline key={`physical-route-${route.edgeId}`} data-testid={`physical-route-${route.edgeId}`} aria-label={`Manhattan preview route ${route.edgeId}`}
              points={(route.points ?? []).map((point) => `${30 + ((point.x - floorplan.die!.originX) / floorplan.die!.width) * 540},${20 + ((point.y - floorplan.die!.originY) / floorplan.die!.height) * 300}`).join(' ')}
              fill="none" stroke="var(--warn, #d9a441)" strokeWidth={1.5} strokeDasharray="5 3" />)}
            {physicalPlacements.map((authoredPlacement) => {
              const placement = dragPlacement?.nodeId === authoredPlacement.nodeId ? dragPlacement : authoredPlacement;
              const x = 30 + ((placement.x - floorplan.die!.originX) / floorplan.die!.width) * 540;
              const y = 20 + ((placement.y - floorplan.die!.originY) / floorplan.die!.height) * 300;
              const width = (placement.width / floorplan.die!.width) * 540;
              const height = (placement.height / floorplan.die!.height) * 300;
              const beginDrag = (event: ReactPointerEvent<SVGElement>, mode: 'move' | 'resize'): void => {
                event.preventDefault(); event.stopPropagation();
                if (authoredPlacement.locked) return;
                if (typeof event.currentTarget.setPointerCapture === 'function') event.currentTarget.setPointerCapture(event.pointerId);
                setSelectedPhysicalNode(placement.nodeId);
                setAnchorXDraft(String(placement.x)); setAnchorYDraft(String(placement.y));
                setPlacementDraft({ nodeId: placement.nodeId, x: String(placement.x), y: String(placement.y), width: String(placement.width), height: String(placement.height) });
                setPlacementDrag({ nodeId: placement.nodeId, mode, startX: event.clientX, startY: event.clientY, original: authoredPlacement });
                setDragPlacement(authoredPlacement);
              };
              return <g key={placement.nodeId} role="button" tabIndex={0} aria-label={`${placement.nodeId} physical rectangle`} aria-pressed={selectedPhysicalNode === placement.nodeId}
                onPointerDown={(event) => beginDrag(event, 'move')}
                onClick={() => { setSelectedPhysicalNode(placement.nodeId); setAnchorXDraft(String(placement.x)); setAnchorYDraft(String(placement.y)); setPlacementDraft({ nodeId: placement.nodeId, x: String(placement.x), y: String(placement.y), width: String(placement.width), height: String(placement.height) }); }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedPhysicalNode(placement.nodeId); setAnchorXDraft(String(placement.x)); setAnchorYDraft(String(placement.y)); setPlacementDraft({ nodeId: placement.nodeId, x: String(placement.x), y: String(placement.y), width: String(placement.width), height: String(placement.height) }); } }} style={{ cursor: authoredPlacement.locked ? 'not-allowed' : placementDrag?.nodeId === placement.nodeId ? 'grabbing' : 'grab' }}>
                <rect x={x} y={y} width={width} height={height} fill={selectedPhysicalNode === placement.nodeId ? 'var(--accent-dim)' : 'var(--bg-card)'} stroke="var(--accent)" strokeWidth={2} />
                <text x={x + width / 2} y={y + height / 2} textAnchor="middle" dominantBaseline="middle" fontSize={10} fill="var(--text)">{placement.nodeId}</text>
                <rect data-testid={`resize-handle-${placement.nodeId}`} role="button" aria-label={`${placement.nodeId} resize handle`} x={x + width - 5} y={y + height - 5} width={10} height={10} fill="var(--warn, #d9a441)"
                  onPointerDown={(event) => beginDrag(event, 'resize')} />
              </g>;
            })}
          </>}
        </svg>
      </fieldset>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button type="button" className="btn" onClick={() => setHeat((h) => !h)}>Heatmap: {heat ? 'on' : 'off'}</button>
        <button type="button" className="btn" onClick={() => { if (ref.current) exportSvgPng(ref.current, 'floorplan.png'); }}>Export PNG</button>
        <span className="muted">abstract projection — tile sizes uniform, no area or timing model</span>
      </div>
      <svg ref={ref} width="100%" height={360} style={{ background: 'var(--bg-raise)', border: '1px solid var(--border)', borderRadius: 8 }}>
        {store.doc.edges.map((e, i) => {
          const a = byId.get(e.src);
          const b = byId.get(e.dst);
          if (!a || !b) return null;
          const t = (i % 10) / 10;
          return <line key={e.id} x1={sx(a.x)} y1={sy(a.y)} x2={sx(b.x)} y2={sy(b.y)} stroke={heat ? `rgba(217,164,65,${0.3 + 0.6 * t})` : 'var(--border)'} strokeWidth={1 + 2 * t} />;
        })}
        {store.doc.nodes.map((n) => (
          <g key={n.id} transform={`translate(${sx(n.x)},${sy(n.y)})`}>
            <rect x={-24} y={-17} width={48} height={34} rx={4} fill="var(--bg-card)" stroke="var(--border)" />
            <text textAnchor="middle" y={-1} fontSize={9} fill="var(--text)" fontFamily="monospace">{n.id.slice(0, 8)}</text>
            <text textAnchor="middle" y={12} fontSize={8} fill="var(--muted)" fontFamily="monospace">{n.role.slice(0, 10)}</text>
          </g>
        ))}
      </svg>
      <p className="muted">Wire length is Manhattan canvas distance; delay and area figures are TODO with no model and are not shown.</p>
    </div>
  );
}
