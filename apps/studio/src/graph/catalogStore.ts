/** The catalog a project authoring session reads from (tracker M2-12 / M2-13).
 *
 *  A project may embed its own local catalog in `metadata.localCatalog`; when it
 *  does, that catalog replaces the built-in one for search, stamping and
 *  provenance resolution. Otherwise the shipped built-in catalog is used. */
import { BUILTIN_CATALOG_V1, type LocalCatalogV1 } from './catalog';
import type { LoomProject } from './project';

export function effectiveCatalog(project: Pick<LoomProject, 'metadata'>): LocalCatalogV1 {
  return project.metadata?.localCatalog ?? BUILTIN_CATALOG_V1;
}

export function hasLocalCatalog(project: Pick<LoomProject, 'metadata'>): boolean {
  return project.metadata?.localCatalog !== undefined;
}
