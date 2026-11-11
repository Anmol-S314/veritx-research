/** Measured workload power/area/energy evidence.
 *
 *  The workload ablation slice carries latency, hops and throughput but no
 *  power model.  The native-power snapshot joins a matching trace replay that
 *  ran BookSim with ``sim_power=1``, so this module only exposes recorded
 *  values and arithmetic over them.  It never estimates a missing arm.
 */

export type PowerBreakdown = {
  channel_wire_w?: number | null;
  channel_clock_w?: number | null;
  channel_retiming_w?: number | null;
  channel_leakage_w?: number | null;
  input_read_w?: number | null;
  input_write_w?: number | null;
  input_leakage_w?: number | null;
  switch_compute_w?: number | null;
  switch_control_w?: number | null;
  switch_leakage_w?: number | null;
  output_dff_w?: number | null;
  output_clock_w?: number | null;
  output_control_w?: number | null;
  log_total_power_w?: number | null;
  log_total_area_mm2?: number | null;
  log_completion_cycles?: number | null;
};

export type PowerModel = {
  status?: string | null;
  model_id?: string | null;
  technology?: string | null;
  clock_hz?: number | null;
  clock_rule?: string | null;
  channel_width_bits?: number | null;
  wire_length_mm_per_latency_cycle?: number | null;
  energy_definition?: string | null;
  limitations?: string | null;
};

export type WorkloadPowerRun = {
  workload: string;
  workload_label?: string | null;
  topology: string;
  topology_label?: string | null;
  family?: string | null;
  nodes?: number | null;
  vcs?: number | null;
  routing?: string | null;
  vc_buf_size?: number | null;
  status?: string | null;
  qualification?: string | null;
  delivered_packets?: number | null;
  delivered_flits?: number | null;
  effective_packet_size_flits?: number[] | null;
  completion_cycles?: number | null;
  latency_mean?: number | null;
  latency_p50?: number | null;
  latency_p95?: number | null;
  latency_p99?: number | null;
  hops_avg?: number | null;
  throughput_packets_per_cycle?: number | null;
  throughput_flits_per_cycle?: number | null;
  accepted_packet_rate?: number | null;
  resource_cost?: { routers?: number | null; crosspoints?: number | null; storage_flits?: number | null } | null;
  native_power_w?: number | null;
  native_area_mm2?: number | null;
  native_energy_pj_per_cycle?: number | null;
  total_energy_pj?: number | null;
  power_cycles?: number | null;
  native_model?: PowerModel | null;
  source_path?: string | null;
  log?: string | null;
  power_breakdown_w?: PowerBreakdown | null;
};

export type WorkloadPowerDoc = {
  schema: string;
  generated_by?: string;
  generated_from?: string;
  scope?: string;
  corner?: { vdd_v?: number | null; temperature_c?: number | null; source?: string; sha256?: string | null };
  model?: {
    technology?: string | null;
    clock_hz?: number | null;
    clock_rule?: string | null;
    channel_width_bits?: number | null;
    wire_length_mm_per_latency_cycle?: number | null;
    energy_definition?: string | null;
    limitations?: string | null;
    model_ids?: string[];
  };
  workloads: { workload_id: string; label: string; nodes: number; events?: number | null; trace_sha256?: string | null; source_path?: string; arm_count?: number }[];
  topologies: { topology_id: string; label: string; family: string; nodes?: number }[];
  runs: WorkloadPowerRun[];
};

export type DerivedArm = {
  run: WorkloadPowerRun;
  clockHz: number;
  totalEnergyPj: number | null;
  energyPerPacketPj: number | null;
  energyPerFlitPj: number | null;
  energyPerBitPj: number | null;
  energyPerHopPj: number | null;
  pdpPj: number | null;
  throughputPerWatt: number | null;
  powerPerRouterW: number | null;
  areaPerRouterMm2: number | null;
  dynamicPowerW: number | null;
  leakagePowerW: number | null;
  wirePowerW: number | null;
  switchPowerW: number | null;
  bufferPowerW: number | null;
  breakdownTotalW: number | null;
};

const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const positive = (value: unknown): number | null => { const number = finite(value); return number !== null && number > 0 ? number : null; };
const sum = (...values: (number | null | undefined)[]): number | null => {
  const present = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  return present.length ? present.reduce((total, value) => total + value, 0) : null;
};
const ratio = (numerator: number | null, denominator: number | null): number | null =>
  numerator !== null && denominator !== null && denominator !== 0 ? numerator / denominator : null;

export function parseWorkloadPower(value: unknown): WorkloadPowerDoc {
  if (!value || typeof value !== 'object') throw new Error('Workload power evidence must be an object');
  const doc = value as Partial<WorkloadPowerDoc>;
  if (doc.schema !== 'veritx/workload-power/1') throw new Error('Workload power evidence has an unknown schema');
  if (!Array.isArray(doc.workloads) || !Array.isArray(doc.topologies) || !Array.isArray(doc.runs)) {
    throw new Error('Workload power evidence must carry workloads, topologies and runs');
  }
  if (!doc.workloads.length || !doc.runs.length) throw new Error('Workload power evidence is empty');
  for (const run of doc.runs) {
    if (!run || typeof run !== 'object' || typeof run.workload !== 'string' || typeof run.topology !== 'string') {
      throw new Error('Each workload power row needs a workload and topology');
    }
  }
  return doc as WorkloadPowerDoc;
}

export function deriveArm(run: WorkloadPowerRun, fallbackClock: number): DerivedArm {
  const clockHz = positive(run.native_model?.clock_hz) ?? fallbackClock;
  const power = finite(run.native_power_w);
  const cycles = positive(run.power_cycles) ?? positive(run.completion_cycles);
  const totalEnergyPj = finite(run.total_energy_pj)
    ?? (power !== null && cycles !== null ? power * (cycles / clockHz) * 1e12 : null);
  const packets = positive(run.delivered_packets);
  const flits = positive(run.delivered_flits);
  const hops = positive(run.hops_avg);
  const width = positive(run.native_model?.channel_width_bits) ?? 128;
  const latency = positive(run.latency_p95);
  const breakdown = run.power_breakdown_w ?? null;
  const breakdownTotalW = breakdown
    ? sum(breakdown.channel_wire_w, breakdown.channel_clock_w, breakdown.channel_retiming_w,
      breakdown.channel_leakage_w, breakdown.input_read_w, breakdown.input_write_w, breakdown.input_leakage_w,
      breakdown.switch_compute_w, breakdown.switch_control_w, breakdown.switch_leakage_w,
      breakdown.output_dff_w, breakdown.output_clock_w, breakdown.output_control_w)
    : null;
  const leakagePowerW = breakdown
    ? sum(breakdown.channel_leakage_w, breakdown.input_leakage_w, breakdown.switch_leakage_w) : null;
  const dynamicPowerW = breakdownTotalW !== null && leakagePowerW !== null
    ? breakdownTotalW - leakagePowerW : null;
  return {
    run, clockHz,
    totalEnergyPj,
    energyPerPacketPj: ratio(totalEnergyPj, packets),
    energyPerFlitPj: ratio(totalEnergyPj, flits),
    energyPerBitPj: flits !== null ? ratio(totalEnergyPj, flits * width) : null,
    energyPerHopPj: packets !== null && hops !== null ? ratio(totalEnergyPj, packets * hops) : null,
    pdpPj: power !== null && latency !== null ? power * (latency / clockHz) * 1e12 : null,
    throughputPerWatt: power !== null && finite(run.throughput_flits_per_cycle) !== null
      ? (run.throughput_flits_per_cycle as number) * clockHz / 1e9 / power : null,
    powerPerRouterW: ratio(power, positive(run.resource_cost?.routers)),
    areaPerRouterMm2: ratio(finite(run.native_area_mm2), positive(run.resource_cost?.routers)),
    dynamicPowerW,
    leakagePowerW,
    wirePowerW: breakdown ? sum(breakdown.channel_wire_w, breakdown.channel_clock_w, breakdown.channel_retiming_w) : null,
    switchPowerW: breakdown ? sum(breakdown.switch_compute_w, breakdown.switch_control_w,
      breakdown.output_dff_w, breakdown.output_clock_w, breakdown.output_control_w) : null,
    bufferPowerW: breakdown ? sum(breakdown.input_read_w, breakdown.input_write_w) : null,
    breakdownTotalW,
  };
}

export const sharePercent = (part: number | null, total: number | null): number | null =>
  part !== null && total !== null && total !== 0 ? 100 * part / total : null;

export function workloadRuns(doc: WorkloadPowerDoc, workload: string): WorkloadPowerRun[] {
  return doc.runs.filter(run => run.workload === workload);
}

/** One measured workload arm.  Power/area/energy stay absent when the model
 *  did not produce them, so an unsupported family never becomes a zero. */
export function buildArmObservations(doc: WorkloadPowerDoc, workload: string) {
  const runs = workloadRuns(doc, workload);
  const fallbackClock = positive(doc.model?.clock_hz) ?? 1;
  const derived = runs.map(run => deriveArm(run, fallbackClock));
  const withPower = derived.filter(arm => arm.energyPerPacketPj !== null);
  const bestEnergy = withPower.length ? Math.min(...withPower.map(arm => arm.energyPerPacketPj as number)) : null;
  return derived.map((arm, index) => {
    const run = arm.run;
    const quality = withPower.length ? 'measured' : 'power not modeled';
    const values: Record<string, number | null> = {
      vcs: finite(run.vcs),
      latency_p95: finite(run.latency_p95),
      latency_mean: finite(run.latency_mean),
      hops_avg: finite(run.hops_avg),
      throughput_flits_per_cycle: finite(run.throughput_flits_per_cycle),
      completion_cycles: finite(run.completion_cycles),
      native_power_w: finite(run.native_power_w),
      native_area_mm2: finite(run.native_area_mm2),
      total_energy_pj: arm.totalEnergyPj,
      energy_per_packet_pj: arm.energyPerPacketPj,
      energy_per_flit_pj: arm.energyPerFlitPj,
      energy_per_bit_pj: arm.energyPerBitPj,
      energy_per_hop_pj: arm.energyPerHopPj,
      pdp_pj: arm.pdpPj,
      throughput_per_watt: arm.throughputPerWatt,
      power_per_router_w: arm.powerPerRouterW,
      area_per_router_mm2: arm.areaPerRouterMm2,
      dynamic_share_pct: sharePercent(arm.dynamicPowerW, arm.breakdownTotalW),
      leakage_share_pct: sharePercent(arm.leakagePowerW, arm.breakdownTotalW),
      wire_share_pct: sharePercent(arm.wirePowerW, arm.breakdownTotalW),
      switch_share_pct: sharePercent(arm.switchPowerW, arm.breakdownTotalW),
      buffer_share_pct: sharePercent(arm.bufferPowerW, arm.breakdownTotalW),
      energy_index: bestEnergy !== null && arm.energyPerPacketPj !== null ? arm.energyPerPacketPj / bestEnergy : null,
    };
    return {
      id: run.topology,
      label: run.topology_label ?? run.topology,
      sublabel: `${run.vcs ?? '—'} VCs · ${run.routing ?? 'routing not reported'} · ${run.qualification ?? 'qualification not reported'}`,
      series: run.topology_label ?? run.topology,
      values,
      meta: [
        ['Topology', run.topology],
        ['Family', run.family ?? 'Not reported'],
        ['VCs', String(run.vcs ?? 'Not reported')],
        ['Routing', run.routing ?? 'Not reported'],
        ['Buffer depth', `${run.vc_buf_size ?? '—'} flits/VC`],
        ['Power model', run.native_model?.status ?? 'Not reported'],
        ['Model id', run.native_model?.model_id ? `${run.native_model.model_id.slice(0, 16)}…` : 'Not reported'],
        ['Qualification', run.qualification ?? 'Not reported'],
      ] as [string, string][],
      note: arm.totalEnergyPj === null
        ? 'This family is measured in the trace replay, but the native power model did not report power or area for it. Power and energy axes skip it rather than plotting zero.'
        : `${quality}; energy is the native model over the power-counter interval, not a silicon measurement.`,
      index,
      derived: arm,
    };
  });
}

export const WORKLOAD_METRICS = {
  latency_p95: { key: 'latency_p95', label: 'Packet P95 latency', unit: 'cycles', direction: 'MIN' as const, digits: 1 },
  latency_mean: { key: 'latency_mean', label: 'Mean packet latency', unit: 'cycles', direction: 'MIN' as const, digits: 1 },
  hops_avg: { key: 'hops_avg', label: 'Average hops', unit: 'hops/packet', direction: 'MIN' as const, digits: 2 },
  throughput_flits_per_cycle: { key: 'throughput_flits_per_cycle', label: 'Delivered throughput', unit: 'flits/cycle', direction: 'MAX' as const, digits: 2 },
  completion_cycles: { key: 'completion_cycles', label: 'Completion cycles', unit: 'cycles', direction: 'MIN' as const, digits: 0 },
  native_power_w: { key: 'native_power_w', label: 'Modeled power', unit: 'W', direction: 'MIN' as const, digits: 3 },
  native_area_mm2: { key: 'native_area_mm2', label: 'Modeled area', unit: 'mm²', direction: 'MIN' as const, digits: 4 },
  total_energy_pj: { key: 'total_energy_pj', label: 'Total network energy', unit: 'pJ', direction: 'MIN' as const, digits: 0 },
  energy_per_packet_pj: { key: 'energy_per_packet_pj', label: 'Energy per packet', unit: 'pJ/packet', direction: 'MIN' as const, digits: 1 },
  energy_per_flit_pj: { key: 'energy_per_flit_pj', label: 'Energy per flit', unit: 'pJ/flit', direction: 'MIN' as const, digits: 3 },
  energy_per_bit_pj: { key: 'energy_per_bit_pj', label: 'Energy per bit', unit: 'pJ/bit', direction: 'MIN' as const, digits: 4 },
  energy_per_hop_pj: { key: 'energy_per_hop_pj', label: 'Energy per hop', unit: 'pJ/hop', direction: 'MIN' as const, digits: 2 },
  pdp_pj: { key: 'pdp_pj', label: 'Power–delay product', unit: 'pJ (P × P95)', direction: 'MIN' as const, digits: 1 },
  throughput_per_watt: { key: 'throughput_per_watt', label: 'Throughput per watt', unit: 'Gflit/s/W', direction: 'MAX' as const, digits: 2 },
  power_per_router_w: { key: 'power_per_router_w', label: 'Power per router', unit: 'W/router', direction: 'MIN' as const, digits: 3 },
  area_per_router_mm2: { key: 'area_per_router_mm2', label: 'Area per router', unit: 'mm²/router', direction: 'MIN' as const, digits: 5 },
  vcs: { key: 'vcs', label: 'Virtual channels', unit: 'VCs', digits: 0 },
  dynamic_share_pct: { key: 'dynamic_share_pct', label: 'Dynamic power share', unit: '%', direction: 'MIN' as const, digits: 1 },
  leakage_share_pct: { key: 'leakage_share_pct', label: 'Leakage power share', unit: '%', direction: 'MIN' as const, digits: 1 },
  wire_share_pct: { key: 'wire_share_pct', label: 'Wire/clock power share', unit: '%', direction: 'MIN' as const, digits: 1 },
  switch_share_pct: { key: 'switch_share_pct', label: 'Switch/output power share', unit: '%', direction: 'MIN' as const, digits: 1 },
  buffer_share_pct: { key: 'buffer_share_pct', label: 'Buffer read/write share', unit: '%', direction: 'MIN' as const, digits: 1 },
  energy_index: { key: 'energy_index', label: 'Energy index vs best arm', unit: '× best', direction: 'MIN' as const, digits: 2 },
} as const;

export type WorkloadMetricKey = keyof typeof WORKLOAD_METRICS;
export const metricKeys = Object.keys(WORKLOAD_METRICS) as WorkloadMetricKey[];

const FAMILY_ACRONYMS = new Set(['GEC', 'MECS', 'SROTA']);
export const familyLabel = (family: string | undefined, fallback: string): string => {
  const words = (family && family !== '—' ? family : fallback).split(/[_\s]+/).filter(Boolean);
  return words.map((word, index) => FAMILY_ACRONYMS.has(word.toUpperCase()) ? word.toUpperCase()
    : index === 0 ? word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
      : word.toLowerCase()).join(' ');
};

export const formatPj = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(3)} mJ`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(2)} µJ`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(2)} nJ`;
  return `${value.toPrecision(3)} pJ`;
};

export const formatDurationNs = (cycles: number | null | undefined, clockHz: number): string => {
  if (typeof cycles !== 'number' || !Number.isFinite(cycles) || !clockHz) return '—';
  const ns = cycles / clockHz * 1e9;
  return ns >= 1e6 ? `${(ns / 1e6).toFixed(2)} ms` : ns >= 1e3 ? `${(ns / 1e3).toFixed(2)} µs` : `${ns.toFixed(2)} ns`;
};
