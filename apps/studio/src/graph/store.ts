/** useGraphStore: editable graph + dirty + autosave + crash recovery. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { GraphHistory, type GraphCommand } from './history';
import { buildPreset, type PresetId } from './presets';
import { parseProjectDraft, parseProjectResult, type LoomProject } from './project';
import type { ValidationIssue } from './validation';

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
  issues?: ValidationIssue[];
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
      if (raw) histRef.current = new GraphHistory(parseProjectDraft(raw));
    } catch { /* invalid recovery data falls back to a preset */ }
    histRef.current ??= new GraphHistory(buildPreset(initial));
  }
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [savedText, setSavedText] = useState(() => JSON.stringify(histRef.current!.current()));
  void version;

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        if (histRef.current?.undo()) { setError(persistSnapshot(key, histRef.current.current())); setIssues([]); setVersion((v) => v + 1); }
      } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        if (histRef.current?.redo()) { setError(persistSnapshot(key, histRef.current.current())); setIssues([]); setVersion((v) => v + 1); }
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
    if (out.refused) { setError(out.refused); setIssues(out.issues); return out.refused; }
    setError(persistSnapshot(key, histRef.current!.current()));
    setIssues([]); setVersion((v) => v + 1); return null;
  }, [key]);
  const undo = useCallback(() => { if (histRef.current!.undo()) {
    setError(persistSnapshot(key, histRef.current!.current()));
    setIssues([]); setVersion((v) => v + 1);
  } }, [key]);
  const redo = useCallback(() => { if (histRef.current!.redo()) {
    setError(persistSnapshot(key, histRef.current!.current()));
    setIssues([]); setVersion((v) => v + 1);
  } }, [key]);
  const loadPreset = useCallback((id: PresetId) => {
    const out = histRef.current!.apply({ type: 'load_project', project: buildPreset(id) });
    if (out.refused) { setError(out.refused); setIssues(out.issues); return; }
    const text = JSON.stringify(histRef.current!.current());
    setSavedText(text);
    setError(persistSnapshot(key, histRef.current!.current()));
    setIssues([]); setVersion((v) => v + 1);
  }, [key]);
  const loadJson = useCallback((json: string): string | null => {
    const parsed = parseProjectResult(json);
    if (!parsed.ok) {
      const syntaxIssue = parsed.issues.find(issue => issue.message.startsWith('invalid project JSON:'));
      const message = syntaxIssue?.message ?? parsed.issues.map(({ path, message: detail, objectRef }) => `${path ?? objectRef.path}: ${detail}`).join('\\n');
      setError(message); setIssues(parsed.issues);
      return message;
    }
    try {
      const out = histRef.current!.apply({ type: 'load_project', project: parsed.project });
      if (out.refused) { setError(out.refused); setIssues(out.issues); return out.refused; }
      const text = JSON.stringify(histRef.current!.current());
      setSavedText(text);
      setError(persistSnapshot(key, histRef.current!.current()));
      setIssues([]); setVersion((v) => v + 1); return null;
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
    doc, dirty, error, issues,
    canUndo: histRef.current.canUndo(), canRedo: histRef.current.canRedo(),
    isCustom: doc.presetHint === null,
    run, undo, redo, loadPreset, loadJson, serialize,
  };
}
