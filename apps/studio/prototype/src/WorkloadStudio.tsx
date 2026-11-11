import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useProject, type LoadedProject } from './project';
import { Assumptions, Badge, Button, Empty, Icon, Notice, PageLink, Section } from './ui';
import { DraftContext, DraftSaveBar, IssueList, draftSchema, integerText, useDraftSave, type Draft } from './draftSave';
import { bytes, num } from './format';
import type { IntentSaveState } from './intent';

const MODEL_FAMILIES = [
  ['dense_transformer', 'Dense transformer'],
  ['mixture_of_experts', 'Mixture of experts'],
  ['diffusion', 'Diffusion'],
  ['cnn', 'CNN'],
  ['custom', 'Custom'],
] as const;
const COLLECTIVE_KINDS = ['allreduce', 'allgather', 'reducescatter', 'broadcast', 'alltoall'];
const DIMENSIONS = ['TP', 'DP', 'EP', 'PP', 'GLOBAL'];
const TRAFFIC_CLASS_SUGGESTIONS = ['tp_collective', 'ep_dispatch', 'tp_reduce', 'ep_combine'];

function TrafficClassSelect({ value, options, onChange, ariaLabel }: {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState('');
  const choices = [...new Set([...options, ...(value ? [value] : [])].filter(Boolean))];
  const cancel = () => { setAdding(false); setDraft(''); };
  const commit = () => {
    const name = draft.trim();
    if (!name) return;
    onChange(name);
    cancel();
  };
  if (adding) {
    return <div className="traffic-class-new">
      <input autoFocus aria-label={`${ariaLabel} new name`} value={draft} placeholder="New class name"
        onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {
          if (event.key === 'Enter') { event.preventDefault(); commit(); }
          if (event.key === 'Escape') { event.preventDefault(); cancel(); }
        }} />
      <Button onClick={commit} disabled={!draft.trim()}>Use</Button>
      <Button onClick={cancel}>Cancel</Button>
    </div>;
  }
  return <select aria-label={ariaLabel} value={value} onChange={event => {
    const next = event.target.value;
    if (next === '__new__') { setAdding(true); setDraft(''); return; }
    onChange(next);
  }}>
    <option value="">Select a class…</option>
    {choices.map(option => <option key={option} value={option}>{option}</option>)}
    <option value="__new__">＋ New traffic class…</option>
  </select>;
}

type CollectiveRow = {
  kind: string;
  dimension: string;
  payload_bytes: string;
  traffic_class: string;
  source_rank: string;
};

/** One canonical initiator→target transfer (v4 `workload.traffic_profiles`).
 *  It is a volume/mix row, never a timestamped schedule. */
type ProfileRow = {
  src_rank: string;
  dst_rank: string;
  traffic_class: string;
  payload_bytes: string;
};

type StageRow = {
  stage_id: string;
  owner: string;
  duration_ns: string;
  input_bytes: string;
  weight_bytes: string;
  output_bytes: string;
  input_loc: string;
  weight_loc: string;
  output_loc: string;
};

export type WorkloadForm = {
  model_name: string;
  model_family: string;
  tp: string;
  dp: string;
  ep: string;
  pp: string;
  collectives: CollectiveRow[];
  profiles: ProfileRow[];
  stages: StageRow[];
};

type Tab = 'traffic' | 'profiles' | 'compute';

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

function fromRequest(request: Draft | null): WorkloadForm {
  const workload = (request?.workload ?? {}) as Draft;
  const collectives = Array.isArray(workload.collectives) ? workload.collectives as Draft[] : [];
  const profiles = Array.isArray(workload.traffic_profiles) ? workload.traffic_profiles as Draft[] : [];
  const stages = Array.isArray(request?.compute?.stages) ? request!.compute.stages as Draft[] : [];
  return {
    model_name: text(workload.model_name),
    model_family: text(workload.model_family) || 'dense_transformer',
    tp: text(workload.tp ?? 1),
    dp: text(workload.dp ?? 1),
    ep: text(workload.ep ?? 1),
    pp: text(workload.pp ?? 1),
    collectives: collectives.map(row => ({
      kind: text(row.kind) || 'allreduce',
      dimension: text(row.dimension) || 'TP',
      payload_bytes: text(row.payload_bytes),
      traffic_class: text(row.traffic_class),
      source_rank: text(row.source_rank),
    })),
    profiles: profiles.map(row => ({
      src_rank: text(row.src_rank),
      dst_rank: text(row.dst_rank),
      traffic_class: text(row.traffic_class),
      payload_bytes: text(row.payload_bytes),
    })),
    stages: stages.map(row => ({
      stage_id: text(row.stage_id),
      owner: text(row.owner),
      duration_ns: text(row.duration_ns),
      input_bytes: text(row.input_bytes ?? 0),
      weight_bytes: text(row.weight_bytes ?? 0),
      output_bytes: text(row.output_bytes ?? 0),
      input_loc: text(row.input_loc) || 'LOCAL',
      weight_loc: text(row.weight_loc) || 'LOCAL',
      output_loc: text(row.output_loc) || 'LOCAL',
    })),
  };
}

export function workloadIssues(form: WorkloadForm): string[] {
  const issues: string[] = [];
  if (!MODEL_FAMILIES.some(([value]) => value === form.model_family)) issues.push('Choose a model family this editor supports.');
  const parallelism: [string, string][] = [
    ['TP', form.tp], ['DP', form.dp], ['EP', form.ep], ['PP', form.pp],
  ];
  const ranks: Record<string, number | null> = {};
  for (const [label, value] of parallelism) {
    const parsed = integerText(value, 1);
    ranks[label] = parsed;
    if (parsed === null) issues.push(`${label} must be a whole number of at least 1.`);
  }
  const world = Object.values(ranks).every(value => value !== null)
    ? (ranks.TP as number) * (ranks.DP as number) * (ranks.EP as number) * (ranks.PP as number)
    : null;
  ranks.GLOBAL = world;
  form.collectives.forEach((row, index) => {
    const where = `Traffic row ${index + 1}`;
    if (!COLLECTIVE_KINDS.includes(row.kind)) issues.push(`${where}: choose a collective kind.`);
    if (!DIMENSIONS.includes(row.dimension)) issues.push(`${where}: choose a rank dimension.`);
    if (integerText(row.payload_bytes, 1) === null) issues.push(`${where}: payload must be a whole number of bytes, at least 1.`);
    if (!row.traffic_class.trim()) issues.push(`${where}: a traffic class name is required.`);
    if (row.kind === 'broadcast') {
      if (integerText(row.source_rank, 0) === null) issues.push(`${where}: a broadcast needs an explicit source rank.`);
    } else if (row.source_rank.trim() !== '') {
      issues.push(`${where}: only a broadcast may name a source rank.`);
    }
    // The backend refuses a one-member collective at compile time; surface the
    // same rule here so an unsavable intent never reaches the gateway.
    const members = ranks[row.dimension];
    if (row.dimension === 'PP') {
      issues.push(`${where}: PP-dimension collectives are not supported; pipeline stages communicate point-to-point.`);
    } else if (members != null && members < 2) {
      issues.push(`${where}: ${row.kind} over ${row.dimension} needs at least 2 participants; ${row.dimension === 'GLOBAL' ? 'the declared world size' : row.dimension} is ${members}.`);
    }
  });
  const ids = new Set<string>();
  const seenProfiles = new Set<string>();
  form.profiles.forEach((row, index) => {
    const where = `Initiator profile ${index + 1}`;
    const src = integerText(row.src_rank, 0);
    const dst = integerText(row.dst_rank, 0);
    if (src === null) issues.push(`${where}: source rank must be a whole number, at least 0.`);
    if (dst === null) issues.push(`${where}: target rank must be a whole number, at least 0.`);
    if (src !== null && dst !== null && src === dst) issues.push(`${where}: source and target ranks must differ.`);
    if (world !== null && ((src !== null && src >= world) || (dst !== null && dst >= world))) {
      issues.push(`${where}: ranks must stay below the ${world} declared participants (TP × DP × EP × PP).`);
    }
    if (!row.traffic_class.trim()) issues.push(`${where}: a traffic class name is required.`);
    if (integerText(row.payload_bytes, 1) === null) issues.push(`${where}: payload must be a whole number of bytes, at least 1.`);
    if (src !== null && dst !== null && row.traffic_class.trim()) {
      const key = `${src}->${dst}:${row.traffic_class.trim()}`;
      if (seenProfiles.has(key)) issues.push(`${where}: ${key} duplicates an earlier row.`);
      seenProfiles.add(key);
    }
  });
  form.stages.forEach((row, index) => {
    const where = `Compute stage ${index + 1}`;
    const id = row.stage_id.trim();
    if (!id) issues.push(`${where}: a stage id is required.`);
    else if (ids.has(id)) issues.push(`${where}: the stage id "${id}" is already used.`);
    ids.add(id);
    if (integerText(row.duration_ns, 0) === null) issues.push(`${where}: duration must be a whole number of nanoseconds.`);
    for (const [label, value] of [['input bytes', row.input_bytes], ['weight bytes', row.weight_bytes], ['output bytes', row.output_bytes]] as const) {
      if (integerText(value, 0) === null) issues.push(`${where}: ${label} must be a whole number.`);
    }
    if (row.owner.trim() !== '' && integerText(row.owner, 0) === null) issues.push(`${where}: owner must be a whole number or left empty.`);
  });
  return issues;
}

function buildRequest(base: Draft, form: WorkloadForm): Draft {
  const previous = (base.workload ?? {}) as Draft;
  const collectives = form.collectives.map(row => ({
    kind: row.kind,
    dimension: row.dimension,
    payload_bytes: Number(row.payload_bytes),
    traffic_class: row.traffic_class.trim(),
    source_rank: row.source_rank.trim() === '' ? null : Number(row.source_rank),
  }));
  const workload: Draft = {
    ...previous,
    model_name: form.model_name.trim(),
    model_family: form.model_family,
    tp: Number(form.tp),
    dp: Number(form.dp),
    ep: Number(form.ep),
    pp: Number(form.pp),
    collectives,
  };
  // `traffic_profiles` is v4-only. Removing every row must delete it rather
  // than leave an empty declaration behind; an untouched v3 draft keeps no
  // key its own identity cannot express.
  if (form.profiles.length || previous.traffic_profiles !== undefined) {
    workload.traffic_profiles = form.profiles.map(row => ({
      src_rank: Number(row.src_rank),
      dst_rank: Number(row.dst_rank),
      traffic_class: row.traffic_class.trim(),
      payload_bytes: Number(row.payload_bytes),
    }));
  }
  const request: Draft = { ...base, workload };
  if (form.stages.length || base.compute !== undefined) {
    const prior = (base.compute ?? {}) as Draft;
    request.compute = {
      ...prior,
      ...(prior.source === undefined
        ? { source: { kind: 'declared', detail: 'Authored in the Srota Studio workload editor.' } }
        : {}),
      stages: form.stages.map(row => ({
        stage_id: row.stage_id.trim(),
        owner: row.owner.trim() === '' ? null : Number(row.owner),
        duration_ns: Number(row.duration_ns),
        input_bytes: Number(row.input_bytes),
        weight_bytes: Number(row.weight_bytes),
        output_bytes: Number(row.output_bytes),
        input_loc: row.input_loc || 'LOCAL',
        weight_loc: row.weight_loc || 'LOCAL',
        output_loc: row.output_loc || 'LOCAL',
      })),
    };
  }
  return request;
}

function nextStageId(stages: StageRow[]): string {
  const taken = new Set(stages.map(row => row.stage_id.trim()));
  let index = stages.length + 1;
  while (taken.has(`stage_${index}`)) index += 1;
  return `stage_${index}`;
}

type CatalogWorkload = { workload_id: string; display_name?: string; model_family?: string };

export function LiveWorkloadPage({ project, notify, initialTab, embedded = false, onDirty, onSaveState, footer }: {
  project: LoadedProject;
  notify: (message: string) => void;
  initialTab?: Tab;
  embedded?: boolean;
  onDirty?: (dirty: boolean) => void;
  onSaveState?: (state: IntentSaveState) => void;
  /** Rendered after the form and before the assumptions, so a surrounding
   *  flow can place its save/next actions without splitting the scope block. */
  footer?: ReactNode;
}) {
  const { reload } = useProject();
  const request = project.request as Draft | null;
  const baseline = useMemo(() => fromRequest(request), [request]);
  const tabKey = `srota-workload-tab:${project.detail.project.project_id}`;
  const remembered = (() => {
    try {
      const value = sessionStorage.getItem(tabKey);
      return value === 'traffic' || value === 'profiles' || value === 'compute' ? value : null;
    } catch { return null; }
  })();
  const [form, setForm] = useState<WorkloadForm>(baseline);
  const [tab, setTab] = useState<Tab>(initialTab ?? remembered ?? (baseline.collectives.length === 0 && baseline.profiles.length > 0 ? 'profiles' : baseline.collectives.length === 0 && baseline.stages.length > 0 ? 'compute' : 'traffic'));
  useEffect(() => { setForm(baseline); }, [baseline]);
  useEffect(() => { try { sessionStorage.setItem(tabKey, tab); } catch { /* Remembering the tab is optional. */ } }, [tabKey, tab]);
  const saveState = useDraftSave(project, notify);
  const saveRef = useRef<() => void>(() => {});
  const [catalog, setCatalog] = useState<CatalogWorkload[]>([]);
  const [catalogId, setCatalogId] = useState('');
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogError, setCatalogError] = useState('');

  useEffect(() => { gateway.workloads().then(setCatalog).catch(() => setCatalog([])); }, []);

  const dirty = JSON.stringify(form) !== JSON.stringify(baseline);
  useEffect(() => { onDirty?.(dirty); }, [dirty, onDirty]);
  const issues = workloadIssues(form);
  const valid = issues.length === 0;
  const schema = draftSchema(project);
  const needsUpgrade = schema !== null && schema > 0 && schema < 4 && form.stages.length > 0;
  const readOnly = schema !== null && schema >= 5;
  const parallel = [form.tp, form.dp, form.ep, form.pp].every(value => integerText(value, 1) !== null)
    ? Number(form.tp) * Number(form.dp) * Number(form.ep) * Number(form.pp)
    : null;
  const sourceRef = request?.workload?.workload_source_ref ?? null;
  const sourceDigest = typeof sourceRef === 'string' ? sourceRef : sourceRef?.content_digest ?? null;
  const sourceFormat = typeof sourceRef === 'string' ? null : sourceRef?.format ?? null;
  const totalDuration = form.stages.reduce((total, row) => total + (integerText(row.duration_ns, 0) ?? 0), 0);
  const nonLocal = form.stages.some(row => [row.input_loc, row.weight_loc, row.output_loc].some(location => location && location !== 'LOCAL'));
  const trafficClassOptions = [...new Set([
    ...form.collectives.map(row => row.traffic_class.trim()),
    ...TRAFFIC_CLASS_SUGGESTIONS,
  ].filter(Boolean))];

  const patchCollective = (index: number, patch: Partial<CollectiveRow>) => setForm(current => ({
    ...current,
    collectives: current.collectives.map((row, position) => position === index ? { ...row, ...patch } : row),
  }));
  const patchStage = (index: number, patch: Partial<StageRow>) => setForm(current => ({
    ...current,
    stages: current.stages.map((row, position) => position === index ? { ...row, ...patch } : row),
  }));
  const patchProfile = (index: number, patch: Partial<ProfileRow>) => setForm(current => ({
    ...current,
    profiles: current.profiles.map((row, position) => position === index ? { ...row, ...patch } : row),
  }));
  const addCollective = () => {
    setForm(current => ({
      ...current,
      collectives: [...current.collectives, {
        kind: 'allreduce',
        dimension: 'TP',
        payload_bytes: '',
        traffic_class: '',
        source_rank: '',
      }],
    }));
    setTab('traffic');
  };
  const addStage = () => {
    setForm(current => ({
      ...current,
      stages: [...current.stages, {
        stage_id: nextStageId(current.stages),
        owner: '',
        duration_ns: '',
        input_bytes: '0',
        weight_bytes: '0',
        output_bytes: '0',
        input_loc: 'LOCAL',
        weight_loc: 'LOCAL',
        output_loc: 'LOCAL',
      }],
    }));
    setTab('compute');
  };
  const addProfile = () => {
    setForm(current => ({
      ...current,
      profiles: [...current.profiles, {
        src_rank: '0',
        dst_rank: '',
        traffic_class: current.collectives[0]?.traffic_class.trim() || '',
        payload_bytes: '',
      }],
    }));
    setTab('profiles');
  };
  const save = () => saveState.save(
    base => buildRequest(base, form),
    'Workload saved to the draft. Compile the revision to use it.',
    { needsV4: form.stages.length > 0 || form.profiles.length > 0 },
  );
  saveRef.current = save;
  useEffect(() => {
    onSaveState?.({
      dirty,
      valid: valid && !readOnly,
      busy: saveState.busy,
      error: saveState.error,
      save: () => saveRef.current(),
    });
  }, [dirty, valid, readOnly, saveState.busy, saveState.error, onSaveState]);

  const applyCatalog = async () => {
    if (!catalogId || catalogBusy) return;
    if (dirty && !window.confirm('Replace the current workload with the catalog workload template? Unsaved workload edits will be lost.')) return;
    setCatalogBusy(true); setCatalogError('');
    try {
      await gateway.selectWorkload(project.detail.project.project_id, catalogId);
      notify('Catalog workload applied to the draft. Compile the revision to use it.');
      reload();
    } catch (caught) {
      setCatalogError(gatewayReason(caught));
    } finally {
      setCatalogBusy(false);
    }
  };

  return <div className={embedded ? 'studio-embedded' : 'view-main studio-view'}>
    {!embedded && <DraftContext project={project} />}
    {!embedded && <div className="studio-intro">
      <div>
        <h2>{form.model_name.trim() || 'Unnamed workload'}</h2>
      </div>
      <PageLink page="workloads/requirements">Next: requirements <Icon name="arrow" /></PageLink>
    </div>}

        <Section title="Workload identity">
      <div className="stat-strip">
        <div className="stat"><span>Ranks</span><strong>{parallel === null ? '—' : parallel}</strong><small>TP × DP × EP × PP</small></div>
        <div className="stat"><span>Collectives</span><strong>{form.collectives.length}</strong><small>declared traffic rows</small></div>
        <div className="stat"><span>Initiator profiles</span><strong>{form.profiles.length}</strong><small>{form.profiles.length ? 'declared P2P rows' : 'no per-initiator demand'}</small></div>
        <div className="stat"><span>Compute stages</span><strong>{form.stages.length}</strong><small>{form.stages.length ? 'declared durations' : 'no execution timing derivable'}</small></div>
        <div className="stat"><span>Declared duration</span><strong>{form.stages.length ? `${(totalDuration / 1e6).toFixed(3)} ms` : '—'}</strong><small>{form.stages.length ? 'summed, not a critical path' : 'no stage durations'}</small></div>
      </div>
      {catalog.length > 0 && <div className="intent-catalog">
        <label className="field"><span>Catalog workload</span>
          <select aria-label="Catalog workload" value={catalogId} onChange={event => setCatalogId(event.target.value)}>
            <option value="">Select a catalog workload…</option>
            {catalog.map(entry => <option key={entry.workload_id} value={entry.workload_id}>{entry.display_name ?? entry.workload_id}</option>)}
          </select>
        </label>
        <Button disabled={!catalogId || catalogBusy} onClick={applyCatalog}>{catalogBusy ? 'Loading…' : 'Load template'}</Button>
        <span className="muted">Replaces the workload identity and collectives. Review the draft before compiling.</span>
      </div>}
      {catalogError && <Notice tone="red">{catalogError}</Notice>}
      <div className="form-grid">
        <label className="field"><span>Model name</span>
          <input value={form.model_name} placeholder="e.g. meta-llama/Llama-3.1-8B" onChange={event => setForm(current => ({ ...current, model_name: event.target.value }))} />
        </label>
        <label className="field"><span>Model family</span>
          <select value={form.model_family} onChange={event => setForm(current => ({ ...current, model_family: event.target.value }))}>
            {!MODEL_FAMILIES.some(([value]) => value === form.model_family) && <option value={form.model_family}>{form.model_family} (unsupported here)</option>}
            {MODEL_FAMILIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <div className="field"><span>Parallelism · TP × DP × EP × PP</span>
          <div className="parallel-inputs">
            {([['TP', 'tp'], ['DP', 'dp'], ['EP', 'ep'], ['PP', 'pp']] as const).map(([label, key]) => <label key={key}>
              <small>{label}</small>
              <input aria-label={`${label} parallelism`} type="number" min={1} step={1} value={form[key]} onChange={event => setForm(current => ({ ...current, [key]: event.target.value }))} />
            </label>)}
          </div>
        </div>
      </div>
    </Section>

    <Section
      title="Traffic, initiators and compute"
      actions={<div className="segmented" role="tablist" aria-label="Workload detail">
        <button role="tab" aria-selected={tab === 'traffic'} className={tab === 'traffic' ? 'active' : ''} onClick={() => setTab('traffic')}>Traffic · {form.collectives.length}</button>
        <button role="tab" aria-selected={tab === 'profiles'} className={tab === 'profiles' ? 'active' : ''} onClick={() => setTab('profiles')}>Initiators · {form.profiles.length}</button>
        <button role="tab" aria-selected={tab === 'compute'} className={tab === 'compute' ? 'active' : ''} onClick={() => setTab('compute')}>Compute · {form.stages.length}</button>
      </div>}
    >
      {tab === 'traffic' ? <>
        <div className="toolbar toolbar-start">
          <Button onClick={addCollective}><Icon name="plus" />Add collective</Button>
        </div>
        {form.collectives.length ? <div className="table-scroll"><table className="editor-table">
          <thead><tr><th>Kind</th><th>Dimension</th><th>Payload</th><th>Traffic class</th><th>Source rank</th><th /></tr></thead>
          <tbody>
            {form.collectives.map((row, index) => <tr key={index}>
              <td><select aria-label={`traffic row ${index + 1} kind`} value={row.kind} onChange={event => patchCollective(index, { kind: event.target.value, ...(event.target.value === 'broadcast' ? {} : { source_rank: '' }) })}>
                {COLLECTIVE_KINDS.map(kind => <option key={kind} value={kind}>{kind}</option>)}
              </select></td>
              <td><select aria-label={`traffic row ${index + 1} dimension`} value={row.dimension} onChange={event => patchCollective(index, { dimension: event.target.value })}>
                {DIMENSIONS.map(dimension => <option key={dimension} value={dimension}>{dimension}</option>)}
              </select></td>
              <td><div className="cell-input-hint"><input aria-label={`traffic row ${index + 1} payload bytes`} type="number" min={1} step={1} value={row.payload_bytes} placeholder="bytes" onChange={event => patchCollective(index, { payload_bytes: event.target.value })} />
                {integerText(row.payload_bytes, 1) !== null && <small>{bytes(Number(row.payload_bytes))}</small>}</div></td>
              <td><TrafficClassSelect ariaLabel={`traffic row ${index + 1} traffic class`} value={row.traffic_class}
                options={trafficClassOptions} onChange={value => patchCollective(index, { traffic_class: value })} /></td>
              <td><input aria-label={`traffic row ${index + 1} source rank`} value={row.source_rank} placeholder={row.kind === 'broadcast' ? 'required' : 'all ranks'} disabled={row.kind !== 'broadcast'} onChange={event => patchCollective(index, { source_rank: event.target.value })} /></td>
              <td><Button onClick={() => setForm(current => ({ ...current, collectives: current.collectives.filter((_, position) => position !== index) }))}>Remove</Button></td>
            </tr>)}
          </tbody>
        </table></div> : <Empty title="No traffic declared">
          This workload declares no collectives; a compute-only declaration is allowed.
        </Empty>}
      </> : tab === 'profiles' ? <>
        <div className="toolbar toolbar-start">
          <Button onClick={addProfile}><Icon name="plus" />Add initiator profile</Button>
          <Badge tone="amber">Schema v4</Badge>
          <span className="muted">One declared initiator→target transfer per row, lowered in declaration order.</span>
        </div>
        {form.profiles.length ? <div className="table-scroll"><table className="editor-table">
          <thead><tr><th>Source rank</th><th>Target rank</th><th>Traffic class</th><th>Payload</th><th /></tr></thead>
          <tbody>
            {form.profiles.map((row, index) => <tr key={index}>
              <td><input aria-label={`profile row ${index + 1} source rank`} type="number" min={0} step={1} value={row.src_rank} onChange={event => patchProfile(index, { src_rank: event.target.value })} /></td>
              <td><input aria-label={`profile row ${index + 1} target rank`} type="number" min={0} step={1} value={row.dst_rank} placeholder="rank" onChange={event => patchProfile(index, { dst_rank: event.target.value })} /></td>
              <td><TrafficClassSelect ariaLabel={`profile row ${index + 1} traffic class`} value={row.traffic_class}
                options={trafficClassOptions} onChange={value => patchProfile(index, { traffic_class: value })} /></td>
              <td><div className="cell-input-hint"><input aria-label={`profile row ${index + 1} payload bytes`} type="number" min={1} step={1} value={row.payload_bytes} placeholder="bytes" onChange={event => patchProfile(index, { payload_bytes: event.target.value })} />
                {integerText(row.payload_bytes, 1) !== null && <small>{bytes(Number(row.payload_bytes))}</small>}</div></td>
              <td><Button onClick={() => setForm(current => ({ ...current, profiles: current.profiles.filter((_, position) => position !== index) }))}>Remove</Button></td>
            </tr>)}
          </tbody>
        </table></div> : <Empty title="No initiator profiles declared">
          Collective traffic above is still evaluated. Add rows when the workload is per-initiator demand rather than collectives.
        </Empty>}
        <p className="meta-line">Ranks are workload participants (0 to TP × DP × EP × PP − 1), not topology endpoint IDs, so a profile cannot address an HBM controller. Each row becomes one P2P transfer and joins the catalog path on typed fabrics. ASTRA-SIM’s qualified execution path refuses P2P, so a profile-only workload is network-only: the system scope reports a typed refusal instead of a number. Order is identity-bearing.</p>
      </> : <>
        <div className="toolbar toolbar-start">
          {form.stages.length > 0 && <Button onClick={addStage}><Icon name="plus" />Add compute stage</Button>}
          <Badge tone="amber">Not a schedule</Badge>
          <span className="muted">Declared durations sum to {form.stages.length ? `${(totalDuration / 1e6).toFixed(3)} ms` : '0 ms'}.</span>
        </div>
        {form.stages.length ? <div className="table-scroll"><table className="editor-table">
          <thead><tr><th>Stage id</th><th title="Authored single-rank compute owner. ASTRA executes this stage on this rank; a TP/EP shard map is not represented.">Compute owner</th><th>Duration (ns)</th><th>Input (B)</th><th>Weight (B)</th><th>Output (B)</th><th /></tr></thead>
          <tbody>
            {form.stages.map((row, index) => <tr key={index}>
              <td><input aria-label={`stage ${index + 1} id`} className="mono" value={row.stage_id} onChange={event => patchStage(index, { stage_id: event.target.value })} /></td>
              <td><input aria-label={`stage ${index + 1} compute owner rank`} type="number" min={0} step={1} value={row.owner} placeholder="any" onChange={event => patchStage(index, { owner: event.target.value })} /></td>
              <td><input aria-label={`stage ${index + 1} duration ns`} type="number" min={0} step={1} value={row.duration_ns} onChange={event => patchStage(index, { duration_ns: event.target.value })} /></td>
              <td><input aria-label={`stage ${index + 1} input bytes`} type="number" min={0} step={1} value={row.input_bytes} onChange={event => patchStage(index, { input_bytes: event.target.value })} /></td>
              <td><input aria-label={`stage ${index + 1} weight bytes`} type="number" min={0} step={1} value={row.weight_bytes} onChange={event => patchStage(index, { weight_bytes: event.target.value })} /></td>
              <td><input aria-label={`stage ${index + 1} output bytes`} type="number" min={0} step={1} value={row.output_bytes} onChange={event => patchStage(index, { output_bytes: event.target.value })} /></td>
              <td><Button onClick={() => setForm(current => ({ ...current, stages: current.stages.filter((_, position) => position !== index) }))}>Remove</Button></td>
            </tr>)}
          </tbody>
        </table></div> : <div className="callout">
          <div>
            <strong>No compute stages declared.</strong>
            <p>{request?.compute ? 'The draft has a compute block with no stages.' : 'The draft request has no compute block.'} Network traffic is still evaluable.</p>
          </div>
          <Button primary onClick={addStage}><Icon name="plus" />Add the first stage</Button>
        </div>}
        {nonLocal && <p className="meta-line warn-text">Some stages declare non-local locations. The memory lowerer accepts local pools only.</p>}
        <PageLink page="design/fabric-topology">Inspect agent placement</PageLink>
      </>}
    </Section>

    <IssueList issues={issues} />
    {needsUpgrade && <div className="inline-note amber"><strong>Schema v{schema} draft.</strong> Compute stages and initiator profiles require schema v4. Saving validates the existing fabric with the gateway, migrates this draft to v4, and preserves workload, requirements, agents, and address ranges.</div>}
    {readOnly && <div className="inline-note amber"><strong>Schema v{schema} draft.</strong> This page reads it but will not rewrite nested v5 intent. Use the Project workflow draft editor.</div>}
    {!embedded && <DraftSaveBar dirty={dirty} valid={valid && !readOnly} state={saveState} onSave={save} note="Saved changes still need a compile before they become a revision." />}
    {footer}
    <Assumptions rows={[
      ['Project', project.detail.project.name],
      ['Project id', <span className="mono">{project.detail.project.project_id}</span>],
      ['Compiled revision', <span className="mono">{project.detail.active_revision_id ?? 'none'}</span>],
      ['Request schema', `v${schema ?? 'not declared'}`],
      ['Compute source', text(request?.compute?.source?.kind) || 'not declared'],
      ['Workload source', sourceDigest ? `pinned ${sourceFormat ?? 'artifact'} · ${sourceDigest.slice(0, 19)}…` : 'declared inline; no imported artifact pinned'],
      ['Initiator profiles', form.profiles.length ? `${form.profiles.length} declared P2P row${form.profiles.length === 1 ? '' : 's'} in declaration order; network scope only on typed fabrics (ASTRA refuses P2P).` : 'None declared; the workload carries collectives only.'],
      ['Timing', 'A model name does not supply measured compute timing. Declare or import stage durations when system-level timing is required.'],
      ['Measures', form.stages.length ? `${form.stages.length} declared stages; ${num(totalDuration, ' ns')} summed duration` : 'No execution timing derivable'],
      ['Parallelism', `${parallel === null ? '—' : `${parallel} ranks`} declared by TP × DP × EP × PP; a declaration, not a scheduled rank map.`],
      ['Declared duration', form.stages.length ? `${(totalDuration / 1e6).toFixed(3)} ms summed from stage durations; no dependency edges, so not a critical path.` : 'No stage durations declared.'],
      ['Memory timing', 'Memory-access demand is workload input; Ramulator HBM timing appears under Analysis → Memory when the selected run includes DRAM_TIMING.'],
      ['Virtual channels', 'VC count is derived by the compiler from traffic-class dependencies; buffer depth is per VC.'],
    ]} />
  </div>;
}
