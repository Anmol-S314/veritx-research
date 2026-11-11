import { expect, test } from '@playwright/test';

const request = {
  schema_version: 4,
  compiler_semantics_version: 4,
  topology: { kind: 'mesh', side_length: 2, concentration: 1 },
  agents: [{ kind: 'compute_tile', count: 4, data_width: 128, protocol: 'AXI' }],
  physical: { clock_freq_mhz: 1000, data_width: 128 },
  noc_controls: { link_width: 64 },
  workload: {
    model_name: 'intent-model',
    model_family: 'dense_transformer',
    serving_mode: 'mixed',
    tp: 1, dp: 1, ep: 1, pp: 1,
    collectives: [],
  },
  requirements: [],
  address_map: { ranges: [] },
  dependencies: [],
};

const project = {
  project: { project_id: 'p-intent', name: 'Intent stage project', created_at: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-02T00:00:00+00:00' },
  active_revision_id: 'p-intent-r01',
  active_revision: { revision_id: 'p-intent-r01', display_name: 'r01', design: {} },
  revisions: [{ revision_id: 'p-intent-r01', display_name: 'r01', created_at: '2026-01-01T00:00:00+00:00', compilation_status: 'COMPILED', certificate_overall: 'PASS' }],
  runs: [],
};

const topology = {
  contract_version: 1,
  family: 'mesh',
  counts: { routers: 4, channels: 8, endpoints: 4 },
  routers: [{ router_id: 0, coordinates: [0, 0] }, { router_id: 1, coordinates: [1, 0] }, { router_id: 2, coordinates: [0, 1] }, { router_id: 3, coordinates: [1, 1] }],
  channels: [],
  endpoints: [{ endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 }],
};

test('Intent stage keeps workload, fabric, requirements, and validation in one place', async ({ page }) => {
  const puts: string[] = [];
  let saved = request;
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { projects: [project] } }));
  await page.route('**/gw/api/v1/projects/p-intent', route => route.fulfill({ json: project }));
  await page.route('**/gw/api/v1/projects/p-intent/jobs*', route => route.fulfill({ json: { jobs: [] } }));
  await page.route('**/gw/api/v1/projects/p-intent/draft', route => {
    if (route.request().method() === 'PUT') {
      const body = JSON.parse(route.request().postData() ?? '{}');
      puts.push(route.request().postData() ?? '');
      saved = body.request;
      return route.fulfill({ json: { contract_version: 1, request: saved, dirty: true } });
    }
    return route.fulfill({ json: { contract_version: 1, request: saved, dirty: false } });
  });
  await page.route('**/gw/api/v1/projects/p-intent/compile', route => route.fulfill({ json: { revision_id: 'p-intent-r02', compilation: { status: 'COMPILED' }, certificate: { overall: 'PASS' } } }));
  await page.route('**/gw/api/v1/projects/p-intent/topology-preview', route => route.fulfill({ json: { request: { ...request, ...JSON.parse(route.request().postData() ?? '{}').request } } }));
  await page.route('**/gw/api/v1/revisions/p-intent-r01/topology', route => route.fulfill({ json: topology }));
  await page.route('**/gw/api/v1/revisions/p-intent-r01/diff*', route => route.fulfill({ json: { revision_id: 'p-intent-r01', display_name: 'r01', against_revision_id: null, against_display_name: null, has_basis: false, reason: 'first revision', design_changes: [], derived_changes: [], capability_changes: [] } }));
  await page.route('**/gw/api/v1/catalog/workloads', route => route.fulfill({ json: { workloads: [{ workload_id: 'catalog-one', display_name: 'Catalog one' }] } }));

  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).first().click();
  await page.goto('/#/workloads/workflow');

  await expect(page.getByRole('button', { name: 'Set workload', exact: true })).toHaveCount(0);
  const tabs = page.getByRole('tablist', { name: 'Intent sections' });
  await expect(tabs.getByRole('tab')).toHaveText(['Workload', 'Requirements', 'Fabric', 'Validate']);
  await expect(page.getByRole('heading', { name: 'Workload identity' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Compile draft', exact: true })).toBeVisible();

  await tabs.getByRole('tab', { name: 'Fabric' }).click();
  await page.getByRole('tab', { name: 'Topology & sizing', exact: true }).click();
  await expect(page.getByLabel('Topology family')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Validate topology', exact: true })).toBeVisible();

  await tabs.getByRole('tab', { name: 'Requirements' }).click();
  await expect(page.getByRole('heading', { name: 'Acceptance criteria' })).toBeVisible();

  await tabs.getByRole('tab', { name: 'Validate' }).click();
  await expect(page.getByText('Readiness checks', { exact: true })).toBeVisible();

  await tabs.getByRole('tab', { name: 'Workload' }).click();
  await page.getByLabel('Model name').fill('intent-model-2');
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect.poll(() => puts.length).toBe(1);
  expect(JSON.parse(puts[0]).request.workload.model_name).toBe('intent-model-2');
  await expect(page.getByRole('button', { name: 'Compile draft', exact: true })).toBeEnabled();
});
