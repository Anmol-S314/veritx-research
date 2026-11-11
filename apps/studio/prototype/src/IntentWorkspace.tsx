import { useCallback, useEffect, useState } from 'react';
import type { LoadedProject } from './project';
import { DraftContext } from './draftSave';
import { Badge, Button, Notice } from './ui';
import { LiveWorkloadPage } from './WorkloadStudio';
import { LiveRequirementsPage } from './RequirementsStudio';
import { LiveValidatePage } from './ValidationStudio';
import { DraftEditor } from './DraftEditor';
import type { IntentSaveState, IntentTab } from './intent';

const TABS: { id: IntentTab; label: string }[] = [
  { id: 'workload', label: 'Workload' },
  { id: 'requirements', label: 'Requirements' },
  { id: 'fabric', label: 'Fabric' },
  { id: 'validate', label: 'Validate' },
];

export function IntentWorkspace({
  project,
  notify,
  tab,
  onTabChange,
  onCompile,
  compileBusy = false,
  onDirtyChange,
}: {
  project: LoadedProject;
  notify: (message: string) => void;
  tab: IntentTab;
  onTabChange: (tab: IntentTab) => void;
  onCompile: () => void;
  compileBusy?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [saveState, setSaveState] = useState<IntentSaveState | null>(null);
  const [dirty, setDirty] = useState(false);
  const handleSaveState = useCallback((state: IntentSaveState) => setSaveState(state), []);
  const handleDirty = useCallback((next: boolean) => setDirty(next), []);
  const activeDirty = saveState?.dirty ?? dirty;

  useEffect(() => {
    setSaveState(null);
    setDirty(false);
    onDirtyChange?.(false);
    // The parent owns the selected tab; reset the active editor's reported
    // state when the tab changes so a stale save action cannot be invoked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  useEffect(() => {
    onDirtyChange?.(activeDirty);
  }, [activeDirty, onDirtyChange]);

  const switchTab = (next: IntentTab) => {
    if (next === tab) return;
    if (activeDirty && !window.confirm('Discard unsaved changes in this tab? They have not been saved to the gateway.')) return;
    onDirtyChange?.(false);
    onTabChange(next);
  };

  const savedDirty = project.draftMeta?.dirty === true;
  const saveBlocked = !saveState
    ? 'No save action for this tab'
    : !saveState.dirty
      ? 'No unsaved changes'
      : !saveState.valid
        ? 'Validate the draft before saving'
        : saveState.busy
          ? 'Saving'
          : '';
  const statusTone = activeDirty || savedDirty ? 'amber' : 'green';
  const statusText = activeDirty
    ? 'Unsaved changes in this tab.'
    : savedDirty
      ? 'Saved draft differs from the revision.'
      : 'Draft matches the revision.';

  return <div className="intent-workspace">
    <DraftContext project={project} />
    <div className="intent-tabs" role="tablist" aria-label="Intent sections">
      {TABS.map(item => <button key={item.id} type="button" role="tab" aria-selected={tab === item.id}
        className={tab === item.id ? 'active' : ''} onClick={() => switchTab(item.id)}>{item.label}</button>)}
    </div>
    <div className="intent-body">
      {tab === 'workload' && <LiveWorkloadPage project={project} notify={notify} embedded onDirty={handleDirty} onSaveState={handleSaveState} />}
      {tab === 'fabric' && <DraftEditor project={project} embedded onDirty={handleDirty} onSaveState={handleSaveState} />}
      {tab === 'requirements' && <LiveRequirementsPage project={project} notify={notify} embedded onDirty={handleDirty} onSaveState={handleSaveState} />}
      {tab === 'validate' && <LiveValidatePage project={project} embedded />}
    </div>
    <div className="intent-status">
      <div className="intent-status-copy">
        <Badge tone={statusTone}>{statusText}</Badge>
        {activeDirty && saveState && !saveState.valid && <span className="muted">Fix the issues above before saving.</span>}
        {activeDirty && !saveState && tab === 'validate' && <span className="muted">Validation is read-only.</span>}
        {!activeDirty && savedDirty && <span className="muted">Compile to publish the saved draft as a revision.</span>}
        {!activeDirty && !savedDirty && <span className="muted">No draft changes to save.</span>}
        {saveState?.error && <Notice tone="red">{saveState.error}</Notice>}
      </div>
      <div className="actions">
        {saveState?.save && <Button disabled={!saveState.dirty || !saveState.valid || saveState.busy} title={saveBlocked || undefined} onClick={saveState.save}>{saveState.busy ? 'Saving…' : 'Save draft'}</Button>}
        <Button primary disabled={compileBusy || activeDirty || saveState?.busy || !project.request} onClick={onCompile}>{compileBusy ? 'Compiling…' : 'Compile draft'}</Button>
      </div>
    </div>
  </div>;
}
