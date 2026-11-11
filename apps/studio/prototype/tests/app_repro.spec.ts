import { test, expect } from '@playwright/test';

// Reproduces the two packaged-build failures a user hits in the desktop app:
//   1. "Workload ablation evidence is unavailable: The string did not match the
//      expected pattern."  -> AblationWorkbench fetched /public/data/...
//   2. "Find fabrics" disabled forever -> catalog carried no vc_buf_size depths
//      because public/data/design_sensitivity.json was not shipped.
// Green here, against the built dist and the packaged gateway, means the
// packaged surface offers both features.

test('fabric search offers buffers and runs a search', async ({ page }) => {
  const bad: string[] = [];
  page.on('response', r => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url()}`); });
  await page.goto('/#/explore/fabric-search', { waitUntil: 'load' });
  await page.waitForTimeout(4000);
  const chips = page.locator('.fabric-chip');
  const chipCount = await chips.count();
  const btn = page.getByRole('button', { name: /Find fabrics|Searching/ });
  const helper = await page.locator('.fabric-search-action small').innerText().catch(() => '');
  console.log(`chips=${chipCount} buttonDisabled=${await btn.isDisabled()} helper="${helper.replace(/\s+/g, ' ')}"`);
  expect(chipCount).toBeGreaterThan(0);
  expect(await btn.isDisabled()).toBe(false);
  expect(bad).toEqual([]);
});

test('ablation evidence parses instead of returning index.html', async ({ page }) => {
  const bad: string[] = [];
  page.on('response', r => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url()}`); });
  await page.goto('/#/explore/ablations', { waitUntil: 'load' });
  await page.waitForTimeout(2000);
  const text = (await page.locator('main').innerText()).replace(/\s+/g, ' ');
  console.log(`ablation page: ${text.slice(0, 180)}`);
  expect(text).not.toMatch(/did not match the expected pattern|is not valid JSON/i);
  expect(text).toMatch(/Best candidate for/);
  expect(bad).toEqual([]);
});

test('Find fabrics actually runs a measured search', async ({ page }) => {
  const bad: string[] = [];
  page.on('response', r => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url().slice(0, 60)}`); });
  await page.goto('/#/explore/fabric-search', { waitUntil: 'load' });
  await page.waitForTimeout(3500);
  const btn = page.getByRole('button', { name: /Find fabrics/ });
  await expect(btn).toBeEnabled();
  await btn.click();
  // The search is a gateway job; poll the view for a result table or an error.
  const deadline = Date.now() + 240000;
  let state = 'pending';
  while (Date.now() < deadline) {
    const text = (await page.locator('main').innerText()).replace(/\s+/g, ' ');
    if (/runner produced no ablation|is not valid JSON|did not match the expected pattern|Gateway refused/i.test(text)) { state = `ERROR: ${text.slice(0, 200)}`; break; }
    if (/Evaluations|P95 cycles|measured configurations/i.test(text) && !/Searching/i.test(text)) { state = 'RESULTS'; break; }
    await page.waitForTimeout(3000);
  }
  console.log(`find-fabrics state: ${state}`);
  expect(state).toBe('RESULTS');
  expect(bad).toEqual([]);
});
