import { useEffect, useState } from 'react';
import { AnalysisWorkbench } from './AnalysisWorkbench';
import type { WorkbenchMetric, WorkbenchObservation, WorkbenchPreset, WorkbenchState, WorkbenchView } from './analysisWorkbench';
import { num } from './format';
import { Badge, Button, Field, Notice, downloadJson } from './ui';
import { identityIssue, parseAblationDocument, workloadArms, type AblationEvidence } from './workloadExplorer';

/** Measured workload × topology replay, kept out of the uniform injection-rate
 *  sweep: there is no offered-load axis here, only a workload selection.
 *  Root-relative on purpose: this file is copied to the build root as
 *  data/workload_ablation.json. The previous 'public/data/...' form resolved
 *  only because the dev server serves the project tree; in a packaged build the
 *  request missed and the WebKit asset handler reported "The string did not
 *  match the expected pattern" instead of a plain 404. */
const SOURCE = 'data/workload_ablation.json';

function useAblationEvidence() {
  const [state, setState] = useState<{ data?: AblationEvidence; error?: string }>({});
  useEffect(() => {
    let live = true;
    fetch(`/${SOURCE}`, { cache: 'no-store' })      .then(async response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = parseAblationDocument(await response.json());
        if (live) setState({ data });
      })
      .catch(error => {
        if (live) setState({ error: error instanceof Error ? error.message : 'Ablation evidence unreadable.' });
      });
    return () => { live = false; };
  }, []);
  return state;
}

const METRICS: WorkbenchMetric[] = [
  { key: 'throughput', label: 'Accepted throughput', unit: 'packets/node/cycle', direction: 'MAX', digits: 6 },
  { key: 'latencyMean', label: 'Mean packet latency', unit: 'cycles', direction: 'MIN', digits: 3 },
  { key: 'latencyP95', label: 'p95 packet latency', unit: 'cycles', direction: 'MIN', digits: 3 },
  { key: 'hopsAvg', label: 'Hops per packet', unit: 'hops', direction: 'MIN', digits: 3 },
  { key: 'completionCycles', label: 'Completion cycles', unit: 'cycles', direction: 'MIN', digits: 0 },
  { key: 'crosspoints', label: 'Crossbar cost', unit: 'crosspoints', direction: 'MIN', digits: 0 },
  { key: 'storageFlits', label: 'Buffer capacity', unit: 'flits', direction: 'MIN', digits: 0 },
  { key: 'routers', label: 'Router count', unit: 'routers', direction: 'MIN', digits: 0 },
];

export function AblationWorkbench() {
  const { data, error } = useAblationEvidence();
  const [chosen, setChosen] = useState('');
  if (error) return <Notice tone="amber">Workload ablation evidence is unavailable: {error} No comparison is substituted.</Notice>;
  if (!data) return <p className="loading-line">Reading workload ablation evidence…</p>;
  const workload = data.workloads.some(item => item.id === chosen) ? chosen : data.workloads[0]?.id ?? '';
  const points = workloadArms(data, workload);
  const issue = identityIssue(points);
  const label = points[0]?.workloadLabel ?? workload;

  const observations: WorkbenchObservation[] = points.map(point => ({
    id: point.topology,
    label: point.topologyLabel,
    sublabel: point.family,
    values: {
      throughput: point.throughput, latencyMean: point.latencyMean, latencyP95: point.latencyP95,
      hopsAvg: point.hopsAvg, completionCycles: point.completionCycles,
      crosspoints: point.crosspoints, storageFlits: point.storageFlits, routers: point.routers,
    },
    meta: [
      ['Family', point.family],
      ['Endpoints / VCs', `${point.nodes} / ${point.vcs ?? 'not reported'}`],
      ['Mean packet latency', num(point.latencyMean, ' cycles', 3)],
      ['p95 packet latency', num(point.latencyP95, ' cycles', 3)],
      ['Accepted throughput', num(point.throughput, ' packets/node/cycle', 6)],
      ['Hops per packet', num(point.hopsAvg, ' hops', 3)],
      ['Completion', num(point.completionCycles, ' cycles', 0)],
      ['Crosspoints', num(point.crosspoints, '', 0)],
      ['Buffer capacity', num(point.storageFlits, ' flits', 0)],
    ],
  }));

  const views: WorkbenchView[] = [{
    id: 'workload', label: 'Measured workload', chartTitle: 'Measured workload comparison',
    metrics: METRICS, observations, mode: 'scatter', frontMode: issue ? 'none' : 'generic',
    defaultX: 'throughput', defaultY: 'latencyMean', eligibleLabel: 'arms', picker: 'observations',
    note: 'No offered-load axis: every arm replays one measured workload. Arms differ in radix, virtual channels and buffering, so this is not a hardware-equalized comparison.',
    emptyMessage: 'This workload has no successful measured cell.',
  }];
  const presets: WorkbenchPreset[] = [
    { id: 'tradeoff', label: 'Trade-off', view: 'workload', x: 'throughput', y: 'latencyMean', hint: 'Accepted throughput against mean packet latency' },
    { id: 'tail', label: 'Tail latency', view: 'workload', x: 'throughput', y: 'latencyP95', hint: 'Accepted throughput against p95 packet latency' },
    { id: 'path', label: 'Path length', view: 'workload', x: 'hopsAvg', y: 'latencyMean', hint: 'Hops per packet against mean latency' },
    { id: 'cost', label: 'Structural cost', view: 'workload', x: 'crosspoints', y: 'latencyMean', hint: 'Crossbar cost against mean latency' },
  ];

  const table = (state: WorkbenchState, select: (id: string) => void) => <div className="table-scroll"><table aria-label="Measured workload comparison by topology"><thead><tr><th>Arm / family / routing</th><th>Latency mean</th><th>p95</th><th>Accepted throughput</th><th>Hops</th><th>Completion</th><th>Crosspoints</th><th>Buffers</th><th>Comparison result</th></tr></thead><tbody>
    {points.map(point => <tr key={point.topology} className={state.selectedId === point.topology ? 'selected' : undefined}>
      <th><button className="text-button" aria-label={`Select ${point.topology} from data`} onClick={() => select(point.topology)}>{point.topologyLabel}</button><small className="block">{point.family}</small></th>
      <td className="numeric">{num(point.latencyMean, '', 3)}</td><td className="numeric">{num(point.latencyP95, '', 3)}</td>
      <td className="numeric">{num(point.throughput, '', 6)}</td><td className="numeric">{num(point.hopsAvg, '', 3)}</td>
      <td className="numeric">{num(point.completionCycles, '', 0)}</td><td className="numeric">{num(point.crosspoints, '', 0)}</td>
      <td className="numeric">{num(point.storageFlits, '', 0)}</td>
      <td>{!state.frontAvailable ? <Badge tone={issue ? 'amber' : 'neutral'}>{issue ? 'Unverified' : 'Measured'}</Badge> : state.frontIds.includes(point.topology) ? <Badge tone="green">Non-dominated</Badge> : 'Dominated'}</td>
    </tr>)}
  </tbody></table></div>;

  return <AnalysisWorkbench
    title="Workload-matched measured comparison"
    source={{ label: 'Measured trace replay', text: <>Measured BookSim trace replay of one workload across topologies — no offered-load axis, so this is not the uniform injection-rate sweep.{data.skipped > 0 ? ` ${data.skipped} unsuccessful cells in the snapshot are excluded, never zero-filled.` : ''}</> }}
    badges={<><Badge>{data.workloads.length} workloads</Badge><Badge>{points.length} arms at 64 endpoints</Badge>{data.generatedAt && <Badge>measured {data.generatedAt.slice(0, 10)}</Badge>}<Badge tone="amber">Unequal resource budgets</Badge></>}
    actions={(state) => <Button disabled={!points.length} onClick={() => downloadJson('workload-ablation-comparison.json', {
      source: SOURCE, generated_at: data.generatedAt, scope: data.scope, workload, label,
      simulator_seed: data.seed, identity_issue: issue,
      front: state.frontIds, points,
    })}>Export comparison</Button>}
    context={<><Field label="Workload (measured trace replay)"><select value={workload} onChange={event => setChosen(event.target.value)}>
      {data.workloads.map(item => <option key={item.id} value={item.id}>{item.id} · {item.label}</option>)}
    </select></Field><Badge>{label}</Badge></>}
    notice={issue
      ? <Notice tone="amber">Arms at this workload are not a verified comparison: {issue}</Notice>
      : <p className="meta-line">Workload labels are not experimental identity: every arm here shares one trace hash, simulator binary and seed, while the fabric definition is the variable under comparison.</p>}
    views={views}
    presets={presets}
    defaultPreset="tradeoff"
    tableSummary="Measured arm data"
    table={table}
    after={<details className="plot-data"><summary>How to read this comparison</summary><p className="meta-line">Network-only replay: no model compute or DRAM timing, no offered-load axis and no saturation point. Arms differ in radix, virtual channels and buffering, so this is not a hardware-equalized comparison and it does not qualify a topology. Front membership is derived on the two plotted objectives from the measured arms; it is not a study result.</p></details>}
  />;
}
