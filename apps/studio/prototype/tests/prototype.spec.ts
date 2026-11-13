import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { PAGES, STORAGE_KEY } from '../src/model';

const EXPORTS = fileURLToPath(new URL('../../../../docs/design/stitch_veritx_studio_eda_frontend/', import.meta.url));
const PROMPT_ONLY = [
  'flow_start_workload', 'flow_fine_tune', 'flow_fabric_search', 'flow_optimize', 'flow_run_analyze', 'flow_compare_versions',
  'workloads_requirements_project_workflow', 'analysis_curves_pareto', 'analysis_workload_ablations', 'analysis_gr00t_architecture_trace', 'explore_project_fabric', 'explore_fabric_ablations', 'explore_workload_search_recommendations', 'explore_revision_recommendation_study',
  'design_agent_fabric_map', 'analysis_fabric_static_checks', 'design_workflow_flow',
];
const UNROUTED_EXPORTS = ['explore_versioned_exploration_brief_stu_088'];

test('every supplied design export has exactly one route', () => {
  const supplied = readdirSync(EXPORTS).filter(d => existsSync(`${EXPORTS}${d}/code.html`));
  expect(supplied.length).toBeGreaterThan(40);
  const routable = supplied.filter(dir => !UNROUTED_EXPORTS.includes(dir));
  expect(supplied.filter(dir => UNROUTED_EXPORTS.includes(dir))).toEqual(UNROUTED_EXPORTS);
  for (const dir of routable) expect(PAGES.filter(p => p.source === dir), `no route for export ${dir}`).toHaveLength(1);
  expect(PAGES.filter(p => !supplied.includes(p.source)).map(p => p.source).sort()).toEqual([...PROMPT_ONLY].sort());
});

test('all imported routes render at both desktop widths without external requests or page overflow', async ({ page }, testInfo) => {
  test.setTimeout(120000);
  const errors: string[] = [], external: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) { external.push(url.origin); await route.abort(); }
    else await route.continue();
  });
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 800 });
    for (const route of PAGES) {
      await page.goto(`/#/${route.id}`);
      const expectedTitle = route.id === 'flow/compare' ? 'Evaluate & choose fabric' : route.title;
      await expect(page.getByRole('heading', { level: 1, name: expectedTitle, exact: true })).toBeVisible();
      await expect(page.getByText('Sample project · local browser state', { exact: true })).toBeVisible();
      const size = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth }));
      expect(size.width, `${route.id} at ${width}`).toBeLessThanOrEqual(size.viewport);
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: testInfo.outputPath(`${route.id.replace('/', '-')}-${width}.png`), animations: 'disabled' });
    }
  }
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

test('local Design overview makes compile and RTL boundaries actionable', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/design/system');
  await expect(page.getByRole('heading', { name: 'Design → compiler → RTL preview', exact: true })).toBeVisible();
  await expect(page.getByText('Illustrative local draft', { exact: true })).toBeVisible();
  await expect(page.getByText('Not compiled', { exact: true })).toBeVisible();
  await expect(page.getByText('Preview readiness requires a loaded gateway project', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Load a gateway project', exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: testInfo.outputPath('design-local-overview.png'), animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(await page.locator('.design-handoff-track').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(1);
});

const STUB_PROJECT = {
  project: { project_id: 'p-stub', name: 'Stubbed 2x2 project', created_at: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-02T00:00:00+00:00' },
  active_revision_id: 'p-stub-r01',
  active_revision: { revision_id: 'p-stub-r01', display_name: 'r01', design: { agents: [{ kind: 'compute_tile', count: 2 }, { kind: 'hbm_controller', count: 1 }], locked_derived: { routing: 'DOR_XY', vc_count: 2, certificate_overall: 'PASS' }, noc_guided: { link_width: 64, topology_family: null }, requirements: [{ traffic_class: 'tp_collective', qos_class: 'latency_critical', latency_ceiling_cycles: 50000 }] } },
  runs: [
    { run_id: 'run-2', revision_id: 'p-stub-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', qualification: 'QUALIFIED', requirements_pass: true, completed_at: '2026-01-01T10:00:00+00:00', bundle_id: 'bundle-run-2', display_name: 'older stub run' },
    { run_id: 'run-1', revision_id: 'p-stub-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', qualification: 'QUALIFIED', requirements_pass: true, completed_at: '2026-01-02T10:00:00+00:00', bundle_id: 'bundle-run-1', display_name: 'newer stub run' },
  ],
  optimizations: [
    { optimization_id: 'opt-stub', base_revision_id: 'p-stub-r01', created_at: '2026-01-02T09:00:00+00:00', candidate_count: 2, pareto_count: 1, selected_candidate_id: 'cand-b' },
    { optimization_id: 'opt-pareto', base_revision_id: 'p-stub-r01', created_at: '2026-01-02T09:10:00+00:00', candidate_count: 2, pareto_count: 2, selected_candidate_id: 'cand-c' },
    { optimization_id: 'opt-thin', base_revision_id: 'p-stub-r01', created_at: '2026-01-02T09:20:00+00:00', candidate_count: 3, pareto_count: 0, selected_candidate_id: null },
  ],
  latest_optimization_study: { optimization_id: 'opt-stub', base_revision_id: 'p-stub-r01', created_at: '2026-01-02T09:00:00+00:00', candidate_count: 2, pareto_count: 1, selected_candidate_id: 'cand-b' },
};
const STUB_REQUEST = { schema_version: 1, compiler_semantics_version: 3, topology: { kind: 'mesh', side_length: 2, concentration: 1 }, agents: [{ kind: 'compute_tile', count: 3, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: null, power_domain: null }, { kind: 'hbm_controller', count: 1, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: 'clk_core', power_domain: null }], physical: { clock_freq_mhz: 1000, data_width: 256, num_power_domains: 1, process_node_nm: 7 }, noc_controls: { link_width: 64, arbitration: null, output_formats: ['json'], obfuscation_level: 0 }, address_map: { ranges: [{ name: 'HBM', base: '0x100000000', size_bytes: 17179869184, target: 'hbm_controller' }] }, requirements: [{ traffic_class: 'tp_collective', qos_class: 'latency_critical', binding: true, latency_ceiling_cycles: 50000, bandwidth_floor_gbps: null }, { traffic_class: 'ep_dispatch', qos_class: 'latency_critical', binding: false, latency_ceiling_cycles: null, bandwidth_floor_gbps: 12 }, { traffic_class: 'tile_ingest', qos_class: 'bandwidth', binding: false, latency_ceiling_cycles: null, bandwidth_floor_gbps: 40 }], workload: { model_name: 'stub-model-30b', model_family: 'mixture_of_experts', serving_mode: 'mixed', tp: 2, dp: 1, ep: 2, pp: 1, workload_source_ref: null, collectives: [{ kind: 'allreduce', dimension: 'TP', payload_bytes: 4096, traffic_class: 'tp_collective', source_rank: null }, { kind: 'alltoall', dimension: 'EP', payload_bytes: 2048, traffic_class: 'ep_dispatch', source_rank: null }] }, compute: { source: 'compiler', stages: [{ stage_id: 'layer0_attn', owner: 0, duration_ns: 1000, input_bytes: 4096, output_bytes: 4096, weight_bytes: 0, input_loc: 'LOCAL', output_loc: 'LOCAL', weight_loc: 'LOCAL' }, { stage_id: 'layer0_moe', owner: 1, duration_ns: 3000, input_bytes: 4096, output_bytes: 2048, weight_bytes: 1024, input_loc: 'LOCAL', output_loc: 'LOCAL', weight_loc: 'REMOTE' }] }, dependencies: [] };
const STUB_TOPOLOGY = {
  contract_version: 1, family: 'mesh', counts: { routers: 4, channels: 8, endpoints: 3, seats: 4 },
  routers: [{ router_id: 0, coordinates: [0, 0], seat_capacity: 1 }, { router_id: 1, coordinates: [1, 0], seat_capacity: 1 }, { router_id: 2, coordinates: [0, 1], seat_capacity: 1 }, { router_id: 3, coordinates: [1, 1], seat_capacity: 2 }],
  channels: [[0, 1], [1, 0], [0, 2], [2, 0], [1, 3], [3, 1], [2, 3], [3, 2]].map(([a, b], i) => ({ channel_id: i, src_router: a, dst_router: b, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1, route_weight: 1, physical_link_id: null })),
  endpoints: [{ endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 }, { endpoint_id: 1, router_id: 3, kind: 'compute_tile', port_id: 0 }, { endpoint_id: 2, router_id: 3, kind: 'hbm_controller', port_id: 1 }],
  physical_links: [],
};

test('a loaded gateway project drives the live Design surfaces without fixture leakage', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  let draftDirty = true;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: { BOOKSIM_STANDALONE: { state: 'PRESENT', binary_present: true } } } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST, dirty: draftDirty, design_hash: 'draft-p-stub-02' } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/projects/p-stub/catalog-evaluation-plan', route => route.fulfill({ json: {
    draft_design_hash: 'draft-p-stub-02', workload_id: 'wl-stub', participant_count: 2, operation_count: 1, compute_stages: 2,
    topologies: [], selection: { job_id: 'job-stub', candidate_id: 'candidate-stub', topology_id: 'mesh', label: 'Mesh', workload_id: 'wl-stub' }, backends: [],
  } }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/compile-result', route => route.fulfill({ json: { available: true, revision_id: 'p-stub-r01', certificate: { overall: 'PASS' }, stage1_verdicts: [{ module: 'address_permission', ok: true, status: 'PASS', reason: null, findings: [], stopped_at_stage: 'COMPLETE' }], stage1_findings: ["AGENT_PROTOCOL_UNOWNED: group 0 ('AXI') declare legacy Agent.protocol literals with no matching agent_intents entry"] } }));
  await page.route('**/gw/api/v1/projects/p-stub/rtl-readiness', route => route.fulfill({ json: { revision_id: 'p-stub-r01', draft_design_hash: 'stub-hash', final_rtl_available: false, final_rtl_reason: 'General implementation RTL is not available.', preview_available: true, preview_blockers: [], limitations: ['Topology-only preview'], selection: null, preview_support: { supported: true, code: 'SUPPORTED', reason: null, vc_count: 2, emitted_vcs: 2, matches_certified_vc_count: true, shared_wire_links: 0, connected: true, reciprocal: true, router_count: 4 } } }));

  await page.goto('/#/shared/projects');
  await expect(page.getByText('Stubbed 2x2 project', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();
  await expect(page.locator('.header-revision')).toContainText('live store');
  await expect(page.getByText('Sample project · local browser state', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Address checks', { exact: true })).toBeVisible();

  await page.goto('/#/design/fabric-topology');
  await expect(page.getByText('Live project data · Stubbed 2x2 project', { exact: false })).toHaveCount(0);
  await expect(page.locator('.header-revision')).toHaveText('p-stub-r01 · live store');
  await expect(page.locator('.gateway-nodes circle')).toHaveCount(4);
  await expect(page.locator('.gateway-links path')).toHaveCount(4);
  await expect(page.locator('.fabric-toolbar').getByText('mesh · 4 routers · 8 directed channels · 3 endpoints')).toBeVisible();
  await expect(page.getByText('Saved draft differs from active revision p-stub-r01.', { exact: false })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('.gateway-node').nth(3).click();
  await expect(page.locator('.inspector h3')).toHaveText('R3');
  await expect(page.getByText('Not declared in this payload').first()).toBeVisible();
  await page.getByRole('link', { name: 'Open agent and RTL reach map' }).click();
  await expect(page.getByRole('heading', { name: 'Agent fabric map', exact: true })).toBeVisible();
  await expect(page.getByText('Saved draft · compile pending', { exact: true })).toBeVisible();
  await expect(page.getByText('Compiler and preview evidence below still belongs to that active revision', { exact: false })).toBeVisible();
  await page.getByLabel(/Window name/).first().fill('HBM pending');
  await expect(page.locator('.view-main > .toolbar').getByText('Unsaved edits', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Inspect physical fabric topology' }).click();
  await page.goto('/#/design/agent-map');
  await expect(page.getByLabel(/Window name/).first()).toHaveValue('HBM pending');
  await expect(page.locator('.view-main > .toolbar').getByText('Unsaved edits', { exact: true })).toBeVisible();
  await page.getByLabel(/Window name/).first().fill('HBM');
  await expect(page.locator('.view-main > .toolbar').getByText('Saved draft · compile pending', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /^Agents/ }).click();
  await expect(page.getByRole('heading', { name: 'Protocol ownership' })).toBeVisible();
  await expect(page.getByText(/AGENT_PROTOCOL_UNOWNED/)).toBeVisible();
  await page.getByRole('button', { name: 'Control reach' }).click();
  await expect(page.getByRole('columnheader', { name: 'Draft declaration', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Check preview readiness', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Design → compiler → RTL preview', exact: true })).toBeVisible();
  await expect(page.locator('.design-handoff-track .design-handoff-step').first()).toContainText('Saved draft differs from the active revision');
  await page.getByRole('link', { name: 'Open RTL handoff', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Finalize topology & RTL', exact: true })).toBeVisible();
  await expect(page.getByText('Compile the selected fabric\'s saved parameters before final validation.', { exact: false })).toBeVisible();

  draftDirty = false;
  await page.reload();
  await expect(page.locator('.header-revision')).toHaveText('p-stub-r01 · live store');
  await expect(page.getByRole('link', { name: 'Open delivery & RTL preview', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Open delivery & RTL preview', exact: true }).click();
  await expect(page.getByText('Current project preview', { exact: true })).toBeVisible();
  await page.goto('/#/design/agent-map');
  await expect(page.getByText('Matches active revision', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Control reach' }).click();
  await page.getByRole('link', { name: 'Check final RTL handoff', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open delivery & RTL preview', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Open delivery & RTL preview', exact: true }).click();
  await expect(page.getByText('Current project preview', { exact: true })).toBeVisible();
  await page.goto('/#/design/agent-map');
  await page.getByRole('link', { name: 'Inspect physical fabric topology' }).click();
  await expect(page.locator('.fabric-toolbar').getByText('mesh · 4 routers · 8 directed channels · 3 endpoints')).toBeVisible();

  await page.goto('/#/design/system');
  await expect(page.getByRole('heading', { name: 'Design → compiler → RTL preview', exact: true })).toBeVisible();
  await expect(page.locator('.design-handoff-track .design-handoff-step').nth(2).getByText('Preview only · final unavailable', { exact: true })).toBeVisible();
  await expect(page.locator('.design-handoff-note')).toContainText('Final implementation RTL: General implementation RTL is not available.');
  await expect(page.getByRole('link', { name: 'Inspect compiler and RTL control reach' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(await page.locator('.design-handoff-track').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)).toBe(1);

  draftDirty = true;
  await page.reload();
  await expect(page.locator('.design-handoff-track .design-handoff-step').first()).toContainText('Saved draft differs from the active revision');
  await page.goto('/#/design/endpoints');
  await expect(page.getByText('EP-2', { exact: true })).toBeVisible();
  await expect(page.getByText('Seats are compiled, not attached here.', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Declared agents vs materialized seats' })).toBeVisible();
  await expect(page.getByText('1 kind differs', { exact: true })).toBeVisible();
  await expect(page.getByText('Saved draft differs from active revision p-stub-r01.', { exact: false })).toBeVisible();
  await expect(page.getByText('Agent groups come from the saved draft; endpoint seats come from the active revision.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(page.getByText('hbm_controller', { exact: true }).first()).toBeVisible();

  await page.goto('/#/design/mapping');
  await expect(page.getByText('Saved draft differs from active revision p-stub-r01.', { exact: false })).toBeVisible();
  await expect(page.getByText('Channel structure and compiler artifacts describe the active revision; address windows come from the saved draft.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.goto('/#/design/addresses');
  await expect(page.getByRole('rowheader', { name: 'HBM' })).toBeVisible();
  await expect(page.getByText('Saved draft differs from active revision p-stub-r01.', { exact: false })).toBeVisible();
  await expect(page.getByText('Declared windows come from the saved draft; resolved rows and endpoint joins come from the active revision.', { exact: false })).toBeVisible();
  await expect(page.getByText('Edit here.', { exact: false })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open agent map', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: '0x0001_0000_0000', exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.goto('/#/design/domains');
  await expect(page.getByText('1000 MHz')).toBeVisible();
  await expect(page.getByText('clk_core', { exact: false }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.goto('/#/design/placement');
  await expect(page.getByRole('heading', { name: 'Logical router-coordinate map', exact: true })).toBeVisible();
  await expect(page.locator('.logical-placement-canvas')).toBeVisible();
  await expect(page.locator('.logical-placement-node')).toHaveCount(4);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  // The live Agent catalog route is a legacy alias for Agents; the fixture-only
  // add form must not reappear when a gateway project is loaded.
  await page.goto('/#/design/catalog');
  await expect(page.getByRole('button', { name: /^Address windows/ })).toBeVisible();
  await expect(page.getByText('Add an agent group to the draft', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(errors).toEqual([]);
});

const STUB_MEMORY_ANALYSIS = {
  backend_id: 'RAMULATOR2_HBM3_V1', question: 'DRAM_TIMING', status: 'EVALUATED', qualification: 'PASS', model_fidelity: 'MEMORY_CYCLE_SIMULATION',
  limitations: [
    'DRAM timing assumes the certified CERTIFIED_RAMULATOR_HBM3_V1 profile: single HBM3 channel (51.2 GB/s peak at 6400 MT/s x 8 B).',
    'memory cycle simulation over a recorded request stream: row/queue timing is simulated, request generation is assumed.',
    'NoC and memory cycles are separate analyses and are not additive.',
  ],
  native_summary: {
    accepted_requests: 13633536, completed_read_bytes: 872480768, completed_requests: 13633536,
    completed_write_bytes: 65536, completion_cycles: 107321449, generated_requests: 13633536,
    outstanding_requests: 0, row_conflicts: 53200, row_hits: 13580272, row_misses: 64, status: 'PASS',
  },
  normalized_metrics: [
    { key: 'completion_cycles', value: 107321449, unit: 'cycles' },
    { key: 'average_read_latency_cycles', value: 296.180176, unit: 'cycles' },
    { key: 'read_queue_len_avg', value: 31.999922, unit: 'requests' },
    { key: 'write_queue_len_avg', value: 5.425047, unit: 'requests' },
    { key: 'completed_read_bytes', value: 872480768, unit: 'bytes' },
    { key: 'completed_write_bytes', value: 65536, unit: 'bytes' },
    { key: 'row_hits', value: 13580272, unit: 'requests' },
    { key: 'row_misses', value: 64, unit: 'requests' },
    { key: 'row_conflicts', value: 53200, unit: 'requests' },
    { key: 'generated_requests', value: 13633536, unit: 'requests' },
    { key: 'accepted_requests', value: 13633536, unit: 'requests' },
    { key: 'completed_requests', value: 13633536, unit: 'requests' },
    { key: 'outstanding_requests', value: 0, unit: 'requests' },
  ],
};
const stubRun = (runId: string, cycles: number, revision: string) => ({
  contract_version: 1, run_id: runId, display_name: `${runId} stub`, project_id: 'p-stub', revision_id: revision,
  backend: 'BOOKSIM_STANDALONE', status: 'EVALUATED', qualification: 'QUALIFIED',
  qualification_basis: 'stub basis', requirements_pass: true, started_at: '2026-01-02T10:00:00+00:00', completed_at: '2026-01-02T10:00:01+00:00',
  bundle_id: 'bundle-run-1', reason: null,
  evaluation: { status: 'EVALUATED', metrics: { completion_cycles: cycles, sample_window_cycles: cycles + 10, delivered_packets: 96, flits_injected: 768, flits_accepted: 768, packet_latency_avg: 12.5, flit_latency_avg: 3.25 }, fidelity_warning: 'stub fidelity warning', workload_id: 'workload-stub', network_traffic_window: { window_cycles: cycles + 10, wall_time_ns: cycles + 10 } },
  requirements: { contract_version: 1, entries: [{ requirement_index: 0, traffic_class: 'tp_collective', qos_class: 'latency_critical', verdict: 'SATISFIED', measured: cycles, required: 50000, binding: true, reason: `measured ${cycles} cycles <= ceiling 50000 cycles`, metric_authority: 'performance_result.network_binding.duration' }] },
  evidence: { evidence_id: 'evidence-run-1' },
  analyses: [{ backend_id: 'BOOKSIM_STANDALONE', question: 'NETWORK_COMPLETION', status: 'EVALUATED', model_fidelity: 'NETWORK_PACKET_SIMULATION', limitations: ['network packet simulation only'] }, ...(runId === 'run-1' ? [STUB_MEMORY_ANALYSIS] : [])],
});
const STUB_LOAD = {
  run: 'run-1', source: 'measured', capacity_formula: 'flits_per_window/(window_cycles*link_capacity_flits_per_cycle)',
  link_capacity_flits_per_cycle: 1, sample_period_cycles: 500, num_windows: 2, cycles_sampled: 1000, time_resets_observed: 0,
  channels: [
    { logical_channel_id: 0, flits_total: 100, cycles_sampled: 1000, utilization: 0.2, peak_window_utilization: 0.5, has_stalls: true, queue_cycles_total: 20, arb_wait_cycles_total: 2, per_hop_latency_mean_cycles: 2, peak_queued_flits: 4, peak_arb_wait_cycles: 0, peak_per_hop_latency_cycles: 8 },
    { logical_channel_id: 10001, flits_total: 40, cycles_sampled: 1000, utilization: 0.1, peak_window_utilization: 0.4, has_stalls: false, queue_cycles_total: 4, arb_wait_cycles_total: 0, per_hop_latency_mean_cycles: 1, peak_queued_flits: 2, peak_arb_wait_cycles: 0, peak_per_hop_latency_cycles: 3 },
    { logical_channel_id: 4, flits_total: 10, cycles_sampled: 1000, utilization: 0.02, peak_window_utilization: 0.1, has_stalls: false },
  ],
};
const STUB_SERIES = {
  run: 'run-1', source: 'measured', sample_period_cycles: 500, num_windows: 2, cycles_sampled: 1000,
  channels: [
    { logical_channel_id: 0, flits_per_window: [60, 40], window_cycles: [500, 500], queue_max_per_window: [4, 1], latency_max_per_window: [8, 2] },
    { logical_channel_id: 10001, flits_per_window: [10, 30], window_cycles: [500, 500], queue_max_per_window: [1, 2], latency_max_per_window: [2, 3] },
    { logical_channel_id: 4, flits_per_window: [10, 0], window_cycles: [500, 500], queue_max_per_window: [0, 0], latency_max_per_window: [0, 0] },
  ],
};
const STUB_LINK = {
  run: 'run-1', source: 'measured', logical_channel_id: 0, utilization: 0.2, total_flits: 100, stalls_total: 1,
  breakdown: { source: 'measured', queue_cycles: 20, arb_wait_cycles: 2, tx_flits: 100, tx_busy_cycles: 100, per_hop_latency_mean_cycles: 2, mean_queued_flits_per_output: 0.2, peak_queued_flits: 4, peak_arb_wait_cycles: 0, peak_per_hop_latency_cycles: 8 },
};
const STUB_MATRIX = {
  run_id: 'run-1', revision_id: 'p-stub-r01', availability: 'MEASURED',
  source: { trace: 'analyses/network_completion/run/workload.trace', backend: 'BOOKSIM_STANDALONE', declared_packets: 96 },
  nodes: 4, packets: 96, flits: 768, distinct_pairs: 3, classes: { 0: 64, 1: 32 },
  matrix: [[0, 48, 0, 0], [0, 0, 24, 0], [0, 0, 0, 24], [0, 0, 0, 0]],
  flit_matrix: [[0, 384, 0, 0], [0, 0, 192, 0], [0, 0, 0, 192], [0, 0, 0, 0]],
  pairs: [{ src: 0, dst: 1, packets: 48, flits: 384 }, { src: 1, dst: 2, packets: 24, flits: 192 }, { src: 2, dst: 3, packets: 24, flits: 192 }],
  class_matrices: {
    '0': {
      packets: 64, flits: 512, distinct_pairs: 3,
      matrix: [[0, 32, 0, 0], [0, 0, 16, 0], [0, 0, 0, 16], [0, 0, 0, 0]],
      flit_matrix: [[0, 256, 0, 0], [0, 0, 128, 0], [0, 0, 0, 128], [0, 0, 0, 0]],
      pairs: [{ src: 0, dst: 1, packets: 32, flits: 256 }, { src: 1, dst: 2, packets: 16, flits: 128 }, { src: 2, dst: 3, packets: 16, flits: 128 }],
    },
    '1': {
      packets: 32, flits: 256, distinct_pairs: 3,
      matrix: [[0, 16, 0, 0], [0, 0, 8, 0], [0, 0, 0, 8], [0, 0, 0, 0]],
      flit_matrix: [[0, 128, 0, 0], [0, 0, 64, 0], [0, 0, 0, 64], [0, 0, 0, 0]],
      pairs: [{ src: 0, dst: 1, packets: 16, flits: 128 }, { src: 1, dst: 2, packets: 8, flits: 64 }, { src: 2, dst: 3, packets: 8, flits: 64 }],
    },
  },
};
const STUB_INTEGRITY = { run_id: 'run-1', packet_conservation: { declared: { value: 96, availability: 'MEASURED' }, loaded: { value: 96, availability: 'MEASURED' }, delivered: { value: 96, availability: 'MEASURED' } }, flit_conservation: { injected: { value: 768, availability: 'MEASURED' }, accepted: { value: 768, availability: 'MEASURED' } }, route_realization: { status: 'OBSERVED', scope: 'destination-aware first-hop realization', full_path_claimed: false }, analyses: { network_completion: { backend: 'BOOKSIM_STANDALONE', status: 'EVALUATED', packets: 96, flits: 768 } } };
const STUB_ARTIFACTS = { run_id: 'run-1', bundle: { file_count: 3, files: { 'analyses/network_completion/run/workload.trace': 'bb884c2c7883176e63bfe752ce5e21ab122c5a26349dd070f1ec22085ae6fae7', 'analyses/network_completion/run/routing.dump': 'd4b9d304aaf57f9f4ca4956da2149efbebd2e9b290963ef95eeb58e1377ec826', 'summary.json': 'summary-fixture' } } };
const STUB_STUDY = {
  contract_version: 1, optimization_id: 'opt-stub', project_id: 'p-stub', base_revision_id: 'p-stub-r01', created_at: '2026-01-02T09:00:00+00:00',
  study: {
    contract_version: 2,
    definition: { method: 'grid', selection: 'min_first_objective', domain: { link_width: [64, 128] }, objectives: [{ metric: 'completion_cycles', direction: 'MIN', question: 'NETWORK_COMPLETION', backend_id: null }], constraints: [], budget: {}, seed: null },
    candidates: [
      { candidate_id: 'cand-a', guided_patch: { link_width: 64 }, objective_values: { completion_cycles: 3259 }, objective_availability: { completion_cycles: 'MEASURED' }, evaluation_status: 'EVALUATED', evaluation_authority: 'certified-backend', pareto_member: false, pareto_eligible: true },
      { candidate_id: 'cand-b', guided_patch: { link_width: 128 }, objective_values: { completion_cycles: 1425 }, objective_availability: { completion_cycles: 'MEASURED' }, evaluation_status: 'EVALUATED', evaluation_authority: 'certified-backend', pareto_member: true, pareto_eligible: true },
    ],
    pareto_ids: ['cand-b'], selected_candidate_id: 'cand-b', selection_rationale: 'selected cand-b minimizing completion_cycles',
  },
  candidate_runs: [{ candidate_id: 'cand-b', evaluation_status: 'EVALUATED', evidence_kind: 'optimization-candidate', run_id: null }],
  candidate_evidence_note: 'Stub candidate evidence lives in the study.',
};
const STUB_PARETO = {
  contract_version: 1, optimization_id: 'opt-pareto', project_id: 'p-stub', base_revision_id: 'p-stub-r01', created_at: '2026-01-02T09:10:00+00:00',
  study: {
    contract_version: 2,
    definition: { method: 'grid', selection: 'min_first_objective', domain: { link_width: [64, 128] }, objectives: [{ metric: 'completion_cycles', direction: 'MIN', question: 'NETWORK_COMPLETION', backend_id: null }, { metric: 'sample_window_cycles', direction: 'MIN', question: 'NETWORK_COMPLETION', backend_id: null }], constraints: [], budget: {}, seed: null },
    candidates: [
      { candidate_id: 'cand-c', guided_patch: { link_width: 64 }, objective_values: { completion_cycles: 3259, sample_window_cycles: 3617 }, objective_availability: { completion_cycles: 'MEASURED', sample_window_cycles: 'MEASURED' }, evaluation_status: 'EVALUATED', evaluation_authority: 'certified-backend', pareto_member: true, pareto_eligible: true },
      { candidate_id: 'cand-d', guided_patch: { link_width: 128 }, objective_values: { completion_cycles: 1425, sample_window_cycles: 3725 }, objective_availability: { completion_cycles: 'MEASURED', sample_window_cycles: 'MEASURED' }, evaluation_status: 'EVALUATED', evaluation_authority: 'certified-backend', pareto_member: true, pareto_eligible: true },
    ],
    pareto_ids: ['cand-c', 'cand-d'], selected_candidate_id: 'cand-c', selection_rationale: 'selected cand-c minimizing completion_cycles',
  },
  candidate_runs: [],
  candidate_evidence_note: 'Stub Pareto evidence lives in the study.',
};
const STUB_THIN = {
  contract_version: 1, optimization_id: 'opt-thin', project_id: 'p-stub', base_revision_id: 'p-stub-r01', created_at: '2026-01-02T09:20:00+00:00',
  study: {
    contract_version: 2,
    definition: { method: 'grid', selection: 'min_first_objective', domain: { ep: [1, 2, 4] }, objectives: [{ metric: 'completion_cycles', direction: 'MIN', question: 'NETWORK_COMPLETION', backend_id: null }], constraints: [], budget: {}, seed: null },
    candidates: [
      { candidate_id: 'thin-a', guided_patch: { ep: 1 }, objective_values: { completion_cycles: 9000 }, objective_availability: { completion_cycles: 'MEASURED' }, evaluation_status: 'EVALUATED', evaluation_authority: 'certified-backend', pareto_member: false, pareto_eligible: true },
      { candidate_id: 'thin-b', guided_patch: { ep: 2 }, evaluation_status: 'NOT_EVALUATED' },
      { candidate_id: 'thin-c', guided_patch: { ep: 4 }, evaluation_status: 'EXCLUDED' },
    ],
    pareto_ids: [], selected_candidate_id: null, selection_rationale: 'no feasible Pareto candidate — nothing selected',
  },
  candidate_runs: [],
  candidate_evidence_note: 'Stub thin evidence lives in the study.',
};

test('the Design heading compiles only a saved draft', async ({ page }) => {
  let dirty = false;
  let token: string | null = 'draft-p-stub-02';
  let compileBody: Record<string, unknown> | null = null;
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST, dirty, design_hash: token } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/compile-result', route => route.fulfill({ json: { available: true, revision_id: 'p-stub-r01', certificate: { overall: 'PASS' }, stage1_verdicts: [] } }));
  await page.route('**/gw/api/v1/projects/p-stub/compile', async route => {
    compileBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ json: { revision_id: 'p-stub-r02', design_hash: 'draft-p-stub-03', certificate: { overall: 'PASS' }, compilation: { status: 'COMPILED' } } });
  });

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();
  await page.goto('/#/design/fabric-topology');
  const compile = page.getByRole('button', { name: 'Compile draft', exact: true });
  await expect(compile).toBeEnabled();
  await compile.click();
  await expect.poll(() => compileBody).not.toBeNull();
  expect(compileBody).toEqual({ expected_draft_design_hash: 'draft-p-stub-02' });

  dirty = true;
  await page.reload();
  // A saved draft that differs from the active revision is compilable; it is not an unsaved edit.
  await expect(page.getByRole('button', { name: 'Compile draft', exact: true })).toBeEnabled();

  token = null;
  await page.reload();
  await expect(page.getByRole('button', { name: 'Compile draft', exact: true })).toBeDisabled();
  expect(errors).toEqual([]);
});

test('a loaded run drives the live Analysis and Verify surfaces', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', features: { artifact_bytes: true }, backends: { BOOKSIM_STANDALONE: { state: 'PRESENT', binary_present: true } } } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/runs/run-1', route => route.fulfill({ json: stubRun('run-1', 4200, 'p-stub-r01') }));
  await page.route('**/gw/api/v1/runs/run-2', async route => { await new Promise(resolve => setTimeout(resolve, 500)); return route.fulfill({ json: stubRun('run-2', 6000, 'p-stub-r00') }); });
  await page.route('**/gw/api/v1/runs/run-1/traffic-matrix', route => route.fulfill({ json: STUB_MATRIX }));
  await page.route('**/gw/api/v1/runs/run-1/integrity', route => route.fulfill({ json: STUB_INTEGRITY }));
  await page.route('**/gw/api/v1/runs/run-1/artifacts', route => route.fulfill({ json: STUB_ARTIFACTS }));
  await page.route('**/gw/api/v1/optimizations/opt-stub', route => route.fulfill({ json: STUB_STUDY }));
  await page.route('**/gw/api/v1/optimization/capabilities', route => route.fulfill({ json: { guided_parameters: [{ name: 'link_width', kind: 'int', executable: true, qualified_for_certified_optimization: true }] } }));
  await page.route('**/gw/api/v1/loom/simulation/load*', route => route.fulfill({ json: STUB_LOAD }));
  await page.route('**/gw/api/v1/loom/simulation/series*', route => route.fulfill({ json: STUB_SERIES }));
  await page.route('**/gw/api/v1/loom/simulation/link*', route => {
    const channel = new URL(route.request().url()).searchParams.get('channel') ?? '0';
    const row = STUB_LOAD.channels.find(entry => String(entry.logical_channel_id) === channel) ?? STUB_LOAD.channels[0];
    return route.fulfill({ json: {
      ...STUB_LINK, logical_channel_id: Number(channel), utilization: row.utilization, total_flits: row.flits_total,
      breakdown: { ...STUB_LINK.breakdown, tx_flits: row.flits_total, tx_busy_cycles: row.flits_total, queue_cycles: row.queue_cycles_total ?? 0, arb_wait_cycles: row.arb_wait_cycles_total ?? 0, per_hop_latency_mean_cycles: row.per_hop_latency_mean_cycles ?? null, peak_queued_flits: row.peak_queued_flits ?? null, peak_per_hop_latency_cycles: row.peak_per_hop_latency_cycles ?? null },
    } });
  });
  await page.route('**/gw/api/v1/optimizations/opt-pareto', route => route.fulfill({ json: STUB_PARETO }));
  await page.route('**/gw/api/v1/optimizations/opt-thin', route => route.fulfill({ json: STUB_THIN }));
  await page.route(/\/gw\/api\/v1\/runs\/run-1\/artifact\?/, route => {
    const artifactPath = new URL(route.request().url()).searchParams.get('path') ?? '';
    if (artifactPath.endsWith('workload.trace')) return route.fulfill({ body: '0 0 1 0 4\n1 1 2 0 4\n', headers: { 'content-type': 'text/plain', 'x-content-sha256': 'bb884c2c7883176e63bfe752ce5e21ab122c5a26349dd070f1ec22085ae6fae7' } });
    if (artifactPath.endsWith('routing.dump')) return route.fulfill({ body: '# header\nsrc_router 0 dst_node 0 next_router 0 port 4\nsrc_router 0 dst_node 1 next_router 1 port 0\n', headers: { 'content-type': 'text/plain', 'x-content-sha256': 'd4b9d304aaf57f9f4ca4956da2149efbebd2e9b290963ef95eeb58e1377ec826' } });
    return route.fulfill({ status: 404, json: { detail: 'no artifact' } });
  });
  await page.route('**/gw/api/v1/compare*', route => route.fulfill({ json: {
    contract_version: 1, a: { run_id: 'run-1' }, b: { run_id: 'run-2' },
    compatibility: { compatible: false, metric_definitions_complete: true, metric_definition_issues: [], reasons: ['different revision (p-stub-r01 vs p-stub-r00)'] },
    rows: [{ key: 'completion_cycles', a: 4200, b: 6000, unit: 'cycles', definition_id: 'product.metric.completion_cycles.v1', comparable: false, verdict: 'NOT_COMPARABLE', differs: 'scenario', delta_b_minus_a: null, reason: 'different revision' }],
    note: 'No automatic winner.' } }));

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();

  await page.goto('/#/analysis/summary');
  await expect(page.locator('.toolbar select').first()).toHaveValue('run-1');
  await expect(page.getByText('SATISFIED', { exact: true })).toBeVisible();
  await expect(page.getByText('4,200', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Authored fixture · not tool output')).toHaveCount(0);

  await page.getByRole('tab', { name: 'Memory', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'HBM3 memory timing' })).toBeVisible();
  await expect(page.locator('.memory-kpis')).toContainText('107,321,449');
  await expect(page.locator('.memory-kpis')).toContainText('99.61');
  await expect(page.locator('.memory-outcome-figure')).toContainText('99.61');
  await expect(page.locator('.memory-outcome-head')).toContainText('53,264');
  await expect(page.locator('.memory-outcome-head')).toContainText('1 in 256 requests');
  await expect(page.locator('.memory-outcome-row')).toHaveCount(2);
  await expect(page.locator('.memory-outcome-row').first()).toContainText('39 per 10,000');
  await expect(page.locator('.memory-outcome-row').nth(1)).toContainText('1 in 213,024');
  await expect(page.locator('.memory-traffic-row')).toHaveCount(2);
  await expect(page.locator('.memory-traffic-row').first()).toContainText('99.992 %');
  await expect(page.locator('.memory-traffic-row').nth(1)).toContainText('64.00 KiB');

  await page.locator('.run-bar select').selectOption('run-2');
  await expect(page.getByText('Loading run…', { exact: true })).toBeVisible();
  await expect(page.getByText('Runs in this project', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'Memory', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('No DRAM_TIMING analysis in this run', { exact: false })).toBeVisible();
  await page.locator('.run-bar select').selectOption('run-1');
  await expect(page.getByRole('tab', { name: 'Memory', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.memory-kpis')).toContainText('107,321,449');

  await page.goto('/#/analysis/metrics');
  await expect(page.getByText('completion_cycles', { exact: true })).toBeVisible();
  await expect(page.getByText('12.5', { exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Reporting analysis' })).toHaveCount(0);

  await page.goto('/#/analysis/matrix');
  await expect(page.locator('.matrix-heat-cell')).toHaveCount(16);
  await expect(page.locator('.matrix-margin-bar')).toHaveCount(8);
  await expect(page.locator('.matrix-kpis > div')).toHaveCount(4);
  await expect(page.locator('.matrix-kpis')).toContainText('Active pairs');
  await expect(page.locator('.traffic-profile')).toContainText('Pair distribution');
  await expect(page.locator('.traffic-profile')).toContainText('Median pair');
  await expect(page.locator('.class-mix-legend')).toContainText('class 0');
  await expect(page.getByText('MEASURED', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('analyses/network_completion/run/workload.trace').first()).toHaveCount(1);
  await expect(page.getByText('Share of trace packets')).toBeVisible();
  await expect(page.getByText('Flow patterns', { exact: true })).toBeVisible();
  await page.locator('.matrix-class-filter').getByRole('button', { name: 'class 1', exact: true }).click();
  await expect(page.locator('.matrix-kpis')).toContainText('Class 1 packets');
  await expect(page.locator('.matrix-kpis')).toContainText('32');
  await expect(page.getByRole('heading', { name: 'Packet count by source → destination · class 1' })).toBeVisible();
  await page.locator('.matrix-class-filter').getByRole('button', { name: 'All classes', exact: true }).click();
  await page.getByLabel('Filter endpoint pairs').fill('1→2');
  await expect(page.locator('.pair-focus')).toContainText('1 → 2');
  await expect(page.locator('.pair-focus')).toContainText('24 packets');

  await page.goto('/#/analysis/topology');
  await expect(page.getByText('Declared directed channels', { exact: true })).toBeVisible();
  await page.getByText('Declared directed channels', { exact: true }).click();
  await page.getByLabel('Find a declared channel').fill('CH-2');
  await expect(page.locator('.channel-table-scroll tbody tr')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'Per-router measured load', exact: true })).toBeVisible();
  const routerTotals = page.locator('.section').filter({ hasText: 'Per-router measured load' });
  await expect(routerTotals).toContainText('R0');
  await expect(routerTotals).toContainText('110');
  await expect(page.getByRole('heading', { name: 'Fabric load shape · measured channels', exact: true })).toBeVisible();
  await expect(page.locator('.load-shape-layout')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Measured channel activity', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Measured delay cost per channel', exact: true })).toBeVisible();
  await expect(page.locator('.window-matrix g[role=button]')).toHaveCount(3);
  await expect(page.getByTestId('window-reading')).toBeVisible();
  await expect(page.getByTestId('window-reading')).toContainText('What this shows');
  const grain = page.getByLabel('Original windows per column');
  await expect(grain).toBeVisible();
  await grain.selectOption('1');
  await expect(page.getByText('Each column sums up to 1 original window', { exact: false })).toBeVisible();
  await grain.selectOption('auto');
  await expect(page.locator('.load-histogram svg')).toBeVisible();
  await page.locator('.load-histogram g[role=button]').first().click();
  await expect(page.getByTestId('utilization-filter')).toBeVisible();
  await expect(page.getByTestId('load-bin-readout')).toContainText('Filtering the measured-channel list');
  await page.getByTestId('utilization-filter').getByText('Clear filter', { exact: true }).click();
  await expect(page.getByTestId('utilization-filter')).toHaveCount(0);
  await expect(page.locator('.channel-context')).toContainText('R0 p0 → R1 p1 · east');
  await page.locator('.window-matrix g[role=button]').nth(2).click();
  await expect(page.locator('.measured-detail-head h3')).toHaveText('CH-10001');
  await expect(page.locator('.channel-context')).toContainText('R1 p1 → R0 p1 · west');

  await expect(page.getByTestId('delay-reading')).toBeVisible();
  await expect(page.getByTestId('delay-reading')).toContainText('What this shows');
  const delayPoints = page.locator('.delay-point');
  await expect(delayPoints).toHaveCount(2);
  const scatterMetrics = () => page.evaluate(() => {
    const figure = document.querySelector('.delay-scatter')!;
    const svg = figure.querySelector('svg')!;
    const readout = figure.querySelector('.delay-readout')!;
    const figureBox = figure.getBoundingClientRect(), svgBox = svg.getBoundingClientRect(), readoutBox = readout.getBoundingClientRect();
    return {
      offset: Math.round(svgBox.top - figureBox.top),
      figureHeight: Math.round(figureBox.height),
      readoutHeight: Math.round(readoutBox.height),
    };
  });
  const chartBefore = await scatterMetrics();
  await delayPoints.first().hover();
  await expect(page.getByTestId('delay-readout')).toContainText('CH-0');
  const chartAfter = await scatterMetrics();
  expect(chartAfter).toEqual(chartBefore);
  await expect(page.locator('.measured-detail-head h3')).toHaveText('CH-10001');
  await delayPoints.first().click();
  await expect(page.locator('.measured-detail-head h3')).toHaveText('CH-0');
  await expect(page.locator('.measured-detail')).toBeInViewport();
  await expect(page.locator('.delay-point[aria-pressed="true"]')).toHaveCount(1);
  await expect(page.locator('.delay-ring.picked')).toHaveCount(1);
  await expect(page.locator('.channel-context')).toContainText('R0 p0 → R1 p1 · east');
  await page.locator('.delay-row').nth(1).click();
  await expect(page.locator('.measured-detail-head h3')).toHaveText('CH-10001');
  await expect(page.locator('.channel-context')).toContainText('R1 p1 → R0 p1 · west');

  await page.goto('/#/analysis/trace');
  await expect(page.getByText('Trace workspace', { exact: true })).toBeVisible();
  await expect(page.locator('.trace-meta')).toContainText('records');
  await expect(page.locator('.trace-chart-summary > span')).toHaveCount(4);
  await expect(page.getByRole('heading', { name: 'Requested injections over time' })).toBeVisible();
  await expect(page.locator('.trace-profile-card')).toHaveCount(3);
  await expect(page.locator('.trace-profile')).toContainText('Source balance');
  await expect(page.locator('.trace-profile')).toContainText('Destination balance');
  await expect(page.locator('.trace-class-legend')).toContainText('class 1');
  await expect(page.getByText('flits / bucket', { exact: true })).toBeVisible();
  await expect(page.locator('.trace-profile')).toContainText('No source hotspot');
  await expect(page.locator('.trace-profile')).toContainText('Average');
  await page.locator('.trace-bucket').nth(1).hover();
  await expect(page.locator('.trace-bucket-detail')).toContainText('Cycles');
  await page.locator('.trace-bucket').nth(1).click();
  await expect(page.locator('.trace-bucket.selected')).toHaveCount(1);
  await page.getByRole('button', { name: 'Packets', exact: true }).click();
  await expect(page.locator('.trace-chart-head')).toContainText('packets per');
  await page.locator('.trace-class-chip').first().click();
  await expect(page.locator('.trace-class-chip.off')).toHaveCount(1);
  await expect(page.locator('.trace-meta')).toContainText('analyses/network_completion/run/workload.trace');
  await expect(page.getByRole('button', { name: 'First-hop realization', exact: true })).toHaveCount(0);
  await expect(page.getByText('the remainder of each path is not recorded', { exact: false })).toHaveCount(0);

  await page.goto('/#/analysis/comparison');
  await expect(page.getByText('Reported metrics side by side')).toBeVisible();
  await expect(page.getByText('Backend verdict: not comparable.', { exact: false })).toBeVisible();
  await expect(page.locator('.compare-sides')).toContainText('A · this run');
  await expect(page.locator('.compare-sides')).toContainText('B · comparison run');
  await expect(page.getByText('Backend verdict:', { exact: false })).toBeVisible();
  const backendSection = page.locator('.section').filter({ hasText: 'backend verdicts' });
  const backendRow = backendSection.getByRole('row').filter({ hasText: 'completion_cycles' });
  await expect(backendRow.getByText('product.metric.completion_cycles.v1', { exact: true })).toBeVisible();
  await expect(backendRow.getByText('NOT_COMPARABLE', { exact: true })).toBeVisible();
  await expect(backendRow.locator('td').nth(3)).toHaveText('—');

  await page.goto('/#/analysis/curves');
  await expect(page.getByText('Repository workload reference.', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Measured optimization study', exact: true })).toHaveCount(0);

  await page.goto('/#/explore/brief');
  await page.getByRole('button', { name: /Bounded study/ }).click();
  await expect(page.getByRole('heading', { name: 'Study analysis', exact: true })).toBeVisible();
  await expect(page.getByText('Backend-measured candidate study.', { exact: false }).first()).toHaveCount(1);
  const studyPlot = page.getByRole('group', { name: /^Study candidates:/ });
  await expect(studyPlot).toBeVisible();
  await expect(studyPlot).toContainText('Link width');
  await expect(page.locator('.study-summary')).toContainText('1,425 cycles');
  await page.locator('summary').filter({ hasText: 'Study candidates' }).click();
  await expect(page.getByRole('row', { name: /^C2 Link width/ })).toContainText('1,425 cycles');
  await page.getByLabel('Optimization study').selectOption('opt-pareto');
  await expect(page.getByRole('group', { name: /^Study candidates:/ })).toBeVisible();
  await expect(page.getByText('2 of 2 measured candidates are marked non-dominated', { exact: false })).toBeVisible();
  await page.getByLabel('Optimization study').selectOption('opt-thin');
  await expect(page.getByText('No comparable measured candidates.', { exact: false })).toBeVisible();
  await expect(page.getByText('1 of 3 candidates has a measured objective value.', { exact: false })).toBeVisible();
  await expect(page.getByText('Selection: no feasible Pareto candidate', { exact: false })).toBeVisible();
  await expect(page.getByRole('group', { name: /^Study candidates:/ })).toHaveCount(0);

  await page.goto('/#/verify/checks');
  await expect(page.getByText('Packet conservation').first()).toBeVisible();
  await expect(page.getByText('OBSERVED', { exact: true }).first()).toBeVisible();

  await page.goto('/#/verify/evidence');
  await expect(page.getByRole('heading', { name: 'Bundle files', exact: true })).toBeVisible();
  await expect(page.locator('.section').filter({ hasText: 'Bundle files' }).getByText('summary.json', { exact: true })).toBeVisible();

  expect(errors).toEqual([]);
});

test('a loaded draft drives the live workload surfaces without inventing a schedule', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/runs/run-1', route => route.fulfill({ json: stubRun('run-1', 4200, 'p-stub-r01') }));
  await page.route('**/gw/api/v1/runs/run-1/traffic-matrix', route => route.fulfill({ json: STUB_MATRIX }));
  await page.route('**/gw/api/v1/runs/run-1/integrity', route => route.fulfill({ json: STUB_INTEGRITY }));
  await page.route('**/gw/api/v1/runs/run-1/artifacts', route => route.fulfill({ json: STUB_ARTIFACTS }));

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();

  await page.goto('/#/workloads/library');
  await expect(page.locator('.studio-context')).toContainText('Stubbed 2x2 project');
  await expect(page.getByLabel('Model name')).toHaveValue('stub-model-30b');
  const workloadStats = page.locator('.stat-strip').first();
  await expect(workloadStats.locator('.stat').filter({ hasText: 'Ranks' })).toContainText('4');
  await expect(workloadStats.locator('.stat').filter({ hasText: 'Collectives' })).toContainText('2');
  await expect(workloadStats.locator('.stat').filter({ hasText: 'Compute stages' })).toContainText('2');
  await expect(page.getByLabel('traffic row 1 traffic class')).toHaveValue('tp_collective');
  await expect(page.getByText('4.00 KiB')).toBeVisible();
  await expect(page.getByText('No compute stages declared.', { exact: false })).toHaveCount(0);

  await page.goto('/#/workloads/editor');
  await expect(page.locator('.stat').filter({ hasText: 'Compute stages' })).toContainText('2');
  await expect(page.getByLabel('stage 2 id')).toHaveValue('layer0_moe');
  await expect(page.getByText('Not a schedule', { exact: true })).toBeVisible();

  await page.goto('/#/workloads/requirements');
  await expect(page.getByText('Binding', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('SATISFIED', { exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Bandwidth floor GB/s' })).toBeVisible();

  await page.goto('/#/workloads/bindings');
  await expect(page.getByText('No binding table in this draft.', { exact: false })).toBeVisible();
  await expect(page.getByText('More agents than attached seats')).toBeVisible();

  await page.goto('/#/workloads/assumptions');
  await expect(page.getByText('1000 MHz')).toBeVisible();
  await expect(page.getByText('clk_core')).toBeVisible();

  await page.goto('/#/workloads/lowering');
  await expect(page.getByText('No lowering adapter.', { exact: false })).toBeVisible();
  await expect(page.getByText('Requirement has no matching traffic')).toBeVisible();
  await expect(page.getByText('Parallelism product 4 ≠ 3 tiles')).toBeVisible();
  expect(errors).toEqual([]);
});

test('the workloads workspace exposes four purposeful views and keeps legacy routes working', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/runs/run-1', route => route.fulfill({ json: stubRun('run-1', 4200, 'p-stub-r01') }));
  await page.route('**/gw/api/v1/runs/run-1/traffic-matrix', route => route.fulfill({ json: STUB_MATRIX }));
  await page.route('**/gw/api/v1/runs/run-1/integrity', route => route.fulfill({ json: STUB_INTEGRITY }));
  await page.route('**/gw/api/v1/runs/run-1/artifacts', route => route.fulfill({ json: STUB_ARTIFACTS }));
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();
  await page.goto('/#/workloads/workflow');
  // One live destination does not need a strip; the intent tabs are the sections.
  await expect(page.getByRole('navigation', { name: 'Workloads & Requirements views' })).toHaveCount(0);
  await expect(page.getByText('Endpoint bindings')).toHaveCount(0);
  await expect(page.getByText('Assumptions & inputs')).toHaveCount(0);
  const intentTabs = page.getByRole('tablist', { name: 'Intent sections' });
  await expect(intentTabs.getByRole('tab')).toHaveText(['Workload', 'Requirements', 'Fabric', 'Validate']);
  await intentTabs.getByRole('tab', { name: 'Requirements' }).click();
  await expect(page.getByRole('heading', { name: 'Acceptance criteria' })).toBeVisible();
  await intentTabs.getByRole('tab', { name: 'Validate' }).click();
  await expect(page.getByText('Readiness checks', { exact: true })).toBeVisible();
  await page.goto('/#/workloads/editor');
  await expect(page.locator('.page-heading h1')).toHaveText('Workload');
  await expect(page.getByRole('tab', { name: 'Compute · 2' })).toBeVisible();
  await page.goto('/#/workloads/assumptions');
  await expect(page.locator('.page-heading h1')).toHaveText('Validate');
  await expect(page.getByText('Readiness checks', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

const STUB_PLAN = { contract_version: 1, revision_id: 'p-stub-r01', analyses: [
  { question: 'NETWORK_COMPLETION', backend: 'BOOKSIM_STANDALONE', support: 'SUPPORTED', readiness: 'READY', qualification: { basis: 'certified mesh-DOR envelope', numerical_qualification: 'ESTABLISHED', calibration: 'NOT_ESTABLISHED' } },
  { question: 'DRAM_TIMING', backend: 'RAMULATOR2_HBM3_V1', support: 'SUPPORTED', readiness: 'READY', qualification: { basis: 'audited HBM3 chunk', numerical_qualification: 'ESTABLISHED', calibration: 'NOT_ESTABLISHED' } },
  { question: 'SERVING_TTFT', backend: 'CANONICAL_SERVING', support: 'SUPPORTED', readiness: 'BLOCKED', reason: 'no serving experiment bound to this adapter' },
] };
const stubJob = (state: string, runId?: string) => ({ contract_version: 1, job_id: 'job-stub', project_id: 'p-stub', kind: 'EVALUATION', revision_id: 'p-stub-r01', state, submitted_at: '2026-01-02T10:00:00+00:00', updated_at: '2026-01-02T10:00:20+00:00', error_code: null, error_message: null, result: runId ? { run_id: runId } : null, cancellable: state === 'RUNNING' });

test('launching an evaluation is gated by the real plan, tracks the gateway job, and selects the published run', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  const posts: string[] = [];
  let jobPolls = 0;
  let projectReads = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST } }));
  await page.route('**/gw/api/v1/projects/p-stub/jobs?kind=EVALUATION', route => route.fulfill({ json: { contract_version: 1, jobs: [] } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => {
    projectReads += 1;
    const body = projectReads === 1 ? STUB_PROJECT : { ...STUB_PROJECT, runs: [...STUB_PROJECT.runs, { run_id: 'run-new', revision_id: 'p-stub-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', qualification: 'QUALIFIED', requirements_pass: true, completed_at: '2026-01-03T10:00:00+00:00', bundle_id: 'bundle-run-new', display_name: 'newly published run' }] };
    route.fulfill({ json: body });
  });
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/evaluation-plan', route => route.fulfill({ json: STUB_PLAN }));
  await page.route('**/gw/api/v1/runs/run-1', route => route.fulfill({ json: stubRun('run-1', 4200, 'p-stub-r01') }));
  await page.route('**/gw/api/v1/runs/run-1/traffic-matrix', route => route.fulfill({ json: STUB_MATRIX }));
  await page.route('**/gw/api/v1/runs/run-1/integrity', route => route.fulfill({ json: STUB_INTEGRITY }));
  await page.route('**/gw/api/v1/runs/run-1/artifacts', route => route.fulfill({ json: STUB_ARTIFACTS }));
  await page.route('**/gw/api/v1/runs/run-new', route => route.fulfill({ json: stubRun('run-new', 3900, 'p-stub-r01') }));
  await page.route('**/gw/api/v1/runs/run-new/traffic-matrix', route => route.fulfill({ json: STUB_MATRIX }));
  await page.route('**/gw/api/v1/runs/run-new/integrity', route => route.fulfill({ json: STUB_INTEGRITY }));
  await page.route('**/gw/api/v1/runs/run-new/artifacts', route => route.fulfill({ json: STUB_ARTIFACTS }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/evaluate', route => { posts.push(route.request().postData() ?? ''); route.fulfill({ json: stubJob('QUEUED') }); });
  await page.route('**/gw/api/v1/jobs/job-stub', route => { jobPolls += 1; route.fulfill({ json: jobPolls < 2 ? stubJob('RUNNING') : stubJob('COMPLETED', 'run-new') }); });

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();
  await page.goto('/#/analysis/summary');

  await page.getByRole('button', { name: 'Run new evaluation' }).click();
  const launchSection = page.locator('.launch-disclosure');
  await expect(launchSection.getByText('Writes a real run')).toBeVisible();
  await expect(launchSection.getByRole('checkbox', { name: 'Select SERVING_TTFT' })).toBeDisabled();
  await expect(launchSection.getByRole('checkbox', { name: 'Select NETWORK_COMPLETION' })).toBeChecked();
  const launchButton = launchSection.getByRole('button', { name: /^Launch/ });
  await expect(launchButton).toBeDisabled();
  await expect(launchSection.getByText('questions are blocked', { exact: false })).toBeVisible();

  await launchSection.getByRole('checkbox', { name: /I understand: run real backends/ }).check();
  await expect(launchButton).toBeEnabled();
  await launchButton.click();

  await expect(page.getByText(/Job\s*RUNNING|RUNNING/).first()).toBeVisible();
  await expect(page.getByText('Run published', { exact: false }).first()).toBeVisible({ timeout: 10000 });
  await expect(page.getByText('01a16c43', { exact: false })).toHaveCount(0);
  await expect(page.locator('.toolbar select').first()).toHaveValue('run-new');
  expect(posts.length).toBe(1);
  expect(JSON.parse(posts[0]).questions).toEqual(['NETWORK_COMPLETION', 'DRAM_TIMING']);
  expect(errors).toEqual([]);
});

test('the draft editor validates topology with the gateway and saves only the canonical request', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  const previews: string[] = [];
  const puts: string[] = [];
  let savedDraft: Record<string, unknown> | null = null;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft*', route => {
    if (route.request().method() === 'PUT') {
      const body = JSON.parse(route.request().postData() ?? '{}');
      puts.push(route.request().postData() ?? '');
      savedDraft = body.request;
      return route.fulfill({ json: { contract_version: 1, request: body.request, dirty: true } });
    }
    return route.fulfill({ json: { contract_version: 1, request: savedDraft ?? STUB_REQUEST, dirty: savedDraft !== null } });
  });
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/runs/run-1', route => route.fulfill({ json: stubRun('run-1', 4200, 'p-stub-r01') }));
  await page.route('**/gw/api/v1/runs/run-1/traffic-matrix', route => route.fulfill({ json: STUB_MATRIX }));
  await page.route('**/gw/api/v1/runs/run-1/integrity', route => route.fulfill({ json: STUB_INTEGRITY }));
  await page.route('**/gw/api/v1/runs/run-1/artifacts', route => route.fulfill({ json: STUB_ARTIFACTS }));
  await page.route('**/gw/api/v1/projects/p-stub/topology-preview', route => {
    previews.push(route.request().postData() ?? '');
    const body = JSON.parse(route.request().postData() ?? '{}');
    route.fulfill({ json: { contract_version: 1, request: { ...body.request, topology: body.topology } } });
  });

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();
  await page.goto('/#/workloads/workflow');

  await page.getByRole('button', { name: 'Edit draft' }).click();
  await page.getByRole('tab', { name: 'Topology & sizing', exact: true }).click();
  const sideLength = page.getByRole('spinbutton', { name: 'Routers per side', exact: true });
  await sideLength.fill('4');
  await page.getByRole('button', { name: 'Validate topology' }).click();
  await expect(page.getByText('Topology accepted', { exact: true })).toBeVisible();
  expect(JSON.parse(previews[0]).topology).toMatchObject({ kind: 'mesh', side_length: 4, concentration: 1 });

  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(page.getByText('uncompiled', { exact: true })).toBeVisible();
  await expect(page.getByRole('spinbutton', { name: 'Routers per side', exact: true })).toHaveValue('4');
  const saved = JSON.parse(puts[0]).request;
  expect(saved.topology).toMatchObject({ side_length: 4 });
  expect(saved.noc_controls).toBeDefined();
  expect(saved.agents.length).toBe(STUB_REQUEST.agents.length);

  await page.getByLabel('Topology family').selectOption('torus');
  await expect(page.getByRole('spinbutton', { name: 'Routers per side', exact: true })).toHaveValue('4');
  await page.getByRole('button', { name: 'Add agent' }).click();
  await page.getByRole('button', { name: 'Validate topology' }).click();
  await expect.poll(() => previews.length).toBe(2);
  expect(JSON.parse(previews[1]).topology).toMatchObject({ kind: 'torus', side_length: 4, concentration: 1 });
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect.poll(() => puts.length).toBe(2);
  const saved2 = JSON.parse(puts[1]).request;
  expect(saved2.topology.kind).toBe('torus');
  expect(saved2.agents.length).toBe(STUB_REQUEST.agents.length + 1);
  expect(errors).toEqual([]);
});

test('a schema-2 draft saves as canonical v4 without carrying v2 NOC shape fields', async ({ page }) => {
  const puts: string[] = [];
  const legacy = {
    schema_version: 2, compiler_semantics_version: 3,
    agents: [{ kind: 'compute_tile', count: 4, data_width: 256, protocol: 'AXI' }],
    physical: { clock_freq_mhz: 1000, data_width: 256 },
    noc_config: { topology_family: 'mesh', concentration: null, link_width: 64, radix: null },
    workload: null, address_map: { ranges: [] }, requirements: [], dependencies: [],
  };
  const canonical: Record<string, unknown> = {
    ...legacy, schema_version: 4,
    noc_controls: { link_width: 64, arbitration: 'deterministic', rcu_enabled: false, obfuscation_level: 0 },
    topology: { kind: 'mesh', side_length: 4, concentration: 1 },
  };
  delete canonical.noc_config;
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(String(error)));

  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => {
    if (route.request().method() === 'PUT') { puts.push(route.request().postData() ?? ''); return route.fulfill({ json: { dirty: true } }); }
    return route.fulfill({ json: { contract_version: 1, request: legacy, dirty: false } });
  });
  await page.route('**/gw/api/v1/projects/p-stub/topology-preview', route => route.fulfill({ json: { contract_version: 1, request: canonical } }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/runs/run-1', route => route.fulfill({ json: stubRun() }));

  await page.goto('/?v=legacy#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await page.goto('/#/workloads/workflow');
  await page.getByRole('button', { name: 'Edit draft' }).click();
  await page.getByRole('tablist', { name: 'Intent sections' }).getByRole('tab', { name: 'Fabric', exact: true }).click();
  await expect(page.getByText('Schema v2 draft', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Validate topology' }).click();
  await expect(page.getByText('Topology accepted', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect.poll(() => puts.length).toBe(1);
  const saved = JSON.parse(puts[0]).request;
  expect(saved.schema_version).toBe(4);
  expect(saved.noc_config).toBeUndefined();
  expect(saved.noc_controls).toBeDefined();
  expect(saved.noc_controls.concentration).toBeUndefined();
  expect(saved.topology).toMatchObject({ kind: 'mesh', side_length: 4 });
  expect(errors).toEqual([]);
});

test('gateway project panel degrades honestly when the gateway is unreachable', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/**', route => route.abort('connectionrefused'));
  await page.goto('/#/shared/projects');
  await expect(page.getByText('Gateway not reachable at', { exact: false })).toBeVisible();
  await expect(page.getByText('No connection could be made to the gateway.')).toBeVisible();
  await expect(page.getByText('Write access from this prototype')).toHaveCount(0);
  await expect(page.getByRole('heading', { level: 1, name: 'Projects, Revisions & Recovery' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('catalogue addition is manual, validated, and survives navigation and reload', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/design/catalog');
  await page.getByRole('button', { name: 'Add agent group', exact: true }).click();
  await page.getByLabel('Agent group identifier').fill('EP_NPU_0');
  await expect(page.getByRole('button', { name: 'Add group to draft', exact: true })).toBeDisabled();
  await page.getByLabel('Agent group identifier').fill('EP_TEST_0');
  await page.getByRole('button', { name: 'Add group to draft', exact: true }).click();
  await page.getByRole('link', { name: 'Inspect endpoint instances', exact: true }).click();
  await page.getByRole('textbox', { name: 'Filter endpoints' }).fill('EP_TEST_0');
  await expect(page.getByRole('button', { name: 'EP_TEST_0', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'EP_TEST_0', exact: true })).toBeVisible();
});

test('address correction changes actual local intent and check records bind the input revision', async ({ page }) => {
  await page.goto('/#/design/addresses');
  await page.getByRole('button', { name: 'Review BAR relocation' }).click();
  await page.getByLabel('Proposed base address').fill('0x80000000');
  await expect(page.getByRole('button', { name: 'Apply local address edit' })).toBeDisabled();
  await page.getByLabel('Proposed base address').fill('0xC0000000');
  await page.getByRole('button', { name: 'Apply local address edit' }).click();
  await expect(page.getByText('0 interval overlaps', { exact: true })).toBeVisible();
  await page.goto('/#/verify/checks');
  await page.getByRole('button', { name: 'Run local declaration checks' }).click();
  await expect(page.getByRole('row').filter({ hasText: 'LOCAL-ADDR-01' }).getByText('Pass', { exact: true })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'CDC-IMPL-01' }).getByText('Not evaluated', { exact: true })).toBeVisible();
  const record = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(record.checks.revision).toBe(record.draft.revision);
  expect(record.draft.regions.find((r: {id: string}) => r.id === 'PCIE_BAR0').base).toBe(0xc0000000);
});

test('scope approval and amendments record only local preview intent', async ({ page }) => {
  await page.goto('/#/explore/brief');
  await page.getByRole('button', { name: 'Approve local scope preview' }).click();
  await expect(page.getByRole('heading', { name: 'Study Execution & Budgets', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Review scope amendment' }).click();
  await page.getByLabel('Proposed wall-clock limit (minutes)').fill('120');
  await page.getByRole('button', { name: 'Approve local amendment' }).click();
  const record = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(record.approvedBrief.wallMinutes).toBe(120);
  expect(record.events[0]).toContain('local');
  await expect(page.getByRole('button', { name: 'Launch evaluations unavailable' })).toBeDisabled();
});

test('selection carries from results to comparison and adoption preserves the active draft', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('**/gw/**', route => route.abort('connectionrefused'));
  await page.goto('/#/explore/results');
  await page.getByRole('button', { name: 'Select candidate C-09', exact: true }).click();
  await page.getByRole('link', { name: 'Compare observations' }).click();
  await expect(page.getByRole('heading', { name: 'Candidate Comparison', exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: 'Explore views' }).getByRole('link', { name: 'Adoption / branch', exact: true }).click();
  await page.getByRole('button', { name: 'Review local adoption' }).click();
  await page.getByRole('button', { name: 'Confirm local branch', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'System / Block Diagram', exact: true })).toBeVisible();
  await page.reload();
  const record = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(record.draft.fromCandidate).toBe('C-09');
  expect(record.archives).toHaveLength(1);
  expect(record.archives[0].id).toBe('local-draft');
  expect(record.archives[0].vcs).toBe(2);
  expect(record.draft.vcs).toBe(4);
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Review restore copy' }).click();
  await page.getByRole('button', { name: 'Preserve current & activate copy' }).click();
  const restored = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(restored.archives).toHaveLength(2);
  expect(restored.draft.vcs).toBe(2);
});

test('delivery creates a real descriptive JSON download, not fake generated RTL', async ({ page }) => {
  await page.goto('/#/deliver/configuration');
  await page.getByLabel('Download filename').fill('../invalid.json');
  await expect(page.getByRole('button', { name: 'Prepare local export for review' })).toBeDisabled();
  await page.getByLabel('Download filename').fill('reviewed-architecture.json');
  await page.getByRole('button', { name: 'Prepare local export for review' }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download architecture JSON' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('reviewed-architecture.json');
  const content = JSON.parse(await readFile((await download.path())!, 'utf8'));
  expect(content.illustrative).toBe(true);
  expect(content.schema).toBe('srota-studio-prototype/architecture-intent/v1');
  expect(content.capturedDraft.endpoints).toHaveLength(8);
  expect(content.limitations.join(' ')).toContain('No RTL');
  await page.getByRole('link', { name: 'Inspect exact JSON contents' }).click();
  await expect(page.locator('pre')).toContainText('capturedDraft');
});

test('keyboard navigation and compact inspector work, invalid saved state is not silently overwritten', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.addInitScript(([key]) => localStorage.setItem(key, '{invalid'), [STORAGE_KEY]);
  await page.goto('/#/design/system');
  await expect(page.getByRole('status').filter({ hasText: 'could not be read' })).toBeVisible();
  expect(await page.evaluate(key => localStorage.getItem(key), STORAGE_KEY)).toBe('{invalid');
  await page.getByRole('link', { name: 'Skip to workspace' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-workspace')).toBeFocused();
  expect(page.url()).toContain('#/design/system');
  await page.getByRole('button', { name: 'Inspector', exact: true }).click();
  await expect(page.locator('#selection-inspector')).toBeVisible();
  await page.getByRole('button', { name: 'Close inspector', exact: true }).click();
  await page.keyboard.press('Control+k');
  await page.getByRole('textbox', { name: 'Search views' }).fill('fabric ablation');
  await page.getByRole('button', { name: /Fabric Ablations/ }).click();
  await expect(page.getByRole('heading', { name: 'Fabric Ablations', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Accept current preview for saving' }).click();
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!).version, STORAGE_KEY)).toBe(1);
});
