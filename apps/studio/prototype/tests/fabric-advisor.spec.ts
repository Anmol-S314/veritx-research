import { expect, test } from '@playwright/test';

test('fabric advisor turns measured workload evidence into a constrained recommendation', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/#/explore/brief');
  await expect(page.getByRole('heading', { name: 'Revision Study (Advanced)', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recommendation inputs', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recommendation', exact: true })).toBeVisible();
  await expect(page.locator('.advisor-pick')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Candidate field', exact: true })).toBeVisible();
  await page.locator('.advisor-disclosure > summary').click();
  await expect(page.getByRole('heading', { name: 'Buffer and width guidance', exact: true })).toBeVisible();

  const workload = page.getByRole('combobox', { name: 'Measured workload' });
  await workload.selectOption('moe');
  await expect(workload).toHaveValue('moe');

  const priority = page.getByRole('combobox', { name: /Recommendation priority/ });
  await priority.selectOption('power');
  await expect(priority).toHaveValue('power');
  await expect(page.locator('.advisor-pick')).toBeVisible();

  await page.locator('.advisor-constraints > summary').click();
  const power = page.getByLabel('Maximum modeled power in W');
  await power.fill('1');
  await expect(page.getByRole('heading', { name: 'No candidate satisfies every hard constraint.', exact: true })).toBeVisible();
  await power.fill('');
  await expect(page.locator('.advisor-pick')).toBeVisible();
});

test('live advisor filters to executable families and pre-fills the bounded study', async ({ page, request }) => {
  test.skip(process.env.VERITX_LIVE_TEST !== '1', 'Set VERITX_LIVE_TEST=1 to exercise the live project context.');
  const projects = await (await request.get('/gw/api/v1/projects')).json();
  const project = projects.projects.find((row: any) => /Mixtral/i.test(row.project.name)) ?? projects.projects.find((row: any) => row.active_revision_id);
  expect(project).toBeTruthy();
  await page.goto('/#/explore/brief');
  await page.evaluate(projectId => sessionStorage.setItem('srota-gateway-selection:v1', JSON.stringify({ projectId })), project.project.project_id);
  await page.reload();
  await expect(page.getByText('Executable filter active', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(project.project.name, { exact: false }).first()).toBeVisible();

  const carry = page.getByRole('button', { name: 'Carry shortlist into measured study', exact: true });
  await expect(carry).toBeEnabled();
  await carry.click();
  await expect(page.getByLabel('Study parameter (validated per candidate)')).toHaveValue('topology_family');
  await expect(page.getByRole('group', { name: 'Values to test' }).getByRole('checkbox', { name: /mesh/i }).first()).toBeChecked();
  await expect(page.getByText('Advisor shortlist loaded', { exact: false })).toBeVisible();
});

test('advisor download carries provenance and does not claim a width optimum', async ({ page }) => {
  await page.goto('/#/explore/brief');
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download recommendation JSON', exact: true }).first().click();
  const download = await downloading;
  const text = await (await import('node:fs/promises')).readFile((await download.path())!, 'utf8');
  const brief = JSON.parse(text);
  expect(brief.schema).toBe('srota/fabric-recommendation/1');
  expect(brief.limits.join(' ')).toContain('width');
  expect(brief.candidates.length).toBeGreaterThan(0);
  expect(brief.recommendation.topology_label).toBeTruthy();
});
