import { expect, test, type Page } from '@playwright/test';

const BASE = 'http://127.0.0.1:5174/desktop-test/gw';
const PROJECT = {
  project: { project_id: 'desktop-project', name: 'My desktop project', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
  active_revision_id: null, active_revision: null, runs: [],
};

async function desktop(page: Page, options: { offline?: boolean; projects?: boolean } = {}) {
  await page.addInitScript(base => {
    Object.defineProperty(window, '__TAURI_INTERNALS__', {
      value: { invoke: async (command: string) => {
        if (command !== 'gateway_connection') throw new Error('Unexpected desktop command');
        return { base };
      } },
    });
  }, BASE);
  await page.route('**/desktop-test/gw/api/v1/**', async route => {
    if (options.offline) return route.abort();
    const path = new URL(route.request().url()).pathname.split('/api/v1')[1];
    const documents: Record<string, unknown> = {
      '/health': { status: 'ok', api: 'v1', backends: {} },
      '/projects': { projects: options.projects ? [PROJECT] : [] },
      '/projects/desktop-project': PROJECT,
      '/projects/desktop-project/draft': { request: { schema_version: 4, agents: [], topology: { kind: 'torus', side_length: 5 }, workload: {} }, design_hash: 'sha256:desktop-test' },
      '/catalog/fabric-presets': { presets: [] },
      '/catalog/workloads': { workloads: [] },
    };
    return route.fulfill({ json: documents[path] ?? {} });
  });
}

test('a fresh desktop shows live projects, not the illustrative offline sample', async ({ page }) => {
  await desktop(page);
  await page.goto('/#/design/system');
  await expect(page.getByRole('heading', { name: 'Srota Studio projects', exact: true })).toBeVisible({ timeout: 2000 });
  await expect(page.getByText('The store holds no projects', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'New project', exact: true })).toBeVisible();
  await expect(page.getByText('Sample project · local browser state', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Falcon8_NoC_Gen2', { exact: true })).toHaveCount(0);
  await page.goto('/#/analysis/summary');
  await expect(page.getByRole('heading', { name: 'Srota Studio projects', exact: true })).toBeVisible();
  await expect(page.getByText('Sample project · local browser state', { exact: true })).toHaveCount(0);
});

test('a desktop connection failure stays visible instead of falling back to sample projects', async ({ page }) => {
  await desktop(page, { offline: true });
  await page.goto('/#/shared/projects');
  await expect(page.getByText('Gateway not reachable', { exact: false })).toBeVisible();
  await expect(page.getByText('Sample project · local browser state', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Falcon8_NoC_Gen2', { exact: true })).toHaveCount(0);
});

test('selecting a desktop project opens the shared live workspace', async ({ page }) => {
  const workspaceRequests: string[] = [];
  page.on('request', request => {
    if (/\/(DesignViews|ExploreViews|OperationalViews|WorkloadViews|AnalysisViews|AgentViews)[.-]/.test(new URL(request.url()).pathname)) {
      workspaceRequests.push(request.url());
    }
  });
  await desktop(page, { projects: true });
  await page.goto('/#/design/system');
  await expect(page.getByRole('heading', { name: 'Srota Studio projects', exact: true })).toBeVisible();
  // The project picker must not download or evaluate unopened workspaces.
  expect(workspaceRequests).toEqual([]);
  await page.getByRole('button', { name: 'Load', exact: true }).click();
  await expect(page.locator('.header-revision')).toContainText('live store');
  await expect.poll(() => workspaceRequests.some(url => url.includes('/DesignViews'))).toBe(true);
  await expect(page.getByRole('status').filter({ hasText: 'Loading workspace…' })).toHaveCount(0);
  await expect(page.locator('.project-switch')).toHaveText('My desktop project');
  await page.reload();
  await expect(page.locator('.project-switch')).toHaveText('My desktop project');
  await expect(page.getByText('Sample project · local browser state', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Falcon8_NoC_Gen2', { exact: true })).toHaveCount(0);
});
