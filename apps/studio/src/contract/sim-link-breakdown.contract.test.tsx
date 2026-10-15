/** Measured link split: segments are measured, absences are named. */
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api';
import type { SimLinkView, SimLoadView } from '../api/types';
import { HottestLinkBreakdown, SimLinkBreakdown } from '../pages/loom/SimLinkBreakdown';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function linkDoc(): SimLinkView {
  return {
    run: 'run-9',
    source: 'measured',
    logical_channel_id: 30004,
    utilization: 0.8174,
    total_flits: 50005,
    stalls_total: null,
    breakdown: {
      source: 'measured',
      queue_cycles: 21,
      arb_wait_cycles: 6,
      tx_flits: 60,
      tx_busy_cycles: 40,
      per_hop_latency_mean_cycles: 0.45,
      mean_queued_flits_per_output: 3.0,
      peak_queued_flits: 6,
      peak_arb_wait_cycles: 5,
      peak_per_hop_latency_cycles: 15,
    },
    breakdown_absence: null,
    capacity_formula: 'flits_per_window/(window_cycles*link_capacity_flits_per_cycle)',
    sample_period_cycles: 100,
    num_windows: 42,
    cycles_sampled: 4123,
    time_resets_observed: 0,
  };
}

function loadDoc(channels: SimLoadView['channels']): SimLoadView {
  return {
    run: 'run-9',
    source: 'measured',
    capacity_formula: 'f',
    link_capacity_flits_per_cycle: 1,
    sample_period_cycles: 100,
    num_windows: 42,
    cycles_sampled: 4123,
    time_resets_observed: 0,
    channels,
    provenance: {},
  };
}

function row(id: number, latency: number | null, util: number): SimLoadView['channels'][number] {
  return {
    logical_channel_id: id,
    flits_total: 100,
    cycles_sampled: 4123,
    utilization: util,
    peak_window_utilization: util,
    has_stalls: false,
    has_split: latency != null,
    queue_cycles_total: latency != null ? 21 : null,
    arb_wait_cycles_total: latency != null ? 6 : null,
    tx_flits_total: latency != null ? 60 : null,
    per_hop_latency_mean_cycles: latency,
    mean_queued_flits_per_output: latency != null ? 3.0 : null,
    peak_queued_flits: latency != null ? 6 : null,
    peak_arb_wait_cycles: latency != null ? 5 : null,
    peak_per_hop_latency_cycles: latency != null ? 15 : null,
  };
}

describe('SimLinkBreakdown', () => {
  it('renders the three measured segments with exact cycles', async () => {
    vi.spyOn(api, 'simLink').mockResolvedValue(linkDoc());
    render(<SimLinkBreakdown data={null} runId="run-9" channelId={30004} />);

    const bar = await screen.findByRole('img', { name: /queue 21 cycles, arb-wait 6 cycles, Tx 40 cycles/ });
    expect(bar).toBeTruthy();
    expect(screen.getByText(/head flit present, no credit/)).toBeTruthy();
    expect(screen.getByText(/grantable, ungranted/)).toBeTruthy();
    expect(screen.getByText(/40 busy cycles over 60 grants/)).toBeTruthy();
  });

  it('renders the named absence on a v2 run, never zeros', async () => {
    const doc = linkDoc();
    doc.breakdown = null;
    doc.breakdown_absence = 'the measured queue / arb-wait / Tx split is absent';
    vi.spyOn(api, 'simLink').mockResolvedValue(doc);
    render(<SimLinkBreakdown data={null} runId="run-9" channelId={30004} />);

    expect((await screen.findByRole('note')).textContent).toContain('absent');
    expect(screen.queryByRole('img', { name: /queue / })).toBeNull();
  });

  it('withholds the split when the response belongs to another run', async () => {
    const doc = linkDoc();
    doc.run = 'run-other';
    vi.spyOn(api, 'simLink').mockResolvedValue(doc);
    render(<SimLinkBreakdown data={null} runId="run-9" channelId={30004} />);

    expect((await screen.findByRole('alert')).textContent).toContain('not displayed run run-9');
  });

  it('reports a missing split without substituting numbers', async () => {
    vi.spyOn(api, 'simLink').mockRejectedValue(
      new ApiError(422, 'NO_MEASURED', 'NO_MEASURED: no series for this run'));
    render(<SimLinkBreakdown data={null} runId="run-9" channelId={30004} />);

    expect((await screen.findByRole('alert')).textContent).toContain('NO_MEASURED');
  });
});

describe('HottestLinkBreakdown', () => {
  it('selects the hottest link by mean per-hop latency', async () => {
    vi.spyOn(api, 'simLoad').mockResolvedValue(loadDoc([row(1, 0.2, 0.9), row(2, 0.8, 0.1)]));
    const link = vi.spyOn(api, 'simLink').mockResolvedValue({ ...linkDoc(), logical_channel_id: 2 });
    render(<HottestLinkBreakdown data={null} runId="run-9" />);

    await screen.findByText(/channel/);
    expect(link).toHaveBeenCalledWith('run-9', '2');
  });

  it('falls back to the busiest link when no link carries the split', async () => {
    vi.spyOn(api, 'simLoad').mockResolvedValue(loadDoc([row(1, null, 0.9), row(2, null, 0.1)]));
    const absent = linkDoc();
    absent.logical_channel_id = 1;
    absent.breakdown = null;
    absent.breakdown_absence = 'absent: schema v2 predates the fork counters';
    vi.spyOn(api, 'simLink').mockResolvedValue(absent);
    render(<HottestLinkBreakdown data={null} runId="run-9" />);

    expect((await screen.findByRole('note')).textContent).toContain('absent');
  });

  it('states a missing artifact instead of showing zero waits', async () => {
    vi.spyOn(api, 'simLoad').mockRejectedValue(
      new ApiError(422, 'NO_MEASURED', 'NO_MEASURED: sampler artifact absent'));
    render(<HottestLinkBreakdown data={null} runId="run-9" />);

    expect((await screen.findByRole('alert')).textContent).toContain('NO_MEASURED');
    expect(screen.queryByRole('img', { name: /queue / })).toBeNull();
  });
});
