import { expect, test, type Page } from '@playwright/test';

const id = 'p-fixture';
const entry = {
  workload_id: 'fixture-workload',
  display_name: 'Fixture workload',
  description: 'A fixture workload for the start page.',
  source: 'tracks/t3-topology/examples/fixture.json',
  model_family: 'dense_transformer',
  model_name: 'fixture/model',
  parallelism: { tp: 1, dp: 1, ep: 1, pp: 1 },
  collectives: [],
  agents: [{ kind: 'compute_tile', count: 1 }],
  noc: { topology_family: 'mesh', link_width: 64 },
  request: { schema_version: 4, workload: { model_name: 'fixture/model' }, requirements: [], compute: { stages: [] } },
  evaluation_support: 'SUPPORTED',
  evaluation_readiness: 'READY',
  evaluation_supported: true,
};
const project = {
  project: { project_id: id, name: 'Fallback fixture', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  active_revision_id: null,
  runs: [],
};

async function mock(page: Page, options: { projects: unknown[] } = { projects: [project] }) {
  await page.route('**/gw/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/gw/api/v1', '');
    const ok = (json: unknown) => route.fulfill({ json });
    if (path === '/health') return ok({ status: 'ok', api: 'v1', backends: {} });
    if (path === '/projects') return ok({ projects: options.projects });
    if (path === `/projects/${id}`) return ok(project);
    if (path === `/projects/${id}/draft`) return ok({ request: {}, dirty: false, design_hash: 'sha256:fixture' });
    if (path === `/projects/${id}/jobs`) return ok({ jobs: [] });
    if (path === '/catalog/workloads') return ok({ workloads: [entry] });
    return route.fulfill({ status: 404, json: { detail: `Unmocked fixture request: ${path}` } });
  });
}

test('a deleted saved project falls back to the project list without an error banner', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('srota-gateway-selection:v1', JSON.stringify({ projectId: 'p-deleted', runId: null }));
    sessionStorage.setItem('srota-gateway-selection:v1', JSON.stringify({ projectId: 'p-deleted', runId: null }));
  });
  await mock(page, { projects: [] });
  await page.goto('/#/shared/projects');
  await expect(page.getByRole('heading', { name: 'Repository gateway projects', exact: true })).toBeVisible();
  await expect(page.getByText('Project unavailable', { exact: false })).toHaveCount(0);
});

test('workload definitions mount their JSON only when the fold opens', async ({ page }) => {
  await mock(page);
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).first().click();
  await page.goto('/#/flow/start');
  await expect(page.locator('.flow-workload-card')).toHaveCount(1);
  await expect(page.locator('.json-view')).toHaveCount(0);
  await page.locator('.flow-workload-definition > summary').click();
  await expect(page.locator('.json-view')).toHaveCount(1);
  await expect(page.locator('.json-view')).toContainText('schema_version');
});
