import { expect, test } from '@playwright/test';

// Opt in explicitly: creates and deletes only its own disposable project.
test('fabric-wide router control saves, recompiles, and re-proves', async ({ page, request }) => {
  test.skip(process.env.VERITX_LIVE_TEST !== '1', 'Set VERITX_LIVE_TEST=1 to run real backends.');
  test.setTimeout(120000);
  page.setDefaultTimeout(15000);
  const api = '/gw/api/v1';
  const name = `prototype-router-${Date.now()}`;
  let id: string | undefined;
  try {
    const created = await request.post(`${api}/projects/from-preset`, { data: { preset_id: 'srota32', name } });
    expect(created.ok(), await created.text()).toBe(true);
    id = (await created.json()).project.project_id;
    const compiled = await request.post(`${api}/projects/${id}/compile`, { data: {}, timeout: 60000 });
    expect(compiled.ok(), await compiled.text()).toBe(true);
    const result = await compiled.json();
    expect(result.compilation?.status, JSON.stringify(result.compilation)).toBe('COMPILED');

    await page.goto('/#/shared/projects');
    await page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: 'Load', exact: true }).click();
    await page.evaluate(() => { location.hash = '/design/fabric-topology'; });
    await page.getByRole('button', { name: 'Select router 0', exact: true }).click();
    await page.getByRole('button', { name: 'Inspector', exact: true }).click();

    await expect(page.getByText('One router configuration for the fabric.', { exact: false })).toBeVisible();
    await expect(page.getByText('Derived router configuration', { exact: true })).toBeVisible();
    await expect(page.getByText('Deadlock proof', { exact: true })).toBeVisible();
    await expect(page.getByText('PASS', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('8 flits / VC', { exact: true }).first()).toBeVisible();

    await page.getByRole('button', { name: 'Review buffer-depth change', exact: true }).click();
    await page.getByRole('spinbutton', { name: /Input buffer depth/ }).fill('16');
    await page.getByRole('button', { name: 'Apply and recompile', exact: true }).click();
    await expect(page.getByText('Buffer depth set to 16 flits per VC and the revision was recompiled.', { exact: false })).toBeVisible({ timeout: 90000 });
    await expect(page.locator('.header-revision')).toContainText('-r02', { timeout: 30000 });

    await page.getByRole('button', { name: 'Select router 0', exact: true }).click();
    await page.getByRole('button', { name: 'Inspector', exact: true }).click();
    await expect(page.getByText('16 flits / VC', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Deadlock proof', { exact: true })).toBeVisible();
  } finally {
    if (id) {
      const cleanup = await request.delete(`${api}/projects/${id}`);
      expect(cleanup.ok(), await cleanup.text()).toBe(true);
    }
  }
});
