import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

// Opt in explicitly: creates and deletes only its own disposable project.
test('design pages read real preflight, UVM collateral and compiler routes', async ({ page, request }) => {
  test.skip(process.env.VERITX_LIVE_TEST !== '1', 'Set VERITX_LIVE_TEST=1 to run real backends.');
  test.setTimeout(120000);
  page.setDefaultTimeout(15000);

  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));

  const api = '/gw/api/v1';
  const name = `design-backend-${Date.now()}`;
  let id: string | undefined;
  try {
    const created = await request.post(`${api}/projects/from-preset`, { data: { preset_id: 'mesh4', name } });
    expect(created.ok(), await created.text()).toBe(true);
    id = (await created.json()).project.project_id;

    const draft = await (await request.get(`${api}/projects/${id}/draft`)).json();
    const compiled = await request.post(`${api}/projects/${id}/compile`, {
      data: { expected_draft_design_hash: draft.design_hash }, timeout: 60000,
    });
    expect(compiled.ok(), await compiled.text()).toBe(true);
    expect((await compiled.json()).compilation?.status).toBe('COMPILED');

    await page.goto('/#/shared/projects');
    await page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: 'Load', exact: true }).click();
    await expect(page.locator('.header-revision')).toContainText('-r');

    // design/flow: the cross-page flow and its stated consequences.
    await page.evaluate(() => { location.hash = '/design/flow'; });
    await expect(page.getByRole('heading', { name: 'Design Workflow', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Consequences of the current state', exact: true })).toBeVisible();
    await expect(page.getByText('No unsaved design edits.', { exact: true })).toBeVisible();
    await expect(page.getByRole('row').filter({ hasText: 'Derived facts' })).toContainText('active revision');
    await expect(page.getByRole('row').filter({ hasText: 'Measurements' })).toContainText('No evaluation has measured this design.');
    await expect(page.getByRole('row').filter({ hasText: 'Clock & power domains' })).toContainText('Saves and compiles a new revision');

    // design/system: the backend's preflight gates, then real UVM collateral.
    await page.evaluate(() => { location.hash = '/design/system'; });
    await expect(page.getByRole('heading', { name: 'Backend collateral', exact: true })).toBeVisible();
    const preflightRow = page.getByRole('row').filter({ hasText: 'compilation' });
    await expect(preflightRow).toContainText('READY');
    await expect(page.getByText('Chipyard source ·', { exact: false })).toBeVisible();

    await page.getByRole('button', { name: 'Generate UVM collateral', exact: true }).click();
    await expect(page.getByText('UVM generated', { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByText('mesh · 4 nodes · k=2 · 2 VC(s)', { exact: true })).toBeVisible();
    const fileRow = page.getByRole('row').filter({ hasText: 'noc_dut_binding.sv' });
    await expect(fileRow).toContainText('noc_dut_binding.sv');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      fileRow.getByRole('button', { name: 'Download', exact: true }).click(),
    ]);
    expect(download.suggestedFilename()).toBe('noc_dut_binding.sv');
    const path = await download.path();
    expect(path).toBeTruthy();
    expect(await readFile(path!, 'utf8')).toContain('module noc_dut_binding');

    // design/mapping: the route is walked out of the frozen compile result.
    await page.evaluate(() => { location.hash = '/design/mapping'; });
    await expect(page.getByRole('heading', { name: 'Compiler-derived route', exact: true })).toBeVisible();
    await expect(page.getByText('DOR_XY · 2 hops', { exact: true })).toBeVisible();
    await expect(page.getByText('R0 → R1 → R3', { exact: true })).toBeVisible();
    await expect(page.getByText('Yes · LOCAL_EJECTION', { exact: true })).toBeVisible();
    await expect(page.getByRole('row').filter({ hasText: 'R0 · p1' })).toContainText('R1 · p1');

    // design/domains: clock intent is a real draft write plus compile.
    await page.evaluate(() => { location.hash = '/design/domains'; });
    await expect(page.getByRole('heading', { name: 'Declared clock domains', exact: true })).toBeVisible();
    await page.getByLabel('Clock domain for compute_tile 1', { exact: true }).fill('clk_core');
    await page.getByRole('button', { name: 'Save & compile clock intent', exact: true }).click();
    await expect(page.locator('.header-revision')).toContainText('-r02', { timeout: 30000 });

    expect(errors).toEqual([]);
  } finally {
    if (id) {
      const cleanup = await request.delete(`${api}/projects/${id}`);
      expect(cleanup.ok(), await cleanup.text()).toBe(true);
    }
  }
});
