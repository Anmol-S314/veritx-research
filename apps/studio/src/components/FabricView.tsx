import { Suspense, lazy, useState, type ReactElement } from 'react';
import { api } from '../api';
import type { DesignView, TopologyView } from '../types';
import Canvas2D, { OVERLAYS, type Overlay } from './FabricCanvas';
import { fabricModel } from '../fabricLayout';
import { useAsync } from '../studio';

// Three.js is heavy; load it only when the 3D view is shown.
const FabricCanvas3D = lazy(() => import('./FabricCanvas3D'));

const shortHash = (value: string | null): string =>
  value ? `${value.replace(/^sha256:/, '').slice(0, 12)}…` : '';

/**
 * Topology / traffic view. 3D by default (orbitable structure), with a 2D
 * fallback.
 *
 * Source honesty: with a revision id we draw the certified TopologyView
 * (routers, channels, agent seats). Without one — an uncompiled draft —
 * we draw the intent preview and say so. A revision whose materialized
 * topology cannot be loaded (refused, missing, tampered) renders a
 * FABRIC NOT MATERIALIZED panel: never a mesh that implies a certified
 * fabric exists.
 */
export default function FabricView({ design, revisionId }: {
  design: DesignView;
  revisionId?: string | null;
}): ReactElement {
  const [overlay, setOverlay] = useState<Overlay>('structure');
  const [mode, setMode] = useState<'3d' | '2d'>('3d');
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

  return (
    <CertifiedCanvas
      design={design}
      topology={topology.result.state === 'ready' ? topology.result.data : null}
      overlay={overlay}
      onOverlay={setOverlay}
      mode={mode}
      onMode={setMode}
      unavailable={unavailable}
    />
  );
}

/** The certified-or-preview canvas with its toolbar. Split so the
 * not-materialized branch above returns before any mesh is constructed. */
function CertifiedCanvas({ design, topology, overlay, onOverlay, mode, onMode,
  unavailable }: {
  design: DesignView;
  topology: TopologyView | null;
  overlay: Overlay;
  onOverlay: (o: Overlay) => void;
  mode: '3d' | '2d';
  onMode: (m: '3d' | '2d') => void;
  unavailable: { id: Overlay; label: string; needs: string }[];
}): ReactElement {
  const model = fabricModel(design, topology);

  const meta = model.source === 'topology'
    ? `${model.family} · ${model.counts.routers} routers · `
      + `${model.counts.channels} directed channels · `
      + `${model.counts.endpoints} endpoints / ${model.counts.seats} seats · `
      + `topology ${shortHash(model.topologyHash)}`
    : `~${model.counts.routers} routers from declared counts · `
      + `${model.totals.compute} compute · `
      + 'compile to materialize the certified graph';

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
        <div className="segmented small" role="tablist" aria-label="View mode">
          <button
            role="tab"
            aria-selected={mode === '3d'}
            className={mode === '3d' ? 'selected' : ''}
            onClick={() => onMode('3d')}
          >
            3D
          </button>
          <button
            role="tab"
            aria-selected={mode === '2d'}
            className={mode === '2d' ? 'selected' : ''}
            onClick={() => onMode('2d')}
          >
            2D
          </button>
        </div>
      </div>

      <span className="canvas-meta">
        {model.source === 'topology' ? 'materialized · ' : 'preview · '}
        {meta}
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

      {mode === '3d' ? (
        <Suspense fallback={
          <div className="canvas-3d canvas-3d-loading" role="status">
            loading 3D topology…
          </div>
        }>
          <FabricCanvas3D model={model} />
        </Suspense>
      ) : (
        <Canvas2D model={model} />
      )}
    </div>
  );
}
