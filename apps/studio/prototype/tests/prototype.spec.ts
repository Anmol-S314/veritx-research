import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { PAGES, STORAGE_KEY } from '../src/model';

const EXPORTS = fileURLToPath(new URL('../../../../docs/design/stitch_veritx_studio_eda_frontend/', import.meta.url));
const PROMPT_ONLY = ['analysis_logs_artifacts'];

test('every supplied design export has exactly one route', () => {
  const supplied = readdirSync(EXPORTS).filter(d => existsSync(`${EXPORTS}${d}/code.html`));
  expect(supplied.length).toBeGreaterThan(40);
  for (const dir of supplied) expect(PAGES.filter(p => p.source === dir), `no route for export ${dir}`).toHaveLength(1);
  expect(PAGES.filter(p => !supplied.includes(p.source)).map(p => p.source)).toEqual(PROMPT_ONLY);
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
      await expect(page.getByRole('heading', { level: 1, name: route.title, exact: true })).toBeVisible();
      await expect(page.getByText('Sample project', { exact: true })).toBeVisible();
      const size = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth }));
      expect(size.width, `${route.id} at ${width}`).toBeLessThanOrEqual(size.viewport);
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: testInfo.outputPath(`${route.id.replace('/', '-')}-${width}.png`), animations: 'disabled' });
    }
  }
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

const STUB_PROJECT = {
  project: { project_id: 'p-stub', name: 'Stubbed 2x2 project', created_at: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-02T00:00:00+00:00' },
  active_revision_id: 'p-stub-r01',
  active_revision: { revision_id: 'p-stub-r01', display_name: 'r01', design_hash: 'sha256:' + 'a'.repeat(64), design: { agents: [{ kind: 'compute_tile', count: 2 }, { kind: 'hbm_controller', count: 1 }], locked_derived: { routing: 'DOR_XY', vc_count: 2, certificate_overall: 'PASS' }, noc_guided: { link_width: 64, topology_family: null }, requirements: [{ traffic_class: 'tp_collective', qos_class: 'latency_critical', latency_ceiling_cycles: 50000 }] } },
  runs: [
    { run_id: 'run-2', revision_id: 'p-stub-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', qualification: 'QUALIFIED', requirements_pass: true, completed_at: '2026-01-01T10:00:00+00:00', bundle_id: 'sha256:' + 'e'.repeat(64), display_name: 'older stub run' },
    { run_id: 'run-1', revision_id: 'p-stub-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', qualification: 'QUALIFIED', requirements_pass: true, completed_at: '2026-01-02T10:00:00+00:00', bundle_id: 'sha256:' + 'f'.repeat(64), display_name: 'newer stub run' },
  ],
};
const STUB_REQUEST = { schema_version: 1, compiler_semantics_version: 3, topology: { kind: 'mesh', side_length: 2, concentration: 1 }, agents: [{ kind: 'compute_tile', count: 3, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: null, power_domain: null }, { kind: 'hbm_controller', count: 1, data_width: 256, addr_width: 64, protocol: 'AXI', clock_domain: 'clk_core', power_domain: null }], physical: { clock_freq_mhz: 1000, data_width: 256, num_power_domains: 1, process_node_nm: 7 }, noc_controls: { link_width: 64, arbitration: null, output_formats: ['json'], obfuscation_level: 0 }, address_map: { ranges: [{ name: 'HBM', base: '0x100000000', size_bytes: 17179869184, target: 'hbm_controller' }] }, requirements: [{ traffic_class: 'tp_collective', qos_class: 'latency_critical', binding: true, latency_ceiling_cycles: 50000, bandwidth_floor_gbps: null }, { traffic_class: 'ep_dispatch', qos_class: 'latency_critical', binding: false, latency_ceiling_cycles: null, bandwidth_floor_gbps: 12 }, { traffic_class: 'tile_ingest', qos_class: 'bandwidth', binding: false, latency_ceiling_cycles: null, bandwidth_floor_gbps: 40 }], workload: { model_name: 'stub-model-30b', model_family: 'mixture_of_experts', serving_mode: 'mixed', tp: 2, dp: 1, ep: 2, pp: 1, workload_source_ref: null, collectives: [{ kind: 'allreduce', dimension: 'TP', payload_bytes: 4096, traffic_class: 'tp_collective', source_rank: null }, { kind: 'alltoall', dimension: 'EP', payload_bytes: 2048, traffic_class: 'ep_dispatch', source_rank: null }] }, compute: { source: 'compiler', stages: [{ stage_id: 'layer0_attn', owner: 0, duration_ns: 1000, input_bytes: 4096, output_bytes: 4096, weight_bytes: 0, input_loc: 'LOCAL', output_loc: 'LOCAL', weight_loc: 'LOCAL' }, { stage_id: 'layer0_moe', owner: 1, duration_ns: 3000, input_bytes: 4096, output_bytes: 2048, weight_bytes: 1024, input_loc: 'LOCAL', output_loc: 'LOCAL', weight_loc: 'REMOTE' }] }, dependencies: [] };
const STUB_TOPOLOGY = {
  contract_version: 1, family: 'mesh', counts: { routers: 4, channels: 8, endpoints: 3, seats: 4 },
  design_hash: 'sha256:' + 'b'.repeat(64), topology_hash: 'sha256:' + 'c'.repeat(64), attachment_hash: 'sha256:' + 'd'.repeat(64),
  routers: [{ router_id: 0, coordinates: [0, 0], seat_capacity: 1 }, { router_id: 1, coordinates: [1, 0], seat_capacity: 1 }, { router_id: 2, coordinates: [0, 1], seat_capacity: 1 }, { router_id: 3, coordinates: [1, 1], seat_capacity: 2 }],
  channels: [[0, 1], [1, 0], [0, 2], [2, 0], [1, 3], [3, 1], [2, 3], [3, 2]].map(([a, b], i) => ({ channel_id: i, src_router: a, dst_router: b, src_port: 1, dst_port: 1, width_bits: 64, latency_cycles: 1, route_weight: 1, physical_link_id: null })),
  endpoints: [{ endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 }, { endpoint_id: 1, router_id: 3, kind: 'compute_tile', port_id: 0 }, { endpoint_id: 2, router_id: 3, kind: 'hbm_controller', port_id: 1 }],
  physical_links: [],
};

test('a loaded gateway project drives the live Design surfaces without fixture leakage', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: { BOOKSIM_STANDALONE: { state: 'PRESENT', binary_present: true } } } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));

  await page.goto('/#/shared/projects');
  await expect(page.getByText('Stubbed 2x2 project', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();
  await expect(page.getByText('Gateway project', { exact: true })).toBeVisible();
  await expect(page.getByText('Sample project', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Address checks not run', { exact: true })).toBeVisible();

  await page.goto('/#/design/fabric-topology');
  await expect(page.getByText('Live project data · Stubbed 2x2 project', { exact: false })).toBeVisible();
  await expect(page.locator('.gateway-nodes circle')).toHaveCount(4);
  await expect(page.locator('.gateway-links line')).toHaveCount(4);
  await expect(page.getByText('mesh · 4 routers · 8 directed channels · 3 endpoints')).toBeVisible();
  await page.locator('.gateway-node').nth(3).click();
  await expect(page.locator('.inspector h3')).toHaveText('R3');
  await expect(page.getByText('Not declared in this payload').first()).toBeVisible();

  await page.goto('/#/design/endpoints');
  await expect(page.getByText('EP-2', { exact: true })).toBeVisible();
  await expect(page.getByText('hbm_controller', { exact: true }).first()).toBeVisible();

  await page.goto('/#/design/addresses');
  await expect(page.getByText('HBM', { exact: true })).toBeVisible();
  await expect(page.getByText('0x100000000')).toBeVisible();

  await page.goto('/#/design/domains');
  await expect(page.getByText('1000 MHz')).toBeVisible();
  await expect(page.getByText('clk_core', { exact: false }).first()).toBeVisible();

  await page.goto('/#/design/catalog');
  await expect(page.getByText('still shows the fixture', { exact: false })).toBeVisible();
  expect(errors).toEqual([]);
});

const stubRun = (runId: string, cycles: number, revision: string) => ({
  contract_version: 1, run_id: runId, display_name: `${runId} stub`, project_id: 'p-stub', revision_id: revision,
  design_hash: 'sha256:' + 'a'.repeat(64), backend: 'BOOKSIM_STANDALONE', status: 'EVALUATED', qualification: 'QUALIFIED',
  qualification_basis: 'stub basis', requirements_pass: true, started_at: '2026-01-02T10:00:00+00:00', completed_at: '2026-01-02T10:00:01+00:00',
  bundle_id: 'sha256:' + 'f'.repeat(64), reason: null,
  evaluation: { status: 'EVALUATED', metrics: { completion_cycles: cycles, sample_window_cycles: cycles + 10, delivered_packets: 96, flits_injected: 768, flits_accepted: 768, packet_latency_avg: 12.5, flit_latency_avg: 3.25 }, fidelity_warning: 'stub fidelity warning', evidence: { raw_evidence_digest: 'rawdigest', stats_digest: 'statsdigest' }, workload_id: 'sha256:' + '9'.repeat(64), network_traffic_window: { window_cycles: cycles + 10, wall_time_ns: cycles + 10 }, resolved_fabric_hash: 'sha256:' + '8'.repeat(64) },
  requirements: { contract_version: 1, entries: [{ requirement_index: 0, traffic_class: 'tp_collective', qos_class: 'latency_critical', verdict: 'SATISFIED', measured: cycles, required: 50000, binding: true, reason: `measured ${cycles} cycles <= ceiling 50000 cycles`, metric_authority: 'performance_result.network_binding.duration' }] },
  evidence: { evidence_id: 'sha256:' + '7'.repeat(64), raw_evidence_digest: 'rawdigest' },
  analyses: [{ backend_id: 'BOOKSIM_STANDALONE', status: 'EVALUATED', model_fidelity: 'NETWORK_PACKET_SIMULATION', limitations: ['network packet simulation only'] }],
});
const STUB_MATRIX = { run_id: 'run-1', revision_id: 'p-stub-r01', availability: 'MEASURED', source: { trace: 'analyses/network_completion/run/workload.trace', backend: 'BOOKSIM_STANDALONE', declared_packets: 96 }, nodes: 4, packets: 96, flits: 768, distinct_pairs: 3, classes: { 0: 96 }, matrix: [[0, 48, 0, 0], [0, 0, 24, 0], [0, 0, 0, 24], [0, 0, 0, 0]], flit_matrix: [[0, 384, 0, 0], [0, 0, 192, 0], [0, 0, 0, 192], [0, 0, 0, 0]], pairs: [{ src: 0, dst: 1, packets: 48, flits: 384 }, { src: 1, dst: 2, packets: 24, flits: 192 }, { src: 2, dst: 3, packets: 24, flits: 192 }] };
const STUB_INTEGRITY = { run_id: 'run-1', packet_conservation: { declared: { value: 96, availability: 'MEASURED' }, loaded: { value: 96, availability: 'MEASURED' }, delivered: { value: 96, availability: 'MEASURED' } }, flit_conservation: { injected: { value: 768, availability: 'MEASURED' }, accepted: { value: 768, availability: 'MEASURED' } }, route_realization: { status: 'OBSERVED', scope: 'destination-aware first-hop realization', full_path_claimed: false, realized_digest: 'realizeddigest' }, evidence_id: 'sha256:' + '7'.repeat(64), analyses: { network_completion: { backend: 'BOOKSIM_STANDALONE', status: 'EVALUATED', packets: 96, flits: 768 } } };
const STUB_ARTIFACTS = { run_id: 'run-1', bundle: { schema_version: 1, algorithm: 'sha256', bundle_id: 'f'.repeat(64), file_count: 3, files: { 'analyses/network_completion/run/workload.trace': 'a'.repeat(64), 'analyses/network_completion/run/routing.dump': 'c'.repeat(64), 'summary.json': 'b'.repeat(64) } } };

test('a loaded run drives the live Analysis and Verify surfaces', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: { BOOKSIM_STANDALONE: { state: 'PRESENT', binary_present: true } } } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [STUB_PROJECT] } }));
  await page.route('**/gw/api/v1/projects/p-stub/draft', route => route.fulfill({ json: { contract_version: 1, request: STUB_REQUEST } }));
  await page.route('**/gw/api/v1/projects/p-stub', route => route.fulfill({ json: STUB_PROJECT }));
  await page.route('**/gw/api/v1/revisions/p-stub-r01/topology', route => route.fulfill({ json: STUB_TOPOLOGY }));
  await page.route('**/gw/api/v1/runs/run-1', route => route.fulfill({ json: stubRun('run-1', 4200, 'p-stub-r01') }));
  await page.route('**/gw/api/v1/runs/run-2', route => route.fulfill({ json: stubRun('run-2', 6000, 'p-stub-r00') }));
  await page.route('**/gw/api/v1/runs/run-1/traffic-matrix', route => route.fulfill({ json: STUB_MATRIX }));
  await page.route('**/gw/api/v1/runs/run-1/integrity', route => route.fulfill({ json: STUB_INTEGRITY }));
  await page.route('**/gw/api/v1/runs/run-1/artifacts', route => route.fulfill({ json: STUB_ARTIFACTS }));
  await page.route('**/gw/api/v1/compare*', route => route.fulfill({ json: {
    contract_version: 1, a: { run_id: 'run-1' }, b: { run_id: 'run-2' },
    compatibility: { compatible: false, metric_definitions_complete: true, metric_definition_issues: [], reasons: ['different revision (p-stub-r01 vs p-stub-r00)'] },
    rows: [{ key: 'completion_cycles', a: 4200, b: 6000, unit: 'cycles', definition_id: 'product.metric.completion_cycles.v1', comparable: false, verdict: 'NOT_COMPARABLE', differs: 'scenario', delta_b_minus_a: null, reason: 'different revision' }],
    note: 'No automatic winner.' } }));

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await expect(page.getByText('p-stub-r01 · live store')).toBeVisible();

  await page.goto('/#/analysis/summary');
  await expect(page.getByText('Run run-1', { exact: false })).toBeVisible();
  await expect(page.getByText('SATISFIED', { exact: true })).toBeVisible();
  await expect(page.getByText('4,200', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('stub fidelity warning')).toBeVisible();
  await expect(page.getByText('Authored fixture · not tool output')).toHaveCount(0);

  await page.goto('/#/analysis/metrics');
  await expect(page.getByText('completion_cycles', { exact: true })).toBeVisible();
  await expect(page.getByText('12.5', { exact: true })).toBeVisible();
  await expect(page.getByText('No histogram or percentiles supplied').first()).toBeVisible();

  await page.goto('/#/analysis/matrix');
  await expect(page.locator('.matrix-cell')).toHaveCount(16);
  await expect(page.getByText('MEASURED', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('analyses/network_completion/run/workload.trace').first()).toBeVisible();
  await expect(page.getByText('Share of delivered packets')).toBeVisible();

  await page.goto('/#/analysis/trace');
  await expect(page.getByLabel('Sealed artifact')).toContainText('routing.dump');
  await page.getByLabel('Sealed artifact').selectOption('analyses/network_completion/run/routing.dump');
  await expect(page.getByRole('button', { name: 'Decode first-hop realization', exact: true })).toBeVisible();
  await expect(page.getByText('realized first hops only', { exact: false })).toBeVisible();

  await page.goto('/#/analysis/comparison');
  await expect(page.getByText('Reported metrics side by side')).toBeVisible();
  await expect(page.getByText('Backend verdict: not comparable.', { exact: false })).toBeVisible();
  const backendSection = page.locator('.section').filter({ hasText: 'backend verdicts' });
  const backendRow = backendSection.getByRole('row').filter({ hasText: 'completion_cycles' });
  await expect(backendRow.getByText('product.metric.completion_cycles.v1', { exact: true })).toBeVisible();
  await expect(backendRow.getByText('NOT_COMPARABLE', { exact: true })).toBeVisible();
  await expect(backendRow.locator('td').nth(3)).toHaveText('—');

  await page.goto('/#/verify/checks');
  await expect(page.getByText('Packet conservation').first()).toBeVisible();
  await expect(page.getByText('OBSERVED', { exact: true }).first()).toBeVisible();

  await page.goto('/#/verify/evidence');
  await expect(page.getByText('Bundle files with recorded digests')).toBeVisible();
  await expect(page.locator('.section').filter({ hasText: 'Bundle files with recorded digests' }).getByText('summary.json', { exact: true })).toBeVisible();

  await page.goto('/#/analysis/logs-artifacts');
  await expect(page.getByText('Local activity + run', { exact: false })).toBeVisible();
  await expect(page.getByText('a'.repeat(64))).toBeVisible();
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
  await expect(page.getByText('Live draft · Stubbed 2x2 project', { exact: false })).toBeVisible();
  await expect(page.getByText('stub-model-30b', { exact: true })).toBeVisible();
  await expect(page.getByText('2 × 1 × 2 × 1 = 4')).toBeVisible();
  await expect(page.getByText('Parallelism 4 ≠ 3 declared tiles.')).toBeVisible();
  await expect(page.getByText('tp_collective', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('4.00 KiB')).toBeVisible();

  await page.goto('/#/workloads/editor');
  await expect(page.getByText('2 stages · 2 owners', { exact: false })).toBeVisible();
  await expect(page.getByText('layer0_moe', { exact: true })).toBeVisible();
  await expect(page.getByText('Not a schedule')).toBeVisible();

  await page.goto('/#/workloads/requirements');
  await expect(page.getByText('Binding', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('SATISFIED', { exact: true })).toBeVisible();
  await expect(page.getByText('Bandwidth floor', { exact: true })).toBeVisible();

  await page.goto('/#/workloads/bindings');
  await expect(page.getByText('No binding table in this draft.', { exact: false })).toBeVisible();
  await expect(page.getByText('More agents than attached seats')).toBeVisible();

  await page.goto('/#/workloads/assumptions');
  await expect(page.getByText('1000 MHz')).toBeVisible();
  await expect(page.getByText('null for every agent')).toBeVisible();

  await page.goto('/#/workloads/lowering');
  await expect(page.getByText('No lowering adapter.', { exact: false })).toBeVisible();
  await expect(page.getByText('Requirement has no matching traffic')).toBeVisible();
  await expect(page.getByText('Parallelism product 4 ≠ 3 tiles')).toBeVisible();
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
    const body = projectReads === 1 ? STUB_PROJECT : { ...STUB_PROJECT, runs: [...STUB_PROJECT.runs, { run_id: 'run-new', revision_id: 'p-stub-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', qualification: 'QUALIFIED', requirements_pass: true, completed_at: '2026-01-03T10:00:00+00:00', bundle_id: 'sha256:' + '1'.repeat(64), display_name: 'newly published run' }] };
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

  const launchSection = page.locator('.section').filter({ hasText: 'Run a new evaluation on this revision' });
  await expect(launchSection.getByText('Runs real backends and appends a run')).toBeVisible();
  await expect(launchSection.getByRole('checkbox', { name: 'Select SERVING_TTFT' })).toBeDisabled();
  await expect(launchSection.getByRole('checkbox', { name: 'Select NETWORK_COMPLETION' })).toBeChecked();
  const launchButton = launchSection.getByRole('button', { name: /^Launch/ });
  await expect(launchButton).toBeDisabled();
  await expect(launchSection.getByText('not READY and cannot be selected', { exact: false })).toBeVisible();

  await launchSection.getByText('I understand this runs real backend binaries', { exact: false }).click();
  await expect(launchButton).toBeEnabled();
  await launchButton.click();

  await expect(page.getByText(/Job\s*RUNNING|RUNNING/).first()).toBeVisible();
  await expect(page.getByText('Run published:', { exact: false }).first()).toBeVisible({ timeout: 10000 });
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

  await page.getByRole('button', { name: 'Edit draft' }).click();
  const sideLength = page.getByRole('spinbutton', { name: 'side length', exact: true });
  await sideLength.fill('4');
  await page.getByRole('button', { name: 'Validate topology' }).click();
  await expect(page.getByText('Topology accepted', { exact: true })).toBeVisible();
  expect(JSON.parse(previews[0]).topology).toMatchObject({ kind: 'mesh', side_length: 4, concentration: 1 });

  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(page.getByText('uncompiled changes')).toBeVisible();
  await expect(page.getByRole('spinbutton', { name: 'side length', exact: true })).toHaveValue('4');
  const saved = JSON.parse(puts[0]).request;
  expect(saved.topology).toMatchObject({ side_length: 4 });
  expect(saved.noc_controls).toBeDefined();
  expect(saved.agents.length).toBe(STUB_REQUEST.agents.length);

  await page.getByLabel('Topology family').selectOption('torus');
  await expect(page.getByRole('spinbutton', { name: 'side length', exact: true })).toHaveValue('4');
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
    schema_version: 2, compiler_semantics_version: 3, design_hash: 'sha256:legacy',
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
  await page.getByRole('button', { name: 'Edit draft' }).click();
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
  await page.getByRole('button', { name: 'Review new instance' }).click();
  await page.getByLabel('Endpoint identifier').fill('EP_NPU_0');
  await expect(page.getByRole('button', { name: 'Add to local draft' })).toBeDisabled();
  await page.getByLabel('Endpoint identifier').fill('EP_TEST_0');
  await page.getByRole('button', { name: 'Add to local draft' }).click();
  await page.locator('.view-sidebar').getByRole('link', { name: 'Hardware endpoints', exact: true }).click();
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
  await page.goto('/#/explore/results');
  await page.getByRole('button', { name: 'Select candidate C-09', exact: true }).click();
  await page.getByRole('link', { name: 'Compare observations' }).click();
  await expect(page.getByRole('heading', { name: 'Candidate Comparison', exact: true })).toBeVisible();
  await page.locator('.view-sidebar').getByRole('link', { name: 'Adoption / branch', exact: true }).click();
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
  await expect(page.getByRole('status')).toContainText('could not be read');
  expect(await page.evaluate(key => localStorage.getItem(key), STORAGE_KEY)).toBe('{invalid');
  await page.getByRole('link', { name: 'Skip to workspace' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-workspace')).toBeFocused();
  expect(page.url()).toContain('#/design/system');
  await page.getByRole('button', { name: 'Inspector', exact: true }).click();
  await expect(page.locator('#selection-inspector')).toBeVisible();
  await page.getByRole('button', { name: 'Close inspector', exact: true }).click();
  await page.keyboard.press('Control+k');
  await page.getByRole('textbox', { name: 'Search views' }).fill('artifact');
  await page.getByRole('button', { name: 'Artifact Inspection & Export Deliver' }).click();
  await expect(page.getByRole('heading', { name: 'Artifact Inspection & Export', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Accept current preview for saving' }).click();
  expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!).version, STORAGE_KEY)).toBe(1);
});
