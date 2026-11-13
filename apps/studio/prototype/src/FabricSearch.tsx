import { useEffect, useMemo, useState } from 'react';
import { gateway, gatewayReason, type AblationCatalog, type AblationRequest } from './gateway';
import type { PageId } from './model';
import './fabricSearch.css';
import { Assumptions, Badge, Button, Field, Icon, Notice, Section, downloadJson } from './ui';
import { InteractiveScatter } from './InteractiveScatter';
import { draftDepthFor, draftTopologyFor, handoffReason } from './fabricHandoff';
import { useProject, type LoadedProject } from './project';
import { expandSearchGrid, finiteValue, recommendSearch, searchObservation, searchTradeoff, type SearchMetric, type SearchRow } from './workloadSearchPolicy';

type Knob = { name: string; type: string; category?: string; overridable?: boolean; pinned?: string | number; default?: string | number; note?: string; owner?: string };
const metricNames: Record<SearchMetric, string> = { latency: 'P95 latency', throughput: 'throughput', energy: 'replay energy', power: 'modeled power', area: 'modeled area', routers: 'router count', crosspoints: 'crosspoints', storage: 'buffer storage' };
const limitsMetrics: SearchMetric[] = ['latency', 'energy', 'power', 'area', 'throughput', 'routers', 'crosspoints', 'storage'];
const number = (value: number | null | undefined) => finiteValue(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'Unavailable';
const energy = (value: number | null) => value === null ? 'Unavailable' : value >= 1e9 ? `${number(value / 1e9)} mJ` : value >= 1e6 ? `${number(value / 1e6)} µJ` : `${number(value)} pJ`;
const metricValue = (row: SearchRow, metric: SearchMetric): string => metric === 'latency' ? `${number(row.latency)} cyc`
  : metric === 'throughput' ? `${number(row.throughput)} packets/cycle`
    : metric === 'energy' ? energy(row.energy)
      : metric === 'power' ? `${number(row.power)} W`
        : metric === 'area' ? `${number(row.area)} mm²`
          : number(row[metric]);
const profileMetrics = (id: string, metrics: SearchMetric[]): SearchMetric[] => {
  const extras: SearchMetric[] = id === 'efficient' ? ['energy', 'power'] : id === 'compact' ? ['area', 'power'] : ['energy', 'area'];
  return [...new Set([...metrics, ...extras])].slice(0, 4);
};
const barWidth = (value: number | null, values: (number | null)[], higher: boolean): number => {
  if (value === null) return 0;
  const finite = values.filter((item): item is number => item !== null && Number.isFinite(item));
  if (finite.length < 2) return 100;
  const low = Math.min(...finite), high = Math.max(...finite);
  if (high === low) return 100;
  const share = higher ? (value - low) / (high - low) : (high - value) / (high - low);
  return Math.max(6, Math.min(100, share * 100));
};
function useCatalog() {
  const [state, setState] = useState<{ catalog?: AblationCatalog; knobs: Knob[]; error: string; loading: boolean }>({ knobs: [], error: '', loading: true });
  useEffect(() => {
    let live = true;
    Promise.all([gateway.ablationCatalog(), gateway.knobInventory()]).then(([catalog, inventory]) => {
      const backend = inventory.backend as { knobs?: Knob[] } | null | undefined;
      if (!catalog.workloads?.length || !catalog.topologies?.length) throw new Error('The ablation catalog has no workloads or topologies.');
      if (live) setState({ catalog, knobs: (backend?.knobs ?? []).filter(k => k.overridable && !catalog.override_exclusions.includes(k.name)), error: '', loading: false });
    }).catch(error => { if (live) setState({ knobs: [], error: gatewayReason(error), loading: false }); });
    return () => { live = false; };
  }, []);
  return state;
}

type CatalogTrace = AblationCatalog['workloads'][number];

const normalized = (value?: string | null) => (value ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/**
 * An exact identifier match only. The catalog does not publish a mapping from
 * a registry workload to a reference trace, so this deliberately refuses to
 * guess: a missing match is shown to the operator instead of silently picking
 * an unrelated trace and calling it "closest".
 */
function exactProjectTrace(workloads: CatalogTrace[], loaded: LoadedProject | null): CatalogTrace | null {
  if (!loaded) return null;
  const draftId = normalized(loaded.detail.draft?.workload_id);
  const projectName = normalized(loaded.detail.project.name);
  const model = normalized(loaded.request?.workload?.model_name);
  return workloads.find(row =>
    (draftId && normalized(row.workload_id) === draftId)
    || (projectName && normalized(row.project) === projectName)
    || (model && normalized(row.workload_id) === model)
  ) ?? null;
}

export function FabricSearch({ navigate, notify, embedded = false, onApplied }: {
  navigate: (page: PageId) => void;
  notify: (message: string) => void;
  /** The guided flow owns the page shell; embedding drops the extra scroll/pad wrapper. */
  embedded?: boolean;
  /** Continue the guided flow after the selected fabric is written to the draft. */
  onApplied?: () => void;
}) {
  const { catalog, knobs, error: catalogError, loading } = useCatalog();
  const { project, reload } = useProject();
  const loaded = project.phase === 'loaded' ? project.data : null;
  const [workload, setWorkload] = useState(''), [workloadTouched, setWorkloadTouched] = useState(false), [buffers, setBuffers] = useState<number[]>([]);
  const [dimensions, setDimensions] = useState<Record<string, (string | number)[]>>({});
  const [selectedKnob, setSelectedKnob] = useState(''), [budget, setBudget] = useState(256), [seed, setSeed] = useState(1);
  const [limitValues, setLimitValues] = useState<Record<SearchMetric, string>>({ latency: '', energy: '', power: '', area: '', throughput: '', routers: '', crosspoints: '', storage: '' });
  const [rows, setRows] = useState<SearchRow[]>([]), [records, setRecords] = useState<{ request: AblationRequest; result?: any; error?: string }[]>([]);
  const [phase, setPhase] = useState<'idle' | 'running' | 'complete' | 'failed'>('idle'), [progress, setProgress] = useState(''), [failure, setFailure] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [applying, setApplying] = useState(false);
  const [applyState, setApplyState] = useState<{ tone: 'blue' | 'red' | 'amber'; text: string } | null>(null);
  const matchedTrace = useMemo(() => exactProjectTrace(catalog?.workloads ?? [], loaded), [catalog, loaded?.detail.project.project_id]);
  useEffect(() => {
    if (!catalog) return;
    // An empty dimension must not disable the primary action. The catalog only
    // carries depths when design_sensitivity.json is readable; when it is not,
    // a packaged build showed no chips and "Find fabrics" stayed disabled with
    // no way forward. Seed from the declared default instead, which is what the
    // runner would use anyway.
    const declared = (catalog.knob_dimensions?.vc_buf_size?.values ?? [])
      .filter((value): value is number => Number.isInteger(value) && value > 0 && value <= 64);
    const fallback = Number.isInteger(catalog.defaults.vc_buf_size)
      ? Number(catalog.defaults.vc_buf_size) : 8;
    setBuffers(declared.length ? [...new Set(declared)].sort((a, b) => a - b) : [fallback]);
    setSeed(catalog.defaults.seed ?? 1);
  }, [catalog]);
  useEffect(() => {
    if (!catalog || workloadTouched) return;
    // With a project, only an exact identifier match is preselected. Without
    // one, the first catalog trace is an explicit sample-mode default. A
    // project with no registered trace gets an empty selection and a notice.
    setWorkload(matchedTrace?.workload_id ?? (loaded ? '' : catalog.workloads[0]?.workload_id ?? ''));
  }, [catalog, matchedTrace, loaded, workloadTouched]);
  const topologyIds = catalog?.topologies.map(t => t.topology_id) ?? [];
  const axes = useMemo(() => ({ ...dimensions, vc_buf_size: buffers }), [dimensions, buffers]);
  let grid: ReturnType<typeof expandSearchGrid> | null = null, planError = '';
  try { if (catalog) grid = expandSearchGrid(axes, new Set(['vc_buf_size', ...knobs.map(k => k.name)]), budget, topologyIds.length); } catch (e) { planError = e instanceof Error ? e.message : String(e); }
  const limits: Partial<Record<SearchMetric, number | null>> = {};
  for (const metric of limitsMetrics) { const raw = limitValues[metric].trim(); const value = raw === '' ? null : Number(raw); if (value !== null && !finiteValue(value)) planError ||= `${metricNames[metric]} limit must be finite and non-negative.`; limits[metric] = value; }
  if (!Number.isInteger(seed) || seed < 0 || seed > 2147483647) planError ||= 'Seed must be a non-negative 32-bit integer.';
  const recommendations = recommendSearch(phase === 'complete' ? rows : [], limits);
  const winners = recommendations.flatMap(result => result.winner ? [result.winner] : []);
  const selectedRow = rows.find(row => row.id === selectedId) ?? winners[0] ?? rows[0] ?? null;
  const chartRows = rows.filter(row => row.latency !== null && row.throughput !== null);
  const chartFront = new Set(chartRows.filter(row => !chartRows.some(other => other !== row
    && other.latency! <= row.latency! && other.throughput! >= row.throughput!
    && (other.latency! < row.latency! || other.throughput! > row.throughput!))).map(row => row.id));
  const chartPoints = chartRows.map(row => ({ id: row.id, label: `${topologyLabel(row.topology)} · ${row.request.vc_buf_size ?? '?'}f`, x: row.throughput!, y: row.latency!, front: chartFront.has(row.id) }));
  const workloadInfo = catalog?.workloads.find(item => item.workload_id === workload);
  const projectRequest = (loaded?.request ?? null) as Record<string, any> | null;
  const projectWorkload = projectRequest?.workload ?? null;
  const projectModel = projectWorkload?.model_name || loaded?.detail?.draft?.workload_id || '';
  const projectEndpoints = (projectRequest?.agents ?? []).reduce((total: number, agent: any) => total + (Number(agent.count) || 0), 0);
  const projectParallelism = projectWorkload
    ? `TP${projectWorkload.tp ?? 1} · DP${projectWorkload.dp ?? 1} · EP${projectWorkload.ep ?? 1} · PP${projectWorkload.pp ?? 1}`
    : 'no workload declared';
  const limitCount = Object.values(limitValues).filter(value => value.trim() !== '').length;
  const availableBuffers = catalog?.knob_dimensions?.vc_buf_size?.values ?? [catalog?.defaults.vc_buf_size ?? 8];
  const recommendedAs = selectedRow ? recommendations.filter(result => result.winner?.id === selectedRow.id).map(result => result.label) : [];
  const selectedStatus = selectedRow ? constraintFailuresText(selectedRow, limits) : '';
  const selectedTopology = selectedRow ? catalog?.topologies.find(item => item.topology_id === selectedRow.topology) : null;
  const selectedDraftTopology = selectedRow && selectedTopology
    ? draftTopologyFor({ topology: selectedRow.topology, family: selectedTopology.family, nodes: selectedTopology.nodes, vcBufSize: selectedRow.request?.vc_buf_size })
    : null;
  const selectedDepth = selectedRow
    ? draftDepthFor({ topology: selectedRow.topology, family: selectedTopology?.family, nodes: selectedTopology?.nodes, vcBufSize: selectedRow.request?.vc_buf_size })
    : null;
  const applyReason = !loaded
    ? 'Start from a workload template before applying a fabric.'
    : loaded.draftMeta?.dirty
      ? 'Save or discard the draft edits before applying a fabric.'
      : selectedRow && selectedRow.status !== 'ok'
        ? 'This observation did not complete successfully.'
        : selectedRow && selectedTopology
          ? handoffReason({ topology: selectedRow.topology, family: selectedTopology.family, nodes: selectedTopology.nodes, vcBufSize: selectedRow.request?.vc_buf_size })
          : 'Select a measured fabric.';
  const canApply = !applying && !!selectedDraftTopology && selectedDepth !== null && !applyReason;

  function topologyLabel(id: string) { return catalog?.topologies.find(t => t.topology_id === id)?.label ?? id; }
  function addKnob() {
    const knob = knobs.find(item => item.name === selectedKnob); if (!knob) return;
    setDimensions(value => ({ ...value, [knob.name]: [knob.pinned ?? knob.default ?? ''] })); setSelectedKnob(''); clear();
  }
  function clear() { setRows([]); setRecords([]); setPhase('idle'); setProgress(''); setFailure(''); setSelectedId(''); }
  function updateLimit(metric: SearchMetric, value: string) { setLimitValues(current => ({ ...current, [metric]: value })); }
  async function run() {
    if (!catalog || !grid || planError || !workload || phase === 'running') return;
    clear(); setPhase('running');
    const nextRows: SearchRow[] = [], nextRecords: { request: AblationRequest; result?: any; error?: string }[] = [];
    const combinations = grid.grid;
    try {
      for (const [index, combination] of combinations.entries()) {
        const { vc_buf_size = catalog.defaults.vc_buf_size ?? 8, ...overridesRaw } = combination;
        const overrides = Object.fromEntries(Object.entries(overridesRaw).map(([key, value]) => [key, String(value)]));
        const request: AblationRequest = { workloads: [workload], topologies: topologyIds, packet_size: catalog.defaults.packet_size ?? 5, vc_buf_size: Number(vc_buf_size), use_noc_latency: catalog.defaults.use_noc_latency ?? 0, seed, overrides: { ...(catalog.simulators?.booksim_power_audited ? { sim_power: '1' } : {}), ...overrides } };
        const record: { request: AblationRequest; result?: any; error?: string } = { request }; nextRecords.push(record); setRecords([...nextRecords]);
        try {
          const result = await gateway.runAblation(request); const observed = (result.document as any)?.runs;
          if (!Array.isArray(observed) || observed.length !== topologyIds.length || new Set(observed.map((row: any) => row.topology)).size !== topologyIds.length || observed.some((row: any) => row.workload !== workload || !topologyIds.includes(row.topology))) throw new Error('Gateway did not return exactly one result for every requested topology; search remains incomplete.');
          record.result = result;
          for (const [i, raw] of observed.entries()) nextRows.push(searchObservation(raw, request, result.out, i));
          setRows([...nextRows]); setRecords([...nextRecords]); setProgress(`${Math.min((index + 1) * topologyIds.length, grid.count)} / ${grid.count} evaluations`);
        } catch (caught) { record.error = gatewayReason(caught); setRecords([...nextRecords]); throw caught; }
      }
      setPhase('complete'); setProgress(`${grid.count} evaluations complete`);
      const failed = nextRows.filter(row => row.status !== 'ok').length;
      notify(`Fabric search complete: ${grid.count} cells; ${failed} simulation failures. Recommendations use complete, comparable evidence only.`);
    } catch (caught) { setPhase('failed'); setFailure(gatewayReason(caught)); setProgress('Search incomplete; partial observations are retained but no winners are recommended.'); }
  }
  async function applyToDraft(row: SearchRow) {
    if (!loaded || !catalog) return;
    const topo = catalog.topologies.find(item => item.topology_id === row.topology);
    const input = { topology: row.topology, family: topo?.family, nodes: topo?.nodes, vcBufSize: row.request?.vc_buf_size };
    const intent = draftTopologyFor(input);
    const depth = draftDepthFor(input);
    if (!intent || depth === null) {
      setApplyState({ tone: 'amber', text: handoffReason(input) || 'This row cannot be written to the project draft.' });
      return;
    }
    if (loaded.draftMeta?.dirty) {
      setApplyState({ tone: 'amber', text: 'Save or discard the current draft edits before applying a fabric.' });
      return;
    }
    setApplying(true); setApplyState(null);
    try {
      const request = (loaded.request ?? {}) as Record<string, any>;
      const measuredWidth = Number(row.raw?.native_model?.channel_width_bits ?? row.raw?.knobs?.channel_width);
      const linkWidth = Number.isInteger(measuredWidth) && measuredWidth > 0 ? measuredWidth : null;
      // Canonicalise the topology first. A legacy v3 request must be sent
      // WITHOUT a root `topology` field: the v3 parser rejects it before the
      // gateway can migrate the document. Passing the topology separately
      // lets the gateway migrate to v4 and return the canonical request.
      const withTopology = request.topology !== undefined ? { ...request, topology: intent } : request;
      const topologyPreview = await gateway.topologyPreview(loaded.detail.project.project_id, withTopology, intent);
      const canonical = (topologyPreview.request ?? withTopology) as Record<string, any>;
      const nocKey = canonical.noc_controls !== undefined ? 'noc_controls' : 'noc_config';
      const depthKey = nocKey === 'noc_controls' ? 'input_buffer_depth_flits_per_vc' : 'vc_buf_size';
      const withControls = {
        ...canonical,
        [nocKey]: { ...(canonical[nocKey] ?? {}), [depthKey]: depth, ...(linkWidth ? { link_width: linkWidth } : {}) },
      };
      const controlPreview = await gateway.topologyPreview(loaded.detail.project.project_id, withControls, intent);
      const finalRequest = (controlPreview.request ?? withControls) as Record<string, any>;
      await gateway.putDraft(loaded.detail.project.project_id, finalRequest, loaded.draftMeta?.revisionToken);
      try { sessionStorage.setItem(`srota-intent-tab:${loaded.detail.project.project_id}`, 'fabric'); } catch { /* The tab hint is optional. */ }
      const applied = `${topologyLabel(row.topology)}${linkWidth ? `, ${linkWidth}-bit links` : ''} and ${depth} flits/VC`;
      setApplyState({ tone: 'blue', text: `Applied ${applied} to the draft. Validate and compile to publish it on this project.` });
      notify(`Applied ${applied} to the draft. Validate and compile before evaluation.`);
      reload();
      if (onApplied) onApplied();
      else navigate('workloads/workflow');
    } catch (caught) {
      setApplyState({ tone: 'red', text: gatewayReason(caught) });
    } finally {
      setApplying(false);
    }
  }
  function openInDesign(row: SearchRow) {
    const info = catalog?.workloads.find(item => item.workload_id === workload);
    try { sessionStorage.setItem('srota-workload-search-handoff', JSON.stringify({ workload: info, selected: { topology: row.topology, request: row.request, latency: row.latency, throughput: row.throughput, power: row.power, area: row.area, energy: row.energy, model: row.model, source: row.source, log: row.raw.log }, capturedAt: new Date().toISOString() })); } catch { /* Navigation remains available without optional session storage. */ }
    notify(`Opened Design with ${topologyLabel(row.topology)} · ${row.request.vc_buf_size} flits as a review reference. No configuration was changed.`);
    navigate('design/fabric-topology');
  }
  if (loading) return <div className="view-main"><p role="status">Loading fabric catalog…</p></div>;
  if (catalogError || !catalog) return <div className="view-main"><Notice tone="red">Could not load fabric search: {catalogError}</Notice><Button onClick={() => window.location.reload()}>Retry catalog</Button></div>;
  const selectedModel = selectedRow?.model;
  return <div className={`${embedded ? 'flow-embedded' : 'view-main'} explore-page fabric-search`} data-context-kind="section" data-context-id="explore-fabric-search" data-context-label="Fabric search">
    <section className="fabric-search-card" aria-label="Fabric search setup">
      <div className="fabric-search-row">
        <Field label="Reference trace"><select disabled={phase === 'running'} value={workload} onChange={e => { setWorkload(e.target.value); setWorkloadTouched(true); clear(); }}><option value="">Select a reference trace…</option>{catalog.workloads.map(item => <option key={item.workload_id} value={item.workload_id}>{item.label || item.workload_id}</option>)}</select></Field>
        <fieldset className="fabric-buffers"><legend>Buffer depth <small>flits per VC</small></legend><div className="fabric-chips">{availableBuffers.map(value => <label className="fabric-chip" key={value}><input type="checkbox" disabled={phase === 'running'} checked={buffers.includes(value)} onChange={() => { setBuffers(v => v.includes(value) ? v.filter(n => n !== value) : [...v, value]); clear(); }} /><span>{value} flits</span></label>)}</div></fieldset>
        <div className="fabric-search-action"><Button primary disabled={!!planError || !grid || phase === 'running' || !buffers.length || !workload} onClick={run} title={!workload ? 'Choose a reference trace first.' : undefined}><Icon name="search" />{phase === 'running' ? 'Searching…' : 'Find fabrics'}</Button><small>{!workload ? 'Choose a reference trace to plan the search.' : planError || `${grid?.count ?? 0} evaluations · ${topologyIds.length} fabrics`}</small></div>
      </div>
      <p className="fabric-workload-line"><strong>Project workload:</strong> {projectModel || 'not declared'}{projectWorkload ? ` · ${projectParallelism} · ${number(projectEndpoints)} declared endpoint seats` : ''}</p>
      <p className="fabric-workload-line"><strong>Reference trace:</strong> {workloadInfo ? <><span className="mono">{workloadInfo.label || workloadInfo.workload_id}</span> · {number(workloadInfo.nodes)} endpoints · {number(workloadInfo.events)} trace events · <span className="mono">trace {workloadInfo.trace_sha256 ? `${workloadInfo.trace_sha256.slice(0, 12)}…` : 'hash unavailable'}</span></> : 'Choose a reference trace.'}</p>
      {loaded && matchedTrace && <Notice tone="blue">
        <strong>Reference trace matched by identifier.</strong> {matchedTrace.label ?? matchedTrace.workload_id}. The catalog measurements are still made on that repository trace, not on this project revision.
      </Notice>}
      {loaded && !matchedTrace && <Notice tone="blue"><strong>Reference search only.</strong> Results measure {workloadInfo?.label ?? 'the selected repository trace'}, not this project; applying a fabric edits the draft but does not transfer those measurements.</Notice>}
      {!loaded && <p className="meta-line">No project is loaded, so the first catalog trace is an explicit sample-mode default.</p>}
      <details className="fabric-refine"><summary><span>Refine search</span><span>{limitCount ? `${limitCount} limit${limitCount === 1 ? '' : 's'}` : 'optional limits, budget and audited knobs'}</span></summary>
        <div className="fabric-refine-block"><h3>Limits</h3><div className="fabric-constraint-grid">{limitsMetrics.map(metric => <Field key={metric} label={`${metric === 'throughput' ? 'Min' : 'Max'} ${metricNames[metric]}`}><input type="number" disabled={phase === 'running'} min="0" step="any" value={limitValues[metric]} placeholder="Unbounded" onChange={e => updateLimit(metric, e.target.value)} /></Field>)}</div><p className="meta-line">Limits filter candidates before ranking. Changing a limit updates the recommendations immediately; it does not rerun the search.</p></div>
        <div className="fabric-refine-block"><h3>Search scope</h3><div className="form-grid"><Field label="Audited parameter"><select disabled={phase === 'running'} value={selectedKnob} onChange={e => setSelectedKnob(e.target.value)}><option value="">Choose an audited parameter…</option>{knobs.filter(k => !(k.name in dimensions)).map(k => <option key={k.name} value={k.name}>{k.name} · {k.category ?? 'backend'}</option>)}</select></Field><div className="toolbar toolbar-start"><Button disabled={phase === 'running' || !selectedKnob} onClick={addKnob}>Add parameter</Button></div><Field label="Evaluation budget" hint="The complete grid must fit; no silent truncation."><input type="number" disabled={phase === 'running'} min="1" max="10000" value={budget} onChange={e => { setBudget(e.target.valueAsNumber); clear(); }} /></Field><Field label="Seed"><input type="number" disabled={phase === 'running'} min="0" max="2147483647" value={seed} onChange={e => { setSeed(e.target.valueAsNumber); clear(); }} /></Field></div>
          {Object.entries(dimensions).map(([name, values]) => <fieldset className="knob-dimension" key={name}><div className="knob-heading"><strong>{name}</strong><button type="button" className="button" disabled={phase === 'running'} onClick={() => { setDimensions(d => { const next = { ...d }; delete next[name]; return next; }); clear(); }}>Remove parameter</button></div><div className="knob-values">{values.map((value, index) => <label className="knob-value" key={index}><input aria-label={`${name} value ${index + 1}`} disabled={phase === 'running'} value={String(value)} onChange={e => { const next = [...values]; next[index] = e.target.value; setDimensions(d => ({ ...d, [name]: next })); clear(); }} /><button type="button" disabled={phase === 'running' || values.length <= 1} aria-label={`Remove ${name} value ${index + 1}`} onClick={() => { setDimensions(d => ({ ...d, [name]: values.filter((_, i) => i !== index) })); clear(); }}>×</button></label>)}<Button disabled={phase === 'running'} onClick={() => setDimensions(d => ({ ...d, [name]: [...values, ''] }))}>Add value</Button></div><small>{knobs.find(k => k.name === name)?.note ?? knobs.find(k => k.name === name)?.owner ?? 'Audited backend override'}</small></fieldset>)}
          <details className="fabric-inventory"><summary>Available topology and knob inventory</summary>{catalog.topologies.map(t => <p className="meta-line" key={t.topology_id}>{t.label || t.topology_id} · {t.family ?? 'family unavailable'}{t.note ? ` · ${t.note}` : ''}</p>)}{knobs.map(k => <p className="meta-line" key={k.name}><code>{k.name}</code> · overridable · {k.note ?? k.owner ?? 'scope not stated'}</p>)}</details>
          {planError && <Notice tone="red">{planError}</Notice>}
        </div>
      </details>
      {phase === 'running' && <div className="fabric-progress"><progress aria-label="Search progress" max={grid?.count ?? 1} value={Number(progress.match(/^\d+/)?.[0] ?? 0)} /><span>{progress}</span></div>}
      {progress && phase !== 'running' && <p role="status" className="fabric-search-status">{progress}</p>}
      {failure && <Notice tone="red">{failure}</Notice>}
    </section>

    <section className="fabric-results" aria-labelledby="fabric-recommendations-heading">
      <div className="fabric-results-head"><div><h2 id="fabric-recommendations-heading">Recommended fabrics</h2></div><div className="actions"><Badge>{catalog.topologies.length} {catalog.topologies.length === 1 ? 'fabric' : 'fabrics'}</Badge><Badge>{catalog.workloads.length} {catalog.workloads.length === 1 ? 'workload' : 'workloads'}</Badge><Badge tone={phase === 'complete' ? 'green' : phase === 'running' ? 'blue' : 'neutral'}>{rows.length ? `${rows.length} measured` : 'Not run'}</Badge></div></div>
      {rows.length ? <>
        <div className="recommendations">{recommendations.map(result => {
          const ref = recommendations.find(other => other.id === (result.id === 'balanced' ? 'performance' : 'balanced'));
          const winner = result.winner;
          const metrics = profileMetrics(result.id, result.metrics);
          return <button type="button" className={`recommendation ${winner ? '' : 'empty'} ${selectedRow?.id === winner?.id ? 'selected' : ''}`} data-profile={result.id} key={result.id} aria-pressed={selectedRow?.id === winner?.id} onClick={() => winner && setSelectedId(winner.id)}>
            <span className="fabric-card-head"><span className="fabric-card-profile">{result.label}</span>{phase === 'running' ? <Badge tone="blue">Searching</Badge> : winner ? <Badge tone="blue">{result.frontier.length} frontier</Badge> : <Badge tone="amber">No winner</Badge>}</span>
            <strong>{phase === 'running' ? 'Measuring…' : winner ? topologyLabel(winner.topology) : 'No fabric'}</strong>
            <p className="fabric-card-why">{result.description}</p>
            {phase === 'running' ? <span className="fabric-card-reason">Evaluating {grid?.count ?? 0} configurations. Recommendations appear when every requested depth has finished.</span> : winner ? <>
              <span className="winner-config">{winner.request.vc_buf_size} flits per VC</span>
              <span className="fabric-metric-grid">{metrics.map(metric => <span className="fabric-metric" key={metric}><span>{metricNames[metric]}</span><strong>{metricValue(winner, metric)}</strong><span className="fabric-metric-track"><i style={{ width: `${barWidth(winner[metric], result.frontier.map(row => row[metric]), metric === 'throughput')}%` }} /></span></span>)}</span>
              <span className="tradeoff">{searchTradeoff(winner, ref?.winner ?? null, ref?.label ?? 'Balanced')}</span>
            </> : <span className="fabric-card-reason">{result.reason}</span>}
          </button>;
        })}</div>
        <p className="fabric-card-note">Bars are relative to each profile&apos;s feasible frontier.</p>
        <Section title="Measured fabric trade-offs" actions={<Badge>{chartPoints.length} plotted</Badge>}>
          {chartPoints.length > 1 ? <InteractiveScatter points={chartPoints} selected={selectedRow?.id ?? null} onSelect={setSelectedId}
            xLabel="Accepted throughput (packets/cycle) · higher is better" yLabel="P95 latency (cycles) · lower is better"
            label="Measured fabric trade-offs across the catalog" /> : <p className="meta-line">Not enough measured latency and throughput pairs to plot a trade-off.</p>}
        </Section>
        {selectedRow && <div className="fabric-selection" aria-live="polite">
          <div className="fabric-selection-copy"><strong>{topologyLabel(selectedRow.topology)}</strong><p>{catalog.topologies.find(t => t.topology_id === selectedRow.topology)?.family ?? 'family unavailable'} · {selectedRow.request.vc_buf_size} flits per VC · {number(selectedRow.routers)} routers</p></div>
          <dl className="fabric-selection-metrics">{[['P95 latency', `${number(selectedRow.latency)} cyc`], ['Throughput', `${number(selectedRow.throughput)} pkt/cyc`], ['Power', `${number(selectedRow.power)} W`], ['Area', `${number(selectedRow.area)} mm²`], ['Replay energy', energy(selectedRow.energy)]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
          <div className="fabric-selection-actions">{recommendedAs.map(label => <Badge key={label} tone="blue">{label}</Badge>)}{selectedStatus !== 'Measured · passes entered limits' && <Badge tone="amber">{selectedStatus}</Badge>}
            <Button primary disabled={!canApply} title={applyReason || 'Write this topology, measured link width and buffer depth to the project draft.'} onClick={() => applyToDraft(selectedRow)}>{applying ? 'Applying…' : 'Apply topology to draft'}</Button>
            <Button disabled={applying} onClick={() => openInDesign(selectedRow)}><Icon name="arrow" />Open in Design as reference</Button>
          </div>
          {applyReason && <p className="meta-line">{applyReason}</p>}
          {applyState && <Notice tone={applyState.tone}>{applyState.text}</Notice>}
          <p className="meta-line">Catalog measurements were taken on <strong>{workloadInfo?.label ?? 'the selected trace'}</strong> ({number(workloadInfo?.nodes)} endpoints). Applying writes topology, measured link width and buffer depth{loaded ? ` to ${loaded.detail.project.name}` : ''}; those latency, throughput, power and area numbers are not transferred. Compile and evaluate to measure this project.</p>
          {selectedModel && <details className="fabric-selection-provenance"><summary>Model limits &amp; exact request</summary><p className="meta-line">{selectedModel.status === 'AVAILABLE' ? `Model ${selectedModel.model_id} · ${selectedModel.technology ?? 'native model'}. ${selectedModel.limitations ?? ''}` : 'No compatible cost model. This direction requires same-run identified model evidence.'}</p><pre className="code-preview">{JSON.stringify(selectedRow.request, null, 2)}</pre></details>}
        </div>}
      </> : <div className="fabric-empty"><span className="fabric-empty-icon"><Icon name="network" size={30} /></span><strong>No fabrics measured yet</strong><p>Choose a reference trace and buffer depth, then run a search.</p></div>}
    </section>

    <details className="fabric-evidence"><summary>Measured configurations &amp; exact requests <span>{rows.length} rows</span></summary>
      {rows.length ? <div className="table-scroll advisor-table-scroll"><table><thead><tr><th>Topology / knobs</th><th>P95 cycles</th><th>Packets / cycle</th><th>Routers</th><th>Crosspoints</th><th>Buffer flits</th><th>Power W · model</th><th>Area mm² · model</th><th>Replay energy pJ · model</th><th>Status / limits</th></tr></thead><tbody>{[...rows].sort((a, b) => (a.latency ?? Infinity) - (b.latency ?? Infinity)).map(row => <tr key={row.id} className={selectedRow?.id === row.id ? 'selected' : undefined}><th><button type="button" className="text-button" onClick={() => setSelectedId(row.id)}>{topologyLabel(row.topology)}</button><pre className="code-preview">{JSON.stringify({ vc_buf_size: row.request.vc_buf_size, ...row.request.overrides })}</pre></th>{(['latency', 'throughput', 'routers', 'crosspoints', 'storage', 'power', 'area', 'energy'] as const).map(metric => { const diagnosticKey = ({ power: 'power_w', area: 'area_mm2', energy: 'total_energy_pj' } as const)[metric as 'power' | 'area' | 'energy']; const diagnostic = ['INCOMPLETE', 'UNAUDITED'].includes(row.raw.native_output?.status) ? row.raw.native_output : null; const emitted = diagnosticKey && finiteValue(diagnostic?.[diagnosticKey]) ? diagnostic[diagnosticKey] : null; return <td className="numeric" key={metric}>{number(row[metric])}{row[metric] === null && emitted !== null ? ' †' : ''}</td>; })}<td>{constraintFailuresText(row, limits)}</td></tr>)}</tbody></table><Button onClick={() => downloadJson('fabric-search-evidence.json', { workload, records, observations: rows })}>Export exact search evidence</Button></div> : <p className="meta-line">Run a search to inspect measured configurations. Missing evidence is never treated as zero.</p>}
      {rows.some(row => ['INCOMPLETE', 'UNAUDITED'].includes(row.raw.native_output?.status)) && <p className="meta-line">† Partial or unaudited native output; excluded from recommendations and constraints.</p>}
      <details className="fabric-record"><summary>Execution record &amp; exact requests</summary><pre className="code-preview">{records.length ? JSON.stringify(records, null, 2) : 'Not run.'}</pre></details>
    </details>

    <Assumptions rows={[
      ['Scope', 'Catalog search over repository reference workload × fabric × buffer configurations. It is not the loaded revision. Only an exact identifier match between the project workload and a catalog trace is preselected; otherwise the operator chooses the reference trace. Applying a fabric writes topology, measured link width and buffer depth to the project draft; the catalog latency, throughput, power and area measurements are not transferred.'],
      ['Evidence', 'Latency, throughput and energy are measured from the same trace run; power and area come from the same-run native cost model. Missing evidence is never treated as zero or borrowed from another configuration.'],
      ['Ranking', 'Each profile ranks a different objective. Limits filter before ranking and update recommendations without rerunning. Trade-offs are stated relative to Balanced.'],
      ['Trade-off plot', 'All measured rows are plotted. Limit filters apply to the recommendation cards, not to this view. Bars are relative to each profile\'s feasible frontier.'],
      ['Not established', 'Requirement compliance, RTL qualification and hardware sign-off. Viewing a fabric in Design is a review reference and changes no configuration; applying it requires an explicit action and a new compile and evaluation on this project.'],
    ]} />
  </div>;
}
function constraintFailuresText(row: SearchRow, limits: Partial<Record<SearchMetric, number | null>>) { return [...(row.status === 'ok' ? [] : [`Simulation ${row.status}`]), ...Object.entries(limits).flatMap(([metric, limit]) => limit == null ? [] : row[metric as SearchMetric] === null ? [`${metricNames[metric as SearchMetric]} unavailable`] : (metric === 'throughput' ? row[metric as SearchMetric]! < limit : row[metric as SearchMetric]! > limit) ? [`${metricNames[metric as SearchMetric]} limit failed`] : [])].join(' · ') || 'Measured · passes entered limits'; }
