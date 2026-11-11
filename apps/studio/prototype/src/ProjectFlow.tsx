import { useEffect, useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useProject } from './project';
import type { LoadedProject } from './project';
import { Assumptions, Badge, Button, Notice, PageLink, Section } from './ui';
import { DraftHistory } from './DraftHistory';
import { TopologyGraph } from './TopologyGraph';
import { revisionLabel, runVersionLabels } from './runLabel';
import { RevisionHistory } from './RevisionHistory';
import { IntentWorkspace } from './IntentWorkspace';
import type { IntentTab } from './intent';

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

export function ProjectFlow({ active, notify }: { active: LoadedProject; notify: (message: string) => void }) {
  const { reload, clear, refreshList, loadRun, run: runState } = useProject();
  const [panel, setPanel] = useState<'rename' | 'delete' | null>(null);
  const [intentTab, setIntentTab] = useState<IntentTab>(() => {
    try {
      const value = sessionStorage.getItem(`srota-intent-tab:${active.detail.project.project_id}`);
      return value === 'workload' || value === 'fabric' || value === 'requirements' || value === 'validate' ? value : 'workload';
    } catch { return 'workload'; }
  });
  const [intentDirty, setIntentDirty] = useState(false);
  const [showLayout, setShowLayout] = useState(false);
  const [rename, setRename] = useState(active.detail.project.name);
  const [confirmId, setConfirmId] = useState('');
  const [busy, setBusy] = useState<'rename' | 'delete' | 'compile' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const detail = active.detail;
  const design = (detail.active_revision?.design ?? {}) as Record<string, any>;
  const revisions = detail.revisions ?? [];
  const runs = detail.runs ?? [];
  const topology = active.topology;
  const revisionId = detail.active_revision_id;
  const activeRevision = revisions.find(revision => revision.revision_id === revisionId) ?? null;
  const selectedRunId = runState.phase === 'loaded' && runState.data.detail.project_id === detail.project.project_id
    ? runState.data.detail.run_id
    : runState.phase === 'loading' && runs.some(run => run.run_id === runState.runId)
      ? runState.runId
      : null;
  const openRun = (runId: string) => {
    if (!runId) return;
    loadRun(runId);
    window.location.hash = '/analysis/summary';
  };
  const workloadName = (active.request?.workload?.model_name || detail.draft?.workload_id || 'no workload') as string;
  const tileAgents = (active.request?.agents ?? design.agents ?? []).filter((a: any) => a.kind === 'compute_tile').reduce((n: number, a: any) => n + (a.count ?? 0), 0);

  useEffect(() => { setRename(detail.project.name); }, [detail.project.name]);
  useEffect(() => {
    try { sessionStorage.setItem(`srota-intent-tab:${detail.project.project_id}`, intentTab); } catch { /* Remembering the tab is optional. */ }
  }, [detail.project.project_id, intentTab]);
  useEffect(() => {
    const openEditor = () => setIntentTab('fabric');
    window.addEventListener('srota:open-draft-editor', openEditor);
    return () => window.removeEventListener('srota:open-draft-editor', openEditor);
  }, []);
  useEffect(() => { setPanel(null); }, [detail.project.project_id]);

  const run = async (kind: 'rename' | 'delete' | 'compile', action: () => Promise<void>) => {
    setBusy(kind); setError(null);
    try { await action(); setPanel(null); } catch (caught) { setError(gatewayReason(caught)); } finally { setBusy(null); }
  };
  const toggle = (next: 'rename' | 'delete') => setPanel(current => current === next ? null : next);
  const dirty = active.draftMeta?.dirty === true;
  const draftTopology = active.request?.topology as Record<string, any> | undefined;
  const draftKind = draftTopology?.kind ?? active.request?.noc_config?.topology_family ?? 'no fabric';
  const draftSide = typeof draftTopology?.side_length === 'number' ? draftTopology.side_length : null;
  const draftFabric = draftTopology?.kind === 'explicit'
    ? `explicit · ${draftTopology.graph?.nodes ?? '?'} nodes`
    : draftSide ? `${draftKind} ${draftSide}×${draftSide}` : draftKind;
  const trafficClasses = new Set((active.request?.workload?.collectives ?? []).map(collective => collective.traffic_class).filter((value): value is string => Boolean(value)));
  const criteriaClasses = new Set((active.request?.requirements ?? []).map(requirement => requirement.traffic_class).filter((value): value is string => Boolean(value)));
  const missingCriteria = [...trafficClasses].some(value => !criteriaClasses.has(value));
  const intentStart: IntentTab = !active.request?.workload?.model_name
    ? 'workload'
    : missingCriteria
      ? 'requirements'
      : !(active.request?.topology?.kind || active.request?.noc_config?.topology_family)
        ? 'fabric'
        : 'fabric';
  const runLabels = runVersionLabels(runs);
  const latest = [...runs].sort((a, b) => String(b.completed_at ?? '').localeCompare(String(a.completed_at ?? '')))[0];
  const activeRuns = [...runs]
    .filter(entry => entry.revision_id === detail.active_revision_id)
    .sort((a, b) => String(a.completed_at ?? '').localeCompare(String(b.completed_at ?? '')));
  const activeRun = activeRuns[activeRuns.length - 1] ?? null;
  const latestStudy = detail.latest_optimization_study ?? null;
  const study = latestStudy && (!latestStudy.base_revision_id || latestStudy.base_revision_id === detail.active_revision_id) ? latestStudy : null;
  const nextAction = intentDirty
    ? { text: 'Save and compile the draft to publish it as a revision before evaluating or exploring it. Use Save draft, then Compile draft in the Intent bar.', page: null, label: '' }
    : dirty
      ? { text: 'Compile the saved draft to publish it as a revision before evaluating or exploring it. Use Compile draft in the Intent bar.', page: null, label: '' }
      : !detail.active_revision_id
        ? { text: 'Declare the workload, requirements and fabric in the Intent step, then compile the draft into a revision.', page: null, label: '' }
        : !activeRun
          ? { text: `Evaluate ${revisionLabel(revisionId)} to produce evidence for this revision.`, page: 'analysis/summary' as const, label: 'Evaluate active revision' }
          : { text: 'Review the run. If you want a different fabric, choose one for this workload and compile a new revision.', page: 'explore/fabric' as const, label: 'Choose fabric for this workload' };
  const compile = () => run('compile', async () => {
    await gateway.compileProject(detail.project.project_id, active.draftMeta?.revisionToken);
    notify('Draft compiled. Evaluate the active revision to produce new verdicts.');
    reload();
  });

  return <><Section title={`Workflow · ${detail.project.name}`} actions={<>
    {topology ? <Badge tone="blue">Live store</Badge> : <Badge tone="amber">No topology</Badge>}
  </>}>
    <Notice tone="blue">
      <strong>Next:</strong> <span>{nextAction.text}</span>{' '}
      {nextAction.page && <PageLink page={nextAction.page} primary>{nextAction.label}</PageLink>}
    </Notice>
    <Step index={1} title="Project"
      summary={<><span className="mono">{detail.project.project_id}</span> · {workloadName}{workloadName === 'no workload' ? '' : ` · TP${active.request?.workload?.tp ?? '—'} DP${active.request?.workload?.dp ?? '—'} EP${active.request?.workload?.ep ?? '—'} PP${active.request?.workload?.pp ?? '—'}`}</>}
      actions={<Button aria-pressed={panel === 'rename'} onClick={() => toggle('rename')}>Rename</Button>}>
      {panel === 'rename' && <div className="toolbar">
        <input aria-label="Project name" value={rename} onChange={e => setRename(e.target.value)} />
        <Button primary disabled={busy !== null || !rename.trim() || rename === detail.project.name}
          onClick={() => run('rename', async () => { await gateway.renameProject(detail.project.project_id, rename.trim()); reload(); })}>{busy === 'rename' ? 'Renaming…' : 'Save name'}</Button>
      </div>}
    </Step>

    <Step index={2} title="Intent"
      summary={<>{workloadName} · {draftFabric} · {tileAgents} compute tiles {intentDirty ? '· unsaved edits' : dirty ? '· saved draft differs from revision' : '· matches compiled revision'}</>}
      actions={<>
        <Badge tone={dirty || intentDirty ? 'amber' : 'green'}>{intentDirty ? 'unsaved edits' : dirty ? 'uncompiled' : 'compiled'}</Badge>
        <Button onClick={() => setIntentTab(intentStart)}>Edit draft</Button>
      </>}>
      <IntentWorkspace
        project={active}
        notify={notify}
        tab={intentTab}
        onTabChange={setIntentTab}
        onCompile={compile}
        compileBusy={busy === 'compile'}
        onDirtyChange={setIntentDirty}
      />
    </Step>

    <Step index={3} title="Revision"
      summary={revisionId
        ? <><span className="mono">{revisionLabel(revisionId)}</span> · {activeRevision?.certificate_overall ?? activeRevision?.compilation_status ?? 'status not recorded'} · {topology ? `${topology.counts?.routers ?? 0} routers · ${topology.counts?.channels ?? topology.channels.length} channels · ${topology.counts?.endpoints ?? 0} endpoints` : 'no topology published'}</>
        : 'Nothing compiled yet.'}
      actions={<>
        {topology && <Button aria-pressed={showLayout} onClick={() => setShowLayout(open => !open)}>{showLayout ? 'Hide layout' : 'Show layout'}</Button>}
      </>}>
      {(dirty || intentDirty) && <Notice tone="amber">
        <strong>This card is the compiled snapshot{revisionId ? ` (${revisionLabel(revisionId)})` : ''}, not the current draft.</strong>{' '}
        {intentDirty ? 'The open Intent tab has unsaved changes: save them in the Intent bar, then compile.' : 'The saved draft differs from this revision: compile from the Intent bar to publish it.'}{' '}
        The saved draft declares <span className="mono">{draftFabric}</span>{revisionId && topology ? `; this revision has ${topology.counts?.routers ?? topology.routers.length} routers and ${topology.counts?.channels ?? topology.channels.length} channels.` : '.'}
      </Notice>}
      {topology && showLayout && <TopologyGraph topology={topology} />}
    </Step>

    <Step index={4} title="Evaluation"
      summary={runs.length
        ? activeRun
          ? <>Active <span className="mono">{runLabels.get(activeRun.run_id)}</span> {activeRun.status} · {activeRun.requirements_pass === true ? 'requirements pass' : activeRun.requirements_pass === false ? 'requirements fail' : 'requirements not recorded'} · {runs.length} run{runs.length === 1 ? '' : 's'} total</>
          : <>No run on {revisionLabel(revisionId)} · latest historical <span className="mono">{latest ? runLabels.get(latest.run_id) : '—'}</span> {latest?.status}</>
        : 'No run yet.'}
      actions={<>
        {activeRun && <Badge tone="green">Run recorded on active revision</Badge>}
        {activeRun
          ? <Button primary onClick={() => openRun(activeRun.run_id)}>Open latest run</Button>
          : <PageLink page="analysis/summary" primary>Evaluate active revision</PageLink>}
      </>}>
      {!activeRun && runs.length > 0 && <Notice tone="amber"><strong>No run exists on the active revision {revisionLabel(revisionId)}.</strong>{' '}
        The history below includes revisions that do have runs. Open the evaluation launcher to measure the active revision.</Notice>}
      {(revisions.length || runs.length) && <RevisionHistory revisions={revisions} runs={runs} activeRevisionId={detail.active_revision_id} selectedRunId={selectedRunId} onOpenRun={openRun} />}
    </Step>

    <Step index={5} title="Explore & improve"
      summary={activeRun
        ? <>Run <span className="mono">{runLabels.get(activeRun.run_id)}</span> recorded · {study ? `${study.candidate_count ?? 0} measured candidate${(study.candidate_count ?? 0) === 1 ? '' : 's'} on this revision` : latestStudy ? `latest study is on ${revisionLabel(latestStudy.base_revision_id)}; no study on this revision` : 'no study yet'}</>
        : 'Blocked until the active revision has a run.'}
      actions={<>
        <PageLink page="explore/fabric-search">Catalog fabric search</PageLink>
        <PageLink page="explore/brief" primary={!!activeRun}>Revision study</PageLink>
      </>}>
      {activeRun
        ? <p className="meta-line">A catalog fabric is reference evidence. Apply its topology to the draft to test it here; the revision study measures candidates on this revision and is the only path that adopts a winner.</p>
        : <Notice tone="amber">Evaluate the active revision before carrying a fabric shortlist into a measured study.</Notice>}
    </Step>

    <Step index={6} title="Verify & deliver"
      summary={activeRun ? 'Evidence and the revision manifest are available.' : 'No evaluation evidence yet.'}
      actions={<>
        <PageLink page="verify/evidence" primary={!!activeRun}>Verify evidence</PageLink>
        <PageLink page="deliver/readiness">Deliver manifest</PageLink>
      </>}>
      <p className="meta-line">Verification is scoped to the active revision and its run. Delivery exports the declared architecture; RTL and hardware qualification remain not established.</p>
    </Step>

    <DraftHistory key={`${detail.project.project_id}:${active.draftMeta?.revisionToken}`} project={active} />
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
  </Section>
    <Assumptions rows={[
      ['Revision', 'A revision is a compiled snapshot of the saved draft.'],
      ['Run', 'A run is one evaluation of a revision; failed compile attempts stay visible so the sequence has no gaps.'],
      ['Missing evidence', 'No run on a revision means no evaluation evidence; nothing is inferred from its absence.'],
      ['Intent workspace', 'Fabric and workload edits are local to the draft; validate, save, then compile to publish a revision.'],
      ['Virtual channels', 'VC count is derived by the compiler from traffic-class dependencies; buffer depth is per VC.'],
      ['Topology probe', 'Backend family status is probed server-side against the compiler, projection, execution handler and qualification profile; authorable does not imply executable.'],
      ['Fabric scope', 'The Srota editor declares plane, MECS and island intent; the compiler maps it to the BookSim Srota model, and simulator knobs (VC counts, allocators, seeds) are not authorable.'],
    ]} />
  </>;
}
