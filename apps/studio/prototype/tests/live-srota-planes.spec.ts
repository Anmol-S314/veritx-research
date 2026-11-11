import { expect, test } from '@playwright/test';

// Opt in explicitly: creates and deletes only its own disposable project.
test('SROTA D+C+T planes render their own declared structure', async ({ page, request }) => {
  test.skip(process.env.VERITX_LIVE_TEST !== '1', 'Set VERITX_LIVE_TEST=1 to run real backends.');
  test.setTimeout(120000);
  page.setDefaultTimeout(15000);
  const api = '/gw/api/v1';
  const name = `prototype-planes-${Date.now()}`;
  let id: string | undefined;
  try {
    const created = await request.post(`${api}/projects/from-preset`, { data: { preset_id: 'srota32_plane_c', name } });
    expect(created.ok(), await created.text()).toBe(true);
    id = (await created.json()).project.project_id;
    const compiled = await request.post(`${api}/projects/${id}/compile`, { data: {}, timeout: 60000 });
    expect(compiled.ok(), await compiled.text()).toBe(true);
    expect((await compiled.json()).compilation?.status).toBe('COMPILED');

    await page.goto('/#/shared/projects');
    await page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: 'Load', exact: true }).click();
    await page.evaluate(() => { location.hash = '/design/fabric-topology'; });

    await expect(page.getByRole('group', { name: 'Packet plane' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Data (D)' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Control (C)' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Telemetry (T)' })).toBeVisible();

    await page.getByRole('button', { name: 'Data (D)' }).click();
    await expect(page.locator('.gateway-shared-links polyline')).toHaveCount(48);
    await expect(page.locator('.gateway-links line')).toHaveCount(0);
    await expect(page.getByText('48 shared wires', { exact: false }).first()).toBeVisible();

    // The wire list lives in the canvas tree. Choosing W0 there isolates and
    // labels that exact multidrop wire without inventing point-to-point links.
    await page.getByRole('button', { name: 'Wires 48', exact: true }).click();
    await expect(page.locator('.tree-wire')).toHaveCount(48);
    await page.locator('.tree-wire').first().click();
    await expect(page.locator('.shared-wire.selected')).toHaveCount(1);
    await expect(page.locator('.shared-wire-label')).toHaveText('W0');
    await expect(page.locator('.gateway-shared-links')).toHaveAttribute('data-dim', 'true');
    await expect(page.locator('.fabric-wire-strip')).toContainText('R0 → R1 · R2 · R3');
    await expect(page.locator('tr.selected').filter({ hasText: 'W0' })).toHaveCount(1);
    await page.getByRole('button', { name: 'Clear wire', exact: true }).click();
    await expect(page.locator('.shared-wire.selected')).toHaveCount(0);

    // Parallelism comes from the compiler's rank -> endpoint mapping. TP is the
    // declared axis for this preset; all 32 ranks must paint on the 16 routers.
    const parallel = page.getByLabel('Parallelism overlay');
    await expect(parallel).toBeEnabled();
    await parallel.selectOption('tp');
    await expect(page.locator('.parallel-satellite')).toHaveCount(32);
    await expect(page.getByRole('heading', { name: 'Parallelism mapping', exact: true })).toBeVisible();
    await expect(page.getByRole('rowheader', { name: 'TP 0', exact: true })).toHaveCount(1);
    await expect(page.getByRole('rowheader', { name: 'TP 31', exact: true })).toHaveCount(1);

    await page.getByRole('button', { name: 'Control (C)' }).click();
    await expect(page.locator('svg.gateway-control-plane')).toBeVisible();
    await expect(page.getByText('Plane C · declared subnet', { exact: true })).toBeVisible();
    await expect(page.getByText('REQ / RSP / SNP', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Declared structure only; Plane C is not simulated in this view', { exact: false })).toBeVisible();

    await page.getByRole('button', { name: 'Telemetry (T)' }).click();
    await expect(page.getByText('Plane T · telemetry', { exact: true })).toBeVisible();
    await expect(page.getByText('Period 4 cycles', { exact: false }).first()).toBeVisible();
    await expect(page.locator('.gateway-telemetry-ring')).toHaveCount(16);
  } finally {
    if (id) {
      const cleanup = await request.delete(`${api}/projects/${id}`);
      expect(cleanup.ok(), await cleanup.text()).toBe(true);
    }
  }
});
