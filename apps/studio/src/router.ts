// Minimal history router. Deep links are real paths (refresh-safe with an
// SPA fallback): /projects/:pid/design, /runs/:runId, /trust, /offline.
import { useEffect, useState } from 'react';

export function usePathname(): string {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const onPop = (): void => setPath(window.location.pathname);
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  return path;
}

export function navigate(to: string): void {
  if (window.location.pathname === to) return;
  window.history.pushState({}, '', to);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export interface ParsedRoute {
  kind: 'root' | 'project' | 'runs' | 'run' | 'trust' | 'offline' | 'notfound';
  projectId?: string;
  section?: string;
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
  if (parts[0] === 'projects' && parts[1]) {
    return {
      kind: 'project',
      projectId: parts[1],
      // `/projects/:pid/design/review` is the pre-compile boundary; it is
      // its own section so the review snapshot has a real deep link.
      section: parts[2] === 'design' && parts[3] === 'review'
        ? 'review'
        : parts[2] ?? 'overview',
    };
  }
  return { kind: 'notfound' };
}

export function projectLink(projectId: string, section = 'overview'): string {
  return `/projects/${projectId}/${section}`;
}
