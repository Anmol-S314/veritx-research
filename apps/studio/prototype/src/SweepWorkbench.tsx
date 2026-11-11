import { useState } from 'react';
import {
  constrainedSweep, nativeMetric, operatingPointsFor, SWEEP_METRICS, sweepCohort, sweepNumber,
  type SweepEvidence, type SweepLimit, type SweepMetric,
} from './analysisCurves';
import { AnalysisWorkbench } from './AnalysisWorkbench';
import type { WorkbenchMetric, WorkbenchObservation, WorkbenchPreset, WorkbenchState, WorkbenchView } from './analysisWorkbench';
import { num } from './format';
import { Badge, Button, Field, Notice, downloadJson } from './ui';

const metrics = Object.keys(SWEEP_METRICS) as SweepMetric[];
const limits: { metric: SweepMetric; op: 'MIN' | 'MAX'; label: string }[] = [
  { metric: 'latency_cycles', op: 'MAX', label: 'Maximum latency (cycles)' },
  { metric: 'accepted_rate', op: 'MIN', label: 'Minimum accepted throughput (packets/node/cycle)' },
  { metric: 'hops_avg', op: 'MAX', label: 'Maximum hops per packet' },
  { metric: 'crosspoints', op: 'MAX', label: 'Maximum crosspoints' },
  { metric: 'storage_flits', op: 'MAX', label: 'Maximum buffer capacity (flits)' },
  { metric: 'native_power_w', op: 'MAX', label: 'Maximum native modeled power (W)' },
  { metric: 'native_area_mm2', op: 'MAX', label: 'Maximum native modeled area (mm²)' },
  { metric: 'native_energy_pj_per_cycle', op: 'MAX', label: 'Maximum native modeled energy (pJ/cycle)' },
];
const metricLabel = (key: SweepMetric) => `${SWEEP_METRICS[key].label} (${SWEEP_METRICS[key].unit})`;
const FAMILY_ACRONYMS = new Set(['GEC', 'MECS', 'SROTA']);
const familyLabel = (family: string | undefined, fallback: string): string => {
  const words = (family && family !== '—' ? family : fallback).split(/[_\s]+/).filter(Boolean);
  return words.map((word, index) => FAMILY_ACRONYMS.has(word.toUpperCase()) ? word.toUpperCase()
    : index === 0 ? word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
      : word.toLowerCase()).join(' ');
};
const digitsFor = (key: SweepMetric): number => key === 'accepted_rate' ? 6
  : ['routers', 'crosspoints', 'storage_flits'].includes(key) ? 0
    : key.startsWith('native_') ? 6 : 3;
const def = (key: SweepMetric): WorkbenchMetric => ({
  key, label: SWEEP_METRICS[key].label, unit: SWEEP_METRICS[key].unit,
  direction: SWEEP_METRICS[key].direction, digits: digitsFor(key),
});
const LOAD: WorkbenchMetric = { key: 'injection_rate', label: 'Offered load', unit: 'packets/node/cycle', digits: 4 };
const HOPS_ZERO: WorkbenchMetric = { key: 'hops_zero', label: 'Hops at zero load', unit: 'hops/packet', direction: 'MIN', digits: 3 };
const ZERO_LOAD: WorkbenchMetric = { key: 'zero_load', label: 'Zero-load latency', unit: 'cycles', direction: 'MIN', digits: 3 };
const OFFERED: WorkbenchMetric = { key: 'offered_rate', label: 'Last stable offered load', unit: 'packets/node/cycle', digits: 4 };
const OPERATING_METRICS: WorkbenchMetric[] = [def('accepted_rate'), def('latency_cycles'), HOPS_ZERO, ZERO_LOAD, OFFERED,
  def('routers'), def('crosspoints'), def('storage_flits')];

export function SweepWorkbench({ evidence, onRefresh, fallback }: { evidence: SweepEvidence; onRefresh: () => void; fallback?: string }) {
  const cohorts = [...new Set(evidence.rows.map(sweepCohort))];
  const [chosenCohort, setChosenCohort] = useState('');
  const cohort = cohorts.includes(chosenCohort) ? chosenCohort : cohorts[0] ?? '';
  const cohortRows = evidence.rows.filter(row => sweepCohort(row) === cohort);
  const rates = [...new Set(cohortRows.map(row => row.injection_rate))]
    .filter(rate => Number.isFinite(rate) && rate >= 0).sort((a, b) => a - b);
  const [chosenRate, setRate] = useState<number | null>(null);
  const rate = chosenRate !== null && rates.includes(chosenRate) ? chosenRate : rates[0];
  const [bounds, setBounds] = useState<Record<string, string>>({});
  const [includeNative, setIncludeNative] = useState(false);
  const [extraObjectives, setExtraObjectives] = useState<SweepMetric[]>([]);
  const nativeRows = evidence.rows.filter(row => row.native_model?.status === 'AVAILABLE');
  const available = (metric: SweepMetric) => !nativeMetric(metric) || (includeNative && nativeRows.some(row => sweepNumber(row, metric) !== null));
  const visibleMetrics = metrics.filter(metric => !nativeMetric(metric) || includeNative);
  const visibleLimits = limits.filter(limit => !nativeMetric(limit.metric) || includeNative);
  const active: SweepLimit[] = visibleLimits.flatMap(limit => {
    const raw = bounds[limit.metric]?.trim();
    return raw && Number.isFinite(Number(raw)) && Number(raw) >= 0 ? [{ ...limit, value: Number(raw) }] : [];
  });
  const invalid = visibleLimits.some(limit => {
    const raw = bounds[limit.metric]?.trim();
    return Boolean(raw) && (!Number.isFinite(Number(raw)) || Number(raw) < 0);
  });
  const candidates = !invalid && rate !== undefined ? constrainedSweep(evidence.rows, rate, cohort, [], active) : [];

  const commonObservations: WorkbenchObservation[] = candidates.map(point => ({
    id: point.topology,
    label: point.topology,
    series: familyLabel(point.row?.family, point.topology),
    sublabel: point.row ? `${point.row.routing ?? 'routing not reported'} · ${point.row.qualification ?? 'qualification not reported'}` : 'No observation at this load',
    values: Object.fromEntries(visibleMetrics.map(metric => [metric, point.row ? sweepNumber(point.row, metric) : null])),
    excluded: point.eligible ? undefined : point.reasons.join('; '),
    meta: [
      ['Routing', point.row?.routing ?? 'Not available'],
      ['Product status', point.row?.qualification ?? 'not reported'],
    ],
    note: point.eligible ? undefined : point.reasons.join('; '),
  }));

  const seriesObservations: WorkbenchObservation[] = [];
  for (const topology of [...new Set(cohortRows.map(row => row.topology))]) {
    const sorted = cohortRows.filter(row => row.topology === topology).sort((a, b) => a.injection_rate - b.injection_rate);
    const cliff = sorted.findIndex(row => row.status === 'unstable');
    const plotted = cliff >= 0 ? sorted.slice(0, cliff + 1) : sorted;
    for (const row of plotted) {
      if (typeof row.latency_cycles !== 'number' && typeof row.hops_avg !== 'number' && typeof row.accepted_rate !== 'number') continue;
      seriesObservations.push({
        id: `${topology}@${row.injection_rate}`,
        label: topology,
        sublabel: `offered ${row.injection_rate}`,
        series: topology,
        values: { injection_rate: row.injection_rate, ...Object.fromEntries(visibleMetrics.map(metric => [metric, sweepNumber(row, metric)])) },
        meta: [
          ['Offered load', String(row.injection_rate)],
          ['Status', row.status ?? 'status absent'],
          ['Routing', row.routing ?? 'not reported'],
          ['Product status', row.qualification ?? 'not reported'],
        ],
        note: row.status === 'unstable' ? 'First unstable window; the curve stops here because the network never reached steady state.' : undefined,
      });
    }
  }

  const operating = operatingPointsFor(cohortRows);
  const operatingObservations: WorkbenchObservation[] = operating.map(point => {
    const last = cohortRows.find(row => row.topology === point.topology && row.injection_rate === point.rate && row.status === 'ok');
    return {
      id: point.topology,
      label: point.topology,
      series: familyLabel(point.family, point.topology),
      sublabel: `${point.family} · ${point.routing} · ${point.vcs ?? '—'} VCs`,
      values: {
        accepted_rate: point.accepted, latency_cycles: point.latency, hops_zero: point.zeroHops,
        zero_load: point.zeroLoad, offered_rate: point.rate,
        routers: last?.routers ?? null, crosspoints: last?.crosspoints ?? null, storage_flits: last?.storage_flits ?? null,
      },
      meta: [
        ['Family', point.family], ['Routing', point.routing], ['VCs', String(point.vcs ?? 'not reported')],
        ['Last stable offered', String(point.rate)], ['First unstable load', point.firstUnstable === null ? 'Not observed' : String(point.firstUnstable)],
        ['Latency here', `${point.latency.toFixed(2)} cycles`], ['Accepted throughput', point.accepted.toFixed(6)],
      ],
      note: 'Last stable observation per arm. Accepted throughput is a lower bound; the unstable window is not a saturation measurement.',
    };
  });

  const allMetricOptions = metrics.map(metric => ({ ...def(metric), disabled: nativeMetric(metric) && !available(metric) }));
  const views: WorkbenchView[] = [
    {
      id: 'series', label: 'All offered loads', chartTitle: 'Latency versus injection rate for each topology', metrics: [LOAD, ...visibleMetrics.map(def)], metricOptions: [LOAD, ...allMetricOptions],
      observations: seriesObservations, mode: 'curve', frontMode: 'none', defaultX: 'injection_rate', defaultY: 'latency_cycles',
      seriesAxis: 'injection_rate', defaultLogY: true, picker: 'series',
      note: 'Each arm stops at its first unstable window; beyond that BookSim is draining a network that never reached steady state.',
      emptyMessage: 'The sweep carries no numeric observations for this cohort.',
    },
    {
      id: 'common', label: 'Common offered load', chartTitle: 'Load-matched Pareto', metrics: visibleMetrics.map(def), metricOptions: allMetricOptions,
      observations: commonObservations, mode: 'scatter', frontMode: 'generic', extraFrontKeys: extraObjectives,
      defaultX: 'latency_cycles', defaultY: 'hops_avg', picker: 'observations',
      note: `Observations at one shared offered load (${rate ?? 'no rate'}). Constraints apply before dominance; equal points both survive.`,
      emptyMessage: 'No eligible observations at this load and these limits. Reduce the offered load or clear constraints.',
    },
    {
      id: 'operating', label: 'Last stable operating point', chartTitle: 'Operating point: accepted throughput versus latency at the last stable offered rate', metrics: OPERATING_METRICS,
      observations: operatingObservations, mode: 'scatter', frontMode: 'generic',
      defaultX: 'accepted_rate', defaultY: 'latency_cycles', picker: 'observations',
      note: 'One last-stable observation per arm, at different offered loads. This is not the common-load Pareto comparison or a latency SLA.',
      emptyMessage: 'No stable operating points with measured accepted throughput.',
    },
  ];
  const presets: WorkbenchPreset[] = [
    { id: 'latency', label: 'Latency vs load', view: 'series', x: 'injection_rate', y: 'latency_cycles', hint: 'Latency across every offered load' },
    ...(includeNative ? [{ id: 'power', label: 'Power vs load', view: 'series', x: 'injection_rate', y: 'native_power_w', hint: 'Native modeled power across offered load' } satisfies WorkbenchPreset] : []),
    { id: 'tradeoff', label: 'Trade-off', view: 'common', x: 'latency_cycles', y: 'hops_avg', hint: 'Two objectives at one shared offered load' },
    { id: 'path', label: 'Path length', view: 'common', x: 'hops_avg', y: 'latency_cycles', hint: 'Hops per packet against latency at one shared load' },
    { id: 'operating', label: 'Operating point', view: 'operating', x: 'accepted_rate', y: 'latency_cycles', hint: 'Last stable latency and accepted throughput per arm' },
  ];

  const objectivesFor = (state: WorkbenchState): SweepMetric[] => [...new Set([state.xKey, state.yKey, ...extraObjectives]
    .filter(key => (metrics as string[]).includes(key))
    .map(key => key as SweepMetric)
    .filter(metric => available(metric)))];

  const exportComparison = (state: WorkbenchState) => {
    const objectives = objectivesFor(state);
    if (state.viewId === 'common') {
      const exported = !invalid && rate !== undefined ? constrainedSweep(evidence.rows, rate, cohort, objectives, active) : [];
      downloadJson('sweep-pareto.json', {
        source_path: evidence.source_path, sha256: evidence.sha256, scope: evidence.scope,
        cohort, injection_rate: rate, projection: [state.xKey, state.yKey], include_native_estimates: includeNative,
        objectives: objectives.map(metric => ({ metric, ...SWEEP_METRICS[metric] })), constraints: active,
        candidates: exported.map(point => ({ ...point, front: state.frontIds.includes(point.topology) })),
      });
      return;
    }
    const view = views.find(item => item.id === state.viewId);
    downloadJson(`sweep-${state.viewId}.json`, {
      source_path: evidence.source_path, sha256: evidence.sha256, scope: evidence.scope,
      cohort, view: state.viewId, projection: [state.xKey, state.yKey],
      include_native_estimates: includeNative, observations: view?.observations ?? [],
    });
  };

  const candidateTable = (state: WorkbenchState, select: (id: string) => void) => <div className="table-scroll"><table aria-label="Load-matched sweep candidates"><thead><tr><th>Arm / routing / qualification</th>{visibleMetrics.map(metric => <th key={metric}>{metricLabel(metric)}</th>)}<th>Comparison result</th></tr></thead>
    <tbody>{candidates.map(point => {
      const plotted = [state.xKey, state.yKey].filter(key => (metrics as string[]).includes(key)) as SweepMetric[];
      const missing = plotted.filter(key => !point.row || sweepNumber(point.row, key) === null);
      const result = !point.eligible ? point.reasons.join('; ')
        : missing.length ? `Not plotted: ${missing.map(key => SWEEP_METRICS[key].label).join(', ')} unavailable`
          : !state.frontAvailable ? 'Measured'
            : state.frontIds.includes(point.topology) ? <Badge tone="green">Non-dominated</Badge> : 'Dominated';
      return <tr key={point.topology} className={state.selectedId === point.topology ? 'selected' : undefined}>
        <th><button className="text-button" aria-label={`Select ${point.topology} from data`} onClick={() => select(point.topology)}>{point.topology}</button><small className="block">{point.row?.routing ?? 'No matching observation'} · {point.row?.qualification ?? 'qualification not reported'}</small></th>
        {visibleMetrics.map(metric => <td key={metric} className="numeric">{point.row ? num(sweepNumber(point.row, metric), '', metric === 'accepted_rate' ? 6 : 3) : '—'}</td>)}
        <td>{result}</td>
      </tr>;
    })}</tbody></table></div>;

  const operatingTable = (state: WorkbenchState, select: (id: string) => void) => <div className="table-scroll"><table aria-label="Operating point data"><thead><tr><th>Arm</th><th>Family</th><th>VCs</th><th>Routing</th><th>Zero-load</th><th>Hops @ zero</th><th>Last stable offered</th><th>Accepted</th><th>Latency there</th><th>First unstable</th><th>Comparison</th></tr></thead>
    <tbody>{operatingObservations.map(point => <tr key={point.id} className={state.selectedId === point.id ? 'selected' : undefined}>
      <th><button className="text-button" onClick={() => select(point.id)}>{point.label}</button></th>
      <td>{point.sublabel?.split(' · ')[0] ?? '—'}</td><td>{point.meta?.find(([label]) => label === 'VCs')?.[1] ?? '—'}</td>
      <td>{point.meta?.find(([label]) => label === 'Routing')?.[1] ?? '—'}</td>
      <td className="numeric">{num(point.values.zero_load, ' cyc', 3)}</td><td className="numeric">{num(point.values.hops_zero, '', 3)}</td>
      <td className="numeric">{num(point.values.offered_rate, '', 4)}</td><td className="numeric">{num(point.values.accepted_rate, '', 6)}</td>
      <td className="numeric">{num(point.values.latency_cycles, ' cyc', 3)}</td>
      <td>{point.meta?.find(([label]) => label === 'First unstable load')?.[1] ?? '—'}</td>
      <td>{state.frontAvailable ? (state.frontIds.includes(point.id) ? 'Non-dominated' : 'Dominated') : '—'}</td>
    </tr>)}</tbody></table></div>;

  return <AnalysisWorkbench
    title="Repository sweep comparison"
    source={{ label: 'Reference experiment', text: <>Uniform injection · repository reference, not the selected project's study or run.</> }}
    actions={(state) => <>
      <Button disabled={invalid || !candidates.length} onClick={() => exportComparison(state)}>{state.viewId === 'common' ? 'Export comparison' : 'Export data'}</Button>
      <Button onClick={onRefresh}>Refresh sweep evidence</Button>
    </>}
    context={(state) => <><Field label="Sweep workload and size"><select value={cohort} onChange={event => { setChosenCohort(event.target.value); setRate(null); }}>{cohorts.map(value => <option key={value}>{value}</option>)}</select></Field>
      {state.viewId === 'common' && <Field label="Offered load (packets/node/cycle)"><select value={rate ?? ''} onChange={event => setRate(Number(event.target.value))}>{rates.map(value => <option key={value} value={value}>{value}</option>)}</select></Field>}
    </>}
    notice={<>
      {fallback && <Notice tone="amber">Gateway sweep unavailable; showing the bundled snapshot.</Notice>}
      {includeNative && <Notice tone="amber">Research estimates · 2007 ITRS 32nm model, not silicon signoff. Unsupported families are excluded. Energy is per cycle, not per packet.</Notice>}
      {invalid && <Notice tone="red">Constraints must be finite, non-negative numbers. Clear or correct the invalid limit.</Notice>}
      {!invalid && !candidates.length && rate !== undefined && <Notice tone="amber">No eligible observations at this load and these limits. Reduce the offered load or clear constraints. Missing values are never substituted.</Notice>}
    </>}
    views={views}
    presets={presets}
    defaultPreset="latency"
    refine={<>
      {active.length > 0 && <div className="sweep-filter-chips" aria-label="Active constraints">{active.map(limit => <button key={limit.metric} type="button" onClick={() => setBounds({ ...bounds, [limit.metric]: '' })} aria-label={`Remove ${SWEEP_METRICS[limit.metric].label} constraint`}>{SWEEP_METRICS[limit.metric].label} {limit.op === 'MAX' ? '≤' : '≥'} {limit.value}<span aria-hidden="true"> ×</span></button>)}</div>}
      <details className="wb-refine"><summary>Refine comparison · {active.length} constraints · {extraObjectives.length} extra objectives</summary>
        <label className="check-row"><input type="checkbox" checked={includeNative} disabled={!nativeRows.length} onChange={event => {
          setIncludeNative(event.target.checked);
          if (!event.target.checked) {
            setExtraObjectives(extraObjectives.filter(metric => !nativeMetric(metric)));
            setBounds(Object.fromEntries(Object.entries(bounds).filter(([metric]) => !metric.startsWith('native_'))));
          }
        }} />Include BookSim native estimates (research only)</label>
        <div className="wb-refine-block"><h3>Exploratory constraints</h3>
          <div className="form-grid">{visibleLimits.map(limit => <Field key={limit.metric} label={limit.label}><input type="number" min="0" step="any" placeholder="No limit" value={bounds[limit.metric] ?? ''} onChange={event => setBounds({ ...bounds, [limit.metric]: event.target.value })} /></Field>)}</div>
          <div className="actions"><Button onClick={() => setBounds({})}>Clear constraints</Button></div>
          <p className="meta-line">Constraints apply to the common-load comparison before dominance, never to the all-loads curve.</p>
        </div>
        <div className="wb-refine-block"><h3>Front objectives</h3>
          <div className="actions">{metrics.map(metric => <label className="check-chip" key={metric}>
            <input type="checkbox" aria-label={`Optimize ${metricLabel(metric)}`} checked={extraObjectives.includes(metric)} disabled={!available(metric)} onChange={event => setExtraObjectives(event.target.checked ? [...extraObjectives, metric] : extraObjectives.filter(value => value !== metric))} />{metricLabel(metric)} · {SWEEP_METRICS[metric].direction}
          </label>)}</div>
          <p className="meta-line">Front membership uses the two plotted axes plus every extra objective. {extraObjectives.length > 0 ? 'The chart is a 2D projection of this multi-objective front.' : 'Add an objective to compare more than two dimensions.'}</p>
        </div>
      </details>
    </>}
    tableSummary={(state) => state.viewId === 'common' ? 'Candidate data' : 'Operating point data'}
    table={(state, select) => state.viewId === 'common' ? candidateTable(state, select) : state.viewId === 'series' ? undefined : operatingTable(state, select)}
    after={undefined}
    assumptions={[
      ['Evidence file', <>{evidence.source_path}{evidence.sha256 ? <> · <span className="mono">{evidence.sha256.slice(0, 19)}…</span></> : null}{fallback ? ' · bundled snapshot' : null}</>],
      ['Scope', evidence.scope ?? 'Repository reference, not the selected project or run'],
      ['Experiment', `Uniform random injection at ${cohorts.length} workload/size cohort${cohorts.length === 1 ? '' : 's'}; one arm is one fabric configuration.`],
      ['Not ranked', 'Latency across different offered loads. The all-loads curve is a trajectory, not a frontier.'],
      ['Operating point', 'Last stable window per arm, at different offered loads. Accepted throughput is a lower bound, not a saturation measurement.'],
      ['Not measured', 'Model compute, DRAM timing, power, area and silicon timing. Power and area, where shown, are labeled research estimates from the native BookSim model, not hardware measurements.'],
      ['Qualification', 'Completing a sweep does not qualify a configuration for RTL, ASIC or FPGA.'],
    ]}
  />;
}
