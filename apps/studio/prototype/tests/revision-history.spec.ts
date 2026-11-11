import { expect, test } from '@playwright/test';

const project = {
  project: { project_id: 'p-hist', name: 'History project', created_at: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-12T00:00:00+00:00' },
  active_revision_id: 'p-hist-r12',
  active_revision: { revision_id: 'p-hist-r12', display_name: 'r12', design: {} },
  revisions: [
    { revision_id: 'p-hist-r01', display_name: 'r01', created_at: '2026-01-01T00:00:00+00:00', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
    { revision_id: 'p-hist-r02', display_name: 'r02', created_at: '2026-01-02T00:00:00+00:00', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
    { revision_id: 'p-hist-r03', display_name: 'r03', created_at: '2026-01-03T00:00:00+00:00', compilation_status: 'UNSUPPORTED', error: '8 seats but 74 agents must attach' },
    { revision_id: 'p-hist-r11', display_name: 'r11', created_at: '2026-01-11T00:00:00+00:00', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
    { revision_id: 'p-hist-r12', display_name: 'r12', created_at: '2026-01-12T00:00:00+00:00', compilation_status: 'COMPILED', certificate_overall: 'PASS' },
  ],
  runs: [
    { run_id: 'run-a', revision_id: 'p-hist-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', requirements_pass: true, completed_at: '2026-01-01T10:00:00+00:00', bundle_id: 'bundle-a', analysis_backends: [{ question: 'NETWORK_COMPLETION' }] },
    { run_id: 'run-b', revision_id: 'p-hist-r01', status: 'UNSUPPORTED', completed_at: '2026-01-01T11:00:00+00:00', bundle_id: null },
    { run_id: 'run-c', revision_id: 'p-hist-r12', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', requirements_pass: true, completed_at: '2026-01-12T10:00:00+00:00', bundle_id: 'bundle-c', analysis_backends: [{ question: 'NETWORK_COMPLETION' }, { question: 'SYSTEM_MAKESPAN' }] },
  ],
};

const topology = { contract_version: 1, family: 'mesh', counts: { routers: 1, channels: 0, endpoints: 1 }, routers: [{ router_id: 0, coordinates: [0, 0] }], channels: [], endpoints: [{ endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 }] };

test('revision history keeps failed attempts visible and opens the exact run', async ({ page }) => {
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { projects: [project] } }));
  await page.route('**/gw/api/v1/projects/p-hist/draft', route => route.fulfill({ json: { request: null, dirty: false } }));
  await page.route('**/gw/api/v1/projects/p-hist', route => route.fulfill({ json: project }));
  await page.route('**/gw/api/v1/projects/p-hist/jobs*', route => route.fulfill({ json: { jobs: [] } }));
  await page.route('**/gw/api/v1/revisions/p-hist-r12/topology', route => route.fulfill({ json: topology }));
  await page.route('**/gw/api/v1/revisions/p-hist-r12/diff*', route => route.fulfill({ json: {
    revision_id: 'p-hist-r12',
    display_name: 'r12',
    against_revision_id: 'p-hist-r11',
    against_display_name: 'r11',
    has_basis: true,
    reason: null,
    design_changes: [],
    derived_changes: [],
    capability_changes: [{ field: 'capability.COMM-006', before: 'ep_dispatch', after: 'tp_reduce', kind: 'changed' }],
  } }));
  await page.route('**/gw/api/v1/runs/run-a', route => route.fulfill({ json: { run_id: 'run-a', project_id: 'p-hist', revision_id: 'p-hist-r01', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', evaluation: { metrics: { completion_cycles: 101 } } } }));
  await page.route('**/gw/api/v1/runs/run-c', route => route.fulfill({ json: { run_id: 'run-c', project_id: 'p-hist', revision_id: 'p-hist-r12', status: 'EVALUATED', backend: 'BOOKSIM_STANDALONE', evaluation: { metrics: { completion_cycles: 999 } } } }));

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load' }).first().click();
  await page.goto('/#/workloads/workflow');

  await expect(page.getByRole('heading', { name: 'Revision history' })).toBeVisible();
  await expect(page.getByRole('button', { name: /r03 UNSUPPORTED/ })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'r12 · run 1' })).toBeVisible();
  await expect(page.getByText('What changed from r11')).toBeVisible();

  await page.getByRole('button', { name: /r01 COMPILED/ }).click();
  const firstRun = page.getByRole('row').filter({ hasText: 'r01 · run 1' });
  await expect(firstRun).toContainText('NETWORK_COMPLETION');
  await firstRun.getByRole('button', { name: 'Open analysis', exact: true }).click();

  await expect(page).toHaveURL(/#\/analysis\/summary/);
  await expect(page.getByLabel('Selected run')).toHaveValue('run-a');
});
