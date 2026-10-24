import { expect, test, type Page } from '@playwright/test';

type Calls = { puts: any[]; posts: { path: string; body: any }[]; releaseA?: () => void };
async function backend(page: Page, delayedA = false, failPut?: { status: number; detail: string }) {
  const calls: Calls = { puts: [], posts: [] };
  let stored: any = { schema_version: 4, topology: { kind: 'mesh', side_length: 2, concentration: 1 }, physical: { clock_freq_mhz: 1000, data_width: 128 }, noc_controls: { link_width: 64 }, agents: [{ kind: 'compute_tile', count: 1, data_width: 128, protocol: 'AXI' }], workload: { model_name: 'tiny', tp: 1 }, requirements: [], dependencies: [], address_map: { ranges: [] } };
  const hold = delayedA ? new Promise<void>(resolve => { calls.releaseA = resolve; }) : Promise.resolve();
  const detail = (id: string) => ({ project: { project_id: id, name: `Project ${id}`, updated_at: '2026-01-01', created_at: '2026-01-01' }, active_revision_id: `${id}-r01`, active_revision: { revision_id: `${id}-r01`, design_hash: 'h1', design: {} }, runs: [] });
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
    else if (path.endsWith('/artifacts')) json = { design_hash: 'h1', nodes: [{ artifact: 'topology', label: 'Compiled topology', hash: 'real-hash', proved_by: ['CONNECTED'] }] };
    else if (path === '/optimization/capabilities') json = { guided_parameters: [{ name: 'link_width', kind: 'int', executable: true, qualified_for_certified_optimization: true }] };
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

test('structured draft sections require revalidation and save canonical fields', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await page.getByRole('button', { name: 'Edit draft', exact: true }).click();
  await page.getByRole('button', { name: 'Add requirement', exact: true }).click();
  await page.getByLabel('requirement 1 traffic class').fill('bulk');
  await page.getByLabel('requirement 1 qos class').selectOption('latency_critical');
  await page.getByLabel('requirement 1 latency ceiling').fill('100');
  await page.getByLabel('requirement 1 binding').check();
  await page.getByRole('button', { name: 'Add address range', exact: true }).click();
  await page.getByLabel('address range 1 name').fill('memory');
  await page.getByLabel('address range 1 base').fill('0x1000');
  await page.getByLabel('address range 1 size').fill('4096');
  await page.getByLabel('address range 1 target').fill('1');
  await page.getByRole('button', { name: 'Add dependency', exact: true }).click();
  await page.getByLabel('dependency 1 source').fill('bulk');
  await page.getByLabel('dependency 1 target').fill('other');
  await page.getByRole('button', { name: 'Add collective', exact: true }).click();
  await page.getByLabel('collective 1 payload bytes').fill('128');
  await page.getByLabel('collective 1 traffic class').fill('bulk');
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await page.getByLabel('requirement 1 traffic class').fill('renamed');
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeDisabled();
  await page.getByLabel('requirement 1 traffic class').fill('bulk');
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect.poll(() => calls.puts.length).toBe(1);
  expect(calls.puts[0]).toMatchObject({
    schema_version: 4,
    address_map: { ranges: [{ name: 'memory', base: 4096, size: 4096, target_agent_idx: 1 }] },
    requirements: [{ traffic_class: 'bulk', qos_class: 'latency_critical', latency_ceiling_cycles: 100, bandwidth_floor_gbps: null, binding: true }],
    dependencies: [{ source: 'bulk', target: 'other', kind: 'blocking' }],
    workload: { model_name: 'tiny', tp: 1, collectives: [{ kind: 'allreduce', dimension: 'TP', payload_bytes: 128, traffic_class: 'bulk', source_rank: null }] },
  });
});

test('explicit topology graphs are authored structurally, not pasted as JSON', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await page.getByRole('button', { name: 'Edit draft', exact: true }).click();
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
  await page.getByRole('button', { name: 'Compile draft', exact: true }).click();
  await expect(page.getByText('Insufficient endpoint seats', { exact: true })).toBeVisible();
});

test('live capability, obligation, delivery and bounded study panels use backend documents', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'verify/support'); await expect(page.getByText('TEST_BACKEND', { exact: true })).toBeVisible();
  await expect(page.getByText('power_isolation', { exact: true })).toBeVisible();
  await go(page, 'verify/obligations'); await expect(page.getByText('OBL-TXN-01', { exact: true })).toBeVisible();
  await expect(page.getByText('Design obligations, not capability gaps.', { exact: true }).first()).toBeVisible();
  await go(page, 'deliver/readiness'); await expect(page.getByText('Compiled topology', { exact: true })).toBeVisible();
  await go(page, 'explore/brief');
  await page.getByRole('checkbox', { name: /Approve this revision/ }).check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
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
  await page.getByRole('row').filter({ hasText: 'r1' }).getByRole('button', { name: 'Inspect', exact: true }).click();
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
  await go(page, 'explore/brief');
  await page.getByRole('checkbox', { name: /Approve this revision/ }).check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel study', exact: true }).click();
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible();
});

test('unconfigured AI cannot transmit a draft even with local consent checked', async ({ page }) => {
  const calls = await backend(page); await load(page);
  await go(page, 'agents/runtime');
  await expect(page.getByText('No server model configured', { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: /Allow this draft snapshot/ }).check();
  await expect(page.getByRole('button', { name: 'Request topology proposals', exact: true })).toBeDisabled();
  expect(calls.posts).toEqual([]);
});

test('a refused draft save surfaces the backend reason and keeps the editor open', async ({ page }) => {
  const calls = await backend(page, false, { status: 409, detail: 'STALE_REVIEW: draft changed; reload and review before writing' });
  await load(page);
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
    if (deleted) return route.fulfill({ json: { projects: [{ project: { project_id: 'b', name: 'Project b', updated_at: '2026-01-01', created_at: '2026-01-01' }, active_revision_id: 'b-r01', active_revision: { revision_id: 'b-r01', design_hash: 'h1', design: {} }, runs: [] }] } });
    return route.fallback();
  });
  await load(page, 'a');
  await page.getByRole('button', { name: 'Delete project…', exact: true }).click();
  await page.getByLabel('Delete confirmation').fill('a');
  await page.getByRole('button', { name: 'Delete permanently', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'Project a' })).toHaveCount(0);
  expect(deletes).toEqual(['DELETE /projects/a']);
  await expect(page.getByRole('row').filter({ hasText: 'Project b' })).toBeVisible();
});
