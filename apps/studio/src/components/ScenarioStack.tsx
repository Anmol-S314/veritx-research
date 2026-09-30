import { useState, type ReactElement } from 'react';
import {
  Link, useAsync,
} from '../studio';
import { api } from '../api';
import type {
  CompileResultView,
  EnergyAuthorityListView,
  EvaluationPlanView,
  ServingExperimentEntry,
  WorkloadCatalogEntry,
} from '../api/types';
import type { WorkbenchGroup } from './DesignViewV2Editor';
import { fmtNum, Prov } from './badges';

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function workloadMatches(
  models: string[],
  _denseOrMoe: string | null,
  modelName: string | null,
  _modelFamily: string | null,
): boolean {
  if (!modelName) return false;
  const target = norm(modelName);
  if (target.length < 4) return false;
  return models.some((m) => {
    const cand = norm(m.replace(/^.*\//, ''));
    return cand.includes(target) || target.includes(cand);
  });
}

interface AgentRow {
  kind: string | null;
  count: number | null;
}

function agentRows(doc: Record<string, unknown>): AgentRow[] {
  const raw = doc['agents'];
  if (!Array.isArray(raw)) return [];
  return raw.map((a) => {
    const r = (a ?? {}) as Record<string, unknown>;
    return {
      kind: typeof r['kind'] === 'string' ? r['kind'] : null,
      count: num(r['count']),
    };
  });
}

function LayerHead({ index, title, note }: {
  index: string;
  title: string;
  note: string;
}): ReactElement {
  return (
    <div className="layer-head">
      <span className="layer-index">{index}</span>
      <h3>{title}</h3>
      <span className="muted">{note}</span>
    </div>
  );
}

function EditButton({ onEdit, group, label }: {
  onEdit: (group: WorkbenchGroup) => void;
  group: WorkbenchGroup;
  label: string;
}): ReactElement {
  return (
    <button type="button" className="btn btn-small" onClick={() => onEdit(group)}>
      {label}
    </button>
  );
}

function Card({ title, prov, children }: {
  title: string;
  prov: 'EDITABLE' | 'DERIVED' | 'PROFILE';
  children: React.ReactNode;
}): ReactElement {
  return (
    <section className="card scenario-card" aria-label={title}>
      <h3>{title} <Prov kind={prov} /></h3>
      {children}
    </section>
  );
}

interface HwProfile {
  architecture: string;
  compute_units: string;
  frequency: string;
  peak_throughput: string;
  local_memory: string;
  l1: string;
  l2: string;
  cache_line: string;
  mem_type: string;
  mem_capacity: string;
  mem_bandwidth: string;
  mem_controllers: string;
  mem_latency: string;
  io_interface: string;
  io_bandwidth: string;
}

const EMPTY_PROFILE: HwProfile = {
  architecture: '', compute_units: '', frequency: '', peak_throughput: '',
  local_memory: '', l1: '', l2: '', cache_line: '', mem_type: '',
  mem_capacity: '', mem_bandwidth: '', mem_controllers: '', mem_latency: '',
  io_interface: '', io_bandwidth: '',
};

const PROFILE_FIELDS: { key: keyof HwProfile; label: string; hint: string }[] = [
  { key: 'architecture', label: 'Architecture', hint: 'e.g. Custom accelerator' },
  { key: 'compute_units', label: 'Compute units', hint: 'e.g. 96 SMs' },
  { key: 'frequency', label: 'Core clock', hint: 'e.g. 2.4 GHz' },
  { key: 'peak_throughput', label: 'Peak throughput', hint: 'e.g. 125 TFLOP/s' },
  { key: 'local_memory', label: 'Local SRAM', hint: 'e.g. 32 MB' },
  { key: 'l1', label: 'L1 / local cache', hint: 'e.g. 256 KB per unit' },
  { key: 'l2', label: 'L2 cache', hint: 'e.g. 96 MB' },
  { key: 'cache_line', label: 'Cache line', hint: 'e.g. 128 B' },
  { key: 'mem_type', label: 'Memory type', hint: 'e.g. GDDR7' },
  { key: 'mem_capacity', label: 'Memory capacity', hint: 'e.g. 96 GB' },
  { key: 'mem_bandwidth', label: 'Memory bandwidth', hint: 'e.g. 1.8 TB/s' },
  { key: 'mem_controllers', label: 'Memory controllers', hint: 'e.g. 8' },
  { key: 'mem_latency', label: 'Latency model', hint: 'e.g. fixed 200 ns' },
  { key: 'io_interface', label: 'Host interface', hint: 'e.g. PCIe Gen5' },
  { key: 'io_bandwidth', label: 'Host bandwidth', hint: 'e.g. 128 GB/s' },
];

function loadProfile(projectId: string): HwProfile {
  try {
    const raw = window.localStorage.getItem(`veritx.hwprofile.${projectId}`);
    if (!raw) return { ...EMPTY_PROFILE };
    const parsed = JSON.parse(raw) as Partial<HwProfile>;
    return { ...EMPTY_PROFILE, ...parsed };
  } catch {
    return { ...EMPTY_PROFILE };
  }
}

function profileFilled(p: HwProfile): boolean {
  return Object.values(p).some((v) => v !== '');
}

function MiniMap({ ranks, compute, memory }: {
  ranks: number | null;
  compute: number | null;
  memory: number | null;
}): ReactElement | null {
  if (ranks == null || compute == null || ranks <= 0 || compute <= 0) return null;
  const shown = Math.min(ranks, 8);
  const idle = compute - Math.min(ranks, compute);
  return (
    <div className="minimap" aria-label="Rank to endpoint mapping">
      <div className="mm-map">
        {Array.from({ length: shown }, (_, i) => (
          <span key={i} className="mm-col">
            <span className="mm-chip mm-rank">r{i}</span>
            <span className="mm-arrow" aria-hidden="true">↓</span>
            <span className="mm-chip mm-ep">C{i}</span>
          </span>
        ))}
      </div>
      {(idle > 0 || (memory ?? 0) > 0) && (
        <p className="muted">
          {ranks > 8 ? `+${ranks - 8} more ranks` : ''}
          {ranks > 8 && (idle > 0 || (memory ?? 0) > 0) ? ' · ' : ''}
          {idle > 0 ? `+${idle} idle compute` : ''}
          {idle > 0 && (memory ?? 0) > 0 ? ' · ' : ''}
          {(memory ?? 0) > 0 ? `+${memory} memory` : ''}
        </p>
      )}
    </div>
  );
}

type ModelStatus =
  | 'DETAILED' | 'SUPPORTED' | 'BLOCKED'
  | 'BOUND' | 'NOT BOUND'
  | 'NOT MODELED' | 'NOT CONFIGURED' | 'ESTIMATES ONLY';

interface ModelRow {
  label: string;
  status: ModelStatus;
  authority: string;
  consequence: string;
  diagnostic?: string | null;
  action?: ReactElement | null;
  lines?: string[];
}

function ModelCoverageRow({ row }: { row: ModelRow }): ReactElement {
  return (
    <details className="model-row">
      <summary>
        <span className={`model-pill model-${row.status.toLowerCase().replace(/ /g, '-')}`}>
          {row.status}
        </span>
        <span className="model-label">{row.label}</span>
        <span className="muted model-authority">{row.authority}</span>
      </summary>
      <p>{row.consequence}</p>
      {row.lines && row.lines.length > 0 && (
        <ul className="muted model-lines">
          {row.lines.map((line) => <li key={line}>{line}</li>)}
        </ul>
      )}
      {row.action && <div className="empty-actions">{row.action}</div>}
      {row.diagnostic && (
        <details className="subtle">
          <summary>View diagnostic</summary>
          <p className="muted model-diagnostic">{row.diagnostic}</p>
        </details>
      )}
    </details>
  );
}

function planRow(
  plan: EvaluationPlanView | null, question: string,
): { ready: boolean | null; backend: string; detail: string; fidelity: string | null } {
  if (!plan) return { ready: null, backend: '—', detail: 'no compiled revision', fidelity: null };
  const row = plan.analyses.find((a) => a.question === question);
  if (!row) return { ready: null, backend: '—', detail: 'not represented in the plan', fidelity: null };
  if (row.readiness === 'READY') {
    return {
      ready: true,
      backend: row.backend ?? 'backend',
      detail: [row.support, row.model_fidelity].filter((v) => v).join(' · ') || 'ready',
      fidelity: row.model_fidelity,
    };
  }
  return { ready: false, backend: row.backend ?? '—', detail: row.reason ?? row.readiness ?? 'blocked', fidelity: null };
}

export function dramConsequence(detail: string): string {
  if (/no COMPUTE memory-operand bytes|nothing to resolve|declares no COMPUTE/i.test(detail)) {
    return 'This workload declares communication only — it carries no '
      + 'compute memory operands, so there is no memory demand for '
      + 'Ramulator to simulate. DRAM timing needs compute/memory intent.';
  }
  if (/carry no placement|issue_node|memory-issuing/i.test(detail)) {
    return 'Compute operations have not been assigned to memory-issuing '
      + 'nodes, so VERITX cannot attribute memory traffic. DRAM timing '
      + 'stays unavailable until execution placement is provided.';
  }
  return 'The memory backend refused this analysis — see the diagnostic.';
}

export default function ScenarioStack({ projectId, doc, workloadId, activeRevisionId, onEditGroup }: {
  projectId: string;
  doc: Record<string, unknown>;
  workloadId: string | null;
  activeRevisionId: string | null;
  onEditGroup: (group: WorkbenchGroup) => void;
}): ReactElement {
  const catalog = useAsync(api.workloadCatalog, []);
  const servingCat = useAsync(api.servingExperiments, []);
  const compile = useAsync(
    () => (activeRevisionId
      ? api.compileResult(activeRevisionId)
      : Promise.reject(new Error('no compiled revision'))),
    [activeRevisionId],
  );
  const plan = useAsync(
    () => (activeRevisionId
      ? api.evaluationPlan(activeRevisionId)
      : Promise.reject(new Error('no compiled revision'))),
    [activeRevisionId],
  );
  const energy = useAsync(api.energyAuthoritiesVnext, []);
  const hwCatalog = useAsync(api.hardwareProfiles, []);
  const [bindingBusy, setBindingBusy] = useState(false);
  const [bindingNote, setBindingNote] = useState<string | null>(null);
  const bindExperiment = async (entry: ServingExperimentEntry) => {
    setBindingBusy(true);
    setBindingNote(null);
    try {
      await api.bindServing(projectId, {
        cluster_config: entry.config_source,
        dataset: entry.trace_source,
      });
      setBindingNote('Bound. Serving is now runnable for this revision.');
      plan.reload();
      servingCat.reload();
    } catch (err) {
      setBindingNote(err instanceof Error ? err.message : String(err));
    } finally {
      setBindingBusy(false);
    }
  };
  const [profile, setProfile] = useState<HwProfile>(() => loadProfile(projectId));
  const [editingProfile, setEditingProfile] = useState(false);

  const saveProfile = (next: HwProfile): void => {
    setProfile(next);
    try {
      window.localStorage.setItem(`veritx.hwprofile.${projectId}`, JSON.stringify(next));
    } catch { }
  };

  const workload = (doc['workload'] ?? {}) as Record<string, unknown>;
  const modelName = str(workload['model_name']);
  const modelFamily = str(workload['model_family']);
  const dims = (['tp', 'pp', 'ep', 'dp'] as const).map((d) => num(workload[d]));
  const ranks = dims.every((d) => d !== null)
    ? (dims as number[]).reduce((a, b) => a * b, 1) : null;
  const collectives = Array.isArray(workload['collectives'])
    ? (workload['collectives'] as unknown[]) : [];
  const agents = agentRows(doc);
  const computeCount = agents
    .filter((a) => a.kind && /compute|tile|core|sm|cu\b/i.test(a.kind) && !/hbm|dram|memory/i.test(a.kind))
    .reduce((a, r) => a + (r.count ?? 0), 0);
  const memoryCount = agents
    .filter((a) => a.kind && /hbm|dram|memory|controller/i.test(a.kind))
    .reduce((a, r) => a + (r.count ?? 0), 0);
  const endpoints = computeCount + memoryCount;
  const noc = (doc['noc_config'] ?? {}) as Record<string, unknown>;
  const physical = (doc['physical'] ?? {}) as Record<string, unknown>;
  const requirements = Array.isArray(doc['requirements'])
    ? (doc['requirements'] as Record<string, unknown>[]) : [];

  const catalogEntry: WorkloadCatalogEntry | null = catalog.result.state === 'ready' && workloadId
    ? catalog.result.data.workloads.find((w) => w.workload_id === workloadId) ?? null
    : null;

  const matched: ServingExperimentEntry[] = servingCat.result.state === 'ready'
    ? servingCat.result.data.experiments.filter((e) => workloadMatches(
      e.facets.models, e.facets.dense_or_moe ?? null, modelName, modelFamily,
    ))
    : [];

  const derived = compile.result.state === 'ready'
    ? (compile.result.data as CompileResultView).groups?.summary?.derived as
      Record<string, unknown> | undefined
    : undefined;
  const planView = plan.result.state === 'ready' ? plan.result.data : null;
  const net = planRow(planView, 'NETWORK_COMPLETION');
  const sys = planRow(planView, 'SYSTEM_MAKESPAN');
  const dram = planRow(planView, 'DRAM_TIMING');
  const servingRow = planView?.analyses.find(
    (a) => a.question === 'SERVING_TTFT');
  const servingBound = servingRow?.readiness === 'READY';
  const energyView: EnergyAuthorityListView | null =
    energy.result.state === 'ready' ? energy.result.data : null;
  const hwProfiles = hwCatalog.result.state === 'ready'
    ? hwCatalog.result.data.profiles : [];
  const wantedHw = (matched[0]?.facets.hardware[0] ?? '').toUpperCase();
  const matchedProfile = hwProfiles.find((p) =>
    (wantedHw && p.hardware_id.toUpperCase() === wantedHw)
    || (modelName && p.timing_source
        && p.timing_source.model.toLowerCase().includes(modelName.toLowerCase())))
    ?? null;

  const lede = [
    catalogEntry?.display_name ?? modelName ?? 'workload',
    profile.architecture || 'custom accelerator',
    str(noc['topology_family']) ?? 'fabric',
  ].join(' / ');

  const modelRows: ModelRow[] = [
    {
      label: 'Network transport',
      status: net.ready === true ? 'DETAILED' : net.ready === false ? 'BLOCKED' : 'NOT CONFIGURED',
      authority: net.ready === true ? net.backend : net.detail,
      consequence: net.ready === true
        ? `Packet-level transport is simulated by ${net.backend}${net.fidelity ? ` at ${net.fidelity} fidelity` : ''}.`
        : net.ready === false
          ? 'The network backend refused this analysis — see the diagnostic.'
          : 'No compiled revision adjudicates network support yet.',
      diagnostic: net.ready === false ? net.detail : null,
    },
    {
      label: 'Collective scheduling',
      status: sys.ready === true ? 'DETAILED' : sys.ready === false ? 'BLOCKED' : 'NOT CONFIGURED',
      authority: sys.ready === true ? sys.backend : sys.detail,
      consequence: sys.ready === true
        ? `Collective execution is scheduled by ${sys.backend}.`
        : sys.ready === false
          ? 'The scheduling backend refused this analysis — see the diagnostic.'
          : 'No compiled revision adjudicates scheduling support yet.',
      diagnostic: sys.ready === false ? sys.detail : null,
    },
    {
      label: 'DRAM timing',
      status: dram.ready === true ? 'DETAILED' : dram.ready === false ? 'BLOCKED' : 'NOT CONFIGURED',
      authority: dram.ready === true ? dram.backend
        : /no COMPUTE memory-operand bytes|nothing to resolve|declares no COMPUTE/i.test(dram.detail)
          ? 'Ramulator · no memory demand'
          : 'Ramulator · missing execution placement',
      consequence: dram.ready === true
        ? `DRAM timing is simulated by ${dram.backend}.`
        : dram.ready === false
          ? dramConsequence(dram.detail)
          : 'No compiled revision adjudicates DRAM support yet.',
      diagnostic: dram.ready === false ? dram.detail : null,
      action: dram.ready === false ? (
        <EditButton onEdit={onEditGroup} group="system" label="Configure memory mapping" />
      ) : null,
    },
    {
      label: 'Compute execution',
      status: 'NOT MODELED',
      authority: 'no backend authority',
      consequence: 'VERITX does not simulate instruction execution, pipelines, '
        + 'or core microarchitecture. Compute duration is not predicted — '
        + 'bind a hardware profile or a compute backend to change this.',
      action: <EditButton onEdit={onEditGroup} group="system" label="Configure hardware" />,
    },
    {
      label: 'Cache hierarchy',
      status: 'NOT MODELED',
      authority: 'no cache model',
      consequence: 'L1/L2 behavior is not simulated. Cache fields in the '
        + 'hardware profile are descriptive until a memory authority consumes them.',
    },
    {
      label: 'Serving dynamics',
      status: servingBound ? 'BOUND' : 'NOT BOUND',
      authority: servingBound
        ? 'serving experiment bound to this project'
        : matched.length > 0
          ? `${matched.length} catalog experiment${matched.length === 1 ? '' : 's'} list this model`
          : 'no serving experiment lists this workload',
      consequence: servingBound
        ? 'A serving experiment is bound. Serving answers become runnable in '
          + 'Evaluate.'
        : matched.length > 0
          ? 'The catalog has compatible cluster×trace experiments, but none is '
            + 'bound. A catalog count is not readiness — bind one to make '
            + 'serving runnable.'
          : 'Serving stays unavailable until a cluster×trace experiment lists '
            + 'this workload model and is bound.',
      action: servingBound ? (
        <Link className="btn btn-small" to={`/projects/${projectId}/serving`}>
          Open Serving →
        </Link>
      ) : matched.length > 0 ? (
        <button
          type="button" className="btn btn-small"
          disabled={bindingBusy}
          onClick={() => bindExperiment(matched[0])}
        >
          {bindingBusy ? 'Binding…' : 'Bind experiment'}
        </button>
      ) : (
        <Link className="btn btn-small" to={`/projects/${projectId}/serving`}>
          Open Serving →
        </Link>
      ),
      lines: bindingNote ? [bindingNote] : undefined,
    },
    {
      label: 'Power & energy',
      status: 'ESTIMATES ONLY',
      authority: energyView
        ? `${energyView.authorities.length} separate authorities`
        : 'authorities endpoint unreachable',
      consequence: energyView
        ? 'Tool-derived estimates only — never one number, never signoff.'
        : 'The energy authorities could not be loaded, so even estimate provenance is unknown.',
      lines: energyView
        ? energyView.authorities.map((a) => `${a.id} (${a.fidelity}): ${a.scope}`)
        : undefined,
    },
  ];

  return (
    <div className="scenario-stack">
      <p className="muted scenario-lede">{lede}</p>

      <LayerHead index="01" title="Design intent" note="Authored here — owned by the draft." />
      <div className="scenario-grid">
        <Card title="Workload" prov="EDITABLE">
          <div className="kv"><span>Model</span>
            <span>{catalogEntry?.display_name ?? modelName ?? '—'}</span>
          </div>
          <div className="kv"><span>Mode</span>
            <span>{str(workload['serving_mode'])?.replace(/_/g, ' ') ?? '—'}</span>
          </div>
          <div className="kv"><span>Parallelism</span>
            <span className="num">
              TP{dims[0] ?? '·'} / PP{dims[1] ?? '·'} / EP{dims[2] ?? '·'} / DP{dims[3] ?? '·'}
              {ranks != null ? ` → ${ranks} ranks` : ''}
            </span>
          </div>
          <div className="kv"><span>Communication</span>
            <span>{collectives.length} phase{collectives.length === 1 ? '' : 's'}</span>
          </div>
          <div className="empty-actions">
            <Link className="btn btn-small" to={`/projects/${projectId}/workload`}>
              Change workload
            </Link>
            <EditButton onEdit={onEditGroup} group="workload" label="Edit intent" />
          </div>
        </Card>

        <Card title="Hardware" prov="DERIVED">
          {!editingProfile ? (
            <>
              <div className="kv"><span>Components</span>
                <span className="num">
                  {computeCount > 0 ? `${computeCount} compute` : '—'}
                  {memoryCount > 0 ? ` · ${memoryCount} memory` : ''}
                </span>
              </div>
              <p className="muted">
                Inventory derived from the draft's agents — the compiler's
                parsed hardware.
              </p>
              {matchedProfile ? (
                <div className="hw-profile-bound">
                  <div className="kv"><span>Profile</span>
                    <span>{matchedProfile.vendor_model}
                      <span className="muted"> · {matchedProfile.device_kind}</span>
                    </span>
                  </div>
                  {matchedProfile.memory_capacity_bytes != null && (
                    <div className="kv"><span>Memory</span>
                      <span className="num">
                        {(matchedProfile.memory_capacity_bytes / 1e9).toFixed(0)} GB
                        {matchedProfile.memory_bandwidth_bytes_per_s != null
                          ? ` · ${(matchedProfile.memory_bandwidth_bytes_per_s / 1e9).toFixed(0)} GB/s`
                          : ''}
                      </span>
                    </div>
                  )}
                  {matchedProfile.timing_source && (
                    <p className="muted">
                      Timing source: measured LLMServingSim profile ·{' '}
                      {matchedProfile.timing_source.model} ·{' '}
                      {matchedProfile.timing_source.variant} · TP
                      {matchedProfile.timing_source.tp_degrees.join('/')} ·
                      consumed by serving. Design-time compute execution stays
                      NOT MODELED.
                    </p>
                  )}
                  <p className="muted profile-note">
                    Derived from tracked sources — descriptive at design time,
                    never part of the design hash.
                  </p>
                </div>
              ) : (
                <p className="muted">
                  No canonical hardware profile matches this design.
                </p>
              )}
              {matched.length > 0 && (
                <p className="muted">
                  Serving catalog lists {matched[0].display_name} — shape
                  only, not bound to this revision.
                </p>
              )}
              <details className="subtle profile-notes">
                <summary>Local hardware notes (not sent to the compiler)</summary>
                {profileFilled(profile) ? (
                  <>
                    {(profile.compute_units || profile.frequency || profile.peak_throughput) && (
                      <div className="kv"><span>Compute</span>
                        <span>{[profile.compute_units, profile.frequency, profile.peak_throughput]
                          .filter((v) => v).join(' · ')}</span>
                      </div>
                    )}
                    {(profile.local_memory || profile.l1 || profile.l2) && (
                      <div className="kv"><span>Cache / SRAM</span>
                        <span>{[profile.local_memory, profile.l1, profile.l2]
                          .filter((v) => v).join(' · ')}</span>
                      </div>
                    )}
                    {(profile.mem_type || profile.mem_capacity || profile.mem_bandwidth) && (
                      <div className="kv"><span>Memory</span>
                        <span>{[profile.mem_type, profile.mem_capacity, profile.mem_bandwidth]
                          .filter((v) => v).join(' · ')}</span>
                      </div>
                    )}
                    {profile.architecture && (
                      <div className="kv"><span>Architecture</span><span>{profile.architecture}</span></div>
                    )}
                  </>
                ) : (
                  <p className="muted">No notes recorded.</p>
                )}
                <p className="muted profile-note">
                  Stored in this browser only. These notes have NO compiler or
                  backend effect — a canonical hardware-profile contract is not
                  wired yet.
                </p>
                <div className="empty-actions">
                  <button type="button" className="btn btn-small" onClick={() => setEditingProfile(true)}>
                    {profileFilled(profile) ? 'Edit notes' : 'Add notes'}
                  </button>
                </div>
              </details>
            </>
          ) : (
            <form
              className="hw-profile-form"
              onSubmit={(e) => {
                e.preventDefault();
                const data = new FormData(e.currentTarget);
                const next = { ...EMPTY_PROFILE };
                for (const f of PROFILE_FIELDS) {
                  next[f.key] = String(data.get(f.key) ?? '').trim();
                }
                saveProfile(next);
                setEditingProfile(false);
              }}
            >
              <p className="muted profile-note">
                Descriptive only — stored in this browser, never sent to the compiler.
              </p>
              {PROFILE_FIELDS.map((f) => (
                <label key={f.key} className="field">
                  <span className="field-label">{f.label}</span>
                  <input name={f.key} defaultValue={profile[f.key]} placeholder={f.hint} />
                </label>
              ))}
              <div className="empty-actions">
                <button type="submit" className="btn btn-small btn-primary">Save profile</button>
                <button
                  type="button" className="btn btn-small"
                  onClick={() => { saveProfile({ ...EMPTY_PROFILE }); setEditingProfile(false); }}
                >
                  Clear
                </button>
                <button
                  type="button" className="btn btn-small"
                  onClick={() => setEditingProfile(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </Card>

        <Card title="Fabric" prov="EDITABLE">
          <div className="kv"><span>Topology</span>
            <span>{str(noc['topology_family']) ?? '—'}</span>
          </div>
          <div className="kv"><span>Links</span>
            <span>
              {num(noc['link_width']) != null ? `${noc['link_width']}-bit` : '—'}
              {num(physical['clock_freq_mhz']) != null ? ` · ${physical['clock_freq_mhz']} MHz` : ''}
            </span>
          </div>
          <div className="empty-actions">
            <EditButton onEdit={onEditGroup} group="fabric" label="Edit fabric" />
          </div>
        </Card>

        <Card title="Goals" prov="EDITABLE">
          {requirements.length > 0 ? (
            requirements.map((r, i) => (
              <div className="kv" key={i}>
                <span>{str(r['qos_class'])?.replace(/_/g, ' ') ?? `Goal ${i + 1}`}</span>
                <span className="muted">
                  {[r['traffic_class'], r['latency_ceiling_cycles'] != null
                    ? `≤ ${String(r['latency_ceiling_cycles'])} cycles` : null]
                    .filter((v) => v != null).join(' · ') || '—'}
                </span>
              </div>
            ))
          ) : (
            <p className="muted">No explicit goals — defaults apply.</p>
          )}
          <div className="empty-actions">
            <EditButton onEdit={onEditGroup} group="goals" label="Edit goals" />
          </div>
        </Card>
      </div>

      <LayerHead index="02" title="Interpretation" note="What the intent means for analysis." />
      <div className="scenario-grid">
        <Card title="Placement" prov="DERIVED">
          <div className="kv"><span>Physical endpoints</span>
            <span className="num">
              {endpoints > 0 ? endpoints : '—'}
              {computeCount > 0 || memoryCount > 0
                ? ` (${computeCount} compute · ${memoryCount} memory)` : ''}
            </span>
          </div>
          <div className="kv"><span>Workload participants</span>
            <span className="num">{ranks != null ? `${ranks} ranks` : 'unknown'}</span>
          </div>
          <div className="kv"><span>Rank placement</span>
            <span>
              {ranks != null && computeCount > 0
                ? `${ranks} ranks → ${Math.min(ranks, computeCount)} of ${computeCount} compute endpoints`
                : 'automatic — checked at compile'}
            </span>
          </div>
          <MiniMap ranks={ranks} compute={computeCount > 0 ? computeCount : null}
                   memory={memoryCount > 0 ? memoryCount : null} />
          <p className="muted">
            Automatic rank→endpoint mapping — never hand-placed here.{' '}
            <Link className="link" to={`/projects/${projectId}/compile`}>
              Inspect full mapping →
            </Link>
          </p>
        </Card>

        <Card title="Model coverage" prov="DERIVED">
          <p className="muted">What exactly VERITX will model. Select a row for its authority.</p>
          {modelRows.map((row) => <ModelCoverageRow key={row.label} row={row} />)}
        </Card>
      </div>

      <LayerHead index="03" title="Derived implementation"
                 note="Compiler output from the active revision — never authored here." />
      <div className="scenario-grid">
        <Card title="Implementation" prov="DERIVED">
          {derived ? (
            <>
              <div className="kv"><span>Fabric endpoints</span>
                <span className="num">{fmtNum(derived['endpoints'])}</span>
              </div>
              <div className="kv"><span>Routers</span>
                <span className="num">{fmtNum(derived['routers'])}</span>
              </div>
              <div className="kv"><span>Rank placement</span><span>automatic</span></div>
              <div className="kv"><span>Routing & VC assignment</span>
                <span className="muted">compiler derived — inspect under Compile → Resources</span>
              </div>
              <div className="kv"><span>Collective lowering</span>
                <span className="muted">compiler derived — inspect under Compile → Resources</span>
              </div>
              <div className="empty-actions">
                <Link className="link" to={`/projects/${projectId}/compile`}>
                  Inspect on Compile →
                </Link>
              </div>
            </>
          ) : (
            <p className="muted">
              No compiled revision — derived values appear after compile.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
