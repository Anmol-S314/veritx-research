import { useCallback, useEffect, useState } from 'react';
import type { LoadedProject } from './project';
import { ActionBar, Notice } from './ui';
import { LiveWorkloadPage } from './WorkloadStudio';
import { LiveRequirementsPage } from './RequirementsStudio';
import { LiveValidatePage } from './ValidationStudio';
import { DraftEditor } from './DraftEditor';
import type { IntentActionState, IntentSaveState, IntentTab } from './intent';

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
  tabs = TABS.map(item => item.id),
  actions,
  onDirtyChange,
}: {
  project: LoadedProject;
  notify: (message: string) => void;
  tab: IntentTab;
  onTabChange: (tab: IntentTab) => void;
  tabs?: IntentTab[];
  actions: (state: IntentActionState) => React.ReactNode;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [saveState, setSaveState] = useState<{ tab: IntentTab; state: IntentSaveState } | null>(null);
  const [dirty, setDirty] = useState<{ tab: IntentTab; value: boolean } | null>(null);
  const handleSaveState = useCallback((state: IntentSaveState) => setSaveState({ tab, state }), [tab]);
  const handleDirty = useCallback((value: boolean) => setDirty({ tab, value }), [tab]);
  const currentSave = saveState?.tab === tab ? saveState.state : null;
  const activeDirty = currentSave?.dirty ?? (dirty?.tab === tab ? dirty.value : false);

  useEffect(() => {
    onDirtyChange?.(activeDirty);
  }, [activeDirty, onDirtyChange]);

  const switchTab = (next: IntentTab) => {
    if (next === tab) return;
    if (activeDirty && !window.confirm('Discard unsaved changes in this tab? They have not been saved to the gateway.')) return;
    onDirtyChange?.(false);
    onTabChange(next);
  };

  return <div className="intent-workspace">
    <div className="intent-tabs" role="tablist" aria-label="Intent sections">
      {TABS.filter(item => tabs.includes(item.id)).map(item => <button key={item.id} type="button" role="tab" aria-selected={tab === item.id}
        className={tab === item.id ? 'active' : ''} onClick={() => switchTab(item.id)}>{item.label}</button>)}
    </div>
    <div className="intent-body">
      {tab === 'workload' && <LiveWorkloadPage project={project} notify={notify} embedded onDirty={handleDirty} onSaveState={handleSaveState} />}
      {tab === 'fabric' && <DraftEditor project={project} embedded onDirty={handleDirty} onSaveState={handleSaveState} />}
      {tab === 'requirements' && <LiveRequirementsPage project={project} notify={notify} embedded onDirty={handleDirty} onSaveState={handleSaveState} />}
      {tab === 'validate' && <LiveValidatePage project={project} embedded />}
    </div>
    <ActionBar sticky={false} className="intent-action-bar" status={<>
      {activeDirty && currentSave && !currentSave.valid && <span className="muted">Fix the issues above before saving.</span>}
      {activeDirty && !currentSave && tab === 'validate' && <span className="muted">Validation is read-only.</span>}
      {currentSave?.error && <Notice tone="red">{currentSave.error}</Notice>}
    </>}>
      {actions({ save: currentSave, dirty: activeDirty })}
    </ActionBar>
  </div>;
}
