import { expect, test } from '@playwright/test';

test('connected workspace keeps study constraints and exposes revision history', async ({ page }) => {
  const project = { project: { project_id: 'intent-test', name: 'Intent workspace', created_at: '', updated_at: '' }, active_revision_id: null, active_revision: null, revisions: [], runs: [] };
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { projects: [project] } }));
  await page.route('**/gw/api/v1/projects/intent-test', route => route.fulfill({ json: project }));
  await page.route('**/gw/api/v1/projects/intent-test/draft', route => route.fulfill({ json: { request: null, dirty: false } }));
  await page.route('**/gw/api/v1/optimization/capabilities', route => route.fulfill({ json: { guided_parameters: [{ name: 'topology_family', kind: 'enum', executable: true, qualified_for_certified_optimization: true, executable_values: ['mesh', 'torus'] }] } }));
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).first().click();

  // The workflow page owns project, draft and revision history.
  await page.goto('/#/workloads/workflow');
  await expect(page.getByRole('heading', { name: 'Workflow · Intent workspace', exact: true })).toBeVisible();
  await expect(page.getByText('Evaluation', { exact: true })).toBeVisible();
  await expect(page.getByText('No run yet.', { exact: true })).toBeVisible();

  // Study constraints live in Explore → Revision study, under the bounded study task.
  await page.goto('/#/explore/brief');
  await page.getByRole('button', { name: /Bounded study/ }).click();
  await page.getByRole('button', { name: '+ Add constraint', exact: true }).click();
  await page.getByLabel('Constraint 1 threshold').fill('100');

  // Switching tasks keeps the declared constraint instead of resetting it.
  await page.getByRole('button', { name: /^Recommendation/ }).click();
  await page.getByRole('button', { name: /Bounded study/ }).click();
  await expect(page.getByLabel('Constraint 1 threshold')).toHaveValue('100');
  await expect(page.getByRole('button', { name: 'Launch bounded study' })).toBeDisabled();

  await page.goto('/#/workloads/workflow');
  await expect(page.getByText('No run yet.', { exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/intent-workspace.png', fullPage: true });
});
