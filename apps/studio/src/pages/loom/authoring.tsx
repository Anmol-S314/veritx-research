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
import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import { useAsync, ErrorBox, JobProgress, Link, type Async } from '../../studio';
import { useCompileJob } from '../../hooks/useCompileJob';
import { api, ApiError } from '../../api';
import type { FabricPresetCatalogEntry } from '../../api/types';
import type { TopologyView } from '../../types';
import { graphToDraft, graphToDraftRequest, graphToTopologyIR, presetGraphToProject } from '../../graph/adapter';
import type { GraphCommand } from '../../graph/history';
import { download, exportSvgPng, nodesToCsv, csvToNodePatches } from '../../graph/io';
import { PRESETS } from '../../graph/presets';
import { parseProject, serializeProject, validateProject } from '../../graph/project';
import { manhattan, pathFor } from '../../graph/routing';
import { useGraphStore, type GraphStore } from '../../graph/store';
import { buildMockTrace, topCongested } from '../../graph/trace';

export function useAuthoring(projectId: string): GraphStore {
  return useGraphStore('mesh-8x8', projectId);
}

function Verdict({ store }: { store: GraphStore }): ReactElement {
  const issues = useMemo(() => validateProject(store.doc), [store.doc]);
  if (issues.length > 0) {
    return (
      <p className="t-bad" role="alert">
        ✗ {issues.length} issue(s): {issues.slice(0, 2).map((i) => `${i.path} ${i.message}`).join(' · ')}
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

/** P0: preset seed, validate, save/load project.json, lowering
 * preview, and apply-to-draft → compile against the live gateway. */
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
  const adapted = useMemo(() => graphToDraft(store.doc), [store.doc]);
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
      const issues = validateProject(out.doc);
      if (issues.length) {
        setError(`seeded graph invalid: ${issues.slice(0, 2).map((i) => `${i.path} ${i.message}`).join(' · ')}`);
        return;
      }
      const err = store.loadJson(JSON.stringify(out.doc));
      if (err) { setError(err); return; }
      setApplyState(`✓ seeded from ${g.preset_id} (${g.generation}, ${g.family}, ${g.routers.length} routers) · design ${(g.design_hash ?? '').slice(0, 18)}…`);
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
      const lowered = graphToDraftRequest(store.doc, draftRequest);
      if (!lowered.doc) {
        setError(lowered.refused ?? 'lowering refused');
        return;
      }
      const saved = await api.putDraft(projectId, lowered.doc);
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
        This local graph is not read back from the project's server draft or compiled revision. Nothing changes remotely until Apply; applying replaces the draft with this graph's supported lowering.
      </p>
      {adapted.refused
        ? <p className="t-warn">● lowering refused: {adapted.refused}</p>
        : (
          <p className="muted">
            lowering preview: explicit custom → {ir.doc ? (ir.doc.links as unknown[]).length : 0} links
            {' · '}{(adapted.doc?.agents as unknown[] | undefined)?.length ?? 0} agent groups
            {ir.doc ? ` · uniform edge width ${ir.linkWidthBits} bits → ${String((ir.doc.link_attrs as Record<string, unknown>).bandwidth_GBs)} GB/s at 1 GHz` : ''}
            {' · '}compiler scope is connectivity + uniform width + role/count/clock; interface defaults are AXI/256/64. IDs, canvas positions, and port limits stay in project.json
            {' · '}pipelineStages beyond 1, nonzero vcClass, VC, firewall, or graph workload intent refuse lowering
            {' · '}any edit diverges the preset to custom
          </p>
        )}
      {projectId && draftRequest && (
        <div className="row" style={{ gap: 8, marginTop: 8 }}>
          <button type="button" className="btn" disabled={applying || !!adapted.refused}
            onClick={() => { void apply(false); }}>
            {applying ? 'Applying…' : 'Apply graph to draft'}
          </button>
          <button type="button" className="btn" disabled={applying || compileJob.active || !!adapted.refused}
            onClick={() => { void apply(true); }}>
            {applying ? 'Working…' : 'Apply + compile'}
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
          try { download('project.json', serializeProject(store.doc)); setError(null); }
          catch (e) { setError(e instanceof Error ? e.message : String(e)); }
        }}>Save project.json</button>
        <label className="btn" style={{ cursor: 'pointer' }}>Load project.json
          <input type="file" accept=".json" hidden onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            try {
              const text = await f.text();
              parseProject(text);
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
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [src, setSrc] = useState('');
  const [dst, setDst] = useState('');
  const clip = useRef<{ nodes: { id: string; x: number; y: number; role: string; ports: number }[]; edges: { src: string; dst: string }[] } | null>(null);
  const byId = new Map(store.doc.nodes.map((n) => [n.id, n]));
  const run = (c: GraphCommand): void => { store.run(c); };
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
  const box = `${minX - pad} ${minY - pad} ${maxX - minX + pad * 2} ${maxY - minY + pad * 2}`;

  const addNode = (): void => {
    // A lone node fails connectivity validation, so a new node arrives
    // already wired to the selected node (or the first one) in one command.
    const anchor = (sel && byId.get(sel)) ? sel : store.doc.nodes[0]?.id;
    if (!anchor) return;
    const a = byId.get(anchor);
    const id = `n${Date.now() % 90000 + 10000}`;
    const err = store.run({
      type: 'paste',
      nodes: [{ id, x: (a?.x ?? 400) + 120, y: (a?.y ?? 300) + 60, role: 'compute_tile', ports: 5, clock: 'clk_core' }],
      edges: [{ id: `e${Date.now() % 900000 + 100000}`, src: anchor, dst: id, width: 512, pipelineStages: 1, vcClass: 0 }],
    });
    if (!err) { setSel(id); setSrc(id); }
  };

  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button type="button" className="btn" onClick={addNode}>+ node (wired)</button>
        <button type="button" className="btn" disabled={!sel} onClick={() => {
          const n = byId.get(sel ?? '');
          if (n) { clip.current = { nodes: [{ id: n.id, x: n.x, y: n.y, role: n.role, ports: n.ports }], edges: [] }; }
        }}>Copy</button>
        <button type="button" className="btn" disabled={!clip.current} onClick={() => {
          const c = clip.current;
          if (!c) return;
          const stamp = Date.now() % 9000 + 1000;
          const idMap = new Map(c.nodes.map((n) => [n.id, `${n.id}-c${stamp}`]));
          run({
            type: 'paste',
            nodes: c.nodes.map((n) => ({ id: idMap.get(n.id) ?? n.id, x: n.x + 60, y: n.y + 60, role: n.role, ports: n.ports, clock: 'clk_core' })),
            edges: [],
          });
        }}>Paste</button>
        <button type="button" className="btn" disabled={!sel} onClick={() => { if (sel) { run({ type: 'delete_node', id: sel }); setSel(null); } }}>Delete</button>
      </div>
      <svg data-testid="authoring-canvas" width="100%" height={300} viewBox={box}
        onMouseMove={(ev) => {
          if (!dragging) return;
          const r = ev.currentTarget.getBoundingClientRect();
          const vb = box.split(' ').map(Number);
          const sx = (vb[2] || 1) / Math.max(1, r.width);
          const sy = (vb[3] || 1) / Math.max(1, r.height);
          run({ type: 'move_node', id: dragging, x: Math.round((ev.clientX - r.left) * sx), y: Math.round((ev.clientY - r.top) * sy) });
        }}
        onMouseUp={() => setDragging(null)}
        onMouseLeave={() => setDragging(null)}
        style={{ background: 'var(--bg-raise)', border: '1px solid var(--border)', borderRadius: 8 }}>
        {store.doc.edges.map((e) => {
          const a = byId.get(e.src);
          const b = byId.get(e.dst);
          if (!a || !b) return null;
          return (
            <g key={e.id}>
              {/* fat invisible hit area so a thin link is still clickable */}
              <path d={pathFor(manhattan({ x: a.x, y: a.y }, { x: b.x, y: b.y }))}
                fill="none" stroke="transparent" strokeWidth={14} style={{ cursor: 'pointer' }}
                onClick={(ev) => { ev.stopPropagation(); setSelEdge(e.id); setSel(null); }}
                data-testid={`edge-hit-${e.id}`} />
              <path d={pathFor(manhattan({ x: a.x, y: a.y }, { x: b.x, y: b.y }))}
                fill="none"
                stroke={selEdge === e.id ? 'var(--warn, #d9a441)' : 'var(--accent)'}
                strokeWidth={selEdge === e.id ? 6 : 3} opacity={0.85} />
            </g>
          );
        })}
        {store.doc.nodes.map((n) => {
          const select = (): void => { setSel(n.id); setSrc(n.id); };
          return (
          <g key={n.id} transform={`translate(${n.x},${n.y})`} role="button" tabIndex={0}
            aria-label={`${n.id} ${n.role}`} aria-pressed={sel === n.id}
            onClick={select} onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); }
            }} style={{ cursor: 'pointer' }}>
            <rect x={-34} y={-20} width={68} height={40} rx={6}
              fill={sel === n.id ? 'var(--accent-dim)' : 'var(--bg-card)'}
              stroke={sel === n.id ? 'var(--accent)' : 'var(--border)'} strokeWidth={sel === n.id ? 2 : 1} />
            <text textAnchor="middle" y={-1} fontSize={11} fill="var(--text)" fontFamily="monospace">{n.id.slice(0, 9)}</text>
            <text textAnchor="middle" y={13} fontSize={9} fill="var(--muted)" fontFamily="monospace">{n.role.slice(0, 10)}</text>
          </g>
          );
        })}
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
              {['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU'].map((r) => <option key={r}>{r}</option>)}
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
            store.run({ type: 'add_edge', edge: { id: `e${Date.now() % 900000 + 100000}`, src, dst, width: 512, pipelineStages: 1, vcClass: 0 } });
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
              {['compute_tile', 'hbm_controller', 'nic', 'peripheral', 'ucie_port', 'NPU'].map((r) => <option key={r}>{r}</option>)}
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
  const [expanded, setExpanded] = useState(false);
  const cap = expanded ? 24 : 12;
  const vis = ids.slice(0, cap);
  const saved = (store.doc.firewall?.rules as { src: string; dst: string; perm: string }[] | undefined) ?? [];
  const cellOf = (a: string, b: string): Cell => {
    const r = saved.find((x) => x.src === a && x.dst === b);
    return r?.perm === 'RW' ? 'RW' : r?.perm === 'RO' ? 'RO' : 'none';
  };
  const write = (rules: { src: string; dst: string; perm: string }[]): void => {
    store.run({ type: 'set_firewall', firewall: { default: 'deny', rules } });
  };
  const cycle = (a: string, b: string): void => {
    const cur = cellOf(a, b);
    const next = cur === 'none' ? 'RO' : cur === 'RO' ? 'RW' : 'none';
    const rules = saved.filter((x) => !(x.src === a && x.dst === b));
    if (next !== 'none') rules.push({ src: a, dst: b, perm: next });
    write(rules);
  };
  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button type="button" className="btn" onClick={() => write([])}>Deny by default</button>
        <button type="button" className="btn" onClick={() => {
          const rules: { src: string; dst: string; perm: string }[] = [];
          for (const a of vis) for (const b of vis) if (a !== b) rules.push({ src: a, dst: b, perm: 'RW' });
          write(rules);
        }}>Allow all (visible)</button>
        {ids.length > cap && (
          <button type="button" className="btn" onClick={() => setExpanded((s) => !s)}>
            {expanded ? 'Collapse' : `Expand (${ids.length} nodes)`}
          </button>
        )}
        <span className="muted">{saved.length} rules · default deny · keyed on node id</span>
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
                    aria-label={`${a} to ${b}: ${cellOf(a, b)}`} onClick={() => cycle(a, b)}>
                    {cellOf(a, b)}
                  </button>
                )
            ))}
          </>
        ))}
      </div>
      <p className="muted">Cells cycle none → RO → RW → none. Quadratic sizing: the grid caps at {cap} nodes per side.</p>
    </div>
  );
}

interface Phase { id: string; kind: string; tokens: number; batch: number; tp: number; ep: number; pp: number; dp: number }
interface WorkloadDoc { modelFamily: string; paramsB: number; seqLen: number; batch: number; precision: string; phases: Phase[] }

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

/** P5: phase editor writing workload.phases[] — this view and playback read it. */
export function WorkloadEditor({ store }: { store: GraphStore }): ReactElement {
  const w = readWorkload(store);
  if (!w) {
    return (
      <div>
        <p className="muted">No workload block on the graph yet. Cycles live in workload.phases[], never hardcoded in views.</p>
        <button type="button" className="btn" onClick={() => store.run({ type: 'set_workload', workload: STARTER as unknown as { [key: string]: import('../../graph/project').JsonValue } })}>Load starter (dense-47B TP8/EP8)</button>
      </div>
    );
  }
  const need = Math.max(0, ...w.phases.map((p) => p.tp * p.ep * p.pp * p.dp));
  const set = (patch: Partial<WorkloadDoc>): void => {
    store.run({ type: 'set_workload', workload: { ...w, ...patch } as unknown as { [key: string]: import('../../graph/project').JsonValue } });
  };
  return (
    <div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <label>Model <input aria-label="model family" value={w.modelFamily} onChange={(e) => set({ modelFamily: e.target.value })} /></label>
        <label>Seq <input aria-label="seq len" type="number" value={w.seqLen} style={{ width: 90 }} onChange={(e) => set({ seqLen: Number(e.target.value) | 0 })} /></label>
        <label>Batch <input aria-label="batch" type="number" value={w.batch} style={{ width: 70 }} onChange={(e) => set({ batch: Number(e.target.value) | 0 })} /></label>
        <label>Precision
          <select aria-label="precision" value={w.precision} onChange={(e) => set({ precision: e.target.value })}>
            <option>fp16</option><option>fp8</option><option>int8</option><option>bf16</option>
          </select>
        </label>
      </div>
      {need > store.doc.nodes.length
        ? <p className="t-warn" role="alert">● parallelism needs {need} nodes but the graph has {store.doc.nodes.length}</p>
        : <p className="t-ok">✓ {w.phases.length} phases fit the {store.doc.nodes.length}-node graph</p>}
      <div>
        {w.phases.map((p, i) => (
          <div className="row" key={p.id} style={{ gap: 8, padding: '4px 0', borderTop: '1px solid var(--border)' }}>
            <code>{p.id}</code>
            <select aria-label={`kind ${p.id}`} value={p.kind} onChange={(e) => {
              const phases = w.phases.slice();
              phases[i] = { ...p, kind: e.target.value };
              set({ phases });
            }}>
              {['prefill', 'decode', 'allreduce', 'alltoall', 'memo'].map((k) => <option key={k}>{k}</option>)}
            </select>
            {(['tp', 'ep', 'pp', 'dp'] as const).map((k) => (
              <label key={k}>{k.toUpperCase()} <input aria-label={`${k} ${p.id}`} type="number" min={1} value={p[k]} style={{ width: 56 }} onChange={(e) => {
                const phases = w.phases.slice();
                phases[i] = { ...p, [k]: Math.max(1, Number(e.target.value) | 0) };
                set({ phases });
              }} /></label>
            ))}
            <button type="button" className="btn" onClick={() => set({ phases: w.phases.filter((x) => x.id !== p.id) })}>Remove</button>
          </div>
        ))}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <button type="button" className="btn" onClick={() => set({
          phases: [...w.phases, { id: `ph-${Date.now() % 90000 + 10000}`, kind: 'decode', tokens: 512, batch: w.batch, tp: 1, ep: 1, pp: 1, dp: 1 }],
        })}>+ Phase</button>
        <button type="button" className="btn" onClick={() => store.run({ type: 'set_workload', workload: undefined })}>Clear</button>
      </div>
    </div>
  );
}

/** P6: mock-trace playback keyed on node_id/edge_id. Mock-labelled, never measured. */
export function SimPlayback({ store }: { store: GraphStore }): ReactElement {
  const w = readWorkload(store);
  const phases = w && w.phases.length ? w.phases.map((p) => p.kind) : ['prefill', 'decode'];
  const trace = useMemo(() => buildMockTrace(store.doc, phases), [store.doc, w]);
  const [frame, setFrame] = useState(0);
  const [metric, setMetric] = useState<'utilization' | 'stalls'>('utilization');
  const [timer, setTimer] = useState<ReturnType<typeof setInterval> | null>(null);
  const f = trace.frames[Math.min(frame, trace.frames.length - 1)];
  const top = topCongested(trace, frame, 5);
  const maxUtil = Math.max(1, ...Object.values(f?.edgeUtil ?? { x: 1 }));

  const toggle = (): void => {
    if (timer) { clearInterval(timer); setTimer(null); return; }
    const t = setInterval(() => setFrame((fr) => {
      if (fr + 1 >= trace.frames.length) { clearInterval(t); setTimer(null); return fr; }
      return fr + 1;
    }), 250);
    setTimer(t);
  };

  return (
    <div>
      <p className="muted"><strong>MOCK trace</strong> — playback geometry only. Queue latency, router power and buffer figures have no per-cycle artifact behind them and are not shown.</p>
      <div className="row" style={{ gap: 8, margin: '8px 0' }}>
        <button type="button" className="btn" onClick={toggle}>{timer ? 'Pause' : 'Play'}</button>
        <input aria-label="scrub" type="range" min={0} max={trace.frames.length - 1} value={frame}
          onChange={(e) => setFrame(Number(e.target.value))} style={{ flex: 1 }} />
        <span className="muted">cycle {f?.cycle} · phase <code>{f?.phase}</code> ({frame + 1}/{trace.frames.length})</span>
        <select aria-label="metric" value={metric} onChange={(e) => setMetric(e.target.value as typeof metric)}>
          <option value="utilization">utilization</option>
          <option value="stalls">stalls</option>
        </select>
      </div>
      <svg width="100%" height={220} style={{ background: 'var(--bg-raise)', border: '1px solid var(--border)', borderRadius: 8 }}>
        {store.doc.edges.slice(0, 16).map((e, i) => {
          const v = metric === 'stalls' ? (f?.stalls[e.id] ?? 0) : (f?.edgeUtil[e.id] ?? 0);
          const h = metric === 'stalls' ? Math.min(180, v * 8) : (v / maxUtil) * 180;
          return (
            <g key={e.id} transform={`translate(${50 + i * 60},200)`}>
              <rect x={-20} y={-h} width={40} height={h} fill={v > 55 ? '#e0655a' : 'var(--accent)'} opacity={0.85}>
                <title>{e.id}: {v}%</title>
              </rect>
              <text textAnchor="middle" y={14} fontSize={9} fill="var(--muted)" fontFamily="monospace">{e.id.slice(0, 7)}</text>
            </g>
          );
        })}
      </svg>
      {store.doc.edges.length > 16 && <p className="muted">bars capped at 16 edges; the list below ranks all {store.doc.edges.length}.</p>}
      <p><strong>Top congested</strong></p>
      <div>
        {top.map((t) => (
          <div className="row" key={t.edge} style={{ gap: 12 }}>
            <code>{t.edge}</code><span>util {t.util}%</span><span>stalls {f?.stalls[t.edge] ?? 0}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** P4: abstract tile projection. No die, PDK, STA or power model behind it. */
export function FloorplanPreview({ store }: { store: GraphStore }): ReactElement {
  const [heat, setHeat] = useState(true);
  const ref = useRef<SVGSVGElement>(null);
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
