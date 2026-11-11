import { expect, test, type Page } from '@playwright/test';
import { catalog, readiness } from './fixtures/rtl-delivery-data';

async function bindGateway(page: Page, nextReadiness: () => Promise<void>, launch: () => Promise<void> = async () => {}) {
  const requests: string[] = [];
  let reads = 0;
  await page.route('**/gw/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/gw/api/v1', '');
    requests.push(path);
    if (path === '/catalog/rtl-prototypes') return route.fulfill({ json: catalog });
    if (path.endsWith('/rtl-readiness')) {
      const current = ++reads;
      if (current > 1) await nextReadiness();
      return route.fulfill({ json: { ...readiness, draft_design_hash: `scope-${current}`, preview_available: true, preview_blockers: [] } });
    }
    if (path.endsWith('/rtl-previews') && route.request().method() === 'POST') {
      await launch();
      return route.fulfill({ json: { job_id: 'job-old', state: 'QUEUED' } });
    }
    if (path.endsWith('/rtl-previews/job-old')) return route.fulfill({ json: {
      stale: true, job: { job_id: 'job-old', state: 'COMPLETED' },
      manifest: { lint: { status: 'PASS' } },
    } });
    return route.fulfill({ status: 404, json: { detail: path } });
  });
  await page.goto('/tests/fixtures/rtl-delivery-lifecycle.html');
  await expect(page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ })).toBeEnabled();
  return requests;
}

for (const control of ['Switch project', 'Switch revision']) {
  test(`${control} never commits prior-scope preview actions before reset effects`, async ({ page }) => {
    let release!: () => void;
    const blocked = new Promise<void>(resolve => { release = resolve; });
    const requests = await bindGateway(page, () => blocked);
    await page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ }).check();
    await page.getByRole('button', { name: 'Generate supported RTL preview', exact: true }).click();
    await expect(page.getByRole('link', { name: 'Download preview archive & manifest' })).toBeVisible();
    await page.getByRole('button', { name: control, exact: true }).click();
    await expect(page.getByText('Loading delivery state for the selected project revision…')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Download preview archive & manifest' })).toHaveCount(0);
    await expect(page.getByText(/This preview was generated from a different draft/)).toHaveCount(0);
    await expect(page.getByTestId('scope-leaks')).toHaveText('[]');
    expect(requests).not.toContain('/projects/p-second/rtl-previews/job-old');
    release();
    await expect(page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ })).toBeEnabled();
    await expect(page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ })).not.toBeChecked();
  });
}

test('a late launch response cannot attach its job to a newer revision', async ({ page }) => {
  let release!: () => void;
  const blocked = new Promise<void>(resolve => { release = resolve; });
  const requests = await bindGateway(page, async () => {}, () => blocked);
  await page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ }).check();
  await page.getByRole('button', { name: 'Generate supported RTL preview', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Submitting…', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Switch revision', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: /Generate limited topology-only RTL/ })).not.toBeChecked();
  const response = page.waitForResponse(res => res.url().endsWith('/rtl-previews') && res.request().method() === 'POST');
  release();
  await response;
  await expect(page.getByRole('button', { name: 'Generate supported RTL preview', exact: true })).toBeDisabled();
  await expect(page.getByRole('link', { name: 'Download preview archive & manifest' })).toHaveCount(0);
  await expect(page.getByTestId('scope-leaks')).toHaveText('[]');
  expect(requests.filter(path => path.endsWith('/rtl-previews/job-old'))).toHaveLength(0);
});
