/** Stamp a local IP-catalog entry onto the authoring graph (tracker M2-09).
 *
 *  A stamp is one authored node: default port count, clock/reset/power domains
 *  and a `catalogRef` carrying item/version provenance plus embedded fallback
 *  metadata, so an offline project can still describe the block it stamped.
 *  This is authoring data — it is not a vendor IP claim and not a compile result.
 */
import type { CatalogItemV1, LocalCatalogV1 } from './catalog';
import type { CatalogReference, GraphNode } from './project';

/** Authoring roles the compiler adapter accepts, chosen as an editable default
 *  per catalog class. The adapter has no router kind, so a router template
 *  stamps as a generic interconnect endpoint until the author picks a role. */
export const CATALOG_CLASS_ROLE: Record<CatalogItemV1['class'], string> = {
  compute: 'compute_tile',
  memory: 'hbm_controller',
  bridge: 'ucie_port',
  peripheral: 'peripheral',
  router: 'nic',
};

export interface StampOptions {
  /** Stable node id, minted by the caller (never derived from position). */
  id: string;
  x: number;
  y: number;
}

export function catalogReferenceFor(catalog: LocalCatalogV1, item: CatalogItemV1): CatalogReference {
  return {
    catalogId: catalog.catalogId,
    itemId: item.id,
    version: item.version,
    overrides: {},
    fallbackMetadata: {
      name: item.name,
      class: item.class,
      family: item.family,
      portCount: item.ports.length,
    },
  };
}

/** Build the authoring node for a catalog item. Deterministic: the same item,
 *  id and position always yield the same node. */
export function catalogItemToNode(catalog: LocalCatalogV1, item: CatalogItemV1, options: StampOptions): GraphNode {
  return {
    id: options.id,
    x: options.x,
    y: options.y,
    role: CATALOG_CLASS_ROLE[item.class],
    ports: Math.max(1, item.ports.length),
    clock: item.clocks[0] ?? null,
    resetDomain: item.resets[0] ?? null,
    powerDomain: item.powers[0] ?? null,
    catalogRef: catalogReferenceFor(catalog, item),
  };
}

/** Candidate x for the next stamp, to the right of everything already placed. */
export function nextStampPosition(nodes: readonly Pick<GraphNode, 'x' | 'y'>[]): { x: number; y: number } {
  if (nodes.length === 0) return { x: 200, y: 200 };
  return { x: Math.max(...nodes.map((n) => n.x)) + 140, y: Math.min(...nodes.map((n) => n.y)) };
}
