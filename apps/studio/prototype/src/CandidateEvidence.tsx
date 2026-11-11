import { useState } from 'react';
import { rankMeasured, recommendationGap, candidateNames, shortDigest } from './recommendation';
import { Badge, Section } from './ui';

export function CandidateEvidence({ study, stale = false }: { study: Record<string, any>; stale?: boolean }) {
  const candidates = study.study?.candidates ?? [];
  const [selected, setSelected] = useState('');
  const candidate = candidates.find((row: any) => row.candidate_id === selected) ?? candidates[0];
  if (!candidate) return null;
  const names = candidateNames(study);
  const metrics = [...new Set<string>(candidates.flatMap((row: any) => Object.keys(row.objective_values ?? {})))];
  const definition = study.definition ?? study.study?.definition;
  const objectives = definition?.objectives ?? [];
  const objective = objectives[0];
  const ranked = objective && objectives.length === 1 ? rankMeasured(candidates, objective.metric, objective.direction, (definition?.constraints ?? []).map((row: any) => row.metric)) : [];
  const tied = ranked.length > 1 && ranked[0].objective_values![objective.metric] === ranked[1].objective_values![objective.metric];
  const tone = stale ? 'amber' : ranked.length ? 'green' : 'amber';
  return <Section title="Measured outcome" actions={<Badge tone={tone}>{stale ? 'Historical inputs' : ranked.length ? 'Measured' : 'No eligible candidate'}</Badge>}>
    <p><strong>{stale ? 'These results belong to an earlier input snapshot' : ranked.length ? tied ? 'Leading candidates are tied' : `Recommended in this evaluated set: ${names.get(ranked[0].candidate_id) ?? 'the leading candidate'}` : objectives.length > 1 ? 'Multiple objectives · inspect the backend Pareto set' : 'No candidate satisfies every declared hard constraint.'}</strong></p>
    <p>{ranked.length ? `${objective.direction === 'MAX' ? 'Highest' : 'Lowest'} measured ${objective.metric} among ${ranked.length} eligible configurations satisfying all declared hard constraints.` : objective ? recommendationGap(candidates, objective.metric) : 'This study declares no comparable single objective; inspect the backend Pareto set.'}</p>
    {!stale && ranked.length > 1 && !tied && <p>Runner-up: {names.get(ranked[1].candidate_id) ?? 'the next candidate'} · absolute difference {Math.abs(ranked[1].objective_values![objective.metric] - ranked[0].objective_values![objective.metric]).toLocaleString()} in the objective’s declared unit.</p>}
    <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Parameter values</th><th>Compilation</th><th>Evaluation</th>{metrics.map(metric => <th key={metric}>{metric}</th>)}</tr></thead><tbody>
      {candidates.map((row: any, index: number) => <tr key={row.candidate_id} className={row === candidate ? 'selected' : ''}>
        <th><button className="text-button mono" aria-pressed={row === candidate} onClick={() => setSelected(row.candidate_id)}>{names.get(row.candidate_id) ?? `C${index + 1}`}</button></th>
        <td className="mono">{Object.entries(row.guided_patch ?? {}).map(([key, value]) => `${key} ${value}`).join(' · ') || 'baseline'}</td>
        <td>{row.compilation_status ?? 'Not reported'}{(row.eligibility_reason ?? row.evaluation_reason) && <div className="meta-line">{row.eligibility_reason ?? row.evaluation_reason}</div>}</td>
        <td>{row.evaluation_status ?? 'Not evaluated'}</td>
        {metrics.map(metric => <td key={metric} className="numeric">{typeof row.objective_values?.[metric] === 'number' ? row.objective_values[metric].toLocaleString() : '—'}</td>)}
      </tr>)}
    </tbody></table></div>
    <div className="candidate-selected">
      <div><span className="candidate-selected-label">Selected</span><strong>{names.get(candidate.candidate_id) ?? 'Candidate'}</strong> <span className="mono muted" title={candidate.candidate_id}>{shortDigest(candidate.candidate_id)}</span></div>
      <div className="candidate-selected-metrics">{metrics.map(metric => <span key={metric}><span>{metric}</span><strong>{typeof candidate.objective_values?.[metric] === 'number' ? candidate.objective_values[metric].toLocaleString() : 'Unavailable'}</strong><small>{candidate.objective_availability?.[metric] ?? candidate.evaluation_authority ?? 'authority not reported'}</small></span>)}</div>
      <p>{candidate.eligibility_reason ?? candidate.evaluation_reason ?? 'Inspect metric authority and constraint verdicts before adoption.'}</p>
    </div>
  </Section>;
}
