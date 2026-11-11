import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

test('recorded BookSim native sweep supports modeled area/energy objectives and budgets', async ({ page }, testInfo) => {
  const raw = await readFile(new URL('../public/data/topology_sweep.json', import.meta.url), 'utf8');
  const rows = JSON.parse(raw);
  expect(rows.filter((row: { native_model?: { status: string } }) => row.native_model?.status === 'AVAILABLE').length).toBeGreaterThan(0);
  const evidence = {
    source_path: 'tracks/t3-topology/runs/supported-sweep/20261026-native-power/topology_sweep.json',
    scope: 'repository sweep, not selected project or run', sha256: createHash('sha256').update(raw).digest('hex'), rows,
  };
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/analysis/topology-sweep', route => route.fulfill({ json: evidence }));
  await page.goto('/#/explore/fabric-ablations');
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Repository sweep comparison', exact: true }) });
  await section.getByRole('button', { name: 'Trade-off', exact: true }).click();
  await page.locator('summary').filter({ hasText: 'Refine comparison' }).click();
  await page.getByLabel('Include BookSim native estimates (research only)').check();
  await expect(page.getByText('Research estimates · 2007 ITRS 32nm model', { exact: false })).toBeVisible();
  await page.getByLabel('Horizontal objective').selectOption('native_area_mm2');
  await page.getByLabel('Vertical objective').selectOption('native_energy_pj_per_cycle');
  await expect(section.getByText('1 non-dominated / 7 eligible', { exact: true })).toBeVisible();
  await section.locator('summary').filter({ hasText: 'Candidate data' }).click();
  const table = page.getByRole('table', { name: 'Load-matched sweep candidates', exact: true });
  await expect(table.getByRole('row').filter({ hasText: 'gec_mecs16' })).toContainText('Not plotted');
  await expect(table.getByRole('row').filter({ hasText: 'mesh4x4' })).toContainText('0.281');
  await page.getByLabel('Maximum native modeled area (mm²)', { exact: true }).fill('0.2');
  await expect(section.getByText('1 non-dominated / 1 eligible', { exact: true })).toBeVisible();
  await page.getByLabel('Maximum native modeled energy (pJ/cycle)', { exact: true }).fill('1');
  await expect(section.getByText(/No eligible observations/)).toBeVisible();
  await page.getByRole('button', { name: 'Clear constraints', exact: true }).click();
  await page.getByLabel('Optimize Accepted throughput (packets/node/cycle)', { exact: true }).check();
  await expect(section.getByText(/2D projection of this multi-objective front/)).toBeVisible();
  const promise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export comparison', exact: true }).click();
  const download = await promise;
  const exported = JSON.parse(await readFile((await download.path())!, 'utf8'));
  expect(exported.include_native_estimates).toBe(true);
  expect(exported.objectives).toHaveLength(3);
  expect(exported.candidates.find((candidate: { topology: string }) => candidate.topology === 'mesh4x4').row.native_model).toMatchObject({ status: 'AVAILABLE', fidelity: 'BOOKSIM_NATIVE_MODEL' });
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await section.getByRole('group', { name: /^Load-matched Pareto:/ }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`native-sweep-${width}.png`) });
  }
  await page.getByLabel('Include BookSim native estimates (research only)').uncheck();
  await expect(page.getByLabel('Horizontal objective')).toHaveValue('latency_cycles');
  await expect(page.getByLabel('Vertical objective')).toHaveValue('hops_avg');
  await expect(page.getByLabel('Maximum native modeled area (mm²)', { exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});
