import { expect, test, type Page } from '@playwright/test';
import { join } from 'node:path';

import { projectId, project, readiness, longName, catalog } from './fixtures/rtl-delivery-data';

async function openDelivery(page: Page, mode: 'catalog' | 'offline' | 'stale-preview' | 'retry-preview' | 'refresh-failure' = 'catalog') {
  let statusReads = 0;
  let catalogReads = 0;
  await page.route('**/gw/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/gw/api/v1', '');
    const ok = (json: unknown) => route.fulfill({ json });
    if (path === '/health') return ok({ status: 'ok', api: 'v1', backends: {} });
    if (path === '/projects') return ok({ projects: [project] });
    if (path === `/projects/${projectId}`) return ok(project);
    if (path === `/projects/${projectId}/draft`) return ok({ request: {}, dirty: false, design_hash: 'sha256:fixture' });
    if (path === `/projects/${projectId}/catalog-evaluation-plan`) return ok({ draft_design_hash: 'sha256:fixture', workload_id: 'fixture', participant_count: 2, operation_count: 1, compute_stages: 0, selection: { job_id: 'job-fixture', candidate_id: 'candidate-fixture', topology_id: 'mesh4', label: 'Mesh 4x4', workload_id: 'fixture' }, backends: [], topologies: [] });
    if (path === `/projects/${projectId}/catalog-evaluations/job-fixture`) return ok({ rows: [], job: { state: 'COMPLETED' } });
    if (path === `/projects/${projectId}/rtl-readiness`) return ok(mode === 'stale-preview' || mode === 'retry-preview' ? { ...readiness, preview_available: true, preview_blockers: [] } : readiness);
    if (path === `/projects/${projectId}/rtl-previews` && route.request().method() === 'POST') return ok({ job_id: 'job-stale', project_id: projectId, state: 'QUEUED' });
    if (path === `/projects/${projectId}/rtl-previews/job-stale`) {
      if (mode === 'retry-preview' && statusReads++ === 0) return route.fulfill({ status: 503, json: { detail: 'transient status failure' } });
      return ok({ stale: true, job: { job_id: 'job-stale', project_id: projectId, state: mode === 'retry-preview' ? 'RUNNING' : 'COMPLETED' }, manifest: null });
    }
    if (path === '/catalog/rtl-prototypes') return mode === 'offline' || (mode === 'refresh-failure' && catalogReads++ > 0) ? route.fulfill({ status: 503, json: { detail: 'fixture offline' } }) : ok(catalog);
    return route.fulfill({ status: 404, json: { detail: `Unmocked fixture request: ${path}` } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).click();
  await page.goto('/#/flow/run');
  await expect(page.getByRole('heading', { name: 'Research RTL evidence', exact: true })).toBeVisible();
}

test('delivery renders evidence states, keyboard selection, safe file action and responsive long names', async ({ page }) => {
  await openDelivery(page);
  await expect(page.getByText('Required targets · 1 present / 12')).toBeVisible();
  await expect(page.getByText('Missing or unknown · 11')).toBeVisible();
  await expect(page.getByText('Optional targets (1)')).toBeVisible();
  await expect(page.getByText('Non-target entries (1)')).toBeVisible();
  await expect(page.getByText('Presence unknown').first()).toBeVisible();
  await expect(page.getByText('NOT_QUALIFIED', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: /Mesh 8x8/ }).press('Enter');
  await page.locator('.delivery-details', { hasText: 'Mesh 8x8 · mesh8x8' }).locator('summary').click();
  await expect(page.getByText('Project match')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Current project preview', exact: true })).toBeVisible();
  await expect(page.getByText('Final RTL unavailable.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate supported RTL preview', exact: true })).toBeDisabled();

  const screenshotRoot = process.env.RTL_SCREENSHOT_DIR ?? join(process.cwd(), 'reports/screenshots/rtl-delivery');
  for (const [width, height] of [[1440, 900], [1280, 800], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.getByRole('heading', { name: 'Research RTL evidence', exact: true }).evaluate(element => element.scrollIntoView({ block: 'start' }));
    await expect(page.getByText('Required targets · 1 present / 12')).toBeInViewport();
    await expect(page.getByRole('columnheader', { name: 'Required target', exact: true })).toBeInViewport();
    await expect(page.locator('.delivery-table').first().locator('tbody tr')).toHaveCount(12);
    await expect(page.getByText('Optional targets (1)')).toBeAttached();
    await expect(page.getByText('Non-target entries (1)')).toBeAttached();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: join(screenshotRoot, `inventory-${width}.png`), fullPage: true, animations: 'disabled' });
    const optional = page.getByText('Optional targets (1)', { exact: true });
    const nonTarget = page.getByText('Non-target entries (1)', { exact: true });
    await optional.click();
    await nonTarget.click();
    await optional.evaluate(element => element.scrollIntoView({ block: 'start' }));
    await expect(page.getByRole('button', { name: /DragonflyNew/ })).toBeInViewport();
    await expect(page.getByRole('rowheader', { name: /KNCube/ })).toBeInViewport();
    await page.screenshot({ path: join(screenshotRoot, `scope-split-${width}.png`), fullPage: true, animations: 'disabled' });
    await optional.click();
    await nonTarget.click();
  }
  const selected = page.getByRole('button', { name: /Mesh 8x8/ });
  await selected.focus();
  await page.keyboard.press('Enter');
  await expect(selected).toHaveAttribute('aria-pressed', 'true');
  const link = page.getByRole('link', { name: new RegExp(`Download ${longName}`) });
  await expect(link).toHaveAttribute('href', `/gw/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/${longName}?version=${'a'.repeat(64)}`);
  await expect(link).toHaveAttribute('download');
  await expect(page.getByText(longName, { exact: true })).toBeVisible();

  for (const [width, height] of [[1440, 900], [1280, 800], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.locator('.delivery-details', { hasText: 'Mesh 8x8 · mesh8x8' }).evaluate(element => element.scrollIntoView({ block: 'start' }));
    const detailsText = await page.locator('.delivery-details', { hasText: 'Mesh 8x8 · mesh8x8' }).innerText();
    expect(detailsText).toContain('Project match');
    const dimensions = await page.evaluate(() => ({ pageWidth: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(dimensions.pageWidth, `page overflow at ${width}px`).toBeLessThanOrEqual(dimensions.viewport);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: join(screenshotRoot, `details-${width}.png`), fullPage: true, animations: 'disabled' });
  }
});

test('catalog error has retry and never substitutes a positive offline snapshot', async ({ page }) => {
  await openDelivery(page, 'offline');
  await expect(page.getByText(/Research catalog unavailable:.*fixture offline/)).toBeVisible();
  await expect(page.getByText(/No offline snapshot is shown/)).toBeVisible();
  await expect(page.getByText('Required targets · 1 present / 12')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Refresh evidence' })).toBeEnabled();
});

test('failed refresh removes previously current counts, rows and download actions', async ({ page }) => {
  await openDelivery(page, 'refresh-failure');
  await expect(page.getByText('Required targets · 1 present / 12')).toBeVisible();
  await page.getByRole('button', { name: 'Refresh evidence' }).click();
  await expect(page.getByText(/Research catalog unavailable:.*fixture offline/)).toBeVisible();
  await expect(page.locator('.delivery-table')).toHaveCount(0);
  await expect(page.getByText('Required targets · 1 present / 12')).toHaveCount(0);
  await expect(page.getByRole('link', { name: new RegExp(`Download ${longName}`) })).toHaveCount(0);
});

test('preview status can be retried and catalog refresh preserves active preview tracking', async ({ page }) => {
  await openDelivery(page, 'retry-preview');
  await page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ }).check();
  await page.getByRole('button', { name: 'Generate supported RTL preview', exact: true }).click();
  await expect(page.getByText('transient status failure')).toBeVisible();
  await page.getByRole('button', { name: 'Retry preview status' }).click();
  await expect(page.getByText('running', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Refresh evidence' }).click();
  await expect(page.getByText('running', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate supported RTL preview', exact: true })).toBeDisabled();
});

test('project-specific preview remains separate and reports stale state', async ({ page }) => {
  await openDelivery(page, 'stale-preview');
  await page.locator('.delivery-details', { hasText: 'Mesh 8x8 · mesh8x8' }).locator('summary').click();
  await expect(page.getByText('Project match')).toBeVisible();
  await page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ }).check();
  await page.getByRole('button', { name: 'Generate supported RTL preview', exact: true }).click();
  await expect(page.getByText(/This preview was generated from a different draft/)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Research RTL evidence', exact: true })).toBeVisible();
});
