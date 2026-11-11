import { useCallback, useSyncExternalStore } from 'react';

// One measured-channel selection shared by every Analysis surface. The window
// matrix, the channel list, the detail panel and the delay scatter are separate
// sections, so picking a channel in one of them has to reach the others without
// threading state through the whole page. Selection is keyed by run: switching
// runs must never leave a channel id from the previous run selected.

type Selection = { runId: string; id: string };
type Listener = () => void;

let selection: Selection = { runId: '', id: '' };
const listeners = new Set<Listener>();

const read = () => selection;
const subscribe = (listener: Listener) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

export function setMeasuredChannel(runId: string, id: string): void {
  if (selection.runId === runId && selection.id === id) return;
  selection = { runId, id };
  for (const listener of [...listeners]) listener();
}

/** Returns the selected measured-channel id for this run ('' when none) and a setter. */
export function useChannelSelection(runId: string): [string, (id: string) => void] {
  const current = useSyncExternalStore(subscribe, read, read);
  const id = current.runId === runId ? current.id : '';
  const select = useCallback((next: string) => setMeasuredChannel(runId, next), [runId]);
  return [id, select];
}

/** Brings the detail panel into view after a pick made outside it. The jump
 *  is immediate so a second pick cannot race a still-running scroll. */
export function revealChannelDetail(): void {
  const target = document.getElementById('measured-channel-detail');
  target?.scrollIntoView({ block: 'center', behavior: 'auto' });
}
