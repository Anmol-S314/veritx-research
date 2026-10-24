import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';

// Opt in explicitly: creates and deletes only its own disposable project.
test('disposable live project: save, compile, evaluate, inspect, delete', async ({ page, request }) => {
  test.skip(process.env.VERITX_LIVE_TEST !== '1', 'Set VERITX_LIVE_TEST=1 to run real backends.');
  test.setTimeout(120000);
  page.setDefaultTimeout(10000);
  const api = '/gw/api/v1';
  const before = await (await request.get(`${api}/projects`)).json();
  const name = `prototype-smoke-${Date.now()}`;
  let id: string | undefined;
  try {
    const created = await request.post(`${api}/projects/from-preset`, { data: { preset_id: 'mesh4', name } });
    expect(created.ok(), await created.text()).toBe(true);
    id = (await created.json()).project.project_id;
    expect((await request.post(`${api}/projects/${id}/workload`, { data: { workload_id: 'llama-dense-8b-64tiles' } })).ok()).toBe(true);
    const draft = await (await request.get(`${api}/projects/${id}/draft`)).json();
    const previewResponse = await request.post(`${api}/projects/${id}/topology-preview`, { data: { request: draft.request, topology: { kind: 'mesh', side_length: 9, concentration: 1 } } });
    expect(previewResponse.ok(), await previewResponse.text()).toBe(true);
    const canonical = (await previewResponse.json()).request;
    const saved = await request.put(`${api}/projects/${id}/draft`, { data: { request: canonical } });
    expect(saved.ok(), await saved.text()).toBe(true);
    const compiled = await request.post(`${api}/projects/${id}/compile`, { data: {}, timeout: 60000 });
    expect(compiled.ok(), await compiled.text()).toBe(true);
    const compiledResult = await compiled.json();
    expect(compiledResult.revision_id, JSON.stringify(compiledResult)).toBeTruthy();
    expect(compiledResult.compilation?.status, JSON.stringify(compiledResult.compilation)).toBe('COMPILED');
    await page.goto('/#/shared/projects');
    await page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: 'Load', exact: true }).click();
    await expect(page.locator('.header-revision')).toContainText('-r');
    if (await page.getByRole('button', { name: 'Edit draft', exact: true }).count()) await page.getByRole('button', { name: 'Edit draft', exact: true }).click();
    await page.getByRole('spinbutton', { name: 'clock_freq_mhz', exact: true }).fill('1200');
    await page.getByRole('button', { name: 'Validate topology', exact: true }).click();
    await expect(page.getByText('Topology accepted', { exact: false })).toBeVisible();
    await page.getByRole('button', { name: 'Save draft', exact: true }).click();
    await expect(page.getByText('uncompiled changes', { exact: false })).toBeVisible();
    await page.getByRole('button', { name: 'Compile draft', exact: true }).click();
    await expect(page.locator('.header-revision')).toContainText('-r02', { timeout: 30000 });
    await page.evaluate(() => { location.hash = '/analysis/summary'; });
    await expect(page.getByRole('checkbox', { name: 'Select NETWORK_COMPLETION', exact: true })).toBeEnabled({ timeout: 30000 });
    for (const checkbox of await page.getByRole('checkbox', { name: /^Select / }).all()) if (await checkbox.isEnabled()) await checkbox.uncheck();
    await page.getByRole('checkbox', { name: 'Select NETWORK_COMPLETION', exact: true }).check();
    await page.getByRole('checkbox', { name: /I understand this runs real backend/ }).check();
    await page.getByRole('button', { name: 'Launch 1 analysis', exact: true }).click();
    await expect(page.getByText('Run published:', { exact: false }).first()).toBeVisible({ timeout: 90000 });
    await page.evaluate(() => { location.hash = '/analysis/metrics'; });
    await expect(page.getByText('completion_cycles', { exact: true }).first()).toBeVisible();
    await page.reload();
    await expect(page.getByText('Gateway project', { exact: true })).toBeVisible();
    await expect(page.getByText('completion_cycles', { exact: true }).first()).toBeVisible();
    await page.evaluate(() => { location.hash = '/verify/evidence'; });
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download selected JSON document', exact: true }).click();
    const downloaded = await downloading;
    expect(Object.keys(JSON.parse(await readFile((await downloaded.path())!, 'utf8'))).length).toBeGreaterThan(0);
    await page.evaluate(() => { location.hash = '/explore/brief'; });
    await page.getByRole('checkbox', { name: /Approve this revision/ }).check();
    await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Download study results', exact: true })).toBeVisible({ timeout: 60000 });
  } finally {
    if (id) {
      // Delete through the UI so the test exercises the same typed-id
      // confirmation a user faces; fall back to the API only if the UI fails.
      try {
        await page.evaluate(() => { location.hash = '/shared/projects'; });
        await page.getByRole('button', { name: 'Delete project…', exact: true }).click({ timeout: 10000 });
        await page.getByLabel('Delete confirmation').fill(id);
        await page.getByRole('button', { name: 'Delete permanently', exact: true }).click();
        await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0, { timeout: 15000 });
      } catch {
        const cleanup = await fetch(`http://127.0.0.1:5174${api}/projects/${id}`, { method: 'DELETE', signal: AbortSignal.timeout(15000) });
        expect(cleanup.ok).toBe(true);
      }
    }
    const after = await (await request.get(`${api}/projects`)).json();
    expect(after.projects.some((p: any) => p.project.project_id === id)).toBe(false);
    const remaining = new Set(after.projects.map((p: any) => p.project.project_id));
    expect(before.projects.every((p: any) => remaining.has(p.project.project_id))).toBe(true);
  }
});
