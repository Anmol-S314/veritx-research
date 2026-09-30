import {
  createContext, useCallback, useContext, useState,
  type ReactElement, type ReactNode,
} from 'react';

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
  id: string | number | null;
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
    }
    return EMPTY;
  });
  const select = useCallback((next: Selection) => {
    setSelection(next);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
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
