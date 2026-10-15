/** Catalog provenance and overrides for stamped nodes (tracker M2-11 / M2-14 / M2-24).
 *
 *  Shows each stamped node's catalog reference resolution (resolved / missing /
 *  outdated) and its warning, offers an explicit rebind for an unavailable item
 *  (never a silent replacement), and lets the author apply an allowed override
 *  that is validated against the catalog policy before it is written.
 */
import { useState, type ReactElement } from 'react';
import { BUILTIN_CATALOG_V1, CATALOG_OVERRIDE_CONSTRAINTS, resolveCatalogReference, validateCatalogOverrides } from '../../graph/catalog';
import type { GraphStore } from '../../graph/store';

export function CatalogProvenance({ store }: { store: GraphStore }): ReactElement {
  const [message, setMessage] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const stamped = store.doc.nodes.filter((node) => node.catalogRef);
  if (stamped.length === 0) {
    return <p className="muted">No stamped catalog references on this graph.</p>;
  }
  return (
    <>
      {stamped.map((node) => {
        const ref = node.catalogRef!;
        const resolution = resolveCatalogReference(BUILTIN_CATALOG_V1, ref);
        const available = BUILTIN_CATALOG_V1.items.find((item) => item.id === ref.itemId) ?? null;
        const draft = drafts[node.id] ?? String(ref.overrides.portCount ?? node.ports);
        return (
          <div key={node.id} style={{ borderTop: '1px solid var(--border)', padding: '4px 0' }}>
            <div className="row" style={{ gap: 8, alignItems: 'center' }}>
              <code>{node.id}</code>
              <span className="muted" style={{ fontSize: 12 }}>{ref.catalogId}/{ref.itemId}@{ref.version}</span>
              <span className={resolution.state === 'resolved' ? 't-ok' : 't-warn'} data-testid={`resolution-${node.id}`}>
                {resolution.state}
              </span>
              {resolution.state !== 'resolved' && available && (
                <button type="button" className="btn btn-small" aria-label={`rebind ${node.id}`}
                  onClick={() => {
                    const refused = store.run({ type: 'update_node', id: node.id, patch: { catalogRef: { ...ref, version: available.version } } });
                    setMessage(refused ?? `Rebound ${node.id} to ${available.id}@${available.version} (explicit action).`);
                  }}>rebind to {available.version}</button>
              )}
            </div>
            {resolution.warning && <p className="t-warn" role="status" style={{ fontSize: 12 }}>{resolution.warning}</p>}
            {resolution.state === 'resolved' && (
              <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                <label>Port count override
                  <input aria-label={`port override ${node.id}`} type="number"
                    min={CATALOG_OVERRIDE_CONSTRAINTS.portCount!.min} max={CATALOG_OVERRIDE_CONSTRAINTS.portCount!.max} value={draft}
                    onChange={(event) => setDrafts((previous) => ({ ...previous, [node.id]: event.target.value }))} />
                </label>
                <button type="button" className="btn btn-small" aria-label={`apply override ${node.id}`}
                  onClick={() => {
                    const value = Number(draft);
                    const overrides = { ...ref.overrides, portCount: value };
                    const issues = validateCatalogOverrides(ref.catalogId, overrides);
                    if (issues.length > 0) { setMessage(issues.join('; ')); return; }
                    const refused = store.run({ type: 'update_node', id: node.id, patch: { ports: value, catalogRef: { ...ref, overrides } } });
                    setMessage(refused ?? `Applied portCount=${value} to ${node.id}.`);
                  }}>apply override</button>
              </div>
            )}
          </div>
        );
      })}
      {message && <p className="muted" role="status" style={{ fontSize: 12 }}>{message}</p>}
    </>
  );
}
