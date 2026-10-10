/** useGraphStore: editable graph + dirty + autosave + crash recovery. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { GraphHistory, type GraphCommand } from './history';
import { buildPreset, type PresetId } from './presets';
import { parseProject, type LoomProject } from './project';

const KEY = 'loom-graph-autosave-v1';

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
        if (histRef.current?.undo()) { setError(null); setVersion((v) => v + 1); }
      } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        if (histRef.current?.redo()) { setError(null); setVersion((v) => v + 1); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const doc = histRef.current.current();
  const dirty = JSON.stringify(doc) !== savedText;
  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => {
      try { localStorage.setItem(key, JSON.stringify(histRef.current!.current())); } catch { /* quota */ }
    }, 500);
    return () => clearTimeout(t);
  }, [dirty, key, version]);

  const run = useCallback((cmd: GraphCommand): string | null => {
    const out = histRef.current!.apply(cmd);
    if (out.refused) { setError(out.refused); return out.refused; }
    try { localStorage.setItem(key, JSON.stringify(histRef.current!.current())); } catch { /* quota */ }
    setError(null); setVersion((v) => v + 1); return null;
  }, [key]);
  const undo = useCallback(() => { if (histRef.current!.undo()) {
    try { localStorage.setItem(key, JSON.stringify(histRef.current!.current())); } catch { /* quota */ }
    setError(null); setVersion((v) => v + 1);
  } }, [key]);
  const redo = useCallback(() => { if (histRef.current!.redo()) {
    try { localStorage.setItem(key, JSON.stringify(histRef.current!.current())); } catch { /* quota */ }
    setError(null); setVersion((v) => v + 1);
  } }, [key]);
  const loadPreset = useCallback((id: PresetId) => {
    histRef.current!.reset(buildPreset(id));
    const text = JSON.stringify(histRef.current!.current());
    setSavedText(text);
    try { localStorage.setItem(key, text); } catch { /* quota */ }
    setError(null); setVersion((v) => v + 1);
  }, []);
  const loadJson = useCallback((json: string): string | null => {
    try {
      const parsed = parseProject(json);
      histRef.current!.reset(parsed);
      const text = JSON.stringify(parsed);
      setSavedText(text);
      localStorage.setItem(key, text);
      setError(null); setVersion((v) => v + 1); return null;
    } catch (e) { return e instanceof Error ? e.message : String(e); }
  }, []);
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
