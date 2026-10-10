import { useEffect, useMemo, useState, type ReactElement } from 'react';
import { api } from '../api';
import { baseDocument, withBaseDocument, editableDocument } from '../canonicalDraft';
import type { DraftGeometryView } from '../api/types';
import type { WorkbenchGroup } from './DesignViewV2Editor';
import { agentLabel } from './FabricCanvas';

type Pick = { kind: 'router' | 'link' | 'wire'; id: number } | null;
type RawLink = [number, number, Record<string, unknown>?];

export default function DesignCanvas({ projectId, doc: root, onChange, onInspect }: {
  projectId: string;
  doc: Record<string, unknown>;
  onChange: (doc: Record<string, unknown>) => void;
  onInspect: (group: WorkbenchGroup, agentIndex?: number) => void;
}): ReactElement {
  const doc = baseDocument(root);
  const [preview, setPreview] = useState<DraftGeometryView | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');
  const [pick, setPick] = useState<Pick>(null);
  const [connecting, setConnecting] = useState(false);
  const [from, setFrom] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const snapshot = JSON.stringify(root);
  useEffect(() => {
    let live = true;
    setPending(true);
    setError('');
    const timer = setTimeout(() => {
      api.previewDesign(projectId, JSON.parse(snapshot) as Record<string, unknown>)
        .then((value) => { if (live) setPreview(value); })
        .catch((reason: unknown) => {
          if (live) { setPreview(null); setError(reason instanceof Error ? reason.message : String(reason)); }
        })
        .finally(() => { if (live) setPending(false); });
    }, 180);
    return () => { live = false; clearTimeout(timer); };
  }, [projectId, snapshot]);

  const topology = (doc.topology ?? {}) as Record<string, unknown>;
  const graph = (topology.graph ?? {}) as Record<string, unknown>;
  const explicit = topology.kind === 'explicit';
  const links = Array.isArray(graph.links) ? graph.links as RawLink[] : [];
  const agents = Array.isArray(doc.agents) ? doc.agents as Record<string, unknown>[] : [];
  const workload = (doc.workload ?? {}) as Record<string, unknown>;
  const requirements = Array.isArray(doc.requirements) ? doc.requirements : [];
  const points = useMemo(() => {
    const routers = preview?.topology.routers ?? [];
    const positioned = routers.every(r => r.coordinates.length >= 2)
      && new Set(routers.map(r => `${r.coordinates[0]}:${r.coordinates[1]}`)).size === routers.length;
    const columns = Math.max(1, Math.ceil(Math.sqrt(routers.length)));
    return new Map(routers.map((r, index) => [r.router_id, {
      x: 60 + (positioned ? r.coordinates[0] : index % columns) * 110,
      y: 60 + (positioned ? r.coordinates[1] : Math.floor(index / columns)) * 110,
    }]));
  }, [preview]);
  const width = Math.max(320, ...[...points.values()].map(p => p.x + 70));
  const height = Math.max(240, ...[...points.values()].map(p => p.y + 70));
  const channels = useMemo(() => {
    if (explicit) return links.map(([a, b], id) => ({ id, a, b }));
    const pairs = new Map<string, { id: number; a: number; b: number }>();
    for (const c of preview?.topology.channels ?? []) {
      const key = [c.src_router, c.dst_router].sort((a, b) => a - b).join(':');
      if (!pairs.has(key)) pairs.set(key, { id: c.channel_id, a: c.src_router, b: c.dst_router });
    }
    return [...pairs.values()];
  }, [explicit, links, preview]);
  const selectedLink = explicit && pick?.kind === 'link' ? links[pick.id] : undefined;
  const selectedRouter = pick?.kind === 'router'
    ? preview?.topology.routers.find(r => r.router_id === pick.id) : undefined;
  const selectedWire = pick?.kind === 'wire'
    ? preview?.topology.shared_links.find(w => w.shared_link_id === pick.id) : undefined;
  const updateGraph = (next: Record<string, unknown>): void =>
    onChange(editableDocument(withBaseDocument(root, { ...doc, topology: { ...topology, graph: { ...graph, ...next } } })));
  const updateLink = (key: string, value: unknown): void => {
    if (!selectedLink || pick?.kind !== 'link') return;
    const opts = { ...(selectedLink[2] ?? {}) };
    if (value === null) delete opts[key]; else opts[key] = value;
    updateGraph({ links: links.map((link, index) => index === pick.id
      ? [link[0], link[1], opts] : link) });
  };
  const chooseRouter = (id: number): void => {
    if (pending) return;
    onInspect('fabric');
    if (connecting) {
      if (from === null) { setFrom(id); return; }
      if (from !== id && !links.some(([a, b]) => (a === from && b === id) || (a === id && b === from))) {
        updateGraph({ links: [...links, [from, id]] });
      }
      setConnecting(false); setFrom(null);
    } else setPick({ kind: 'router', id });
  };
  const chooseLink = (id: number, kind: 'link' | 'wire'): void => {
    if (pending) return;
    setPick({ kind, id }); onInspect('fabric');
  };
  const nodeCount = Number(graph.nodes);
  const removeRouter = selectedRouter && explicit && selectedRouter.router_id === nodeCount - 1
    && !preview?.endpoints.some(e => e.router_id === selectedRouter.router_id);

  return <section className="design-canvas" aria-label="Draft canvas" aria-busy={pending}>
    <div className="design-canvas-objects" aria-label="Design objects">
      {agents.map((agent, index) => <button type="button" className="design-object" key={index}
        onClick={() => onInspect('system', index)}>
        <strong>{String(agent.count ?? '—')}</strong>{' '}<span>{agentLabel(String(agent.kind ?? 'Agent'))}</span>
      </button>)}
      <button type="button" className="design-object" onClick={() => onInspect('workload')}>
        <strong>TP {String(workload.tp ?? '—')}</strong>{' '}<span>Workload &amp; communication</span>
      </button>
      <button type="button" className="design-object" onClick={() => onInspect('goals')}>
        <strong>{requirements.length}</strong>{' '}<span>Requirements</span>
      </button>
    </div>
    <div className="design-canvas-toolbar">
      <button type="button" className="btn btn-small" onClick={() => onInspect('fabric')}>Topology &amp; links</button>
      {explicit && <>
        <button type="button" className="btn btn-small" disabled={pending || !preview}
          onClick={() => updateGraph({ nodes: nodeCount + 1 })}>Add router</button>
        <button type="button" className="btn btn-small" aria-pressed={connecting} disabled={pending || !preview}
          onClick={() => { setConnecting(!connecting); setFrom(null); }}>
          {connecting ? 'Cancel connection' : 'Connect routers'}
        </button>
      </>}
      <span className="design-canvas-zoom">
        <button type="button" className="btn btn-small" aria-label="Zoom out" disabled={zoom <= 0.5}
          onClick={() => setZoom(Math.max(0.5, zoom - 0.5))}>−</button>
        <button type="button" className="btn btn-small" onClick={() => setZoom(1)}>Fit</button>
        <button type="button" className="btn btn-small" aria-label="Zoom in" disabled={zoom >= 4}
          onClick={() => setZoom(Math.min(4, zoom + 0.5))}>+</button>
      </span>
    </div>
    {root.schema_version === 5 && <p className="muted">BASE_ONLY preview · V5 root and declarations retained · no extension execution or qualification</p>}
    <p className="design-canvas-caption" role="status">
      {pending ? 'Updating draft diagram…' : preview
        ? `${preview.topology.routers.length} routers · ${preview.endpoints.length} attached endpoints · ${preview.topology.routers.reduce((n, r) => n + r.seat_capacity, 0)} seats · compile checks pending`
        : 'Draft diagram unavailable. Correct the intent in the inspector.'}
    </p>
    {error && <p className="bad" role="alert">{error}</p>}
    {preview && <div className="design-canvas-viewport">
      <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Draft router diagram"
        style={{ width: `${zoom * 100}%`, height: `${360 * zoom}px` }}>
        {channels.map(({ id, a, b }) => {
          const start = points.get(a); const end = points.get(b);
          if (!start || !end) return null;
          return <g key={id} role="button" tabIndex={pending ? -1 : 0}
            aria-label={`Connection ${a} to ${b}`} aria-pressed={pick?.kind === 'link' && pick.id === id}
            onClick={() => chooseLink(id, 'link')}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chooseLink(id, 'link'); } }}>
            <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} className="design-canvas-link-hit" />
            <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} className={`design-canvas-link${pick?.kind === 'link' && pick.id === id ? ' selected' : ''}`} />
          </g>;
        })}
        {(preview.topology.shared_links ?? []).map(wire => {
          const source = points.get(wire.src_router);
          const taps = wire.taps.map(id => points.get(id)).filter(p => p !== undefined);
          if (!source || !taps.length) return null;
          const hub = { x: source.x + 30, y: source.y + 32 };
          return <g key={`wire${wire.shared_link_id}`} role="button" tabIndex={pending ? -1 : 0}
            aria-label={`Shared wire ${wire.shared_link_id} from router ${wire.src_router} to ${wire.taps.join(', ')}`}
            onClick={() => chooseLink(wire.shared_link_id, 'wire')}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chooseLink(wire.shared_link_id, 'wire'); } }}>
            {[source, ...taps].map((target, i) => <line key={i} x1={hub.x} y1={hub.y} x2={target.x} y2={target.y} className="design-canvas-wire" />)}
            <rect x={hub.x - 4} y={hub.y - 4} width={8} height={8} className="design-canvas-wire-hub" />
          </g>;
        })}
        {preview.topology.routers.map(router => {
          const point = points.get(router.router_id)!;
          const endpoints = preview.endpoints.filter(e => e.router_id === router.router_id);
          const chosen = pick?.kind === 'router' && pick.id === router.router_id || from === router.router_id;
          return <g key={router.router_id} transform={`translate(${point.x},${point.y})`} role="button"
            tabIndex={pending ? -1 : 0} aria-label={`Router ${router.router_id}, ${endpoints.length} attached endpoints, ${router.seat_capacity} seats`}
            aria-pressed={chosen} onClick={() => chooseRouter(router.router_id)}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); chooseRouter(router.router_id); } }}>
            <rect x={-32} y={-23} width={64} height={46} rx={5} className={`design-canvas-router${chosen ? ' selected' : ''}`} />
            <text textAnchor="middle" y={-3}>R{router.router_id}</text>
            <text textAnchor="middle" y={13} className="design-canvas-seat-label">{endpoints.length}/{router.seat_capacity} seats</text>
          </g>;
        })}
      </svg>
    </div>}
    <p className="muted design-canvas-help">{connecting
      ? from === null ? 'Pick the source router, then the destination.' : `Source R${from} · pick the destination.`
      : 'Select an agent group, router, or connection to inspect. Diagram layout is not physical placement.'}</p>
    {selectedRouter && <div className="design-canvas-selection">
      <strong>Router {selectedRouter.router_id}</strong>
      <span>Router controls are fabric-wide. Individual router overrides are not supported.</span>
      {removeRouter && <button type="button" className="btn btn-small" onClick={() => updateGraph({
        nodes: nodeCount - 1, links: links.filter(([a, b]) => a !== selectedRouter.router_id && b !== selectedRouter.router_id),
      })}>Remove unused router</button>}
    </div>}
    {selectedWire && <p className="design-canvas-selection">Shared wire {selectedWire.shared_link_id}: R{selectedWire.src_router} → {selectedWire.taps.map(id => `R${id}`).join(', ')} · {selectedWire.width_bits}-bit · width follows fabric settings.</p>}
    {pick?.kind === 'link' && !explicit && <p className="design-canvas-selection">This connection follows the topology. Edit dimensions and global link settings in Fabric; arbitrary connections require an explicit topology.</p>}
    {selectedLink && <div className="design-canvas-selection">
      <strong>Connection R{selectedLink[0]} → R{selectedLink[1]}</strong>
      <div className="form-grid">
        {(['bandwidth_GBs', 'latency_ns'] as const).map(key => <label className="field" key={key}>
          <span className="field-label">{key === 'bandwidth_GBs' ? 'Bandwidth (GB/s)' : 'Latency (ns)'}</span>
          <input type="number" step="any" value={selectedLink[2]?.[key] == null ? '' : String(selectedLink[2][key])}
            onChange={e => updateLink(key, e.target.value === '' ? null : Number(e.target.value))} />
        </label>)}
        <label className="field"><span className="field-label">Directed connection</span>
          <input type="checkbox" checked={selectedLink[2]?.directed === true}
            onChange={e => updateLink('directed', e.target.checked)} /></label>
      </div>
      <p className="muted">These are authored link attributes. Compile and backend qualification check support; widths and VC assignments are not per-link overrides.</p>
      <button type="button" className="btn btn-small" onClick={() => {
        updateGraph({ links: links.filter((_, index) => index !== pick!.id) }); setPick(null);
      }}>Remove connection</button>
    </div>}
  </section>;
}
