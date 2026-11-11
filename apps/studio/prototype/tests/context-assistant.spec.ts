import { expect, test } from '@playwright/test';

// A minimal live project whose sampled counters have the same packed channel
// ids as the native mesh: R0 port 0 (east), R0 port 4 (eject), R1 port 1
// (west), R1 port 4 (eject). The picker must join these by declared neighbour,
// not by the topology's own src_port numbering.
const PROJECT = {
  project: { project_id: 'p-context', name: 'Context picker project', created_at: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-02T00:00:00+00:00' },
  active_revision_id: 'p-context-r01',
  active_revision: {
    revision_id: 'p-context-r01', display_name: 'r01',
    design: { agents: [{ kind: 'compute_tile', count: 2 }], locked_derived: { routing: 'DOR_XY', vc_count: 2, certificate_overall: 'PASS' } },
  },
  runs: [{ run_id: 'run-context', revision_id: 'p-context-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', qualification: 'QUALIFIED', requirements_pass: true, completed_at: '2026-01-02T10:00:00+00:00', bundle_id: 'bundle-context', display_name: 'context run' }],
};

const REQUEST = {
  schema_version: 4, compiler_semantics_version: 3,
  topology: { kind: 'mesh', side_length: 2, concentration: 1 },
  agents: [{ kind: 'compute_tile', count: 2, data_width: 64, addr_width: 32, protocol: 'AXI' }],
  physical: { clock_freq_mhz: 1000, data_width: 64, num_power_domains: 1, process_node_nm: 7 },
  noc_controls: { link_width: 64 },
  address_map: { ranges: [] },
  requirements: [],
  workload: { model_name: 'context-model', tp: 1, dp: 1, ep: 1, pp: 1, collectives: [] },
  dependencies: [],
};

const TOPOLOGY = {
  contract_version: 1, family: 'mesh', counts: { routers: 4, channels: 8, endpoints: 2, seats: 3 },
  routers: [
    { router_id: 0, coordinates: [0, 0], seat_capacity: 2 },
    { router_id: 1, coordinates: [1, 0], seat_capacity: 1 },
    { router_id: 2, coordinates: [0, 1], seat_capacity: 1 },
    { router_id: 3, coordinates: [1, 1], seat_capacity: 1 },
  ],
  channels: [
    { channel_id: 0, src_router: 0, dst_router: 1, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 1, src_router: 1, dst_router: 0, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 2, src_router: 0, dst_router: 2, src_port: 2, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 3, src_router: 2, dst_router: 0, src_port: 1, dst_port: 2, width_bits: 64, latency_cycles: 1 },
    { channel_id: 4, src_router: 1, dst_router: 3, src_port: 2, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 5, src_router: 3, dst_router: 1, src_port: 1, dst_port: 2, width_bits: 64, latency_cycles: 1 },
    { channel_id: 6, src_router: 2, dst_router: 3, src_port: 2, dst_port: 1, width_bits: 64, latency_cycles: 1 },
    { channel_id: 7, src_router: 3, dst_router: 2, src_port: 1, dst_port: 2, width_bits: 64, latency_cycles: 1 },
  ],
  endpoints: [
    { endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 },
    { endpoint_id: 1, router_id: 3, kind: 'hbm_controller', port_id: 0 },
  ],
  physical_links: [], shared_links: [],
};

const LOAD = {
  run: 'run-context', source: 'measured', link_capacity_flits_per_cycle: 1,
  sample_period_cycles: 100, num_windows: 10, cycles_sampled: 1000,
  channels: [
    { logical_channel_id: 0, flits_total: 100, cycles_sampled: 1000, utilization: 0.5, peak_window_utilization: 0.75, queue_cycles_total: 1000, arb_wait_cycles_total: 100, per_hop_latency_mean_cycles: 4, peak_per_hop_latency_cycles: 8 },
    { logical_channel_id: 4, flits_total: 50, cycles_sampled: 1000, utilization: 0.2, peak_window_utilization: 0.3, queue_cycles_total: 100 },
    { logical_channel_id: 10001, flits_total: 20, cycles_sampled: 1000, utilization: 0.1, peak_window_utilization: 0.2, queue_cycles_total: 10 },
    { logical_channel_id: 10004, flits_total: 30, cycles_sampled: 1000, utilization: 0.1, peak_window_utilization: 0.2, queue_cycles_total: 20 },
  ],
};

test('picks a router and answers from measured counters, then picks a section without raw SVG text', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: { BOOKSIM_STANDALONE: { state: 'PRESENT', binary_present: true } } } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-context/draft', route => route.fulfill({ json: { contract_version: 1, request: REQUEST, design_hash: 'draft-context' } }));
  await page.route('**/gw/api/v1/projects/p-context', route => route.fulfill({ json: PROJECT }));
  await page.route('**/gw/api/v1/projects/p-context/jobs?*', route => route.fulfill({ json: { contract_version: 1, jobs: [] } }));
  await page.route('**/gw/api/v1/revisions/p-context-r01/topology', route => route.fulfill({ json: TOPOLOGY }));
  await page.route('**/gw/api/v1/revisions/p-context-r01/compile-result', route => route.fulfill({ json: { groups: { resources: { vc_count: 2 } } } }));
  await page.route('**/gw/api/v1/runs/run-context', route => route.fulfill({ json: { run_id: 'run-context', project_id: 'p-context', revision_id: 'p-context-r01', backend: 'BOOKSIM_STANDALONE', status: 'EVALUATED', qualification: 'QUALIFIED', requirements_pass: true, evaluation: { status: 'EVALUATED', metrics: { completion_cycles: 1000, sample_window_cycles: 1000 } }, requirements: { entries: [] }, analyses: [] } }));
  await page.route('**/gw/api/v1/runs/run-context/traffic-matrix', route => route.fulfill({ json: { run_id: 'run-context', revision_id: 'p-context-r01', availability: 'MEASURED', nodes: 2, packets: 10, flits: 200, distinct_pairs: 2, pairs: [{ src: 0, dst: 1, packets: 5, flits: 100 }, { src: 1, dst: 0, packets: 5, flits: 100 }] } }));
  await page.route('**/gw/api/v1/runs/run-context/integrity', route => route.fulfill({ json: { run_id: 'run-context' } }));
  await page.route('**/gw/api/v1/runs/run-context/artifacts', route => route.fulfill({ json: { run_id: 'run-context', bundle: null } }));
  await page.route('**/gw/api/v1/loom/simulation/load*', route => route.fulfill({ json: LOAD }));
  await page.route('**/gw/api/v1/agents/capabilities', route => route.fulfill({ json: { configured: false, transport: 'openai', reason: 'Configure VERITX_AI_BASE_URL and VERITX_AI_MODEL on the server.' } }));

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-context-r01 · live store')).toBeVisible();

  await page.goto('/#/design/fabric-topology');
  await page.getByRole('button', { name: 'Pick context for the assistant' }).click();
  await page.locator('.gateway-node').first().click();
  await expect(page.locator('.assistant-drawer')).toBeVisible();
  await expect(page.locator('.context-chip', { hasText: 'Router R0' })).toBeVisible();

  await page.getByRole('button', { name: 'What traffic leaves R0?' }).click();
  const answer = page.locator('.assistant-answer').last();
  await expect(answer).toContainText('150 measured flits');
  await expect(answer).toContainText('2 active source-port channels');
  await expect(answer).toContainText('Local ejection accounts for 50 flits');

  await page.getByRole('button', { name: 'Preview context' }).click();
  const pack = page.locator('.assistant-picked-pack .assistant-context-json');
  await expect(pack).toContainText('srota-studio/assistant-context/v1');
  await expect(pack).toContainText('"kind": "router"');

  // Shift-click keeps the picker open so a small set can be assembled in one
  // pass; Escape returns to the drawer with both objects attached.
  await page.locator('.assistant-drawer').getByRole('button', { name: 'Pick context' }).click();
  await page.locator('.gateway-node').nth(1).click({ modifiers: ['Shift'] });
  await page.keyboard.press('Escape');
  await expect(page.locator('.context-chip', { hasText: 'Router R1' })).toBeVisible();
  await expect(page.locator('.context-chip', { hasText: 'Router R0' })).toBeVisible();

  await page.getByRole('button', { name: 'Clear picks' }).click();
  await expect(page.locator('.context-chip', { hasText: 'Router R0' })).toHaveCount(0);

  await page.goto('/#/analysis/topology');
  await expect(page.getByRole('heading', { name: 'Per-router measured load' })).toBeVisible();
  await page.getByRole('button', { name: 'Pick context for the assistant' }).click();
  await page.getByRole('heading', { name: 'Per-router measured load' }).click();
  await expect(page.locator('.context-chip', { hasText: 'Per-router measured load' })).toBeVisible();
  await page.getByRole('button', { name: 'Summarize this selection' }).click();
  await expect(page.locator('.assistant-answer').last()).toContainText('Only the object identity is attached');
  await expect(page.locator('.assistant-answer').last()).not.toContainText('R03,216');

  // A section contains cards and table rows. Clicking a card must attach the
  // card, not the enclosing section.
  await page.getByRole('button', { name: 'Clear picks' }).click();
  await expect(page.getByRole('heading', { name: 'Measured delay cost per channel' })).toBeVisible();
  await expect(page.locator('.delay-scatter')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Zoom in' })).toBeVisible();
  await page.getByRole('button', { name: 'Pick context for the assistant' }).click();
  await page.locator('[data-context-kind="metric"][data-context-label="Median queue cost"]').click();
  const cardChip = page.locator('.context-chip', { hasText: 'Median queue cost' });
  await expect(cardChip).toBeVisible();
  await expect(cardChip).not.toContainText('Measured delay cost per channel');
  await page.getByRole('button', { name: 'Summarize this selection' }).click();
  await expect(page.locator('.assistant-answer').last()).toContainText('selected metric card');
});
