import { Suspense, lazy, useState, type ReactElement } from 'react';
import { api } from '../api';
import type { DesignView } from '../types';
import FabricCanvas, { OVERLAYS, type Overlay } from './FabricCanvas';
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
 * (routers, channels, agent seats). Without one — an uncompiled draft or
 * the offline fixture shell — we draw the intent preview and say so.
 * Overlay selection is equally honest: only `structure` is rendered;
 * every other overlay states the artifact it needs.
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
  const model = fabricModel(
    design,
    topology.result.state === 'ready' ? topology.result.data : null,
  );
  const active = OVERLAYS.find((o) => o.id === overlay);

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
          {OVERLAYS.map((o) => (
            <button
              key={o.id}
              role="tab"
              aria-selected={overlay === o.id}
              className={`overlay-tab${overlay === o.id ? ' active' : ''}`}
              onClick={() => setOverlay(o.id)}
              title={o.needs || 'Structural view (routers, links, attachments)'}
            >
              {o.label}
            </button>
          ))}
        </div>
        <div className="segmented small" role="tablist" aria-label="View mode">
          <button
            role="tab"
            aria-selected={mode === '3d'}
            className={mode === '3d' ? 'selected' : ''}
            onClick={() => setMode('3d')}
          >
            3D
          </button>
          <button
            role="tab"
            aria-selected={mode === '2d'}
            className={mode === '2d' ? 'selected' : ''}
            onClick={() => setMode('2d')}
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

      {topology.result.state === 'error' && (
        <p className="warn">
          Materialized topology unavailable ({topology.result.error.message})
          {' — '}showing the intent preview.
        </p>
      )}

      {overlay !== 'structure' && active && (
        <div className="overlay-note">
          <strong>{active.label} overlay — not rendered.</strong>{' '}
          {active.needs} The view shows structure only; nothing is
          color-fabricated from aggregate data.
        </div>
      )}

      {mode === '3d' ? (
        <Suspense fallback={
          <div className="canvas-3d canvas-3d-loading" role="status">
            loading 3D topology…
          </div>
        }>
          <FabricCanvas3D model={model} />
        </Suspense>
      ) : (
        <FabricCanvas model={model} />
      )}
    </div>
  );
}
