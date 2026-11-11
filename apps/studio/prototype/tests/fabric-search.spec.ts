import { expect, test } from '@playwright/test';

test('Fabric search ranks measured results, filters limits, and carries a review-only Design reference', async ({ page }, testInfo) => {
  const calls: any[] = [];
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { projects: [] } }));
  await page.route('**/gw/api/v1/ablations/catalog', route => route.fulfill({ json: {
    workloads: [{ workload_id: 'tiny', label: 'Tiny trace', nodes: 8, events: 100, trace_sha256: 'abc' }],
    topologies: [{ topology_id: 'srota8x8', label: 'SROTA 8×8', family: 'SROTA' }, { topology_id: 'flatfly', label: 'Flatfly', family: 'FLATFLY' }, { topology_id: 'qtree', label: 'QTree', family: 'QTREE' }],
    defaults: { packet_size: 5, vc_buf_size: 4, use_noc_latency: 0, seed: 1 }, knob_dimensions: { vc_buf_size: { values: [4] } }, override_exclusions: [], max_overrides: 32,
    simulators: { booksim: true, booksim_power_audited: true },
  } }));
  await page.route('**/gw/api/v1/catalog/knob-inventory', route => route.fulfill({ json: { backend: { knobs: [] } } }));
  await page.route('**/gw/api/v1/ablations', async route => {
    const request = route.request().postDataJSON(); calls.push(request);
    await route.fulfill({ json: { schema: 'veritx/workload-ablation-run/1', out: 'test-run', duration_seconds: 1, returncode: 0, failed_cells: 0, document: { runs: [
      { workload: 'tiny', topology: 'srota8x8', status: 'ok', latency_p95: 10, throughput_packets_per_cycle: 5, native_power_w: 90, native_area_mm2: 3, total_energy_pj: 100, power_cycles: 10, log: 'srota.log', native_model: { status: 'AVAILABLE', model_id: 'test-v1', technology: 'test tech', clock_hz: 1e12, energy_definition: 'modeled power interval' }, resource_cost: { routers: 64, crosspoints: 4320, storage_flits: 15360 } },
      { workload: 'tiny', topology: 'flatfly', status: 'ok', latency_p95: 20, throughput_packets_per_cycle: 4, native_power_w: 30, native_area_mm2: 1, total_energy_pj: 30, power_cycles: 10, log: 'flatfly.log', native_model: { status: 'AVAILABLE', model_id: 'test-v1', technology: 'test tech', clock_hz: 1e12, energy_definition: 'modeled power interval' }, resource_cost: { routers: 16, crosspoints: 1600, storage_flits: 1280 } },
      { workload: 'tiny', topology: 'qtree', status: 'ok', latency_p95: 30, throughput_packets_per_cycle: 3, native_power_w: 20, native_area_mm2: .5, total_energy_pj: 20, power_cycles: 10, log: 'qtree.log', native_model: { status: 'AVAILABLE', model_id: 'test-v1', technology: 'test tech', clock_hz: 1e12, energy_definition: 'modeled power interval' }, resource_cost: { routers: 21, crosspoints: 516, storage_flits: 1664 } },
    ] } } });
  });
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/explore/fabric-search');
  await expect(page.getByRole('heading', { name: 'Reference Catalog' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recommended fabrics' })).toBeVisible();
  await page.getByRole('button', { name: 'Find fabrics' }).click();
  await expect(page.getByRole('status').filter({ hasText: '3 evaluations complete' })).toBeVisible();
  await expect(page.locator('.recommendation > strong')).toHaveText(['Flatfly', 'SROTA 8×8', 'QTree', 'QTree']);
  await page.screenshot({ path: testInfo.outputPath('fabric-search-top.png') });
  await page.locator('.fabric-selection').scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('fabric-search-selection.png') });
  await page.getByRole('heading', { name: 'Reference Catalog', exact: true }).scrollIntoViewIfNeeded();
  expect(calls).toHaveLength(1); expect(calls[0].workloads).toEqual(['tiny']); expect(calls[0].topologies).toEqual(['srota8x8', 'flatfly', 'qtree']); expect(calls[0].overrides).toEqual({ sim_power: '1' });
  await page.locator('details.fabric-refine > summary').click(); await page.getByLabel('Max modeled area').fill('0.75');
  await expect(page.locator('[data-profile="performance"] > strong')).toHaveText('QTree');
  expect(calls).toHaveLength(1);
  await page.getByRole('heading', { name: 'Recommended fabrics', exact: true }).scrollIntoViewIfNeeded();
  for (const width of [1440, 1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole('heading', { name: 'Recommended fabrics', exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `viewport should not overflow at ${width}px`).toBe(true);
    const columns = await page.locator('.recommendations').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length);
    expect(columns).toBe(width > 1100 ? 4 : width > 760 ? 2 : 1);
    await page.screenshot({ path: testInfo.outputPath(`explore-search-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('button[data-profile="performance"]').click();
  await page.getByRole('button', { name: 'Open in Design as reference' }).click();
  await expect(page).toHaveURL(/#\/design\/fabric-topology$/);
  const reference = page.locator('.handoff-reference');
  await expect(reference).toContainText('Explore reference:');
  await expect(reference).toContainText('Not applied to this project.');
  await expect(reference.getByRole('button', { name: 'Dismiss' })).toBeVisible();
  const layout = await page.evaluate(() => {
    const content = document.querySelector('.page-content') as HTMLElement;
    const main = document.querySelector('.page-content .view-main') as HTMLElement;
    return { pageOverflow: content.scrollHeight - content.clientHeight, mainBottom: main.getBoundingClientRect().bottom, viewport: innerHeight };
  });
  expect(layout.pageOverflow).toBeLessThanOrEqual(1);
  expect(layout.mainBottom).toBeLessThanOrEqual(layout.viewport);
  expect(errors).toEqual([]);
});
