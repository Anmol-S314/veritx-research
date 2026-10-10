/** React binding for the draft mutation seam: one working copy, one history,
 *  one save path.
 *
 * The store owns no validation. It applies typed commands to the working
 *  copy, and on save hands the WHOLE document to `api.putDraft`, which is the
 *  existing server-validated seam (`parse_request_doc` refuses unknown keys,
 *  recomputes the design hash and marks the draft dirty). A refused command
 *  never mutates; a refused save keeps the working copy and surfaces the
 *  server's reason — the UI never decides that an edit was legal.
 *
 * Undo/redo operates on command snapshots (see draftCommands.ts), not on
 *  component state, and autosave does not clear the stacks: a successful PUT
 *  re-anchors them by resetting history to the saved document, because the
 *  stacks before it described a document the server has now accepted and
 *  frozen as the new dirty baseline.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { editableDocument } from '../../canonicalDraft';
import { DraftHistory, type CommandOutcome, type DraftCommand } from './draftCommands';

export function useServerDraftSync(
  source: string,
  doc: Record<string, unknown> | null,
  dirty: boolean,
  load: (doc: Record<string, unknown>) => void,
): void {
  const loadedSource = useRef<string | null>(null);
  useEffect(() => {
    if (!doc || dirty || loadedSource.current === source) return;
    load(doc);
    loadedSource.current = source;
  }, [source, doc, dirty, load]);
}

export interface DraftStore {
  /** The working copy commands apply to (server draft until edited). */
  doc: Record<string, unknown> | null;
  /** True when the working copy differs from what the server last served. */
  dirty: boolean;
  saving: boolean;
  /** Server or command failure, verbatim; null when healthy. */
  error: string | null;
  canUndo: boolean;
  canRedo: boolean;
  /** Apply a typed command. Returns the outcome (refusal reasons included). */
  run: (command: DraftCommand) => CommandOutcome;
  undo: () => void;
  redo: () => void;
  /** PUT the whole working copy; on success history re-anchors. */
  save: () => Promise<boolean>;
  /** Adopt a fresh server document (initial load / external change). */
  load: (doc: Record<string, unknown>) => void;
}

export function useDraftStore(projectId: string): DraftStore {
  const historyRef = useRef<DraftHistory | null>(null);
  const baselineRef = useRef<string>('');
  const [version, setVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bump = (): void => setVersion((v) => v + 1);

  const load = useCallback((doc: Record<string, unknown>): void => {
    historyRef.current = new DraftHistory(doc);
    baselineRef.current = JSON.stringify(doc);
    setError(null);
    bump();
  }, []);

  const run = useCallback((command: DraftCommand): CommandOutcome => {
    const h = historyRef.current;
    if (!h) {
      const outcome = {
        doc: {}, refused: 'no draft is loaded yet',
        inverse: null,
      } as CommandOutcome;
      return outcome;
    }
    const outcome = h.apply(command);
    if (outcome.refused !== null) {
      setError(outcome.refused);
    } else {
      setError(null);
      bump();
    }
    return outcome;
  }, []);

  const undo = useCallback((): void => {
    if (historyRef.current?.undo()) { setError(null); bump(); }
  }, []);

  const redo = useCallback((): void => {
    if (historyRef.current?.redo()) { setError(null); bump(); }
  }, []);

  const save = useCallback(async (): Promise<boolean> => {
    const h = historyRef.current;
    if (!h || !projectId) return false;
    setSaving(true);
    setError(null);
    try {
      // Copy-on-write commands keep this submitted snapshot immutable while
      // later edits remain local if the request is still in flight.
      const submitted = h.current();
      const submittedText = JSON.stringify(submitted);
      // Whole document through the existing validated seam. The server
      // re-parses, recomputes the design hash and marks the draft dirty —
      // the store never computes identity itself.
      const saved = await api.putDraft(projectId, editableDocument(submitted));
      const persisted = saved.request ?? submitted;
      baselineRef.current = JSON.stringify(persisted);
      // Re-anchor history only if no newer local state arrived during the
      // request. Otherwise keep the newer edits and their undo history dirty.
      if (JSON.stringify(h.current()) === submittedText) h.reset(persisted);
      bump();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setSaving(false);
    }
  }, [projectId]);

  // Derived state re-computed per render (version forces the pass).
  void version;
  const h = historyRef.current;
  const doc = h ? h.current() : null;
  const dirty = h !== null
    && JSON.stringify(h.current()) !== baselineRef.current;
  const canUndo = h?.canUndo() ?? false;
  const canRedo = h?.canRedo() ?? false;

  return { doc, dirty, saving, error, canUndo, canRedo,
           run, undo, redo, save, load };
}
