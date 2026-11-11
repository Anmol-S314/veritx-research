import { useCallback, useEffect, useMemo, useState, type ReactElement } from 'react';
import { gateway, gatewayReason, GATEWAY_START, type GatewayHealth } from './gateway';
import { Assumptions, Badge, Button, Field, Inspector, Notice, Properties, Section, downloadJson } from './ui';
import { comparisonIssue, type AblationIdentity } from './ablationEvidence';

/** Workload × topology ablation, read from a measured trace run.
 *
 *  The page deliberately keeps the two axes separate: a workload is a trace
 *  and a topology is a fabric config, and every cell is the same trace run
 *  against that config. Nothing here is a per-workload topology preset.
 *
 *  The tuner posts a bounded request to the repository gateway, which runs the
 *  same ``ablate_workloads.py`` script as the CLI. It never estimates a result:
 *  a cell is either measured and typed, or it is absent and explained.
 */

type AblationRun = AblationIdentity & {
  workload: string; workload_label: string; topology: string; topology_label: string;
  family: string; nodes: number; vcs: number; routing: string;
  packet_size: number; vc_buf_size: number; use_noc_latency: number;
  status: string;
  delivered_packets?: number; delivered_flits?: number;
  completion_cycles?: number;
  latency_mean?: number; latency_p50?: number; latency_p95?: number; latency_p99?: number;
  hops_avg?: number;
  throughput_packets_per_cycle?: number; throughput_flits_per_cycle?: number;
  accepted_packet_rate?: number;
  knobs?: Record<string, string>;
  effective_packet_size_flits?: number[];
  declared_buffer_flits_per_input?: number;
  resource_cost?: { storage_flits?: number | null; crosspoints?: number | null };
  qualification?: string;
};
type WorkloadMeta = {
  workload_id: string; label: string; nodes: number;
  active_nodes?: number; events?: number;
  trace_sha256?: string; trace_seed?: number | null; packet_size_flits?: number[];
  yaml?: string | null; trace?: string | null; project?: string | null;
};
type TopologyMeta = { topology_id: string; family: string; label: string; nodes: number; config: string; note?: string; support?: string };
type AblationCommon = {
  packet_size: number; vc_buf_size: number; use_noc_latency: number;
  seed?: number;
  note: string; overrides?: Record<string, string>;
  pipeline_normalized?: boolean;
};
type AblationDoc = {
  schema: string; generated_at: string; generated_by: string;
  common: AblationCommon;
  workloads: WorkloadMeta[]; topologies: TopologyMeta[]; runs: AblationRun[];
};
type TunedRun = {
  doc: AblationDoc;
  out: string;
  durationSeconds: number;
  failedCells: number;
  command?: string[];
};

type ObjectiveKey = 'latency_p95' | 'latency_p99' | 'latency_mean' | 'hops_avg' | 'completion_cycles' | 'throughput_flits_per_cycle';
const OBJECTIVES: Record<ObjectiveKey, { label: string; option: string; short: string; unit: string; digits: number; higher: boolean }> = {
  latency_p95: { label: 'packet P95 latency', option: 'P95 latency · lower is better', short: 'P95', unit: 'cyc', digits: 1, higher: false },
  latency_p99: { label: 'packet P99 latency', option: 'P99 latency · lower is better', short: 'P99', unit: 'cyc', digits: 1, higher: false },
  latency_mean: { label: 'mean packet latency', option: 'Mean latency · lower is better', short: 'mean', unit: 'cyc', digits: 1, higher: false },
  hops_avg: { label: 'average hops', option: 'Average hops · lower is better', short: 'hops', unit: 'hops', digits: 2, higher: false },
  completion_cycles: { label: 'completion cycles', option: 'Completion cycles · lower is better', short: 'completion', unit: 'cyc', digits: 0, higher: false },
  throughput_flits_per_cycle: { label: 'delivered flits / cycle', option: 'Flits / cycle · higher is better', short: 'throughput', unit: 'flits/cyc', digits: 2, higher: true },
};
const COLORS = ['#0f6c9e', '#a32928', '#246847', '#79540c', '#6b4f9e', '#0d7f7a', '#8a4b1f', '#3b6f8f', '#7a6a2f', '#6a4f7d', '#3f7a63', '#4f5f8a'];
const STRUCTURAL = new Set(['topology', 'k', 'n', 'c', 'x', 'y', 'xr', 'yr', 'o', 'd', 'mesh', 'hybrid', 'subnets', 'routing_function', 'num_vcs']);
const ARM_STRUCTURE_KEYS = ['k', 'n', 'c', 'x', 'y', 'xr', 'yr', 'o', 'd', 'mesh', 'hybrid', 'subnets'];
const RESERVED_OVERRIDES = new Set([...STRUCTURAL, 'sim_type', 'trace_file', 'trace_packet_log', 'packet_size', 'vc_buf_size', 'use_noc_latency', 'seed']);

const INITIAL_VARIANT = { packet: '', time: '1', burst: '0', stride: '1', offset: '0' };

const KNOB_DEFAULTS: Record<string, string> = {
  vc_allocator: 'islip',
  sw_allocator: 'islip',
  alloc_iters: '1',
  routing_delay: '1',
  vc_alloc_delay: '1',
  sw_alloc_delay: '1',
  credit_delay: '1',
  st_prepare_delay: '0',
  st_final_delay: '1',
  input_speedup: '1',
  output_speedup: '1',
  internal_speedup: '1.0',
  hold_switch_for_packet: '0',
  wait_for_tail_credit: '0',
};

type KnobField = {
  key: string;
  label: string;
  kind: 'select' | 'number';
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
};
const KNOB_FIELDS: KnobField[] = [
  { key: 'vc_allocator', label: 'VC allocator', kind: 'select', options: [{ value: 'islip', label: 'iSLIP' }, { value: 'separable_input_first', label: 'Separable input first' }] },
  { key: 'sw_allocator', label: 'Switch allocator', kind: 'select', options: [{ value: 'islip', label: 'iSLIP' }, { value: 'separable_input_first', label: 'Separable input first' }] },
  { key: 'alloc_iters', label: 'Allocator iterations', kind: 'number', min: 1, max: 8, step: 1 },
  { key: 'routing_delay', label: 'Routing delay', kind: 'number', min: 0, max: 10, step: 1, hint: 'cycles' },
  { key: 'vc_alloc_delay', label: 'VC alloc delay', kind: 'number', min: 0, max: 10, step: 1, hint: 'cycles' },
  { key: 'sw_alloc_delay', label: 'Switch alloc delay', kind: 'number', min: 0, max: 10, step: 1, hint: 'cycles' },
  { key: 'credit_delay', label: 'Credit delay', kind: 'number', min: 0, max: 10, step: 1, hint: 'cycles' },
  { key: 'st_prepare_delay', label: 'ST prepare delay', kind: 'number', min: 0, max: 10, step: 1, hint: 'cycles' },
  { key: 'st_final_delay', label: 'ST final delay', kind: 'number', min: 0, max: 10, step: 1, hint: 'cycles' },
  { key: 'input_speedup', label: 'Input speedup', kind: 'number', min: 1, max: 4, step: 1, hint: '×' },
  { key: 'output_speedup', label: 'Output speedup', kind: 'number', min: 1, max: 4, step: 1, hint: '×' },
  { key: 'internal_speedup', label: 'Internal speedup', kind: 'number', min: 1, max: 4, step: 0.5, hint: '×' },
  { key: 'hold_switch_for_packet', label: 'Hold switch for packet', kind: 'select', options: [{ value: '0', label: 'Off' }, { value: '1', label: 'On' }] },
  { key: 'wait_for_tail_credit', label: 'Wait for tail credit', kind: 'select', options: [{ value: '0', label: 'Off' }, { value: '1', label: 'On' }] },
];

/** Knobs that are not part of the normalised router pipeline but are safe to
 *  set per sweep. They still change what is measured, so each one is labelled
 *  with its scope. The key picker means nobody has to type ``key=value``. */
type ExtraKnob = KnobField & { defaultValue: string; scope: string };
const EXTRA_KNOBS: ExtraKnob[] = [
  { key: 'buffer_policy', label: 'Buffer policy', kind: 'select', defaultValue: 'private', scope: 'router / buffers',
    options: [{ value: 'private', label: 'Private per VC' }, { value: 'shared', label: 'Shared' }] },
  { key: 'priority', label: 'Packet priority', kind: 'select', defaultValue: 'none', scope: 'traffic / ordering',
    options: [
      { value: 'none', label: 'None' }, { value: 'class', label: 'Traffic class' }, { value: 'age', label: 'Age' },
      { value: 'network_age', label: 'Network age' }, { value: 'local_age', label: 'Local age' },
      { value: 'queue_length', label: 'Queue length' }, { value: 'hop_count', label: 'Hop count' }, { value: 'sequence', label: 'Sequence' },
    ] },
  { key: 'injection_rate_uses_flits', label: 'Injection-rate unit', kind: 'select', defaultValue: '0', scope: 'traffic',
    options: [{ value: '0', label: '0 · packets' }, { value: '1', label: '1 · flits' }] },
  { key: 'use_read_write', label: 'Read/write requests', kind: 'select', defaultValue: '0', scope: 'GEC traffic',
    options: [{ value: '0', label: 'Off' }, { value: '1', label: 'On' }] },
  { key: 'warmup_periods', label: 'Warmup periods', kind: 'number', min: 0, max: 100000, step: 1, defaultValue: '3', scope: 'simulation' },
  { key: 'sample_period', label: 'Sample period', kind: 'number', min: 1, max: 1000000000, step: 1, defaultValue: '10000', scope: 'simulation · cycles' },
  { key: 'sim_count', label: 'Simulation count', kind: 'number', min: 1, max: 100, step: 1, defaultValue: '1', scope: 'simulation' },
];

type Preset = { id: string; label: string; hint: string; packetSize?: number; tracePacketSize?: number; vcBufSize?: number; useNoCLatency?: number; knobs?: Record<string, string> };
const PRESETS: Preset[] = [
  { id: 'baseline', label: 'Bundled baseline', hint: 'The pinned values used by the bundled slice.' },
  { id: 'buffers', label: 'Deeper buffers', hint: 'vc_buf_size 8 → 16', vcBufSize: 16 },
  { id: 'allocator', label: 'Allocator search', hint: 'alloc_iters 1 → 2', knobs: { alloc_iters: '2' } },
  { id: 'latency', label: 'NoC latency pricing', hint: 'use_noc_latency 0 → 1', useNoCLatency: 1 },
  { id: 'combined', label: 'Buffers + allocator', hint: 'vc_buf_size 16 · alloc_iters 2', vcBufSize: 16, knobs: { alloc_iters: '2' } },
  { id: 'packets', label: 'Wider trace packets', hint: 'Rewrite trace payloads to 8 flits; a workload variant', tracePacketSize: 8 },
];

function useJson(path: string): { doc: AblationDoc | null; error: string | null } {
  const [value, setValue] = useState<{ doc: AblationDoc | null; error: string | null }>({ doc: null, error: null });
  useEffect(() => {
    let live = true;
    fetch(path, { cache: 'no-store' })
      .then(response => response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then(text => {
        if (!live) return;
        try {
          const parsed = JSON.parse(text) as unknown;
          if (!isAblationDoc(parsed)) throw new Error('The file does not match veritx/workload-ablation/1.');
          setValue({ doc: parsed, error: null });
        } catch (error) { setValue({ doc: null, error: `Ablation data unreadable: ${String(error)}` }); }
      })
      .catch(error => { if (live) setValue({ doc: null, error: String(error.message ?? error) }); });
    return () => { live = false; };
  }, [path]);
  return value;
}

function isAblationDoc(value: unknown): value is AblationDoc {
  if (!value || typeof value !== 'object') return false;
  const doc = value as Partial<AblationDoc>;
  return doc.schema === 'veritx/workload-ablation/1'
    && Array.isArray(doc.workloads)
    && Array.isArray(doc.topologies)
    && Array.isArray(doc.runs)
    && !!doc.common
    && typeof doc.generated_at === 'string';
}

function valueOf(run: AblationRun, objective: ObjectiveKey): number | null {
  const value = run[objective];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function rankFor(runs: AblationRun[], objective: ObjectiveKey): AblationRun[] {
  return [...runs].sort((a, b) => {
    const av = valueOf(a, objective), bv = valueOf(b, objective);
    if (av === null && bv === null) return a.topology.localeCompare(b.topology);
    if (av === null) return 1;
    if (bv === null) return -1;
    return OBJECTIVES[objective].higher ? bv - av : av - bv;
  });
}

function fmt(run: AblationRun, objective: ObjectiveKey): string {
  const value = valueOf(run, objective);
  return value === null ? '—' : value.toFixed(OBJECTIVES[objective].digits);
}

function fmtNumber(value: number, objective: ObjectiveKey): string {
  return value.toFixed(OBJECTIVES[objective].digits);
}

function fmtCompact(value: number, objective: ObjectiveKey): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 100_000) return `${(value / 1_000).toFixed(0)}k`;
  return value.toFixed(OBJECTIVES[objective].digits);
}

function count(value?: number): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
}

function stamp(value?: string): string {
  if (!value) return 'not recorded';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function stampDay(value?: string): string {
  if (!value) return 'not recorded';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function shortIdentity(value?: string | null): string {  if (!value) return 'not recorded';
  return value.length > 22 ? `${value.slice(0, 19)}…` : value;
}

function packetSizeLabel(values?: number[]): string {
  if (!values?.length) return 'Not recorded; the config packet default is not proof of effective payload';
  if (values.length === 1) return `${values[0]} flits`;
  const min = values[0], max = values[values.length - 1];
  if (min === max) return `${min} flits`;
  return `${min}–${max} flits (${values.length} distinct)`;
}

function extraKnobError(field: ExtraKnob, value: string): string | null {
  if (!value.trim()) return `${field.label} needs a value.`;
  if (field.kind === 'select') {
    return field.options?.some(option => option.value === value) ? null : `${field.label} has an unsupported value.`;
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return `${field.label} must be a number.`;
  if ((field.step ?? 1) === 1 && !Number.isInteger(numeric)) return `${field.label} must be an integer.`;
  if (field.min !== undefined && numeric < field.min) return `${field.label} must be at least ${field.min}.`;
  if (field.max !== undefined && numeric > field.max) return `${field.label} must be at most ${field.max}.`;
  return null;
}

function knobScope(key: string): string {
  if (STRUCTURAL.has(key)) return 'topology / routing';
  if (key.startsWith('srota_')) return 'SROTA config';
  if (['vc_buf_size', 'packet_size', 'use_noc_latency', 'traffic', 'injection_rate', 'classes',
    'priority', 'injection_rate_uses_flits', 'use_read_write'].includes(key)) return 'traffic / model';
  if (['warmup_periods', 'sample_period', 'sim_count', 'sim_type', 'watch_out'].includes(key)) return 'simulation / output';
  if (['buffer_policy', 'buf_size', 'channel_width'].includes(key)) return 'router / buffers';
  if (['vc_allocator', 'sw_allocator', 'alloc_iters', 'routing_delay', 'vc_alloc_delay', 'sw_alloc_delay',
    'credit_delay', 'st_prepare_delay', 'st_final_delay', 'input_speedup', 'output_speedup',
    'internal_speedup', 'wait_for_tail_credit', 'router'].includes(key)) return 'flow / router';
  return 'other';
}

function workloadSource(workload: WorkloadMeta): 'project' | 'example' {
  return workload.project ? 'project' : 'example';
}

function pickedKnobValues(doc: AblationDoc): Record<string, string> {
  const values = { ...KNOB_DEFAULTS };
  for (const field of KNOB_FIELDS) {
    const recorded = doc.common.overrides?.[field.key];
    if (recorded !== undefined) values[field.key] = recorded;
  }
  return values;
}

function unknownOverrides(doc: AblationDoc): Record<string, string> {
  const known = new Set(KNOB_FIELDS.map(field => field.key));
  return Object.fromEntries(Object.entries(doc.common.overrides ?? {}).filter(([key]) => !known.has(key) && !RESERVED_OVERRIDES.has(key)));
}

function extraText(overrides: Record<string, string>): string {
  return Object.entries(overrides).map(([key, value]) => `${key}=${value}`).join(' ');
}

function parseExtra(text: string): { values: Record<string, string>; errors: string[] } {
  const values: Record<string, string> = {};
  const errors: string[] = [];
  const tokens = text.split(/[,\s]+/).map(token => token.trim()).filter(Boolean);
  for (const token of tokens) {
    const equals = token.indexOf('=');
    if (equals <= 0) { errors.push(`"${token}" is not a key=value pair.`); continue; }
    const key = token.slice(0, equals).trim(), value = token.slice(equals + 1).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_.]*$/.test(key)) { errors.push(`"${key}" is not a valid BookSim key.`); continue; }
    if (!/^[A-Za-z0-9_.+-]+$/.test(value)) { errors.push(`"${value}" is not a valid value for ${key}.`); continue; }
    if (RESERVED_OVERRIDES.has(key)) { errors.push(`${key} is a structural axis; use the pinned controls.`); continue; }
    if (KNOB_FIELDS.some(field => field.key === key)) { errors.push(`${key} is controlled above, not in the extra field.`); continue; }
    values[key] = value;
  }
  return { values, errors };
}

function percentDelta(next: number, previous: number, higher: boolean): number | null {
  if (!Number.isFinite(next) || !Number.isFinite(previous) || previous === 0) return null;
  const delta = (next - previous) / Math.abs(previous) * 100;
  return higher ? delta : -delta;
}

type CellComparison = {
  workload: string; workloadLabel: string; topology: string; topologyLabel: string;
  baseline: number; tuned: number; delta: number; pct: number | null; better: boolean | null;
};
type WorkloadComparison = {
  workload: WorkloadMeta;
  baselineBest: AblationRun | null; tunedBest: AblationRun | null;
  baselineValue: number | null; tunedValue: number | null;
  pct: number | null; better: boolean | null; winnerChanged: boolean;
};

function compareRuns(baseline: AblationDoc, tuned: AblationDoc, objective: ObjectiveKey) {
  const baselineCells = new Map(baseline.runs.map(run => [`${run.workload}::${run.topology}`, run]));
  const workloadMap = new Map(tuned.workloads.map(workload => [workload.workload_id, workload]));
  const cells: CellComparison[] = [];
  const blocked: string[] = [];
  for (const run of tuned.runs) {
    const previous = baselineCells.get(`${run.workload}::${run.topology}`);
    if (!previous || run.status !== 'ok' || previous.status !== 'ok') continue;
    const issue = comparisonIssue(previous, run);
    if (issue) { blocked.push(`${run.workload}/${run.topology}: ${issue}`); continue; }
    const nextValue = valueOf(run, objective), previousValue = valueOf(previous, objective);
    if (nextValue === null || previousValue === null) continue;
    const delta = nextValue - previousValue;
    const pct = percentDelta(nextValue, previousValue, OBJECTIVES[objective].higher);
    cells.push({
      workload: run.workload,
      workloadLabel: workloadMap.get(run.workload)?.label ?? run.workload_label,
      topology: run.topology,
      topologyLabel: run.topology_label,
      baseline: previousValue,
      tuned: nextValue,
      delta,
      pct,
      better: pct === null ? null : pct > 0.05 ? true : pct < -0.05 ? false : null,
    });
  }

  const perWorkload: WorkloadComparison[] = [];
  for (const workload of tuned.workloads) {
    const comparableArms = new Set(cells.filter(cell => cell.workload === workload.workload_id).map(cell => cell.topology));
    const tunedRuns = tuned.runs.filter(run => run.workload === workload.workload_id && comparableArms.has(run.topology));
    // Compare winners over the same measured arm set. A one-arm rerun must not
    // be scored against the all-arm baseline winner.
    const measuredArms = new Set(tunedRuns.map(run => run.topology));
    const baselineRuns = baseline.runs.filter(run => run.workload === workload.workload_id && run.status === 'ok' && measuredArms.has(run.topology));
    const baselineBest = rankFor(baselineRuns.filter(run => valueOf(run, objective) !== null), objective)[0] ?? null;
    const tunedBest = rankFor(tunedRuns.filter(run => valueOf(run, objective) !== null), objective)[0] ?? null;
    const baselineValue = baselineBest ? valueOf(baselineBest, objective) : null;
    const tunedValue = tunedBest ? valueOf(tunedBest, objective) : null;
    const pct = baselineValue !== null && tunedValue !== null ? percentDelta(tunedValue, baselineValue, OBJECTIVES[objective].higher) : null;
    perWorkload.push({
      workload,
      baselineBest,
      tunedBest,
      baselineValue,
      tunedValue,
      pct,
      better: pct === null ? null : pct > 0.05 ? true : pct < -0.05 ? false : null,
      winnerChanged: Boolean(baselineBest && tunedBest && baselineBest.topology !== tunedBest.topology),
    });
  }

  return {
    cells,
    blocked,
    perWorkload,
    improved: cells.filter(cell => cell.better === true).length,
    regressed: cells.filter(cell => cell.better === false).length,
    unchanged: cells.filter(cell => cell.better === null).length,
    winnerChanges: perWorkload.filter(row => row.winnerChanged).length,
  };
}

function useGatewayHealth() {
  const [health, setHealth] = useState<{ state: 'checking' | 'online' | 'offline'; detail?: string; stale?: string }>({ state: 'checking' });
  const check = useCallback(() => {
    setHealth({ state: 'checking' });
    gateway.health()
      .then((value: GatewayHealth & { code?: { stale?: boolean; reason?: string } }) => setHealth({
        state: 'online',
        stale: value.code?.stale ? value.code.reason : undefined,
      }))
      .catch(error => setHealth({ state: 'offline', detail: gatewayReason(error) }));
  }, []);
  useEffect(() => { check(); }, [check]);
  useEffect(() => {
    const onFocus = () => check();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [check]);
  return { ...health, check };
}

export default function WorkloadAblations(): ReactElement {
  const { doc: baseline, error } = useJson('/data/workload_ablation.json');
  const [tuned, setTuned] = useState<TunedRun | null>(null);
  const [datasetView, setDatasetView] = useState<'baseline' | 'tuned'>('baseline');
  const [workloadId, setWorkloadId] = useState('');
  const [objective, setObjective] = useState<ObjectiveKey>('latency_p95');
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [focus, setFocus] = useState<{ workload: string; topology: string } | null>(null);
  const [sourceFilter, setSourceFilter] = useState<'all' | 'project' | 'example'>('all');
  const { check, ...health } = useGatewayHealth();

  const doc = datasetView === 'tuned' && tuned ? tuned.doc : baseline;
  const runs = doc?.runs ?? [];
  const workloads = doc?.workloads ?? [];
  const topologies = doc?.topologies ?? [];
  const activeWorkload = workloads.find(workload => workload.workload_id === workloadId) ?? workloads[0];
  const activeId = activeWorkload?.workload_id ?? '';
  const visible = useMemo(() => new Set(chosen ?? topologies.map(topology => topology.topology_id)), [chosen, topologies]);
  const workloadRuns = runs.filter(run => run.workload === activeId);
  const ranked = rankFor(workloadRuns.filter(run => visible.has(run.topology)), objective);
  const best = ranked.find(run => run.status === 'ok' && valueOf(run, objective) !== null) ?? null;
  const runnerUp = ranked.filter(run => run !== best && run.status === 'ok' && valueOf(run, objective) !== null)[0] ?? null;
  const bestSupport = best ? topologies.find(topology => topology.topology_id === best.topology)?.support ?? 'product' : null;
  const objectiveInfo = OBJECTIVES[objective];
  const inspected = focus
    ? runs.find(run => run.workload === focus.workload && run.topology === focus.topology) ?? null
    : best;
  const inspectedTopology = topologies.find(topology => topology.topology_id === inspected?.topology) ?? null;
  const inspectedKnobs = inspected
    ? Object.entries(inspected.knobs ?? {})
      .filter(([key]) => key !== 'trace_file' && key !== 'trace_packet_log')
      .sort(([a], [b]) => knobScope(a).localeCompare(knobScope(b)) || a.localeCompare(b))
    : [];
  const baselineRun = tuned && inspected && datasetView === 'tuned'
    ? baseline?.runs.find(run => run.workload === inspected.workload && run.topology === inspected.topology) ?? null
    : null;
  const projectCount = workloads.filter(workload => workload.project).length;
  const productArms = topologies.filter(topology => (topology.support ?? 'product') === 'product').length;
  const researchArms = topologies.filter(topology => topology.support === 'research').length;
  const bookSimArms = topologies.length - productArms - researchArms;
  const okCount = runs.filter(run => run.status === 'ok').length;
  const failedCount = runs.length - okCount;

  useEffect(() => { setFocus(null); setChosen(null); setSourceFilter('all'); }, [datasetView]);

  const knobRows = (() => {
    const values = new Map<string, { values: Set<string>; cells: number }>();
    for (const run of runs) {
      for (const [key, value] of Object.entries(run.knobs ?? {})) {
        if (key === 'trace_file' || key === 'trace_packet_log') continue;
        const entry = values.get(key) ?? { values: new Set<string>(), cells: 0 };
        entry.values.add(value);
        entry.cells += 1;
        values.set(key, entry);
      }
    }
    return [...values.entries()].map(([key, entry]) => ({
      key,
      scope: knobScope(key),
      values: [...entry.values].sort(),
      covered: entry.cells,
      structural: STRUCTURAL.has(key),
    })).sort((a, b) => a.scope.localeCompare(b.scope) || a.key.localeCompare(b.key));
  })();

  const pinnedKnobs = knobRows.filter(knob => !knob.structural && knob.values.length === 1);
  const variedKnobs = knobRows.filter(knob => !knob.structural && knob.values.length > 1);
  const structuralKnobs = knobRows.filter(knob => knob.structural);

  const selectCell = (workload: string, topology: string) => {
    setWorkloadId(workload);
    setFocus({ workload, topology });
  };

  if (error) return <div className="view-main"><Notice tone="red">Workload ablation file unreadable: {error}</Notice></div>;
  if (!baseline || !doc) return <div className="view-main"><p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading workload ablation…</p></div>;

  const common = doc.common;
  const baselineOverrides = Object.entries(common.overrides ?? {});
  const structuralByArm = new Map<string, Record<string, string>>(topologies.map(topology => {
    const knobs = runs.find(run => run.topology === topology.topology_id)?.knobs;
    return [topology.topology_id, knobs ?? {}] as const;
  }));
  const rankDelta = best && runnerUp
    ? (() => {
      const a = valueOf(best, objective), b = valueOf(runnerUp, objective);
      if (a === null || b === null || b === 0) return null;
      return Math.abs((a - b) / b) * 100;
    })()
    : null;
  const bestGap = best && inspected && inspected !== best
    ? (() => {
      const a = valueOf(inspected, objective), b = valueOf(best, objective);
      if (a === null || b === null || b === 0) return null;
      return percentDelta(a, b, objectiveInfo.higher);
    })()
    : null;

  const bars = ranked.filter(run => run.status === 'ok' && valueOf(run, objective) !== null);
  const barValues = bars.map(run => valueOf(run, objective) as number);
  const barMin = Math.min(...barValues), barMax = Math.max(...barValues);
  const barScore = (value: number) => {
    if (objectiveInfo.higher) return barMax === 0 ? 100 : 100 * value / barMax;
    if (!Number.isFinite(value) || value <= 0 || barMin <= 0) return 100;
    return 100 * barMin / value;
  };

  const matrixWorkloads = workloads.filter(workload => sourceFilter === 'all' || workloadSource(workload) === sourceFilter);
  const projectWorkloads = workloads.filter(workload => workloadSource(workload) === 'project').length;
  const exampleWorkloads = workloads.length - projectWorkloads;

  const onMeasured = (run: TunedRun) => {
    setTuned(run);
    setDatasetView('tuned');
    setChosen(null);
    setFocus(null);
  };

  const scrollToTune = () => {
    const target = document.getElementById('tune-workloads');
    const main = target?.closest('.view-main') as HTMLElement | null;
    if (!target || !main) return;
    const controls = main.querySelector('.abl-controls') as HTMLElement | null;
    const offset = (controls?.offsetHeight ?? 68) + 24;
    const top = target.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - offset;
    main.scrollTo({ top, behavior: 'smooth' });
  };

  return <div className="view-layout abl-layout">
    <div className="view-main abl-main" id="ablation-main">
      <div className="abl-facts" aria-label="Slice coverage">
        <span><strong>{workloads.length}</strong><small>{workloads.length === 1 ? 'workload' : 'workloads'}</small></span>
        <span><strong>{projectCount}</strong><small>{projectCount === 1 ? 'project trace' : 'project traces'}</small></span>
        <span><strong>{topologies.length}</strong><small>{topologies.length === 1 ? 'fabric arm' : 'fabric arms'}</small></span>
        <span><strong>{runs.length}</strong><small>{runs.length === 1 ? 'measured cell' : 'measured cells'}</small></span>
        <span><strong>{okCount}</strong><small>{okCount === 1 ? 'cell ok' : 'cells ok'}</small></span>
        <span><strong>{failedCount}</strong><small>{failedCount === 1 ? 'typed failure' : 'typed failures'}</small></span>
        <span className="abl-fact-version" title={stamp(doc.generated_at)}><strong>{stampDay(doc.generated_at)}</strong><small>{datasetView === 'tuned' ? 'tuned run' : 'bundled baseline'}</small></span>
      </div>

      <div className="abl-controls">
        <label className="field"><span>Workload</span>
          <select value={activeId} onChange={event => { setWorkloadId(event.target.value); setFocus(null); }}>
            <optgroup label={`Project traces (${projectWorkloads})`}>
              {workloads.filter(workload => workload.project).map(workload => <option key={workload.workload_id} value={workload.workload_id}>{workload.label}</option>)}
            </optgroup>
            <optgroup label={`BookSim examples (${exampleWorkloads})`}>
              {workloads.filter(workload => !workload.project).map(workload => <option key={workload.workload_id} value={workload.workload_id}>{workload.label}</option>)}
            </optgroup>
          </select>
        </label>
        <label className="field"><span>Rank by</span>
          <select value={objective} onChange={event => setObjective(event.target.value as ObjectiveKey)}>
            {Object.entries(OBJECTIVES).map(([key, info]) => <option key={key} value={key}>{info.option}</option>)}
          </select>
        </label>
        <div className="abl-control-actions">
          {tuned && <div className="segmented" role="group" aria-label="Measured dataset">
            <button type="button" className={datasetView === 'baseline' ? 'active' : ''} aria-pressed={datasetView === 'baseline'} onClick={() => setDatasetView('baseline')}>Bundled</button>
            <button type="button" className={datasetView === 'tuned' ? 'active' : ''} aria-pressed={datasetView === 'tuned'} onClick={() => setDatasetView('tuned')}>Tuned</button>
          </div>}
          <span className="abl-visible-count"><strong>{visible.size}</strong> of {topologies.length} {topologies.length === 1 ? 'fabric' : 'fabrics'}</span>
          <Button onClick={() => setChosen(new Set(topologies.map(topology => topology.topology_id)))}>All candidates</Button>
          <Button onClick={() => { setChosen(new Set(best ? [best.topology] : [])); }}>Best only</Button>
          <Button primary onClick={scrollToTune}>Tune &amp; rerun</Button>
        </div>
      </div>

      <div className="curve-legend" role="group" aria-label="Candidate topologies">
        {topologies.map((topology, index) => {
          const on = visible.has(topology.topology_id);
          const run = workloadRuns.find(row => row.topology === topology.topology_id);
          return <button key={topology.topology_id} type="button" aria-pressed={on}
            className={on ? 'curve-chip on' : 'curve-chip'}
            title={`${topology.label} · ${topology.family} · ${topology.support ?? 'product'} · ${on ? 'hide from' : 'show in'} ranking`}
            onClick={() => setChosen(current => {
              const next = new Set(current ?? topologies.map(t => t.topology_id));
              if (next.has(topology.topology_id)) next.delete(topology.topology_id); else next.add(topology.topology_id);
              return next;
            })}>
            <i style={{ background: COLORS[index % COLORS.length] }} />
            <span className="mono">{topology.label}</span>
            <small>{run?.vcs ?? '—'} VC</small>
          </button>;
        })}
      </div>

      {activeWorkload && <Section title={`Best candidate for ${activeWorkload.label}`}
        actions={<><Badge tone="amber">{objectiveInfo.label}</Badge><Badge>{activeWorkload.project ? 'project trace' : 'BookSim example'}</Badge></>}>
        <div className="abl-outcome">
          <div className="abl-winner">
            {best ? <>
              <strong className="abl-winner-name">{best.topology_label}</strong>
              <div className="abl-winner-value numeric">{fmt(best, objective)} <small>{objectiveInfo.unit}</small></div>
              <dl className="abl-winner-meta">
                <div><dt>Family / VCs</dt><dd>{best.family} · {best.vcs}</dd></div>
                <div><dt>Support</dt><dd>{bestSupport ?? 'product'}</dd></div>
                <div><dt>Routing</dt><dd className="mono">{best.routing}</dd></div>
                <div><dt>Runner-up</dt><dd>{runnerUp ? <>{runnerUp.topology_label} · {fmt(runnerUp, objective)}</> : 'none measured'}</dd></div>
                <div><dt>Gap to runner-up</dt><dd>{rankDelta !== null ? (rankDelta < 0.05 ? 'tie' : `${rankDelta.toFixed(1)}%`) : '—'}</dd></div>
              </dl>
            </> : <Notice tone="amber">No selected candidate produced a numeric {objectiveInfo.label} for this workload.</Notice>}
          </div>

          <div className="abl-ranking">
            <div className="abl-ranking-head">
              <h3>{objectiveInfo.label} by candidate</h3>
              <span className="meta-line">Longer bar = better · click a row to inspect</span>
            </div>
            <div className="hop-bars" role="list" aria-label={`${objectiveInfo.label} by candidate topology`}>
              {bars.map((run, index) => {
                const value = valueOf(run, objective) as number;
                const gap = percentDelta(value, barValues[0], objectiveInfo.higher);
                const isBest = best?.topology === run.topology;
                return <div className={`hop-row ${isBest ? 'best' : ''} ${focus?.topology === run.topology && focus?.workload === run.workload ? 'active' : ''}`}
                  role="listitem" key={run.topology} tabIndex={0}
                  aria-label={`${run.topology_label}: ${value.toFixed(objectiveInfo.digits)} ${objectiveInfo.unit}`}
                  onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setFocus({ workload: run.workload, topology: run.topology }); } }}
                  onClick={() => setFocus({ workload: run.workload, topology: run.topology })}>
                  <span className="abl-rank-index numeric">{index + 1}</span>
                  <span className="hop-name mono">{run.topology_label}</span>
                  <span className="hop-track"><i style={{ width: `${Math.max(2, barScore(value))}%` }} /></span>
                  <span className="hop-value numeric" title={value.toFixed(objectiveInfo.digits)}>{fmtCompact(value, objective)}</span>
                  <span className="abl-delta numeric" title={isBest ? 'Best measured value for this objective' : 'Gap to the best measured value'}>
                    {isBest ? 'best' : gap === null ? '—' : Math.abs(gap) < 0.05 ? 'tie' : `gap ${Math.abs(gap).toFixed(1)}%`}
                  </span>
                </div>;
              })}
            </div>
            <details className="abl-ranking-details">
              <summary>Table view ({ranked.length})</summary>
              <div className="table-scroll"><table><thead><tr>
                <th>Rank</th><th>Topology</th><th>VCs</th><th>P50</th><th>P95</th><th>P99</th><th>Hops</th><th>Status</th>
              </tr></thead><tbody>
                {ranked.map((run, index) => <tr key={run.topology} tabIndex={0}
                  className={best?.topology === run.topology || focus?.topology === run.topology ? 'selected' : undefined}
                  onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setFocus({ workload: run.workload, topology: run.topology }); } }}
                  onClick={() => setFocus({ workload: run.workload, topology: run.topology })}>
                  <td className="numeric">{run.status === 'ok' && valueOf(run, objective) !== null ? index + 1 : '—'}</td>
                  <th><span className="mono">{run.topology_label}</span>{best?.topology === run.topology && <> <Badge tone="green">best</Badge></>}
                    <br /><small>{run.family} · {run.routing}</small></th>
                  <td className="numeric">{run.vcs}</td>
                  <td className="numeric">{run.latency_p50?.toFixed(1) ?? '—'}</td>
                  <td className="numeric">{run.latency_p95?.toFixed(1) ?? '—'}</td>
                  <td className="numeric">{run.latency_p99?.toFixed(1) ?? '—'}</td>
                  <td className="numeric">{run.hops_avg?.toFixed(2) ?? '—'}</td>
                  <td>{run.status === 'ok' ? <Badge tone="green">ok</Badge> : <Badge tone="amber">{run.status}</Badge>}</td>
                </tr>)}
              </tbody></table></div>
            </details>
          </div>
        </div>
      </Section>}

      <Section title="Workload × topology matrix"
        actions={<><Badge>{okCount} ok {okCount === 1 ? 'cell' : 'cells'}</Badge><Badge>{projectCount} project · {exampleWorkloads} {exampleWorkloads === 1 ? 'example' : 'examples'}</Badge></>}>
        <div className="abl-matrix-toolbar">
          <div className="segmented" role="group" aria-label="Workload source">
            <button type="button" className={sourceFilter === 'all' ? 'active' : ''} aria-pressed={sourceFilter === 'all'} onClick={() => setSourceFilter('all')}>All workloads ({workloads.length})</button>
            <button type="button" className={sourceFilter === 'project' ? 'active' : ''} aria-pressed={sourceFilter === 'project'} onClick={() => setSourceFilter('project')}>Project traces ({projectCount})</button>
            <button type="button" className={sourceFilter === 'example' ? 'active' : ''} aria-pressed={sourceFilter === 'example'} onClick={() => setSourceFilter('example')}>Examples ({exampleWorkloads})</button>
          </div>
          <span className="meta-line">Row-normalized heat; outlined cell is the row best.</span>
        </div>
        <div className="table-scroll abl-matrix-scroll"><table className="mapping-table abl-matrix"><thead><tr>
          <th>Workload</th>{topologies.map((topology, index) => <th key={topology.topology_id} className="mono">
            <span className="abl-matrix-arm"><i style={{ background: COLORS[index % COLORS.length] }} />{topology.label}{topology.support && topology.support !== 'product' ? ' †' : ''}</span>
            <small title={`${topology.family} · ${topology.label} · ${topology.support ?? 'product'}`}>{runs.find(run => run.topology === topology.topology_id)?.vcs ?? '—'} VC</small>
          </th>)}
        </tr></thead><tbody>
          {matrixWorkloads.map(workload => {
            const cells = runs.filter(run => run.workload === workload.workload_id);
            const values = cells.filter(run => run.status === 'ok').map(run => valueOf(run, objective)).filter((value): value is number => value !== null);
            const min = values.length ? Math.min(...values) : 0, max = values.length ? Math.max(...values) : 0;
            const bestCell = rankFor(cells.filter(run => run.status === 'ok' && valueOf(run, objective) !== null), objective)[0] ?? null;
            return <tr key={workload.workload_id}>
              <th scope="row">
                <button type="button" className="abl-workload-label" onClick={() => { setWorkloadId(workload.workload_id); setFocus(null); }}>
                  <span>{workload.label}</span>
                  <small><span className={`abl-source-dot ${workload.project ? 'project' : ''}`} />{workload.project ? 'project trace' : 'BookSim example'}
                    {workload.events !== undefined ? ` · ${count(workload.events)} events` : ''}
                    {workload.active_nodes !== undefined ? ` · ${workload.active_nodes} active` : ''}</small>
                </button>
              </th>
              {topologies.map((topology, index) => {
                const run = cells.find(cell => cell.topology === topology.topology_id);
                const value = run?.status === 'ok' ? valueOf(run, objective) : null;
                const normalized = value === null || max === min ? 0.5 : (value - min) / (max - min);
                const strength = objectiveInfo.higher ? normalized : 1 - normalized;
                const lightness = 94 - strength * 48;
                const bg = `hsl(205 62% ${lightness.toFixed(1)}%)`;
                const isDark = lightness < 63;
                const isBest = bestCell?.topology === topology.topology_id;
                const isVisible = visible.has(topology.topology_id);
                const isFocus = focus?.workload === workload.workload_id && focus.topology === topology.topology_id;
                const rank = run ? rankFor(cells.filter(cell => cell.status === 'ok' && valueOf(cell, objective) !== null), objective).findIndex(cell => cell.topology === topology.topology_id) + 1 : 0;
                return <td key={topology.topology_id}>
                  <button type="button" className="matrix-cell abl-matrix-cell"
                    style={{
                      background: bg,
                      color: isDark ? '#fff' : '#17374b',
                      outline: isBest ? `2px solid ${COLORS[index % COLORS.length]}` : isFocus ? '2px solid #163c54' : undefined,
                      outlineOffset: isBest || isFocus ? 1 : undefined,
                      opacity: isVisible ? 1 : 0.4,
                    }}
                    title={run ? `${workload.label} · ${topology.label}\n${objectiveInfo.label}: ${value === null ? '—' : value.toFixed(objectiveInfo.digits)} ${objectiveInfo.unit}\nP95: ${run.latency_p95?.toFixed(1) ?? '—'} cyc · VCs: ${run.vcs} · ${run.routing}` : 'Not measured'}
                    onClick={() => selectCell(workload.workload_id, topology.topology_id)}
                    aria-label={`${workload.label} on ${topology.label}: ${value === null ? 'no value' : `${value.toFixed(objectiveInfo.digits)} ${objectiveInfo.unit}`}`}>
                    <span className="abl-matrix-value" title={value === null ? 'not measured' : `${value.toFixed(objectiveInfo.digits)} ${objectiveInfo.unit}`}>{value === null ? '—' : fmtCompact(value, objective)}</span>
                    <span className="abl-matrix-sub">{isBest ? 'best' : rank > 0 && run?.status === 'ok' ? `#${rank}` : run?.status ?? 'not measured'}</span>
                  </button>
                </td>;
              })}
            </tr>;
          })}
        </tbody></table></div>
        <div className="legend">
          <span>Darker = better {objectiveInfo.label} within the row</span>
          <span>Outline = row best</span>
          <span>— = not measured</span>
          <span>† Research or BookSim-only arm</span>
        </div>
      </Section>

      <div id="tune-workloads">
        <TuningWorkbench
          baseline={baseline}
          activeWorkloadId={activeId}
          baselineLabel={datasetView === 'tuned' ? 'bundled baseline' : 'current baseline'}
          tuned={tuned}
          objective={objective}
          health={health}
          onCheckGateway={check}
          onMeasured={onMeasured}
          onOpenTuned={() => setDatasetView('tuned')}
          onOpenBaseline={() => setDatasetView('baseline')}
          currentView={datasetView}
        />
      </div>

      <Section title="Candidate arms"
        actions={<>
          <Badge>{topologies.length} {topologies.length === 1 ? 'fabric' : 'fabrics'} · {runs.length} {runs.length === 1 ? 'trace run' : 'trace runs'}</Badge>
          <Badge tone="amber">{topologies.filter(topology => topology.support && topology.support !== 'product').length} non-product</Badge>
        </>}>
        <div className="table-scroll"><table className="arm-table"><thead><tr>
          <th>Arm</th><th>Family</th><th>Support</th><th>Endpoints</th><th>VCs</th><th>Routing</th><th>Structure</th><th>Config</th>
        </tr></thead><tbody>
          {topologies.map((topology, index) => {
            const arm = structuralByArm.get(topology.topology_id) ?? {};
            const structure = ARM_STRUCTURE_KEYS.filter(key => arm[key] !== undefined).map(key => `${key}=${arm[key]}`).join(' · ');
            const support = topology.support ?? 'product';
            return <tr key={topology.topology_id}>
              <th><i className="arm-swatch" style={{ background: COLORS[index % COLORS.length] }} aria-hidden="true" /><span className="mono arm-name">{topology.label}</span></th>
              <td>{topology.family}</td>
              <td><Badge tone={support === 'product' ? 'blue' : support === 'research' ? 'amber' : 'red'}>{support}</Badge></td>
              <td className="numeric">{topology.nodes}</td>
              <td className="numeric">{arm.num_vcs ?? '—'}</td>
              <td className="mono">{arm.routing_function ?? '—'}</td>
              <td className="mono arm-structure">{structure || '—'}</td>
              <td className="mono arm-config">{topology.config}{topology.note && <><br /><small className="arm-note">{topology.note.replace(/;?\s*product registry stage EXECUTABLE=NO\.?/i, '').replace(/;\s*$/, '')}</small></>}</td>
            </tr>;
          })}
        </tbody></table></div>
      </Section>

      <Assumptions rows={(() => {
        const identity = activeWorkload?.trace_sha256 ?? workloadRuns[0]?.trace_sha256 ?? null;
        const traceSeed = activeWorkload?.project ? 'not applicable' : activeWorkload?.trace_seed ?? 'not recorded';
        return [
          ['Dataset', <>{datasetView === 'tuned' && tuned ? `Tuned run · ${stamp(tuned.doc.generated_at)}` : `Bundled baseline · ${stamp(doc.generated_at)}`} · {workloads.length} workloads · {topologies.length} arms · {runs.length} cells ({okCount} ok, {failedCount} failed)</>],
          ['Source', <><span className="mono">public/data/workload_ablation.json</span> · generated by <span className="mono">{doc.generated_by}</span></>],
          ['Traffic endpoints', activeWorkload ? `${activeWorkload.active_nodes ?? 'not recorded'} active / ${activeWorkload.nodes} available${activeWorkload.active_nodes !== undefined && activeWorkload.active_nodes < activeWorkload.nodes ? ' · sparse placement, not full-fabric coverage' : ''}` : 'not recorded'],
          ['Trace identity', identity ? <span className="mono" title={identity}>{shortIdentity(identity)}</span> : 'Not recorded — legacy results are not verified paired comparisons'],
          ['Trace / simulator seed', `${traceSeed} / ${workloadRuns[0]?.simulator_seed ?? 'not recorded'}`],
          ['Trace packet sizes', packetSizeLabel(activeWorkload?.packet_size_flits)],
          ['Pinned knobs', `packet_size=${common.packet_size} · vc_buf_size=${common.vc_buf_size} · use_noc_latency=${common.use_noc_latency} · seed=${common.seed ?? '—'}`],
          ['Run overrides', Object.keys(common.overrides ?? {}).length ? Object.entries(common.overrides ?? {}).map(([key, value]) => `${key}=${value}`).join(' · ') : 'none'],
          ['Latency definition', <>Per-packet <span className="mono">total_latency</span> from BookSim <span className="mono">packets_out.csv</span>; percentiles are nearest-rank over delivered packets.</>],
          ['Support', `${productArms} product · ${researchArms} research · ${bookSimArms} BookSim-only (registry EXECUTABLE=NO)`],
          ['Arm definition', 'One fabric configuration. VC count is each family\'s canonical minimum, recorded per arm rather than equalized. QTree, Tree4, Fly and Ring are BookSim-only fixtures; dragonflynew p=2 is a 72-endpoint fabric and is not forced into this 64-endpoint slice.'],
          ['Not compared', 'Resource budgets differ by arm: this is not an equal-area or equal-power comparison.'],
          ['Not ranked', 'Cross-workload latency. Each trace has its own arrival pattern and offered load, so a percentile is comparable across fabrics within one workload only.'],
          ['Not measured', 'Injection-rate saturation, model compute, DRAM timing, power, area and silicon timing. Completing a replay is not qualification.'],
          ['Execution scope', 'Network trace replay only. Gateway reruns replay catalog traces rather than generating random traffic; the runner keeps failed cells typed instead of dropping them.'],
        ];
      })()}>
        <div className="knob-summary">
          <span><strong>{pinnedKnobs.length}</strong><small>pinned where recorded</small></span>
          <span><strong>{variedKnobs.length}</strong><small>varied by cell</small></span>
          <span><strong>{structuralKnobs.length}</strong><small>structural keys</small></span>
          <span><strong>{baselineOverrides.length}</strong><small>baseline overrides</small></span>
        </div>

        {variedKnobs.length > 0 ? <>
          <h3 className="subheading">Varied across cells</h3>
          <div className="table-scroll"><table><thead><tr>
            <th>Knob</th><th>Scope</th><th>Observed values</th><th>Recorded in</th>
          </tr></thead><tbody>
            {variedKnobs.map(knob => <tr key={knob.key}>
              <th className="mono">{knob.key}</th>
              <td>{knob.scope}</td>
              <td className="mono">{knob.values.join(' · ')}</td>
              <td className="numeric">{knob.covered} / {runs.length} cells</td>
            </tr>)}
          </tbody></table></div>
        </> : null}

        <div className="knob-overrides">
          <div><h3 className="subheading">Baseline overrides</h3></div>
          <div className="knob-chips">
            {baselineOverrides.length
              ? baselineOverrides.map(([key, value]) => <code key={key}>{key}={value}</code>)
              : <span className="meta-line">None recorded.</span>}
          </div>
        </div>

        <details className="knob-details">
          <summary>Pinned values ({pinnedKnobs.length})</summary>
          <div className="knob-grid">
            {pinnedKnobs.map(knob => <div className="knob-item" key={knob.key}>
              <code>{knob.key}</code>
              <span className="mono">{knob.values[0] ?? '—'}</span>
              <small>{knob.scope} · {knob.covered}/{runs.length} cells</small>
            </div>)}
          </div>
        </details>

        <details className="knob-details">
          <summary>Structural parameters by arm ({structuralKnobs.length} keys)</summary>
          <div className="table-scroll capped"><table><thead><tr>
            <th>Key</th>{topologies.map(topology => <th key={topology.topology_id} className="mono">{topology.label}</th>)}
          </tr></thead><tbody>
            {structuralKnobs.map(knob => <tr key={knob.key}>
              <th className="mono">{knob.key}</th>
              {topologies.map(topology => <td key={topology.topology_id} className="mono">
                {structuralByArm.get(topology.topology_id)?.[knob.key] ?? '—'}
              </td>)}
            </tr>)}
          </tbody></table></div>
        </details>
      </Assumptions>
    </div>

    <Inspector title="Selected cell">
      {inspected ? <>
        <h3 className="mono">{inspected.workload_label}<br />{inspected.topology_label}</h3>
        <div className="actions">
          {inspected.status === 'ok' ? <Badge tone="green">ok</Badge> : <Badge tone="amber">{inspected.status}</Badge>}
          {best?.topology === inspected.topology && best?.workload === inspected.workload && <Badge tone="blue">best for workload</Badge>}
          {bestGap !== null && <Badge tone={bestGap > 0 ? 'green' : 'neutral'}>{bestGap > 0 ? `${Math.abs(bestGap).toFixed(1)}% better than best` : `${Math.abs(bestGap).toFixed(1)}% behind best`}</Badge>}
        </div>
        <Properties rows={[
          ['P50 latency', `${inspected.latency_p50?.toFixed(1) ?? '—'} cyc`],
          ['P95 latency', `${inspected.latency_p95?.toFixed(1) ?? '—'} cyc`],
          ['P99 latency', `${inspected.latency_p99?.toFixed(1) ?? '—'} cyc`],
          ['Mean latency', `${inspected.latency_mean?.toFixed(1) ?? '—'} cyc`],
          ['Hops', inspected.hops_avg?.toFixed(2) ?? '—'],
          ['Completion', `${inspected.completion_cycles?.toFixed(0) ?? '—'} cyc`],
          ['Delivered', inspected.delivered_packets?.toLocaleString() ?? '—'],
          ['VCs / routing', `${inspected.vcs} / ${inspected.routing}`],
          ['Packet size / VC depth', `${inspected.packet_size} / ${inspected.vc_buf_size} flits`],
          ['Buffer per input', `${inspected.declared_buffer_flits_per_input ?? inspected.vcs * inspected.vc_buf_size} flits`],
          ['Simulator buffer', inspected.resource_cost?.storage_flits === undefined || inspected.resource_cost.storage_flits === null ? 'not reported' : `${inspected.resource_cost.storage_flits} flits`],
          ['Qualification', inspected.qualification ?? 'not established by this replay'],
          ['Config', <span className="mono">{inspectedTopology?.config ?? '—'}</span>],
        ]} />
        {baselineRun && comparisonIssue(baselineRun, inspected) && <Notice tone="amber">{comparisonIssue(baselineRun, inspected)}</Notice>}
        {baselineRun && !comparisonIssue(baselineRun, inspected) && <div className="abl-inspector-delta">
          <h4>vs bundled baseline</h4>
          <Properties rows={[
            ['P95', `${fmt(baselineRun, 'latency_p95')} → ${fmt(inspected, 'latency_p95')} cyc`],
            ['P99', `${fmt(baselineRun, 'latency_p99')} → ${fmt(inspected, 'latency_p99')} cyc`],
            ['Completion', `${baselineRun.completion_cycles?.toFixed(0) ?? '—'} → ${inspected.completion_cycles?.toFixed(0) ?? '—'} cyc`],
          ]} />
        </div>}
        <details>
          <summary>Merged BookSim config ({inspectedKnobs.length} keys)</summary>
          <div className="table-scroll capped"><table><thead><tr>
            <th>Key</th><th>Scope</th><th>Value</th>
          </tr></thead><tbody>
            {inspectedKnobs.map(([key, value]) => <tr key={key}>
              <th className="mono">{key}</th>
              <td>{knobScope(key)}</td>
              <td className="mono">{value}</td>
            </tr>)}
          </tbody></table></div>
        </details>
      </> : <p>Select a matrix cell or ranking row to inspect its measurements and every recorded knob.</p>}
    </Inspector>
  </div>;
}

type TuningProps = {
  baseline: AblationDoc;
  activeWorkloadId: string;
  baselineLabel: string;
  tuned: TunedRun | null;
  objective: ObjectiveKey;
  health: { state: 'checking' | 'online' | 'offline'; detail?: string; stale?: string };
  onCheckGateway: () => void;
  onMeasured: (run: TunedRun) => void;
  onOpenTuned: () => void;
  onOpenBaseline: () => void;
  currentView: 'baseline' | 'tuned';
};

function TuningWorkbench(props: TuningProps): ReactElement {
  const { baseline, activeWorkloadId, tuned, objective, health, onCheckGateway, onMeasured } = props;
  const defaultTopologies = useMemo(() => baseline.topologies.map(topology => topology.topology_id), [baseline]);
  const [scope, setScope] = useState<'current' | 'all'>('current');
  const [selectedTopologies, setSelectedTopologies] = useState<Set<string>>(() => new Set(defaultTopologies));
  const [packetSize, setPacketSize] = useState(String(baseline.common.packet_size));
  const [vcBufSize, setVcBufSize] = useState(String(baseline.common.vc_buf_size));
  const [useNoCLatency, setUseNoCLatency] = useState(String(baseline.common.use_noc_latency));
  const [knobs, setKnobs] = useState<Record<string, string>>(() => pickedKnobValues(baseline));
  const [extra, setExtra] = useState(() => extraText(unknownOverrides(baseline)));
  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const [variant, setVariant] = useState(INITIAL_VARIANT);
  const [extraKey, setExtraKey] = useState('');
  const [extraValue, setExtraValue] = useState('');
  const [extraAddError, setExtraAddError] = useState<string | null>(null);

  const parsedExtra = useMemo(() => parseExtra(extra), [extra]);
  const extraField = EXTRA_KNOBS.find(knob => knob.key === extraKey) ?? null;
  const extraValueError = extraField ? extraKnobError(extraField, extraValue) : null;
  const extraEntries = Object.entries(parsedExtra.values);
  const baselinePicked = useMemo(() => pickedKnobValues(baseline), [baseline]);
  const baselineExtra = useMemo(() => unknownOverrides(baseline), [baseline]);
  const baselineExtraText = useMemo(() => extraText(baselineExtra), [baselineExtra]);
  const selectedTopologyList = baseline.topologies.filter(topology => selectedTopologies.has(topology.topology_id));
  const runCells = (scope === 'all' ? baseline.workloads.length : 1) * selectedTopologyList.length;
  const includesMwa = scope === 'all' ? baseline.workloads.some(workload => workload.workload_id === 'mwa-fx-correlator') : activeWorkloadId === 'mwa-fx-correlator';

  const changeChips = useMemo(() => {
    const chips: string[] = [];
    if (Number(packetSize) !== baseline.common.packet_size) chips.push(`packet_size=${packetSize}`);
    if (Number(vcBufSize) !== baseline.common.vc_buf_size) chips.push(`vc_buf_size=${vcBufSize}`);
    if (Number(useNoCLatency) !== baseline.common.use_noc_latency) chips.push(`use_noc_latency=${useNoCLatency}`);
    for (const field of KNOB_FIELDS) {
      if ((knobs[field.key] ?? KNOB_DEFAULTS[field.key]) !== (baselinePicked[field.key] ?? KNOB_DEFAULTS[field.key])) {
        chips.push(`${field.key}=${knobs[field.key] ?? KNOB_DEFAULTS[field.key]}`);
      }
    }
    for (const [key, value] of Object.entries(parsedExtra.values)) {
      if (baselineExtra[key] !== value) chips.push(`${key}=${value}`);
    }
    return chips;
  }, [packetSize, vcBufSize, useNoCLatency, knobs, baseline, baselinePicked, baselineExtra, parsedExtra.values]);

  const validation = (() => {
    const issues = [...parsedExtra.errors];
    const packet = Number(packetSize), buffer = Number(vcBufSize), latency = Number(useNoCLatency);
    if (!Number.isInteger(packet) || packet < 1 || packet > 1024) issues.push('packet_size must be an integer between 1 and 1024.');
    if (!Number.isInteger(buffer) || buffer < 1 || buffer > 4096) issues.push('vc_buf_size must be an integer between 1 and 4096.');
    if (latency !== 0 && latency !== 1) issues.push('use_noc_latency must be 0 or 1.');
    if (variant.packet !== '' && (!Number.isInteger(Number(variant.packet)) || Number(variant.packet) < 1 || Number(variant.packet) > 1024)) issues.push('Trace packet size must be 1–1024 flits or blank to preserve.');
    if (!Number.isFinite(Number(variant.time)) || Number(variant.time) < 0.01 || Number(variant.time) > 100) issues.push('Time scale must be between 0.01 and 100.');
    for (const key of ['burst', 'stride', 'offset'] as const) {
      if (!Number.isInteger(Number(variant[key])) || Number(variant[key]) < (key === 'stride' ? 1 : 0) || Number(variant[key]) > (key === 'burst' ? 1_000_000_000 : 1_000_000)) issues.push(`Invalid ${key} value.`);
    }
    if (variant.stride !== '1' && baseline.workloads.some(workload => {
      let a = Number(variant.stride), b = workload.nodes;
      if (!Number.isInteger(a) || a < 1) return true;
      while (b) [a, b] = [b, a % b];
      return a !== 1;
    })) issues.push('Rank stride must be coprime to the endpoint count so placement remains bijective.');
    for (const field of KNOB_FIELDS) {
      const raw = knobs[field.key] ?? KNOB_DEFAULTS[field.key];
      if (field.kind === 'select') {
        if (!field.options?.some(option => option.value === raw)) {
          issues.push(`${field.label} has an unsupported value.`);
        }
        continue;
      }
      const value = Number(raw);
      if (!Number.isFinite(value) || (field.min !== undefined && value < field.min) || (field.max !== undefined && value > field.max)) {
        issues.push(`${field.label} must be between ${field.min ?? '—'} and ${field.max ?? '—'}.`);
      } else if ((field.step ?? 1) === 1 && !Number.isInteger(value)) {
        issues.push(`${field.label} must be an integer.`);
      }
    }
    if (!selectedTopologyList.length) issues.push('Select at least one fabric arm.');
    if (!activeWorkloadId) issues.push('Select a workload.');
    return [...new Set(issues)];
  })();

  const reset = () => {
    setPacketSize(String(baseline.common.packet_size));
    setVcBufSize(String(baseline.common.vc_buf_size));
    setUseNoCLatency(String(baseline.common.use_noc_latency));
    setKnobs(pickedKnobValues(baseline));
    setExtra(baselineExtraText);
    setSelectedTopologies(new Set(defaultTopologies));
    setVariant({ ...INITIAL_VARIANT });
    setExtraKey('');
    setExtraValue('');
    setExtraAddError(null);
    setRunError(null);
  };

  const addExtra = () => {
    if (!extraField) { setExtraAddError('Choose a knob first.'); return; }
    const error = extraKnobError(extraField, extraValue);
    if (error) { setExtraAddError(error); return; }
    setExtra(extraText({ ...parsedExtra.values, [extraField.key]: extraValue.trim() }));
    setExtraKey('');
    setExtraValue('');
    setExtraAddError(null);
  };

  const removeExtra = (key: string) => {
    setExtra(extraText(Object.fromEntries(Object.entries(parsedExtra.values).filter(([entry]) => entry !== key))));
    setExtraAddError(null);
  };

  const chooseExtraKnob = (key: string) => {
    const field = EXTRA_KNOBS.find(knob => knob.key === key) ?? null;
    setExtraKey(key);
    setExtraValue(field?.defaultValue ?? '');
    setExtraAddError(null);
  };

  const applyPreset = (preset: Preset) => {
    setPacketSize(String(preset.packetSize ?? baseline.common.packet_size));
    setVcBufSize(String(preset.vcBufSize ?? baseline.common.vc_buf_size));
    setUseNoCLatency(String(preset.useNoCLatency ?? baseline.common.use_noc_latency));
    setKnobs({ ...pickedKnobValues(baseline), ...(preset.knobs ?? {}) });
    setExtra(baselineExtraText);
    setVariant({ ...INITIAL_VARIANT, packet: preset.tracePacketSize === undefined ? '' : String(preset.tracePacketSize) });
    setExtraKey('');
    setExtraValue('');
    setExtraAddError(null);
    setRunError(null);
  };

  const run = async () => {
    if (validation.length) { setRunError(validation[0]); return; }
    setRunError(null);
    setRunning(true);
    try {
      const latest = await gateway.health() as GatewayHealth & { code?: { stale?: boolean } };
      if (latest.code?.stale) throw new Error('Backend code changed. Restart the gateway or desktop app before running a new experiment.');
      const workloads = scope === 'all' ? baseline.workloads.map(workload => workload.workload_id) : [activeWorkloadId];
      const result = await gateway.runAblation({
        workloads,
        topologies: selectedTopologyList.map(topology => topology.topology_id),
        packet_size: Number(packetSize),
        vc_buf_size: Number(vcBufSize),
        use_noc_latency: Number(useNoCLatency),
        jobs: 6,
        seed: baseline.common.seed ?? 1,
        trace_packet_size: variant.packet === '' ? undefined : Number(variant.packet),
        time_scale: Number(variant.time), burst_window: Number(variant.burst),
        rank_stride: Number(variant.stride), rank_offset: Number(variant.offset),
        overrides: { ...knobs, ...parsedExtra.values },
      });
      if (!isAblationDoc(result.document)) throw new Error('The gateway returned a document this page cannot read.');
      onMeasured({
        doc: result.document,
        out: result.out,
        durationSeconds: result.duration_seconds,
        failedCells: result.failed_cells,
        command: result.command,
      });
    } catch (error) {
      setRunError(gatewayReason(error));
    } finally {
      setRunning(false);
    }
  };

  const command = useMemo(() => {
    const overrides = { ...knobs, ...parsedExtra.values };
    return [
      'python3 tracks/t3-topology/scripts/ablate_workloads.py',
      `  --workloads ${scope === 'all' ? 'all' : activeWorkloadId || 'all'}`,
      `  --topologies ${selectedTopologyList.map(topology => topology.topology_id).join(',') || 'all'}`,
      `  --packet-size ${packetSize || baseline.common.packet_size}`,
      `  --vc-buf-size ${vcBufSize || baseline.common.vc_buf_size}`,
      `  --use-noc-latency ${useNoCLatency || baseline.common.use_noc_latency}`,
      `  --seed ${baseline.common.seed ?? 1}`,
      '  --replay-catalog apps/studio/prototype/public/data/workload_ablation.json',
      ...(variant.packet === '' ? [] : [`  --trace-packet-size ${variant.packet}`]),
      `  --time-scale ${variant.time} --burst-window ${variant.burst}`,
      `  --rank-stride ${variant.stride} --rank-offset ${variant.offset}`,
      ...Object.entries(overrides).map(([key, value]) => `  --set ${key}=${value}`),
      `  --out tracks/t3-topology/runs/workload-ablation/$(date +%Y%m%dT%H%M%S)-${scope === 'all' ? 'all' : activeWorkloadId || 'slice'}`,
    ].join(' \\\n');
  }, [scope, activeWorkloadId, selectedTopologyList, packetSize, vcBufSize, useNoCLatency, knobs, parsedExtra.values, baseline, variant]);

  const copy = () => {
    setCopyError('');
    const pending = navigator.clipboard?.writeText(command);
    if (!pending) { setCopyError('Clipboard access is unavailable. Select and copy the command below.'); return; }
    pending
      .then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1600); })
      .catch(() => { setCopied(false); setCopyError('Could not copy the command. Select and copy it manually.'); });
  };

  return <Section title="Tune & rerun"
    actions={<>
      <Button primary onClick={run} disabled={running || health.state !== 'online' || Boolean(health.stale) || validation.length > 0}>
        {running ? 'Running…' : 'Run sweep'}
      </Button>
      <Badge tone={health.state === 'online' ? (health.stale ? 'amber' : 'green') : health.state === 'checking' ? 'neutral' : 'red'}>
        {health.state === 'online' ? (health.stale ? 'Gateway online · stale code' : 'Gateway connected') : health.state === 'checking' ? 'Checking gateway…' : 'Gateway offline'}
      </Badge>
      <Badge tone="amber">measures · does not estimate</Badge>
    </>}>

    <div className="abl-tune">
      <div className="abl-tune-form">
        <div className="abl-tune-scope">
          <label className="field"><span>Scope</span>
            <select value={scope} onChange={event => setScope(event.target.value as 'current' | 'all')}>
              <option value="current">Current workload only</option>
              <option value="all">All {baseline.workloads.length} workloads</option>
            </select>
          </label>
          <div className="abl-cell-count">
            <strong>{runCells}</strong>
            <span>cells to measure</span>
            <small>{baseline.topologies.length - selectedTopologies.size} arms excluded</small>
          </div>
        </div>

        <fieldset className="abl-knob-group">
          <legend>Fabric arms</legend>
          <div className="abl-fabric-chips">
            {baseline.topologies.map((topology, index) => {
              const on = selectedTopologies.has(topology.topology_id);
              return <button type="button" key={topology.topology_id} className={on ? 'abl-fabric-chip on' : 'abl-fabric-chip'} aria-pressed={on}
                onClick={() => setSelectedTopologies(current => {
                  const next = new Set(current);
                  if (next.has(topology.topology_id)) next.delete(topology.topology_id); else next.add(topology.topology_id);
                  return next;
                })}>
                <i style={{ background: COLORS[index % COLORS.length] }} />
                <span>{topology.label}</span>
                <small>{topology.family}</small>
              </button>;
            })}
          </div>
          <div className="abl-inline-actions">
            <button type="button" className="text-button" onClick={() => setSelectedTopologies(new Set(defaultTopologies))}>All arms</button>
            <button type="button" className="text-button" onClick={() => setSelectedTopologies(new Set())}>Clear arms</button>
          </div>
        </fieldset>

        <fieldset className="abl-knob-group">
          <legend>Pinned axes</legend>
          <div className="abl-knob-grid abl-knob-grid-3">
            <Field label="Packet size" hint="config default only; explicit trace sizes take precedence">
              <input type="number" min={1} max={1024} step={1} value={packetSize} onChange={event => setPacketSize(event.target.value)} />
            </Field>
            <Field label="VC buffer" hint="flits · 1–4096">
              <input type="number" min={1} max={4096} step={1} value={vcBufSize} onChange={event => setVcBufSize(event.target.value)} />
            </Field>
            <Field label="NoC latency pricing" hint="use_noc_latency">
              <select value={useNoCLatency} onChange={event => setUseNoCLatency(event.target.value)}>
                <option value="0">0 · off</option>
                <option value="1">1 · on</option>
              </select>
            </Field>
          </div>
        </fieldset>

        <fieldset className="abl-knob-group">
          <legend>Workload variants · explicit trace changes</legend>
          <div className="abl-knob-grid">
            {([
              ['packet', 'Trace packet size', 'Blank preserves each event; otherwise 1–1024 flits'],
              ['time', 'Arrival time scale', '0.01–100; smaller values increase offered load'],
              ['burst', 'Burst window', 'Cycles; 0 preserves spacing'],
              ['stride', 'Rank placement stride', 'Must be coprime to endpoint count'],
              ['offset', 'Rank placement offset', 'Modulo endpoint count'],
            ] as const).map(([key, label, hint]) => <Field key={key} label={label} hint={hint}>
              <input type="number" aria-label={label} step={key === 'time' ? '0.01' : '1'} value={variant[key]} disabled={running}
                onChange={event => setVariant(current => ({ ...current, [key]: event.target.value }))} />
            </Field>)}
          </div>
          {Object.entries(variant).some(([key, value]) => value !== INITIAL_VARIANT[key as keyof typeof INITIAL_VARIANT]) && <Notice tone="amber">Workload controls changed. Only matching executed trace identities can produce a hardware-only paired delta; workload variants remain inspectable separately.</Notice>}
        </fieldset>

        <fieldset className="abl-knob-group">
          <legend>Router pipeline</legend>
          <div className="abl-knob-grid">
            {KNOB_FIELDS.map(field => <Field key={field.key} label={field.label} hint={field.hint}>
              {field.kind === 'select'
                ? <select value={knobs[field.key] ?? KNOB_DEFAULTS[field.key]} onChange={event => setKnobs(current => ({ ...current, [field.key]: event.target.value }))}>
                  {field.options?.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                : <input type="number" min={field.min} max={field.max} step={field.step ?? 1}
                  value={knobs[field.key] ?? KNOB_DEFAULTS[field.key]}
                  onChange={event => setKnobs(current => ({ ...current, [field.key]: event.target.value }))} />}
            </Field>)}
          </div>
        </fieldset>

        <details className="abl-extra">
          <summary>Other BookSim knobs ({extraEntries.length})</summary>
          <div className="abl-extra-add">
            <Field label="Other knob">
              <select value={extraKey} onChange={event => chooseExtraKnob(event.target.value)} aria-label="Other knob">
                <option value="">Choose a knob…</option>
                {EXTRA_KNOBS.map(knob => <option key={knob.key} value={knob.key}>{knob.label} · {knob.key}</option>)}
              </select>
            </Field>
            <Field label="Other knob value">
              {extraField?.kind === 'select'
                ? <select value={extraValue} onChange={event => setExtraValue(event.target.value)} aria-label="Other knob value">
                  {extraField.options?.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                : extraField
                  ? <input type="number" min={extraField.min} max={extraField.max} step={extraField.step ?? 1}
                    value={extraValue} onChange={event => setExtraValue(event.target.value)} aria-label="Other knob value" />
                  : <input value="" disabled placeholder="Choose a knob first" aria-label="Other knob value" />}
            </Field>
            <Button onClick={addExtra} disabled={!extraField || !extraValue.trim()}>Add override</Button>
          </div>
          {extraField && <p className="abl-extra-scope"><span className="mono">{extraField.key}</span> · {extraField.scope}{extraField.hint ? ` · ${extraField.hint}` : ''}</p>}
          {extraValueError && extraValue && <Notice tone="red">{extraValueError}</Notice>}
          {extraAddError && <Notice tone="red">{extraAddError}</Notice>}
          {extraEntries.length > 0 && <div className="abl-extra-list" aria-label="Other BookSim overrides">
            {extraEntries.map(([key, value]) => {
              const known = EXTRA_KNOBS.find(knob => knob.key === key);
              return <span className="abl-extra-chip" key={key}>
                <span>{known?.label ?? key} ·</span>
                <code>{key}={value}</code>
                <button type="button" aria-label={`Remove ${key} override`} onClick={() => removeExtra(key)}>×</button>
              </span>;
            })}
          </div>}
          <details className="abl-extra-raw">
            <summary>Advanced: paste raw key=value pairs</summary>
            <Field label="Raw overrides">
              <input value={extra} onChange={event => setExtra(event.target.value)} placeholder="arb_type=round_robin" />
            </Field>
            {parsedExtra.errors.length > 0 && <Notice tone="red">{parsedExtra.errors.map(error => <div key={error}>{error}</div>)}</Notice>}
          </details>
        </details>

        <div className="abl-presets">
          <span className="abl-presets-label">Starting points</span>
          <div className="abl-preset-row">
            {PRESETS.map(preset => <button type="button" key={preset.id} className="abl-preset" onClick={() => applyPreset(preset)} title={preset.hint}>
              <strong>{preset.label}</strong><small>{preset.hint}</small>
            </button>)}
            <button type="button" className="abl-preset" onClick={reset} title="Restore every value recorded in the bundled slice">
              <strong>Reset all</strong><small>Bundled pinned values and arm selection</small>
            </button>
          </div>
        </div>

        <div className="abl-change-strip">
          <span>{changeChips.length ? `${changeChips.length} change${changeChips.length === 1 ? '' : 's'} from ${props.baselineLabel}` : `Matches ${props.baselineLabel}`}</span>
          <div className="abl-change-chips">{changeChips.slice(0, 12).map(change => <code key={change}>{change}</code>)}</div>
        </div>

        {validation.length > 0 && <div className="abl-form-issues">{validation.map(issue => <span key={issue}>{issue}</span>)}</div>}
        {runError && <Notice tone="red"><strong>The run did not complete.</strong> {runError}</Notice>}
        {health.state === 'offline' && <Notice tone="amber"><strong>No gateway connection.</strong> {health.detail} Start it with <code>{GATEWAY_START}</code>, then <button type="button" className="text-button" onClick={onCheckGateway}>check again</button>.</Notice>}
        {health.state === 'online' && health.stale && <Notice tone="amber"><strong>The gateway reports stale code.</strong> {health.stale} Results are still labelled as measured by that process. Restart it with <code>{GATEWAY_START}</code>, then <button type="button" className="text-button" onClick={onCheckGateway}>re-check</button> before trusting a new runner change.</Notice>}
        {includesMwa && <Notice tone="amber"><strong>MWA is the slow trace.</strong> It contributes 1,014,384 events; one cell took about a minute in this repository. A full {selectedTopologyList.length}-arm sweep can take several minutes.</Notice>}
        {scope === 'all' && runCells > 24 && <Notice tone="amber"><strong>Large sweep.</strong> This request would run {runCells} cells. The gateway caps one request at 600 s, so a full 11-workload × {selectedTopologyList.length}-arm slice may exceed that cap. Prefer per-workload runs, or use the CLI command below.</Notice>}

        <div className="abl-runbar">
          <Button primary onClick={run} disabled={running || health.state !== 'online' || Boolean(health.stale) || validation.length > 0}>
            {running ? 'Running BookSim…' : `Run ${runCells} measured cell${runCells === 1 ? '' : 's'}`}
          </Button>
          {health.state !== 'online' && <Button onClick={onCheckGateway}>{health.state === 'checking' ? 'Checking…' : 'Check gateway'}</Button>}
        </div>
        {running && <div className="abl-running" role="status" aria-live="polite"><span className="pulse-dot" aria-hidden="true" />Running the trace sweep through BookSim. Keep this tab open; the gateway returns the measured document when it finishes.</div>}
      </div>

      <aside className="abl-tune-side">
        {tuned ? <TuningComparison baseline={baseline} tuned={tuned} objective={objective} activeWorkloadId={activeWorkloadId}
          currentView={props.currentView} onOpenTuned={props.onOpenTuned} onOpenBaseline={props.onOpenBaseline} /> : <TuningExplainer baseline={baseline} />}
      </aside>
    </div>

    <details className="runner-command">
      <summary>Runner command</summary>
      <pre className="code-preview">{command}</pre>
      <div className="actions"><Button onClick={copy}>{copied ? 'Copied' : 'Copy command'}</Button><span role="status">{copied ? 'Command copied to clipboard.' : ''}</span></div>
      <p className="meta-line">This writes a new measured run directory. It does not replace the bundled baseline; add
        <span className="mono"> --copy-to-prototype</span> only when you intentionally want the page&apos;s bundled slice to become this run.</p>
      {copyError && <div role="alert"><Notice tone="amber">{copyError}</Notice></div>}
    </details>
  </Section>;
}

function TuningExplainer({ baseline }: { baseline: AblationDoc }): ReactElement {
  return <div className="abl-explainer">
    <h3>Before you run</h3>
    <ul>
      <li>Each selected workload is replayed against every selected arm. A cell is measured or a typed failure, never interpolated.</li>
      <li>Rankings compare fabrics within one workload only.</li>
    </ul>
    <Properties rows={[
      ['Bundled axes', `packet_size ${baseline.common.packet_size} · vc_buf_size ${baseline.common.vc_buf_size} · use_noc_latency ${baseline.common.use_noc_latency} · seed ${baseline.common.seed ?? '—'}`],
      ['Runner', baseline.generated_by],
      ['Bundled cells', `${baseline.runs.length} across ${baseline.workloads.length} workloads and ${baseline.topologies.length} arms`],
      ['Run ceiling', '600 s per gateway request'],
    ]} />
  </div>;
}

function TuningComparison({ baseline, tuned, objective, activeWorkloadId, currentView, onOpenTuned, onOpenBaseline }: {
  baseline: AblationDoc;
  tuned: TunedRun;
  objective: ObjectiveKey;
  activeWorkloadId: string;
  currentView: 'baseline' | 'tuned';
  onOpenTuned: () => void;
  onOpenBaseline: () => void;
}): ReactElement {
  const comparison = useMemo(() => compareRuns(baseline, tuned.doc, objective), [baseline, tuned, objective]);
  const activeCovered = comparison.perWorkload.some(row => row.workload.workload_id === activeWorkloadId);
  const active = comparison.perWorkload.find(row => row.workload.workload_id === activeWorkloadId) ?? comparison.perWorkload[0] ?? null;
  const objectiveInfo = OBJECTIVES[objective];
  const changedRows = comparison.cells
    .filter(cell => cell.workload === active?.workload.workload_id)
    .sort((a, b) => (b.pct ?? 0) - (a.pct ?? 0));
  const failed = tuned.doc.runs.filter(run => run.status !== 'ok');

  if (!comparison.cells.length) return <div className="abl-explainer">
    <h3>Tuned run measured</h3>
    <Notice tone="amber">{comparison.blocked[0] ?? 'No baseline cell overlaps this run.'} No verified paired delta can be shown. The measurements remain available in the dataset switch above.</Notice>
    <div className="actions"><Button onClick={onOpenTuned}>Open tuned results</Button><Button onClick={onOpenBaseline}>Bundled baseline</Button></div>
  </div>;

  const deltaLabel = (pct: number | null) => {
    if (pct === null) return '—';
    const sign = pct > 0 ? (objectiveInfo.higher ? '+' : '−') : (objectiveInfo.higher ? '−' : '+');
    return `${sign}${Math.abs(pct).toFixed(1)}%`;
  };

  return <div className="abl-explainer abl-compare">
    <div className="abl-compare-head">
      <div>
        <h3>Before / after</h3>
      </div>
      <div className="actions">
        <div className="segmented">
          <button type="button" className={currentView === 'baseline' ? 'active' : ''} onClick={onOpenBaseline}>Baseline</button>
          <button type="button" className={currentView === 'tuned' ? 'active' : ''} onClick={onOpenTuned}>Tuned</button>
        </div>
        <Button onClick={() => downloadJson('workload-ablation-tuned.json', tuned.doc)}>Download tuned JSON</Button>
      </div>
    </div>
    <div className="abl-compare-stats">
      <span><strong>{comparison.cells.length}</strong><small>{comparison.cells.length === 1 ? 'comparable cell' : 'comparable cells'}</small></span>
      <span className="good"><strong>{comparison.improved}</strong><small>improved</small></span>
      <span className="bad"><strong>{comparison.regressed}</strong><small>regressed</small></span>
      <span><strong>{comparison.winnerChanges}</strong><small>best-arm change{comparison.winnerChanges === 1 ? '' : 's'}</small></span>
    </div>
    {comparison.blocked.length > 0 && <Notice tone="amber">{comparison.blocked.length} cells excluded from paired deltas because provenance is missing or changed. {comparison.blocked[0]}</Notice>}

    {!activeCovered && active && <Notice tone="amber"><strong>This run does not include the selected workload.</strong>{' '}
      It measured {comparison.perWorkload.length} workload{comparison.perWorkload.length === 1 ? '' : 's'}; showing{' '}
      <strong>{active.workload.label}</strong>. Open the tuned dataset or select a measured workload to compare.</Notice>}

    {active && <div className="abl-compare-winner">
      <div className="abl-compare-subject">
        <span>Workload</span>
        <strong>{active.workload.label}</strong>
      </div>
      <div className="abl-compare-pair">
        <div>
          <span>Best before</span>
          <strong>{active.baselineBest?.topology_label ?? '—'}</strong>
          <b className="numeric">{active.baselineValue === null ? '—' : `${fmtNumber(active.baselineValue, objective)} ${objectiveInfo.unit}`}</b>
        </div>
        <span className="abl-compare-arrow" aria-hidden="true">→</span>
        <div>
          <span>Best after</span>
          <strong>{active.tunedBest?.topology_label ?? '—'}</strong>
          <b className="numeric">{active.tunedValue === null ? '—' : `${fmtNumber(active.tunedValue, objective)} ${objectiveInfo.unit}`}</b>
        </div>
      </div>
      <div className="abl-compare-flags">
        <Badge tone={active.better === true ? 'green' : active.better === false ? 'red' : 'neutral'}>
          {active.pct === null ? 'no delta' : `${deltaLabel(active.pct)} ${active.better === true ? 'better' : active.better === false ? 'worse' : 'same'}`}
        </Badge>
        {active.winnerChanged && <Badge tone="amber">best arm changed</Badge>}
      </div>
    </div>}

    {changedRows.length > 0 && <div className="table-scroll abl-compare-table"><table><thead><tr>
      <th>Fabric</th><th>{objectiveInfo.short} before</th><th>{objectiveInfo.short} after</th><th>Δ</th><th>Result</th>
    </tr></thead><tbody>
      {changedRows.map(cell => <tr key={`${cell.workload}::${cell.topology}`}>
        <th className="mono">{cell.topologyLabel}</th>
        <td className="numeric">{fmtNumber(cell.baseline, objective)}</td>
        <td className="numeric">{fmtNumber(cell.tuned, objective)}</td>
        <td className="numeric abl-delta-cell">
          <span className="abl-delta-track"><i style={{
            width: `${Math.min(100, Math.abs(cell.pct ?? 0) * 4)}%`,
            background: cell.better === true ? '#246847' : cell.better === false ? '#a32928' : '#93a3b2',
          }} /></span>
          <span>{deltaLabel(cell.pct)}</span>
        </td>
        <td>{cell.better === true ? <Badge tone="green">better</Badge> : cell.better === false ? <Badge tone="red">worse</Badge> : <Badge>same</Badge>}</td>
      </tr>)}
    </tbody></table></div>}

    {comparison.cells.length > changedRows.length && <details className="abl-compare-all">
      <summary>All comparable cells ({comparison.cells.length})</summary>
      <div className="table-scroll"><table><thead><tr>
        <th>Workload</th><th>Fabric</th><th>Before</th><th>After</th><th>Δ</th>
      </tr></thead><tbody>
        {[...comparison.cells].sort((a, b) => a.workloadLabel.localeCompare(b.workloadLabel) || a.topologyLabel.localeCompare(b.topologyLabel)).map(cell => <tr key={`${cell.workload}::${cell.topology}`}>
          <th>{cell.workloadLabel}</th>
          <td className="mono">{cell.topologyLabel}</td>
          <td className="numeric">{fmtNumber(cell.baseline, objective)}</td>
          <td className="numeric">{fmtNumber(cell.tuned, objective)}</td>
          <td className="numeric">{deltaLabel(cell.pct)}</td>
        </tr>)}
      </tbody></table></div>
    </details>}

    {failed.length > 0 && <Notice tone="amber"><strong>{failed.length} typed failure{failed.length === 1 ? '' : 's'}.</strong>{' '}
      {failed.slice(0, 4).map(run => `${run.workload}/${run.topology}: ${run.status}`).join(' · ')}{failed.length > 4 ? ' …' : ''}
    </Notice>}
  </div>;
}
