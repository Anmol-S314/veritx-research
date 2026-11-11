import { expect, test } from '@playwright/test';

// Opt in explicitly: creates and deletes only its own disposable project.
test('system composition and connection incidence are drawn from live structure', async ({ page, request }) => {
  test.skip(process.env.VERITX_LIVE_TEST !== '1', 'Set VERITX_LIVE_TEST=1 to run real backends.');
  test.setTimeout(120000);
  page.setDefaultTimeout(15000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const api = '/gw/api/v1';
  const name = `prototype-viz-${Date.now()}`;
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
    await page.evaluate(() => { location.hash = '/design/system'; });

    await expect(page.getByRole('heading', { name: 'System composition', exact: true })).toBeVisible();
    await expect(page.locator('.system-composition')).toBeVisible();
    await expect(page.locator('.system-composition').getByText('Compute tiles', { exact: true })).toBeVisible();
    await expect(page.locator('.system-composition').getByText('32 attached', { exact: true })).toBeVisible();
    await expect(page.locator('.system-composition').getByText('16 routers · 32 endpoint seats', { exact: true })).toBeVisible();
    await expect(page.getByText('not a floorplan or a packet path', { exact: false })).toBeVisible();

    await page.evaluate(() => { location.hash = '/design/mapping'; });
    await expect(page.getByRole('heading', { name: 'Connection incidence matrix', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'MECS taps 48', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: 'Channels 0', exact: true })).toBeDisabled();
    await expect(page.locator('.incidence-cell')).toHaveCount(256);
    await expect(page.locator('.incidence-caption')).toContainText('not point-to-point channels');
    await expect(page.getByText('No directed channels are declared.', { exact: false })).toBeVisible();
    await expect(page.getByText('no declared rule', { exact: true })).toBeVisible();

    expect(errors).toEqual([]);
  } finally {
    if (id) {
      const cleanup = await request.delete(`${api}/projects/${id}`);
      expect(cleanup.ok(), await cleanup.text()).toBe(true);
    }
  }
});
