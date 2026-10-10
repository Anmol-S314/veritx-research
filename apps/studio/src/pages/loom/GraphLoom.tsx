/** Graph workspace — the fabric editor as a first-class view.
 *
 * A full-width canvas where a node is clicked to select, dragged to place,
 * and edited in the inspector; a link is clicked to edit its properties;
 * connections are made by picking a source and a target. This owns the
 * AUTHORING graph only. The certified FabricCanvas on the topology tab
 * stays select-only and keeps reading the compiler's TopologyView.
 */
import { useMemo, useRef, useState, type ReactElement } from 'react';
import { useSearch } from '../../router';
import { graphToDraftRequest, graphToTopologyIR } from '../../graph/adapter';
import type { GraphCommand } from '../../graph/history';
import type { GraphEdge, GraphNode } from '../../graph/project';
import { exportProjectJson } from '../../graph/io';
import { parseProject } from '../../graph/project';
import { manhattan, pathFor } from '../../graph/routing';
import { useGraphStore, type GraphStore } from '../../graph/store';
import { validateProject } from '../../graph/project';
import { PRESETS } from '../../graph/presets';
import { Panes, RailSection, SummaryStrip } from './parts';
import { api, ApiError, type JobView } from '../../api';

const ROLES = ['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU'];

export default function GraphLoom({ projectId, draftRequest }: {
  projectId: string;
  draftRequest: Record<string, unknown> | null;
}): ReactElement {
  const store = useGraphStore('mesh-8x8');
  const [selNodes, setSelNodes] = useState<string[]>([]);
  const [selEdges, setSelEdges] = useState<string[]>([]);
  const [linking, setLinking] = useState(false);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [marquee, setMarquee] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const drag = useRef<string | null>(null);
  const band = useRef<{ from: string; x: number; y: number } | null>(null);
  const box = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const clip = useRef<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const selNode = selNodes.length === 1 ? selNodes[0] : null;
  const selEdge = selEdges.length === 1 ? selEdges[0] : null;

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
  const issues = useMemo(() => validateProject(doc), [doc]);
  const ir = useMemo(() => graphToTopologyIR(doc), [doc]);
  const run = (c: GraphCommand): void => { store.run(c); };

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
    <div className="loom-view">
      <SummaryStrip items={[
        { k: 'Nodes', v: String(doc.nodes.length), tone: 'info' },
        { k: 'Links', v: String(doc.edges.length) },
        { k: 'Shape', v: doc.presetHint ?? 'custom' },
        { k: 'Validation', v: issues.length ? `${issues.length} issue(s)` : 'clean',
          tone: issues.length ? 'bad' : 'ok' },
        { k: 'Lowering', v: ir.refused ? 'refused' : `${(ir.doc?.links as unknown[] | undefined)?.length ?? 0} links`,
          tone: ir.refused ? 'warn' : 'ok' },
      ]} />
      <div className="row" style={{ gap: 8, margin: '8px 0' }}>
        <button type="button" className={`btn ${linking ? 'primary' : ''}`}
          onClick={() => { setLinking((l) => !l); setLinkFrom(null); }}>
          {linking ? (linkFrom ? `linking from ${linkFrom} — pick a target` : 'link mode: pick a source')
            : 'link mode'}
        </button>
        <button type="button" className="btn" onClick={() => { setLinking(false); setLinkFrom(null); }}>done linking</button>
        <button type="button" className="btn" onClick={() => setView({ x: 0, y: 0, k: 1 })}>reset view</button>
        <span className="muted">click to select · drag to place · wheel to zoom · shift-drag to pan</span>
      </div>
      <svg
        ref={svgRef}
        data-testid="graph-canvas"
        role="application"
        aria-label="fabric graph canvas"
        width="100%"
        height={520}
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, cursor: linking ? 'crosshair' : 'default' }}
        onWheel={(e) => setView((v) => ({ ...v, k: Math.min(3, Math.max(0.2, v.k * (e.deltaY < 0 ? 1.1 : 0.9))) }))}
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
          const p = svgPoint(e);
          run({ type: 'move_node', id: drag.current, x: Math.round(p.x / 20) * 20, y: Math.round(p.y / 20) * 20 });
        }}
        onMouseUp={(e) => {
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
                run({ type: 'add_edge', edge: { id: `e${Date.now() % 900000 + 100000}`, src: from, dst: to, width: 512, pipelineStages: 1, vcClass: 0 } });
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
        onMouseLeave={() => { drag.current = null; box.current = null; }}
        onClick={() => { setSelNodes([]); setSelEdges([]); }}
      >
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {doc.edges.map((e) => {
            const a = byId.get(e.src);
            const b = byId.get(e.dst);
            if (!a || !b) return null;
            const d = pathFor(manhattan({ x: a.x, y: a.y }, { x: b.x, y: b.y }));
            return (
              <g key={e.id}>
                <path d={d} fill="none" stroke="transparent" strokeWidth={16} style={{ cursor: 'pointer' }}
                  onClick={(ev) => { ev.stopPropagation(); select(e.id, ev.shiftKey || ev.metaKey || ev.ctrlKey, 'edge'); }}
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
            return (
              <g key={n.id} transform={`translate(${n.x},${n.y})`}
                data-node-id={n.id}
                onMouseDown={(e) => { e.stopPropagation(); if (!e.shiftKey) drag.current = n.id; }}
                onClick={(e) => {
                  e.stopPropagation();
                  if (linking) {
                    if (!linkFrom) { setLinkFrom(n.id); return; }
                    if (linkFrom !== n.id) {
                      run({ type: 'add_edge', edge: { id: `e${Date.now() % 900000 + 100000}`, src: linkFrom, dst: n.id, width: 512, pipelineStages: 1, vcClass: 0 } });
                      setLinkFrom(null);
                      setLinking(false);
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
      <p className="muted" style={{ fontSize: 12 }}>
        {ir.refused
          ? `The compiler adapter refuses this graph: ${ir.refused}`
          : 'Every edit validates on the way in; a refused edit changes nothing.'}
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
              <button type="button" className="btn" onClick={() => {
                const anchor = selNode ?? doc.nodes[0]?.id;
                if (!anchor) return;
                const a = byId.get(anchor);
                const id = `n${Date.now() % 90000 + 10000}`;
                const err = store.run({
                  type: 'paste',
                  nodes: [{ id, x: (a?.x ?? 200) + 120, y: (a?.y ?? 200) + 80, role: 'compute_tile', ports: 5, clock: 'clk_core' }],
                  edges: edgeUnique(anchor, id)
                    ? [{ id: `e${Date.now() % 900000 + 100000}`, src: anchor, dst: id, width: 512, pipelineStages: 1, vcClass: 0 }]
                    : [],
                });
                if (!err) setSelNodes([id]);
              }}>node (auto-wired)</button>
              <button type="button" className="btn" disabled={selNodes.length === 0}
                onClick={() => { for (const id of selNodes) run({ type: 'delete_node', id }); setSelNodes([]); }}>delete selected</button>
              <button type="button" className="btn"
                disabled={selNodes.length === 0 && selEdges.length === 0}
                onClick={() => {
                  const ids = new Set(selNodes);
                  clip.current = {
                    nodes: doc.nodes.filter((n) => ids.has(n.id)),
                    edges: doc.edges.filter((e) => ids.has(e.src) && ids.has(e.dst)),
                  };
                }}>copy</button>
              <button type="button" className="btn" disabled={!clip.current}
                onClick={() => {
                  const c = clip.current;
                  if (!c) return;
                  const stamp = Date.now() % 9000 + 1000;
                  const map = new Map(c.nodes.map((n) => [n.id, `${n.id}-c${stamp}`]));
                  run({
                    type: 'paste',
                    nodes: c.nodes.map((n) => ({ ...n, id: map.get(n.id) ?? n.id, x: n.x + 60, y: n.y + 60 })),
                    edges: c.edges.map((e) => ({ ...e, id: `e${stamp}-${e.id}`, src: map.get(e.src) ?? e.src, dst: map.get(e.dst) ?? e.dst })),
                  });
                }}>paste</button>
            </div>
            <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              <button type="button" className="btn" onClick={() => exportProjectJson(doc)}>save project.json</button>
              <label className="btn" style={{ cursor: 'pointer' }}>load project.json
                <input type="file" accept=".json" hidden onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  try {
                    const text = await f.text();
                    parseProject(text);
                    store.loadJson(text);
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
              {doc.nodes.map((n) => (
                <button key={n.id} type="button" className="btn"
                  style={{ display: 'block', width: '100%', textAlign: 'left', marginBottom: 2 }}
                  onClick={() => { setSelNodes([n.id]); setSelEdges([]); }}>
                  <code>{n.id}</code> <span className="muted">{n.role}</span>
                </button>
              ))}
            </div>
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
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
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
                  {issues.map((i) => <li key={`${i.path}-${i.message}`}><code>{i.path}</code> — {i.message}</li>)}
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
      const lowered = graphToDraftRequest(store.doc, draftRequest);
      if (!lowered.doc) {
        setError(lowered.refused ?? 'this graph does not lower');
        return;
      }
      const saved = await api.putDraft(projectId, lowered.doc);
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

  const lowered = ir.doc ? (ir.doc.links as unknown[]).length : 0;
  const match = back && back.routers === store.doc.nodes.length
    && back.pairs === lowered;

  return (
    <div>
      <p className="muted" style={{ fontSize: 12 }}>
        Writes this graph onto project {projectId} as an explicit topology,
        keeping its workload and requirements, then compiles it.
      </p>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn" disabled={busy || !draftRequest}
          onClick={() => { void apply(false); }}>save to draft</button>
        <button type="button" className="btn" disabled={busy || !draftRequest}
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
