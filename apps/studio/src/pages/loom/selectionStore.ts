/** The write side of the selection model: the URL is the store, and this is
 *  the only place in the workspace that writes it.
 *
 *  `Loom` owns one of these and passes it to every tab. No tab keeps selection
 *  in React state, so there is nothing to fall out of sync, and a tab change
 *  cannot lose what the previous tab had selected — the set simply stays in
 *  the address bar and the next tab renders the part of it it understands.
 */
import { useCallback, useMemo, useState } from 'react';
import type { LoomViewId } from './data';
import {
  isGraphId as isGraph, loomHref, removeId, selectOne, selectionFromQuery,
  selectionQuery, toggleGraph,
  type GraphId, type LoomId, type LoomSelection, type ParsedSelection,
  type RejectedId,
} from './selection';

export interface LoomSelectionStore {
  selection: LoomSelection;
  /** Ids this URL named that are not part of a valid selection. Counted and
   *  shown; never coerced into something that renders as a real object. */
  rejected: RejectedId[];
  /** Replace the selection with one object. */
  select: (id: LoomId) => void;
  /** The gesture a click carries: a plain click replaces, a modifier click
   *  accumulates on a graph object. The gesture decides nothing about the
   *  object itself. */
  choose: (id: LoomId, additive: boolean) => void;
  /** Remove one object, leaving whatever else is held. */
  drop: (id: LoomId) => void;
  clear: () => void;
  /** A tab link that carries the whole selection across. */
  href: (view: LoomViewId) => string;
  /** The address that reproduces this view and this selection exactly. */
  shareUrl: string;
  copy: () => void;
  copied: boolean;
}

function isGraphId(id: LoomId): id is GraphId {
  return isGraph(id);
}

/** `replaceState`, not `pushState`: shift-clicking across a graph must not
 *  leave fifty entries in the back stack, and the selection is still in the
 *  URL for every other reader of it. */
function writeSelection(selection: LoomSelection): void {
  const query = selectionQuery(selection);
  const next = `${window.location.pathname}${query ? `?${query}` : ''}`;
  const current = `${window.location.pathname}${window.location.search}`;
  if (current === next) return;
  window.history.replaceState({}, '', next);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

/** Read the URL rather than the rendered closure, so two clicks in one frame
 *  compose instead of the second overwriting the first. */
function live(): LoomSelection {
  return selectionFromQuery(window.location.search).selection;
}

export function useLoomSelection(
  parsed: ParsedSelection,
  projectId: string,
): LoomSelectionStore {
  const [copied, setCopied] = useState(false);
  const { selection } = parsed;

  const choose = useCallback((id: LoomId, additive: boolean): void => {
    if (additive && isGraphId(id)) {
      writeSelection(toggleGraph(live(), id));
      return;
    }
    writeSelection(selectOne(live(), id));
  }, []);

  const select = useCallback(
    (id: LoomId): void => { writeSelection(selectOne(live(), id)); },
    [],
  );

  const drop = useCallback((id: LoomId): void => {
    writeSelection(removeId(live(), id));
  }, []);

  const clear = useCallback((): void => {
    writeSelection({ mode: 'empty' });
  }, []);

  const href = useCallback(
    (target: LoomViewId): string => loomHref(projectId, target, selection),
    [projectId, selection],
  );

  // `parsed` is a fresh object on every location change, which is exactly the
  // moment the address it renders has moved.
  const shareUrl = useMemo(
    () => `${window.location.origin}${window.location.pathname}${window.location.search}`,
    [parsed],
  );

  const copy = useCallback((): void => {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(shareUrl).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      },
      () => setCopied(false),
    );
  }, [shareUrl]);

  return {
    selection,
    rejected: parsed.rejected,
    select,
    choose,
    drop,
    clear,
    href,
    shareUrl,
    copy,
    copied,
  };
}

