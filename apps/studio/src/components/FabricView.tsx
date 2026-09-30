import { useState, type ReactElement } from 'react';
import { api } from '../api';
import type { DesignView, TopologyView } from '../types';
import Canvas2D, { OVERLAYS, type Overlay } from './FabricCanvas';
import { fabricModel } from '../fabricLayout';
import { useAsync } from '../studio';
import TopologyInspector from './TopologyInspector';

const shortHash = (value: string | null): string =>
  value ? `${value.replace(/^sha256:/, '').slice(0, 12)}…` : '';

export default function FabricView({ design, revisionId }: {
  design: DesignView;
  revisionId?: string | null;
}): ReactElement {
  const [overlay, setOverlay] = useState<Overlay>('structure');
  const topology = useAsync(
    () => (revisionId
      ? api.topology(revisionId)
      : Promise.resolve(null)),
    [revisionId],
  );
  const unavailable = OVERLAYS.filter((o) => o.id !== 'structure');

  if (revisionId && topology.result.state === 'error') {
    return (
      <div className="fabric-view" role="alert">
        <div className="verdict-banner verdict-unsupported">
          <span className="verdict-text">
            <strong>Fabric not materialized.</strong>{' '}
            {topology.result.error.message} No topology, routing, VC
            assignment or certificate exists for this revision — nothing
            is drawn.
          </span>
        </div>
      </div>
    );
  }

  if (revisionId && topology.result.state === 'ready' && topology.result.data) {
    return (
      <MaterializedFabric
        design={design}
        revisionId={revisionId}
        topology={topology.result.data}
      />
    );
  }

  return (
    <CertifiedCanvas
      design={design}
      topology={null}
      overlay={overlay}
      onOverlay={setOverlay}
      unavailable={unavailable}
    />
  );
}

function MaterializedFabric({ design, revisionId, topology }: {
  design: DesignView;
  revisionId: string;
  topology: TopologyView;
}): ReactElement {
  return (
    <div className="fabric-view">
      <span className="canvas-meta">
        materialized · {topology.family} · {topology.counts.routers} routers ·{' '}
        {topology.counts.channels} directed channels ·{' '}
        {topology.counts.endpoints} endpoints / {topology.counts.seats} seats ·{' '}
        topology {shortHash(topology.topology_hash)}
      </span>
      <TopologyInspector design={design} revisionId={revisionId} topology={topology} />
    </div>
  );
}

function CertifiedCanvas({ design, topology, overlay, onOverlay,
  unavailable }: {
  design: DesignView;
  topology: TopologyView | null;
  overlay: Overlay;
  onOverlay: (o: Overlay) => void;
  unavailable: { id: Overlay; label: string; needs: string }[];
}): ReactElement {
  const model = fabricModel(design, topology);

  const g = design.noc_guided;
  const knobs = [
    g.topology_family ? `family ${g.topology_family}` : 'family —',
    g.concentration != null ? `conc ${g.concentration}` : null,
    g.radix != null ? `side length ${g.radix}` : null,
    g.arbitration ? `arb ${g.arbitration}` : null,
  ].filter((part): part is string => Boolean(part)).join(' · ');
  const meta = `~${model.counts.routers} routers from declared counts · `
    + `${model.totals.compute} compute · ${knobs} · `
    + 'schematic preview — compile to materialize the certified graph';

  return (
    <div className="fabric-view">
      <div className="canvas-toolbar">
        <div className="overlay-tabs" role="tablist" aria-label="Canvas overlays">
          <button
            role="tab"
            aria-selected={overlay === 'structure'}
            className={`overlay-tab${overlay === 'structure' ? ' active' : ''}`}
            onClick={() => onOverlay('structure')}
            title="Structural view (routers, links, attachments)"
          >
            Structure ✓
          </button>
        </div>
      </div>

      <span className="canvas-meta">preview · {meta}
        {model.linkWidth ? ` · link ${model.linkWidth}b` : ''}
      </span>

      <details className="overlay-note">
        <summary>
          Unavailable overlays ({unavailable.length}) — nothing hidden renders
        </summary>
        <ul>
          {unavailable.map((o) => (
            <li key={o.id}>
              <strong>{o.label}</strong> — requires {o.needs}
            </li>
          ))}
        </ul>
      </details>

      <Canvas2D model={model} topology={topology} />
    </div>
  );
}
