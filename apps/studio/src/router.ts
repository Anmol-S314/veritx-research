import { useEffect, useState } from 'react';

/** The routable part of the address. The query string is deliberately not part
 *  of it: a route is a place, and `parseRoute` has no notion of `?sel=`. Views
 *  that encode state in the query read it through `useSearch`. */
export function usePathname(): string {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const onPop = (): void => setPath(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  return path;
}

/** The query string, which changes without changing the route. The Loom
 *  selection lives here, so a selection change must be able to re-render the
 *  view that owns it without the shell re-parsing a route. */
export function useSearch(): string {
  const [search, setSearch] = useState(() => window.location.search);
  useEffect(() => {
    const onPop = (): void => setSearch(window.location.search);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  return search;
}

export function navigate(to: string): void {
  // Compared against the full address, not the pathname: without the query a
  // selection change on the current route reads as "already there" and is
  // silently dropped.
  if (`${window.location.pathname}${window.location.search}` === to) return;
  window.history.pushState({}, '', to);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export type CompileResultGroup =
  | 'summary' | 'mapping' | 'fabric' | 'routing' | 'resources'
  | 'address_decode' | 'provenance' | 'control_plane';

const COMPILE_RESULT_GROUP_SEGMENTS: Record<CompileResultGroup, string> = {
  summary: 'summary',
  mapping: 'mapping',
  fabric: 'fabric',
  routing: 'routing',
  resources: 'resources',
  address_decode: 'address-decode',
  provenance: 'provenance',
  control_plane: 'control-plane',
};

export function compileResultGroupFromSegment(
  segment: string,
): CompileResultGroup | null {
  const entry = Object.entries(COMPILE_RESULT_GROUP_SEGMENTS)
    .find(([, pathSegment]) => pathSegment === segment);
  return entry ? entry[0] as CompileResultGroup : null;
}

export function compileResultGroupSegment(group: string): string | null {
  return COMPILE_RESULT_GROUP_SEGMENTS[group as CompileResultGroup] ?? null;
}

export interface ParsedRoute {
  kind: 'root' | 'project' | 'revision' | 'runs' | 'run' | 'trust' | 'offline' | 'notfound';
  projectId?: string;
  revisionId?: string;
  group?: CompileResultGroup;
  section?: string;
  detail?: string;
  runId?: string;
}

export function parseRoute(path: string): ParsedRoute {
  const parts = path.split('/').filter(Boolean);
  if (parts.length === 0) return { kind: 'root' };
  if (parts[0] === 'trust') return { kind: 'trust' };
  if (parts[0] === 'offline') return { kind: 'offline' };
  if (parts[0] === 'runs') {
    return parts[1]
      ? { kind: 'run', runId: parts[1] }
      : { kind: 'runs' };
  }
  if (parts[0] === 'revisions') {
    if (parts.length !== 3 || !parts[1]) return { kind: 'notfound' };
    const group = compileResultGroupFromSegment(parts[2]);
    return group
      ? { kind: 'revision', revisionId: parts[1], group }
      : { kind: 'notfound' };
  }
  if (parts[0] === 'projects' && parts[1]) {
    const section = parts[2] === 'design' && parts[3] === 'review'
      ? 'review'
      : parts[2] ?? 'overview';
    // The fourth segment is the detail selector: candidate id, Loom view id.
    return {
      kind: 'project',
      projectId: parts[1],
      section,
      detail: parts[3],
    };
  }
  return { kind: 'notfound' };
}

export function projectLink(projectId: string, section = 'overview'): string {
  return `/projects/${projectId}/${section}`;
}

export const SECTION_GROUPS: Record<string, string[]> = {
  BUILD: ['overview', 'design', 'compile'],
  ANALYZE: ['evaluate', 'performance', 'serving'],
  EXPLORE: ['optimize', 'synthesize', 'candidates', 'compare', 'agents', 'loom'],
  TRUST: ['runs', 'verification', 'evidence', 'reproduce',
    'capabilities', 'validation', 'implementation'],
};
