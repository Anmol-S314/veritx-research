import { useState, type ReactElement } from 'react';
import type { ArtifactChainView } from '../api';
import { Hash, shortHash } from './badges';

/**
 * The canonical artifact DAG (Design → Inventory/Mapping → Topology → … →
 * Resolved fabric), rendered from the backend's ArtifactChainView. Every
 * node, hash and parent link comes from the view; nothing is inferred or
 * reordered locally. Layers follow the backend's node order: parents always
 * appear before the artifacts derived from them.
 */
export default function ArtifactChain({
  chain,
}: {
  chain: ArtifactChainView | null;
}): ReactElement {
  const [open, setOpen] = useState<string | null>(null);

  if (!chain) {
    return (
      <p className="muted">
        No artifact chain exists for this revision — it never compiled, so no
        canonical artifacts were produced.
      </p>
    );
  }

  const byId = new Map(chain.nodes.map((n) => [n.artifact, n]));
  const selected = open ? byId.get(open) : undefined;

  return (
    <div className="artifact-chain" aria-label="Canonical artifact chain">
      <ol className="chain-layers">
        {chain.nodes.map((node) => {
          const isOpen = open === node.artifact;
          return (
            <li key={node.artifact} className="chain-layer">
              <button
                type="button"
                className={`chain-node${isOpen ? ' open' : ''}`}
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? null : node.artifact)}
              >
                <span className="chain-label">{node.label}</span>
                <code className="chain-hash">{shortHash(node.hash)}</code>
                {node.proved_by.length > 0 && (
                  <span className="chain-proved" title={node.proved_by.join(', ')}>
                    {node.proved_by.length === 1
                      ? node.proved_by[0]
                      : `${node.proved_by.length} proofs`}
                  </span>
                )}
              </button>
              {isOpen && selected === node && (
                <div className="chain-detail">
                  <div className="kv">
                    <span>artifact</span>
                    <code>{node.artifact}</code>
                  </div>
                  <div className="kv">
                    <span>identity</span>
                    <Hash value={node.hash} />
                  </div>
                  <div className="kv">
                    <span>derived from</span>
                    <span>
                      {node.parents.length === 0
                        ? 'user intent (no parents)'
                        : node.parents
                            .map((p) => byId.get(p)?.label ?? p)
                            .join(' + ')}
                    </span>
                  </div>
                  <div className="kv">
                    <span>proved by</span>
                    <span>
                      {node.proved_by.length > 0
                        ? node.proved_by.join(', ')
                        : '—'}
                    </span>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      <p className="muted chain-note">
        Canonical chain certified by{' '}
        <Hash value={chain.certificate_id} label="certificate" />. Hashes and
        parent links are served by the gateway from the recorded compilation
        bundle — never re-derived in the browser.
      </p>
    </div>
  );
}
