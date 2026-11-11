import { expect, test } from '@playwright/test';

for (const viewport of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 760, height: 900 }]) {
  test(`standalone pages fill the workspace at ${viewport.width}×${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => { localStorage.clear(); sessionStorage.clear(); });
    await page.route('**/gw/**', route => route.fulfill({ status: 503, json: { detail: 'Gateway unavailable for layout test.' } }));
    await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'ok', api: 'v1', backends: {} } }));
    await page.route('**/gw/api/v1/projects', route => route.fulfill({ json: { contract_version: 1, projects: [] } }));

    for (const route of ['flow/start', 'flow/tune', 'flow/search', 'flow/compare', 'flow/optimize', 'flow/run', 'workloads/workflow', 'shared/projects']) {
      await page.goto(`/#/${route}`);
      const panel = page.locator('.page-content > .view-main');
      await expect(panel).toBeVisible();
      await expect(panel).not.toContainText('Loading workspace…');
      await expect.poll(async () => panel.evaluate(element => {
        const content = element.parentElement!.getBoundingClientRect();
        return Math.abs(content.right - element.getBoundingClientRect().right);
      }), { message: `${route} should fill the content area to the right edge` }).toBeLessThan(2);
      await expect.poll(async () => panel.evaluate(element => {
        const content = element.parentElement!.getBoundingClientRect();
        const bounds = element.getBoundingClientRect();
        return Math.abs(content.bottom - bounds.bottom);
      }), { message: `${route} should fill the content area down to its bottom edge` }).toBeLessThan(2);
    }
  });
}
