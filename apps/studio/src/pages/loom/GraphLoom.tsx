/** Graph workspace — the fabric editor as a first-class view.
 *
 * A full-width canvas where a node is clicked to select, dragged to place,
 * and edited in the inspector; a link is clicked to edit its properties;
 * connections are made by picking a source and a target. This owns the
 * AUTHORING graph only. The certified FabricCanvas on the topology tab
 * stays select-only and keeps reading the compiler's TopologyView.
 */
import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { useSearch } from '../../router';
import { Link } from '../../studio';
import { graphToDraftRequest, graphToTopologyIR } from '../../graph/adapter';
import { editableDocument } from '../../canonicalDraft';
import type { GraphCommand } from '../../graph/history';
import type { GraphEdge, GraphNode } from '../../graph/project';
import { exportProjectJson } from '../../graph/io';
import { parseProjectDocument } from '../../project/document';
import { MAX_PROJECT_JSON_BYTES } from '../../graph/project';
import { laneIndex, manhattan, manhattanAvoiding, nodeFootprintRect, pathFor, withLane } from '../../graph/routing';
import { nextEdgeId, nextNodeId, pasteClipboard } from '../../graph/ids';
import { invertSelection, selectAll } from '../../graph/selectionOps';
import { alignNodes, distributeNodes, type AlignMode, type DistributeAxis } from '../../graph/alignOps';
import { INTERFACE_ROLES } from '../../graph/interfaceRole';
import { useGraphStore, type GraphStore } from '../../graph/store';
import { validateProject } from '../../graph/project';
import { PRESETS, presetClaimStatus } from '../../graph/presets';
import { linkCompatibilityProblem } from '../../graph/linkOps';
import { BUILTIN_CATALOG_V1 } from '../../graph/catalog';
import { Panes, RailSection, SummaryStrip } from './parts';
import { api, ApiError, type JobView } from '../../api';

const ROLES = ['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU'];

/** Above this node count the canvas falls back to plain Manhattan routing to
 *  stay inside the render budget; below it, links route around node boxes. */
const OBSTACLE_AVOIDANCE_MAX_NODES = 100;

export default function GraphLoom({ projectId, draftRequest }: {
  projectId: string;
  draftRequest: Record<string, unknown> | null;
}): ReactElement {
  const store = useGraphStore('mesh-8x8', projectId);
  const [selNodes, setSelNodes] = useState<string[]>([]);
  const [selEdges, setSelEdges] = useState<string[]>([]);
  const [linking, setLinking] = useState(false);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [marquee, setMarquee] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [dragPreview, setDragPreview] = useState<{ id: string; x: number; y: number } | null>(null);
  const dragPosition = useRef<{ id: string; x: number; y: number } | null>(null);
  const drag = useRef<string | null>(null);
  const band = useRef<{ from: string; x: number; y: number } | null>(null);
  const box = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const [clip, setClip] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [linkError, setLinkError] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; kind: 'node' | 'edge' | 'canvas'; id?: string } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const searchIndex = useRef(0);

  const selNode = selNodes.length === 1 ? selNodes[0] : null;
  const selEdge = selEdges.length === 1 ? selEdges[0] : null;

  const applySelection = (next: { nodes: string[]; edges: string[] }): void => {
    setSelNodes(next.nodes);
    setSelEdges(next.edges);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const el = document.activeElement as HTMLElement | null;
      const typing = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
        || el.tagName === 'SELECT' || el.isContentEditable);
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (mod && key === 'a' && !typing) {
        e.preventDefault();
        applySelection(selectAll(store.doc));
      } else if (mod && key === 'f') {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === 'Escape' && !typing) {
        applySelection({ nodes: [], edges: [] });
        setLinking(false);
        setLinkFrom(null);
        setMenu(null);
      } else if (!typing && mod && key === 'c') {
        e.preventDefault();
        doCopy();
      } else if (!typing && mod && key === 'v') {
        e.preventDefault();
        doPaste();
      } else if (!typing && mod && key === 'd') {
        e.preventDefault();
        doDuplicate();
      } else if (!typing && mod && e.key === '0') {
        e.preventDefault();
        doFit();
      } else if (!typing && (e.key === 'Delete' || e.key === 'Backspace')) {
        e.preventDefault();
        doDelete();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const select = (id: string, additive: boolean, kind: 'node' | 'edge'): void => {
    if (kind === 'node') {
      setSelEdges([]);
      setSelNodes((cur) => (additive
        ? (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id])
        : [id]));
    } else {
      setSelNodes([]);
      setSelEdges((cur) => (additive
        ? (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id])
        : [id]));
    }
  };
  const svgRef = useRef<SVGSVGElement>(null);
  useSearch(); // keep the tab's query handling identical to its siblings

  const doc = store.doc;
  const byId = useMemo(() => new Map(doc.nodes.map((n) => [n.id, n])), [doc]);
  const node = selNode ? byId.get(selNode) ?? null : null;
  const edge = selEdge ? doc.edges.find((e) => e.id === selEdge) ?? null : null;
  const issues = useMemo(() => validateProject(doc, { knownCatalogItems: BUILTIN_CATALOG_V1.items.map((item) => item.id) }), [doc]);
  const errors = useMemo(() => issues.filter((i) => i.severity === 'error'), [issues]);
  const warnings = useMemo(() => issues.filter((i) => i.severity === 'warning'), [issues]);
  const ir = useMemo(() => graphToTopologyIR(doc), [doc]);
  const claim = useMemo(() => presetClaimStatus(doc), [doc]);
  const run = (c: GraphCommand): void => { store.run(c); };
  const commitPendingDrag = (): void => {
    const pending = dragPosition.current;
    dragPosition.current = null;
    setDragPreview(null);
    if (pending) run({ type: 'move_node', id: pending.id, x: pending.x, y: pending.y });
  };

  // One named action per user operation, reused by the rail buttons and the
  // keyboard layer so a shortcut can never diverge from the button behaviour.
  const doDelete = (): void => {
    const commands: GraphCommand[] = [
      ...selEdges.map((id) => ({ type: 'delete_edge' as const, id })),
      ...selNodes.map((id) => ({ type: 'delete_node' as const, id })),
    ];
    if (commands.length === 1) run(commands[0]);
    else if (commands.length > 1) run({ type: 'batch', commands });
    if (commands.length > 0) { setSelNodes([]); setSelEdges([]); }
  };
  const clipboardForSelection = (): { nodes: GraphNode[]; edges: GraphEdge[] } => {
    const ids = new Set(selNodes);
    return {
      nodes: doc.nodes.filter((n) => ids.has(n.id)),
      edges: doc.edges.filter((e) => ids.has(e.src) && ids.has(e.dst)),
    };
  };
  const doCopy = (): void => {
    if (selNodes.length === 0 && selEdges.length === 0) return;
    setClip(clipboardForSelection());
  };
  const doPaste = (): void => {
    if (!clip) return;
    const pasted = pasteClipboard(doc, clip);
    run({ type: 'paste', nodes: pasted.nodes, edges: pasted.edges });
    setSelNodes(pasted.nodes.map((n) => n.id));
    setSelEdges([]);
  };
  const doDuplicate = (): void => {
    if (selNodes.length === 0) return;
    const pasted = pasteClipboard(doc, clipboardForSelection());
    run({ type: 'paste', nodes: pasted.nodes, edges: pasted.edges });
    setSelNodes(pasted.nodes.map((n) => n.id));
    setSelEdges([]);
  };
  const doFit = (): void => {
    if (doc.nodes.length === 0) { setView({ x: 0, y: 0, k: 1 }); return; }
    const rect = svgRef.current?.getBoundingClientRect();
    const width = rect && rect.width > 0 ? rect.width : 800;
    const height = rect && rect.height > 0 ? rect.height : 600;
    const xs = doc.nodes.map((n) => n.x);
    const ys = doc.nodes.map((n) => n.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);
    const pad = 80;
    const k = Math.min(3, Math.max(0.2, Math.min((width - pad) / spanX, (height - pad) / spanY)));
    setView({ x: (width - spanX * k) / 2 - minX * k, y: (height - spanY * k) / 2 - minY * k, k });
  };
  const searchMatches = useMemo(() => {
    const q = searchTerm.trim().toLowerCase();
    if (!q) return [] as GraphNode[];
    return doc.nodes.filter((n) =>
      n.id.toLowerCase().includes(q)
      || n.role.toLowerCase().includes(q)
      || (n.catalogRef?.itemId ?? '').toLowerCase().includes(q)
      || (n.catalogRef?.catalogId ?? '').toLowerCase().includes(q));
  }, [doc, searchTerm]);
  const centerOn = (target: GraphNode): void => {
    const rect = svgRef.current?.getBoundingClientRect();
    const width = rect && rect.width > 0 ? rect.width : 800;
    const height = rect && rect.height > 0 ? rect.height : 600;
    setView((v) => ({ ...v, x: width / 2 - target.x * v.k, y: height / 2 - target.y * v.k }));
  };
  const doFindNext = (): void => {
    if (searchMatches.length === 0) return;
    const target = searchMatches[searchIndex.current % searchMatches.length]!;
    searchIndex.current += 1;
    select(target.id, false, 'node');
    centerOn(target);
  };

  // A context menu closes on the next window click or on Escape.
  useEffect(() => {
    if (!menu) return;
    const close = (): void => setMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [menu]);

  const canvasSize = (): { width: number; height: number } => {
    const rect = svgRef.current?.getBoundingClientRect();
    return { width: rect && rect.width > 0 ? rect.width : 800, height: rect && rect.height > 0 ? rect.height : 600 };
  };
  const centerOnPoint = (point: { x: number; y: number }): void => {
    const size = canvasSize();
    setView((v) => ({ ...v, x: size.width / 2 - point.x * v.k, y: size.height / 2 - point.y * v.k }));
  };
  const bounds = useMemo(() => {
    if (doc.nodes.length === 0) return null;
    const xs = doc.nodes.map((n) => n.x);
    const ys = doc.nodes.map((n) => n.y);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    return { minX, minY, spanX: Math.max(1, Math.max(...xs) - minX), spanY: Math.max(1, Math.max(...ys) - minY) };
  }, [doc]);
  const visualPosition = (n: GraphNode): { x: number; y: number } =>
    dragPreview?.id === n.id ? { x: dragPreview.x, y: dragPreview.y } : n;

  const edgeUnique = (src: string, dst: string): boolean =>
    !doc.edges.some((e) => (e.src === src && e.dst === dst)
      || (e.src === dst && e.dst === src));
  const portsOf = (id: string): number => doc.edges.filter(
    (e) => e.src === id || e.dst === id).length;
  const usedPorts = (id: string): number => Number(byId.get(id)?.ports ?? 0);

  const svgPoint = (event: React.MouseEvent<SVGSVGElement>): { x: number; y: number } => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - view.x) / view.k,
      y: (event.clientY - rect.top - view.y) / view.k,
    };
  };

  const canvas = (
    <div className="loom-view" style={{ position: 'relative' }}>
      <SummaryStrip items={[
        { k: 'Nodes', v: String(doc.nodes.length), tone: 'info' },
        { k: 'Links', v: String(doc.edges.length) },
        { k: 'Shape', v: claim.holds && doc.presetHint ? doc.presetHint : 'custom' },
        { k: 'Validation',
          v: errors.length ? `${errors.length} error(s)` : warnings.length ? `${warnings.length} warning(s)` : 'clean',
          tone: errors.length ? 'bad' : warnings.length ? 'warn' : 'ok' },
        { k: 'Compiler apply', v: 'blocked · local projection only', tone: 'warn' },
      ]} />
      <div className="row" style={{ gap: 8, margin: '8px 0' }}>
        <button type="button" className={`btn ${linking ? 'primary' : ''}`}
          onClick={() => { setLinking((l) => !l); setLinkFrom(null); }}>
          {linking ? (linkFrom ? `linking from ${linkFrom} — pick a target` : 'link mode: pick a source')
            : 'link mode'}
        </button>
        <button type="button" className="btn" onClick={() => { setLinking(false); setLinkFrom(null); }}>done linking</button>
        <button type="button" className="btn" onClick={() => setView({ x: 0, y: 0, k: 1 })}>reset view</button>
        <button type="button" className="btn" onClick={doFit}>fit view</button>
        <span className="muted">click to select · drag to place · wheel to zoom · shift-drag to pan</span>
      </div>
      {linkError && <p className="t-bad" role="alert" data-testid="link-error">{linkError}</p>}
      <svg
        ref={svgRef}
        data-testid="graph-canvas"
        role="application"
        aria-label="fabric graph canvas"
        width="100%"
        height={520}
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, cursor: linking ? 'crosshair' : 'default' }}
        onWheel={(e) => setView((v) => ({ ...v, k: Math.min(3, Math.max(0.2, v.k * (e.deltaY < 0 ? 1.1 : 0.9))) }))}
        onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, kind: 'canvas' }); }}
        onMouseDown={(e) => {
          if (e.shiftKey) { drag.current = '__pan__'; return; }
          if (e.target === e.currentTarget) {
            box.current = { x: e.clientX, y: e.clientY, moved: false };
          }
        }}
        onMouseMove={(e) => {
          if (box.current) {
            if (Math.abs(e.clientX - box.current.x) > 4
              || Math.abs(e.clientY - box.current.y) > 4) {
              box.current.moved = true;
              const r = e.currentTarget.getBoundingClientRect();
              setMarquee({
                x: (Math.min(e.clientX, box.current.x) - r.left - view.x) / view.k,
                y: (Math.min(e.clientY, box.current.y) - r.top - view.y) / view.k,
                w: Math.abs(e.clientX - box.current.x) / view.k,
                h: Math.abs(e.clientY - box.current.y) / view.k,
              });
            }
            return;
          }
          if (drag.current === '__pan__') {
            setView((v) => ({ ...v, x: v.x + e.movementX, y: v.y + e.movementY }));
            return;
          }
          if (!drag.current) return;
          const id = drag.current;
          const original = byId.get(id);
          if (!original) return;
          const p = svgPoint(e);
          const x = Math.round(p.x / 20) * 20;
          const y = Math.round(p.y / 20) * 20;
          if (x === original.x && y === original.y) {
            dragPosition.current = null;
            setDragPreview(null);
          } else if (dragPosition.current?.id !== id
            || dragPosition.current.x !== x || dragPosition.current.y !== y) {
            dragPosition.current = { id, x, y };
            setDragPreview({ id, x, y });
          }
        }}
        onMouseUp={(e) => {
          commitPendingDrag();
          drag.current = null;
          if (band.current) {
            const target = e.target as Element;
            const hit = target.closest('[data-node-id]');
            const to = hit?.getAttribute('data-node-id') ?? null;
            if (to && to !== band.current.from) {
              const from = band.current.from;
              const free = !doc.edges.some((e2) => (e2.src === from && e2.dst === to)
                || (e2.src === to && e2.dst === from));
              if (free) {
                run({ type: 'add_edge', edge: { id: nextEdgeId(doc.edges), src: from, dst: to, width: 512, pipelineStages: 1, vcClass: 0 } });
              }
            }
            band.current = null;
          }
          if (box.current?.moved) {
            const r = e.currentTarget.getBoundingClientRect();
            const x1 = (Math.min(e.clientX, box.current.x) - r.left - view.x) / view.k;
            const x2 = (Math.max(e.clientX, box.current.x) - r.left - view.x) / view.k;
            const y1 = (Math.min(e.clientY, box.current.y) - r.top - view.y) / view.k;
            const y2 = (Math.max(e.clientY, box.current.y) - r.top - view.y) / view.k;
            const inside = doc.nodes.filter((n) => n.x >= x1 && n.x <= x2 && n.y >= y1 && n.y <= y2)
              .map((n) => n.id);
            setSelNodes(inside);
            setSelEdges(doc.edges.filter((ed) => inside.includes(ed.src) && inside.includes(ed.dst))
              .map((ed) => ed.id));
            setMarquee(null);
          }
          box.current = null;
        }}
        onMouseLeave={() => {
          if (drag.current && drag.current !== '__pan__') commitPendingDrag();
          drag.current = null;
          box.current = null;
        }}
        onClick={() => { setSelNodes([]); setSelEdges([]); }}
      >
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {doc.edges.map((e) => {
            const a = byId.get(e.src);
            const b = byId.get(e.dst);
            if (!a || !b) return null;
            const pa = visualPosition(a);
            const pb = visualPosition(b);
            // Obstacle avoidance for normal graph sizes; large graphs fall back
            // to plain Manhattan routing to stay within the render budget.
            const base = doc.nodes.length <= OBSTACLE_AVOIDANCE_MAX_NODES
              ? manhattanAvoiding(pa, pb, doc.nodes
                .filter((n) => n.id !== e.src && n.id !== e.dst)
                .map((n) => nodeFootprintRect(visualPosition(n))), 10)
              : manhattan(pa, pb);
            // Deterministic lane so links from one source do not overlap exactly.
            const d = pathFor(withLane(base, laneIndex(doc.edges, e.id)));
            return (
              <g key={e.id}>
                <path d={d} fill="none" stroke="transparent" strokeWidth={16} style={{ cursor: 'pointer' }}
                  onClick={(ev) => { ev.stopPropagation(); select(e.id, ev.shiftKey || ev.metaKey || ev.ctrlKey, 'edge'); }}
                  onContextMenu={(ev) => { ev.preventDefault(); ev.stopPropagation(); select(e.id, false, 'edge'); setMenu({ x: ev.clientX, y: ev.clientY, kind: 'edge', id: e.id }); }}
                  data-testid={`link-${e.id}`} />
                <path d={d} fill="none"
                  stroke={selEdge === e.id ? 'var(--warn, #d9a441)' : 'var(--accent)'}
                  strokeWidth={selEdge === e.id ? 5 : 2} opacity={0.8} />
              </g>
            );
          })}
          {doc.nodes.map((n) => {
            const used = portsOf(n.id);
            const cap = usedPorts(n.id);
            const over = used > cap;
            const position = visualPosition(n);
            return (
              <g key={n.id} transform={`translate(${position.x},${position.y})`}
                data-node-id={n.id}
                onMouseDown={(e) => { e.stopPropagation(); if (!e.shiftKey) drag.current = n.id; }}
                onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); select(n.id, false, 'node'); setMenu({ x: e.clientX, y: e.clientY, kind: 'node', id: n.id }); }}
                onClick={(e) => {
                  e.stopPropagation();
                  if (linking) {
                    if (!linkFrom) { setLinkFrom(n.id); setLinkError(null); return; }
                    if (linkFrom !== n.id) {
                      const problem = linkCompatibilityProblem(doc, linkFrom, n.id);
                      if (problem) { setLinkError(problem); return; }
                      const edgeId = nextEdgeId(doc.edges);
                      run({ type: 'add_edge', edge: { id: edgeId, src: linkFrom, dst: n.id, width: 512, pipelineStages: 1, vcClass: 0 } });
                      setLinkError(null);
                      setLinkFrom(null);
                      setLinking(false);
                      // Select the new link so its inspector opens immediately.
                      setSelNodes([]);
                      setSelEdges([edgeId]);
                    }
                    return;
                  }
                  select(n.id, e.shiftKey || e.metaKey || e.ctrlKey, 'node');
                }}
                style={{ cursor: 'pointer' }}
                data-testid={`node-${n.id}`}>
                {(['e', 'w', 'n', 's'] as const).map((side) => {
                  const pos = { e: [46, 0], w: [-46, 0], n: [0, -32], s: [0, 32] }[side];
                  return (
                    <circle key={side} cx={pos[0]} cy={pos[1]} r={5}
                      fill="var(--accent)" opacity={0.75}
                      style={{ cursor: 'crosshair' }}
                      data-testid={`port-${n.id}-${side}`}
                      onMouseDown={(e) => {
                        e.stopPropagation();
                        band.current = { from: n.id, x: pos[0], y: pos[1] };
                      }} />
                  );
                })}
                <rect x={-38} y={-24} width={76} height={48} rx={8}
                  fill={selNodes.includes(n.id) ? 'var(--accent-dim)' : 'var(--bg-raise)'}
                  stroke={over ? 'var(--bad, #e0655a)' : selNodes.includes(n.id) ? 'var(--accent)' : 'var(--border)'}
                  strokeWidth={selNode === n.id ? 2.5 : 1.5} />
                <text textAnchor="middle" y={-6} fontSize={12} fill="var(--text)" fontFamily="monospace">{n.id}</text>
                <text textAnchor="middle" y={8} fontSize={10} fill="var(--muted)" fontFamily="monospace">{n.role}</text>
                <text textAnchor="middle" y={21} fontSize={9} fill={over ? 'var(--bad, #e0655a)' : 'var(--muted)'} fontFamily="monospace">
                  {used}/{cap} ports
                </text>
                {linkFrom === n.id && <circle r={8} cx={0} cy={-32} fill="var(--accent)" />}
              </g>
            );
          })}
          {marquee && (
            <rect x={marquee.x} y={marquee.y} width={marquee.w} height={marquee.h}
              fill="var(--accent)" opacity={0.12} stroke="var(--accent)" strokeDasharray="4 3" />
          )}
        </g>
      </svg>
      {bounds && (
        <div data-testid="graph-minimap"
          style={{ position: 'absolute', top: 8, right: 8, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: 4 }}>
          {(() => {
            const W = 160;
            const H = 120;
            const PAD = 6;
            const scale = Math.min((W - PAD * 2) / bounds.spanX, (H - PAD * 2) / bounds.spanY);
            const mapX = (x: number): number => PAD + (x - bounds.minX) * scale;
            const mapY = (y: number): number => PAD + (y - bounds.minY) * scale;
            const size = canvasSize();
            const vx = (0 - view.x) / view.k;
            const vy = (0 - view.y) / view.k;
            return (
              <svg width={W} height={H} role="img" aria-label="graph minimap" style={{ cursor: 'pointer', display: 'block' }}
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  centerOnPoint({
                    x: bounds.minX + (e.clientX - rect.left - PAD) / scale,
                    y: bounds.minY + (e.clientY - rect.top - PAD) / scale,
                  });
                }}>
                <rect data-testid="minimap-viewport" x={mapX(vx)} y={mapY(vy)}
                  width={(size.width / view.k) * scale} height={(size.height / view.k) * scale}
                  fill="var(--accent)" opacity={0.12} stroke="var(--accent)" />
                {doc.nodes.map((n) => (
                  <circle key={n.id} cx={mapX(n.x)} cy={mapY(n.y)} r={2}
                    fill={selNodes.includes(n.id) ? 'var(--warn, #d9a441)' : 'var(--text)'} />
                ))}
              </svg>
            );
          })()}
        </div>
      )}
      {menu && (
        <div role="menu" data-testid="graph-context-menu"
          style={{ position: 'fixed', left: menu.x, top: menu.y, zIndex: 50, display: 'flex', flexDirection: 'column', gap: 2, background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: 4, minWidth: 150 }}
          onClick={(e) => e.stopPropagation()}>
          {menu.kind === 'node' && (<>
            <button type="button" className="btn" onClick={() => { doDuplicate(); setMenu(null); }}>duplicate</button>
            <button type="button" className="btn" onClick={() => { doCopy(); setMenu(null); }}>copy</button>
            <button type="button" className="btn" onClick={() => { setLinking(true); setLinkFrom(menu.id ?? null); setMenu(null); }}>link from here</button>
            <button type="button" className="btn" onClick={() => { doDelete(); setMenu(null); }}>delete</button>
          </>)}
          {menu.kind === 'edge' && (
            <button type="button" className="btn" onClick={() => { if (menu.id) run({ type: 'delete_edge', id: menu.id }); setSelEdges([]); setMenu(null); }}>delete link</button>
          )}
          {menu.kind === 'canvas' && (<>
            <button type="button" className="btn" disabled={!clip} onClick={() => { doPaste(); setMenu(null); }}>paste</button>
            <button type="button" className="btn" onClick={() => { applySelection(selectAll(doc)); setMenu(null); }}>select all</button>
            <button type="button" className="btn" onClick={() => { doFit(); setMenu(null); }}>fit view</button>
          </>)}
        </div>
      )}
      <p className="muted" style={{ fontSize: 12 }}>
        {ir.refused
          ? `Local topology preview unavailable: ${ir.refused}`
          : 'Edits validate locally. This graph is not the canonical V3/V4/V5 draft and cannot be applied or compiled without a lossless migration.'}
      </p>
    </div>
  );

  return (
    <Panes
      left={
        <>
          <RailSection title="Shape">
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <select aria-label="graph preset" value={doc.presetHint ?? 'custom'}
                onChange={(e) => {
                  const found = PRESETS.find((p) => p.hint === e.target.value);
                  if (found) { store.loadPreset(found.id); setSelNodes([]); setSelEdges([]); }
                }}>
                {!doc.presetHint && <option value="custom">custom</option>}
                {PRESETS.map((p) => <option key={p.id} value={p.hint}>{p.label}</option>)}
              </select>
            </div>
            <p className="muted" style={{ fontSize: 12 }}>
              A preset only seeds the graph. Any edit makes it custom.
            </p>
          </RailSection>

          <RailSection title="Add">
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              {doc.nodes.length > 0 && <button type="button" className="btn" onClick={() => {
                const anchor = selNode ?? doc.nodes[0]?.id;
                if (!anchor) return;
                const a = byId.get(anchor);
                const id = nextNodeId(doc.nodes);
                const err = store.run({
                  type: 'paste',
                  nodes: [{ id, x: (a?.x ?? 200) + 120, y: (a?.y ?? 200) + 80, role: 'compute_tile', ports: 5, clock: 'clk_core' }],
                  edges: edgeUnique(anchor, id)
                    ? [{ id: nextEdgeId(doc.edges), src: anchor, dst: id, width: 512, pipelineStages: 1, vcClass: 0 }]
                    : [],
                });
                if (!err) setSelNodes([id]);
              }}>node (auto-wired)</button>}
              <button type="button" className="btn" disabled={selNodes.length === 0 && selEdges.length === 0}
                onClick={doDelete}>delete selected</button>
              <button type="button" className="btn"
                disabled={selNodes.length === 0 && selEdges.length === 0}
                onClick={doCopy}>copy</button>
              <button type="button" className="btn" disabled={!clip}
                onClick={doPaste}>paste</button>
              <button type="button" className="btn" disabled={selNodes.length === 0}
                onClick={doDuplicate}>duplicate</button>
            </div>
            <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              <button type="button" className="btn" onClick={() => exportProjectJson(doc)}>save project.json</button>
              <label className="btn" style={{ cursor: 'pointer' }}>load project.json
                <input type="file" accept=".json" hidden onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  try {
                    if (f.size > MAX_PROJECT_JSON_BYTES) throw new Error(`project file exceeds ${MAX_PROJECT_JSON_BYTES} byte limit`);
                    const text = await f.text();
                    parseProjectDocument(text);
                    const err = store.loadJson(text);
                    if (err) throw new Error(err);
                    setSelNodes([]); setSelEdges([]);
                  } catch (err) {
                    setLoadError(err instanceof Error ? err.message : String(err));
                  }
                  e.target.value = '';
                }} />
              </label>
            </div>
            {loadError && <p className="t-bad" role="alert">{loadError}</p>}
          </RailSection>

          <RailSection title="Nodes">
            <div style={{ maxHeight: 260, overflow: 'auto' }}>
              {doc.nodes.length === 0 ? (
                <div className="empty-state">
                  <strong>No nodes yet</strong>
                  <p className="muted">Create the first node to start building this graph.</p>
                  <div className="empty-actions">
                    <button type="button" className="btn primary" onClick={() => {
                      const id = nextNodeId(doc.nodes);
                      const err = store.run({ type: 'paste', nodes: [{ id, x: 200, y: 200, role: 'compute_tile', ports: 5, clock: 'clk_core' }], edges: [] });
                      if (!err) setSelNodes([id]);
                    }}>create first node</button>
                  </div>
                </div>
              ) : doc.nodes.map((n) => (
                <button key={n.id} type="button" className="btn"
                  style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 2 }}
                  onClick={() => { setSelNodes([n.id]); setSelEdges([]); }}>
                  <code>{n.id}</code> <span className="muted">{n.role}</span>
                </button>
              ))}
            </div>
          </RailSection>

          <RailSection title="Selection">
            <p className="muted" style={{ fontSize: 12 }} data-testid="selection-count">
              {selNodes.length} node(s), {selEdges.length} link(s) selected
            </p>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <button type="button" className="btn" onClick={() => applySelection(selectAll(doc))}>select all</button>
              <button type="button" className="btn"
                onClick={() => applySelection(invertSelection(doc, { nodes: selNodes, edges: selEdges }))}>invert</button>
              <button type="button" className="btn" onClick={() => applySelection({ nodes: [], edges: [] })}>clear</button>
            </div>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              {(['left', 'right', 'top', 'bottom', 'center-x', 'center-y'] as AlignMode[]).map((mode) => (
                <button key={mode} type="button" className="btn" disabled={selNodes.length < 2}
                  aria-label={`align ${mode}`}
                  onClick={() => {
                    const updates = alignNodes(doc.nodes, selNodes, mode);
                    if (updates.length > 0) run({ type: 'update_nodes', updates });
                  }}>align {mode}</button>
              ))}
            </div>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              {(['horizontal', 'vertical'] as DistributeAxis[]).map((axis) => (
                <button key={axis} type="button" className="btn" disabled={selNodes.length < 3}
                  aria-label={`distribute ${axis}`}
                  onClick={() => {
                    const updates = distributeNodes(doc.nodes, selNodes, axis);
                    if (updates.length > 0) run({ type: 'update_nodes', updates });
                  }}>distribute {axis}</button>
              ))}
            </div>
          </RailSection>

          <RailSection title="Find">
            <div className="row" style={{ gap: 8 }}>
              <input ref={searchRef} aria-label="search topology" placeholder="id, role or catalog item"
                value={searchTerm} onChange={(e) => { setSearchTerm(e.target.value); searchIndex.current = 0; }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); doFindNext(); } }} />
              <button type="button" className="btn" disabled={searchMatches.length === 0} onClick={doFindNext}>find next</button>
            </div>
            <p className="muted" data-testid="search-count">
              {searchTerm.trim() ? `${searchMatches.length} match(es)` : 'Type to match nodes by id, role or catalog item.'}
            </p>
          </RailSection>

          <RailSection title="Shortcuts">
            <ul className="muted" style={{ fontSize: 12, margin: 0, paddingLeft: 16 }}>
              <li>Ctrl/Cmd+A select all · Escape clear</li>
              <li>Delete/Backspace delete · Ctrl/Cmd+D duplicate</li>
              <li>Ctrl/Cmd+C copy · Ctrl/Cmd+V paste</li>
              <li>Ctrl/Cmd+Z undo · Ctrl/Cmd+Shift+Z redo</li>
              <li>Ctrl/Cmd+0 fit · Ctrl/Cmd+F search</li>
            </ul>
          </RailSection>
        </>
      }
      stage={canvas}
      right={
        <>
          <RailSection title="Inspector">
            {!node && !edge && (
              <p className="muted">
                Click a node or a link on the canvas to edit its properties.
              </p>
            )}
            {node && (
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <label>id <code>{node.id}</code></label>
                <label>role
                  <select aria-label="inspector role" value={node.role}
                    onChange={(e) => run({ type: 'update_node', id: node.id, patch: { role: e.target.value } })}>
                    {ROLES.map((r) => <option key={r} value={r}>{r === 'NPU' ? 'NPU (local only)' : r}</option>)}
                  </select>
                </label>
                <label>interface role
                  <select aria-label="inspector interface role" value={node.interfaceRole ?? ''}
                    onChange={(e) => run({ type: 'update_node', id: node.id, patch: { interfaceRole: (e.target.value === '' ? null : e.target.value) as GraphNode['interfaceRole'] } })}>
                    <option value="">unconstrained</option>
                    {INTERFACE_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </label>
                <label>ports
                  <input aria-label="inspector ports" type="number" min={1} defaultValue={node.ports}
                    key={`${node.id}-p${node.ports}`} style={{ width: 70 }}
                    onBlur={(e) => run({ type: 'update_node', id: node.id, patch: { ports: Math.max(1, Number(e.target.value) | 0) } })} />
                </label>
                <label>clock
                  <input aria-label="inspector clock" defaultValue={node.clock ?? ''}
                    key={`${node.id}-c${node.clock ?? ''}`} style={{ width: 100 }}
                    onBlur={(e) => run({ type: 'update_node', id: node.id, patch: { clock: e.target.value.trim() || null } })} />
                </label>
                <label>vc depth
                  <input aria-label="inspector vc depth" type="number" min={1}
                    defaultValue={String(((node.vc ?? {}) as Record<string, unknown>).depth ?? 4)}
                    key={`${node.id}-d${String(((node.vc ?? {}) as Record<string, unknown>).depth ?? 4)}`} style={{ width: 70 }}
                    onBlur={(e) => run({ type: 'update_node', id: node.id, patch: { vc: { ...((node.vc ?? {}) as object), depth: Math.max(1, Number(e.target.value) | 0) } } })} />
                </label>
                <label>link this node as
                  <button type="button" className="btn"
                    onClick={() => { setSelNodes([node.id]); setLinkFrom(node.id); setLinking(true); }}>
                    start a connection here
                  </button>
                </label>
              </div>
            )}
            {edge && (
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <label>link <code>{edge.id}</code></label>
                <label>{edge.src} → {edge.dst}</label>
                <label>width
                  <input aria-label="inspector width" type="number" min={1} defaultValue={edge.width}
                    key={`${edge.id}-w${edge.width}`} style={{ width: 80 }}
                    onBlur={(e) => run({ type: 'update_edge', id: edge.id, patch: { width: Math.max(1, Number(e.target.value) | 0) } })} />
                </label>
                <label>stages
                  <input aria-label="inspector stages" type="number" min={1} defaultValue={edge.pipelineStages}
                    key={`${edge.id}-s${edge.pipelineStages}`} style={{ width: 80 }}
                    onBlur={(e) => run({ type: 'update_edge', id: edge.id, patch: { pipelineStages: Math.max(1, Number(e.target.value) | 0) } })} />
                </label>
                <label>vc class
                  <input aria-label="inspector vc class" type="number" min={0} defaultValue={edge.vcClass}
                    key={`${edge.id}-v${edge.vcClass}`} style={{ width: 80 }}
                    onBlur={(e) => run({ type: 'update_edge', id: edge.id, patch: { vcClass: Math.max(0, Number(e.target.value) | 0) } })} />
                </label>
                <button type="button" className="btn" onClick={() => { run({ type: 'delete_edge', id: edge.id }); setSelEdges([]); }}>delete link</button>
              </div>
            )}
          </RailSection>

          <RailSection title="History">
            <div className="row" style={{ gap: 8 }}>
              <button type="button" className="btn" disabled={!store.canUndo} onClick={() => store.undo()}>undo</button>
              <button type="button" className="btn" disabled={!store.canRedo} onClick={() => store.redo()}>redo</button>
              {store.dirty && <span className="muted">unsaved</span>}
            </div>
          </RailSection>

          <RailSection title="Problems">
            {issues.length === 0
              ? <p className="muted">No issue in the graph.</p>
              : (
                <ul className="loom-needs">
                  {issues.map((i) => (
                    <li key={`${i.code}-${i.path}-${i.message}`} className={i.severity === 'error' ? 't-bad' : 't-warn'}>
                      <code>{i.path}</code> — {i.message}
                      {i.components && (
                        <ul>
                          {i.components.map((c, ci) => (
                            <li key={ci} className="muted">component {ci + 1}: {c.join(', ')}</li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            {store.error && <p className="t-bad" role="alert">{store.error}</p>}
          </RailSection>

          <RailSection title="Send to the compiler">
            <ApplyPanel store={store} projectId={projectId} draftRequest={draftRequest} />
          </RailSection>
        </>
      }
    />
  );
}

/** Poll a job to a terminal state. Bounded, so a stuck job cannot spin. */
async function pollJob(jobId: string, attempts = 60): Promise<JobView> {
  let job: JobView = { job_id: jobId, state: 'QUEUED' } as JobView;
  for (let i = 0; i < attempts; i += 1) {
    await new Promise((r) => setTimeout(r, 2000));
    job = await api.job(jobId);
    if (['COMPLETED', 'REFUSED', 'FAILED', 'CANCELLED'].includes(job.state)) return job;
  }
  return job;
}

function ApplyPanel({ store, projectId, draftRequest }: {
  store: GraphStore;
  projectId: string;
  draftRequest: Record<string, unknown> | null;
}): ReactElement {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState<string | null>(null);
  const [back, setBack] = useState<{ routers: number; pairs: number; channels: number; family: string } | null>(null);
  const ir = useMemo(() => graphToTopologyIR(store.doc), [store.doc]);
  const lowered = useMemo(
    () => graphToDraftRequest(store.doc, draftRequest ?? {}),
    [store.doc, draftRequest],
  );

  const readback = async (revisionId: string): Promise<void> => {
    try {
      const t = await api.topology(revisionId);
      const pairs = new Set(t.channels.filter((c) => c.src_router !== c.dst_router).map((c) => {
        const a = Math.min(c.src_router, c.dst_router);
        const b = Math.max(c.src_router, c.dst_router);
        return `${a}-${b}`;
      }));
      setBack({
        routers: t.counts.routers,
        pairs: pairs.size,
        channels: t.counts.channels,
        family: String(t.family),
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    }
  };

  const apply = async (andCompile: boolean): Promise<void> => {
    if (!draftRequest) {
      setError('This project has no draft to write onto.');
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (!lowered.doc) {
        setError(lowered.refused ?? 'graph application refused');
        return;
      }
      const saved = await api.putDraft(projectId, editableDocument(lowered.doc));
      setMessage(`Draft saved · design ${(saved.design_hash ?? '—').slice(0, 18)}…`);
      if (andCompile) {
        if (!saved.design_hash) throw new Error('saved draft has no identity');
        const submitted = await api.compileJob(projectId, saved.design_hash);
        setMessage(`Draft saved · compile ${submitted.state}`);
        // A compile is a job: poll it to a terminal state before claiming
        // anything about the result. An unfinished job is not a verdict.
        const settled = await pollJob(submitted.job_id);
        if (settled.state === 'COMPLETED' && settled.result?.revision_id) {
          setRevision(settled.result.revision_id);
          setMessage(`Draft saved and compiled · revision ${settled.result.revision_id}`);
          await readback(settled.result.revision_id);
        } else {
          setMessage(`Draft saved · compile ${settled.state}`);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const projectedLinkCount = ir.doc ? (ir.doc.links as unknown[]).length : 0;
  const match = back && back.routers === store.doc.nodes.length
    && back.pairs === projectedLinkCount;

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        Saving replaces only the draft topology. Existing agent/interface, NoC control, address-map, and V5 intent are preserved; node roles and canvas positions remain editor annotations.
      </p>
      {lowered.refused && (
        <div id="graph-apply-refusal" className="t-warn" role="alert">
          <p>{lowered.refused}</p>
          <Link className="link" to={`/projects/${projectId}/design`}>Open Design to edit the canonical draft</Link>
        </div>
      )}
      {projectId && !draftRequest && (
        <p className="muted" role="status">
          Loading the project’s canonical draft. Local graph edits are preserved;
          apply and compile become available when the draft is ready.
        </p>
      )}
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn" disabled={busy || !draftRequest || !lowered.doc}
          aria-describedby="graph-apply-refusal"
          onClick={() => { void apply(false); }}>save to draft</button>
        <button type="button" className="btn" disabled={busy || !draftRequest || !lowered.doc}
          aria-describedby="graph-apply-refusal"
          onClick={() => { void apply(true); }}>save + compile</button>
      </div>
      {message && <p className="t-ok">{message}</p>}
      {error && <p className="t-bad" role="alert">{error}</p>}
      {back && (
        <div style={{ marginTop: 8 }}>
          <p className="muted" style={{ fontSize: 12 }}>
            certified {revision}: {back.routers} routers · {back.pairs} link pairs
            · {back.channels} directed channels · {back.family}
          </p>
          <p className={match ? 't-ok' : 't-warn'}>
            {match
              ? '✓ the compiled fabric is the graph you applied'
              : '● the compiled fabric diverges from this graph; the revision is authoritative'}
          </p>
        </div>
      )}
    </div>
  );
}
