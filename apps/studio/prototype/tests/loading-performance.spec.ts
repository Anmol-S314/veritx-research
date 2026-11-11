import { expect, test } from '@playwright/test';

test('reading a saved run does not build an unused evaluation plan', async ({ page }) => {
  const projectId = 'p-loading', revisionId = 'p-loading-r01', runId = 'run-loading';
  const project = {
    project: { project_id: projectId, name: 'Loading regression' },
    active_revision_id: revisionId, active_revision: { revision_id: revisionId },
    revisions: [], runs: [{ run_id: runId, revision_id: revisionId, backend: 'BOOKSIM_STANDALONE', status: 'EVALUATED', bundle_id: 'bundle', requirements_pass: true }],
  };
  let plans = 0;
  await page.addInitScript(id => localStorage.setItem('srota-gateway-selection:v1', JSON.stringify({ projectId: id })), projectId);
  await page.route('**/gw/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/gw/api/v1', '');
    const ok = (json: unknown) => route.fulfill({ json });
    if (path === '/health') return ok({ status: 'ok', backends: {} });
    if (path === '/projects') return ok({ projects: [project] });
    if (path === `/projects/${projectId}`) return ok(project);
    if (path.endsWith('/draft')) return ok({ request: {}, design_hash: 'draft' });
    if (path.endsWith('/jobs')) return ok({ jobs: [] });
    if (path.endsWith('/topology')) return ok({ family: 'mesh', counts: {}, routers: [], channels: [], endpoints: [] });
    if (path.endsWith('/compile-result')) return ok({ available: true, groups: {} });
    if (path === `/runs/${runId}`) return ok({ ...project.runs[0], project_id: projectId, evaluation: { metrics: { completion_cycles: 123 } } });
    if (path.endsWith('/traffic-matrix')) return ok({ availability: 'NOT_AVAILABLE' });
    if (path.endsWith('/integrity')) return ok({ run_id: runId });
    if (path.endsWith('/artifacts')) return ok({ run_id: runId, bundle: { files: {} } });
    if (path.endsWith('/evaluation-plan')) {
      plans += 1;
      return ok({ revision_id: revisionId, analyses: [{ question: 'NETWORK_COMPLETION', backend: 'BOOKSIM_STANDALONE', readiness: 'READY' }] });
    }
    return route.fulfill({ status: 404, json: { detail: path } });
  });
  await page.goto('/#/analysis/summary');
  await expect(page.locator('.stat-strip')).toContainText('123');
  await page.waitForLoadState('networkidle');
  expect(plans).toBe(0);
  const panel = page.locator('#launch-evaluation');
  await expect(panel).not.toHaveAttribute('open', '');
  await page.getByRole('button', { name: 'Run new evaluation', exact: true }).click();
  await expect(panel.getByLabel('Select NETWORK_COMPLETION')).toBeVisible();
  expect(plans).toBe(1);
  await panel.locator('summary').first().click();
  await panel.locator('summary').first().click();
  await expect(panel.getByLabel('Select NETWORK_COMPLETION')).toBeVisible();
  expect(plans).toBe(1);
});
