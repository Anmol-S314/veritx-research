import { expect, test } from '@playwright/test';

/** The Jobs page now reads the gateway's own job records. It must not present
 *  a client timer, a fabricated live count, or a success for a failed job. */
test('jobs page reads gateway job records and surfaces failures', async ({ page }) => {
  const projectId = 'p-jobs', revisionId = 'p-jobs-r01';
  const project = {
    project: { project_id: projectId, name: 'Jobs project', created_at: '2026-11-12T00:00:00+00:00', updated_at: '2026-11-12T00:00:00+00:00' },
    active_revision_id: revisionId,
    active_revision: { revision_id: revisionId, display_name: 'r01' },
    revisions: [{ revision_id: revisionId, display_name: 'r01' }],
    runs: [],
  };
  const jobs = [
    { contract_version: 1, job_id: 'job-alpha', project_id: projectId, kind: 'CATALOG_EVALUATION', revision_id: null, state: 'COMPLETED', submitted_at: '2026-11-12T00:01:00+00:00', updated_at: '2026-11-12T00:02:00+00:00', error_message: null },
    { contract_version: 1, job_id: 'job-beta', project_id: projectId, kind: 'EVALUATION', revision_id: revisionId, state: 'FAILED', submitted_at: '2026-11-12T00:03:00+00:00', updated_at: '2026-11-12T00:04:00+00:00', error_message: 'The backend refused this revision.' },
  ];
  await page.addInitScript(id => localStorage.setItem('srota-gateway-selection:v1', JSON.stringify({ projectId: id })), projectId);
  await page.route('**/gw/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/gw/api/v1', '');
    const ok = (json: unknown) => route.fulfill({ json });
    if (path === '/health') return ok({ status: 'ok', api: 'v1', features: {}, backends: {} });
    if (path === '/projects') return ok({ contract_version: 1, projects: [project] });
    if (path === `/projects/${projectId}`) return ok(project);
    if (path === `/projects/${projectId}/draft`) return ok({ request: {}, design_hash: 'draft-token' });
    if (path === `/projects/${projectId}/jobs`) return ok({ contract_version: 1, jobs });
    if (path === `/projects/${projectId}/jobs?kind=EVALUATION`) return ok({ contract_version: 1, jobs: [jobs[1]] });
    if (path.endsWith('/topology')) return ok({ family: 'mesh', counts: { routers: 1, channels: 0, endpoints: 0 }, routers: [], channels: [], endpoints: [] });
    if (path.endsWith('/compile-result')) return ok({ available: false, groups: {} });
    return route.fulfill({ status: 404, json: { detail: path } });
  });

  await page.goto('/#/shared/jobs');
  await expect(page.getByRole('heading', { level: 1, name: 'Jobs, Problems & Logs' })).toBeVisible();
  await expect(page.getByText('2 gateway jobs', { exact: true })).toBeVisible();
  await expect(page.getByText('job-alpha', { exact: true })).toBeVisible();
  await expect(page.getByText('job-beta', { exact: true })).toBeVisible();
  await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible();
  await expect(page.getByText('FAILED', { exact: true })).toBeVisible();
  await expect(page.getByText('The backend refused this revision.', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Problems', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Gateway job failures' })).toBeVisible();
  await expect(page.getByText('The backend refused this revision.', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Logs', exact: true }).click();
  await expect(page.getByText('Gateway job logs')).toBeVisible();
  await expect(page.getByText('Local prototype activity')).toBeVisible();
});
