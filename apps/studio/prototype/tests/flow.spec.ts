import { expect, test, type Page } from '@playwright/test';

const id = 'p-flow';
const keys = ['mesh', 'concentrated_mesh', 'torus', 'fattree', 'flatfly', 'srota', 'gec_mecs', 'gec_hybrid', 'qtree_native', 'tree4_native', 'ring_native', 'fly_native'];
const initialRequest = {
  schema_version: 4, compiler_semantics_version: 3,
  topology: { kind: 'mesh', side_length: 4, concentration: 1 } as Record<string, any>,
  agents: [{ kind: 'compute_tile', count: 4, data_width: 128, addr_width: 64, protocol: 'AXI' }],
  physical: { clock_freq_mhz: 1000, data_width: 128, process_node_nm: 7, num_power_domains: 1 },
  noc_controls: { link_width: 128, arbitration: null as string | null, input_buffer_depth_flits_per_vc: 8, credit_return_latency_cycles: 1, allocator_iterations: 1, route_compute_cycles: 1, vc_alloc_cycles: 1, switch_alloc_cycles: 1, switch_traversal_cycles: 1 },
  workload: { model_name: 'custom workload', model_family: 'dense_transformer', serving_mode: 'mixed', tp: 2, dp: 1, ep: 1, pp: 1, collectives: [{ kind: 'allreduce', dimension: 'TP', payload_bytes: 4096, traffic_class: 'tp_collective', source_rank: null }] },
  compute: { stages: [] }, requirements: [], dependencies: [], address_map: { ranges: [] },
};

type FixtureOptions = { selected?: boolean; dirty?: boolean; noProject?: boolean; family?: string; validationFailure?: boolean; compileFailure?: boolean; previewAvailable?: boolean; requiresAck?: boolean; unselectable?: boolean; stale?: boolean; selectionConflict?: boolean };
async function fixture(page: Page, options: FixtureOptions = {}) {
  const state = {
    request: structuredClone(initialRequest), token: 'sha256:initial', dirty: options.dirty ?? false,
    revision: 'p-flow-r01', selected: options.selected ?? false,
    validationFailure: options.validationFailure ?? false, compileFailure: options.compileFailure ?? false,
    writes: [] as { path: string; method: string; body: any }[],
  };
  if (options.family === 'ring_native') state.request.topology = { kind: 'ring_native', router_count: 64 };
  if (['qtree_native', 'tree4_native', 'fly_native'].includes(options.family ?? '')) state.request.topology = { kind: options.family, radix: 4, levels: 3 };
  if (options.family === 'gec') state.request.topology = { kind: 'gec', mode: 'hybrid', grid_side_length: 4, concentration: 1, express_channel_groups_per_dimension: 1, destinations_per_express_channel: 3 };
  const job = { job_id: 'job-catalog', project_id: id, kind: 'CATALOG_EVALUATION', state: 'COMPLETED', cancellable: false, submitted_at: '2026-11-03T00:00:00Z', updated_at: '2026-11-03T00:00:01Z', result: {} };
  const selection = () => state.selected ? { job_id: job.job_id, candidate_id: 'c-mesh', topology_id: options.family ?? 'mesh', label: options.family ?? 'Mesh', workload_id: 'wl-fixture' } : null;
  const project = () => ({ project: { project_id: id, name: 'Flow project', created_at: '2026-11-03T00:00:00Z', updated_at: '2026-11-03T00:00:00Z' }, active_revision_id: state.revision, active_revision: { revision_id: state.revision, design: { locked_derived: { vc_count: 2 } } }, draft: { workload_id: 'fixture' }, revisions: [{ revision_id: state.revision, display_name: 'r01', compilation_status: 'COMPILED' }], runs: [] });
  const rows = () => keys.map((key, index) => ({ topology_id: key, label: key === 'mesh' ? 'Mesh' : key, topology: { kind: key }, trace_files: [`${key}-packets.trace`, `${key}-rank-0.et`, `${key}-rank-1.et`, `${key}-packets.trace`], attempt: index + 1, candidate_id: `c-${key}`, status: 'EVALUATED', selectable: !options.unselectable && !options.stale, requirements_pass: !options.unselectable, requires_backend_ack: options.requiresAck ?? false, objective_values: { completion_cycles: 100 + index }, analyses: [
    { question: 'NETWORK_COMPLETION', backend_id: 'BOOKSIM_STANDALONE', status: 'EVALUATED', normalized_metrics: [{ key: 'completion_cycles', value: 100 + index, unit: 'cycles', dimensions: [] }, { key: 'flits_injected', value: 10 + index, unit: 'flits', dimensions: [['traffic_class', `${key}_network`]] }] },
    { question: 'SYSTEM_MAKESPAN', backend_id: 'ASTRA2_EMBEDDED_BOOKSIM', status: 'EVALUATED', normalized_metrics: [{ key: 'system_makespan_cycles', value: 200 + index, unit: 'cycles', dimensions: [] }, { key: 'completion_cycles', value: 50 + index, unit: 'cycles', dimensions: [['traffic_class', `${key}_system`]] }] },
  ] }));
  await page.route('**/gw/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace('/gw/api/v1', ''), method = request.method();
    const body = () => request.postDataJSON();
    const ok = (json: unknown) => route.fulfill({ json });
    if (!['GET', 'HEAD'].includes(method)) state.writes.push({ path, method, body: body() });
    if (path === '/health') return ok({ status: 'ok', api: 'v1', backends: { BOOKSIM_STANDALONE: { binary_present: true }, ASTRA2_EMBEDDED_BOOKSIM: { binary_present: true } } });
    if (path === '/projects') return ok({ projects: options.noProject ? [] : [project()] });
    if (path === '/catalog/workloads') return ok({ workloads: [] });
    if (path === '/loom/capabilities') return ok({ topology: { families: [{ family: 'mesh', status: 'READY' }] } });
    if (path === `/projects/${id}`) return ok(project());
    if (path === `/projects/${id}/draft`) {
      if (method === 'PUT') {
        if (body().expected_draft_design_hash !== state.token) return route.fulfill({ status: 409, json: { detail: 'Stale draft version' } });
        state.request = body().request; state.token = `sha256:saved-${state.writes.length}`; state.dirty = true;
      }
      return ok({ request: state.request, dirty: state.dirty, design_hash: state.token });
    }
    if (path === `/projects/${id}/jobs`) return ok({ jobs: [] });
    if (path === `/projects/${id}/catalog-evaluation-plan`) return ok({ draft_design_hash: state.token, workload_id: 'wl-fixture', participant_count: 2, operation_count: 1, compute_stages: 0, selection: selection(), backends: ['BOOKSIM_STANDALONE', 'ASTRA2_EMBEDDED_BOOKSIM'], topologies: keys.map(key => ({ topology_id: key, label: key === 'mesh' ? 'Mesh' : key, topology: { kind: key }, reason: null })) });
    if (path === `/projects/${id}/catalog-evaluations`) return ok(job);
    if (path === `/projects/${id}/catalog-evaluations/${job.job_id}`) return ok({ job, workload_id: 'wl-fixture', stale: options.stale ?? false, selection: selection(), artifacts: [], rows: rows() });
    if (path.includes('/candidates/') && path.endsWith('/select')) {
      if (options.selectionConflict || body().expected_draft_design_hash !== state.token) return route.fulfill({ status: 409, json: { detail: 'Stale draft version' } });
      if (options.requiresAck && !body().acknowledge_incomplete_backends) return route.fulfill({ status: 422, json: { detail: 'Backend coverage acknowledgment required' } });
      state.selected = true; state.token = 'sha256:selected'; state.dirty = true;
      return ok({ request: state.request, design_hash: state.token, dirty: true });
    }
    if (path === `/projects/${id}/topology-preview`) return state.validationFailure ? route.fulfill({ status: 422, json: { detail: 'Unsupported parameters' } }) : ok({ request: { ...body().request, topology: body().topology } });
    if (path === `/projects/${id}/compile`) {
      if (body().expected_draft_design_hash !== state.token) return route.fulfill({ status: 409, json: { detail: 'Stale compile version' } });
      if (state.compileFailure) return ok({ compilation: { status: 'FAILED', error: 'Compile refused for this fixture' } });
      state.dirty = false; state.revision = 'p-flow-r02';
      return ok({ revision_id: state.revision, design_hash: state.token, compilation: { status: 'COMPILED' } });
    }
    if (path.endsWith('/topology')) return ok({ contract_version: 1, family: 'mesh', counts: { routers: 4, channels: 0, endpoints: 4 }, routers: [0, 1, 2, 3].map(router_id => ({ router_id, coordinates: [router_id % 2, Math.floor(router_id / 2)] })), channels: [], endpoints: [], physical_links: [] });
    if (path.endsWith('/diff')) return ok({ has_basis: false, design_changes: [], derived_changes: [], capability_changes: [] });
    if (path.endsWith('/evaluation-plan')) return ok({ revision_id: state.revision, analyses: [{ question: 'NETWORK_COMPLETION', backend: 'BOOKSIM_STANDALONE', readiness: 'READY', support: 'SUPPORTED' }, { question: 'SYSTEM_MAKESPAN', backend: 'ASTRA2_EMBEDDED_BOOKSIM', readiness: 'READY', support: 'SUPPORTED' }] });
    if (path === `/projects/${id}/rtl-readiness`) return ok({ revision_id: state.revision, draft_design_hash: state.token, final_rtl_available: false, final_rtl_reason: 'General router RTL realization is not connected.', preview_available: options.previewAvailable ?? false, preview_blockers: options.previewAvailable ? [] : ['Evaluate the finalized revision first.'], limitations: ['Existing emitter is a 64-bit, 2-VC preview.'], selection: selection() });
    if (path === `/projects/${id}/rtl-previews`) return ok({ ...job, job_id: 'job-rtl', kind: 'RTL_PREVIEW' });
    if (path === `/projects/${id}/rtl-previews/job-rtl`) return ok({ stale: false, job: { ...job, job_id: 'job-rtl', kind: 'RTL_PREVIEW', result: { lint: 'PASS', lint_warning_count: 3, lint_clean: false } }, manifest: { scope: 'TOPOLOGY_ONLY_PREVIEW', final_implementation: false, limitations: ['Existing emitter is a 64-bit, 2-VC preview.'], lint: { status: 'PASS', warning_count: 3, clean: false }, emitted_packet_width_bits: 64, emitted_vcs: 2 } });
    if (path === '/agents/capabilities') return ok({ configured: false });
    if (path === '/ai-topology-search/capabilities') return ok({ configured: false, model: null, limits: { max_proposals: 4 } });
    return route.fulfill({ status: 404, json: { detail: `Unmocked read: ${path}` } });
  });
  if (!options.noProject) await page.addInitScript(() => localStorage.setItem('srota-gateway-selection:v1', JSON.stringify({ projectId: 'p-flow', runId: null })));
  return state;
}

async function open(page: Page, step: string) { await page.goto(`/#/flow/${step}`); }
const save = (page: Page) => page.getByRole('button', { name: 'Save & compile', exact: true });
const next = (page: Page) => page.getByRole('button', { name: 'Next · Final validation & RTL', exact: true });

test('workload -> full catalog -> explicit choice -> full parameter editor -> final validation', async ({ page }) => {
  const state = await fixture(page);
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await open(page, 'tune');
  await expect(page.getByRole('tablist', { name: 'Workload intent sections' }).getByRole('tab')).toHaveText(['Workload', 'Requirements']);
  await page.getByLabel('Model name').fill('my custom workload');
  const proceed = page.getByRole('button', { name: 'Next · Generate traffic & evaluate catalog', exact: true });
  await expect(proceed).toBeDisabled();
  await page.getByRole('button', { name: 'Save workload intent', exact: true }).click();
  await expect(proceed).toBeEnabled(); await proceed.click();
  await expect(page.getByRole('heading', { name: 'Choose fabrics to evaluate', exact: true })).toBeVisible();
  for (const key of keys) await expect(page.getByRole('checkbox', { name: key === 'mesh' ? 'Mesh' : key, exact: true })).toBeChecked();
  const launch = page.getByRole('button', { name: 'Generate trace & run catalog', exact: true });
  await expect(launch).toBeDisabled();
  await expect(page.getByText('No fabric is ranked yet.', { exact: false })).toBeVisible();
  await page.getByRole('checkbox', { name: 'Generate traffic from this saved workload and run BookSim + ASTRA-SIM for the selected fabrics.', exact: true }).check();
  await launch.click();
  await expect(page.getByRole('heading', { name: 'Recommended fabrics', exact: true })).toHaveCount(0);
  await expect(page.getByRole('group', { name: 'Recommended fabrics', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Fabric comparison', exact: true })).toBeVisible();
  const summary = page.locator('.catalog-summary');
  await expect(summary.getByText('Chosen fabric', { exact: true })).toBeVisible();
  await expect(summary.getByText('Lowest network completion', { exact: true })).toBeVisible();
  await expect(summary.getByText('Lowest system makespan', { exact: true })).toBeVisible();
  await expect(summary.getByText('Selectable', { exact: true })).toBeVisible();
  const setup = page.locator('.catalog-setup');
  await expect(setup).not.toHaveAttribute('open', '');
  await expect(page.getByRole('heading', { name: 'Deeper analysis', exact: true })).toHaveCount(0);
  await page.locator('summary').filter({ hasText: /^Related analysis & downloads$/ }).click();
  await expect(page.getByRole('link', { name: 'Analysis · Curves & Pareto', exact: true })).toHaveAttribute('href', '#/analysis/curves');
  await expect(page.getByRole('link', { name: 'Flow · Finalize & RTL', exact: true })).toHaveAttribute('href', '#/flow/run');
  expect(state.writes.find(write => write.path.endsWith('/catalog-evaluations'))?.body.topology_ids).toEqual(keys);
  await expect(page).toHaveURL(/#\/flow\/search$/);
  await expect(page.getByRole('link', { name: 'Compare results & choose fabric', exact: true })).toHaveCount(0);
  await expect(page.getByRole('navigation', { name: 'Flow views' }).getByRole('link')).toHaveCount(5);
  for (const profile of ['Network', 'System', 'Balanced', 'Best evidenced']) await expect(page.getByRole('button', { name: new RegExp(`^${profile}\\b`) })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Parameter refinement', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Network\b/ })).toContainText('No decisive fabric');
  await page.getByRole('button', { name: /^Balanced\b/ }).click();
  await page.getByRole('button', { name: 'Choose Mesh', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Selected fabric · Mesh', exact: true })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Refinement method' })).toBeVisible();
  await expect(page.getByText('Network baseline', { exact: true })).toBeVisible();
  await expect(page.getByText('System baseline', { exact: true })).toBeVisible();
  await expect(page.locator('.draft-save-bar')).toHaveCSS('position', 'sticky');
  await page.getByRole('tab', { name: 'Topology & sizing', exact: true }).click();
  await expect(page.getByLabel('Topology family')).toBeDisabled();
  await page.getByRole('tab', { name: 'Router & pipeline', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Allocator iterations', exact: true }).fill('2');
  await page.getByRole('spinbutton', { name: 'Switch traversal (cycles)', exact: true }).fill('3');
  await page.getByLabel('noc arbitration').selectOption('islip');
  await expect(page.getByRole('option', { name: 'Round robin (not executable)', exact: true })).toHaveAttribute('disabled', '');
  await expect(page.getByLabel('noc arbitration')).toHaveValue('islip');
  await expect(next(page)).toBeDisabled();
  await save(page).click(); await expect(next(page)).toBeEnabled();
  expect(state.request.noc_controls).toMatchObject({ allocator_iterations: 2, switch_traversal_cycles: 3, arbitration: 'islip' });
  expect(state.request.workload.model_name).toBe('my custom workload');
  const stored = state.writes.filter(write => write.method === 'PUT').at(-1)!;
  expect(state.writes.find(write => write.path.endsWith('/compile'))?.body.expected_draft_design_hash).not.toBe(stored.body.expected_draft_design_hash);
  await next(page).click();
  await expect(page.getByRole('heading', { name: 'Final fabric evaluation', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Launch 2 analyses', exact: true })).toBeDisabled();
  await expect(page.getByText('Final RTL unavailable.', { exact: true })).toBeVisible();
  await page.getByText('Why / preview limits').click();
  await expect(page.getByText(/General router RTL realization is not connected\./)).toBeVisible();
  expect(errors).toEqual([]);
});

test('old choose-fabric links open the merged catalog step', async ({ page }) => {
  await fixture(page);
  await open(page, 'compare');
  await expect(page.getByRole('heading', { name: 'Evaluate & choose fabric', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Choose fabrics to evaluate', exact: true })).toBeVisible();
  const navigation = page.getByRole('navigation', { name: 'Flow views' });
  await expect(navigation.getByRole('link')).toHaveCount(5);
  await expect(navigation.locator('[aria-current="page"]')).toHaveAttribute('href', '#/flow/search');
  await expect(navigation.locator('a[href="#/flow/compare"]')).toHaveCount(0);
});

test('compact comparison and adjacent inspector expose measurements, configuration and deduplicated files', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await fixture(page);
  await page.addInitScript(() => sessionStorage.setItem('srota-catalog:p-flow', 'job-catalog'));
  await open(page, 'search');
  const table = page.locator('table.catalog-results-table');
  const review = page.locator('.catalog-inspector');
  await expect(page.locator('.catalog-review')).toHaveCount(0);
  await expect(table.getByRole('columnheader')).toHaveText(['Fabric', 'Network', 'System', 'Requirements', 'RTL preview', 'Details']);
  const compact = async () => {
    await expect(table.locator('tbody > tr')).toHaveCount(keys.length);
    for (const row of await table.locator('tbody > tr').all()) {
      await expect(row.locator(':scope > th, :scope > td')).toHaveCount(6);
      await expect(row.getByRole('button', { name: /^Inspect/, exact: false })).toHaveCount(1);
      await expect(row.getByRole('button')).toHaveCount(1);
    }
    await expect(table.locator('details, pre, a, table')).toHaveCount(0);
    await expect(table).not.toContainText(/Per traffic class|flits injected|mesh_network|torus_network|\.trace|\.et|"kind"/);
  };
  const selected = async (label: string) => {
    await expect(review).toHaveCount(1);
    await expect(review).toHaveAttribute('aria-label', `${label} fabric details`);
    await expect(review.locator('header').getByRole('heading', { name: label, exact: true })).toBeVisible();
    await expect(review.getByRole('button', { name: `Choose ${label}`, exact: true })).toBeVisible();
    await expect(page).toHaveURL(/#\/flow\/search$/);
    if (await table.isVisible()) await compact();
  };
  await expect(review).toHaveCount(0);
  await compact();
  await table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^Mesh\b/ }) }).getByRole('button', { name: /^Inspect/, exact: false }).click();
  await selected('Mesh');
  await expect(review.getByRole('tab')).toHaveText(['Measurements', 'Configuration', 'Files (3)']);
  await expect(review.getByRole('tab', { name: 'Measurements', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(review.locator('details')).toHaveCount(0);
  for (const [scope, metric, value] of [['mesh_network', 'flits injected', '10 flits'], ['mesh_system', 'completion cycles', '50 cycles']]) {
    const metrics = review.getByRole('table').filter({ has: page.getByRole('columnheader', { name: scope, exact: true }) });
    await expect(metrics).toBeVisible();
    await expect(metrics.getByRole('row').filter({ has: page.getByRole('rowheader', { name: metric, exact: true }) }).locator('th, td')).toHaveText([metric, value]);
  }
  const comparison = await page.locator('.catalog-comparison').boundingBox();
  const inspector = await review.boundingBox();
  expect(comparison).not.toBeNull(); expect(inspector).not.toBeNull();
  expect(inspector!.x).toBeGreaterThanOrEqual(comparison!.x + comparison!.width - 1);
  expect(Math.abs(inspector!.y - comparison!.y)).toBeLessThan(2);
  await review.getByRole('tab', { name: 'Configuration', exact: true }).click();
  await expect(review.locator('pre').filter({ hasText: '"kind": "mesh"' })).toBeVisible();
  await expect(review.getByRole('heading', { name: 'Recorded controls & provenance', exact: true })).toBeVisible();
  await expect(review.getByRole('heading', { name: 'RTL preview limits', exact: true })).toBeVisible();
  await review.getByRole('tab', { name: 'Files (3)', exact: true }).click();
  await expect(review.getByRole('link')).toHaveCount(3);
  for (const file of ['mesh-packets.trace', 'mesh-rank-0.et', 'mesh-rank-1.et']) {
    const link = review.getByRole('link', { name: file, exact: true });
    await expect(link).toHaveAttribute('title', file);
    await expect(link).toHaveAttribute('download', '');
    await expect(link).toHaveAttribute('href', new RegExp(`${file.replaceAll('.', '\\.')}($|\\?)`));
    await expect(page.getByRole('link', { name: file, exact: true })).toHaveCount(1);
  }
  await expect(review.getByRole('link', { name: /Download execution graph|Download packet trace/ })).toHaveCount(0);
  await table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^torus\b/ }) }).getByRole('button', { name: /^Inspect/, exact: false }).click();
  await selected('torus');
  await expect(page.locator('pre').filter({ hasText: '"kind": "mesh"' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /^mesh-.*\.(trace|et)$/ })).toHaveCount(0);
  await expect(page.getByText(/^mesh_(network|system)$/, { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: /^Balanced\b/ }).click();
  await selected('Mesh');
  await page.getByRole('button', { name: 'Trade-off plot', exact: true }).click();
  await page.getByRole('button', { name: 'Inspect torus', exact: true }).focus();
  await page.keyboard.press('Enter');
  await selected('torus');
  await page.getByRole('button', { name: 'All fabrics', exact: true }).click();
  const origin = table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^Mesh\b/ }) }).getByRole('button', { name: /^Inspect/, exact: false });
  await origin.click();
  await review.getByRole('button', { name: 'Close details', exact: true }).click();
  await expect(review).toHaveCount(0);
  await expect(page.locator('.catalog-workbench')).toHaveClass(/no-selection/);
  await expect(origin).toBeFocused();
  await origin.click();
  await page.getByRole('button', { name: 'Trade-off plot', exact: true }).click();
  await review.getByRole('button', { name: 'Close details', exact: true }).click();
  await expect(page.getByRole('button', { name: 'All fabrics', exact: true })).toBeFocused();
});

for (const width of [1280, 760]) test(`catalog and inspector fit a ${width}px viewport`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  await fixture(page);
  await page.addInitScript(() => sessionStorage.setItem('srota-catalog:p-flow', 'job-catalog'));
  await open(page, 'search');
  await page.locator('.catalog-results-table').getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^Mesh\b/ }) }).getByRole('button', { name: /^Inspect/, exact: false }).click();
  await expect(page.locator('.catalog-inspector').getByRole('heading', { name: 'Mesh', exact: true })).toBeVisible();
  for (const selector of ['.catalog-workbench', '.catalog-comparison', '.catalog-inspector']) {
    const box = await page.locator(selector).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('inspecting another fabric does not change the chosen fabric', async ({ page }) => {
  const state = await fixture(page, { selected: true });
  await page.addInitScript(() => sessionStorage.setItem('srota-catalog:p-flow', 'job-catalog'));
  await open(page, 'search');
  const table = page.locator('.catalog-results-table');
  const mesh = table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^Mesh\b/ }) });
  await mesh.getByRole('button', { name: /^Inspect/, exact: false }).click();
  const inspector = page.locator('.catalog-inspector');
  await expect(inspector.getByText('Chosen fabric', { exact: true })).toBeVisible();
  await table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^torus\b/ }) }).getByRole('button', { name: /^Inspect/, exact: false }).click();
  await expect(inspector).toHaveAttribute('aria-label', 'torus fabric details');
  await expect(inspector.getByText('Inspecting fabric', { exact: true })).toBeVisible();
  await expect(inspector.getByText('Chosen fabric', { exact: true })).toHaveCount(0);
  await expect(mesh).toContainText(/chosen/i);
  expect(state.writes.filter(write => write.path.endsWith('/select'))).toEqual([]);
  await expect(page).toHaveURL(/#\/flow\/search$/);
});

test('incomplete coverage must be acknowledged separately for each reviewed fabric', async ({ page }) => {
  const state = await fixture(page, { requiresAck: true });
  await page.addInitScript(() => sessionStorage.setItem('srota-catalog:p-flow', 'job-catalog'));
  await open(page, 'search');
  const rows = page.getByRole('row');
  const review = (name: string) => rows.filter({ has: page.getByRole('rowheader', { name: new RegExp(`^${name}\\b`) }) }).getByRole('button', { name: /^Inspect/, exact: false });
  await review('Mesh').click();
  const acknowledge = page.getByRole('checkbox', { name: 'I understand that this fabric has incomplete backend coverage.', exact: true });
  await expect(page.getByRole('button', { name: 'Choose Mesh', exact: true })).toBeDisabled();
  await acknowledge.check();
  await expect(page.getByRole('button', { name: 'Choose Mesh', exact: true })).toBeEnabled();
  await review('torus').click();
  await expect(acknowledge).not.toBeChecked();
  await expect(page.getByRole('button', { name: 'Choose torus', exact: true })).toBeDisabled();
  await acknowledge.check();
  await page.getByRole('button', { name: 'Choose torus', exact: true }).click();
  await expect(page).toHaveURL(/#\/flow\/optimize$/);
  expect(state.writes.find(write => write.path.endsWith('/select'))?.body).toEqual({ expected_draft_design_hash: 'sha256:initial', acknowledge_incomplete_backends: true });
});

for (const scenario of ['unselectable', 'stale', 'selectionConflict'] as const) {
  test(`${scenario} catalog results cannot advance to refinement`, async ({ page }) => {
    const state = await fixture(page, { [scenario]: true });
    await page.addInitScript(() => sessionStorage.setItem('srota-catalog:p-flow', 'job-catalog'));
    await open(page, 'search');
    await page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^Mesh\b/ }) }).getByRole('button', { name: /^Inspect/, exact: false }).click();
    const choose = page.getByRole('button', { name: 'Choose Mesh', exact: true });
    if (scenario === 'selectionConflict') {
      await choose.click();
      await expect(page.getByText(/Gateway refused \(409\): Stale draft version/)).toBeVisible();
    } else {
      await expect(choose).toBeDisabled();
      expect(state.writes.filter(write => write.path.endsWith('/select'))).toEqual([]);
    }
    expect(state.selected).toBe(false);
    await expect(page).toHaveURL(/#\/flow\/search$/);
  });
}

test('stale results keep the chosen fabric but say the measurements predate the draft', async ({ page }) => {
  await fixture(page, { selected: true, stale: true });
  await page.addInitScript(() => sessionStorage.setItem('srota-catalog:p-flow', 'job-catalog'));
  await open(page, 'search');
  await expect(page.getByText(/These measurements predate the current saved draft/)).toBeVisible();
  await expect(page.getByRole('link', { name: 'Refine Mesh', exact: true })).toBeVisible();
});

test('parameter refinement is blocked until a measured fabric is chosen', async ({ page }) => {
  await fixture(page); await open(page, 'optimize');
  await expect(page.getByRole('heading', { name: 'Choose a measured fabric first', exact: true })).toBeVisible();
  await expect(save(page)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Propose & evaluate parameter changes', exact: true })).toHaveCount(0);
});

test('invalid parameters never save or compile', async ({ page }) => {
  const state = await fixture(page, { selected: true, validationFailure: true }); await open(page, 'optimize');
  await page.getByRole('tab', { name: 'Router & pipeline', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Link width (bits)', exact: true }).fill('256');
  await save(page).click();
  await expect(page.getByText(/Unsupported parameters/)).toBeVisible();
  expect(state.writes.filter(write => write.method === 'PUT' || write.path.endsWith('/compile'))).toEqual([]);
  await expect(next(page)).toBeDisabled();
});

test('compile failure retains edits and retries against the returned saved draft version', async ({ page }) => {
  const state = await fixture(page, { selected: true, compileFailure: true }); await open(page, 'optimize');
  await page.getByRole('tab', { name: 'Router & pipeline', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Link width (bits)', exact: true }).fill('256');
  await save(page).click(); await expect(page.getByText(/Draft saved; compilation did not finish/)).toBeVisible();
  await expect(next(page)).toBeDisabled();
  await expect(page.getByRole('spinbutton', { name: 'Link width (bits)', exact: true })).toHaveValue('256');
  const savedToken = state.token;
  await save(page).click();
  await expect.poll(() => state.writes.filter(write => write.method === 'PUT').length).toBe(2);
  expect(state.writes.filter(write => write.method === 'PUT')[1].body.expected_draft_design_hash).toBe(savedToken);
  state.compileFailure = false;
  await page.getByRole('spinbutton', { name: 'Link width (bits)', exact: true }).fill('128');
  await save(page).click(); await expect(next(page)).toBeEnabled();
  expect(state.request.noc_controls.link_width).toBe(128);
});

test('switching to AI cannot silently discard unsaved manual parameters', async ({ page }) => {
  await fixture(page, { selected: true }); await open(page, 'optimize');
  await page.getByRole('tab', { name: 'Router & pipeline', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Allocator iterations', exact: true }).fill('3');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'AI-assisted refinement', exact: true }).click();
  await expect(page.getByRole('spinbutton', { name: 'Allocator iterations', exact: true })).toHaveValue('3');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'AI-assisted refinement', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Model endpoint', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Propose & evaluate parameter changes', exact: true })).toBeDisabled();
  await expect(page.locator('details.assumptions')).toHaveCount(1);
});

for (const family of ['ring_native', 'qtree_native', 'tree4_native', 'fly_native', 'gec']) test(`${family} retains editable router controls after selection`, async ({ page }) => {
  const state = await fixture(page, { selected: true, family }); await open(page, 'optimize');
  await page.getByRole('tab', { name: 'Router & pipeline', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Allocator iterations', exact: true }).fill('2');
  if (family !== 'ring_native') await page.getByRole('tab', { name: 'Topology & sizing', exact: true }).click();
  if (family === 'gec') {
    await expect(page.getByRole('spinbutton', { name: 'Express groups per dimension', exact: true })).toBeVisible();
    await expect(page.getByRole('spinbutton', { name: 'Destinations per express group', exact: true })).toBeVisible();
  }
  if (family !== 'gec' && family !== 'ring_native') await expect(page.getByRole('spinbutton', { name: 'Radix', exact: true })).toHaveAttribute('readonly', '');
  await expect(save(page)).toBeEnabled(); await save(page).click(); await expect(next(page)).toBeEnabled();
  expect(state.request.topology.kind).toBe(family);
  expect(state.request.noc_controls.allocator_iterations).toBe(2);
});

test('a lint pass with warnings is never presented as clean RTL', async ({ page }) => {
  await fixture(page, { selected: true, previewAvailable: true }); await open(page, 'run');
  await page.getByRole('checkbox', { name: /^Generate limited topology-only RTL/ }).check();
  await page.getByRole('button', { name: 'Generate supported RTL preview', exact: true }).click();
  await expect(page.getByText('Verilator lint · PASS', { exact: true })).toBeVisible();
  await expect(page.getByText(/clean/i)).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Download preview archive & manifest', exact: true })).toHaveAttribute('download', '');
  await expect(page.getByText('Final RTL unavailable.', { exact: true })).toBeVisible();
  await page.getByText('Why / preview limits').click();
  await expect(page.getByText(/General router RTL realization is not connected\./)).toBeVisible();
});

test('a missing project explains the required starting point', async ({ page }) => {
  await fixture(page, { noProject: true }); await open(page, 'search');
  await expect(page.getByRole('heading', { name: 'Step 3 needs a project', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Go to step 1 · Workload template', exact: true })).toBeVisible();
});
