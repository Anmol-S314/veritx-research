import { expect, test, type Page } from '@playwright/test';

const identity = { trace_sha256: 'sha256:trace', arm_sha256: 'sha256:arm', binary_sha256: 'sha256:binary', simulator_seed: 1 };
function document(verified = true) {
  return {
    schema: 'veritx/workload-ablation/1', generated_at: '2026-10-25T12:00:00Z', generated_by: 'test',
    common: { packet_size: 5, vc_buf_size: 8, use_noc_latency: 0, seed: 1, note: 'VC counts vary', overrides: {} },
    workloads: [{ workload_id: 'sparse', label: 'Sparse trace', nodes: 64, active_nodes: 2, events: 100, project: 'Test project', ...(verified ? { trace_sha256: identity.trace_sha256, trace_seed: 1, packet_size_flits: [8] } : {}) }],
    topologies: ['one', 'two'].map(id => ({ topology_id: id, label: id, family: 'MESH', nodes: 64, config: 'test.cfg', support: 'research' })),
    runs: ['one', 'two'].map((id, index) => ({ workload: 'sparse', workload_label: 'Sparse trace', topology: id, topology_label: id, family: 'MESH', nodes: 64, vcs: 2, routing: 'dor', packet_size: 5, vc_buf_size: 8, use_noc_latency: 0, status: 'ok', latency_p95: 100 + index * 10, latency_p99: 110, completion_cycles: 1000, knobs: {}, ...(verified ? { ...identity, effective_packet_size_flits: [8], declared_buffer_flits_per_input: 16, qualification: 'NOT_ESTABLISHED' } : {}) })),
  };
}

async function setup(page: Page, verified = true) {
  const baseline = document(verified);
  const requests: Record<string, unknown>[] = [];
  await page.route('**/data/workload_ablation.json', route => route.fulfill({ json: baseline }));
  await page.route('**/gw/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/ablations')) {
      const request = route.request().postDataJSON();
      requests.push(request);
      const tuned = structuredClone(baseline);
      tuned.runs[0].latency_p95 = 50;
      if (request.trace_packet_size) {
        for (const run of tuned.runs) Object.assign(run, { trace_sha256: 'sha256:variant' });
      }
      return route.fulfill({ json: { document: tuned, out: 'test/run', duration_seconds: 1, failed_cells: 0, returncode: 0 } });
    }
    return route.fulfill({ json: path.endsWith('/health') ? { status: 'ok', api: 'v1', backends: {} } : { projects: [] } });
  });
  await page.goto('/#/explore/ablations');
  await expect(page.getByRole('heading', { name: /^Best candidate for/ })).toBeVisible();
  return requests;
}

test('sparse coverage and effective payload are visible; every candidate can be hidden', async ({ page }) => {
  await setup(page);
  const assumptions = page.locator('details.assumptions');
  await assumptions.locator('> summary').click();
  await expect(assumptions.getByText('2 active / 64 available · sparse placement, not full-fabric coverage', { exact: false })).toBeVisible();
  await expect(assumptions.getByText('8 flits', { exact: true }).first()).toBeVisible();
  await expect(assumptions.getByText('not applicable / 1', { exact: true })).toBeVisible();
  const candidates = page.getByRole('group', { name: 'Candidate topologies', exact: true });
  await candidates.getByRole('button').nth(0).click();
  await candidates.getByRole('button').nth(1).click();
  await expect(candidates.getByRole('button', { pressed: true })).toHaveCount(0);
  await expect(page.locator('.abl-visible-count')).toContainText('0 of 2');
});

test('legacy results do not fabricate matched-trace improvements', async ({ page }) => {
  await setup(page, false);
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await expect(page.getByText('Trace identity is missing;', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('yes; only knobs changed', { exact: true })).toHaveCount(0);
  await expect(page.locator('.abl-compare-stats')).toHaveCount(0);
});

test('extra knobs use a key picker instead of requiring raw key=value text', async ({ page }) => {
  const requests = await setup(page);
  const extra = page.locator('details.abl-extra');
  await extra.locator('summary').first().click();
  await page.getByLabel('Other knob', { exact: true }).selectOption('buffer_policy');
  await page.getByLabel('Other knob value', { exact: true }).selectOption('shared');
  await page.getByRole('button', { name: 'Add override', exact: true }).click();
  await expect(extra.getByText('buffer_policy=shared', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await expect(page.locator('.abl-compare-stats')).toBeVisible();
  expect(requests[0].overrides).toMatchObject({ buffer_policy: 'shared' });
});

test('clipboard failures are visible instead of silently ignored', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { value: undefined }));
  await setup(page);
  await page.locator('details.runner-command > summary').click();
  await page.getByRole('button', { name: 'Copy command', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Clipboard access is unavailable');
});

test('stale backend code cannot start an ablation', async ({ page }) => {
  const requests = await setup(page);
  await page.route('**/gw/api/v1/health', route => route.fulfill({ json: { status: 'stale', api: 'v1', backends: {}, code: { stale: true, reason: 'Backend code changed' } } }));
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await expect(page.getByText('Backend code changed. Restart the gateway or desktop app before running a new experiment.', { exact: false })).toBeVisible();
  expect(requests).toHaveLength(0);
});

test('verified pairs show deltas and workload variants send explicit inputs', async ({ page }, testInfo) => {
  const requests = await setup(page);
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await expect(page.locator('.abl-compare-stats')).toBeVisible();
  await page.getByRole('button', { name: 'Tune & rerun', exact: true }).click();
  await page.getByLabel('Trace packet size', { exact: true }).fill('16');
  await page.getByLabel('Arrival time scale', { exact: true }).fill('0.5');
  await page.getByLabel('Rank placement stride', { exact: true }).fill('9');
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await expect(page.getByText('Trace changed;', { exact: false }).first()).toBeVisible();
  await expect(page.locator('.abl-compare-stats')).toHaveCount(0);
  expect(requests[1]).toMatchObject({ trace_packet_size: 16, time_scale: 0.5, rank_stride: 9, seed: 1 });
  for (const width of [1440, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const size = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(size.width).toBeLessThanOrEqual(size.viewport);
    await page.screenshot({ path: testInfo.outputPath(`ablation-evidence-${width}.png`) });
  }
});
