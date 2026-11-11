import { expect, test, type Page } from '@playwright/test';

const project = {
  project: { project_id: 'p-v3', name: 'Legacy v3 project', created_at: '2026-01-01T00:00:00+00:00', updated_at: '2026-01-02T00:00:00+00:00' },
  active_revision_id: null,
  active_revision: null,
  revisions: [],
  runs: [],
};

const v3draft = {
  schema_version: 3,
  compiler_semantics_version: 3,
  topology: undefined,
  noc_config: { topology_family: 'mesh', concentration: 1, link_width: 64, radix: null },
  agents: [{ kind: 'compute_tile', count: 4, data_width: 128, addr_width: 64, protocol: 'AXI' }],
  physical: { clock_freq_mhz: 1000, data_width: 128, num_power_domains: 1, process_node_nm: 7 },
  workload: { model_name: 'legacy-dense', model_family: 'dense_transformer', serving_mode: 'mixed', tp: 2, dp: 1, ep: 1, pp: 1, collectives: [] },
  requirements: [],
  address_map: { ranges: [] },
  dependencies: [],
};

const v4draft = {
  ...v3draft,
  schema_version: 4,
  topology: { kind: 'mesh', side_length: 8, concentration: 1 },
  noc_controls: { link_width: 64, arbitration: null, obfuscation_level: 0, input_buffer_depth_flits_per_vc: 4 },
  noc_config: undefined,
  migration_provenance: { from: 3, to: 4 },
};

const topology = { contract_version: 1, family: 'mesh', counts: { routers: 4, channels: 0, endpoints: 4 }, routers: [{ router_id: 0, coordinates: [0, 0] }], channels: [], endpoints: [{ endpoint_id: 0, router_id: 0, kind: 'compute_tile', port_id: 0 }] };

async function mock(page: Page) {
  const previews: any[] = [];
  const puts: any[] = [];
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [project] } }));
  await page.route('**/gw/api/v1/projects/p-v3', route => route.fulfill({ json: project }));
  await page.route('**/gw/api/v1/projects/p-v3/draft', route => {
    if (route.request().method() === 'PUT') {
      puts.push(JSON.parse(route.request().postData() ?? '{}'));
      return route.fulfill({ json: { request: v4draft, dirty: true, design_hash: 'sha256:v4' } });
    }
    return route.fulfill({ json: { contract_version: 1, request: puts.at(-1)?.request ?? v3draft, dirty: puts.length > 0, design_hash: puts.length ? 'sha256:v4' : 'sha256:v3' } });
  });
  await page.route('**/gw/api/v1/projects/p-v3/topology-preview', async route => {
    const body = JSON.parse(route.request().postData() ?? '{}');
    previews.push(body);
    return route.fulfill({ json: { contract_version: 1, request: body.request?.schema_version === 4 ? body.request : v4draft } });
  });
  await page.route('**/gw/api/v1/projects/p-v3/jobs*', route => route.fulfill({ json: { contract_version: 1, jobs: [] } }));
  await page.route('**/gw/api/v1/ablations/catalog', route => route.fulfill({ json: {
    workloads: [{ workload_id: 'legacy-dense', label: 'Legacy dense trace', nodes: 4, events: 10, trace_sha256: 'abc' }],
    topologies: [{ topology_id: 'mesh8x8', label: 'Mesh 8×8', family: 'MESH', nodes: 64 }],
    defaults: { packet_size: 5, vc_buf_size: 4, use_noc_latency: 0, seed: 1 },
    knob_dimensions: { vc_buf_size: { values: [4] } }, override_exclusions: [], max_overrides: 32,
    simulators: { booksim: true, booksim_power_audited: false },
  } }));
  await page.route('**/gw/api/v1/catalog/knob-inventory', route => route.fulfill({ json: { backend: { knobs: [] } } }));
  await page.route('**/gw/api/v1/ablations', route => route.fulfill({ json: {
    schema: 'veritx/workload-ablation-run/1', out: 'test-run', duration_seconds: 1, returncode: 0, failed_cells: 0,
    document: { runs: [{
      workload: 'legacy-dense', topology: 'mesh8x8', status: 'ok',
      latency_p95: 10, throughput_packets_per_cycle: 5, native_power_w: 90, native_area_mm2: 3, total_energy_pj: 100, power_cycles: 10, log: 'mesh.log',
      native_model: { status: 'AVAILABLE', model_id: 'test-v1', technology: 'test tech', clock_hz: 1e12, energy_definition: 'modeled power interval', channel_width_bits: 64 },
      resource_cost: { routers: 64, crosspoints: 4320, storage_flits: 15360 },
    }] },
  } }));
  return { previews, puts };
}

test('applying a catalog fabric to a legacy v3 draft sends no root topology and saves the v4 canonical request', async ({ page }) => {
  const { previews, puts } = await mock(page);
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).first().click();
  await page.goto('/#/explore/fabric-search');
  await expect(page.getByLabel('Reference trace')).toHaveValue('legacy-dense');
  await page.getByRole('button', { name: 'Find fabrics', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '1 evaluations complete' })).toBeVisible();
  await page.locator('.fabric-selection').scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: 'Apply topology to draft', exact: true }).click();
  await expect.poll(() => puts.length).toBe(1);
  await expect(page).toHaveURL(/#\/workloads\/workflow/);

  // The v3 parser rejects a root `topology` field before it can migrate the
  // document. The preview must send the v3 request unchanged.
  expect(previews.length).toBeGreaterThan(0);
  expect(previews[0].request.topology).toBeUndefined();
  expect(previews[0].request.noc_controls).toBeUndefined();
  expect(previews[0].topology).toMatchObject({ kind: 'mesh', side_length: 8 });

  expect(puts[0].request.schema_version).toBe(4);
  expect(puts[0].request.topology).toMatchObject({ kind: 'mesh', side_length: 8, concentration: 1 });
  expect(puts[0].request.noc_controls).toMatchObject({ link_width: 64, input_buffer_depth_flits_per_vc: 4 });
  expect(puts[0].request.noc_config).toBeUndefined();
});

test('the full fabric editor explicitly migrates v3 before editing v4 router controls', async ({ page }) => {
  const { previews, puts } = await mock(page);
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).first().click();
  await page.goto('/#/workloads/workflow');
  await page.getByRole('tab', { name: 'Fabric', exact: true }).click();
  await page.getByRole('tab', { name: 'Topology & sizing', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Routers per side', exact: true }).fill('2');
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect.poll(() => puts.length).toBe(1);
  await page.getByRole('tab', { name: 'Fabric', exact: true }).click();
  await page.getByRole('tab', { name: 'Router & pipeline', exact: true }).click();
  await page.getByRole('spinbutton', { name: 'Buffer depth (flits/VC)', exact: true }).fill('8');
  await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect.poll(() => puts.length).toBe(2);
  expect(previews[0].request.schema_version).toBe(3);
  expect(previews[0].request.topology).toBeUndefined();
  expect(previews[0].topology).toMatchObject({ kind: 'mesh', side_length: 2, concentration: 1 });
  expect(puts[1].request.schema_version).toBe(4);
  expect(puts[1].request.noc_controls).toMatchObject({ link_width: 64, input_buffer_depth_flits_per_vc: 8 });
  expect(puts[1].request.noc_config).toBeUndefined();
  expect(puts[1].expected_draft_design_hash).toBe('sha256:v4');
});

test('an unmatched project workload gets a choice before the reference catalog controls', async ({ page }) => {
  await mock(page);
  await page.route('**/gw/api/v1/projects/p-v3/draft', route => route.fulfill({ json: {
    contract_version: 1,
    request: { ...v3draft, workload: { ...v3draft.workload, model_name: 'Qwen/Qwen3-32B' } },
    dirty: false,
    design_hash: 'sha256:v3',
  } }));
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).first().click();
  await page.goto('/#/explore/fabric-search');
  await expect(page.getByRole('heading', { name: 'Choose what to measure', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Find fabrics', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Measure this project', exact: true }).click();
  await expect(page).toHaveURL(/#\/flow\/search$/);
  await expect(page.getByRole('heading', { name: 'Evaluate & choose fabric', exact: true })).toBeVisible();
});
