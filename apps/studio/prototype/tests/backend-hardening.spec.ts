import { expect, test, type Page } from '@playwright/test';

type Calls = { puts: any[]; posts: { path: string; body: any }[]; releaseA?: () => void };
async function backend(page: Page, delayedA = false, failPut?: { status: number; detail: string }, initial?: Record<string, any>) {
  const calls: Calls = { puts: [], posts: [] };
  let stored: any = initial ?? { schema_version: 4, topology: { kind: 'mesh', side_length: 2, concentration: 1 }, physical: { clock_freq_mhz: 1000, data_width: 128 }, noc_controls: { link_width: 64 }, agents: [{ kind: 'compute_tile', count: 1, data_width: 128, protocol: 'AXI' }], workload: { model_name: 'tiny', tp: 1 }, requirements: [], dependencies: [], address_map: { ranges: [] } };
  const hold = delayedA ? new Promise<void>(resolve => { calls.releaseA = resolve; }) : Promise.resolve();
  const detail = (id: string) => ({ project: { project_id: id, name: `Project ${id}`, updated_at: '2026-01-01', created_at: '2026-01-01' }, active_revision_id: `${id}-r01`, active_revision: { revision_id: `${id}-r01`, design: {} }, runs: [] });
  await page.route('**/gw/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/gw/api/v1', '');
    const method = route.request().method(), body = route.request().postDataJSON();
    if (method === 'POST') calls.posts.push({ path, body });
    let json: any;
    if (path === '/health') json = { status: 'ok', backends: {} };
    else if (path === '/projects') json = { projects: [detail('a'), detail('b')] };
    else if (/^\/projects\/[ab]$/.test(path)) { if (path === '/projects/a') await hold; json = detail(path.at(-1)!); }
    else if (path.endsWith('/draft')) { if (method === 'PUT') { if (failPut) return route.fulfill({ status: failPut.status, json: { detail: failPut.detail } }); stored = body.request; calls.puts.push(stored); } json = { request: stored, design_hash: 'h1', dirty: calls.puts.length > 0 }; }
    else if (path.endsWith('/topology-preview')) json = { request: { ...body.request, topology: body.topology, schema_version: 4 } };
    else if (path.endsWith('/topology')) json = { family: 'mesh', counts: { routers: 1, channels: 0, endpoints: 1 }, routers: [{ router_id: 0, coordinates: [0, 0] }], channels: [], endpoints: [{ endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 }] };
    else if (path.endsWith('/jobs')) json = { jobs: [] };
    else if (path.endsWith('/compile')) json = { revision_id: 'a-r02', compilation: { status: 'UNSUPPORTED', error: 'Insufficient endpoint seats' } };
    else if (path === '/catalog/workloads') json = { workloads: [] };
    else if (path === '/catalog/fabric-presets') json = { presets: [] };
    else if (path === '/capabilities') json = { backends: { TEST_BACKEND: { execution: 'SUPPORTED', lowering: 'SUPPORTED', fidelity_note: 'network scope' } }, deferred: { formal: 'NOT_RUN' } };
    else if (path === '/catalog/capability-gaps') json = { gaps: [{ capability: 'power_isolation', source: 'model.py', line: 1 }] };
    else if (path === '/projects/a/obligations') json = { contract_version: 1, source: 'product.project_obligations.v1', project_id: 'a', revision_id: 'a-r01', run_id: null, generated_at: '2026-01-01', counts: { OPEN: 4, RESOLVED: 0, NOT_APPLICABLE: 0, blocking_open: 3 }, obligations: [{ obligation_id: 'OBL-TXN-01', category: 'measurement', title: 'Transaction-level latency', question: 'Do the declared latency requirements hold at the transaction level?', scope: 'Across declared QoS classes', state: 'OPEN', blocking: true, evidence: { summary: 'Network completion window only; transaction P95 is not modelled.' }, next_action: 'Add transaction-level measurement evidence.', sources: ['draft.requirements'] }], note: 'Design obligations, not capability gaps.' };
    else if (path.endsWith('/artifacts')) json = { nodes: [{ artifact: 'topology', label: 'Compiled topology', hash: 'real-hash', proved_by: ['CONNECTED'] }] };
    else if (path === '/optimization/capabilities') json = {
      guided_parameters: [{ name: 'link_width', kind: 'int', executable: true, qualified_for_certified_optimization: true }],
      workload_parameters: ['tp', 'ep', 'dp', 'pp'].map(name => ({ name, kind: 'int' })),
      federated_metrics: [
        { metric: 'system_makespan_cycles', question: 'SYSTEM_MAKESPAN', optimization_eligible: true },
        { metric: 'average_read_latency_cycles', question: 'DRAM_TIMING', optimization_eligible: true },
      ],
    };
    else if (path.endsWith('/optimize')) json = { job_id: 'study-job', project_id: 'a', state: 'QUEUED' };
    else if (path === '/jobs/study-job') json = { job_id: 'study-job', project_id: 'a', kind: 'OPTIMIZATION', state: 'COMPLETED', result: { optimization_id: 'study-result' } };
    else if (path === '/optimizations/study-result') json = { optimization_id: 'study-result', candidates: [{ candidate_id: 'candidate-real', status: 'EVALUATED' }] };
    else if (path === '/ai-topology-search/capabilities') json = { configured: false, reason: 'No server model configured', limits: { max_proposals: 4 } };
    else return route.fulfill({ status: 404, json: { detail: `Unstubbed ${method} ${path}` } });
    await route.fulfill({ json });
  });
  await page.goto('/#/shared/projects');
  return calls;
}
async function load(page: Page, id = 'a') { await page.getByRole('row').filter({ hasText: `Project ${id}` }).getByRole('button', { name: 'Load', exact: true }).click(); }
async function go(page: Page, route: string) { await page.evaluate(value => { location.hash = '/'+value; }, route); }
async function openStudy(page: Page) { await page.getByRole('button', { name: /Bounded study/ }).click(); }

test('late project reads cannot replace the selected project, and selection survives reload', async ({ page }) => {
  const calls = await backend(page, true);
  await load(page, 'a');
  await load(page, 'b');
  await expect(page.locator('.project-switch')).toHaveText('Project b');
  const old = page.waitForResponse(r => r.url().endsWith('/projects/a'));
  calls.releaseA!(); await old;
  await go(page, 'design/system');
  await expect(page.locator('.project-switch')).toHaveText('Project b');
  await page.reload();
  await expect(page.locator('.project-switch')).toHaveText('Project b');
});

test('fabric draft sections require revalidation and preserve workload intent', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'workloads/workflow');
  await page.getByRole('button', { name: 'Edit draft', exact: true }).click();
  await page.getByRole('button', { name: 'Add address range', exact: true }).click();
  await page.getByLabel('address range 1 name').fill('memory');
  await page.getByLabel('address range 1 base').fill('0x1000');
  await page.getByLabel('address range 1 size').fill('4096');
  await page.getByLabel('address range 1 target').fill('1');
  await page.getByRole('button', { name: 'Add dependency', exact: true }).click();
  await page.getByLabel('dependency 1 source').fill('bulk');
  await page.getByLabel('dependency 1 target').fill('other');
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Add requirement', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect.poll(() => calls.puts.length).toBe(1);
  expect(calls.puts[0]).toMatchObject({
    schema_version: 4,
    address_map: { ranges: [{ name: 'memory', base: 4096, size: 4096, target_agent_idx: 1 }] },
    dependencies: [{ source: 'bulk', target: 'other', kind: 'blocking' }],
    workload: { model_name: 'tiny', tp: 1 },
  });
});

test('fabric draft saves high 64-bit addresses without rounding', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'workloads/workflow');
  await page.getByRole('button', { name: 'Edit draft', exact: true }).click();
  await page.getByRole('button', { name: 'Add address range', exact: true }).click();
  await page.getByLabel('address range 1 name').fill('high-memory');
  await page.getByLabel('address range 1 base').fill('0x8000_0000_0000_3039');
  await page.getByLabel('address range 1 size').fill('4096');
  await page.getByLabel('address range 1 target').fill('1');
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect.poll(() => calls.puts.length).toBe(1);
  expect(calls.puts[0].address_map.ranges).toEqual([
    { name: 'high-memory', base: '9223372036854788153', size: 4096, target_agent_idx: 1 },
  ]);
});

test('legacy agent-map snapshots restore high addresses without Number rounding', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('srota-agent-map:v1:a:h1', JSON.stringify({
    agents: [{ kind: 'compute_tile', count: 1 }],
    windows: [{ id: 'legacy-high', name: 'HIGH', base: '9223372036854788153', size: '4096', targetAgentIdx: 0, selectionPolicy: null, targetInstanceIndex: null, interleaveBytes: null }],
  })));
  await backend(page); await load(page);
  await go(page, 'design/agent-map');
  await expect(page.getByLabel('Window base legacy-high')).toHaveValue('0x8000_0000_0000_3039');
});

test('the requirements page edits criteria and refuses a bound criterion with no bound', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'workloads/requirements');
  await expect(page.getByText('No criteria declared.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Add the first criterion', exact: true }).click();
  await page.getByLabel('criterion 1 binding').check();
  await expect(page.getByRole('button', { name: 'Save to draft', exact: true })).toBeDisabled();
  await page.getByLabel('criterion 1 traffic class').fill('bulk');
  await page.getByLabel('criterion 1 latency ceiling').fill('100');
  await expect(page.getByRole('button', { name: 'Save to draft', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Save to draft', exact: true }).click();
  await expect.poll(() => calls.puts.length).toBe(1);
  expect(calls.puts[0].requirements).toEqual([
    { traffic_class: 'bulk', qos_class: 'latency_critical', latency_ceiling_cycles: 100, bandwidth_floor_gbps: null, binding: true },
  ]);
});

test('the workload page edits collectives and migrates a v3 draft before adding compute stages', async ({ page }) => {
  const calls = await backend(page, false, undefined, {
    schema_version: 3,
    noc_config: { topology_family: 'mesh', concentration: 1, link_width: 64 },
    physical: { clock_freq_mhz: 1000, data_width: 128 },
    agents: [{ kind: 'compute_tile', count: 4, data_width: 128, protocol: 'AXI' }],
    workload: { model_name: 'tiny', tp: 1, collectives: [] },
    requirements: [{ traffic_class: 'tp_collective', qos_class: 'latency_critical', binding: true, latency_ceiling_cycles: 100 }],
    dependencies: [],
    address_map: { ranges: [] },
  });
  await load(page);
  await go(page, 'workloads/editor');
  await expect(page.getByText('No compute stages declared.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Add the first stage', exact: true }).click();
  await page.getByLabel('stage 1 duration ns').fill('2500');
  await page.getByLabel('stage 1 input bytes').fill('1024');
  await page.getByLabel('stage 1 weight bytes').fill('2048');
  await page.getByLabel('stage 1 output bytes').fill('512');
  await expect(page.getByText('Schema v3 draft.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Save to draft', exact: true }).click();
  await expect.poll(() => calls.posts.filter(post => post.path.endsWith('/topology-preview')).length).toBe(1);
  await expect.poll(() => calls.puts.length).toBe(1);
  expect(calls.puts[0]).toMatchObject({
    schema_version: 4,
    topology: { kind: 'mesh' },
    requirements: [{ traffic_class: 'tp_collective', qos_class: 'latency_critical', binding: true, latency_ceiling_cycles: 100 }],
    workload: { model_name: 'tiny', tp: 1 },
    compute: {
      source: { kind: 'declared' },
      stages: [{ stage_id: 'stage_1', owner: null, duration_ns: 2500, input_bytes: 1024, weight_bytes: 2048, output_bytes: 512 }],
    },
  });
});

test('explicit topology graphs are authored structurally, not pasted as JSON', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'workloads/workflow');
  await page.getByRole('button', { name: 'Edit draft', exact: true }).click();
  await page.getByRole('tab', { name: 'Topology & sizing', exact: true }).click();
  await page.getByLabel('Topology family').selectOption('explicit');
  await expect(page.getByText('Explicit topology graph', { exact: true })).toBeVisible();
  await page.getByLabel('Graph name').fill('pair');
  await page.getByLabel('explicit graph kind').selectOption('custom');
  await page.getByLabel('explicit graph nodes').fill('2');
  await page.getByLabel('explicit graph bandwidth').fill('32');
  await page.getByLabel('explicit graph latency').fill('1');
  await page.getByLabel('explicit graph links').fill('0 1');
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect.poll(() => calls.puts.length).toBe(1);
  expect(calls.puts[0].topology).toMatchObject({ kind: 'explicit', graph: { name: 'pair', kind: 'custom', nodes: 2, links: [[0, 1]], link_attrs: { bandwidth_GBs: 32, latency_ns: 1 } } });
});

test('HTTP success with a refused compilation displays the backend refusal', async ({ page }) => {
  await backend(page); await load(page);
  await go(page, 'workloads/workflow');
  await page.getByRole('button', { name: 'Compile draft', exact: true }).click();
  await expect(page.getByText('Insufficient endpoint seats', { exact: true })).toBeVisible();
});

test('generated report inventory is served read-only', async ({ page }) => {
  await backend(page); await load(page);
  const reports = [
    { report_id: 'dash', title: 'T3 dashboard', kind: 'dashboard', media_type: 'text/html', size_bytes: 2048, modified_at: '2026-01-01T00:00:00+00:00', source_path: 'report/t3/index.html' },
    { report_id: 'plot', title: 'Latency–throughput curves', kind: 'image', media_type: 'image/png', size_bytes: 4096, modified_at: '2026-01-01T00:00:00+00:00', source_path: 'tracks/t3-topology/results/baseline/latency_curves.png' },
  ];
  await page.route('**/gw/api/v1/reports', route => route.fulfill({ json: { contract_version: 1, reports } }));
  await go(page, 'deliver/package');
  await expect(page.getByText('Generated reports & plots', { exact: true })).toBeVisible();
  await expect(page.getByText('T3 dashboard', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /T3 dashboard/ })).toHaveAttribute('href', '/gw/api/v1/reports/dash');
  await expect(page.getByAltText('Latency–throughput curves')).toHaveAttribute('src', '/gw/api/v1/reports/plot');
});

test('live capability, obligation, delivery and bounded study panels use backend documents', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'verify/support'); await expect(page.getByText('TEST_BACKEND', { exact: true })).toBeVisible();
  await expect(page.getByText('power_isolation', { exact: true })).toBeVisible();
  await go(page, 'verify/obligations'); await expect(page.getByText('OBL-TXN-01', { exact: true })).toBeVisible();
  await go(page, 'deliver/readiness'); await expect(page.getByText('Compiled topology', { exact: false }).first()).toBeVisible();
  await go(page, 'explore/brief'); await openStudy(page);
  await page.getByRole('checkbox', { name: /Approve this revision/ }).check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
  await page.getByText('Raw study record', { exact: true }).click();
  await expect(page.getByText('candidate-real', { exact: false })).toBeVisible();
  const submitted = calls.posts.find(p => p.path.endsWith('/optimize'))!;
  expect(submitted.body).toMatchObject({ domain: [{ name: 'link_width', values: [64, 128] }], budget: { max_evaluations: 2 } });
});

test('late run responses cannot replace a newer run selection', async ({ page }) => {
  await backend(page);
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/gw/api/v1/projects/a', route => route.fulfill({ json: { project: { project_id: 'a', name: 'Project a' }, active_revision_id: 'a-r01', active_revision: { design: {} }, runs: ['r1', 'r2'].map((run_id, i) => ({ run_id, revision_id: 'a-r01', backend: 'BOOKSIM', bundle_id: run_id, requirements_pass: true, status: 'EVALUATED', completed_at: `2026-01-0${i+1}` })) } }));
  await page.route('**/gw/api/v1/runs/*', async route => {
    const id = route.request().url().split('/').pop();
    if (id === 'r2') await held;
    await route.fulfill({ json: { run_id: id, project_id: 'a', revision_id: 'a-r01', status: 'EVALUATED', backend: 'BOOKSIM', evaluation: { metrics: { completion_cycles: id === 'r1' ? 101 : 999 } } } });
  });
  await load(page);
  await go(page, 'analysis/metrics');
  await page.getByRole('row').filter({ hasText: 'r01 · run 1' }).getByRole('button', { name: 'Open analysis', exact: true }).click();
  await expect(page.getByLabel('Selected run')).toHaveValue('r1');
  const old = page.waitForResponse(r => r.url().endsWith('/runs/r2'));
  release(); await old;
  await expect(page.getByLabel('Selected run')).toHaveValue('r1');
  await expect(page.getByRole('row').filter({ hasText: 'completion_cycles' })).toContainText('101');
});

test('study cancellation refreshes the recorded job state', async ({ page }) => {
  await backend(page); await load(page);
  let cancelled = false;
  await page.route('**/gw/api/v1/jobs/study-job', route => route.fulfill({ json: { job_id: 'study-job', project_id: 'a', state: cancelled ? 'CANCELLED' : 'RUNNING', cancellable: !cancelled } }));
  await page.route('**/gw/api/v1/jobs/study-job/cancel', route => { cancelled = true; return route.fulfill({ json: { job_id: 'study-job', project_id: 'a', state: 'CANCELLED' } }); });
  await go(page, 'explore/brief'); await openStudy(page);
  await page.getByRole('checkbox', { name: /Approve this revision/ }).check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel study', exact: true }).click();
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible();
});

test('unconfigured AI cannot transmit a draft and cannot even consent', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'agents/runtime');
  // The empty state is the model-connection form, not a fake working action.
  await expect(page.getByText('Connect an OpenAI-compatible model to propose and evaluate parameter changes. Manual editing does not require a model.', { exact: true })).toBeVisible();
  const consent = page.getByRole('checkbox', { name: /Allow this draft snapshot/ });
  await expect(consent).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Request topology proposals', exact: true })).toBeDisabled();
  expect(calls.posts).toEqual([]);
});

test('a refused draft save surfaces the backend reason and keeps the editor open', async ({ page }) => {
  const calls = await backend(page, false, { status: 409, detail: 'STALE_REVIEW: draft changed; reload and review before writing' });
  await load(page);
  await go(page, 'workloads/workflow');
  await page.getByRole('button', { name: 'Edit draft', exact: true }).click();
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await expect.poll(() => calls.puts.length).toBe(0);
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByText(/Gateway refused \(409\)/, { exact: false })).toBeVisible();
  await expect(page.getByText(/STALE_REVIEW/, { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeVisible();
  await expect.poll(() => calls.puts.length).toBe(0);
});

test('a timed-out project read reports the timeout and keeps the project list usable', async ({ page }) => {
  await backend(page);
  await page.route('**/gw/api/v1/projects/a', () => new Promise(() => { /* never responds: the client must time out */ }));
  await load(page, 'a');
  await expect(page.getByText('did not answer within the client timeout', { exact: false })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('row').filter({ hasText: 'Project b' }).getByRole('button', { name: 'Load', exact: true })).toBeVisible();
});

test('an active evaluation job is rediscovered after a mid-job reload', async ({ page }) => {
  const running = { job_id: 'eval-job', project_id: 'a', kind: 'EVALUATION', revision_id: 'a-r01', state: 'RUNNING', submitted_at: '2026-01-01', updated_at: '2026-01-01', cancellable: true };
  await backend(page); await load(page);
  await page.route('**/gw/api/v1/projects/a/jobs*', route => route.fulfill({ json: { jobs: [running] } }));
  await page.route('**/gw/api/v1/jobs/eval-job', route => route.fulfill({ json: running }));
  await page.reload();
  await expect(page.getByText('1 running', { exact: true })).toBeVisible({ timeout: 15000 });
});

test('typed-id project deletion removes the project through the UI', async ({ page }) => {
  const deletes: string[] = [];
  let deleted = false;
  await backend(page);
  await page.route('**/gw/api/v1/projects/a', route => {
    if (route.request().method() === 'DELETE') { deleted = true; deletes.push('DELETE /projects/a'); return route.fulfill({ json: { deleted: true, project_id: 'a' } }); }
    if (deleted) return route.fulfill({ status: 404, json: { detail: 'no such project: a' } });
    return route.fallback();
  });
  await page.route('**/gw/api/v1/projects', route => {
    if (deleted) return route.fulfill({ json: { projects: [{ project: { project_id: 'b', name: 'Project b', updated_at: '2026-01-01', created_at: '2026-01-01' }, active_revision_id: 'b-r01', active_revision: { revision_id: 'b-r01', design: {} }, runs: [] }] } });
    return route.fallback();
  });
  await load(page, 'a');
  await go(page, 'workloads/workflow');
  await page.getByRole('button', { name: 'Delete project…', exact: true }).click();
  await page.getByLabel('Delete confirmation').fill('a');
  await page.getByRole('button', { name: 'Delete permanently', exact: true }).click();
  await go(page, 'shared/projects');
  await expect(page.getByRole('row').filter({ hasText: 'Project a' })).toHaveCount(0);
  expect(deletes).toEqual(['DELETE /projects/a']);
  await expect(page.getByRole('row').filter({ hasText: 'Project b' })).toBeVisible();
});

test('typed-id project deletion is available from the project list', async ({ page }) => {
  const deletes: string[] = [];
  let deleted = false;
  await backend(page);
  await page.route('**/gw/api/v1/projects/a', route => {
    if (route.request().method() === 'DELETE') {
      deleted = true;
      deletes.push('DELETE /projects/a');
      return route.fulfill({ json: { deleted: true, project_id: 'a' } });
    }
    return route.fallback();
  });
  await page.route('**/gw/api/v1/projects', route => {
    if (!deleted) return route.fallback();
    return route.fulfill({ json: { projects: [{ project: { project_id: 'b', name: 'Project b', updated_at: '2026-01-01', created_at: '2026-01-01' }, active_revision_id: 'b-r01', active_revision: { revision_id: 'b-r01', design: {} }, runs: [] }] } });
  });
  await load(page, 'a');
  await page.getByRole('row').filter({ hasText: 'Project a' }).getByRole('button', { name: 'Delete…', exact: true }).click();
  await page.getByLabel('Delete confirmation').fill('a');
  await page.getByRole('button', { name: 'Delete permanently', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'Project a' })).toHaveCount(0);
  expect(deletes).toEqual(['DELETE /projects/a']);
});


test('fabric comparison prepares only certified-convertible families without executing until approved', async ({ page }) => {  const calls = await backend(page, false, undefined, {
    schema_version: 4, topology: { kind: 'mesh', side_length: 4, concentration: 1 },
    workload: { tp: 2, collectives: [] }, agents: [{ kind: 'compute_tile', count: 4 }],
    compute: { stages: [{ stage_id: 'compute', duration_ns: 100 }] },
  });
  await page.route('**/gw/api/v1/optimization/capabilities', route => route.fulfill({ json: {
    guided_parameters: [{ name: 'topology_family', kind: 'enum', executable: true, qualified_for_certified_optimization: true, executable_values: ['mesh', 'concentrated_mesh', 'torus', 'ring'] }],
    federated_metrics: [{ metric: 'system_makespan_cycles', question: 'SYSTEM_MAKESPAN', optimization_eligible: true }],
  } }));
  await load(page); await go(page, 'explore/brief'); await openStudy(page);
  await page.getByRole('button', { name: 'Prepare fabric comparison', exact: true }).click();
  const familyValues = page.getByRole('group', { name: 'Values to test' });
  // The certified patcher converts mesh / concentrated_mesh / torus only; the
  // executable list alone is not evidence of a usable substitution.
  for (const family of ['mesh', 'concentrated_mesh', 'torus']) await expect(familyValues.getByRole('checkbox', { name: family, exact: true })).toBeChecked();
  await expect(familyValues.getByRole('checkbox', { name: 'ring', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Study objective')).toHaveValue('system_makespan_cycles');
  await expect(page.getByRole('button', { name: 'Launch bounded study', exact: true })).toBeDisabled();
  expect(calls.posts).toHaveLength(0);
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({ path: test.info().outputPath(`fabric-comparison-${width}.png`), fullPage: true });
  }
  await page.getByLabel('Approve this revision, objective, and 3 configurations to run real backends.').check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
  await expect.poll(() => calls.posts.filter(post => post.path.endsWith('/optimize')).length).toBe(1);
  expect(calls.posts.find(post => post.path.endsWith('/optimize'))!.body).toMatchObject({
    domain: [{ name: 'topology_family', values: ['mesh', 'concentrated_mesh', 'torus'] }],
    objectives: [{ metric: 'system_makespan_cycles', direction: 'MIN', question: 'SYSTEM_MAKESPAN' }],
    budget: { max_evaluations: 3 },
  });
  expect(calls.puts).toHaveLength(0);
});

test('a typed family the patcher cannot convert states why family comparison is unavailable', async ({ page }) => {
  await backend(page, false, undefined, {
    schema_version: 4, topology: { kind: 'srota' },
    workload: { tp: 2, collectives: [] }, agents: [{ kind: 'compute_tile', count: 4 }],
  });
  await page.route('**/gw/api/v1/optimization/capabilities', route => route.fulfill({ json: {
    guided_parameters: [{ name: 'topology_family', kind: 'enum', executable: true, qualified_for_certified_optimization: true, executable_values: ['mesh', 'concentrated_mesh'] }],
  } }));
  await load(page); await go(page, 'explore/brief'); await openStudy(page);
  await expect(page.getByRole('button', { name: 'Prepare fabric comparison', exact: true })).toBeDisabled();
  await expect(page.getByText('The certified patcher substitutes only mesh, concentrated mesh and torus; family comparison is unavailable for srota.', { exact: true })).toBeVisible();
});

test('multi-knob discovery previews the exact Cartesian grid and resets approval on edits', async ({ page }) => {
  const calls = await backend(page);
  await page.route('**/gw/api/v1/optimization/capabilities', route => route.fulfill({ json: {
    guided_parameters: [
      { name: 'topology_family', kind: 'enum', executable: true, qualified_for_certified_optimization: true, executable_values: ['mesh', 'torus'] },
      { name: 'link_width', kind: 'int', executable: true, qualified_for_certified_optimization: true },
    ],
  } }));
  await load(page); await go(page, 'explore/brief'); await openStudy(page);
  await page.getByRole('button', { name: 'Prepare multi-knob discovery', exact: true }).click();
  await expect(page.getByLabel('Study parameter (validated per candidate)')).toHaveValue('topology_family');
  await expect(page.getByLabel('Second fabric knob (optional)')).toHaveValue('link_width');
  const secondValues = page.getByRole('group', { name: 'Second knob values' });
  await expect(secondValues.getByText('64', { exact: true })).toBeVisible();
  await expect(secondValues.getByText('128', { exact: true })).toBeVisible();
  const preview = page.getByLabel('Declared candidate configurations');
  await expect(preview.locator('tbody tr')).toHaveCount(4);
  for (const patch of ['topology_family · link_width = mesh / 64', 'topology_family · link_width = mesh / 128', 'topology_family · link_width = torus / 64', 'topology_family · link_width = torus / 128']) await expect(preview.getByText(patch, { exact: true })).toBeVisible();
  expect(calls.posts).toHaveLength(0);
  const approve = page.getByLabel('Approve this revision, objective, and 4 configurations to run real backends.');
  await approve.check();
  await secondValues.getByRole('button', { name: '256', exact: true }).click();
  await expect(page.getByText('This grid has 6 configurations.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Launch bounded study', exact: true })).toBeDisabled();
  await secondValues.getByRole('button', { name: 'Remove 256', exact: true }).click();
  await expect(approve).not.toBeChecked();
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({ path: test.info().outputPath(`multi-knob-${width}.png`), fullPage: true });
  }
  await approve.check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
  await expect.poll(() => calls.posts.filter(post => post.path.endsWith('/optimize')).length).toBe(1);
  expect(calls.posts.find(post => post.path.endsWith('/optimize'))!.body).toMatchObject({
    domain: [{ name: 'topology_family', values: ['mesh', 'torus'] }, { name: 'link_width', values: [64, 128] }],
    objectives: [{ metric: 'completion_cycles', direction: 'MIN', question: 'NETWORK_COMPLETION' }],
    method: 'grid', budget: { max_evaluations: 4 }, seed: 7,
  });
  expect(calls.puts).toHaveLength(0);
});

test('TP/EP study binds declared demand, objective questions, and a four-cell budget', async ({ page }) => {
  const calls = await backend(page, false, undefined, {
    schema_version: 4, topology: { kind: 'mesh', side_length: 5, concentration: 1 },
    workload: { tp: 2, ep: 4, collectives: [] },
    agents: [{ kind: 'compute_tile', count: 16 }, { kind: 'hbm_controller', count: 1 }],
    compute: { stages: [{ stage_id: 'measured-input', duration_ns: 100, input_bytes: 64, weight_bytes: 128, output_bytes: 32, owner: 0 }] },
  });
  await load(page); await go(page, 'explore/brief'); await openStudy(page);
  await page.getByLabel('Study parameter (validated per candidate)').selectOption('tp');
  const tpValues = page.getByRole('group', { name: 'Values to test' });
  await expect(tpValues.getByText('2', { exact: true })).toBeVisible();
  await expect(tpValues.getByText('4', { exact: true })).toBeVisible();
  await page.getByLabel('Also sweep EP', { exact: false }).check();
  await page.getByLabel('Study objective').selectOption('system_makespan_cycles');
  await page.getByLabel('Include independent DRAM timing objective').check();
  await page.getByLabel('Approve this revision, objective, and 4 configurations to run real backends.').check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
  await expect.poll(() => calls.posts.filter(p => p.path.endsWith('/optimize')).length).toBe(1);
  expect(calls.posts.find(p => p.path.endsWith('/optimize'))!.body).toMatchObject({
    domain: [{ name: 'tp', values: [2,4] }, { name: 'ep', values: [2,4] }],
    objectives: [
      { metric: 'system_makespan_cycles', direction: 'MIN', question: 'SYSTEM_MAKESPAN' },
      { metric: 'average_read_latency_cycles', direction: 'MIN', question: 'DRAM_TIMING' },
    ], budget: { max_evaluations: 4 },
  });
  expect(calls.puts).toHaveLength(0);
  await tpValues.getByRole('button', { name: '8', exact: true }).click();
  await expect(page.getByText('This grid has 6 configurations.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Launch bounded study', exact: true })).toBeDisabled();
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({ path: test.info().outputPath('workload-study-' + width + '.png'), fullPage: true });
  }
});

test('system objectives require declared compute and memory requires an HBM controller', async ({ page }) => {
  await backend(page); await load(page); await go(page, 'explore/brief'); await openStudy(page);
  await expect(page.getByRole('button', { name: 'Prepare fabric comparison', exact: true })).toBeDisabled();
  await expect(page.getByText('The certified backend reports fewer than two executable families', { exact: false })).toBeVisible();
  await page.getByLabel('Study objective').selectOption('system_makespan_cycles');
  await expect(page.getByText('Declare compute stages in Workloads;', { exact: false })).toBeVisible();
  await expect(page.getByLabel('Include independent DRAM timing objective')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Launch bounded study', exact: true })).toBeDisabled();
});


test('memory operands alone do not invent an HBM controller for a study', async ({ page }) => {
  await backend(page, false, undefined, {
    schema_version: 4, topology: { kind: 'mesh', side_length: 2, concentration: 1 },
    workload: { tp: 2, ep: 1 }, agents: [{ kind: 'compute_tile', count: 4 }],
    compute: { stages: [{ stage_id: 'authored', duration_ns: 100, input_bytes: 64, weight_bytes: 128, output_bytes: 32, owner: 0 }] },
  });
  await load(page); await go(page, 'explore/brief'); await openStudy(page);
  await page.getByLabel('Study objective').selectOption('system_makespan_cycles');
  await expect(page.getByLabel('Include independent DRAM timing objective')).toBeDisabled();
  await page.getByLabel('Study objective').selectOption('average_read_latency_cycles');
  await expect(page.getByText('DRAM timing also requires memory operands and an HBM controller', { exact: false })).toBeVisible();
});
