export type IntentTab = 'workload' | 'fabric' | 'requirements' | 'validate';

/** The active editor's save affordance, reported to the one Intent status bar. */
export type IntentSaveState = {
  dirty: boolean;
  valid: boolean;
  busy: boolean;
  error: string;
  save: () => void;
};

/** What a workflow step needs to render its own primary action. The workspace
 *  owns draft state; callers only decide what the next move is. */
export type IntentActionState = {
  save: IntentSaveState | null;
  dirty: boolean;
};
