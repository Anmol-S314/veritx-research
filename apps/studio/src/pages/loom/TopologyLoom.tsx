import { useState, type ReactElement, type ReactNode } from 'react';
import FabricCanvas, { OVERLAYS } from '../../components/FabricCanvas';
import FabricInspector, { type FabricSelection } from '../../components/FabricInspector';
import { fabricModel } from '../../fabricLayout';
import { Hash } from '../../components/badges';
import { compileSummary, type LoomData } from './data';
import {
  ExtensionPoint, Kv, Panes, PlaneCard, RailSection, SummaryStrip,
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

export default function TopologyLoom({ data, problems }: {
  data: LoomData;
  problems?: ReactNode;
}): ReactElement {
  const [plane, setPlane] = useState<PlaneId>('data');
  const [selection, setSelection] = useState<FabricSelection | null>(null);

  const topology = data.topology.result.state === 'ready'
    ? data.topology.result.data
    : null;
  const design = data.design;
  const active = PLANES.find((p) => p.id === plane) ?? PLANES[0];
  const g = design?.noc_guided ?? null;
  const locked = design?.locked_derived ?? null;
  const linkWidth = topology?.channels[0]?.width_bits ?? g?.link_width ?? null;

  const model = design && topology ? fabricModel(design, topology) : null;
  const unavailable = OVERLAYS.filter((o) => o.id !== 'structure');
  const summary = compileSummary(data);
  const decl = summary?.declared ?? {};
  const der = summary?.derived ?? {};
  const num = (v: unknown): number | null => (typeof v === 'number' ? v : null);
  const txt = (v: unknown): string | null => (typeof v === 'string' ? v : null);
  const routeClasses = Array.isArray(der.routing_classes)
    ? (der.routing_classes as unknown[]).filter((c): c is string => typeof c === 'string')
    : null;
  const certificate = locked?.certificate_overall
    ?? txt(summary?.certificate_overall)
    ?? null;

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
          onSelect={setSelection}
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

          <RailSection
            title="Fabric parameters"
            note="Authored intent comes from the draft; derived rows come from the compiled topology. The two are never merged."
          >
            <Kv label="family" value={<code>{topology?.family ?? g?.topology_family ?? '—'}</code>} />
            <Kv label="radix / side" value={num(decl.side_length) ?? g?.radix ?? '—'} mono />
            <Kv label="concentration" value={num(decl.concentration) ?? g?.concentration ?? '—'} mono />
            <Kv label="link width" value={linkWidth != null ? `${linkWidth} bits` : '—'} mono />
            <Kv label="arbitration" value={<code>{txt(decl.arbitration) ?? g?.arbitration ?? '—'}</code>} />
            <Kv label="routing classes (derived)" value={
              <code>{locked?.routing ?? routeClasses?.join(', ') ?? '—'}</code>
            } />
            <Kv label="VC count (derived)" value={num(der.vc_count) ?? locked?.vc_count ?? '—'} mono />
            <Kv label="turn restrictions" value={
              locked?.turn_restrictions?.length
                ? locked.turn_restrictions.join(', ')
                : '—'
            } />
            <Kv label="certificate" value={
              certificate ? (
                <span className={`status status-${certificate === 'PASS' ? 'ok' : 'bad'}`}>
                  {certificate}
                </span>
              ) : '—'
            } />
          </RailSection>

          <RailSection title="Materialization counts">
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
              Select a router, channel or endpoint — selection opens the artifact
              inspector on the right. Selection never writes back to the design.
            </div>
          )}
        </div>
      }
      right={
        <>
          <RailSection title="Artifact inspector">
            {topology && (
              <FabricInspector
                topology={topology}
                selection={selection}
                onClose={() => setSelection(null)}
              />
            )}
            {!topology && (
              <p className="muted">
                No certified topology on this revision, so there is nothing to
                inspect. Intent-only routers are not evidence.
              </p>
            )}
            {topology && !selection && (
              <p className="muted">
                Nothing selected. Every field shown here is read from the
                TopologyView the revision was verified against.
              </p>
            )}
          </RailSection>

          <RailSection title="Identities">
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
