import { expect, test } from '@playwright/test';


test('the uniform fabric sweep and the measured workload explorer stay separate pages', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/explore/fabric-ablations');
  await expect(page.getByRole('heading', { name: 'Repository sweep comparison', exact: true })).toBeVisible();
  // One job per page: the measured workload replay is not a second tab here.
  await expect(page.getByRole('group', { name: 'Evidence source' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Refresh sweep evidence', exact: true })).toBeVisible();

  await page.goto('/#/explore/ablations');
  const workload = page.locator('.abl-controls').getByLabel('Workload');
  await expect(workload.locator('option')).toHaveCount(11);
  await workload.selectOption('llm_transformer');
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: /^Best candidate for/ }) });
  await expect(section).toBeVisible();
  await expect(section).toContainText('8×8 torus');
  await expect(page.getByRole('table', { name: 'Workload × topology matrix' }).or(page.locator('.abl-matrix'))).toBeVisible();

  await workload.selectOption('mwa-fx-correlator');
  await expect(page.getByRole('heading', { name: /^Best candidate for/ })).toContainText('MWA');
  await expect(page.locator('.curve-chip')).toHaveCount(12);

  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.locator('.view-main').first().evaluate(element => element.scrollTo(0, 0));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`workload-explorer-${width}.png`) });
  }
  expect(errors).toEqual([]);
});

test('workload ablation evidence is labelled unavailable rather than substituted', async ({ page }) => {
  await page.route('**/data/workload_ablation.json', route => route.fulfill({ status: 500, body: 'nope' }));
  await page.goto('/#/explore/ablations');
  await expect(page.getByText(/Workload ablation file unreadable/)).toBeVisible();
  await expect(page.getByRole('heading', { name: /^Best candidate for/ })).toHaveCount(0);
});
