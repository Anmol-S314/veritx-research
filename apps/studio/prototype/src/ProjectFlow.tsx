import { useEffect, useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useProject } from './project';
import type { LoadedProject } from './project';
import { Badge, Button, Notice, PageLink, Section } from './ui';
import { DraftEditor } from './DraftEditor';
import { DraftHistory } from './DraftHistory';
import { TopologyGraph } from './TopologyGraph';

type WorkloadEntry = { workload_id: string; display_name?: string };

function Step({ index, title, summary, actions, children }: {
  index: number; title: string; summary: React.ReactNode; actions?: React.ReactNode; children?: React.ReactNode;
}) {
  return <div className="flow-step">
    <div className="flow-head">
      <span className="flow-index" aria-hidden="true">{index}</span>
      <div className="flow-title"><strong>{title}</strong><span>{summary}</span></div>
      <div className="actions">{actions}</div>
    </div>
    {children && <div className="flow-body">{children}</div>}
  </div>;
}

const short = (value?: string | null) => (value ? `${value.slice(0, 18)}…` : '—');

export function ProjectFlow({ active }: { active: LoadedProject }) {
  const { reload, clear, refreshList } = useProject();
  const [panel, setPanel] = useState<'workload' | 'rename' | 'delete' | null>(null);
  const [editorOpen, setEditorOpen] = useState(active.draftMeta?.dirty === true);
  const [showLayout, setShowLayout] = useState(false);
  const [rename, setRename] = useState(active.detail.project.name);
  const [workloads, setWorkloads] = useState<WorkloadEntry[]>([]);
  const [workloadId, setWorkloadId] = useState('');
  const [confirmId, setConfirmId] = useState('');
  const [busy, setBusy] = useState<'rename' | 'delete' | 'compile' | 'workload' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const detail = active.detail;
  const design = (detail.active_revision?.design ?? {}) as Record<string, any>;
  const runs = detail.runs ?? [];
  const topology = active.topology;
  const revisionId = detail.active_revision_id;
  const workloadName = (active.request?.workload?.model_name || detail.draft?.workload_id || 'no workload') as string;
  const tileAgents = (active.request?.agents ?? design.agents ?? []).filter((a: any) => a.kind === 'compute_tile').reduce((n: number, a: any) => n + (a.count ?? 0), 0);

  useEffect(() => { setRename(detail.project.name); }, [detail.project.name]);
  useEffect(() => { gateway.workloads().then(setWorkloads).catch(() => setWorkloads([])); }, []);
  useEffect(() => {
    const openEditor = () => setEditorOpen(true);
    window.addEventListener('srota:open-draft-editor', openEditor);
    return () => window.removeEventListener('srota:open-draft-editor', openEditor);
  }, []);
  useEffect(() => { setEditorOpen(active.draftMeta?.dirty === true); setPanel(null); }, [detail.project.project_id, active.draftMeta?.dirty]);

  const run = async (kind: 'rename' | 'delete' | 'compile' | 'workload', action: () => Promise<void>) => {
    setBusy(kind); setError(null);
    try { await action(); setPanel(null); } catch (caught) { setError(gatewayReason(caught)); } finally { setBusy(null); }
  };
  const toggle = (next: 'workload' | 'rename' | 'delete') => setPanel(current => current === next ? null : next);
  const dirty = active.draftMeta?.dirty === true;
  const latest = runs[0];

  return <Section title={`Workflow · ${detail.project.name}`} actions={<>
    {topology ? <Badge tone="blue">Live store</Badge> : <Badge tone="amber">No topology</Badge>}
  </>}>
    <Step index={1} title="Project"
      summary={<><span className="mono">{detail.project.project_id}</span> · {workloadName}{workloadName === 'no workload' ? '' : ` · TP${active.request?.workload?.tp ?? '—'} DP${active.request?.workload?.dp ?? '—'} EP${active.request?.workload?.ep ?? '—'} PP${active.request?.workload?.pp ?? '—'}`}</>}
      actions={<>
        <Button aria-pressed={panel === 'workload'} onClick={() => toggle('workload')}>Set workload</Button>
        <Button aria-pressed={panel === 'rename'} onClick={() => toggle('rename')}>Rename</Button>
      </>}>
      {panel === 'workload' && <div className="toolbar">
        <select aria-label="Catalog workload" value={workloadId} onChange={e => setWorkloadId(e.target.value)}>
          <option value="">Select a catalog workload…</option>
          {workloads.map(w => <option key={w.workload_id} value={w.workload_id}>{w.display_name ?? w.workload_id}</option>)}
        </select>
        <Button primary disabled={busy !== null || !workloadId} onClick={() => run('workload', async () => { await gateway.selectWorkload(detail.project.project_id, workloadId); reload(); })}>{busy === 'workload' ? 'Applying…' : 'Apply workload'}</Button>
        <span className="muted">Changing the workload needs step 3 again.</span>
      </div>}
      {panel === 'rename' && <div className="toolbar">
        <input aria-label="Project name" value={rename} onChange={e => setRename(e.target.value)} />
        <Button primary disabled={busy !== null || !rename.trim() || rename === detail.project.name}
          onClick={() => run('rename', async () => { await gateway.renameProject(detail.project.project_id, rename.trim()); reload(); })}>{busy === 'rename' ? 'Renaming…' : 'Save name'}</Button>
      </div>}
    </Step>

    <Step index={2} title="Draft intent"
      summary={<>{active.request?.topology?.kind ?? active.request?.noc_config?.topology_family ?? 'no fabric'} · {tileAgents} compute tiles · {detail.draft?.workload_id ?? 'no workload'} {dirty ? '· uncompiled changes' : '· compiled'}</>}
      actions={<>
        <Badge tone={dirty ? 'amber' : 'green'}>{dirty ? 'uncompiled' : 'compiled'}</Badge>
        <Button primary onClick={() => setEditorOpen(open => !open)}>{editorOpen ? 'Close editor' : 'Edit draft'}</Button>
      </>}>
      {editorOpen && <DraftEditor project={active} />}
    </Step>

    <Step index={3} title="Revision"
      summary={revisionId
        ? <><span className="mono">{revisionId}</span> · {topology ? `${topology.counts?.routers ?? 0} routers · ${topology.counts?.channels ?? topology.channels.length} channels · ${topology.counts?.endpoints ?? 0} endpoints` : 'no topology published'} · design {short(detail.active_revision?.design_hash)}</>
        : 'Nothing compiled yet.'}
      actions={<>
        {topology && <Button aria-pressed={showLayout} onClick={() => setShowLayout(open => !open)}>{showLayout ? 'Hide layout' : 'Show layout'}</Button>}
        <Button primary disabled={busy !== null} onClick={() => run('compile', async () => { await gateway.compileProject(detail.project.project_id, active.draftMeta?.design_hash); reload(); })}>{busy === 'compile' ? 'Compiling…' : 'Compile draft'}</Button>
      </>}>
      {topology && showLayout && <TopologyGraph topology={topology} />}
    </Step>

    <Step index={4} title="Evaluation"
      summary={runs.length
        ? <>{runs.length} run{runs.length === 1 ? '' : 's'} · latest <span className="mono">{latest?.run_id.slice(0, 13)}…</span> {latest?.status} · {latest?.requirements_pass === true ? 'requirements pass' : latest?.requirements_pass === false ? 'requirements fail' : 'requirements not recorded'}</>
        : 'No run yet.'}
      actions={<PageLink page="analysis/summary" primary>Open analysis</PageLink>}>
      {runs.length ? <div className="table-scroll"><table><thead><tr><th>Run</th><th>Revision</th><th>Backend</th><th>Status</th><th>Requirements</th><th>Bundle</th></tr></thead><tbody>
        {runs.map(entry => <tr key={entry.run_id}>
          <th className="mono">{entry.run_id.slice(0, 13)}…<br /><small>{entry.display_name ?? ''}</small></th>
          <td className="mono">{entry.revision_id}</td>
          <td className="mono">{entry.backend ?? '—'}</td>
          <td><Badge tone={entry.status === 'EVALUATED' ? 'green' : entry.status === 'FAILED' ? 'red' : 'amber'}>{entry.status}</Badge></td>
          <td>{entry.requirements_pass === undefined ? 'Not recorded' : entry.requirements_pass ? 'Pass' : 'Fail'}</td>
          <td className="mono">{entry.bundle_id ? short(entry.bundle_id) : 'No bundle'}</td>
        </tr>)}
      </tbody></table></div> : <Notice tone="amber">Design intent exists without evaluation evidence. Nothing is inferred from the absence of a run.</Notice>}
    </Step>

    <DraftHistory key={`${detail.project.project_id}:${active.draftMeta?.design_hash}`} project={active} />
    {error && <Notice tone="red">{error}</Notice>}
    <div className="flow-danger">
      {panel === 'delete'
        ? <><input aria-label="Delete confirmation" value={confirmId} placeholder={`Type ${detail.project.project_id}`} onChange={e => setConfirmId(e.target.value)} />
          <Button danger disabled={busy !== null || confirmId !== detail.project.project_id} onClick={() => run('delete', async () => {
            await gateway.deleteProject(detail.project.project_id);
            clear(); refreshList();
          })}>{busy === 'delete' ? 'Deleting…' : 'Delete permanently'}</Button>
          <span className="muted">Removes the project directory, its revisions and runs.</span></>
        : <Button danger onClick={() => toggle('delete')}>Delete project…</Button>}
    </div>
  </Section>;
}
