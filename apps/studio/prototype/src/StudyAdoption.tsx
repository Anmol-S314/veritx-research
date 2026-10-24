import { useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useProject, type LoadedProject } from './project';
import { Button, Field, Notice, Properties, Section } from './ui';

export function StudyAdoption({ project, study }: { project: LoadedProject; study: Record<string, any> }) {
  const { health, reload } = useProject();
  const [selected, setSelected] = useState(''), [approved, setApproved] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const candidates = (study.study?.candidates ?? []).filter((c: any) => ['COMPILED', 'SUCCEEDED'].includes(c.compilation_status) && Object.keys(c.guided_patch ?? {}).length);
  const candidate = candidates.find((c: any) => c.candidate_id === selected);
  const current = project.draftMeta?.design_hash;
  const eligible = health?.features?.optimization_adoption_preconditions && study.project_id === project.detail.project.project_id && study.base_revision_id === project.detail.active_revision_id && project.draftMeta?.dirty === false && !!current;
  const adopt = async () => {
    if (!eligible || !approved || !candidate || !current || busy) return;
    setBusy(true); setError('');
    try { await gateway.adoptOptimization(study.optimization_id, candidate.candidate_id, current); setApproved(false); reload(); }
    catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  return <Section title="Reviewed candidate adoption"><Notice>Creates an editable draft from the study baseline and selected patch. The previous complete draft is archived; compiled revisions and evidence are unchanged.</Notice>
    {!eligible && <Notice tone="amber">Requires an upgraded gateway, the same active baseline revision, and a clean compiled draft.</Notice>}
    <Field label="Candidate to adopt"><select value={selected} onChange={e => { setSelected(e.target.value); setApproved(false); }}><option value="">Select a compiled candidate…</option>{candidates.map((c: any) => <option key={c.candidate_id}>{c.candidate_id}</option>)}</select></Field>
    {candidate && <><Properties rows={[[ 'Study baseline', study.base_revision_id ], ['Expected draft hash', current ?? 'Missing' ], ['Reviewed parameter patch', JSON.stringify(candidate.guided_patch) ], ['Current requirements', 'Preserved from the study baseline; compliance not implied' ]]} /><label className="check-row"><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} />Apply this reviewed candidate to the draft. I understand re-evaluation is required.</label></>}
    <Button primary disabled={!eligible || !candidate || !approved || busy} onClick={adopt}>{busy ? 'Adopting…' : 'Adopt candidate with recovery snapshot'}</Button>{error && <Notice tone="red">{error}</Notice>}
  </Section>;
}
