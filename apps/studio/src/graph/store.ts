/** useGraphStore: editable graph + dirty + autosave + crash recovery. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { GraphHistory, type GraphCommand } from './history';
import { buildPreset, type PresetId } from './presets';
import { parseProject, type LoomProject } from './project';

const KEY = 'loom-graph-autosave-v1';

function persistSnapshot(key: string, doc: LoomProject): string | null {
  try {
    localStorage.setItem(key, JSON.stringify(doc));
    return null;
  } catch (error) {
    const detail = error instanceof Error ? ` (${error.message})` : '';
    return `Local autosave failed${detail}; changes remain in memory but may be lost on exit.`;
  }
}

export interface GraphStore {
  doc: LoomProject;
  dirty: boolean;
  error: string | null;
  canUndo: boolean;
  canRedo: boolean;
  isCustom: boolean;
  run: (cmd: GraphCommand) => string | null;
  undo: () => void;
  redo: () => void;
  loadPreset: (id: PresetId) => void;
  loadJson: (json: string) => string | null;
  serialize: () => string;
}

export function useGraphStore(initial: PresetId = 'mesh-4x4', scope = 'local'): GraphStore {
  const key = `${KEY}:${scope}`;
  const histRef = useRef<GraphHistory | null>(null);
  if (!histRef.current) {
    try {
      const raw = localStorage.getItem(key);
      if (raw) histRef.current = new GraphHistory(parseProject(raw));
    } catch { /* invalid recovery data falls back to a preset */ }
    histRef.current ??= new GraphHistory(buildPreset(initial));
  }
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [savedText, setSavedText] = useState(() => JSON.stringify(histRef.current!.current()));
  void version;

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        if (histRef.current?.undo()) {
          setError(persistSnapshot(key, histRef.current.current()));
          setVersion((v) => v + 1);
        }
      } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        if (histRef.current?.redo()) {
          setError(persistSnapshot(key, histRef.current.current()));
          setVersion((v) => v + 1);
        }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [key]);

  const doc = histRef.current.current();
  const dirty = JSON.stringify(doc) !== savedText;
  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => {
      setError(persistSnapshot(key, histRef.current!.current()));
    }, 500);
    return () => clearTimeout(t);
  }, [dirty, key, version]);

  const run = useCallback((cmd: GraphCommand): string | null => {
    const out = histRef.current!.apply(cmd);
    if (out.refused) { setError(out.refused); return out.refused; }
    setError(persistSnapshot(key, histRef.current!.current()));
    setVersion((v) => v + 1); return null;
  }, [key]);
  const undo = useCallback(() => { if (histRef.current!.undo()) {
    setError(persistSnapshot(key, histRef.current!.current()));
    setVersion((v) => v + 1);
  } }, [key]);
  const redo = useCallback(() => { if (histRef.current!.redo()) {
    setError(persistSnapshot(key, histRef.current!.current()));
    setVersion((v) => v + 1);
  } }, [key]);
  const loadPreset = useCallback((id: PresetId) => {
    const out = histRef.current!.apply({ type: 'load_project', project: buildPreset(id) });
    if (out.refused) { setError(out.refused); return; }
    const text = JSON.stringify(histRef.current!.current());
    setSavedText(text);
    setError(persistSnapshot(key, histRef.current!.current()));
    setVersion((v) => v + 1);
  }, [key]);
  const loadJson = useCallback((json: string): string | null => {
    try {
      const parsed = parseProject(json);
      const out = histRef.current!.apply({ type: 'load_project', project: parsed });
      if (out.refused) { setError(out.refused); return out.refused; }
      const text = JSON.stringify(histRef.current!.current());
      setSavedText(text);
      setError(persistSnapshot(key, parsed));
      setVersion((v) => v + 1); return null;
    } catch (e) { return e instanceof Error ? e.message : String(e); }
  }, [key]);
  const serialize = useCallback(() => {
    const text = JSON.stringify(histRef.current!.current(), null, 2);
    setSavedText(JSON.stringify(histRef.current!.current()));
    localStorage.removeItem(key);
    setVersion((v) => v + 1);
    return text;
  }, []);

  return {
    doc, dirty, error,
    canUndo: histRef.current.canUndo(), canRedo: histRef.current.canRedo(),
    isCustom: doc.presetHint === null,
    run, undo, redo, loadPreset, loadJson, serialize,
  };
}
