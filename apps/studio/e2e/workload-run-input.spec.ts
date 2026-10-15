import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

/** M5-29: workload → mapping → validated run-input flow, driven through the real
 *  browser UI. Creates a workload, authors a phase and its explicit cycles, maps
 *  ranks under a chosen policy, resolves validation, and exports a deterministic
 *  run intent — twice, to prove byte-stability. */
const project = {
  contract_version: 1,
  project: { project_id: 'e2e-workload', name: 'Workload E2E', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  active_revision_id: null,
  active_revision: null,
  latest_attempt_revision_id: null,
  latest_attempt: null,
  latest_active_run: null,
  latest_static_evaluation: null,
  latest_serving_experiment: null,
  latest_optimization_study: null,
  active_evaluation: null,
  draft: { dirty: false, based_on_revision_id: null, workload_id: null, source: null, design_hash: null, updated_at: null },
  revisions: [],
  runs: [],
  optimizations: [],
  flow: { state: 'DRAFT', next_action: 'edit', reason: 'E2E fixture' },
};

test.beforeEach(async ({ page }) => {
  await page.route('**/gw/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/gw/api/v1', '');
    if (path === '/health') await route.fulfill({ json: { status: 'ok', api: 'e2e', backends: {} } });
    else if (path === '/projects') await route.fulfill({ json: { contract_version: 1, projects: [project] } });
    else if (/^\/projects\/[^/]+$/.test(path)) await route.fulfill({ json: project });
    else if (/^\/projects\/[^/]+\/draft$/.test(path)) await route.fulfill({
      json: { contract_version: 1, project_id: 'e2e-workload', workload_id: null, source: null, updated_at: null, design_hash: null, dirty: false, active_revision_id: null, latest_attempt_revision_id: null, request: null },
    });
    else if (path === '/catalog/workloads') await route.fulfill({ json: { contract_version: 1, workloads: [] } });
    else await route.fulfill({ status: 404, json: { detail: 'Not part of this E2E scenario' } });
  });
});

test('M5-29: create workload, map ranks under a policy and export deterministic run input', async ({ page }) => {
  await page.goto('/projects/e2e-workload/loom/workload');
  await expect(page.getByRole('heading', { name: 'Loom workspace: workload' })).toBeVisible();

  // 1. Create an empty custom workload, then author one phase.
  await page.getByRole('button', { name: 'Create empty custom workload' }).click();
  await page.getByRole('button', { name: '+ Phase' }).click();
  await expect(page.getByLabel('tp ph-1')).toBeVisible();

  // 2. Parallelism demand needs two ranks; the run intent needs explicit cycles.
  await page.getByLabel('tp ph-1').fill('2');
  await page.getByLabel('start cycle ph-1').fill('0');
  await page.getByLabel('duration cycles ph-1').fill('10');

  // 3. Map ranks under a chosen policy (deterministic, one undoable edit).
  await page.getByLabel('rank assignment policy').selectOption('spread');
  await page.getByRole('button', { name: 'Auto-map ranks' }).click();

  // 4. Validation is resolved: the run intent is READY.
  await expect(page.getByRole('status').filter({ hasText: 'Run-intent status: READY (intent only)' })).toBeVisible();

  // 5. Export the validated run intent twice; the two payloads must be identical.
  const exportIntent = async (): Promise<string> => {
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Export validated run intent' }).click(),
    ]);
    return readFile(await download.path(), 'utf8');
  };
  const first = await exportIntent();
  const second = await exportIntent();
  expect(second).toBe(first);

  const parsed = JSON.parse(first) as { runIntentSchemaVersion: number; workload: { phases: { id: string; startCycle: number; durationCycles: number; tp: number }[]; rankMappings: { rank: number; nodeId: string }[] } };
  expect(parsed.runIntentSchemaVersion).toBe(1);
  expect(parsed.workload.phases).toHaveLength(1);
  expect(parsed.workload.phases[0]).toMatchObject({ id: 'ph-1', startCycle: 0, durationCycles: 10, tp: 2 });
  expect(parsed.workload.rankMappings).toHaveLength(2);
  expect(parsed.workload.rankMappings.map((m) => m.rank)).toEqual([0, 1]);
});
