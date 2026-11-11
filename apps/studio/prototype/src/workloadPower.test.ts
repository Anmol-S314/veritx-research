import { describe, expect, it } from 'vitest';
import {
  buildArmObservations, deriveArm, formatPj, parseWorkloadPower, sharePercent,
  type WorkloadPowerDoc, type WorkloadPowerRun,
} from './workloadPower';

const clock = 10_000_000_000; // 10 GHz keeps the arithmetic readable.
const row = (overrides: Partial<WorkloadPowerRun> = {}): WorkloadPowerRun => ({
  workload: 'demo', topology: 'mesh', family: 'MESH', nodes: 16, vcs: 2,
  routing: 'dor', vc_buf_size: 8, status: 'ok', delivered_packets: 1000,
  delivered_flits: 5000, completion_cycles: 2000, latency_p95: 100, hops_avg: 2,
  throughput_flits_per_cycle: 2.5, native_power_w: 10, native_area_mm2: 0.5,
  total_energy_pj: 2_000_000, power_cycles: 2000,
  native_model: { status: 'AVAILABLE', clock_hz: clock, channel_width_bits: 128, model_id: 'm1' },
  power_breakdown_w: {
    channel_wire_w: 5, channel_clock_w: 1, channel_retiming_w: 0.2, channel_leakage_w: 0.3,
    input_read_w: 0.5, input_write_w: 0.5, input_leakage_w: 0.2,
    switch_compute_w: 0.9, switch_control_w: 0.4, switch_leakage_w: 0.4,
    output_dff_w: 0.2, output_clock_w: 0.3, output_control_w: 0.1,
    log_total_power_w: 10, log_total_area_mm2: 0.5, log_completion_cycles: 2000,
  },
  resource_cost: { routers: 4 },
  ...overrides,
});
const doc = (runs: WorkloadPowerRun[]): WorkloadPowerDoc => ({
  schema: 'veritx/workload-power/1',
  workloads: [{ workload_id: 'demo', label: 'Demo', nodes: 16 }],
  topologies: [{ topology_id: 'mesh', label: 'Mesh', family: 'MESH' }],
  model: { clock_hz: clock, channel_width_bits: 128 },
  runs,
});

describe('workload power evidence', () => {
  it('derives per-packet, per-flit, per-bit and per-hop energy from measured counts', () => {
    const arm = deriveArm(row(), clock);
    expect(arm.energyPerPacketPj).toBe(2000);
    expect(arm.energyPerFlitPj).toBe(400);
    expect(arm.energyPerBitPj).toBe(400 / 128);
    expect(arm.energyPerHopPj).toBe(1000);
    expect(arm.pdpPj).toBeCloseTo(100_000);
    expect(arm.throughputPerWatt).toBeCloseTo(2.5 * clock / 1e9 / 10);
  });

  it('separates dynamic, leakage, wire, switch and buffer power without inventing a share', () => {
    const arm = deriveArm(row(), clock);
    expect(arm.breakdownTotalW).toBeCloseTo(10);
    expect(arm.leakagePowerW).toBeCloseTo(0.9);
    expect(arm.dynamicPowerW).toBeCloseTo(9.1);
    expect(arm.wirePowerW).toBeCloseTo(6.2);
    expect(arm.switchPowerW).toBeCloseTo(1.9);
    expect(arm.bufferPowerW).toBeCloseTo(1);
    expect(sharePercent(arm.leakagePowerW, arm.breakdownTotalW)).toBeCloseTo(9);
    expect(sharePercent(10, 0)).toBeNull();
  });

  it('keeps an arm without native power visible but leaves power and energy absent', () => {
    const observations = buildArmObservations(doc([
      row(),
      row({ topology: 'ring', family: 'RING', native_power_w: null, native_area_mm2: null, total_energy_pj: null, power_breakdown_w: null }),
    ]), 'demo');
    expect(observations).toHaveLength(2);
    expect(observations[1].values.native_power_w).toBeNull();
    expect(observations[1].values.energy_per_packet_pj).toBeNull();
    expect(observations[1].values.latency_p95).toBe(100);
    expect(observations[1].note).toContain('skip it rather than plotting zero');
  });

  it('normalises energy against the lowest measured arm only', () => {
    const observations = buildArmObservations(doc([
      row(),
      row({ topology: 'torus', native_power_w: 20, total_energy_pj: 4_000_000 }),
      row({ topology: 'ring', native_power_w: null, total_energy_pj: null }),
    ]), 'demo');
    expect(observations[0].values.energy_index).toBe(1);
    expect(observations[1].values.energy_index).toBe(2);
    expect(observations[2].values.energy_index).toBeNull();
  });

  it('rejects a document with the wrong schema or no rows', () => {
    expect(() => parseWorkloadPower({ schema: 'other', workloads: [], topologies: [], runs: [] })).toThrow(/schema/);
    expect(() => parseWorkloadPower({ schema: 'veritx/workload-power/1', workloads: [{}], topologies: [], runs: [] })).toThrow(/empty/);
  });

  it('formats pJ without pretending it is a silicon measurement', () => {
    expect(formatPj(2_000_000)).toBe('2.00 µJ');
    expect(formatPj(1500)).toBe('1.50 nJ');
    expect(formatPj(null)).toBe('—');
  });
});
