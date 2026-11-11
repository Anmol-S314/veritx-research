import { expect, test } from '@playwright/test';

test('Analysis inspects the recorded GR00T architecture bundle without launching a run', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/analysis/gr00t');
  await expect(page.getByRole('heading', { name: 'GR00T Architecture Trace' })).toBeVisible();
  await expect(page.getByText('Recorded run · read only')).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim')).toBeVisible();
  await expect(page.getByText('nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace')).toBeVisible();
  await expect(page.getByText('12,116', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('1,222', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('1,423', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('201', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('10,693', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('node_MatMul_916').first()).toBeVisible();
  await expect(page.getByText('mesh-2x2')).toBeVisible();
  await expect(page.getByText('mesh-4x1')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Topology sweep · same ROI trace' })).toBeVisible();
  await expect(page.getByText('gec_express_k8')).toBeVisible();
  await expect(page.getByText('flatfly_64')).toBeVisible();
  await expect(page.getByText('Rank within size')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'SROTA 8×8 · matched mesh control' })).toBeVisible();
  await expect(page.getByText('srota_8x8')).toBeVisible();
  await expect(page.getByText('The ROI trace contains only adjacent 0→1 and 1→2 traffic, so it does not exercise SROTA\'s long-distance express paths.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Tensor movement coverage' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Timeloop · compute mapping' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'BookSim · tensor communication' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Variant comparison' })).toBeVisible();
  const canvas = page.locator('canvas');
  await expect(canvas).toBeVisible();
  const pixel = await canvas.evaluate((c: HTMLCanvasElement) => [...c.getContext('2d')!.getImageData(100, 100, 1, 1).data]);
  expect(pixel).not.toEqual([0, 0, 0, 0]);
  await page.screenshot({ path: '/tmp/gr00t-studio-1440.png', fullPage: true });

  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(page.locator('.gr00t-backends')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
  await page.screenshot({ path: '/tmp/gr00t-studio-1280.png', fullPage: true });

  const before = await page.getByText('Recorded run · read only').count();
  await page.getByLabel('Import recorded bundle').setInputFiles([
    { name: 'comparison.json', mimeType: 'application/json', buffer: Buffer.from('{"schema":"broken"}') },
    { name: 'manifest.json', mimeType: 'application/json', buffer: Buffer.from('{}') },
    { name: 'observation.rgb24', mimeType: 'application/octet-stream', buffer: Buffer.alloc(640 * 480 * 3) },
  ]);
  await expect(page.getByText('Unsupported GR00T observation schema or qualification.')).toBeVisible();
  expect(await page.getByText('Recorded run · read only').count()).toBe(before);
  await page.getByLabel('Import recorded bundle').setInputFiles([
    '../../../runs/gr00t-model/staticpick-v1-observation/comparison.json',
    '../../../runs/gr00t-model/staticpick-v1-observation/manifest.json',
    '../../../runs/gr00t-model/staticpick-v1-observation/observation.rgb24',
  ]);
  await expect(page.getByText('Imported bundle')).toBeVisible();
  await expect(page.getByText('0 tracked evaluations')).toBeVisible();
});
