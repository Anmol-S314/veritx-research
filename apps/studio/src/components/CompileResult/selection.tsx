import {
  createContext, useCallback, useContext, useState,
  type ReactElement, type ReactNode,
} from 'react';

/** Entities the engineering console can select. Identifiers and navigation
 * context only — no scientific authority lives in this client-side state. */
export type SelectionKind =
  | 'rank'
  | 'agent'
  | 'endpoint'
  | 'router'
  | 'channel'
  | 'routing_class'
  | 'vc'
  | 'artifact'
  | 'obligation';

export interface Selection {
  kind: SelectionKind | null;
  /** The selected identifier: endpoint/router/channel/vc id, rank number,
   * routing-class name, artifact key, obligation name… */
  id: string | number | null;
  /** Secondary identifier (e.g. the VC's routing class, the rank's
   * endpoint) carried for navigation context only. */
  secondary?: string | number | null;
}

const EMPTY: Selection = { kind: null, id: null };

interface SelectionContextValue {
  selection: Selection;
  select: (next: Selection) => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionContextValue>({
  selection: EMPTY,
  select: () => undefined,
  clear: () => undefined,
});

const STORAGE_KEY = 'veritx.compile-selection';

/** Survives tab switches (same tree) and page navigation (session
 * storage) where meaningful. Only identifiers are persisted. */
export function SelectionProvider({ children }: {
  children: ReactNode;
}): ReactElement {
  const [selection, setSelection] = useState<Selection>(() => {
    try {
      const raw = window.sessionStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Selection;
        if (parsed && typeof parsed === 'object' && 'kind' in parsed) {
          return { kind: parsed.kind, id: parsed.id,
                   secondary: parsed.secondary ?? null };
        }
      }
    } catch {
      /* storage unavailable — selection stays session-only */
    }
    return EMPTY;
  });
  const select = useCallback((next: Selection) => {
    setSelection(next);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }, []);
  const clear = useCallback(() => select(EMPTY), [select]);
  return (
    <SelectionContext.Provider value={{ selection, select, clear }}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection(): SelectionContextValue {
  return useContext(SelectionContext);
}
