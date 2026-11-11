export type IntentTab = 'workload' | 'fabric' | 'requirements' | 'validate';

/** The active editor's save affordance, reported to the one Intent status bar. */
export type IntentSaveState = {
  dirty: boolean;
  valid: boolean;
  busy: boolean;
  error: string;
  save: () => void;
};
