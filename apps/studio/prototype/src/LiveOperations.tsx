import { useEffect, useRef, useState } from 'react';
import { DesignAdvisor } from './DesignAdvisor';
import { JobEvents } from './JobEvents';
import { CandidateEvidence } from './CandidateEvidence';
import { CONVERTIBLE_FAMILIES, candidateNames, discoverFabricDomain, fabricComparisonFamilies, fabricGrid, type FabricDomain } from './recommendation';
import { StudyAdoption } from './StudyAdoption';
import { StudyWorkbench } from './LiveStudyResults';
import { gateway, gatewayReason, type FederatedMetricDescriptor, type GeneratedReport, type Job, type LoomOrigin, type OptimizationConstraint, type OptimizationObjective, type OptimizationView } from './gateway';
import { useProject, type LoadedProject } from './project';
import { Assumptions, Badge, Button, Empty, Field, Notice, PageLink, Properties, Section, downloadJson } from './ui';
import { bytes, cappedClass, stamp } from './format';

export function useGatewayDocument(key: string, read: () => Promise<Record<string, any>>) {
  const reader = useRef(read); reader.current = read;
  const [result, setResult] = useState<{ key: string; data?: Record<string, any>; error?: string }>({ key: '' });
  useEffect(() => { let live = true; const call = reader.current; setResult({ key }); call().then(data => { if (live) setResult({ key, data }); }).catch(e => { if (live) setResult({ key, error: gatewayReason(e) }); }); return () => { live = false; }; }, [key]);
  return result.key === key ? result : { key };
}
function DocumentState({ error }: { error?: string }) { return error ? <Notice tone="red">{error}</Notice> : <p>Loading…</p>; }
const terminal = (job: Job) => ['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(job.state);
const defaultStudyValues = (name: string, field: any): string => {
  if (field?.kind === 'enum') return (field.executable_values ?? []).slice(0, 4).join(',');
  if (['tp', 'ep', 'dp', 'pp'].includes(name)) return '2,4';
  if (name === 'radix') return '4,8';
  return '64,128';
};
const studyValueSuggestions = (name: string): number[] => {
  if (name === 'link_width') return [32, 64, 128, 256];
  if (name === 'radix') return [2, 4, 8, 16];
  if (['tp', 'ep', 'dp', 'pp'].includes(name)) return [1, 2, 4, 8];
  return [];
};

/** One objective choice in the bounded study. ``dimensions`` mirrors the
 *  backend metric catalog: an empty list is the aggregate reading, and
 *  ``traffic_class`` marks a reading that only binds with a class selector. */
export type StudyMetric = { metric: string; question: string; unit?: string | null; dimensions?: string[] };

/** The aggregate objectives the study already offered, plus every eligible
 *  per-class metric the backend catalog actually declares. Nothing is derived
 *  from a class name or a metric-name suffix. */
export function studyMetricOptions(federated?: FederatedMetricDescriptor[]): StudyMetric[] {
  const rows: StudyMetric[] = [{ metric: 'completion_cycles', question: 'NETWORK_COMPLETION', unit: 'cycles', dimensions: [] }];
  for (const row of federated ?? []) {
    if (row.optimization_eligible !== true) continue;
    const dimensions = row.dimensions ?? [];
    const perClass = dimensions.includes('traffic_class');
    const knownAggregate = ['system_makespan_cycles', 'average_read_latency_cycles'].includes(row.metric);
    if (!perClass && !knownAggregate) continue;
    if (rows.some(item => item.metric === row.metric)) continue;
    rows.push({ metric: row.metric, question: row.question ?? '', unit: row.unit ?? (/cycles|latency/.test(row.metric) ? 'cycles' : null), dimensions });
  }
  return rows;
}

export function metricSupportsTrafficClass(metric?: StudyMetric): boolean {
  return (metric?.dimensions ?? []).includes('traffic_class');
}

/** Optional class selector shared by the objective and every constraint. The
 *  empty option is the aggregate reading and is the default, so an existing
 *  study request keeps its exact shape. */
export function TrafficClassSelect({ label, value, classes, onChange }: {
  label: string;
  value: string;
  classes: string[];
  onChange: (next: string) => void;
}) {
  return <select aria-label={label} value={value} onChange={event => onChange(event.target.value)}>
    <option value="">No class · aggregate reading</option>
    {classes.map(name => <option key={name} value={name}>{name}</option>)}
  </select>;
}

export const studyMetricUnit = (metric?: StudyMetric): string => metric?.unit ?? (/cycles|latency/.test(metric?.metric ?? '') ? 'cycles' : '');

const studyMetricLabel = (metric: StudyMetric, fabricSearch: boolean): string => {
  const unit = studyMetricUnit(metric);
  if (fabricSearch) {
    if (metric.metric === 'completion_cycles') return 'Network completion (cycles)';
    if (metric.metric === 'system_makespan_cycles') return 'System makespan (cycles)';
    if (metric.metric === 'average_read_latency_cycles') return 'Memory read latency (cycles)';
    return `${metric.metric.replaceAll('_', ' ')}${unit ? ` (${unit})` : ''}`;
  }
  return `${metric.question || 'Metric'} · ${metric.metric}${unit && unit !== 'cycles' ? ` (${unit})` : ''}`;
};

type DeclaredRequest = {
  request?: Record<string, any> | null;
  detail?: { active_revision?: { design?: Record<string, any> | null } | null } | null;
  compileResult?: Record<string, any> | null;
};

/** Canonical classes the revision actually declares. Only workload/coherence
 *  collectives, declared requirements, and the compiled class-to-VC binding
 *  contribute; an empty result is shown as empty, never filled with a guess. */
export function declaredTrafficClasses(project: DeclaredRequest): string[] {
  const found = new Set<string>();
  const add = (value: unknown) => {
    if (typeof value === 'string' && value && value === value.trim()) found.add(value);
  };
  const scan = (rows: unknown) => {
    if (!Array.isArray(rows)) return;
    for (const row of rows) {
      if (typeof row === 'string') add(row);
      else if (row && typeof row === 'object') add((row as any).traffic_class);
    }
  };
  for (const root of [project.request, project.detail?.active_revision?.design]) {
    if (!root) continue;
    // A v5 draft embeds its v4 design under ``base_v4``.
    for (const request of [root, root.base_v4]) {
      if (!request) continue;
      scan(request.workload?.collectives);
      scan(request.workload?.coherence);
      scan(request.collectives);
      scan(request.coherence);
      scan(request.requirements);
    }
  }
  const binding = project.compileResult?.groups?.resources?.traffic_class_to_vcs;
  if (Array.isArray(binding)) {
    for (const entry of binding) {
      if (Array.isArray(entry)) add(entry[0]);
      else if (entry && typeof entry === 'object') add((entry as any).traffic_class ?? (entry as any)[0]);
    }
  }
  return [...found].sort();
}

export type StudyConstraintRow = { metric: string; op: '<=' | '>='; threshold: string; traffic_class?: string };

/** The objective payload the backend accepts. An aggregate objective emits no
 *  ``traffic_class`` key at all, so its request bytes do not move. */
export function buildStudyObjectives(input: { metric: string; question?: string; trafficClass?: string; memory?: boolean }): OptimizationObjective[] {
  const objectives: OptimizationObjective[] = [{
    metric: input.metric,
    direction: 'MIN',
    ...(input.question ? { question: input.question } : {}),
    ...(input.trafficClass ? { traffic_class: input.trafficClass } : {}),
  }];
  if (input.memory && input.metric !== 'average_read_latency_cycles') {
    objectives.push({ metric: 'average_read_latency_cycles', direction: 'MIN', question: 'DRAM_TIMING' });
  }
  return objectives;
}

export function buildStudyConstraints(rows: StudyConstraintRow[]): OptimizationConstraint[] {
  return rows.map(row => ({
    metric: row.metric,
    op: row.op,
    threshold: Number(row.threshold),
    ...(row.traffic_class ? { traffic_class: row.traffic_class } : {}),
  }));
}

/** The axis key the backend serialized into the study definition. A
 *  class-scoped axis carries its own key, so the UI never assembles the
 *  composite spelling itself. */
export function studyAxisKey(axis: { metric?: string; key?: string; traffic_class?: string | null }): string {
  if (axis.key) return axis.key;
  // An aggregate axis has always been keyed by its bare metric. A classed
  // axis without the backend's own key has no safe reading to look up; an
  // empty key reports it as not measured instead of showing the aggregate.
  return axis.traffic_class ? '' : axis.metric ?? '';
}

const axisMetric = (axis: { metric?: string; key?: string }): string => axis.metric ?? axis.key ?? '';
const axisLabel = (axis: { metric?: string; key?: string; traffic_class?: string | null }): string =>
  axis.traffic_class ? `${axisMetric(axis)} · ${axis.traffic_class}` : axisMetric(axis);

/** Prefer the study's v2 definition, which names each class-scoped axis key. */
const studyDefinitionOf = (study: any): any => study?.study?.definition ?? study?.definition;

export type StudyAxisRow = { key: string; metric: string; traffic_class: string | null; label: string };

export function studyAxisRows(study: any): { objectives: StudyAxisRow[]; constraints: StudyAxisRow[]; classed: boolean } {
  const definition = studyDefinitionOf(study);
  const rows = (axes: any[] | undefined): StudyAxisRow[] => (axes ?? []).map(axis => ({
    key: studyAxisKey(axis),
    metric: axisMetric(axis),
    traffic_class: axis.traffic_class ?? null,
    label: axisLabel(axis),
  }));
  const objectives = rows(definition?.objectives);
  const constraints = rows(definition?.constraints);
  return { objectives, constraints, classed: [...objectives, ...constraints].some(row => row.traffic_class !== null) };
}

/** Class-scoped readings only. Aggregate objectives stay in the existing
 *  candidate table; this panel never hides or rewrites them. */
export function ClassScopedStudyResults({ study }: { study: OptimizationView | Record<string, any> }) {
  const axes = studyAxisRows(study);
  if (!axes.classed) return null;
  const candidates: any[] = study?.study?.candidates ?? [];
  if (!candidates.length) return null;
  const names = candidateNames(study);
  const objectives = axes.objectives.filter(row => row.traffic_class !== null);
  const constraints = axes.constraints.filter(row => row.traffic_class !== null);
  return <Section title="Class-scoped study results" actions={<Badge tone="blue">Traffic class readings</Badge>}>
    <p className="meta-line">Objective values and constraint verdicts below are the backend’s readings for the named class. Aggregate objectives remain in the measured-outcome table.</p>
    <div className="table-scroll"><table aria-label="Class-scoped study results"><thead><tr><th>Candidate</th>
      {objectives.map((row, index) => <th key={row.key || `objective-${index}`}>{row.label}</th>)}
      {constraints.map((row, index) => <th key={row.key || `constraint-${index}`}>{row.label} verdict</th>)}
    </tr></thead><tbody>
      {candidates.map((candidate, index) => <tr key={candidate.candidate_id}>
        <th>{names.get(candidate.candidate_id) ?? `C${index + 1}`}</th>
        {objectives.map((row, index) => {
          const value = row.key ? candidate.objective_values?.[row.key] : undefined;
          const availability = row.key ? candidate.objective_availability?.[row.key] : undefined;
          return <td key={row.key || `objective-${index}`} className="numeric">{typeof value === 'number' && Number.isFinite(value) ? <>{value.toLocaleString()}<small className="block">{availability ?? 'authority not reported'}</small></> : <span className="muted">{availability ?? 'Not measured'}</span>}</td>;
        })}
        {constraints.map((row, index) => {
          const verdict = row.key ? candidate.constraint_verdicts?.[row.key] : undefined;
          const detail = (candidate.constraint_details ?? []).find((item: any) => item?.traffic_class === row.traffic_class && item?.metric === row.metric);
          return <td key={row.key || `constraint-${index}`}>{verdict ? <Badge tone={verdict === 'SATISFIED' ? 'green' : verdict === 'VIOLATED' ? 'red' : 'amber'}>{verdict}</Badge> : <span className="muted">Not reported</span>}
            {detail && typeof detail.measured === 'number' && typeof detail.required === 'number' && <small className="block">{detail.measured.toLocaleString()} measured / {detail.required.toLocaleString()} required</small>}
          </td>;
        })}
      </tr>)}
    </tbody></table></div>
  </Section>;
}

function ValueEditor({ label, values, onChange, kind, options = [], suggestions = [], max = 4 }: {
  label: string;
  values: string;
  onChange: (next: string) => void;
  kind: 'int' | 'enum';
  options?: string[];
  suggestions?: number[];
  max?: number;
}) {
  const [draft, setDraft] = useState('');
  const selected = [...new Set(values.split(',').map(value => value.trim()).filter(Boolean))];
  const apply = (next: string[]) => onChange(next.slice(0, max).join(','));
  const add = () => {
    const next = [...selected];
    for (const raw of draft.split(',').map(value => value.trim()).filter(Boolean)) {
      const value = String(Number(raw));
      if (!Number.isSafeInteger(Number(raw)) || Number(raw) <= 0 || next.includes(value)) continue;
      if (next.length >= max) break;
      next.push(value);
    }
    apply(next); setDraft('');
  };
  if (kind === 'enum') return <fieldset className="value-field">
    <legend>{label}</legend>
    <div className="value-chips">
      {options.map(option => <label key={option} className={`check-chip${selected.includes(option) ? ' selected' : ''}`}><input type="checkbox" checked={selected.includes(option)} disabled={!selected.includes(option) && selected.length >= max} onChange={() => apply(selected.includes(option) ? selected.filter(value => value !== option) : [...selected, option])} />{option}</label>)}
      {!options.length && <span className="meta-line">No executable values reported.</span>}
    </div>
    <small className="value-hint">Choose up to {max}.{selected.length ? ` ${selected.length}/${max} selected.` : ''}</small>
  </fieldset>;
  return <fieldset className="value-field">
    <legend>{label}</legend>
    <div className="value-chips">
      {selected.map(value => <span className="value-chip" key={value}><span>{value}</span><button type="button" aria-label={`Remove ${value}`} onClick={() => apply(selected.filter(item => item !== value))}>×</button></span>)}
      {selected.length < max && <span className="value-add"><input aria-label={`Add a value to ${label.toLowerCase()}`} type="number" min="1" step="1" value={draft} placeholder="Add a value" onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); add(); } }} /><Button onClick={add} disabled={!draft.trim()}>Add value</Button></span>}
    </div>
    {suggestions.some(value => !selected.includes(String(value))) && selected.length < max && <div className="value-suggestions"><span>Common</span>{suggestions.filter(value => !selected.includes(String(value))).map(value => <button type="button" key={value} className="value-suggestion" onClick={() => apply([...selected, String(value)])}>{value}</button>)}</div>}
    <small className="value-hint">Add up to {max} values.{selected.length ? ` ${selected.length}/${max} added.` : ''}</small>
  </fieldset>;
}
export function useGatewayJob(id: string) {
  const [job, setJob] = useState<Job | null>(null), [error, setError] = useState(''), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true, timer: number | undefined;
    setJob(null); setError('');
    const poll = async () => {
      try { const value = await gateway.job(id); if (!live) return; setJob(value); if (!terminal(value)) timer = window.setTimeout(poll, 2000); }
      catch (e) { if (live) setError(gatewayReason(e)); }
    };
    if (id) void poll();
    return () => { live = false; window.clearTimeout(timer); };
  }, [id, refresh]);
  return { job, error, retry: () => setRefresh(n => n + 1), cancel: async () => { try { await gateway.cancelJob(id); setRefresh(n => n + 1); } catch (e) { setError(gatewayReason(e)); } } };
}

export function LiveCapabilities({ project }: { project: LoadedProject }) {
  const { data, error } = useGatewayDocument(`capabilities:${project.detail.project.project_id}`, async () => {
    const [registry, gaps] = await Promise.all([gateway.capabilities(), gateway.capabilityGaps()]);
    return { registry, gaps };
  });
  if (!data) return <div className="view-main"><DocumentState error={error} /><Assumptions rows={[['Source', 'Backend registry and capability-gap document from the project gateway; no rows are shown while it is unavailable.']]} /></div>;
  return <div className="view-main">
    <Section title="Registered backend support"><div className="table-scroll"><table><thead><tr><th>Backend</th><th>Lowering</th><th>Execution</th><th>Evidence / scope</th></tr></thead><tbody>{Object.entries(data.registry.backends ?? {}).map(([name, value]: [string, any]) => <tr key={name}><th>{name}</th><td>{value.lowering ?? 'Not reported'}</td><td>{value.execution ?? 'Not reported'}</td><td>{value.fidelity_note ?? value.profile ?? 'Not reported'}</td></tr>)}</tbody></table></div></Section>
    <Section title="Backend capability gaps"><div className="table-scroll"><table><thead><tr><th>Capability</th><th>Source</th><th>State</th></tr></thead><tbody>{(data.gaps.gaps ?? []).map((g: any, i: number) => <tr key={i}><th>{g.capability}</th><td className="mono">{g.source}:{g.line}</td><td>Open</td></tr>)}</tbody></table></div></Section>
    <Section title="Deferred qualification"><Properties rows={Object.entries(data.registry.deferred ?? {}).map(([name, value]) => [name, String(value)])} /></Section>
    <Button onClick={() => downloadJson('backend-capabilities.json', data)}>Export registry JSON</Button><PageLink page="verify/obligations">Review this project’s design obligations</PageLink><PageLink page="analysis/summary">Review revision evaluation plan</PageLink>
    <Assumptions rows={[
      ['Source', 'Backend registry and capability-gap document from the project gateway.'],
      ['Scope', 'Backend registry and refusal sites. Installation is not configuration-specific qualification.'],
      ['Gaps note', data.gaps.note ?? 'Not reported'],
    ]} />
  </div>;
}

const obligationTone = (state: string) => state === 'RESOLVED' ? 'green' as const : state === 'NOT_APPLICABLE' ? 'neutral' as const : 'amber' as const;
export function LiveObligations({ project }: { project: LoadedProject }) {
  const id = project.detail.project.project_id;
  const { data, error } = useGatewayDocument(`obligations:${id}:${project.detail.active_revision_id ?? ''}`, () => gateway.obligations(id));
  if (!data) return <div className="view-main"><DocumentState error={error} /><Assumptions rows={[['Source', 'Gateway obligation register; no obligations are shown while it is unavailable.']]} /></div>;
  const obligations = data.obligations ?? [];
  return <div className="view-main">
    <Properties rows={[[ 'Project', project.detail.project.name ], ['Revision', data.revision_id ?? 'No active revision' ], ['Run', data.run_id ?? 'No run' ], ['Open', String(data.counts.OPEN ?? 0) ], ['Blocking open', String(data.counts.blocking_open ?? 0) ], ['Resolved', String(data.counts.RESOLVED ?? 0) ], ['Not applicable', String(data.counts.NOT_APPLICABLE ?? 0) ], ['Source', data.source ]]} />
    <Section title="Outstanding engineering obligations" actions={<Button onClick={() => downloadJson(`${id}-obligations.json`, data)}>Download register</Button>}>
      <div className="table-scroll"><table><thead><tr><th>Obligation</th><th>Question</th><th>Scope</th><th>State</th><th>Evidence</th><th>Next action</th></tr></thead><tbody>
        {obligations.map((row: any) => <tr key={row.obligation_id}>
          <th><span className="mono">{row.obligation_id}</span><br />{row.title}{row.blocking && row.state === 'OPEN' && <><br /><Badge tone="red">Blocking</Badge></>}</th>
          <td>{row.question}</td>
          <td>{row.scope}</td>
          <td><Badge tone={obligationTone(row.state)}>{row.state}</Badge></td>
          <td><p>{row.evidence?.summary ?? 'No evidence summary.'}</p><details><summary>Evidence record</summary><pre className="code-preview">{JSON.stringify({ evidence: row.evidence, sources: row.sources }, null, 2)}</pre></details></td>
          <td>{row.next_action}</td>
        </tr>)}
      </tbody></table></div>
    </Section>
    <PageLink page="verify/support">Backend capability gaps are separate</PageLink>
    <Assumptions rows={[
      ['Source', 'Gateway obligation register derived from the project draft, latest active run, and declared product limits.'],
      ['Scope', 'Resolved means measured evidence satisfies the stated obligation scope; it never means RTL or physical qualification.'],
      ['Separate register', 'Design obligations are separate from backend capability gaps.'],
      ['Register note', data.note ?? 'Not reported'],
    ]} />
  </div>;
}
export function LiveDelivery({ project }: { project: LoadedProject }) {
  const { run } = useProject(), revision = project.detail.active_revision_id;
  const { data, error } = useGatewayDocument(`delivery:${revision}`, () => revision ? gateway.revisionArtifacts(revision) : Promise.reject(new Error('Compile a revision first.')));
  const revisions = project.detail.revisions ?? [];
  const others = revisions.filter(item => item.revision_id !== revision);
  const [compareId, setCompareId] = useState(others[0]?.revision_id ?? '');
  const [compare, setCompare] = useState<{ phase: 'idle' | 'loading' | 'ready' | 'error'; data?: Record<string, any>; reason?: string }>({ phase: 'idle' });
  useEffect(() => {
    if (!compareId) { setCompare({ phase: 'idle' }); return; }
    let live = true;
    setCompare({ phase: 'loading' });
    gateway.revisionArtifacts(compareId)
      .then(value => { if (live) setCompare({ phase: 'ready', data: value }); })
      .catch(caught => { if (live) setCompare({ phase: 'error', reason: gatewayReason(caught) }); });
    return () => { live = false; };
  }, [compareId]);
  if (!data) return <div className="view-main"><DocumentState error={error} /><Assumptions rows={[['Source', 'Revision artifact manifest from the project gateway; no nodes are shown while it is unavailable.']]} /></div>;
  const nodes = (data.nodes ?? []) as { artifact: string; label?: string; hash: string; parents?: string[]; proved_by?: string[]; revalidated_by?: string }[];
  const proved = nodes.filter(node => (node.proved_by ?? []).length > 0).length;
  const revalidatedOnly = nodes.filter(node => !(node.proved_by ?? []).length && node.revalidated_by).length;
  const scopes = (data.compiled_system?.scopes ?? {}) as Record<string, string>;
  const scopeMeaning: Record<string, string> = {
    control_plane: 'Declared structure only; no control-plane execution.',
    domain_execution: 'Clock and power domain execution is not modeled.',
    extensions: 'V5 extensions are structural declarations only.',
    hardware: 'Legacy certificate obligations remain open; not hardware signoff.',
    physical: 'Legacy topology hints only; no floorplan, parasitics, or timing.',
    routing: 'Routes are normalized for transit; no congestion or timing proof.',
    transactions: 'Transactions are not materialized; no runtime behaviour.',
  };
  const previous = compare.phase === 'ready' ? (compare.data?.nodes ?? []) as typeof nodes : [];
  const previousContent = new Map(previous.map(node => [node.artifact, node.hash]));
  const diff = nodes.map(node => ({ ...node, change: !previousContent.has(node.artifact) ? 'added' : previousContent.get(node.artifact) === node.hash ? 'same' : 'changed' }));
  const removed = previous.filter(node => !nodes.some(active => active.artifact === node.artifact));
  const changed = diff.filter(node => node.change !== 'same').length + removed.length;
  return <div className="view-main">
    <Section title="Manifest export" actions={<Badge tone={data.certificate_id ? 'green' : 'neutral'}>{data.certificate_id ? 'Certificate recorded' : 'No certificate'}</Badge>}>
      <div className="toolbar toolbar-start">
        <Button primary onClick={() => downloadJson(`${revision}-manifest.json`, data)}>Download manifest JSON</Button>
        {run.phase === 'loaded' && <Button onClick={() => downloadJson(`${run.data.detail.run_id}-evidence-index.json`, { run: run.data.detail, artifacts: run.data.artifacts, integrity: run.data.integrity })}>Download run evidence index</Button>}
      </div>
      <p className="meta-line">This page lists what the revision produced and how each artifact is proved. It does not generate RTL: the topology-only RTL preview lives in <PageLink page="flow/run">Flow · Finalize &amp; RTL</PageLink>.</p>
    </Section>
    <Section title="Artifact graph" actions={<><Badge>{nodes.length} nodes</Badge><Badge>{proved} named proofs</Badge>{revalidatedOnly > 0 && <Badge tone="amber">{revalidatedOnly} revalidation only</Badge>}</>}>
      <div className={`table-scroll${cappedClass(nodes.length)}`}><table><thead><tr><th>Artifact</th><th>Derived from</th><th>Proof</th></tr></thead><tbody>
        {nodes.map(node => <tr key={node.artifact}>
          <th>{node.label ?? node.artifact}<br /><span className="mono muted">{node.artifact}</span></th>
          <td className="mono">{((node.parents ?? []) as string[]).join(', ') || 'root'}</td>
          <td>{(node.proved_by ?? []).length ? <span className="mono">{(node.proved_by ?? []).join(', ')}</span> : node.revalidated_by ? <Badge tone="amber">Revalidated only</Badge> : (node.parents ?? []).length ? 'None reported' : <span className="muted">root input</span>}</td>
        </tr>)}
      </tbody></table></div>
    </Section>
    <Section title="Compare with another revision" actions={compare.phase === 'ready' ? <Badge tone={changed ? 'amber' : 'green'}>{changed ? `${changed} difference${changed === 1 ? '' : 's'}` : 'Identical manifest'}</Badge> : undefined}>
      {others.length ? <>
        <div className="toolbar toolbar-start"><label className="field"><span>Comparison revision</span>
          <select value={compareId} onChange={event => setCompareId(event.target.value)}>{others.map(item => <option key={item.revision_id} value={item.revision_id}>{item.revision_id}{item.display_name ? ` · ${item.display_name}` : ''}</option>)}</select>
        </label></div>
        {compare.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading {compareId} manifest…</p>}
        {compare.phase === 'error' && <Notice tone="red">{compare.reason}</Notice>}
        {compare.phase === 'ready' && <>
          <div className={`table-scroll${cappedClass(diff.length)}`}><table><thead><tr><th>Artifact</th><th>Change</th></tr></thead><tbody>
            {diff.map(node => <tr key={node.artifact}><th>{node.label ?? node.artifact}</th><td>{node.change === 'same' ? <span className="muted">same</span> : <Badge tone={node.change === 'changed' ? 'amber' : 'green'}>{node.change}</Badge>}</td></tr>)}
            {removed.map(node => <tr key={`removed-${node.artifact}`}><th>{node.label ?? node.artifact}</th><td><Badge tone="red">removed</Badge></td></tr>)}
          </tbody></table></div>
        </>}
      </> : <Empty title="No other revision to compare">Compile a second revision to diff manifests.</Empty>}
    </Section>
    <Section title="Declared scope coverage">
      <div className="table-scroll"><table><thead><tr><th>Scope</th><th>Declared</th><th>Reading</th></tr></thead><tbody>
        {Object.entries(scopes).map(([name, value]) => <tr key={name}><th className="mono">{name}</th><td><Badge tone={/NOT_|LEGACY|DECLARED/.test(value) ? 'amber' : 'green'}>{value}</Badge></td><td>{scopeMeaning[name] ?? 'No plain-language reading registered.'}</td></tr>)}
      </tbody></table></div>
    </Section>
    <OriginVocabulary />
    <GeneratedReports />
    <Assumptions rows={[
      ['Source', 'Revision artifact manifest from the project gateway; revision comparison reads the same manifest for another revision.'],
      ['Scope', 'Compiled artifact references and the certificate record only. Not generated RTL, a bitstream, a timing or power result, or physical signoff.'],
      ['Certificate', 'A recorded certificate identifies the derivation graph; it is not a signature.'],
      ['Proofs', 'The proof column reports named compiler proofs per artifact. A structurally revalidated node has no independent proof; absence of a proof is shown, never treated as failure or success.'],
      ['Comparison', 'Node identity is compared across revisions, not design correctness. A changed node is the place to look; it is not automatically a regression.'],
      ['Coverage', "Scopes are the manifest's own statement of what it does not cover. File-body download, RTL generation, and ASIC/FPGA implementation are unavailable through this API."],
      ['Reports', 'Generated reports and plots are served read-only from the gateway inventory; nothing is regenerated or rewritten.'],
    ]} />
  </div>;
}

export function OriginVocabulary() {
  const [state, setState] = useState<{ phase: 'loading' | 'ready' | 'error'; data?: LoomOrigin; reason?: string }>({ phase: 'loading' });
  useEffect(() => {
    let live = true;
    gateway.loomOrigin()
      .then(data => { if (live) setState({ phase: 'ready', data }); })
      .catch(error => { if (live) setState({ phase: 'error', reason: gatewayReason(error) }); });
    return () => { live = false; };
  }, []);
  if (state.phase === 'loading') return null;
  if (state.phase === 'error') return <Section title="Value origin & freshness" actions={<Badge tone="amber">Unavailable</Badge>}><p className="meta-line">{state.reason}</p></Section>;
  const data = state.data ?? {};
  return <Section title="Value origin & freshness" actions={<Badge>GET /api/v1/loom/origin</Badge>}>
    <div className={`table-scroll${cappedClass((data.origins ?? []).length)}`}><table><thead><tr><th>Origin</th><th>Meaning</th></tr></thead><tbody>
      {(data.origins ?? []).map(origin => <tr key={origin}><th><Badge tone={origin === 'MEASURED' ? 'green' : origin === 'DECLARED' ? 'amber' : 'neutral'}>{origin}</Badge></th><td>{data.origin_meaning?.[origin] ?? '—'}</td></tr>)}
    </tbody></table></div>
    <div className={`table-scroll${cappedClass((data.freshness ?? []).length)}`} style={{ marginTop: 8 }}><table><thead><tr><th>Freshness</th><th>Meaning</th></tr></thead><tbody>
      {(data.freshness ?? []).map(value => <tr key={value}><th><Badge tone={value === 'CURRENT' ? 'green' : 'amber'}>{value}</Badge></th><td>{data.freshness_meaning?.[value] ?? '—'}</td></tr>)}
    </tbody></table></div>
    {!!data.artifact_kinds?.length && <p className="meta-line">Artifact kinds: <span className="mono">{data.artifact_kinds.join(', ')}</span></p>}
  </Section>;
}

// The t3 report tools write dashboard HTML and PNG plots; the gateway enumerates and serves those
// files read-only. Nothing is regenerated or rewritten here, and an empty inventory says which
// command produces each report.
export function GeneratedReports() {
  const [state, setState] = useState<{ phase: 'loading' | 'ready' | 'error'; reports?: GeneratedReport[]; reason?: string }>({ phase: 'loading' });
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ phase: 'loading' });
    gateway.reports()
      .then(data => { if (live) setState({ phase: 'ready', reports: data.reports ?? [] }); })
      .catch(error => { if (live) setState({ phase: 'error', reason: gatewayReason(error) }); });
    return () => { live = false; };
  }, [refresh]);
  const reports = state.reports ?? [];
  return <Section title="Generated reports & plots" actions={<Button onClick={() => setRefresh(value => value + 1)}>Refresh</Button>}>
    {state.phase === 'loading' && <p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading the report inventory…</p>}
    {state.phase === 'error' && <p className="meta-line">Report inventory unavailable: {state.reason}</p>}
    {state.phase === 'ready' && !reports.length && <p className="meta-line">No generated reports yet. Run <code>t3 dashboard</code> for the Plotly dashboard, <code>t3 plot</code> for latency–throughput curves, or <code>visualize_trace.py</code> for a trace report.</p>}
    {state.phase === 'ready' && reports.length > 0 && <>
      <div className="report-grid">
        {reports.map(report => report.media_type === 'text/html'
          ? <a key={report.report_id} className="report-card report-link" href={gateway.reportUrl(report.report_id)} target="_blank" rel="noreferrer">
            <span className="report-kind">{report.kind}</span>
            <strong>{report.title}</strong>
            <span className="meta-line">{bytes(report.size_bytes)} · {stamp(report.modified_at)}</span>
            <span className="report-open">Open report ↗</span>
          </a>
          : <figure key={report.report_id} className="report-card">
            <a href={gateway.reportUrl(report.report_id)} target="_blank" rel="noreferrer"><img src={gateway.reportUrl(report.report_id)} alt={report.title} loading="lazy" /></a>
            <figcaption><strong>{report.title}</strong><span className="meta-line">{report.kind} · {bytes(report.size_bytes)} · {stamp(report.modified_at)}</span></figcaption>
          </figure>)}
      </div>
    </>}
  </Section>;
}

export function LiveExplore({ project, embedded = false, hideRecommendation = false, initialTask = 'recommend', fabricSearch = false }: {
  project: LoadedProject;
  /** The guided flow owns the page shell; embedding drops the extra scroll/pad wrapper. */
  embedded?: boolean;
  /** Show only the bounded project study, without the repository recommendation tab. */
  hideRecommendation?: boolean;
  initialTask?: 'recommend' | 'study';
  /** Compare configurations of the loaded workload, without repository traces. */
  fabricSearch?: boolean;
}) {
  const id = project.detail.project.project_id, revision = project.detail.active_revision_id;
  const { data: caps, error: capError } = useGatewayDocument(`optimization-capabilities:${id}`, gateway.optimizationCapabilities);
  const [parameter, setParameter] = useState('link_width'), [values, setValues] = useState('64,128'), [approved, setApproved] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [metric, setMetric] = useState('completion_cycles');
  const [objectiveClass, setObjectiveClass] = useState('');
  const [advisorNotice, setAdvisorNotice] = useState('');
  const [secondParameter, setSecondParameter] = useState(''), [secondValues, setSecondValues] = useState('');
  const [constraints, setConstraints] = useState<StudyConstraintRow[]>([]);
  const declaredClasses = declaredTrafficClasses(project);
  const validClass = (value: string | undefined) => !value || declaredClasses.includes(value);
  // The backend refuses a duplicate (metric, traffic_class) risk axis, not a
  // repeated metric name: two classes of one metric are distinct constraints.
  const constraintsValid = constraints.every(row => row.threshold.trim() !== '' && Number.isFinite(Number(row.threshold)) && Number(row.threshold) >= 0 && validClass(row.traffic_class)) && new Set(constraints.map(row => `${row.metric}\u0000${row.traffic_class ?? ''}`)).size === constraints.length;
  const [joint, setJoint] = useState(false), [epValues, setEpValues] = useState('2,4');
  const [memory, setMemory] = useState(false);
  const stages = project.request?.compute?.stages ?? [];
  const hasHbm = (project.request?.agents ?? []).some((agent: any) => agent.kind === 'hbm_controller' && agent.count > 0);
  const hasMemory = hasHbm && stages.some((stage: any) => Number(stage.input_bytes) + Number(stage.weight_bytes) + Number(stage.output_bytes) > 0);
  const imported = !!project.request?.workload?.workload_source_ref;
  const key = `srota-study:${id}:${revision}`;
  const [jobId, setJobId] = useState(() => { try { return sessionStorage.getItem(key) ?? ''; } catch { return ''; } });
  const [task, setTask] = useState<'recommend' | 'study'>(() => { try { return sessionStorage.getItem(key) ? 'study' : initialTask; } catch { return initialTask; } });
  const pageRef = useRef<HTMLDivElement>(null);
  const { job, error: jobError, retry, cancel } = useGatewayJob(jobId);
  const optimizationId = (job?.result as any)?.optimization_id;
  const hasStudy = Boolean(project.detail.latest_optimization_study || (project.detail.optimizations?.length ?? 0) > 0);
  const result = useGatewayDocument(`optimization:${optimizationId ?? ''}`, () => optimizationId ? gateway.optimization(optimizationId) : Promise.resolve({}));
  useEffect(() => { setApproved(false); setMemory(false); setJoint(false); setSecondParameter(''); setSecondValues(''); setMetric('completion_cycles'); setObjectiveClass(''); try { const stored = sessionStorage.getItem(key) ?? ''; setJobId(stored); setTask(stored || hideRecommendation ? 'study' : initialTask); } catch { setJobId(''); setTask(hideRecommendation ? 'study' : initialTask); } }, [key, hideRecommendation, initialTask]);
  useEffect(() => { pageRef.current?.scrollTo({ top: 0 }); }, [task]);
  const numbers = values.split(',').map(v => Number(v.trim()));
  const families = values.split(',').map(v => v.trim()).filter(Boolean);
  const epNumbers = epValues.split(',').map(v => Number(v.trim()));
  const guided = (caps?.guided_parameters ?? []).filter((p: any) => p.executable === true && p.qualified_for_certified_optimization === true && (p.kind === 'int' || p.name === 'topology_family'));
  const familyField = guided.find((p: any) => p.name === 'topology_family');
  const currentFamily = project.request?.topology?.kind ?? project.request?.noc_config?.topology_family;
  const comparisonFamilies = fabricComparisonFamilies(familyField?.executable_values ?? [], currentFamily ?? undefined, !!project.request?.topology);
  // Two different reasons disable family comparison: the certified patcher's
  // conversion set, or too few executable families. Name the real one.
  const typedFamilyUnconvertible = !!project.request?.topology && !CONVERTIBLE_FAMILIES.includes(String(currentFamily ?? '').toLowerCase());
  const eligible = fabricSearch
    ? guided.filter((p: any) => p.name === 'link_width' || (p.name === 'topology_family' && comparisonFamilies.length > 1))
    : [...guided, ...(!imported ? caps?.workload_parameters ?? [] : [])];
  useEffect(() => {
    if (!fabricSearch || !caps) return;
    const families = fabricComparisonFamilies(familyField?.executable_values ?? [], currentFamily ?? undefined, !!project.request?.topology);
    setParameter(families.length > 1 ? 'topology_family' : 'link_width');
    setValues(families.length > 1 ? families.join(',') : '64,128');
    setSecondParameter(''); setApproved(false);
  }, [fabricSearch, caps, id, revision, currentFamily]);
  const field = eligible.find((p: any) => p.name === parameter);
  const fabricParameters = eligible.filter((p: any) => (caps?.guided_parameters ?? []).some((guided: any) => guided.name === p.name));
  // Never offer a family the certified patcher cannot substitute for a typed
  // draft: the option would only produce a refused candidate.
  const familyOptions = fabricSearch || (!!project.request?.topology && field?.name === 'topology_family') ? comparisonFamilies : field?.executable_values ?? [];
  const discovery = discoverFabricDomain(caps?.guided_parameters ?? [], project.request ?? {});
  const secondField = fabricParameters.find((p: any) => p.name === secondParameter && p.name !== parameter && p.kind === 'int');
  const secondNumbers = secondValues.split(',').map(value => Number(value.trim()));
  const metrics = studyMetricOptions(caps?.federated_metrics);
  const objective = metrics.find((m: any) => m.metric === metric);
  const objectiveSupportsClass = metricSupportsTrafficClass(objective);
  const declaredClassKey = declaredClasses.join('\u0000');
  useEffect(() => {
    if (!objectiveSupportsClass && objectiveClass) setObjectiveClass('');
    else if (objectiveClass && !declaredClasses.includes(objectiveClass)) setObjectiveClass('');
  }, [objectiveSupportsClass, objectiveClass, declaredClassKey]);
  const prepareFabricComparison = () => {
    setParameter('topology_family'); setValues(comparisonFamilies.join(','));
    setJoint(false); setSecondParameter(''); setMemory(false); setApproved(false); setError(''); setAdvisorNotice(''); setObjectiveClass('');
    setMetric(stages.length > 0 && metrics.some(m => m.metric === 'system_makespan_cycles') ? 'system_makespan_cycles' : 'completion_cycles');
  };
  const prepareDiscovery = () => {
    if (discovery.length !== 2) return;
    setParameter(discovery[0].name); setValues(discovery[0].values.join(','));
    setSecondParameter(discovery[1].name); setSecondValues(discovery[1].values.join(','));
    setJoint(false); setMemory(false); setApproved(false); setError(''); setAdvisorNotice(''); setObjectiveClass('');
    setMetric(stages.length > 0 && metrics.some(m => m.metric === 'system_makespan_cycles') ? 'system_makespan_cycles' : 'completion_cycles');
  };
  const paired = joint && parameter === 'tp';
  const isFamily = parameter === 'topology_family';
  const domain: FabricDomain = [{ name: parameter, values: isFamily ? families : numbers }, ...(paired ? [{ name: 'ep', values: epNumbers }] : []), ...(secondParameter ? [{ name: secondParameter, values: secondNumbers }] : [])];
  const count = domain.reduce((total, axis) => total * axis.values.length, 1);
  const validSizes = (items: number[]) => items.length > 0 && items.every(n => Number.isSafeInteger(n) && n > 0) && new Set(items).size === items.length;
  const demandsPresent = objective?.question === 'SYSTEM_MAKESPAN' ? stages.length > 0 : objective?.question === 'DRAM_TIMING' ? hasMemory : true;
  const valid = constraintsValid && validClass(objectiveClass) && project.draftMeta?.dirty !== true && !!field && !!objective && demandsPresent && (isFamily ? families.length > 0 && new Set(families).size === families.length && families.every(value => (field.executable_values ?? []).includes(value)) : field.kind === 'int' && validSizes(numbers)) && (!paired || validSizes(epNumbers)) && (!secondParameter || (!!secondField && fabricParameters.some((p: any) => p.name === parameter) && !paired && validSizes(secondNumbers))) && count <= 4 && (!memory || hasMemory);
  const prepareAdvisorStudy = (preset: { families: string[]; linkWidths: number[]; priority: string; winner: string; depth: number; note: string }) => {
    const executable = (familyField?.executable_values ?? []) as string[];
    const familiesToUse = preset.families.filter(family => executable.some(value => value.toLowerCase() === family.toLowerCase()));
    if (!familiesToUse.length) {
      setAdvisorNotice(`No recommended family is reported executable by the backend for ${revision}; the advisor shortlist was not applied. The repository comparison remains available above.`);
      return false;
    }
    setParameter('topology_family');
    setValues(familiesToUse.join(','));
    const canSweepWidth = eligible.some((item: any) => item.name === 'link_width');
    setSecondParameter(canSweepWidth && preset.linkWidths.length ? 'link_width' : '');
    setSecondValues(canSweepWidth && preset.linkWidths.length ? preset.linkWidths.join(',') : '');
    setJoint(false); setMemory(false); setApproved(false); setMetric('completion_cycles'); setObjectiveClass(''); setError('');
    setAdvisorNotice(`Advisor shortlist loaded: ${familiesToUse.join(', ')}${canSweepWidth && preset.linkWidths.length ? ` × link width ${preset.linkWidths.join(' / ')}` : ''}. Review the revision and approve before launching.`);
    return true;
  };
  const submit = async () => { if (!revision || !valid || !approved || busy) return; setTask('study'); setBusy(true); setError(''); try {
    const objectives = buildStudyObjectives({ metric, question: objective.question, trafficClass: objectiveSupportsClass ? objectiveClass : '', memory });
    const value = await gateway.optimize(revision, { domain, objectives, constraints: buildStudyConstraints(constraints), method: 'grid', budget: { max_evaluations: count }, seed: 7 });
    if (!value.job_id) throw new Error('Gateway returned no optimization job ID.');
    setJobId(value.job_id); try { sessionStorage.setItem(key, value.job_id); } catch { /* Optional recovery. */ }
  } catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); } };
  return <div className={embedded ? 'flow-embedded explore-page' : 'view-main explore-page'} ref={pageRef}>
    <div className="explore-taskbar">
      {fabricSearch ? <Badge tone="blue">Project workload</Badge> : hideRecommendation
        ? <Badge tone="blue">Bounded study</Badge>
        : <div className="segmented" role="group" aria-label="Explore task">
          <button type="button" className={task === 'recommend' ? 'active' : ''} aria-pressed={task === 'recommend'} onClick={() => setTask('recommend')}>Recommendation</button>
          <button type="button" className={task === 'study' ? 'active' : ''} aria-pressed={task === 'study'} onClick={() => setTask('study')}>Bounded study{count > 0 && <span className="explore-tab-count">{count}</span>}</button>
        </div>}
      <span className="explore-taskbar-note">{task === 'recommend' && !hideRecommendation ? '' : <>Measures <span className="mono">{revision ?? 'no revision'}</span> · at most four configurations</>}</span>
    </div>

    {!hideRecommendation && <div hidden={task !== 'recommend'}>
      <DesignAdvisor project={project} mode="live" ownAssumptions={false}
        executableFamilies={(caps?.guided_parameters ?? []).find((item: any) => item.name === 'topology_family')?.executable_values ?? []}
        onPrepareStudy={(preset) => { if (prepareAdvisorStudy(preset)) setTask('study'); }} />
      <div className="explore-next">
        <div>
          <strong>{revision ? 'Test the shortlist on this revision' : 'Compile a revision before running a study'}</strong>
        </div>
        <div className="actions">
          <PageLink page="analysis/comparison">Compare published runs</PageLink>
          <Button primary={!!revision} disabled={!revision} onClick={() => setTask('study')}>Open bounded study</Button>
        </div>
      </div>
    </div>}

    <div hidden={!hideRecommendation && task !== 'study'} id="bounded-study">
      {advisorNotice && <Notice tone="blue">{advisorNotice}</Notice>}
      <Section title={fabricSearch ? 'Compare fabric configurations' : 'Bounded project study'} actions={<Badge tone={count > 4 ? 'amber' : 'neutral'}>{count} {count === 1 ? 'configuration' : 'configurations'}</Badge>}>
        {fabricSearch && comparisonFamilies.length < 2 && <Notice tone="amber">Family switching needs a complete topology declaration for {currentFamily ?? 'this fabric'}. Compare link widths here, or <PageLink page="flow/tune">edit the fabric</PageLink>.</Notice>}
        {!fabricSearch && <div className="study-presets">
          <span className="study-presets-label">Start from</span>
          <Button disabled={!revision || project.draftMeta?.dirty === true || discovery.length !== 2 || busy || (!!jobId && (!job || !terminal(job)))} onClick={prepareDiscovery}>Prepare multi-knob discovery</Button>
          <Button disabled={!revision || project.draftMeta?.dirty === true || comparisonFamilies.length < 2 || busy || (!!jobId && (!job || !terminal(job)))} onClick={prepareFabricComparison}>Prepare fabric comparison</Button>
          {comparisonFamilies.length < 2 && <Notice tone="amber">{typedFamilyUnconvertible ? `The certified patcher substitutes only mesh, concentrated mesh and torus; family comparison is unavailable for ${currentFamily}.` : 'The certified backend reports fewer than two executable families; fabric comparison is unavailable for this revision.'}</Notice>}
          {discovery.length !== 2 && <Notice tone="amber">Multi-knob discovery needs exactly two executable fabric knobs.</Notice>}
        </div>}

        <div className="study-workbench">
          <div className="study-builder">
            <section className="study-step" aria-labelledby="study-knobs">
              <div className="study-step-head"><h3 id="study-knobs">Knobs</h3><span>What varies across runs</span></div>
              {capError && <Notice tone="red">{capError}</Notice>}
              <div className="form-grid"><Field label={fabricSearch ? 'Compare by' : 'Study parameter (validated per candidate)'}><select value={parameter} onChange={e => { const next = eligible.find((p: any) => p.name === e.target.value); setParameter(e.target.value); setSecondParameter(''); setValues(e.target.value === 'topology_family' && fabricSearch ? comparisonFamilies.join(',') : defaultStudyValues(e.target.value, next)); setApproved(false); }}>{eligible.map((p: any) => <option key={p.name} value={p.name}>{fabricSearch ? p.name === 'topology_family' ? 'Fabric family' : 'Link width (bits)' : p.name}</option>)}</select></Field><ValueEditor label="Values to test" values={values} onChange={next => { setValues(next); setApproved(false); }} kind={field?.kind === 'enum' ? 'enum' : 'int'} options={familyOptions} suggestions={studyValueSuggestions(parameter)} /></div>
              {parameter === 'tp' && <><label className="check-row"><input type="checkbox" checked={joint} onChange={e => { setJoint(e.target.checked); setApproved(false); }} />Also sweep EP (Cartesian grid, at most four configurations total)</label>{joint && <ValueEditor label="EP values" values={epValues} onChange={next => { setEpValues(next); setApproved(false); }} kind="int" suggestions={[1, 2, 4, 8]} />}</>}
              {fabricParameters.some((p: any) => p.name === parameter) && <div className="form-grid" hidden={fabricSearch && !fabricParameters.some((p: any) => p.kind === 'int' && p.name !== parameter)}><Field label="Second fabric knob (optional)"><select value={secondParameter} onChange={e => { setSecondParameter(e.target.value); setSecondValues(e.target.value ? defaultStudyValues(e.target.value, fabricParameters.find((p: any) => p.name === e.target.value)) : ''); setApproved(false); }}><option value="">None · single-knob study</option>{fabricParameters.filter((p: any) => p.kind === 'int' && p.name !== parameter).map((p: any) => <option key={p.name}>{p.name}</option>)}</select></Field>{secondParameter && <ValueEditor label="Second knob values" values={secondValues} onChange={next => { setSecondValues(next); setApproved(false); }} kind="int" suggestions={studyValueSuggestions(secondParameter)} />}</div>}
              {field?.reason && <details className="study-inline-details"><summary>Why these {isFamily ? 'families' : 'values'} are available</summary><p className="meta-line">{field.reason}</p></details>}
              {imported && <Notice tone="amber">Imported trace: decomposition sweeps are unavailable. Author canonical collectives to change TP/EP.</Notice>}
            </section>

            <section className="study-step" aria-labelledby="study-objective">
              <div className="study-step-head"><h3 id="study-objective">Objective</h3><span>What the backend minimizes</span></div>
              <div className="form-grid">
                <Field label="Study objective"><select aria-label="Study objective" value={metric} onChange={e => { setMetric(e.target.value); setObjectiveClass(''); setApproved(false); }}>{metrics.map((m: any) => <option key={m.metric} value={m.metric}>{studyMetricLabel(m, fabricSearch)}</option>)}</select></Field>
                {objectiveSupportsClass && <Field label="Objective traffic class"><TrafficClassSelect label="Objective traffic class" value={objectiveClass} classes={declaredClasses} onChange={next => { setObjectiveClass(next); setApproved(false); }} />{!declaredClasses.length && <small className="meta-line">This revision declares no workload traffic class; the aggregate reading is the only choice.</small>}</Field>}
              </div>
              <details open={fabricSearch ? undefined : true}>
              <summary>Optional · Memory objective & constraints</summary>
              <label className="check-row"><input type="checkbox" checked={memory} disabled={!hasMemory || !(caps?.federated_metrics ?? []).some((m: any) => m.metric === 'average_read_latency_cycles' && m.optimization_eligible)} onChange={e => { setMemory(e.target.checked); setApproved(false); }} />Include independent DRAM timing objective</label>
              {!demandsPresent && <Notice tone="amber">Declare compute stages in Workloads; DRAM timing also requires memory operands and an HBM controller in the design.</Notice>}
              <div className="study-constraints">
                <div className="study-step-head"><h3>Study metric constraints</h3><span>Optional hard filters</span></div>
                {constraints.map((row, index) => {
                  const rowMetric = metrics.find((item: any) => item.metric === row.metric);
                  return <div className="study-constraint-row" key={index}><select aria-label={`Constraint ${index + 1} metric`} value={row.metric} onChange={e => { const next = metrics.find((item: any) => item.metric === e.target.value); setConstraints(rows => rows.map((item, i) => i === index ? { ...item, metric: e.target.value, traffic_class: metricSupportsTrafficClass(next) ? item.traffic_class ?? '' : '' } : item)); setApproved(false); }}>{metrics.map((item: any) => <option key={item.metric} value={item.metric}>{item.metric}{studyMetricUnit(item) ? ` · ${studyMetricUnit(item)}` : ''}</option>)}</select>
                    {metricSupportsTrafficClass(rowMetric) && <TrafficClassSelect label={`Constraint ${index + 1} traffic class`} value={row.traffic_class ?? ''} classes={declaredClasses} onChange={next => { setConstraints(rows => rows.map((item, i) => i === index ? { ...item, traffic_class: next } : item)); setApproved(false); }} />}
                    <select aria-label={`Constraint ${index + 1} operator`} value={row.op} onChange={e => { setConstraints(rows => rows.map((item, i) => i === index ? { ...item, op: e.target.value as '<=' | '>=' } : item)); setApproved(false); }}><option value="<=">≤</option><option value=">=">≥</option></select><input aria-label={`Constraint ${index + 1} threshold`} type="number" min="0" value={row.threshold} onChange={e => { setConstraints(rows => rows.map((item, i) => i === index ? { ...item, threshold: e.target.value } : item)); setApproved(false); }} /><Button onClick={() => { setConstraints(rows => rows.filter((_, i) => i !== index)); setApproved(false); }}>Remove</Button></div>;
                })}
                <Button disabled={constraints.length >= metrics.length} onClick={() => { const next = metrics.find((item: any) => !constraints.some(row => row.metric === item.metric)); if (next) setConstraints(rows => [...rows, { metric: next.metric, op: '<=', threshold: '', traffic_class: '' }]); setApproved(false); }}>+ Add constraint</Button>
                {!constraintsValid && <Notice tone="amber">Enter a non-negative finite threshold and use each metric only once.</Notice>}
              </div>
              </details>
            </section>
          </div>

          <aside className="study-preview" aria-label="Study run preview">
            <div className="study-preview-head"><h3>Run preview</h3><Badge tone={count > 4 ? 'amber' : 'neutral'}>{count}/4</Badge></div>
            {count <= 4 && <div className="table-scroll"><table aria-label="Declared candidate configurations"><thead><tr><th>Candidate</th><th>Parameter values</th><th>State</th></tr></thead><tbody>{fabricGrid(domain).map((patch, index) => <tr key={index}><th className="mono">C{index + 1}</th><td className="mono">{Object.keys(patch).join(' · ')} = {Object.values(patch).join(' / ')}</td><td><Badge tone="amber">Not evaluated</Badge></td></tr>)}</tbody></table></div>}
            {count > 4 && <Notice tone="amber">This grid has {count} configurations. Reduce the values to at most four total.</Notice>}
            {project.draftMeta?.dirty === true && <Notice tone="amber">Save and compile the draft before launching a study so the displayed demand matches its revision.</Notice>}
            <div className="study-approve">
              <label className="check-row"><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} />Approve this revision, objective, and {count} configurations to run real backends.</label>
              <Button primary disabled={!revision || !valid || !approved || busy || (!!jobId && (!job || !terminal(job)))} onClick={submit}>{busy ? 'Submitting…' : fabricSearch ? 'Search project fabrics' : 'Launch bounded study'}</Button>
              {(error || jobError) && <Notice tone="red">{error || jobError}</Notice>}{jobError && <Button onClick={retry}>Retry job status</Button>}
            </div>
          </aside>
        </div>
      </Section>

      {job && (!terminal(job) || !optimizationId) && <Section title="Study job" actions={<Badge tone={job.state === 'FAILED' || job.state === 'REFUSED' ? 'red' : 'blue'}>{job.state}</Badge>}><Properties rows={[[ 'Job', job.job_id ], ['Error', job.error_message ?? 'None reported' ]]} />{!terminal(job) && <Button disabled={!job.cancellable} onClick={cancel}>Cancel study</Button>}</Section>}
      {optimizationId && <Section title="Backend study results" actions={job ? <Badge tone={job.state === 'COMPLETED' ? 'green' : 'amber'}>{job.state}</Badge> : undefined}>{result.data ? <>
        <ClassScopedStudyResults study={result.data} />
        <CandidateEvidence study={result.data} stale={project.draftMeta?.dirty === true || (!!result.data.base_revision_id && result.data.base_revision_id !== revision)} />
        <Button onClick={() => downloadJson(`${optimizationId}.json`, result.data)}>Download study results</Button><details><summary>Raw study record</summary><pre className="code-preview">{JSON.stringify(result.data, null, 2)}</pre></details></> : <DocumentState error={result.error} />}</Section>}
      {hasStudy && <StudyWorkbench project={project} studyId={optimizationId} title="Study analysis" />}
      {optimizationId && result.data && <StudyAdoption key={`${optimizationId}:${project.draftMeta?.revisionToken}`} project={project} study={result.data} />}
      {jobId && <JobEvents key={jobId} jobId={jobId} state={job?.state} />}

      {!fabricSearch && <div className="explore-next">
        <div><strong>Need the repository comparison?</strong></div>
        <div className="actions"><PageLink page="analysis/comparison">Compare published runs</PageLink>{!hideRecommendation && <Button onClick={() => setTask('recommend')}>Back to recommendation</Button>}</div>
      </div>}
    </div>
    <Assumptions rows={[
      ['Source', 'Measured candidates come from backend runs launched by the bounded study; repository recommendation traces are separate evidence.'],
      ['Candidates', 'Each candidate is a study input, never an adopted design. Nothing is measured until launch; backend refusal is not a zero-valued result.'],
      ['Budget', 'At most four configurations per study.'],
      ['Scopes', 'Network, system and memory cycles retain their own scope. Power and PDP are unavailable; no power authority is attached.'],
      ['Workload sweeps', 'Workload sweeps rebuild collective groups; compute and memory stay as authored.'],
      ['Recommendation', 'The advisor replays repository traces. Only the bounded study measures the loaded revision.'],
      ['Advisor evidence', 'Latency, hops and throughput are measured; power and area are derived from the native 32 nm model, per-endpoint scaled from a 16-endpoint reference. The adapter recommends topology and measured buffer depth, not a link width, and claims no project-revision performance, transaction P95, DRAM timing or qualification.'],
      ['Advisor shortlist', 'Loading a shortlist defines a study, not a measurement. A recommended buffer depth applies to the next draft; buffer depth is not a study dimension.'],
      ['Families', 'Executable families are validated by the backend; executable does not guarantee workload compatibility.'],
      ['Constraints', 'Study metric constraints use each metric’s own cycles and are separate from the advisor’s repository-evidence bounds.'],
    ]} />
  </div>;
}
