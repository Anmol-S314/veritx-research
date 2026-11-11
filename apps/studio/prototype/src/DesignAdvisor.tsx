import { useEffect, useMemo, useRef, useState } from 'react';
import { parseSweepRows, type SweepRow } from './analysisCurves';
import { num } from './format';
import type { LoadedProject } from './project';
import { Assumptions, Badge, Button, Field, Notice, PageLink, Properties, Section, downloadJson } from './ui';
import { InteractiveScatter } from './InteractiveScatter';
import {
  advise, CONSTRAINT_UNITS, depthVariants, emptyConstraints, matchWorkload, parseAdvisorEvidence, parseSensitivity,
  PRIORITY_HELP, PRIORITY_LABELS,
  type AdvisorCandidate, type AdvisorConstraints, type AdvisorEvidence,
  type ConstraintKey, type Priority, type SensitivityEvidence,
} from './designAdvisor';

const WORKLOAD_URL = '/data/workload_ablation.json';
const SWEEP_URL = '/data/topology_sweep.json';
const SENSITIVITY_URL = '/data/design_sensitivity.json';

type AxisKey = 'latencyP95' | 'throughput' | 'powerW' | 'areaMm2' | 'storageFlits';
type ViewMode = 'executable' | 'product' | 'all';
const AXES: Record<AxisKey, { label: string; short: string; unit: string; direction: 'MIN' | 'MAX' }> = {
  latencyP95: { label: 'Measured P95 packet latency', short: 'P95 latency', unit: 'cycles', direction: 'MIN' },
  throughput: { label: 'Measured delivered throughput', short: 'Throughput', unit: 'packets/cycle', direction: 'MAX' },
  powerW: { label: 'Modeled total power', short: 'Modeled power', unit: 'W', direction: 'MIN' },
  areaMm2: { label: 'Modeled total area', short: 'Modeled area', unit: 'mm²', direction: 'MIN' },
  storageFlits: { label: 'Declared buffer storage', short: 'Buffer storage', unit: 'flits', direction: 'MIN' },
};

const STUDY_FAMILY: Record<string, string> = {
  MESH: 'mesh',
  CONCENTRATED_MESH: 'concentrated_mesh',
  TORUS: 'torus',
  FAT_TREE: 'fat_tree',
  FLATFLY: 'flatfly',
  SROTA: 'srota',
  GEC_MECS: 'gec_mecs',
  GEC_HYBRID: 'gec_hybrid',
};

const PRIORITIES: Priority[] = ['latency', 'throughput', 'power', 'area', 'balanced'];

const CONSTRAINT_FIELDS: { key: ConstraintKey; label: string; placeholder: string; unit: string }[] = [
  { key: 'maxLatencyP95', label: 'Maximum P95 packet latency', placeholder: 'e.g. 600', unit: 'cycles' },
  { key: 'minThroughput', label: 'Minimum delivered throughput', placeholder: 'e.g. 0.90', unit: 'packets/cycle' },
  { key: 'maxPowerW', label: 'Maximum modeled power', placeholder: 'e.g. 70', unit: 'W' },
  { key: 'maxAreaMm2', label: 'Maximum modeled area', placeholder: 'e.g. 1.5', unit: 'mm²' },
  { key: 'maxStorageFlits', label: 'Maximum buffer storage', placeholder: 'e.g. 10,240', unit: 'flits' },
];

type EvidenceState = {
  phase: 'loading' | 'ready' | 'error';
  evidence?: AdvisorEvidence;
  sweep?: SweepRow[];
  sensitivity?: SensitivityEvidence;
  reason?: string;
};

type AdvisorPreset = {
  families: string[];
  linkWidths: number[];
  priority: Priority;
  winner: string;
  depth: number;
  note: string;
};

export function DesignAdvisor({ project = null, mode, executableFamilies = [], onPrepareStudy, ownAssumptions = true }: {
  project?: LoadedProject | null;
  mode: 'live' | 'fixture';
  executableFamilies?: string[];
  onPrepareStudy?: (preset: AdvisorPreset) => void;
  ownAssumptions?: boolean;
}) {
  const [state, setState] = useState<EvidenceState>({ phase: 'loading' });
  const [workloadId, setWorkloadId] = useState('');
  const [priority, setPriority] = useState<Priority>('latency');
  const [bounds, setBounds] = useState<Record<ConstraintKey, string>>({
    maxLatencyP95: '', minThroughput: '', maxPowerW: '', maxAreaMm2: '', maxStorageFlits: '',
  });
  const [viewMode, setViewMode] = useState<ViewMode>(mode === 'live' && executableFamilies.length > 0 ? 'executable' : 'product');
  const viewTouched = useRef(false);
  const [constraintsOpen, setConstraintsOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [xAxis, setXAxis] = useState<AxisKey>('latencyP95');
  const [yAxis, setYAxis] = useState<AxisKey>('throughput');

  useEffect(() => {
    let live = true;
    setState({ phase: 'loading' });
    Promise.all([
      fetch(WORKLOAD_URL, { cache: 'no-store' }).then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`))),
      fetch(SWEEP_URL, { cache: 'no-store' }).then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`))),
      fetch(SENSITIVITY_URL, { cache: 'no-store' }).then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`))),
    ]).then(([workloads, sweep, sensitivity]) => {
      if (!live) return;
      setState({
        phase: 'ready',
        evidence: parseAdvisorEvidence(workloads),
        sweep: parseSweepRows(sweep),
        sensitivity: parseSensitivity(sensitivity),
      });
    }).catch(error => {
      if (live) setState({ phase: 'error', reason: error instanceof Error ? error.message : 'Evidence could not be read.' });
    });
    return () => { live = false; };
  }, []);

  const projectKey = project?.detail.project.project_id ?? 'fixture';
  // The declared model name wins. A draft keeps the catalog workload id it was
  // seeded from; using that id after the user renames the model silently maps
  // the recommendation to the old trace. Only fall back to the id when the
  // request carries no model name at all.
  const hints = useMemo(() => [
    project?.request?.workload?.model_name,
    project?.request?.workload?.model_name ? null : project?.detail?.draft?.workload_id,
    project?.detail?.project?.name,
  ], [project]);
  const hintKey = hints.map(value => value ?? '').join('|');

  useEffect(() => { setWorkloadId(''); setSelectedId(null); }, [projectKey]);
  useEffect(() => {
    if (state.phase !== 'ready' || !state.evidence || workloadId) return;
    setWorkloadId(matchWorkload(state.evidence.workloads, hints));
  }, [state, workloadId, hintKey]);

  const includeResearch = viewMode === 'all';
  const onlyExecutable = viewMode === 'executable';
  const parsed = useMemo(() => {
    const numberOrNull = (key: ConstraintKey): number | null => {
      const raw = bounds[key].trim();
      if (!raw) return null;
      const value = Number(raw);
      return Number.isFinite(value) && value >= 0 ? value : null;
    };
    const errors = CONSTRAINT_FIELDS.filter(field => {
      const raw = bounds[field.key].trim();
      if (!raw) return false;
      const value = Number(raw);
      return !Number.isFinite(value) || value < 0;
    });
    const constraints: AdvisorConstraints = {
      ...emptyConstraints(),
      maxLatencyP95: numberOrNull('maxLatencyP95'),
      minThroughput: numberOrNull('minThroughput'),
      maxPowerW: numberOrNull('maxPowerW'),
      maxAreaMm2: numberOrNull('maxAreaMm2'),
      maxStorageFlits: numberOrNull('maxStorageFlits'),
      includeResearch,
    };
    return { constraints, errors };
  }, [bounds, includeResearch]);

  const executableKey = executableFamilies.join(',');
  const workload = state.evidence?.workloads.find(item => item.id === workloadId);
  const arms = useMemo(() => state.evidence?.arms.filter(arm => arm.workload === workloadId) ?? [],
    [state.evidence, workloadId]);
  const executableSet = useMemo(() => new Set(executableFamilies.map(family => family.toLowerCase())), [executableKey]);
  const executableArms = useMemo(() => arms.filter(arm => {
    const value = STUDY_FAMILY[arm.family] ?? arm.family.toLowerCase();
    return executableSet.has(value);
  }), [arms, executableSet]);
  const productArms = useMemo(() => arms.filter(arm => arm.support === 'product'), [arms]);
  useEffect(() => {
    if (mode === 'live' && executableFamilies.length && !viewTouched.current && viewMode === 'product') {
      setViewMode('executable');
    }
  }, [mode, executableKey, executableFamilies.length, viewMode]);
  const allResult = useMemo(() => state.phase === 'ready' && state.sweep && arms.length
    ? advise(arms, state.sweep, state.sensitivity ?? null, parsed.constraints, priority)
    : null, [state, arms, parsed.constraints, priority]);
  const executableResult = useMemo(() => state.phase === 'ready' && state.sweep && executableArms.length
    ? advise(executableArms, state.sweep, state.sensitivity ?? null, parsed.constraints, priority)
    : null, [state, executableArms, parsed.constraints, priority]);
  const executableFilterActive = mode === 'live' && onlyExecutable && executableArms.length > 0;
  const result = executableFilterActive ? executableResult : allResult;

  useEffect(() => { setSelectedId(null); }, [workloadId, priority, onlyExecutable]);
  const selected = result?.candidates.find(candidate => candidate.id === selectedId)
    ?? result?.winner ?? result?.ranked[0] ?? result?.candidates[0] ?? null;

  const activeConstraintCount = CONSTRAINT_FIELDS.filter(field => bounds[field.key].trim()).length;
  const rawWidth = project?.request?.noc_controls?.link_width
    ?? project?.request?.noc_config?.link_width
    ?? project?.request?.physical?.data_width
    ?? 128;
  const declaredWidth = typeof rawWidth === 'number' && Number.isFinite(rawWidth) && rawWidth > 0 ? rawWidth : 128;
  const declaredModel = project?.request?.workload?.model_name ?? '';
  const catalogWorkloadId = project?.detail?.draft?.workload_id ?? '';
  const projectWorkload = declaredModel || catalogWorkloadId || project?.detail?.project?.name || '';
  const exactWorkloadMatch = Boolean(workload && [declaredModel, catalogWorkloadId].some(value => {
    if (!value) return false;
    const declared = value.toLowerCase();
    const label = workload.label.toLowerCase();
    return workload.id === value || label === declared || (workload.project ?? '').toLowerCase() === declared
      || declared.includes(label) || label.includes(declared);
  }));

  const winnersFamilies = [...new Set([
    result?.winner?.arm.family,
    result?.runnerUp?.arm.family,
  ].filter((family): family is string => Boolean(family)))];
  const recommendedStudyFamilies = winnersFamilies
    .map(family => STUDY_FAMILY[family] ?? family.toLowerCase())
    .filter((family, index, list) => list.indexOf(family) === index);
  const executable = recommendedStudyFamilies.filter(family =>
    executableFamilies.some(value => value.toLowerCase() === family.toLowerCase()));
  const studyFamilies = executable.length ? executable : [];
  const linkWidths = [declaredWidth, declaredWidth >= 256 ? declaredWidth / 2 : declaredWidth * 2]
    .filter((value, index, list) => Number.isInteger(value) && value > 0 && list.indexOf(value) === index)
    .slice(0, 2);

  const prepareStudy = () => {
    if (!result?.winner || !onPrepareStudy || !studyFamilies.length) return;
    onPrepareStudy({
      families: studyFamilies,
      linkWidths,
      priority,
      winner: result.winner.arm.topologyLabel,
      depth: result.winner.depth,
      note: 'Advisor shortlist only. Review the revision, domain and evidence limits before launching.',
    });
  };

  const download = () => {
    if (!result) return;
    downloadJson(`fabric-recommendation-${workloadId || 'workload'}.json`, {
      schema: 'srota/fabric-recommendation/1',
      generated_at: new Date().toISOString(),
      mode,
      workload: workload ?? null,
      priority,
      constraints: parsed.constraints,
      reference_load: result.referenceLoad,
      workload_demand_per_node: result.medianLoad,
      recommendation: result.winner ? briefCandidate(result.winner) : null,
      runner_up: result.runnerUp ? briefCandidate(result.runnerUp) : null,
      sensitivity: result.sensitivity,
      candidates: result.candidates.map(briefCandidate),
      modeled_costs: [...result.models.values()].map(model => ({
        family: model.family,
        reference_topology: model.referenceTopology,
        reference_endpoints: model.referenceEndpoints,
        reference_load: model.referenceLoad,
        power_w: model.powerW,
        area_mm2: model.areaMm2,
        power_per_endpoint_w: model.powerPerEndpointW,
        area_per_endpoint_mm2: model.areaPerEndpointMm2,
        model_id: model.modelId,
        technology: model.technology,
        limitations: model.limitations,
      })),
      evidence: {
        workload_source: WORKLOAD_URL,
        sweep_source: SWEEP_URL,
        buffer_sensitivity_source: SENSITIVITY_URL,
        buffer_scope: state.sensitivity?.scope ?? null,
      },
      limits: [
        'Latency and throughput are measured network trace replay, not end-to-end workload time or transaction P95.',
        'Power and area are derived from the BookSim native 32nm model at a 16-endpoint reference and scaled linearly by endpoint count. They are screening estimates, not silicon measurements.',
        'Link/flit width is a declared input. The measured sweep does not vary it, so no width optimum is claimed.',
        'The recommendation is the leading configuration inside this measured/modeled set, not a global optimum or a qualification.',
        'Advisor bounds are screening filters on repository evidence. They are not silently translated into project study constraints, whose metric scope is different.',
      ],
    });
  };

  if (state.phase === 'loading') {
    return <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading measured workload, topology and buffer evidence…</p>;
  }
  if (state.phase === 'error' || !state.evidence || !result) {
    return <Notice tone="red">Fabric evidence could not be read: {state.reason ?? 'No comparable arms.'} No recommendation is substituted.</Notice>;
  }

  const winner = result.winner;
  const runnerUp = result.runnerUp;
  const overallWinner = executableFilterActive ? allResult?.winner ?? null : null;
  const nearMiss = [...result.candidates]
    .filter(candidate => !candidate.feasible)
    .sort((a, b) => b.verdicts.filter(verdict => verdict.pass).length - a.verdicts.filter(verdict => verdict.pass).length
      || a.latencyP95 - b.latencyP95)[0] ?? null;
  const plotCandidates = result.candidates.filter(candidate => candidate.feasible
    && candidate[xAxis] !== null && candidate[yAxis] !== null);
  const plotPoints = plotCandidates.map(candidate => ({
    id: candidate.id,
    label: `${candidate.arm.topologyLabel} · ${candidate.depth}f`,
    x: candidate[xAxis] as number,
    y: candidate[yAxis] as number,
    front: result.paretoIds.has(candidate.id),
  }));
  const tableCandidates = [...result.candidates].sort((a, b) => {
    if (a.feasible !== b.feasible) return a.feasible ? -1 : 1;
    if (a.rank !== null && b.rank !== null) return a.rank - b.rank;
    if (a.rank !== null) return -1;
    if (b.rank !== null) return 1;
    return a.latencyP95 - b.latencyP95;
  });
  const model = selected ? result.models.get(selected.arm.family) : undefined;
  const variants = selected ? depthVariants(selected.arm, state.sensitivity ?? null) : [];
  const referenceVariant = variants.find(variant => variant.depth === 8) ?? variants[0];
  const sw = state.sensitivity;
  const winnerVerdicts = winner?.verdicts ?? [];
  const chartLabel = `${AXES[xAxis].short} versus ${AXES[yAxis].short}`;

  return <div className="advisor">
    <Section title="Recommendation inputs" actions={<>
      <Badge tone="blue">{mode === 'live' ? 'Live project context' : 'Repository evidence'}</Badge>
      <Badge>{state.evidence.workloads.length} measured workloads</Badge>
      <Badge>{state.sweep?.length ?? 0} sweep rows</Badge>
    </>}>
      <div className="advisor-controls">
        <Field label="Measured workload" hint="Repository trace evidence; the project workload may map to a different measured trace.">
          <select value={workloadId} onChange={event => { setWorkloadId(event.target.value); setSelectedId(null); }}>
            {state.evidence.workloads.map(item => <option key={item.id} value={item.id}>{item.label}{item.project ? ' · project trace' : ' · example trace'}</option>)}
          </select>
        </Field>
        <Field label="Recommendation priority" hint={PRIORITY_HELP[priority]}>
          <select value={priority} onChange={event => { setPriority(event.target.value as Priority); setSelectedId(null); }}>
            {PRIORITIES.map(item => <option key={item} value={item}>{PRIORITY_LABELS[item]}</option>)}
          </select>
        </Field>
        <Field label="Reference load for modeled costs" hint="Nearest common sweep load to measured demand; chooses the native-model row only.">
          <span className="advisor-readonly mono">{result.referenceLoad.toFixed(3)} packets/node/cycle</span>
        </Field>
      </div>
      <div className="advisor-scope-row">
        <span className="advisor-scope-count">Showing <strong>{result.candidates.length}</strong> of <strong>{arms.length}</strong> measured topologies{viewMode === 'executable' ? ' · backend-executable only' : viewMode === 'product' ? ' · product arms' : ' · including research'}</span>
        {viewMode === 'executable' && <Button onClick={() => { viewTouched.current = true; setViewMode('product'); setSelectedId(null); }}>Compare all product arms</Button>}
        {viewMode !== 'all' && <Button onClick={() => { viewTouched.current = true; setViewMode('all'); setSelectedId(null); }}>All measured</Button>}
      </div>
      <details className="advisor-constraints" open={constraintsOpen}
        onToggle={event => setConstraintsOpen(event.currentTarget.open)}>
        <summary>Hard constraints <span>{activeConstraintCount ? `${activeConstraintCount} active` : 'none — add bounds'}</span></summary>
        <div className="form-grid advisor-constraint-grid">
          {CONSTRAINT_FIELDS.map(field => {
            const invalid = parsed.errors.some(error => error.key === field.key);
            return <Field key={field.key} label={`${field.label} (${field.unit})`} hint={`${field.placeholder} · blank means no bound`}>
              <input type="number" min="0" step="any" inputMode="decimal"
                aria-label={`${field.label} in ${field.unit}`} aria-invalid={invalid}
                value={bounds[field.key]}
                onChange={event => { setBounds(current => ({ ...current, [field.key]: event.target.value })); setSelectedId(null); }}
                placeholder={field.placeholder} />
            </Field>;
          })}
        </div>
        {parsed.errors.length > 0 && <Notice tone="amber">Invalid bounds are ignored until corrected: {parsed.errors.map(error => error.label).join(', ')}.</Notice>}
      </details>
    </Section>

    <Section title="Recommendation" actions={winner ? <>
      <Badge tone="green">Leading measured arm</Badge>
      <Badge tone={result.paretoIds.has(winner.id) ? 'blue' : 'neutral'}>{result.paretoIds.has(winner.id) ? 'On the selected front' : 'Ranked leader'}</Badge>
      {executableFilterActive && <Badge tone="blue">Executable filter active</Badge>}
    </> : <Badge tone="amber">No feasible candidate</Badge>}>
      {executableFilterActive && overallWinner && overallWinner.id !== winner?.id && <Notice tone="blue">
        The unfiltered leader is <strong>{overallWinner.arm.topologyLabel}</strong> at {num(overallWinner.latencyP95, '', 1)} cycles P95; that family is not reported executable. The recommendation below is the best measured executable arm.
      </Notice>}
      {winner ? <div className="advisor-hero">
        <div className="advisor-pick">
          <h3>{winner.arm.topologyLabel}</h3>
          <p className="advisor-subtitle">{winner.arm.family} · {winner.arm.vcs ?? '—'} VCs · {winner.depth} flits/VC · 128-bit measured reference · {winner.arm.routing} routing</p>
          <div className="advisor-metric-grid">
            <div><span>P95 latency</span><strong>{num(winner.latencyP95, '', 1)}</strong><small>cycles · measured</small></div>
            <div><span>Delivered throughput</span><strong>{num(winner.throughput, '', 4)}</strong><small>packets/cycle · measured</small></div>
            <div><span>Modeled power</span><strong>{winner.powerW === null ? 'Not modeled' : num(winner.powerW, '', 2)}</strong><small>{winner.powerW === null ? 'no native family reference' : 'W · derived screening'}</small></div>
            <div><span>Modeled area</span><strong>{winner.areaMm2 === null ? 'Not modeled' : num(winner.areaMm2, '', 3)}</strong><small>{winner.areaMm2 === null ? 'no native family reference' : 'mm² · derived screening'}</small></div>
          </div>
          <div className="advisor-verdicts">
            {winnerVerdicts.length ? winnerVerdicts.map(verdict => <span key={verdict.key} className={`advisor-verdict ${verdict.pass ? 'pass' : 'fail'}`}>
              {verdict.label} {verdict.op} {num(verdict.limit, '', 4)} · {verdict.pass ? 'pass' : 'fail'}
              <small>{verdict.authority === 'UNAVAILABLE' ? 'value unavailable' : verdict.authority === 'MODELED' ? 'derived' : 'measured'}</small>
            </span>) : <span className="advisor-verdict pass">No hard constraint active · ranked by {PRIORITY_LABELS[priority].toLowerCase()}</span>}
          </div>
          <p className="advisor-depth-reason"><strong>Buffer depth:</strong> {winner.depthReason}</p>
          <div className="toolbar toolbar-start advisor-actions">
            <Button primary disabled={!onPrepareStudy || !studyFamilies.length} title={!studyFamilies.length ? 'None of the recommended families is reported executable by the backend.' : 'Prefill the bounded project study with this shortlist.'} onClick={prepareStudy}>Carry shortlist into measured study</Button>
            <Button onClick={download}>Download recommendation JSON</Button>
            {onPrepareStudy && !studyFamilies.length && <span className="meta-line">No recommended family is reported executable by the backend.</span>}
          </div>
        </div>
        <aside className="advisor-why" aria-label="Recommendation basis">
          <h3>Why this one</h3>
          <p>{PRIORITY_HELP[priority]} Among {result.ranked.length} eligible measured configuration{result.ranked.length === 1 ? '' : 's'}, <strong>{winner.arm.topologyLabel}</strong> leads on {PRIORITY_LABELS[priority].toLowerCase()}.</p>
          {runnerUp ? <p><strong>Runner-up:</strong> {runnerUp.arm.topologyLabel} · {num(runnerUp.latencyP95, '', 1)} cycles P95, {num(runnerUp.throughput, '', 4)} packets/cycle, {runnerUp.powerW === null ? 'power not modeled' : `${num(runnerUp.powerW, '', 2)} W modeled`}. Difference to winner: {deltaText(winner, runnerUp, priority)}.</p> : <p>No second measured configuration is eligible.</p>}
          <h3>What would change the answer</h3>
          {result.sensitivity.length ? <ul className="advisor-flips">
            {result.sensitivity.map(note => <li key={`${note.key}-${note.threshold}`}>
              If <strong>{note.label.toLowerCase()}</strong> were {note.op === '≤' ? 'capped at' : 'required at or above'} <span className="mono">{num(note.threshold, '', 4)} {CONSTRAINT_UNITS[note.key]}</span>, <strong>{note.winnerLabel}</strong> would lead. <small>{note.basis}</small>
            </li>)}
          </ul> : <p>No tested constraint threshold inside this candidate set changes the leading measurement.</p>}
        </aside>
      </div> : <div className="advisor-empty">
        <h3>No candidate satisfies every hard constraint.</h3>
        <p>{nearMiss ? <>Closest measured arm: <strong>{nearMiss.arm.topologyLabel}</strong> with {nearMiss.verdicts.filter(verdict => verdict.pass).length}/{nearMiss.verdicts.length} constraints passing. {failingText(nearMiss)}</> : 'No measured arm is available for this workload.'}</p>
      </div>}
      {mode === 'live' && !exactWorkloadMatch && <Notice tone="amber">
        <strong>{project?.detail.project.name}</strong> · {project?.detail.active_revision_id ?? 'no active revision'}. Declared workload “{projectWorkload || 'not named'}” is not a measured trace; the closest is <strong>{workload?.label ?? 'not selected'}</strong>.
      </Notice>}
    </Section>

    <Section title="Candidate field" actions={<>
      <Badge>{result.candidates.length} configurations</Badge>
      <Badge tone="blue">{result.paretoIds.size} non-dominated</Badge>
      {result.excluded.length > 0 && <Badge tone="amber">{result.excluded.length} excluded</Badge>}
    </>}>
      <div className="advisor-view">
        <div className="advisor-coverage" aria-label="Topology coverage">
          <div><span>Measured</span><strong>{arms.length}</strong><small>trace-replay arms</small></div>
          <div><span>Product</span><strong>{productArms.length}</strong><small>product-supported</small></div>
          <div><span>Backend-executable</span><strong>{executableArms.length}</strong><small>certified path</small></div>
          <div><span>In current view</span><strong>{result.candidates.length}</strong><small>{viewMode === 'all' ? 'incl. research' : viewMode === 'executable' ? 'runnable shortlist' : 'evidence-only allowed'}</small></div>
        </div>
        <Field label="Topology view" hint="Backend-executable is the only view that can be carried into the project study.">
          <select value={viewMode} onChange={event => { viewTouched.current = true; setViewMode(event.target.value as ViewMode); setSelectedId(null); }}>
            {mode === 'live' && executableFamilies.length > 0 && <option value="executable">Backend-executable ({executableArms.length})</option>}
            <option value="product">All product arms ({productArms.length})</option>
            <option value="all">All measured topologies ({arms.length})</option>
          </select>
        </Field>
      </div>
      {onlyExecutable && executableFamilies.length > 0 && executableArms.length === 0 && <Notice tone="amber">None of this revision’s executable families appears in the measured slice. The comparison falls back to all product arms; carry the shortlist only after confirming backend support.</Notice>}
      <div className="advisor-chart-controls">
        <Field label="Horizontal axis"><select value={xAxis} onChange={event => setXAxis(event.target.value as AxisKey)}>{Object.entries(AXES).map(([key, axis]) => <option key={key} value={key}>{axis.label} · {axis.direction === 'MIN' ? 'lower is better' : 'higher is better'}</option>)}</select></Field>
        <Field label="Vertical axis"><select value={yAxis} onChange={event => setYAxis(event.target.value as AxisKey)}>{Object.entries(AXES).map(([key, axis]) => <option key={key} value={key}>{axis.label} · {axis.direction === 'MIN' ? 'lower is better' : 'higher is better'}</option>)}</select></Field>
      </div>
      {plotPoints.length >= 2 ? <div className="advisor-plot">
        <InteractiveScatter points={plotPoints} selected={selected?.id ?? null} onSelect={setSelectedId}
          xLabel={`${AXES[xAxis].short} (${AXES[xAxis].unit}) · ${AXES[xAxis].direction === 'MIN' ? 'lower is better' : 'higher is better'}`}
          yLabel={`${AXES[yAxis].short} (${AXES[yAxis].unit}) · ${AXES[yAxis].direction === 'MIN' ? 'lower is better' : 'higher is better'}`}
          label={`${chartLabel} for measured workload ${workload?.label ?? workloadId}`} />
        <p className="meta-line">Front membership uses the priority objectives, not only the two displayed axes.</p>
      </div> : <Notice tone="amber">The selected axes do not carry at least two numeric observations. Choose a measured axis such as P95 latency or throughput.</Notice>}
      <details className="advisor-table-details">
        <summary>Candidate data · {result.candidates.length} configurations</summary>
      <div className="table-scroll advisor-table-scroll"><table aria-label="Fabric recommendation candidates"><thead><tr>
        <th>Result</th><th>Topology / configuration</th><th>Depth</th><th>P95 latency</th><th>Throughput</th><th>Modeled power</th><th>Modeled area</th><th>Buffer storage</th><th>Constraints</th>
      </tr></thead><tbody>
        {tableCandidates.map(candidate => <tr key={candidate.id} className={candidate.id === selected?.id ? 'selected' : undefined}>
          <td>{candidate.rank === 1 ? <Badge tone="green">Recommended</Badge> : candidate.rank === 2 ? <Badge tone="blue">Runner-up</Badge> : candidate.feasible && candidate.rank === null ? <Badge tone="amber">Not ranked · no model</Badge> : candidate.feasible ? <Badge>Eligible</Badge> : <Badge tone="red">Excluded</Badge>}
            {candidate.arm.support !== 'product' && <small className="block"><Badge tone="amber">{candidate.arm.support}</Badge></small>}
          </td>
          <th><button className="text-button" onClick={() => setSelectedId(candidate.id)}>{candidate.arm.topologyLabel}</button><small className="block">{candidate.arm.family} · {candidate.arm.vcs ?? '—'} VCs · {candidate.arm.routing}</small></th>
          <td className="numeric">{candidate.depth} flits/VC<small className="block">{candidate.depth === 8 ? 'reference' : 'measured variant'}</small></td>
          <td className="numeric">{num(candidate.latencyP95, '', 1)}<small className="block">cycles · measured</small></td>
          <td className="numeric">{num(candidate.throughput, '', 4)}<small className="block">packets/cycle · measured</small></td>
          <td className="numeric">{candidate.powerW === null ? 'Not modeled' : num(candidate.powerW, '', 2)}<small className="block">{candidate.powerW === null ? 'no family reference' : 'W · derived'}</small></td>
          <td className="numeric">{candidate.areaMm2 === null ? 'Not modeled' : num(candidate.areaMm2, '', 3)}<small className="block">{candidate.areaMm2 === null ? 'no family reference' : 'mm² · derived'}</small></td>
          <td className="numeric">{candidate.storageFlits === null ? '—' : `${candidate.storageFlits.toLocaleString()}`}<small className="block">flits declared</small></td>
          <td>{candidate.feasible ? <span className="advisor-pass">Pass{candidate.rank === null ? ' · not ranked (no modeled cost)' : ''}</span> : <span className="advisor-fail">{failingText(candidate)}</span>}</td>
        </tr>)}
      </tbody></table></div>
      </details>
      <details className="advisor-coverage-table">
        <summary>All measured topologies · {arms.length}</summary>
        <div className="table-scroll"><table aria-label="Measured topology coverage"><thead><tr><th>Topology</th><th>Family / VCs</th><th>Support</th><th>Backend</th><th>P95</th><th>Throughput</th><th>Depth slice</th><th>In view</th></tr></thead><tbody>
          {arms.map(arm => {
            const backend = executableSet.has(STUDY_FAMILY[arm.family] ?? arm.family.toLowerCase());
            const inView = result.candidates.some(candidate => candidate.arm.topology === arm.topology);
            const variants = depthVariants(arm, state.sensitivity ?? null);
            return <tr key={arm.topology} className={inView ? undefined : 'muted'}>
              <th>{arm.topologyLabel}<small className="block mono">{arm.topology}</small></th>
              <td>{arm.family}<small className="block">{arm.vcs ?? '—'} VCs</small></td>
              <td><Badge tone={arm.support === 'product' ? 'blue' : 'amber'}>{arm.support}</Badge></td>
              <td>{backend ? <Badge tone="green">executable</Badge> : <Badge tone="neutral">evidence-only</Badge>}</td>
              <td className="numeric">{num(arm.latencyP95, '', 1)}</td>
              <td className="numeric">{num(arm.throughput, '', 4)}</td>
              <td>{variants.length > 1 ? `${variants.length} depths` : 'reference'}</td>
              <td>{inView ? 'yes' : 'no'}</td>
            </tr>;
          })}
        </tbody></table></div>
      </details>
    </Section>

    <details className="advisor-disclosure">
      <summary><span>Buffer depth, width & evidence</span><span>{selected ? `${selected.arm.topologyLabel} · ${selected.depth} flits/VC · 128-bit reference` : 'No selection'}</span></summary>
    <Section title="Buffer and width guidance" actions={<Badge tone="blue">{selected?.arm.topologyLabel ?? 'No selection'} · depth {selected?.depth ?? '—'}</Badge>}>
      {selected && variants.length > 1 ? <>
        <div className="table-scroll advisor-depth-table"><table aria-label="Measured buffer-depth variants"><thead><tr><th>Depth / VC</th><th>P95 latency</th><th>Throughput</th><th>Buffer storage</th><th>Delta vs depth 8</th><th>Evidence</th></tr></thead><tbody>
          {variants.map(variant => {
            const baseline = referenceVariant ?? variant;
            const latencyDelta = baseline.latencyP95 > 0 ? (variant.latencyP95 - baseline.latencyP95) / baseline.latencyP95 * 100 : 0;
            const throughputDelta = baseline.throughput > 0 ? (variant.throughput - baseline.throughput) / baseline.throughput * 100 : 0;
            return <tr key={variant.depth} className={variant.depth === selected.depth ? 'selected' : undefined}>
              <th>{variant.depth} flits/VC{variant.depth === 8 && <small className="block">reference</small>}</th>
              <td className="numeric">{num(variant.latencyP95, '', 1)}</td>
              <td className="numeric">{num(variant.throughput, '', 4)}</td>
              <td className="numeric">{variant.storageFlits === null ? '—' : variant.storageFlits.toLocaleString()}</td>
              <td className="numeric">{variant.depth === 8 ? 'baseline' : latencyDelta === 0 && throughputDelta === 0 ? 'no measured change' : `${latencyDelta > 0 ? '+' : ''}${latencyDelta.toFixed(1)}% P95 · ${throughputDelta > 0 ? '+' : ''}${throughputDelta.toFixed(1)}% throughput`}</td>
              <td>{variant.measured ? <Badge tone="green">measured slice</Badge> : <Badge tone="amber">reference</Badge>}</td>
            </tr>;
          })}
        </tbody></table></div>
      </> : <Notice tone="amber">No measured buffer-depth slice is available for this topology and workload. The recommendation keeps the depth-8 reference.</Notice>}
      <div className="advisor-width">
        <Properties rows={[
          ['Selected depth', selected ? `${selected.depth} flits/VC · ${selected.depth === 8 ? 'reference arm' : 'measured variant'}` : '—'],
          ['Virtual channels', selected ? `${selected.arm.vcs ?? 'not reported'} per port · canonical for the arm, not equalized` : '—'],
          ['Mean / P99 packet latency', selected ? `${num(selected.latencyMean, '', 1)} / ${num(selected.latencyP99, '', 1)} cycles` : '—'],
          ['Network completion', selected?.arm.completionCycles === null || selected?.arm.completionCycles === undefined ? 'Not reported' : `${selected.arm.completionCycles.toLocaleString()} cycles`],
          ['Hops per packet', selected?.arm.hopsAvg === null || selected?.arm.hopsAvg === undefined ? 'Not reported' : num(selected.arm.hopsAvg, '', 2)],
          ['Routers / crosspoints', selected ? `${selected.arm.routers ?? '—'} / ${selected.arm.crosspoints ?? '—'}` : '—'],
          ['Measured link / flit width', '128-bit reference in the trace-replay slice'],
          ['Project declared width', `${declaredWidth}-bit`],
          ['Width evidence', 'Not varied by this measured sweep; no width optimum is claimed'],
          ['Widths to test in a project study', linkWidths.join(' / ')],
          ['Buffer storage', selected?.storageFlits === null || selected?.storageFlits === undefined ? 'Not reported' : `${selected.storageFlits.toLocaleString()} flits declared`],
          ['Routing', selected?.arm.routing ?? 'not reported'],
          ['Support stage', selected?.arm.support ?? 'not reported'],
        ]} />
        {mode === 'live' && <div className="toolbar toolbar-start"><PageLink page="design/fabric-topology">Open fabric topology to apply the depth</PageLink></div>}
      </div>
    </Section>

    <div className="toolbar toolbar-start"><PageLink page="explore/ablations">Inspect the full workload × fabric matrix</PageLink><PageLink page="explore/fabric-ablations">Open fabric ablations</PageLink><Button onClick={download}>Download full recommendation</Button><Button onClick={() => { viewTouched.current = false; setViewMode(mode === 'live' && executableFamilies.length ? 'executable' : 'product'); setBounds({ maxLatencyP95: '', minThroughput: '', maxPowerW: '', maxAreaMm2: '', maxStorageFlits: '' }); setPriority('latency'); setSelectedId(null); }}>Reset targets</Button></div>

    {ownAssumptions && <Assumptions rows={[
      ['Scope', mode === 'live'
        ? 'Repository trace replay plus modeled family costs. The recommendation does not measure this project revision; only the bounded project study does that.'
        : 'Illustrative evidence review. No project draft is loaded; this compares measured repository traces and modeled family costs and mutates nothing.'],
      ['Workload evidence', `${workload?.label ?? workloadId} · ${workload?.nodes ?? '—'} endpoints · ${workload?.events?.toLocaleString() ?? 'events not reported'} events · ${workload?.project ? `project trace ${workload.project}` : 'BookSim example trace'}`],
      ['Trace identity', workload?.traceSha256 ? <span className="mono" title={workload.traceSha256}>{workload.traceSha256.slice(0, 30)}…</span> : 'Not recorded'],
      ['Evidence files', <span className="mono">workload_ablation.json · topology_sweep.json · design_sensitivity.json</span>],
      ['Measured rows', `${state.evidence.arms.length} successful cells across ${state.evidence.workloads.length} workloads; ${state.evidence.skipped} failed or incomplete cells excluded`],
      ['Buffer slice', sw ? `${sw.points.length} successful depth points; ${sw.skipped} incomplete points excluded` : 'Not loaded'],
      ['Selection rule', 'Depth 4/8/16 is measured for product arms in the buffer slice; research arms use the depth-8 reference. A candidate is recommended only when it is measured, modeled where required, and inside every declared bound.'],
      ['Evidence-only', 'A topology measured here but not reported executable by the backend for this optimization path. Not zero-valued and not a rejected measurement.'],
      ['Front membership', 'Uses the priority objectives, not only the two displayed axes; a missing modeled value is absent from that axis rather than plotted at zero. The flip list re-ranks declared candidates only and predicts nothing between tested values.'],
      ['Link width', 'A declared input. The measured trace replay holds 128-bit flits; the advisor recommends topology and measured buffer depth, not a width value.'],
      ['Modeled cost', `${result.referenceLoad.toFixed(3)} packets/node/cycle · ${[...new Set(result.candidates.map(candidate => candidate.arm.family).filter(family => result.models.has(family)))].join(', ') || 'no family model'} · BookSim native 32nm prediction, per-endpoint scaled from a 16-endpoint reference, not a re-run at 64 endpoints`],
      ['Model identity', selected && model ? <span className="mono">{model.modelId ?? 'not reported'}</span> : 'Not reported for this arm'],
      ['Study handoff', 'The study receives the topology and link-width shortlist only. Repository latency, power and area bounds are not converted into backend constraints because their metric scopes differ.'],
      ['Not claimed', 'Project-revision performance, transaction P95, end-to-end workload time, DRAM timing, compute/communication overlap, a link/flit-width optimum, or any silicon power, floorplan, timing or qualification claim.'],
    ]}>
      {selected && model && <details className="advisor-provenance">
        <summary>Modeled-power formula inputs</summary>
        <pre className="code-preview">{JSON.stringify({
          family: model.family,
          reference_topology: model.referenceTopology,
          reference_endpoints: model.referenceEndpoints,
          reference_load: model.referenceLoad,
          reference_power_w: model.powerW,
          reference_area_mm2: model.areaMm2,
          power_formula: selected.powerFormula,
          area_formula: selected.areaFormula,
          technology: model.technology,
          limitations: model.limitations,
        }, null, 2)}</pre>
      </details>}
    </Assumptions>}
    </details>
  </div>;
}

function briefCandidate(candidate: AdvisorCandidate) {
  return {
    id: candidate.id,
    topology: candidate.arm.topology,
    topology_label: candidate.arm.topologyLabel,
    family: candidate.arm.family,
    support: candidate.arm.support,
    vcs: candidate.arm.vcs,
    depth: candidate.depth,
    routing: candidate.arm.routing,
    latency_p95_cycles: candidate.latencyP95,
    throughput_packets_per_cycle: candidate.throughput,
    modeled_power_w: candidate.powerW,
    modeled_area_mm2: candidate.areaMm2,
    buffer_storage_flits: candidate.storageFlits,
    feasible: candidate.feasible,
    rank: candidate.rank,
    pareto: candidate.pareto,
    constraints: candidate.verdicts,
    depth_reason: candidate.depthReason,
  };
}

function deltaText(winner: AdvisorCandidate, runnerUp: AdvisorCandidate, priority: Priority): string {
  if (priority === 'throughput') {
    const delta = runnerUp.throughput - winner.throughput;
    return `${delta >= 0 ? '+' : ''}${delta.toFixed(4)} packets/cycle`;
  }
  if (priority === 'power' && winner.powerW !== null && runnerUp.powerW !== null) {
    return `${(runnerUp.powerW - winner.powerW).toFixed(2)} W modeled`;
  }
  if (priority === 'area' && winner.areaMm2 !== null && runnerUp.areaMm2 !== null) {
    return `${(runnerUp.areaMm2 - winner.areaMm2).toFixed(3)} mm² modeled`;
  }
  const delta = runnerUp.latencyP95 - winner.latencyP95;
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} cycles P95`;
}

function failingText(candidate: AdvisorCandidate): string {
  const failed = candidate.verdicts.filter(verdict => !verdict.pass);
  if (!failed.length) return 'Pass';
  return failed.map(verdict => `${verdict.label} ${verdict.op} ${num(verdict.limit, '', 4)}${verdict.value === null ? ' (unavailable)' : ` (has ${num(verdict.value, '', 4)})`}`).join('; ');
}
