import { useState, type ReactElement, type ReactNode } from 'react';
import { Link } from '../../studio';
import FabricCanvas, { OVERLAYS } from '../../components/FabricCanvas';
import FabricInspector, { type FabricSelection } from '../../components/FabricInspector';
import { fabricModel } from '../../fabricLayout';
import { Hash } from '../../components/badges';
import { compileSummary, type LoomData } from './data';
import type { DraftStore } from './draftStore';
import {
  agentId, channelId, isGraphId, loomIdText, nodeId, pickId, selectionIds,
  type GraphId, type LoomId,
} from './selection';
import type { LoomSelectionStore } from './selectionStore';
import {
  ExtensionPoint, From, Kv, Panes, PlaneCard, RailSection, SummaryStrip,
} from './parts';

type PlaneId = 'data' | 'telemetry' | 'config';

const PLANES: { id: PlaneId; label: string; detail: string; needs: string }[] = [
  {
    id: 'data',
    label: 'Data plane',
    detail: 'certified structure — routers, channels, attachments',
    needs: '',
  },
  {
    id: 'telemetry',
    label: 'Telemetry plane',
    detail: '32-bit diagnostic tree',
    needs: 'a telemetry-plane topology artifact (regional hubs, trace sink) emitted by the compiler; the frozen views carry one fabric graph',
  },
  {
    id: 'config',
    label: 'Config plane',
    detail: '32-bit configuration fabric',
    needs: 'a configuration-plane topology artifact (config ingress/egress and its ordering) emitted by the compiler',
  },
];

/** The canvas's own pick vocabulary is the canvas's; these are the canonical
 *  ids. A router or a channel is a vertex or an edge of the certified graph and
 *  accumulates, while an endpoint is one declared agent instance and replaces
 *  the set — an agent instance is a record, not a graph element. */
function loomIdFor(
  pick: FabricSelection,
  endpoints: { endpoint_id: number; group_index: number; instance_index: number }[],
): LoomId | null {
  if (pick.kind === 'router' && pick.routerId !== undefined) {
    return nodeId(pick.routerId);
  }
  if (pick.kind === 'channel' && pick.channelId !== undefined) {
    return channelId(pick.channelId);
  }
  if (pick.kind === 'endpoint' && pick.endpointId !== undefined) {
    const seat = endpoints.find((e) => e.endpoint_id === pick.endpointId);
    return seat ? agentId(seat.group_index, seat.instance_index) : null;
  }
  return null;
}

function fabricSelectionFor(
  id: LoomId,
  endpoints: { endpoint_id: number; group_index: number; instance_index: number }[],
): FabricSelection | null {
  if (id.kind === 'node') return { kind: 'router', routerId: id.routerId };
  if (id.kind === 'channel') return { kind: 'channel', channelId: id.channelId };
  if (id.kind !== 'agent') return null;
  const seat = endpoints.find(
    (e) => e.group_index === id.groupIndex && e.instance_index === id.instanceIndex,
  );
  return seat ? { kind: 'endpoint', endpointId: seat.endpoint_id } : null;
}

export default function TopologyLoom({ data, sel, draftStore, problems }: {
  data: LoomData;
  sel: LoomSelectionStore;
  draftStore: DraftStore;
  problems?: ReactNode;
}): ReactElement {
  const [plane, setPlane] = useState<PlaneId>('data');

  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data
    : null;
  const design = data.design;
  const active = PLANES.find((p) => p.id === plane) ?? PLANES[0];
  const g = design?.noc_guided ?? null;
  const locked = design?.locked_derived ?? null;
  const draftDoc = draftStore.doc ?? data.draftRequest;
  const draftNoc = draftDoc?.noc_config && typeof draftDoc.noc_config === 'object'
    && !Array.isArray(draftDoc.noc_config)
    ? draftDoc.noc_config as Record<string, unknown> : null;
  const draftTopology = draftDoc?.topology && typeof draftDoc.topology === 'object'
    && !Array.isArray(draftDoc.topology)
    ? draftDoc.topology as Record<string, unknown> : null;
  const authoredFamily = typeof draftNoc?.topology_family === 'string'
    ? draftNoc.topology_family
    : typeof draftTopology?.kind === 'string' ? draftTopology.kind
      : g?.topology_family ?? '—';
  const linkWidth = topology?.channels[0]?.width_bits ?? g?.link_width ?? null;

  const model = design && topology ? fabricModel(design, topology) : null;
  const unavailable = OVERLAYS.filter((o) => o.id !== 'structure');
  const summary = compileSummary(data);
  const decl = summary?.declared ?? {};
  const der = summary?.derived ?? {};
  const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);
  const txt = (v: unknown): string | null => (typeof v === 'string' ? v : null);
  const authoredRadix = typeof draftNoc?.radix === 'number'
    ? draftNoc.radix
    : typeof draftTopology?.side_length === 'number'
      ? draftTopology.side_length
      : draftNoc ? 'compiler default' : num(decl.side_length) ?? g?.radix ?? '—';
  const authoredConcentration = typeof draftNoc?.concentration === 'number'
    ? draftNoc.concentration
    : typeof draftTopology?.concentration === 'number'
      ? draftTopology.concentration
      : draftNoc ? 'compiler default'
        : num(decl.concentration) ?? g?.concentration ?? '—';
  const routeClasses = Array.isArray(der.routing_classes)
    ? (der.routing_classes as unknown[]).filter((c): c is string => typeof c === 'string')
    : null;
  const certificate = locked?.certificate_overall
    ?? txt(summary?.certificate_overall)
    ?? null;

  const seats = topology?.endpoints ?? [];
  const held = selectionIds(sel.selection);
  const graphHeld = held.filter(isGraphId);
  // An endpoint chip is a seat on the certified attachment, so the seat facts
  // are read here rather than left for the tab that keeps the full record.
  const chosenAgent = pickId(sel.selection, 'agent');
  const seat = chosenAgent
    ? seats.find((e) => (
      e.group_index === chosenAgent.groupIndex
      && e.instance_index === chosenAgent.instanceIndex
    )) ?? null
    : null;
  // The canvas draws whatever the workspace holds, including the seat an agent
  // selection names — otherwise clicking an endpoint would move the highlight
  // off the thing that was clicked.
  const canvasHeld = [...graphHeld, ...(chosenAgent ? [chosenAgent] : [])]
    .map((id) => fabricSelectionFor(id, seats))
    .filter((s): s is FabricSelection => s !== null);

  const onCanvasSelect = (pick: FabricSelection | null, additive: boolean): void => {
    if (!pick) {
      sel.clear();
      return;
    }
    const id = loomIdFor(pick, seats);
    if (!id) return;
    sel.choose(id, additive);
  };

  const isolate = (id: GraphId): void => {
    sel.select(id);
  };

  const stage = ((): ReactElement => {
    if (!data.revisionId) {
      return (
        <ExtensionPoint
          title="No compiled revision on this project"
          needs="a compiled revision. The draft is intent only — no topology, routing or certificate exists to draw."
        />
      );
    }
    if (data.topology.result.state === 'loading') {
      return <p className="muted" role="status">materializing topology…</p>;
    }
    if (data.topology.result.state === 'error') {
      return (
        <div className="verdict-banner verdict-unsupported" role="alert">
          <span className="verdict-text">
            <strong>Fabric not materialized.</strong>{' '}
            {data.topology.result.error.message} Nothing is drawn for this
            revision.
          </span>
        </div>
      );
    }
    if (plane !== 'data') {
      return (
        <ExtensionPoint
          title={`${active.label} — ${active.detail}`}
          needs={active.needs}
        />
      );
    }
    if (!design || !model) {
      return <ExtensionPoint title="Draft unreadable" needs="a draft with agents and noc_config blocks" />;
    }
    return (
      <>
        <FabricCanvas
          model={model}
          topology={topology}
          selection={canvasHeld}
          onSelect={onCanvasSelect}
        />
      </>
    );
  })();

  return (
    <Panes
      left={
        <>
          <RailSection title="Datapath planes">
            <div className="loom-plane-list">
              {PLANES.map((p) => (
                <PlaneCard
                  key={p.id}
                  id={p.id}
                  label={p.label}
                  detail={p.id === 'data' && linkWidth != null && topology
                    ? `${linkWidth}-bit · ${topology.counts.channels} directed channels`
                    : p.detail}
                  active={plane === p.id}
                  onSelect={() => setPlane(p.id)}
                  available={p.id === 'data'}
                />
              ))}
            </div>
          </RailSection>

          <RailSection title="Authored fabric parameters">
            <From
              origin="AUTHORED"
              artifact="draft"
              note="what the draft says; the compiler may still refuse it"
              data={data}
            />
            <TopologyEditor data={data} store={draftStore} />
            <Kv label="family" value={<code>{authoredFamily}</code>} />
            <Kv label="radix / side" value={authoredRadix} mono />
            <Kv label="concentration" value={authoredConcentration} mono />
            <Kv label="link width" value={linkWidth != null ? `${linkWidth} bits` : '—'} mono />
            <Kv label="arbitration" value={<code>{txt(decl.arbitration) ?? g?.arbitration ?? '—'}</code>} />
            <Kv label="turn restrictions" value={
              locked?.turn_restrictions?.length
                ? locked.turn_restrictions.join(', ')
                : '—'
            } />
          </RailSection>

          <RailSection title="Derived fabric parameters">
            <From
              origin="DERIVED"
              artifact="compile_result"
              note="what the compiler produced; read the row, not the draft"
              data={data}
            />
            <Kv label="routing classes" value={
              <code>{locked?.routing ?? routeClasses?.join(', ') ?? '—'}</code>
            } />
            <Kv label="VC count" value={num(der.vc_count) ?? locked?.vc_count ?? '—'} mono />
            <Kv label="certificate" value={
              certificate ? (
                <span className={`status status-${certificate === 'PASS' ? 'ok' : 'bad'}`}>
                  {certificate}
                </span>
              ) : '—'
            } />
            {data.compileResult.result.state === 'error' && (
              <p className="bad" role="alert">
                Compile summary unreadable: {data.compileResult.result.error.message}. Derived rows above fall back to draft intent — the revision's own numbers are not shown.
              </p>
            )}
          </RailSection>

          <RailSection title="Materialization counts">
            <From
              origin="DERIVED"
              artifact="topology"
              data={data}
            />
            <Kv label="routers" value={topology?.counts.routers ?? '—'} mono />
            <Kv label="directed channels" value={topology?.counts.channels ?? '—'} mono />
            <Kv label="physical links" value={topology?.physical_links.length ?? '—'} mono />
            <Kv label="endpoints / seats" value={
              topology ? `${topology.counts.endpoints} / ${topology.counts.seats}` : '—'
            } mono />
          </RailSection>

          <RailSection
            title="Unavailable overlays"
            note="Studio draws a colored overlay only from its backing artifact."
          >
            <ul className="loom-needs">
              {unavailable.map((o) => (
                <li key={o.id}>
                  <b>{o.label}</b> — requires {o.needs}
                </li>
              ))}
            </ul>
          </RailSection>
        </>
      }
      stage={
        <div className="loom-view">
          <SummaryStrip items={[
            {
              k: 'Active plane',
              v: `${active.label}${plane === 'data' && linkWidth != null ? ` (${linkWidth}-bit)` : ''}`,
              tone: 'info',
            },
            { k: 'Materialization', v: topology ? 'CERTIFIED TOPOLOGYVIEW' : (data.revisionId ? 'PENDING' : 'NONE'), tone: topology ? 'ok' : 'warn' },
            { k: 'Endpoints', v: topology ? `${topology.counts.endpoints}` : '—', },
            { k: 'Draft', v: data.dirty ? 'UNCOMPILED CHANGES' : 'in sync', tone: data.dirty ? 'warn' : undefined },
          ]} />
          {stage}
          {plane === 'data' && (
            <div className="loom-hint">
              Click a router or a link to inspect it; a modifier click holds
              several at once, which is the only way to ask a question about a
              set of graph objects. Selection never writes back to the design.
            </div>
          )}
        </div>
      }
      right={
        <>
          <RailSection
            title={graphHeld.length > 1 ? 'Artifact inspector — graph set' : 'Artifact inspector'}
          >
            <From
              origin="DERIVED"
              artifact="topology"
              data={data}
            />
            {topology && graphHeld.length === 1 && (
              <FabricInspector
                topology={topology}
                selection={canvasHeld.length === 1 ? canvasHeld[0] : null}
                onClose={() => sel.clear()}
              />
            )}
            {topology && graphHeld.length > 1 && (
              <>
                <p className="loom-note">
                  {graphHeld.length} graph objects are held. Each is inspected on
                  its own below; nothing is combined into a figure, because no
                  artifact aggregates a set of routers or channels.
                </p>
                <ul className="loom-sel-list">
                  {graphHeld.map((id) => {
                    const pick = fabricSelectionFor(id, seats);
                    return (
                      <li key={loomIdText(id)}>
                        <button
                          type="button"
                          className="loom-chip"
                          onClick={() => isolate(id)}
                        >
                          show only {loomIdText(id)}
                        </button>
                        {pick && (
                          <FabricInspector
                            topology={topology}
                            selection={pick}
                            onClose={() => isolate(id)}
                          />
                        )}
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
            {topology && graphHeld.length === 0 && chosenAgent && (
              <>
                <From
                  origin="DERIVED"
                  artifact="attachment"
                  data={data}
                />
                <Kv label="agent" value={
                  <code>{`agent_group[${chosenAgent.groupIndex}]/…[${chosenAgent.instanceIndex}]`}</code>
                } />
                {seat ? (
                  <>
                    <Kv label="endpoint id" value={String(seat.endpoint_id)} mono />
                    <Kv label="kind" value={seat.kind} />
                    <Kv
                      label="seated at"
                      value={<span>router <code>R{seat.router_id}</code>, port {seat.port_id}</span>}
                      mono
                    />
                  </>
                ) : (
                  <p className="warn">
                    No certified seat for group {chosenAgent.groupIndex} instance
                    {' '}{chosenAgent.instanceIndex}. The declaration stands and
                    the seat does not; that is an attachment finding, not an
                    empty inspector.
                  </p>
                )}
                <Link className="link" to={sel.href('agents')}>
                  The full record in the agent matrix →
                </Link>
              </>
            )}
            {topology && graphHeld.length === 0 && !chosenAgent && held.length > 0 && (
              <p className="muted">
                Nothing in the graph is selected. The selection bar above carries
                {` ${held.length} record id(s) this tab does not inspect.`}
              </p>
            )}
            {!topology && (
              <p className="muted">
                No certified topology on this revision, so there is nothing to
                inspect. Intent-only routers are not evidence.
              </p>
            )}
            {topology && held.length === 0 && (
              <p className="muted">
                Nothing selected. Every field shown here is read from the
                TopologyView the revision was verified against.
              </p>
            )}
          </RailSection>

          <RailSection title="Identities">
            <From
              origin="DERIVED"
              artifact="certificate"
              note="hashes the revision was verified against"
              data={data}
            />
            <Kv label="design" value={<Hash value={data.designHash} />} />
            <Kv label="topology" value={<Hash value={topology?.topology_hash ?? null} />} />
            <Kv label="attachment" value={<Hash value={topology?.attachment_hash ?? null} />} />
            <Kv label="revision" value={<code>{data.revisionId ?? '—'}</code>} />
          </RailSection>

          {problems}
        </>
      }
    />
  );
}

function TopologyEditor({ data, store }: {
  data: LoomData;
  store: DraftStore;
}): ReactElement {
  const [refusal, setRefusal] = useState<string | null>(null);
  const doc = store.doc ?? data.draftRequest;
  const raw = doc?.noc_config;
  const config = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : null;
  const family = config?.topology_family;
  const supported = (doc?.schema_version === 2 || doc?.schema_version === 3)
    && ['mesh', 'concentrated_mesh', 'torus'].includes(String(family))
    && config !== null;

  if (!doc) return <p className="muted">Load a draft to edit topology.</p>;
  if (!supported || !config) {
    return (
      <p className="muted">
        Topology editing is limited to declared mesh-like v2/v3 parameters;
        this draft’s topology semantics are not rewritten here.
      </p>
    );
  }

  const edit = (field: 'radix' | 'concentration', rawValue: string): void => {
    const value = rawValue === '' ? null : Number(rawValue);
    const result = store.run({ type: 'set_topology_field', field, value });
    setRefusal(result.refused);
  };
  const numberValue = (field: 'radix' | 'concentration'): string =>
    typeof config[field] === 'number' ? String(config[field]) : '';
  const save = async (): Promise<void> => {
    if (await store.save()) data.reloadDraft();
  };

  return (
    <div className="loom-editor" role="group" aria-label="Edit draft topology">
      <p className="loom-note">
        Authored v2/v3 mesh parameters. Save validates the draft; compile mints
        a new revision. Blank restores the compiler default.
      </p>
      <label className="loom-field">
        <span>radix / side length</span>
        <input type="number" min={1} step={1} value={numberValue('radix')}
          onChange={(e) => edit('radix', e.target.value)} />
      </label>
      <label className="loom-field">
        <span>concentration</span>
        <input type="number" min={1} step={1}
          value={numberValue('concentration')}
          onChange={(e) => edit('concentration', e.target.value)} />
      </label>
      <div className="loom-actions">
        <button type="button" className="btn"
          disabled={!store.dirty || store.saving}
          onClick={() => { void save(); }}>
          {store.saving ? 'Saving…' : 'Save draft'}
        </button>
        <button type="button" className="btn" disabled={!store.canUndo}
          onClick={store.undo}>Undo</button>
        <button type="button" className="btn" disabled={!store.canRedo}
          onClick={store.redo}>Redo</button>
        {store.dirty && <span className="stale">UNSAVED</span>}
      </div>
      {(refusal ?? store.error) && (
        <p className="bad" role="alert">{refusal ?? store.error}</p>
      )}
    </div>
  );
}
