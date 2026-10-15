import { expect, test } from '@playwright/test';

const project = {
  contract_version: 1,
  project: {
    project_id: 'e2e-graph',
    name: 'Graph E2E',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  active_revision_id: null,
  active_revision: null,
  latest_attempt_revision_id: null,
  latest_attempt: null,
  latest_active_run: null,
  latest_static_evaluation: null,
  latest_serving_experiment: null,
  latest_optimization_study: null,
  active_evaluation: null,
  draft: {
    dirty: false,
    based_on_revision_id: null,
    workload_id: null,
    source: null,
    design_hash: null,
    updated_at: null,
  },
  revisions: [],
  runs: [],
  optimizations: [],
  flow: { state: 'DRAFT', next_action: 'edit', reason: 'E2E fixture' },
};

test.beforeEach(async ({ page }) => {
  let projects = [project];
  let createdProject = project;
  await page.route('**/gw/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/gw/api/v1', '');
    if (path === '/health') {
      await route.fulfill({ json: { status: 'ok', api: 'e2e', backends: {} } });
    } else if (path === '/projects') {
      if (route.request().method() === 'POST') {
        const input = route.request().postDataJSON() as { name?: string };
        createdProject = {
          ...project,
          project: { ...project.project, project_id: 'e2e-created', name: input.name ?? 'E2E project' },
        };
        projects = [...projects, createdProject];
        await route.fulfill({ json: createdProject });
      } else {
        await route.fulfill({ json: { contract_version: 1, projects } });
      }
    } else if (/^\/projects\/[^/]+$/.test(path)) {
      await route.fulfill({ json: path.includes('e2e-created') ? createdProject : project });
    } else if (/^\/projects\/[^/]+\/draft$/.test(path)) {
      await route.fulfill({
        json: {
          contract_version: 1,
          project_id: path.split('/')[2],
          workload_id: null,
          source: null,
          updated_at: null,
          design_hash: null,
          dirty: false,
          active_revision_id: null,
          latest_attempt_revision_id: null,
          request: null,
        },
      });
    } else if (path === '/catalog/workloads') {
      await route.fulfill({ json: { contract_version: 1, workloads: [] } });
    } else {
      await route.fulfill({ status: 404, json: { detail: 'Not part of this E2E scenario' } });
    }
  });
});

test('preset load is one undoable graph edit', async ({ page }) => {
  await page.goto('/projects/e2e-graph/loom/graph');
  await expect(page.getByRole('heading', { name: 'Loom workspace: graph' })).toBeVisible();
  const nodes = page.locator('[data-testid="graph-canvas"] g[data-node-id]');
  await expect(nodes).toHaveCount(64);

  const preset = page.getByRole('combobox', { name: 'graph preset' });
  await preset.selectOption({ label: 'Ring ×8' });
  await expect(nodes).toHaveCount(8);
  await expect(page.getByRole('button', { name: 'undo', exact: true })).toBeEnabled();

  await page.getByRole('button', { name: 'undo', exact: true }).click();
  await expect(preset).toHaveValue('8x8-mesh');
  await expect(nodes).toHaveCount(64);
  await expect(page.getByRole('button', { name: 'redo', exact: true })).toBeEnabled();

  await page.getByRole('button', { name: 'redo', exact: true }).click();
  await expect(preset).toHaveValue('ring');
  await expect(nodes).toHaveCount(8);
});

test('F01: edit, validate, export and reopen a custom topology', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Name' }).fill('F01 Graph');
  await page.getByRole('button', { name: 'Create project' }).click();
  await expect(page).toHaveURL(/\/projects\/e2e-created\/workload$/);
  await page.getByRole('link', { name: 'System graph' }).click();
  await expect(page.getByRole('heading', { name: 'Loom workspace: graph' })).toBeVisible();
  const nodes = page.locator('[data-testid="graph-canvas"] g[data-node-id]');
  const links = page.locator('[data-testid="graph-canvas"] [data-testid^="link-e"]');
  await expect(nodes).toHaveCount(64);

  await page.getByRole('button', { name: 'node (auto-wired)' }).click();
  await expect(nodes).toHaveCount(65);
  await expect(page.locator('.loom-strip-val').nth(2)).toHaveText('custom');

  await page.getByRole('button', { name: 'link mode' }).click();
  await page.getByTestId('node-n1').click();
  await page.getByTestId('node-n3').click();
  await expect(links).toHaveCount(114);
  // The hit target is an intentionally transparent, wide SVG path over the
  // visible edge line, so force is needed for Playwright's painted-pixel check.
  await links.last().click({ force: true, position: { x: 60, y: 0 } });
  const width = page.getByRole('spinbutton', { name: 'inspector width' });
  await expect(width).toBeVisible();
  await width.fill('1024');
  await width.press('Tab');
  await expect(width).toHaveValue('1024');
  await expect(page.getByText('No issue in the graph.')).toBeVisible();

  const saved = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('loom-graph-autosave-v1:e2e-created') ?? 'null'));
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'save project.json' }).click(),
  ]);
  await page.locator('input[type="file"]').setInputFiles(await download.path());
  await expect(nodes).toHaveCount(65);
  await expect(links).toHaveCount(114);
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem('loom-graph-autosave-v1:e2e-created') ?? 'null'))).toEqual(saved);

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Loom workspace: graph' })).toBeVisible();
  await expect(nodes).toHaveCount(65);
  await expect(links).toHaveCount(114);
  await expect(page.getByText('No issue in the graph.')).toBeVisible();
  await expect.poll(() => page.evaluate(() =>
    JSON.parse(localStorage.getItem('loom-graph-autosave-v1:e2e-created') ?? 'null'))).toEqual(saved);
});

test('F21: a legacy flat graph migrates on load through the real UI', async ({ page }) => {
  const legacy = {
    schemaVersion: 1,
    presetHint: 'custom',
    nodes: [
      { id: 'n1', x: 0, y: 0, role: 'nic', ports: 2, clock: 'clk_core' },
      { id: 'n2', x: 120, y: 0, role: 'compute_tile', ports: 2, clock: 'clk_core' },
      { id: 'n3', x: 240, y: 0, role: 'hbm_controller', ports: 2, clock: 'clk_core' },
    ],
    edges: [
      { id: 'e1', src: 'n1', dst: 'n2', width: 512, pipelineStages: 1, vcClass: 0 },
      { id: 'e2', src: 'n2', dst: 'n3', width: 512, pipelineStages: 1, vcClass: 0 },
    ],
  };
  await page.goto('/projects/e2e-graph/loom/graph');
  await expect(page.getByRole('heading', { name: 'Loom workspace: graph' })).toBeVisible();
  const nodes = page.locator('[data-testid="graph-canvas"] g[data-node-id]');
  await expect(nodes).toHaveCount(64);

  await page.locator('input[type="file"]').setInputFiles({
    name: 'legacy.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(legacy)),
  });
  await expect(nodes).toHaveCount(3);
  await expect(page.getByText('No issue in the graph.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'undo', exact: true })).toBeDisabled();
});
