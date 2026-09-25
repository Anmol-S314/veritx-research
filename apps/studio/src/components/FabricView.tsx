import { Suspense, lazy, useState, type ReactElement } from 'react';
import type { DesignView } from '../types';
import FabricCanvas, { OVERLAYS, type Overlay } from './FabricCanvas';
import { deriveFabric } from '../fabricLayout';

// Three.js is heavy; load it only when the 3D view is shown.
const FabricCanvas3D = lazy(() => import('./FabricCanvas3D'));

/**
 * Topology / traffic view. 3D by default (orbitable structure), with a 2D
 * fallback. Overlay selection is honest: only `structure` is rendered;
 * every other overlay states the artifact it needs and is never faked.
 */
export default function FabricView({ design }: {
  design: DesignView;
}): ReactElement {
  const [overlay, setOverlay] = useState<Overlay>('structure');
  const [mode, setMode] = useState<'3d' | '2d'>('3d');
  const layout = deriveFabric(design);
  const active = OVERLAYS.find((o) => o.id === overlay);

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
        {layout.routerCount} routers · {layout.links.length} links ·{' '}
        {layout.compute} compute tiles · {layout.hbm} HBM · link width{' '}
        {design.noc_guided.link_width ?? '—'}
      </span>

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
          <FabricCanvas3D design={design} />
        </Suspense>
      ) : (
        <FabricCanvas design={design} />
      )}
    </div>
  );
}
