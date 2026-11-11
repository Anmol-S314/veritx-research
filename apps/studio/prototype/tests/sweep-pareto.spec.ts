import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const rows = [0.01, 0.1].flatMap(injection_rate => [
  { topology: 'mesh-test', injection_rate, latency_cycles: 20, hops_avg: 3, accepted_rate: injection_rate * 0.9, crosspoints: 400, storage_flits: 512, routers: 16, status: 'ok', traffic: 'uniform', endpoints: 16, routing: 'dor', qualification: 'QUALIFIED', log: 'logs/mesh.log' },
  { topology: 'express-test', injection_rate, latency_cycles: 30, hops_avg: 2, accepted_rate: injection_rate * 0.95, crosspoints: 800, storage_flits: 1024, routers: 16, status: 'ok', traffic: 'uniform', endpoints: 16, routing: 'min', qualification: 'PARTIAL', log: 'logs/express.log' },
]);
const evidence = { source_path: 'tracks/t3-topology/runs/supported-sweep/browser/topology_sweep.json', scope: 'repository sweep, not selected project or run', sha256: 'test-digest', rows };

test('one workbench drives constraints, objectives, export and refresh', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let requests = 0;
  await page.route('**/api/v1/analysis/topology-sweep', route => {
    requests++;
    return route.fulfill({ json: evidence });
  });
  await page.goto('/#/explore/fabric-ablations');
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Repository sweep comparison', exact: true }) });
  await expect(section.getByRole('button', { name: 'Latency vs load', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await section.getByRole('button', { name: 'Trade-off', exact: true }).click();
  await expect(section.getByText('2 non-dominated / 2 eligible', { exact: true })).toBeVisible();
  await page.locator('summary').filter({ hasText: 'Refine comparison' }).click();
  await expect(page.getByLabel('Include BookSim native estimates (research only)')).toBeDisabled();
  await expect(page.getByLabel('Horizontal objective').locator('option[value="native_area_mm2"]')).toHaveAttribute('disabled', '');
  await expect(page.getByLabel('Horizontal objective').locator('option[value="native_energy_pj_per_cycle"]')).toHaveAttribute('disabled', '');
  await page.getByLabel('Offered load (packets/node/cycle)').selectOption('0.1');
  await page.getByLabel('Maximum crosspoints', { exact: true }).fill('500');
  await expect(section.getByText('1 non-dominated / 1 eligible', { exact: true })).toBeVisible();
  await section.locator('summary').filter({ hasText: 'Candidate data' }).click();
  await expect(section.getByRole('row').filter({ hasText: 'express-test' })).toContainText('Crossbar cost above 500');
  await page.getByLabel('Vertical objective').selectOption('accepted_rate');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export comparison', exact: true }).click();
  const download = await downloadPromise;
  const exported = JSON.parse(await readFile((await download.path())!, 'utf8'));
  expect(exported.sha256).toBe('test-digest');
  expect(exported.injection_rate).toBe(0.1);
  expect(exported.objectives[1]).toMatchObject({ metric: 'accepted_rate', direction: 'MAX' });
  expect(exported.candidates.filter((candidate: { front: boolean }) => candidate.front).map((candidate: { topology: string }) => candidate.topology)).toEqual(['mesh-test']);
  await page.getByLabel('Maximum latency (cycles)').fill('1');
  await expect(section.getByText(/No eligible observations/)).toBeVisible();
  await page.getByRole('button', { name: 'Clear constraints', exact: true }).click();
  await expect(section.getByText('2 non-dominated / 2 eligible', { exact: true })).toBeVisible();
  const beforeRefresh = requests;
  await page.getByRole('button', { name: 'Refresh sweep evidence', exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThan(beforeRefresh);
  await expect(section.getByRole('group', { name: /^Load-matched Pareto:/ })).toBeVisible();
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await section.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`sweep-pareto-${width}.png`) });
  }
  expect(errors).toEqual([]);
});

test('gateway absence is labelled and malformed bundled evidence cannot crash the page', async ({ page }) => {
  await page.route('**/api/v1/analysis/topology-sweep', route => route.fulfill({ status: 404, json: { error: { message: 'No sweep' } } }));
  await page.goto('/#/explore/fabric-ablations');
  await expect(page.getByText('Gateway sweep unavailable; showing the bundled snapshot.', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Repository sweep comparison', exact: true })).toBeVisible();
  await page.route('**/data/topology_sweep.json', route => route.fulfill({ json: [null] }));
  await page.getByRole('button', { name: 'Refresh sweep evidence', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Sweep evidence unreadable');
  await expect(page.getByRole('group', { name: /^Latency versus injection rate/ })).toHaveCount(0);
});
