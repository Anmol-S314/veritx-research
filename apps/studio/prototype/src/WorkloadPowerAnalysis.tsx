import { useEffect, useState, type ReactElement } from 'react';
import { AnalysisWorkbench } from './AnalysisWorkbench';
import type { WorkbenchMetric, WorkbenchPreset, WorkbenchState, WorkbenchView } from './analysisWorkbench';
import {
  buildArmObservations, familyLabel, formatDurationNs, formatPj, metricKeys,
  parseWorkloadPower, sharePercent, WORKLOAD_METRICS, type DerivedArm, type WorkloadPowerDoc,
  type WorkloadPowerRun,
} from './workloadPower';
import { Assumptions, Badge, Button, Field, Notice, Properties, Section, downloadJson } from './ui';
import './analysisCharts.css';

type SensitivityPoint = {
  workload: string; topology: string; topology_label?: string; family?: string;
  vcs?: number; depth: number; status?: string;
  latency_p95?: number | null; latency_mean?: number | null; hops_avg?: number | null;
  throughput?: number | null; completion_cycles?: number | null; storage_flits?: number | null;
  routers?: number | null; crosspoints?: number | null; source?: string;
};
type SensitivityDoc = { points: SensitivityPoint[]; scope?: string };

function useJson<T>(path: string, parse: (value: unknown) => T): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let live = true;
    fetch(path, { cache: 'no-store' })
      .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then(value => { if (live) setState({ data: parse(value), error: null }); })
      .catch(reason => { if (live) setState({ data: null, error: String(reason?.message ?? reason) }); });
    return () => { live = false; };
  }, [path]);
  return state;
}

const asNumber = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;

const metric = (key: keyof typeof WORKLOAD_METRICS): WorkbenchMetric => {
  const definition = WORKLOAD_METRICS[key] as { label: string; unit?: string; direction?: 'MIN' | 'MAX'; digits?: number };
  return { key, label: definition.label, unit: definition.unit, direction: definition.direction, digits: definition.digits };
};

const number = (value: number | null | undefined, digits = 2): string =>
  typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';

const best = (arms: DerivedArm[], value: (arm: DerivedArm) => number | null, direction: 'MIN' | 'MAX'): { arm: DerivedArm; value: number } | null => {
  const scored = arms.flatMap(arm => { const result = value(arm); return result === null ? [] : [{ arm, value: result }]; });
  if (!scored.length) return null;
  return scored.reduce((left, right) => direction === 'MIN'
    ? (right.value < left.value ? right : left)
    : (right.value > left.value ? right : left));
};

const breakdownRows = (arm: DerivedArm): { label: string; value: number | null; share: number | null; tone: string }[] => {
  const run = arm.run;
  const breakdown = run.power_breakdown_w ?? {};
  const total = arm.breakdownTotalW;
  return [
    { label: 'Channel wire', value: asNumber(breakdown.channel_wire_w), share: sharePercent(asNumber(breakdown.channel_wire_w), total), tone: '#0f6c9e' },
    { label: 'Clock + retiming', value: asNumber(breakdown.channel_clock_w) !== null && asNumber(breakdown.channel_retiming_w) !== null
      ? (asNumber(breakdown.channel_clock_w) as number) + (asNumber(breakdown.channel_retiming_w) as number) : null, share: null, tone: '#3b87b5' },
    { label: 'Buffer read/write', value: asNumber(breakdown.input_read_w) !== null && asNumber(breakdown.input_write_w) !== null
      ? (asNumber(breakdown.input_read_w) as number) + (asNumber(breakdown.input_write_w) as number) : null, share: arm.bufferPowerW !== null && total ? sharePercent(arm.bufferPowerW, total) : null, tone: '#246847' },
    { label: 'Switch compute/control', value: asNumber(breakdown.switch_compute_w) !== null && asNumber(breakdown.switch_control_w) !== null
      ? (asNumber(breakdown.switch_compute_w) as number) + (asNumber(breakdown.switch_control_w) as number) : null, share: null, tone: '#79540c' },
    { label: 'Output DFF/clock', value: asNumber(breakdown.output_dff_w) !== null && asNumber(breakdown.output_clock_w) !== null && asNumber(breakdown.output_control_w) !== null
      ? (asNumber(breakdown.output_dff_w) as number) + (asNumber(breakdown.output_clock_w) as number) + (asNumber(breakdown.output_control_w) as number) : null, share: null, tone: '#6b4f9e' },
    { label: 'Leakage', value: arm.leakagePowerW, share: sharePercent(arm.leakagePowerW, total), tone: '#a32928' },
  ];
};

function PowerShareBar({ arm }: { arm: DerivedArm }) {
  const rows = breakdownRows(arm).filter(row => row.value !== null && row.value > 0);
  const total = rows.reduce((sum, row) => sum + (row.value as number), 0);
  if (!rows.length || !total) return <p className="meta-line">No per-component power breakdown was parsed for this arm.</p>;
  return <div className="power-share-bar" role="img" aria-label="Power share by component">
    {rows.map(row => <span key={row.label} style={{ width: `${100 * (row.value as number) / total}%`, background: row.tone }}
      title={`${row.label}: ${(row.value as number).toFixed(3)} W (${(100 * (row.value as number) / total).toFixed(1)}%)`} />)}
  </div>;
}

function ArmTable({ arms, state, select }: { arms: DerivedArm[]; state: WorkbenchState; select: (id: string) => void }) {
  const keys: (keyof typeof WORKLOAD_METRICS)[] = ['latency_p95', 'hops_avg', 'throughput_flits_per_cycle', 'vcs', 'native_power_w', 'native_area_mm2', 'energy_per_packet_pj', 'pdp_pj', 'throughput_per_watt'];
  return <div className="table-scroll"><table aria-label="Workload arm analysis">
    <thead><tr><th>Topology / family</th>{keys.map(key => <th key={key}>{WORKLOAD_METRICS[key].label}</th>)}<th>Result</th></tr></thead>
    <tbody>{arms.map(arm => {
      const run = arm.run;
      const selected = state.selectedId === run.topology;
      return <tr key={run.topology} className={selected ? 'selected' : undefined}>
        <th><button className="text-button" onClick={() => select(run.topology)}>{run.topology_label ?? run.topology}</button><small className="block">{familyLabel(run.family ?? undefined, run.topology)} · {run.routing ?? 'routing not reported'}</small></th>
        <td className="numeric">{number(run.latency_p95, 1)}</td>
        <td className="numeric">{number(run.hops_avg, 2)}</td>
        <td className="numeric">{number(run.throughput_flits_per_cycle, 2)}</td>
        <td className="numeric">{number(run.vcs, 0)}</td>
        <td className="numeric">{number(run.native_power_w, 3)}</td>
        <td className="numeric">{number(run.native_area_mm2, 4)}</td>
        <td className="numeric">{arm.energyPerPacketPj === null ? '—' : formatPj(arm.energyPerPacketPj)}</td>
        <td className="numeric">{arm.pdpPj === null ? '—' : formatPj(arm.pdpPj)}</td>
        <td className="numeric">{number(arm.throughputPerWatt, 2)}</td>
        <td>{arm.totalEnergyPj === null ? <Badge tone="amber">power not modeled</Badge> : state.frontIds.includes(run.topology) ? <Badge tone="green">non-dominated</Badge> : 'measured'}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

function BufferDepthTable({ points, runs }: { points: SensitivityPoint[]; runs: WorkloadPowerRun[] }) {
  const topologies = [...new Set(points.map(point => point.topology))];
  if (!topologies.length) return <p className="meta-line">No buffer-depth measurements for this workload.</p>;
  const vcs = new Map(runs.map(run => [run.topology, run.vcs]));
  return <div className="table-scroll"><table aria-label="Buffer depth and virtual channels">
    <thead><tr><th>Topology</th><th>VCs</th><th>Depth 4 · P95</th><th>Depth 8 · P95</th><th>Depth 16 · P95</th><th>Depth 8 · storage</th><th>Depth 8 · hops</th><th>Measured depths</th></tr></thead>
    <tbody>{topologies.map(topology => {
      const rows = points.filter(point => point.topology === topology);
      const find = (depth: number) => rows.find(row => row.depth === depth);
      const depth8 = find(8);
      const measured = [...new Set(rows.map(row => row.depth))].sort((a, b) => a - b);
      return <tr key={topology}>
        <th>{depth8?.topology_label ?? topology}<small className="block">{familyLabel(depth8?.family, topology)}</small></th>
        <td className="numeric">{number(vcs.get(topology) ?? depth8?.vcs, 0)}</td>
        {[4, 8, 16].map(depth => <td className="numeric" key={depth}>{number(find(depth)?.latency_p95, 1)}</td>)}
        <td className="numeric">{number(depth8?.storage_flits, 0)}</td>
        <td className="numeric">{number(depth8?.hops_avg, 2)}</td>
        <td>{measured.length > 1 ? `${measured.join(' / ')} flits/VC` : <Badge tone="amber">depth 8 only</Badge>}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

export function WorkloadPowerAnalysis({ initialWorkload, projectWorkload }: { initialWorkload?: string; projectWorkload?: string }): ReactElement {
  const power = useJson<WorkloadPowerDoc>('/data/workload_power.json', parseWorkloadPower);
  const sensitivity = useJson<SensitivityDoc>('/data/design_sensitivity.json', value => {
    if (!value || typeof value !== 'object' || !Array.isArray((value as SensitivityDoc).points)) throw new Error('Design sensitivity evidence is unreadable');
    return value as SensitivityDoc;
  });
  const [workload, setWorkload] = useState(initialWorkload ?? '');
  const [focus, setFocus] = useState('');
  // The project can load after this panel mounts; adopt its matching reference
  // once the evidence is available without overriding a later manual choice.
  useEffect(() => {
    if (!initialWorkload || !power.data) return;
    if (power.data.workloads.some(item => item.workload_id === initialWorkload)) setWorkload(initialWorkload);
  }, [initialWorkload, power.data]);

  if (power.error) return <Section title="Workload analysis"><Notice tone="red">Workload power evidence unreadable: {power.error}. The project study above is unaffected.</Notice></Section>;
  if (!power.data) return <Section title="Workload analysis"><p className="loading-line"><span className="pulse-dot" aria-hidden="true" />Reading measured workload power evidence…</p></Section>;

  const doc = power.data;
  const workloads = doc.workloads;
  const selectedWorkload = workloads.some(item => item.workload_id === workload)
    ? workload
    : workloads.find(item => item.workload_id === 'llm_transformer')?.workload_id ?? workloads[0]?.workload_id ?? '';
  const meta = workloads.find(item => item.workload_id === selectedWorkload);
  const referenceMatch = Boolean(initialWorkload && workloads.some(item => item.workload_id === initialWorkload));
  const observations = buildArmObservations(doc, selectedWorkload);
  const arms = observations.map(observation => observation.derived);
  const clockHz = doc.model?.clock_hz && doc.model.clock_hz > 0 ? doc.model.clock_hz : 1;
  const focusRun = arms.find(arm => arm.run.topology === focus) ?? best(arms, arm => arm.energyPerPacketPj, 'MIN')?.arm ?? arms[0];
  const sensitivityPoints = (sensitivity.data?.points ?? []).filter(point => point.workload === selectedWorkload);
  const componentRows = focusRun ? breakdownRows(focusRun).map(row => ({
    ...row,
    share: row.value !== null && focusRun.breakdownTotalW ? sharePercent(row.value, focusRun.breakdownTotalW) : null,
  })) : [];
  const leaders: { label: string; pick: { arm: DerivedArm; value: number } | null; format: (arm: DerivedArm, value: number) => string; sub?: (arm: DerivedArm) => string }[] = [
    { label: 'Lowest P95 latency', pick: best(arms, arm => arm.run.latency_p95 ?? null, 'MIN'), format: (_arm: DerivedArm, value: number) => `${number(value, 0)} cyc` },
    { label: 'Highest delivered throughput', pick: best(arms, arm => arm.run.throughput_flits_per_cycle ?? null, 'MAX'), format: (_arm: DerivedArm, value: number) => `${number(value, 2)} flits/cyc` },
    { label: 'Shortest average path', pick: best(arms, arm => arm.run.hops_avg ?? null, 'MIN'), format: (_arm: DerivedArm, value: number) => `${number(value, 2)} hops` },
    { label: 'Lowest modeled power', pick: best(arms, arm => arm.run.native_power_w ?? null, 'MIN'), format: (_arm: DerivedArm, value: number) => `${number(value, 3)} W` },
    { label: 'Smallest modeled area', pick: best(arms, arm => arm.run.native_area_mm2 ?? null, 'MIN'), format: (_arm: DerivedArm, value: number) => `${number(value, 4)} mm²` },
    { label: 'Lowest energy per packet', pick: best(arms, arm => arm.energyPerPacketPj, 'MIN'), format: (_arm: DerivedArm, value: number) => formatPj(value) },
    { label: 'Workload horizon', pick: best(arms, arm => arm.run.completion_cycles ?? null, 'MIN'), format: (arm: DerivedArm, value: number) => formatDurationNs(value, arm.clockHz), sub: () => 'Fastest completion at the model clock' },
  ];

  const views: WorkbenchView[] = [{
    id: 'arms', label: 'Workload arms', chartTitle: 'Workload arm analysis',
    metrics: metricKeys.map(key => metric(key)),
    observations,
    mode: 'scatter', frontMode: 'generic',
    extraFrontKeys: ['native_area_mm2', 'energy_per_packet_pj', 'hops_avg', 'pdp_pj'],
    defaultX: 'latency_p95', defaultY: 'native_power_w',
    picker: 'observations', eligibleLabel: 'measured', barSort: 'value', barLog: true, xLabel: 'Topology arm',
    emptyMessage: 'This workload has no measured arm for the selected axes.',
  }, {
    id: 'depth', label: 'Buffer depth', chartTitle: 'Buffer-depth sweep',
    metrics: [
      { key: 'depth', label: 'Buffer depth', unit: 'flits/VC', direction: 'MIN', digits: 0 },
      metric('latency_p95'),
      metric('latency_mean'),
      metric('hops_avg'),
      { key: 'throughput', label: 'Delivered throughput', unit: 'flits/cycle', direction: 'MAX', digits: 2 },
      { key: 'storage_flits', label: 'Configured storage', unit: 'flits', direction: 'MIN', digits: 0 },
      metric('vcs'),
    ],
    observations: sensitivityPoints.map(point => {
      const label = point.topology_label ?? point.topology;
      return {
        id: `${point.topology}@${point.depth}`,
        label,
        sublabel: `${point.depth} flits/VC · ${point.vcs ?? '—'} VCs`,
        series: label,
        values: {
          depth: point.depth,
          latency_p95: point.latency_p95 ?? null,
          latency_mean: point.latency_mean ?? null,
          hops_avg: point.hops_avg ?? null,
          throughput: point.throughput ?? null,
          storage_flits: point.storage_flits ?? null,
          vcs: point.vcs ?? null,
        },
        meta: [
          ['Topology', label],
          ['Buffer depth', `${point.depth} flits/VC`],
          ['Storage', point.storage_flits === null || point.storage_flits === undefined ? 'Not reported' : `${point.storage_flits.toLocaleString()} flits`],
          ['Source', point.source ?? 'Not reported'],
        ] as [string, string][],
        note: point.status === 'ok' ? 'Measured depth sweep; trace, topology, binary and seed are held per arm.' : `Status: ${point.status ?? 'not reported'}.`,
      };
    }),
    mode: 'scatter', frontMode: 'none',
    defaultX: 'depth', defaultY: 'latency_p95',
    picker: 'observations', eligibleLabel: 'measured',
    note: 'Five product arms were swept at 4, 8 and 16 flits per VC; the other seven arms contribute only the depth-8 baseline.',
    emptyMessage: sensitivity.error ? 'Buffer-depth evidence is unreadable.'
      : sensitivity.data ? 'This workload has no measured buffer-depth sweep.' : 'Reading buffer-depth evidence…',
  }];

  const presets: WorkbenchPreset[] = [
    { id: 'pareto', label: 'Latency · power Pareto', view: 'arms', x: 'latency_p95', y: 'native_power_w', hint: 'Measured latency against modeled power; the front uses every declared objective' },
    { id: 'power-area', label: 'Power · area', view: 'arms', x: 'native_power_w', y: 'native_area_mm2', hint: 'Modeled power and area, both lower is better' },
    { id: 'energy', label: 'Energy vs latency', view: 'arms', x: 'latency_p95', y: 'energy_per_packet_pj', hint: 'Energy per delivered packet against packet P95 latency' },
    { id: 'hops', label: 'Hops vs latency', view: 'arms', x: 'hops_avg', y: 'latency_p95', hint: 'Average path length against packet P95 latency' },
    { id: 'vcs', label: 'Virtual channels', view: 'arms', x: 'vcs', y: 'latency_p95', hint: 'Canonical VC count against packet P95 latency' },
    { id: 'depth', label: 'Buffer depth', view: 'depth', x: 'depth', y: 'latency_p95', hint: 'Measured P95 latency at 4, 8 and 16 flits per VC for the five product arms' },
    { id: 'latency', label: 'Latency ranking', view: 'arms', x: 'latency_p95', y: 'latency_p95', mode: 'bars', hint: 'Packet P95 latency by topology, ranked best first' },
    { id: 'power-delay', label: 'Power–delay product', view: 'arms', x: 'pdp_pj', y: 'pdp_pj', mode: 'bars', hint: 'P × P95 latency; a derived cross-check, not a separate measurement' },
    { id: 'efficiency', label: 'Throughput per watt', view: 'arms', x: 'throughput_per_watt', y: 'throughput_per_watt', mode: 'bars', hint: 'Delivered flits per second per modeled watt' },
    { id: 'energy-index', label: 'Energy index', view: 'arms', x: 'energy_index', y: 'energy_index', mode: 'bars', hint: 'Energy per packet relative to the lowest measured arm' },
  ];

  const exportAnalysis = (state: WorkbenchState) => downloadJson(`workload-analysis-${selectedWorkload}.json`, {
    schema: 'veritx/workload-analysis/1',
    generated_from: doc.generated_from,
    scope: doc.scope,
    workload: { id: selectedWorkload, label: meta?.label, trace_sha256: meta?.trace_sha256, source_path: meta?.source_path },
    corner: doc.corner,
    model: doc.model,
    projection: [state.xKey, state.yKey],
    arms: arms.map(arm => ({
      topology: arm.run.topology,
      family: arm.run.family,
      vcs: arm.run.vcs,
      routing: arm.run.routing,
      latency_p50_cycles: arm.run.latency_p50,
      latency_p95_cycles: arm.run.latency_p95,
      latency_p99_cycles: arm.run.latency_p99,
      hops_avg: arm.run.hops_avg,
      throughput_flits_per_cycle: arm.run.throughput_flits_per_cycle,
      completion_cycles: arm.run.completion_cycles,
      power_w: arm.run.native_power_w,
      area_mm2: arm.run.native_area_mm2,
      total_energy_pj: arm.totalEnergyPj,
      energy_per_packet_pj: arm.energyPerPacketPj,
      energy_per_flit_pj: arm.energyPerFlitPj,
      energy_per_bit_pj: arm.energyPerBitPj,
      energy_per_hop_pj: arm.energyPerHopPj,
      power_delay_product_pj: arm.pdpPj,
      throughput_per_watt: arm.throughputPerWatt,
      power_breakdown_w: arm.run.power_breakdown_w,
      model_id: arm.run.native_model?.model_id,
      source_path: arm.run.source_path,
    })),
  });

  return <div className="curves-workspace">
    <Section title="Workload analysis">
      <div className="wb-context">
        <Field label="Repository reference workload"><select value={selectedWorkload} onChange={event => { setWorkload(event.target.value); setFocus(''); }}>
          {workloads.map(item => <option key={item.workload_id} value={item.workload_id}>{item.label} · {item.arm_count ?? '—'} arms</option>)}
        </select></Field>
      </div>
      <p className="meta-line">{meta?.label ?? selectedWorkload} · {number(meta?.nodes, 0)} endpoints · {meta?.events?.toLocaleString() ?? '—'} trace events. Native BookSim 32nm power/area model.</p>
      {projectWorkload && <p className="meta-line">Loaded revision: {projectWorkload}. {referenceMatch ? 'Showing the matching repository trace.' : 'No repository trace matches this model; showing the closest reference.'}</p>}
      <div className="stat-strip">
        {leaders.map(({ label, pick, format, sub }) => <div className="stat" key={label}>
          <span>{label}</span>
          <strong>{pick ? format(pick.arm, pick.value) : '—'}</strong>
          <small>{pick ? (sub ? sub(pick.arm) : pick.arm.run.topology_label ?? pick.arm.run.topology) : 'No measured arm'}</small>
        </div>)}
      </div>
      <AnalysisWorkbench
        title="Curves and Pareto"
        showBadges={false}
        badges={null}
        source={{ label: 'Same workload, one run per arm', text: <>Latency, hops and throughput are measured; power, area and energy use the native model.</> }}
        assumptions={[
          ['Reference', `${meta?.label ?? selectedWorkload} · ${meta?.nodes ?? 64} endpoints · ${meta?.events?.toLocaleString() ?? '—'} trace events, replayed from the repository workload.`],
          ['Arms', 'Every point is one measured topology for this workload.'],
          ['Model', 'Latency, hops and throughput are measured; power, area and energy use the native BookSim 32 nm model, no compute or DRAM.'],
        ]}
        ownAssumptions={false}
        notice={sensitivity.error ? <Notice tone="amber">Buffer-depth evidence unreadable: {sensitivity.error}. The arm analysis is unaffected.</Notice> : undefined}
        actions={(state) => <Button onClick={() => exportAnalysis(state)}>Export analysis</Button>}
        views={views}
        presets={presets}
        defaultPreset="pareto"
        tableSummary={(state) => state.viewId === 'depth' ? `Buffer-depth sweep · ${sensitivityPoints.length} measurements` : 'Workload arm data'}
        table={(state, select) => state.viewId === 'depth'
          ? <BufferDepthTable points={sensitivityPoints} runs={arms.map(arm => arm.run)} />
          : <ArmTable arms={arms} state={state} select={select} />}
      />
    </Section>

    <Section title="Power and energy characteristics">
      <div className="wb-context">
        <Field label="Inspect topology"><select value={focusRun?.run.topology ?? ''} onChange={event => setFocus(event.target.value)}>
          {arms.map(arm => <option key={arm.run.topology} value={arm.run.topology}>{arm.run.topology_label ?? arm.run.topology}</option>)}
        </select></Field>
        {focusRun && <span className="muted">{focusRun.run.vcs ?? '—'} VCs · {focusRun.run.routing ?? 'routing not reported'}</span>}
      </div>
      {!focusRun ? <Notice tone="amber">No arm to inspect.</Notice> : <>
        <div className="power-characteristics-layout">
          <div className="power-composition-card">
            <h3>Power composition <span>{number(focusRun.run.native_power_w, 3)} W total</span></h3>
            <PowerShareBar arm={focusRun} />
            <div className="table-scroll"><table className="power-component-table" aria-label="Power composition by component">
              <thead><tr><th>Component</th><th>Power</th><th>Share</th><th><span className="visually-hidden">Proportion</span></th></tr></thead>
              <tbody>{componentRows.map(row => <tr key={row.label}>
                <th><i className="power-swatch" style={{ background: row.tone }} aria-hidden="true" />{row.label}</th>
                <td className="numeric">{row.value === null ? '—' : `${number(row.value, 3)} W`}</td>
                <td className="numeric">{row.share === null ? '—' : `${number(row.share, 1)}%`}</td>
                <td><span className="power-share-track"><i style={{ width: `${row.share ?? 0}%`, background: row.tone }} /></span></td>
              </tr>)}
              <tr className="total"><th>Total</th><td className="numeric">{number(focusRun.breakdownTotalW, 3)} W</td><td className="numeric">100%</td><td /></tr>
              </tbody>
            </table></div>
            <div className="power-balance">
              <div className="power-balance-bar" role="img" aria-label={`Dynamic ${number(sharePercent(focusRun.dynamicPowerW, focusRun.breakdownTotalW), 1)}%, leakage ${number(sharePercent(focusRun.leakagePowerW, focusRun.breakdownTotalW), 1)}%`}>
                <span className="dynamic" style={{ width: `${sharePercent(focusRun.dynamicPowerW, focusRun.breakdownTotalW) ?? 0}%` }} />
                <span className="leakage" style={{ width: `${sharePercent(focusRun.leakagePowerW, focusRun.breakdownTotalW) ?? 0}%` }} />
              </div>
              <div className="power-balance-key">
                <span><i className="dynamic" />Dynamic <strong>{focusRun.dynamicPowerW === null ? '—' : `${number(sharePercent(focusRun.dynamicPowerW, focusRun.breakdownTotalW), 1)}%`}</strong></span>
                <span><i className="leakage" />Leakage <strong>{focusRun.leakagePowerW === null ? '—' : `${number(sharePercent(focusRun.leakagePowerW, focusRun.breakdownTotalW), 1)}%`}</strong></span>
              </div>
            </div>
          </div>
          <div className="power-ratios-card">
            <h3>Ratios and intensity</h3>
            <Properties rows={[
              ['Dynamic / leakage', focusRun.dynamicPowerW === null || !focusRun.leakagePowerW ? 'Not reported' : `${number(focusRun.dynamicPowerW, 3)} W / ${number(focusRun.leakagePowerW, 3)} W · ${number(focusRun.dynamicPowerW / focusRun.leakagePowerW, 2)}×`],
              ['Wire / switch / buffer', focusRun.wirePowerW === null ? 'Not reported' : `${number(sharePercent(focusRun.wirePowerW, focusRun.breakdownTotalW), 1)}% / ${number(sharePercent(focusRun.switchPowerW, focusRun.breakdownTotalW), 1)}% / ${number(sharePercent(focusRun.bufferPowerW, focusRun.breakdownTotalW), 1)}%`],
              ['Energy per packet', focusRun.energyPerPacketPj === null ? 'Not reported' : formatPj(focusRun.energyPerPacketPj)],
              ['Energy per flit', focusRun.energyPerFlitPj === null ? 'Not reported' : formatPj(focusRun.energyPerFlitPj)],
              ['Energy per hop', focusRun.energyPerHopPj === null ? 'Not reported' : formatPj(focusRun.energyPerHopPj)],
              ['Energy per bit', focusRun.energyPerBitPj === null ? 'Not reported' : `${number(focusRun.energyPerBitPj, 4)} pJ/bit`],
              ['Power–delay product', focusRun.pdpPj === null ? 'Not reported' : formatPj(focusRun.pdpPj)],
              ['Total network energy', formatPj(focusRun.totalEnergyPj)],
              ['Power per router', focusRun.powerPerRouterW === null ? 'Not reported' : `${number(focusRun.powerPerRouterW, 3)} W/router`],
              ['Area / per router', focusRun.run.native_area_mm2 === null || focusRun.run.native_area_mm2 === undefined ? 'Not reported' : `${number(focusRun.run.native_area_mm2, 4)} mm² · ${number(focusRun.areaPerRouterMm2, 5)} mm²/router`],
              ['Completion', `${number(focusRun.run.completion_cycles, 0)} cyc · ${formatDurationNs(focusRun.run.completion_cycles, focusRun.clockHz)}`],
              ['Power-counter interval', focusRun.run.power_cycles ? `${number(focusRun.run.power_cycles, 0)} cyc` : 'Not reported'],
            ]} />
          </div>
        </div>
      </>}
    </Section>

    <Assumptions>
      <h3>Scope</h3>
      <p>This is a repository trace replay, not a measurement of the loaded project revision or its declared workload. Every point is one measured topology for the selected workload; latency, hops and throughput are measured while power, area and energy use the native BookSim 32 nm model with no compute or DRAM. Project-specific study results are in Explore → Revision study. {projectWorkload ? `Loaded revision workload: ${projectWorkload}.` : 'The loaded revision declares no named workload.'}</p>
      <h3>Power, voltage and time <Badge tone="amber">fixed corner</Badge> <Badge>no voltage sweep</Badge></h3>
      <Properties rows={[
        ['Process (P)', doc.model?.technology ?? 'Not reported'],
        ['Voltage (V)', `${number(doc.corner?.vdd_v, 2)} V · fixed technology constant`],
        ['Temperature (T)', `${number(doc.corner?.temperature_c, 0)} °C · fixed technology constant`],
        ['Model clock', `${number(clockHz / 1e9, 4)} GHz · ${doc.model?.clock_rule ?? 'rule not reported'}`],
        ['Flit width', `${number(doc.model?.channel_width_bits, 0)} bit`],
        ['Wire length per latency cycle', `${number(doc.model?.wire_length_mm_per_latency_cycle, 2)} mm`],
        ['Energy definition', doc.model?.energy_definition ?? 'Not reported'],
      ]} />
      <p>No P–V or P–T curve exists in this evidence. Vdd and temperature are fixed tech-file constants; this repository has no voltage or temperature sweep for these workloads.</p>
      <p><strong>Model limitations:</strong> {doc.model?.limitations ?? 'No limitations text is recorded.'}</p>
      <h3>Comparison and derived values</h3>
      <ul>
        <li>Arms differ in radix, VC count and buffering. The comparison is not resource-equalised and is not a hardware qualification or a global optimum.</li>
        <li>Power, area and energy exist only where the native model reported them. Missing values are omitted from those axes, not plotted as zero. Unstable windows are not plotted.</li>
        <li>Power counters span the full simulation, not only the steady-state packet window. Component shares use the parsed component total; energy per bit uses the recorded flit width.</li>
        <li>Energy per packet, flit, bit and hop, power–delay product, throughput per watt and energy index are derived from native model power and measured counts. None is a new measurement.</li>
        <li>VC counts are canonical per family and not equalised. The buffer-depth comparison is a separate measured sweep for the five product arms; storage is declared capacity, not occupancy. Cross-depth comparisons hold trace, topology, binary and seed per arm.</li>
      </ul>
    </Assumptions>
  </div>;
}
