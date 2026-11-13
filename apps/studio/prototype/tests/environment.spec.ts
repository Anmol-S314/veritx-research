import { expect, test } from '@playwright/test';

/** The environment page is the one place the prototype reports what the
 *  gateway can actually execute. It must read health, the qualification
 *  register and the report index, and it must not turn a stale gateway into a
 *  green state. */
test('environment reports live gateway backends, qualification and reports', async ({ page }) => {
  await page.addInitScript(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.route('**/gw/api/v1/health', route => route.fulfill({
    json: {
      status: 'ok', api: 'v1',
      code: { stale: false, pid: 4242, source_age_s: 2.5 },
      features: { job_events: true, job_logs: true, agent_runtime: false },
      backends: {
        BOOKSIM_STANDALONE: { state: 'PRESENT', binary_present: true, manifest_present: true },
        ASTRA2_EMBEDDED_BOOKSIM: { state: 'PRESENT', binary_present: true, manifest_present: true },
        RAMULATOR2_HBM3_V1: { state: 'ABSENT', binary_present: false, manifest_present: false },
      },
    },
  }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [] } }));
  await page.route('**/gw/api/v1/capabilities', route => route.fulfill({ json: { backends: {}, deferred: { formal_verification: 'NOT_RUN' } } }));
  await page.route('**/gw/api/v1/qualification', route => route.fulfill({
    json: {
      engines: {
        booksim_embedded: { role: 'canonical network execution engine', integration: 'QUALIFIED', numerical: 'QUALIFIED', limitations: ['route realization observed at the first hop only'] },
        astra: { role: 'runtime / integration', integration: 'QUALIFIED', numerical: 'NOT_ESTABLISHED', limitations: ['absolute timing remains unqualified'] },
      },
      deferred: { rtl_verification: 'NOT_RUN', formal_verification: 'NOT_RUN' },
    },
  }));
  await page.route('**/gw/api/v1/reports', route => route.fulfill({
    json: { reports: [{ report_id: 'r-1', title: 'T3 dashboard', kind: 'dashboard', media_type: 'text/html', size_bytes: 8192, modified_at: '2026-11-12T00:00:00+00:00', source_path: 'report/t3/index.html' }] },
  }));

  await page.goto('/#/shared/environment');
  await expect(page.getByRole('heading', { level: 1, name: 'Environment & Local Settings' })).toBeVisible();
  await expect(page.getByText('api/v1', { exact: true })).toBeVisible();
  await expect(page.getByText('2 / 3', { exact: true })).toBeVisible();
  await expect(page.getByText('ASTRA-SIM 2 · embedded BookSim', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('canonical network execution engine', { exact: true })).toBeVisible();
  await expect(page.getByText('NOT_ESTABLISHED', { exact: true })).toBeVisible();
  await expect(page.getByRole('rowheader', { name: /T3 dashboard/ })).toBeVisible();
  await expect(page.getByText('8.00 KiB', { exact: true })).toBeVisible();
  await expect(page.getByText('The gateway reports that its loaded code is older than the checkout.', { exact: false })).toHaveCount(0);
});

test('a stale gateway is visible and not presented as a clean connection', async ({ page }) => {
  await page.addInitScript(() => { localStorage.clear(); sessionStorage.clear(); });
  await page.route('**/gw/api/v1/health', route => route.fulfill({
    json: {
      status: 'stale', api: 'v1',
      code: { stale: true, pid: 9, source_age_s: 7200 },
      features: {}, backends: {},
    },
  }));
  await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [] } }));
  await page.route('**/gw/api/v1/capabilities', route => route.fulfill({ json: {} }));
  await page.route('**/gw/api/v1/qualification', route => route.fulfill({ json: { engines: {} } }));
  await page.route('**/gw/api/v1/reports', route => route.fulfill({ json: { reports: [] } }));

  await page.goto('/#/shared/environment');
  await expect(page.getByText('Connected · stale', { exact: true })).toBeVisible();
  await expect(page.getByText('The gateway reports that its loaded code is older than the checkout.', { exact: false })).toBeVisible();
  await expect(page.getByText('2.0 h', { exact: true })).toBeVisible();
});
