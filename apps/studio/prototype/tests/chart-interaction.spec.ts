import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('one workbench keeps mouse and keyboard inspection across presets and sources', async ({ page }, testInfo) => {
  const rows = JSON.parse(await readFile(new URL('../public/data/topology_sweep.json', import.meta.url), 'utf8'));
  await page.route('**/api/v1/analysis/topology-sweep', route => route.fulfill({ json: {
    source_path: 'recorded/native/topology_sweep.json', scope: 'repository sweep, not selected project or run', rows,
  } }));
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/explore/fabric-ablations');
  const section = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Repository sweep comparison', exact: true }) });
  await expect(section).toBeVisible();

  // The default preset is the all-loads curve. The arm picker is the legend.
  await expect(section.getByRole('button', { name: 'Latency vs load', exact: true })).toHaveAttribute('aria-pressed', 'true');
  const latencyPlot = section.getByRole('group', { name: /^Latency versus injection rate for each topology/ });
  await expect(latencyPlot).toBeVisible();
  const armPicker = section.getByRole('group', { name: 'Select an arm', exact: true });
  await armPicker.getByRole('button', { name: /^mesh4x4/ }).click();
  await expect(section.locator('.plot-readout strong')).toHaveText('mesh4x4');
  await expect(section.getByRole('complementary', { name: 'Observation inspector' }).getByRole('heading', { name: 'mesh4x4', exact: true })).toBeVisible();
  await expect(section.getByRole('group', { name: 'Focused arm', exact: true })).toContainText('mesh4x4');
  await section.getByRole('button', { name: 'Show all arms', exact: true }).click();
  await expect(section.getByRole('group', { name: 'Focused arm', exact: true })).toHaveCount(0);
  const latencyPoint = latencyPlot.getByRole('button', { name: 'Inspect mesh4x4', exact: true }).first();
  await latencyPoint.focus(); await latencyPoint.press('Enter');
  await expect(section.locator('.plot-readout strong')).toHaveText('mesh4x4');

  // The same canvas becomes the common-load trade-off.
  await section.getByRole('button', { name: 'Trade-off', exact: true }).click();
  const paretoPlot = section.getByRole('group', { name: /^Load-matched Pareto:/ });
  await expect(paretoPlot).toBeVisible();
  const inspector = section.getByRole('complementary', { name: 'Observation inspector' });
  await section.locator('.candidate-picker').getByRole('button', { name: /mesh4x4/ }).click();
  await expect(inspector.getByRole('heading', { name: 'mesh4x4', exact: true })).toBeVisible();
  await expect(inspector).toContainText('Dominated by');
  await paretoPlot.getByRole('button', { name: 'Inspect torus4x4', exact: true }).hover();
  await expect(section.locator('.plot-readout strong')).toHaveText('torus4x4');
  await expect(inspector.getByRole('heading', { name: 'mesh4x4', exact: true })).toBeVisible();
  await page.mouse.move(10, 10);
  await section.getByRole('button', { name: 'Include zero', exact: true }).click();
  await expect(section.getByRole('button', { name: 'Include zero', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await section.getByRole('button', { name: 'Fit data', exact: true }).click();
  await section.getByLabel('Front only', { exact: true }).check();
  await expect(paretoPlot.getByRole('button', { name: 'Inspect mesh4x4', exact: true })).toHaveCount(0);
  await expect(section.locator('.plot-hint')).toContainText('Actual observations, no interpolation');
  await section.getByLabel('Front only', { exact: true }).uncheck();

  // Path length is the same common-load view with different axes.
  await section.getByRole('button', { name: 'Path length', exact: true }).click();
  await expect(section.getByLabel('Horizontal objective')).toHaveValue('hops_avg');
  await expect(section.getByLabel('Vertical objective')).toHaveValue('latency_cycles');

  // Operating points are the last-stable observation per arm, still in the same frame.
  await section.getByRole('button', { name: 'Operating point', exact: true }).click();
  const operatingPlot = section.getByRole('group', { name: /^Operating point: accepted throughput versus latency/ });
  await expect(operatingPlot).toBeVisible();
  await section.locator('.candidate-picker').getByRole('button', { name: /flatfly16/ }).click();
  await expect(section.locator('.plot-readout')).toContainText('flatfly16');
  await section.getByRole('button', { name: 'Latency vs load', exact: true }).click();
  await expect(section.getByLabel('Log Y axis', { exact: true })).toBeChecked();
  await latencyPlot.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('interactive-latency-1440.png') });

  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole('heading', { name: 'Repository sweep comparison', exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`interactive-analysis-${width}.png`) });
  }
  expect(errors).toEqual([]);
});
