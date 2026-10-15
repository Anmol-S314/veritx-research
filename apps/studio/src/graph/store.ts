/** useGraphStore: project-scoped graph history, dirty state, and local recovery. */
import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react';
import { GraphHistory, type GraphCommand } from './history';
import { buildPreset, type PresetId } from './presets';
import { parseProject, type LoomProject } from './project';
import { graphFromDocument, parseProjectDocument } from '../project/document';

const KEY = 'loom-graph-autosave-v1';

type Entry = {
  history: GraphHistory;
  savedText: string;
  error: string | null;
  revision: number;
  listeners: Set<() => void>;
  timer: ReturnType<typeof setTimeout> | null;
};
const entries = new Map<string, Entry>();
let activeScope: string | null = null;
const mountedScopes: string[] = [];
let keydownUsers = 0;

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

function emit(entry: Entry): void {
  entry.revision += 1;
  entry.listeners.forEach((listener) => listener());
}

function initialize(initial: PresetId, scope: string): Entry {
  const key = `${KEY}:${scope}`;
  let doc: LoomProject | null = null;
  let savedText = '';
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      doc = parseProject(raw);
      savedText = JSON.stringify(doc);
    }
  } catch { /* invalid recovery data falls back to a preset */ }
  doc ??= buildPreset(initial);
  const currentText = JSON.stringify(doc);
  return {
    history: new GraphHistory(doc), savedText: savedText || currentText,
    error: null, revision: 0, listeners: new Set(), timer: null,
  };
}

function entryFor(initial: PresetId, scope: string): Entry {
  let entry = entries.get(scope);
  if (!entry) {
    entry = initialize(initial, scope);
    entries.set(scope, entry);
  }
  return entry;
}

function persist(entry: Entry, scope: string, snapshot: string): void {
  try {
    localStorage.setItem(`${KEY}:${scope}`, snapshot);
    entry.savedText = snapshot;
    entry.error = null;
  } catch (e) {
    entry.error = `Could not save graph recovery data: ${e instanceof Error ? e.message : String(e)}`;
  }
  emit(entry);
}

function changed(entry: Entry, scope: string): void {
  emit(entry);
  persist(entry, scope, JSON.stringify(entry.history.current()));
  if (entry.timer !== null) clearTimeout(entry.timer);
  entry.timer = setTimeout(() => {
    entry.timer = null;
    persist(entry, scope, JSON.stringify(entry.history.current()));
  }, 500);
}

function onKeydown(e: KeyboardEvent): void {
  if (!activeScope || !(e.ctrlKey || e.metaKey)) return;
  const entry = entries.get(activeScope);
  if (!entry) return;
  const key = e.key.toLowerCase();
  if (key === 'z' && !e.shiftKey) {
    if (entry.history.undo()) { e.preventDefault(); entry.error = null; changed(entry, activeScope); }
  } else if (key === 'y' || (key === 'z' && e.shiftKey)) {
    if (entry.history.redo()) { e.preventDefault(); entry.error = null; changed(entry, activeScope); }
  }
}

export function useGraphStore(initial: PresetId = 'mesh-4x4', scope = 'local'): GraphStore {
  const entry = entryFor(initial, scope);
  useEffect(() => {
    mountedScopes.push(scope);
    activeScope = scope;
    if (keydownUsers++ === 0) window.addEventListener('keydown', onKeydown);
    return () => {
      keydownUsers -= 1;
      const index = mountedScopes.lastIndexOf(scope);
      if (index >= 0) mountedScopes.splice(index, 1);
      activeScope = mountedScopes[mountedScopes.length - 1] ?? null;
      if (keydownUsers === 0) window.removeEventListener('keydown', onKeydown);
    };
  }, [scope]);
  const subscribe = useCallback((listener: () => void) => {
    entry.listeners.add(listener);
    return () => {
      entry.listeners.delete(listener);
      if (entry.listeners.size === 0 && entry.timer !== null) {
        clearTimeout(entry.timer);
        entry.timer = null;
      }
    };
  }, [entry]);
  const getSnapshot = useCallback(() => entry.revision, [entry]);
  const revision = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const doc = entry.history.current();
  const text = JSON.stringify(doc);
  const dirty = text !== entry.savedText;
  useEffect(() => {
    if (!dirty) return;
    if (entry.timer !== null) clearTimeout(entry.timer);
    entry.timer = setTimeout(() => {
      entry.timer = null;
      persist(entry, scope, JSON.stringify(entry.history.current()));
    }, 500);
    // The timer belongs to the shared scope, not this hook consumer. The last
    // subscriber's unsubscribe cleanup cancels it when nobody can observe it.
  }, [dirty, entry, scope, revision]);

  const run = useCallback((cmd: GraphCommand): string | null => {
    const out = entry.history.apply(cmd);
    if (out.refused) { entry.error = out.refused; emit(entry); return out.refused; }
    entry.error = null;
    changed(entry, scope);
    return null;
  }, [entry, scope]);
  const undo = useCallback(() => {
    if (!entry.history.undo()) return;
    entry.error = null;
    changed(entry, scope);
  }, [entry, scope]);
  const redo = useCallback(() => {
    if (!entry.history.redo()) return;
    entry.error = null;
    changed(entry, scope);
  }, [entry, scope]);
  const loadPreset = useCallback((id: PresetId) => {
    const out = entry.history.apply({ type: 'replace_project', doc: buildPreset(id) });
    if (out.refused) { entry.error = out.refused; emit(entry); return; }
    entry.error = null;
    changed(entry, scope);
  }, [entry, scope]);
  const loadJson = useCallback((json: string): string | null => {
    try {
      // Accept both the unified project document and the legacy flat graph
      // form; the editor state is graph-scoped, so sections fold back in.
      const parsed = graphFromDocument(parseProjectDocument(json));
      entry.history.reset(parsed);
      entry.error = null;
      changed(entry, scope);
      return null;
    } catch (e) { return e instanceof Error ? e.message : String(e); }
  }, [entry, scope]);
  const serialize = useCallback(() => JSON.stringify(entry.history.current(), null, 2), [entry]);

  return useMemo(() => ({
    doc, dirty, error: entry.error,
    canUndo: entry.history.canUndo(), canRedo: entry.history.canRedo(),
    isCustom: doc.presetHint === null,
    run, undo, redo, loadPreset, loadJson, serialize,
  }), [doc, dirty, entry, entry.error, revision, run, undo, redo, loadPreset, loadJson, serialize]);
}
