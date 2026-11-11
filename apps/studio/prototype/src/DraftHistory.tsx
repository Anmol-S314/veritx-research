import { useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useGatewayDocument } from './LiveOperations';
import { useProject, type LoadedProject } from './project';
import { Button, Notice, Properties, Section } from './ui';

export function DraftHistory({ project }: { project: LoadedProject }) {
  const { health, reload } = useProject();
  const id = project.detail.project.project_id, revisionToken = project.draftMeta?.revisionToken;
  const enabled = health?.features?.optimization_adoption_preconditions === true;
  const { data, error } = useGatewayDocument(`draft-history:${id}:${revisionToken}:${enabled}`, () => enabled ? gateway.draftHistory(id) : Promise.resolve({ snapshots: [] }));
  const [selected, setSelected] = useState(''), [approved, setApproved] = useState(false), [busy, setBusy] = useState(false), [failure, setFailure] = useState('');
  if (!enabled || !data?.snapshots?.length) return error ? <Notice tone="red">{error}</Notice> : null;
  return <Section title="Preserved draft snapshots"><select aria-label="Draft snapshot to restore" value={selected} onChange={e => { setSelected(e.target.value); setApproved(false); }}><option value="">Select a snapshot…</option>{data.snapshots.map((s: any) => <option key={s.snapshot_id} value={s.snapshot_id}>{s.snapshot_id}</option>)}</select>
    {selected && <><Properties rows={[[ 'Restore consequence', 'Replace the draft; preserve the displaced draft as another snapshot' ], ['Compiled revisions / evidence', 'Unchanged' ]]} /><label className="check-row"><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} />Restore this snapshot as the working draft.</label></>}
    <Button disabled={!selected || !approved || !revisionToken || busy} onClick={async () => { if (!revisionToken) return; setBusy(true); setFailure(''); try { await gateway.restoreDraft(id, selected, revisionToken); setSelected(''); setApproved(false); reload(); } catch (e) { setFailure(gatewayReason(e)); } finally { setBusy(false); } }}>Restore reviewed snapshot</Button>{failure && <Notice tone="red">{failure}</Notice>}
  </Section>;
}
