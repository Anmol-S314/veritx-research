import { useEffect, useState } from 'react';
import { gateway, gatewayReason, type OptimizationStudyCandidate, type OptimizationView } from './gateway';
import { num } from './format';
import type { LoadedProject } from './project';
import { AnalysisWorkbench } from './AnalysisWorkbench';
import type { WorkbenchMetric, WorkbenchObservation, WorkbenchPreset, WorkbenchView } from './analysisWorkbench';
import { Assumptions, Badge, Empty, Notice, PageLink, Section } from './ui';

const metricLabel = (metric: string): string => metric.replaceAll('_', ' ');
const metricUnit = (metric: string): string => /cycles/.test(metric) ? 'cycles' : /latency/.test(metric) ? 'cycles' : /throughput|bandwidth/.test(metric) ? 'GB/s' : '';
const PARAM_LABEL: Record<string, string> = {
  link_width: 'Link width',
  input_buffer_depth_flits_per_vc: 'Buffer depth',
  concentration: 'Concentration',
  radix: 'Radix',
  topology_family: 'Topology',
  arbitration: 'Arbitration',
};
const PARAM_UNIT: Record<string, string> = { link_width: ' b', input_buffer_depth_flits_per_vc: ' flits', radix: '' };
const patchLabel = (patch: Record<string, unknown> | undefined): string =>
  patch && Object.keys(patch).length
    ? Object.entries(patch).map(([key, value]) => `${PARAM_LABEL[key] ?? metricLabel(key)} ${String(value)}${PARAM_UNIT[key] ?? ''}`).join(' · ')
    : 'baseline';
const shortRevision = (id: string | undefined): string => id ? id.split('-').filter(Boolean).slice(-1)[0] : 'not reported';
const consequenceLabel = (locked: Record<string, unknown> | undefined): string => {
  if (!locked) return '—';
  const parts: string[] = [];
  if (typeof locked.router_count === 'number') parts.push(`${locked.router_count} routers`);
  if (typeof locked.vc_count === 'number') parts.push(`${locked.vc_count} VC${locked.vc_count === 1 ? '' : 's'}`);
  if (Array.isArray(locked.routing_classes) && locked.routing_classes.length) parts.push(locked.routing_classes.join('/'));
  if (typeof locked.topology_family === 'string') parts.push(locked.topology_family);
  return parts.length ? parts.join(' · ') : '—';
};
const measured = (candidate: OptimizationStudyCandidate, metric: string): number | null => {
  const value = candidate.objective_values?.[metric];
  return candidate.objective_availability?.[metric] === 'MEASURED' && typeof value === 'number' ? value : null;
};
const definitionOf = (study: OptimizationView) => study.definition ?? study.study?.definition;
const domainParams = (definition: ReturnType<typeof definitionOf>) => {
  const domain = definition?.domain;
  return Array.isArray(domain) ? domain : Object.entries(domain ?? {}).map(([name, values]) => ({ name, values }));
};
const candidateNames = (study: OptimizationView): Map<string, string> => {
  const candidates = [...(study.study?.candidates ?? [])];
  const domain = domainParams(definitionOf(study))[0];
  const sorted = [...candidates].sort((a, b) => {
    const av = domain ? a.guided_patch?.[domain.name] : undefined;
    const bv = domain ? b.guided_patch?.[domain.name] : undefined;
    if (typeof av === 'number' && typeof bv === 'number') return av - bv;
    return String(av ?? '').localeCompare(String(bv ?? ''));
  });
  return new Map(sorted.map((candidate, index) => [candidate.candidate_id, `C${index + 1}`]));
};
function objectiveKeys(study: OptimizationView): string[] {
  const declared = (definitionOf(study)?.objectives ?? []).map(objective => objective.metric);
  const present = [...new Set((study.study?.candidates ?? []).flatMap(candidate => Object.keys(candidate.objective_values ?? {})))];
  return [...new Set([...declared, ...present])];
}
function primaryDirection(study: OptimizationView, metric: string): string {
  return definitionOf(study)?.objectives?.find(objective => objective.metric === metric)?.direction ?? 'MIN';
}
const selectionId = (study: OptimizationView): string | null => study.study?.selected_candidate_id ?? study.selected_candidate_id ?? null;

function StudySummary({ study }: { study: OptimizationView }) {
  const metrics = objectiveKeys(study);
  const metric = metrics[0];
  const names = candidateNames(study);
  const candidates = study.study?.candidates ?? [];
  if (!metric) return null;
  const rows = candidates.map(candidate => ({ candidate, value: measured(candidate, metric) }))
    .filter((row): row is typeof row & { value: number } => row.value !== null);
  if (!rows.length) return null;
  const direction = primaryDirection(study, metric);
  const unit = metricUnit(metric);
  const best = rows.reduce((a, b) => direction === 'MAX' ? (b.value > a.value ? b : a) : (b.value < a.value ? b : a));
  const worst = rows.reduce((a, b) => direction === 'MAX' ? (b.value < a.value ? b : a) : (b.value > a.value ? b : a));
  const diff = Math.abs(worst.value - best.value);
  const percent = best.value ? 100 * diff / Math.abs(best.value) : 0;
  const selected = rows.find(row => row.candidate.candidate_id === selectionId(study)) ?? best;
  const verdicts = selected.candidate.product_requirements?.verdicts ?? [];
  const binding = verdicts.find(verdict => verdict.binding && typeof verdict.required === 'number' && typeof verdict.measured === 'number');
  const headroom = binding && typeof binding.required === 'number' && typeof binding.measured === 'number' ? binding.required - binding.measured : null;
  const pareto = rows.filter(row => (study.study?.pareto_ids ?? []).includes(row.candidate.candidate_id) || row.candidate.pareto_member).length;
  return <div className="study-summary">
    <div><span>Best measured</span><strong>{names.get(best.candidate.candidate_id) ?? 'Candidate'} · {num(best.value)} {unit}</strong><small>{patchLabel(best.candidate.guided_patch)}</small></div>
    <div><span>Spread vs best</span><strong>{rows.length === 1 ? 'No alternative' : `${num(diff)} ${unit} · +${percent.toFixed(1)}%`}</strong><small>{rows.length === 1 ? 'One measured candidate' : `${names.get(worst.candidate.candidate_id) ?? 'Other candidate'} is the furthest tested value`}</small></div>
    <div><span>Non-dominated</span><strong>{pareto} of {rows.length}</strong><small>{metrics.length === 1 ? 'Single objective; ranking only' : `${metrics.length} declared objectives`}</small></div>
    <div><span>{binding?.traffic_class ?? 'Binding requirement'}</span><strong>{binding && headroom !== null ? `${binding.verdict ?? 'Reported'} · ${num(headroom)} ${unit} headroom` : 'No numeric binding requirement'}</strong><small>{binding ? `${num(binding.measured)} measured / ${num(binding.required)} allowed` : 'See candidate verdicts below'}</small></div>
  </div>;
}

function StudyCandidatesTable({ study }: { study: OptimizationView }) {
  const names = candidateNames(study);
  const metrics = objectiveKeys(study);
  const metric = metrics[0];
  const direction = metric ? primaryDirection(study, metric) : 'MIN';
  const unit = metric ? metricUnit(metric) : '';
  const candidates = study.study?.candidates ?? [];
  const measuredValues = candidates.map(candidate => metric ? measured(candidate, metric) : null).filter((value): value is number => value !== null);
  const bestValue = measuredValues.length ? (direction === 'MAX' ? Math.max(...measuredValues) : Math.min(...measuredValues)) : null;
  return <div className="table-scroll"><table aria-label="Study candidates"><thead><tr><th>Configuration</th><th>Measured result</th><th>Δ vs best</th><th>Fabric</th><th>Requirements</th><th>Status</th><th>Result</th></tr></thead><tbody>
    {candidates.map(candidate => {
      const selected = selectionId(study) === candidate.candidate_id;
      const front = (study.study?.pareto_ids ?? []).includes(candidate.candidate_id) || candidate.pareto_member;
      const verdicts = candidate.product_requirements?.verdicts ?? [];
      const value = metric ? measured(candidate, metric) : null;
      const diff = value !== null && bestValue !== null ? Math.abs(value - bestValue) : null;
      const percent = diff !== null && bestValue ? 100 * diff / Math.abs(bestValue) : 0;
      return <tr key={candidate.candidate_id} className={selected ? 'selected' : undefined}>
        <th>{names.get(candidate.candidate_id) ?? 'Candidate'}<small className="block">{patchLabel(candidate.guided_patch)}</small></th>
        <td>{metrics.map(key => {
          const result = measured(candidate, key);
          return <span className="block mono" key={key}>{metricLabel(key)}: {result === null ? 'Not measured' : `${num(result)} ${metricUnit(key)}`}</span>;
        })}</td>
        <td className="numeric">{value === null ? '—' : diff === 0 ? 'best' : `+${num(diff)} ${unit}${percent ? ` (${percent.toFixed(1)}%)` : ''}`}</td>
        <td><small>{consequenceLabel(candidate.locked_consequences)}</small></td>
        <td>{verdicts.length ? verdicts.map((verdict, index) => <span className="block" key={`${verdict.traffic_class ?? index}-${verdict.verdict ?? ''}`} title={verdict.reason}>
          <Badge tone={verdict.verdict === 'SATISFIED' ? 'green' : verdict.verdict === 'VIOLATED' ? 'red' : 'amber'}>{verdict.verdict ?? 'Not reported'}</Badge>{' '}<small>{verdict.traffic_class ?? verdict.qos_class ?? ''}</small>
        </span>) : '—'}</td>
        <td>{candidate.evaluation_status === 'EVALUATED' ? 'Measured' : candidate.evaluation_status ?? 'Not reported'}<small className="block">{candidate.compilation_status ?? candidate.evaluation_authority ?? ''}</small></td>
        <td>{front && <Badge tone="blue">front</Badge>} {selected && <Badge tone="green">selected</Badge>}{!front && !selected && '—'}</td>
      </tr>;
    })}
  </tbody></table></div>;
}

function useOptimizationStudy(project: LoadedProject, preferredStudyId?: string) {
  const summaries = project.detail.optimizations ?? [];
  const latest = project.detail.latest_optimization_study ?? summaries[0] ?? null;
  const [studyId, setStudyId] = useState(preferredStudyId || latest?.optimization_id || '');
  const [study, setStudy] = useState<OptimizationView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const next = preferredStudyId || project.detail.latest_optimization_study?.optimization_id || project.detail.optimizations?.[0]?.optimization_id || '';
    setStudyId(next);
    setStudy(null);
    setError('');
  }, [project.detail.project.project_id, project.detail.latest_optimization_study?.optimization_id, preferredStudyId]);

  useEffect(() => {
    if (!studyId) { setLoading(false); return; }
    let live = true;
    setLoading(true);
    setError('');
    setStudy(null);
    gateway.optimization(studyId)
      .then(value => { if (live) setStudy(value); })
      .catch(reason => { if (live) { setStudy(null); setError(gatewayReason(reason)); } })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [studyId]);

  return { summaries, latest, studyId, setStudyId, study, loading, error };
}

export function StudyWorkbench({ project, studyId: preferredStudyId, title = 'Measured optimization study' }: { project: LoadedProject; studyId?: string; title?: string }) {
  const { summaries, latest, studyId, setStudyId, study, loading, error } = useOptimizationStudy(project, preferredStudyId);
  if (!summaries.length && !latest) {
    return <Section title={title}>
      <Notice tone="amber"><strong>No measured optimization study for this project.</strong> <PageLink page="explore/brief">Open bounded study</PageLink></Notice>
      <Assumptions rows={[
        ['Source', 'Repository sweep charts are independent reference experiments, not this project.'],
        ['Project study', 'Candidate results for this project come from a bounded study.'],
      ]} />
    </Section>;
  }
  if (loading) return <Section title={title}><p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading measured study…</p></Section>;
  if (error) return <Section title={title}><Notice tone="red">{error}</Notice><Assumptions rows={[['Source', 'Optimization study document from the project gateway; no candidate values are shown while it is unavailable.']]} /></Section>;
  if (!study) return <Section title={title}><Empty title="No study selected">Pick an optimization study for this project.</Empty><Assumptions rows={[['Source', 'Optimization study document from the project gateway.']]} /></Section>;

  const candidates = study.study?.candidates ?? [];
  const names = candidateNames(study);
  const rationale = study.study?.selection_rationale
    ? [...names].reduce((text, [id, label]) => text.replaceAll(id, label), study.study.selection_rationale).replaceAll('_', ' ')
    : null;
  const objectives = objectiveKeys(study);
  const measuredCount = candidates.filter(candidate => objectives.some(key => measured(candidate, key) !== null)).length;
  const domains = domainParams(definitionOf(study));
  const numericDomains = domains.filter(domain => domain.values.length > 0 && domain.values.every(value => typeof value === 'number'));
  const paretoIds = new Set(study.study?.pareto_ids ?? candidates.filter(candidate => candidate.pareto_member).map(candidate => candidate.candidate_id));
  const chosen = selectionId(study);
  const studyPicker = summaries.length > 1 ? <label className="field inline-field"><span>Optimization study</span><select aria-label="Optimization study" value={studyId} onChange={event => setStudyId(event.target.value)}>{summaries.map((summary, index) => <option key={summary.optimization_id} value={summary.optimization_id}>Study {index + 1} · {summary.candidate_count ?? '—'} candidates</option>)}</select></label> : undefined;

  // A single measured point cannot support a Pareto front or a parameter
  // comparison. Keep the study's coverage visible without drawing an empty
  // chart or promoting a non-member to "best".
  if (measuredCount < 2) {
    return <Section title={title} actions={<><Badge tone="blue">{summaries.length || 1} {summaries.length === 1 ? 'study' : 'studies'}</Badge><Badge>{candidates.length} candidates</Badge><Badge tone="amber">{measuredCount} measured</Badge></>}>
      {studyPicker && <div className="wb-context">{studyPicker}</div>}
      <Notice tone="amber"><strong>{candidates.length ? 'No comparable measured candidates.' : 'No candidates recorded.'}</strong>{' '}{candidates.length ? `${measuredCount} of ${candidates.length} candidates ${measuredCount === 1 ? 'has' : 'have'} a measured objective value.` : ''}</Notice>
      {rationale && <p className="meta-line">Selection: {rationale}</p>}
      {candidates.length > 0 && <details className="plot-data"><summary>Study candidates · {candidates.length}</summary><StudyCandidatesTable study={study} /></details>}
      <Assumptions rows={[
        ['Objectives', `The study declares ${objectives.length} ${objectives.length === 1 ? 'objective' : 'objectives'}. A chart needs at least two measured candidates.`],
        ['Pareto membership', 'Decided by the study contract, not this page.'],
      ]} />
    </Section>;
  }

  const metrics: WorkbenchMetric[] = [
    ...objectives.map(key => ({ key, label: metricLabel(key), unit: metricUnit(key), direction: primaryDirection(study, key) === 'MAX' ? 'MAX' as const : 'MIN' as const, digits: 3 })),
    ...numericDomains.map(domain => ({ key: `param:${domain.name}`, label: PARAM_LABEL[domain.name] ?? metricLabel(domain.name), digits: 0 })),
    { key: 'candidate_index', label: 'Candidate order', digits: 0 },
  ];
  const observations: WorkbenchObservation[] = candidates.map((candidate, index) => {
    const front = paretoIds.has(candidate.candidate_id);
    const selected = chosen === candidate.candidate_id;
    const verdicts = candidate.product_requirements?.verdicts ?? [];
    const values: Record<string, number | null> = { candidate_index: index + 1 };
    for (const key of objectives) values[key] = measured(candidate, key);
    for (const domain of numericDomains) {
      const value = candidate.guided_patch?.[domain.name];
      values[`param:${domain.name}`] = typeof value === 'number' ? value : null;
    }
    const missing = objectives.length > 0 && objectives.every(key => measured(candidate, key) === null);
    const excluded = candidate.evaluation_status && candidate.evaluation_status !== 'EVALUATED'
      ? `Not evaluated: ${candidate.evaluation_status}`
      : missing ? 'No measured objective value' : undefined;
    return {
      id: candidate.candidate_id,
      label: names.get(candidate.candidate_id) ?? `C${index + 1}`,
      sublabel: `${patchLabel(candidate.guided_patch)}${selected ? ' · selected by the study' : ''}`,
      values,
      front,
      excluded,
      tone: front ? 'green' : undefined,
      meta: [
        ['Configuration', patchLabel(candidate.guided_patch)],
        ['Study selection', selected ? 'Selected by the study' : 'Not selected'],
        ['Evaluation status', candidate.evaluation_status ?? 'Not reported'],
        ['Authority', candidate.evaluation_authority ?? 'Not reported'],
        ['Compilation', candidate.compilation_status ?? 'Not reported'],
        ['Fabric consequence', consequenceLabel(candidate.locked_consequences)],
        ...(verdicts.length ? verdicts.map((verdict, verdictIndex) => [`Requirement ${verdict.traffic_class ?? verdictIndex + 1}`, `${verdict.verdict ?? 'Not reported'} · ${num(verdict.measured)} measured / ${num(verdict.required)} allowed`] as [string, string]) : []),
        ...(candidate.eligibility_reason ? [['Eligibility reason', candidate.eligibility_reason] as [string, string]] : []),
      ],
      note: front ? 'Marked non-dominated by the study contract.' : 'Not a member of the study Pareto set.',
    };
  });

  const objective0 = objectives[0];
  const objective1 = objectives[1];
  const param0 = numericDomains[0] ? `param:${numericDomains[0].name}` : null;
  const defaultX = objective1 ? objective0 : param0 ?? 'candidate_index';
  const defaultY = objective0 ?? param0 ?? 'candidate_index';
  const plottedCount = observations.filter(observation => !observation.excluded).length;
  const view: WorkbenchView = {
    id: 'candidates', label: 'Study candidates', chartTitle: 'Study candidates',
    metrics, observations: objective0 ? observations : [], mode: 'scatter', frontMode: 'authoritative',
    defaultX, defaultY, eligibleLabel: 'measured', picker: 'observations', barSort: 'value',
    note: `${paretoIds.size} of ${plottedCount} measured candidates are marked non-dominated by the study.`,
    emptyMessage: 'The study carries no candidate with the plotted objectives measured.',
  };
  const presets: WorkbenchPreset[] = [];
  if (objective0 && objective1) presets.push({ id: 'tradeoff', label: 'Trade-off', view: 'candidates', x: objective0, y: objective1, hint: 'Two measured study objectives' });
  if (objective0 && param0) presets.push({ id: 'parameter', label: 'Parameter sweep', view: 'candidates', x: param0, y: objective0, hint: 'Declared parameter against a measured objective' });
  if (objective0) presets.push({ id: 'ranking', label: 'Ranking', view: 'candidates', x: 'candidate_index', y: objective0, mode: 'bars', hint: 'Measured candidates ordered by the objective' });
  const defaultPreset = presets.find(preset => preset.id === (objective1 ? 'tradeoff' : param0 ? 'parameter' : 'ranking'))?.id ?? presets[0]?.id;
  const single = objectives.length < 2;

  return <AnalysisWorkbench
    title={title}
    source={{ label: 'Backend-measured study', text: <>Backend-measured candidate study. {candidates.length} configurations of {domains.map(domain => `${PARAM_LABEL[domain.name] ?? metricLabel(domain.name)} ${domain.values.join(' / ')}`).join('; ') || 'declared parameters'} on revision {shortRevision(study.base_revision_id)}. Objective values belong to this study; the Repository sweep is a separate evidence source.</> }}
    badges={<><Badge tone="blue">{summaries.length || 1} {summaries.length === 1 ? 'study' : 'studies'}</Badge><Badge>{candidates.length} candidates</Badge></>}
    context={studyPicker}
    notice={<>
      {!objective0 && <Notice tone="amber"><strong>No declared objective metric.</strong> Candidates remain listed below.</Notice>}
    </>}
    summary={<><StudySummary study={study} />{rationale && <p className="meta-line">Selection: {rationale}</p>}</>}
    views={[view]}
    presets={presets}
    defaultPreset={defaultPreset}
    tableSummary={`Study candidates · ${candidates.length}`}
    table={<StudyCandidatesTable study={study} />}
    assumptions={[
      ['Coverage', `${candidates.length} candidates; ${plottedCount} plotted. ${metrics.length} selectable axes.`],
      ['Plot', single && objective0 ? `Single declared objective (${objective0}). The ranking plots measured candidates; there is no 2D trade-off.` : `${objectives.length} declared objectives.`],
      ['Pareto membership', 'Decided by the study contract, not this page. Inspecting a point does not adopt or change the selected candidate.'],
      ['Missing values', 'A candidate without a measured objective value is excluded from the plot and never interpolated.'],
    ]}
  />;
}
