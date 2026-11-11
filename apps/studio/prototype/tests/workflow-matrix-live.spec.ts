import { test, expect } from '@playwright/test';

for (const scenario of [
  { prefix: 'Flow test 02', mode: 'evaluate', questions: ['NETWORK_COMPLETION', 'SYSTEM_MAKESPAN', 'DRAM_TIMING'] },
  { prefix: 'Flow test 03', mode: 'evaluate', questions: ['NETWORK_COMPLETION'] },
  { prefix: 'Flow test 04', mode: 'evaluate', questions: ['NETWORK_COMPLETION'] },
  { prefix: 'Flow test 05', mode: 'evaluate', questions: ['NETWORK_COMPLETION'] },
  { prefix: 'Flow test 06', mode: 'draft', questions: [] },
  { prefix: 'Flow test 07', mode: 'evaluate', questions: ['NETWORK_COMPLETION'] },
  { prefix: 'Flow test 08', mode: 'refusal', questions: [], blockedBy: 'seat_capacity' },
]) test(`${scenario.prefix}: ${scenario.mode} and inspect browser`, async ({ page, request }) => {
  test.skip(process.env.VERITX_LIVE_TEST !== '1', 'Real backend opt-in');
  test.setTimeout(180000);
  page.setDefaultTimeout(15000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const projects = await (await request.get('/gw/api/v1/projects')).json();
  let project = projects.projects.find((row: any) => row.project.name.startsWith(scenario.prefix));
  if (scenario.mode === 'draft' && project?.runs?.length) {
    // Another session may evaluate the draft-only fixture. The subject of this
    // scenario is the empty state, so take any project that still has no runs
    // instead of mutating or skipping.
    project = projects.projects.find((row: any) => row.runs?.length === 0);
  }
  expect(project).toBeTruthy();
  const id = project.project!.project_id;
  await page.goto('/#/shared/projects');
  await page.getByRole('row').filter({ hasText: id }).getByRole('button', { name: 'Load', exact: true }).click();
  await page.goto('/#/workloads/workflow');
  await expect(page.getByRole('tablist', { name: 'Intent sections' })).toBeVisible();
  for (const name of ['Fabric', 'Requirements', 'Validate', 'Workload']) {
    await page.getByRole('tab', { name, exact: true }).click();
    await expect(page.getByRole('tab', { name, exact: true })).toHaveAttribute('aria-selected', 'true');
  }
  if (scenario.mode === 'draft') {
    await page.goto('/#/analysis/summary');
    const project_detail = await (await request.get(`/gw/api/v1/projects/${id}`)).json();
    expect(project_detail.runs).toHaveLength(0);
    await expect(page.getByText(/This project has no runs/)).toBeVisible();
    // The section list stays visible; each section names what it needs instead
    // of disappearing and leaving an apparently broken workspace.
    const tabs = page.getByRole('tablist', { name: 'Analysis sections' });
    await expect(tabs).toBeVisible();
    await expect(page.getByRole('heading', { name: /needs a run/ })).toBeVisible();
    await page.getByRole('tab', { name: 'Memory', exact: true }).click();
    await expect(page.getByRole('tab', { name: 'Memory', exact: true })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('a DRAM_TIMING analysis in the selected run')).toBeVisible();
    await expect(page.getByText(/an unmeasured value is unavailable, not zero and not a pass/)).toBeVisible();
  } else if (scenario.mode === 'refusal') {
    const response = await request.get(`/gw/api/v1/revisions/${project.active_revision_id}/evaluation-plan`);
    expect(response.ok()).toBe(true);
    const plan = await response.json();
    const network = plan.analyses.find((row: any) => row.question === 'NETWORK_COMPLETION');
    // The refusal must name the exact envelope that fails, not a generic denial.
    expect(network.readiness).toBe('BLOCKED');
    expect(network.support).toBe('UNSUPPORTED');
    expect(network.backend).toBeNull();
    expect(String(network.reason)).toContain(scenario.blockedBy);
    await page.goto('/#/analysis/summary');
    const blocked = page.getByRole('row').filter({ hasText: 'NETWORK_COMPLETION' });
    await blocked.getByText('Why blocked', { exact: true }).click();
    await expect(blocked.getByText(new RegExp(scenario.blockedBy!)).first()).toBeVisible();
    await expect(page.getByRole('checkbox', { name: 'Select NETWORK_COMPLETION', exact: true })).toBeDisabled();
    // The plan and the submit gate must agree: a plan that says BLOCKED and a
    // backend that accepts the run would be two truths for one revision.
    const submit = await request.post(`/gw/api/v1/revisions/${project.active_revision_id}/evaluate`, { data: { questions: ['NETWORK_COMPLETION'] } });
    expect(submit.ok()).toBe(false);
    expect(await submit.text()).toContain(scenario.blockedBy!);
    const after = await (await request.get(`/gw/api/v1/projects/${id}`)).json();
    expect(after.runs).toHaveLength(0);
  } else {
    await page.goto('/#/analysis/summary');
    const launcher = page.getByRole('button', { name: 'Run new evaluation' });
    const networkBox = page.getByRole('checkbox', { name: 'Select NETWORK_COMPLETION', exact: true });
    await expect(launcher.or(networkBox)).toBeVisible({ timeout: 30000 });
    // The panel is a disclosure: clicking the toggle while it is already open closes it.
    if (!(await networkBox.isVisible().catch(() => false)) && await launcher.count()) await launcher.click();
    await expect(page.getByRole('checkbox', { name: 'Select NETWORK_COMPLETION', exact: true })).toBeEnabled({ timeout: 30000 });
    for (const box of await page.getByRole('checkbox', { name: /^Select / }).all()) if (await box.isEnabled()) await box.uncheck();
    for (const question of scenario.questions) await page.getByRole('checkbox', { name: `Select ${question}`, exact: true }).check();
    await page.getByRole('checkbox', { name: /I understand this runs real backend/ }).check();
    await page.getByRole('button', { name: scenario.questions.length === 1 ? 'Launch 1 analysis' : `Launch ${scenario.questions.length} analyses`, exact: true }).click();
    await expect(page.getByText('Run published', { exact: false }).first()).toBeVisible({ timeout: 120000 });
    const detail = await (await request.get(`/gw/api/v1/projects/${id}`)).json();
    const latest = [...detail.runs].sort((a: any, b: any) => String(b.completed_at).localeCompare(String(a.completed_at)))[0];
    const counters = await request.get(`/gw/api/v1/loom/simulation/load?run=${latest.run_id}&source=measured`);
    expect(counters.ok(), await counters.text()).toBe(true);
    const series = await request.get(`/gw/api/v1/loom/simulation/series?run=${latest.run_id}`);
    expect(series.ok(), await series.text()).toBe(true);
    await page.goto('/#/analysis/topology');
    const routerPanel = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Per-router measured load', exact: true }) }).last();
    await expect(routerPanel).not.toContainText('Not recorded', { timeout: 15000 });
    const shapePanel = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Fabric load shape · measured channels', exact: true }) }).last();
    await expect(shapePanel).not.toContainText('Not recorded', { timeout: 15000 });
    if (scenario.prefix === 'Flow test 05') {
      await expect(page.getByRole('button', { name: 'Play observed capture', exact: true })).toBeVisible({ timeout: 15000 });
      // Observed hops are checked against the certified route set, not projected.
      const verification = page.getByTestId('observed-verification');
      await expect(verification).toBeVisible({ timeout: 20000 });
      const countOf = async (label: string) => Number((await verification.locator('span').filter({ hasText: label }).locator('strong').first().innerText()).replaceAll(',', ''));
      const watched = await countOf('Watched');
      expect(watched).toBeGreaterThan(0);
      expect(await countOf('Full route')).toBeGreaterThan(0);
      // Every watched flit is accounted for: one that is neither verified, local
      // nor mismatched means the check silently dropped it.
      await expect(verification.getByText('Unverifiable')).toHaveCount(0);
      await expect(verification.getByText('Mismatched')).toHaveCount(0);
      expect(await countOf('Full route') + await countOf('Local')).toBe(watched);
      const observed = page.getByRole('slider', { name: 'Observed playback cycle' });
      const initial = await observed.inputValue();
      await page.getByRole('button', { name: 'Play observed capture', exact: true }).click();
      await expect.poll(() => observed.inputValue()).not.toBe(initial);
      await page.getByRole('button', { name: 'Pause observed capture', exact: true }).click();
      await page.getByLabel('Measured native subnet').selectOption('0');
      await expect(page.getByLabel('Measured native subnet')).toHaveValue('0');
      await expect(page.getByRole('table', { name: 'Measured channels' })).not.toContainText('S1 ·');
      await page.getByLabel('Measured native subnet').selectOption('1');
      await expect(page.getByRole('table', { name: 'Measured channels' })).not.toContainText('S0 ·');
      // Shared-wire fabrics must project on their own resources, not be refused.
      await expect(page.getByText(/not applicable to this shared-wire/)).toHaveCount(0);
      await expect(page.getByText(/does not cover shared-wire resources/)).toHaveCount(0);
      const playback = page.getByTestId('shared-playback');
      const shared = playback.getByRole('slider', { name: 'Shared playback cycle' });
      const before = await shared.inputValue();
      await playback.getByRole('button', { name: 'Play shared playback', exact: true }).click();
      await expect.poll(() => shared.inputValue()).not.toBe(before);
      await playback.getByRole('button', { name: 'Pause shared playback', exact: true }).click();
      await expect(playback.getByText('Rejected rows')).toBeVisible();
      expect(await playback.innerText()).toContain('Rejected rows\n0');
      await playback.getByLabel('playback native plane').selectOption('0');
      const planeD = await playback.locator('g[data-resource]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-resource')).filter(Boolean));
      expect(planeD.length).toBeGreaterThan(0);
      expect(planeD.every(key => key!.startsWith('D:'))).toBe(true);
      await playback.getByLabel('playback native plane').selectOption('1');
      const planeC = await playback.locator('g[data-resource]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-resource')).filter(Boolean));
      expect(planeC.every(key => key!.startsWith('C:'))).toBe(true);
      await playback.getByLabel('playback native plane').selectOption('all');
      // Attribution must name certified shared wires and conserve projected flit-hops.
      const sweep = page.getByTestId('shared-sweep');
      await sweep.getByRole('button', { name: 'Sweep shared resources', exact: true }).click();
      const table = sweep.getByRole('table', { name: 'Shared resource attribution' });
      await expect(table).toBeVisible();
      const topology = await (await request.get(`/gw/api/v1/revisions/${project.active_revision_id}/topology`)).json();
      const wireIds = new Set<string>(topology.shared_links.map((wire: any) => `D:${wire.shared_link_id}`));
      const rows = await table.locator('tbody tr').evaluateAll(nodes => nodes.map(node => ({ key: node.querySelector('button')?.textContent ?? '', flits: Number((node as HTMLTableRowElement).cells[4].innerText.replaceAll(',', '')) })));
      expect(rows.length).toBeGreaterThan(10);
      const sharedRows = rows.filter(row => row.key.startsWith('D:'));
      expect(sharedRows.length).toBeGreaterThan(0);
      expect(sharedRows.every(row => wireIds.has(row.key))).toBe(true);
      const attributed = await sweep.innerText();
      expect(attributed).toContain('Rejected rows\n0');
      // The projection must agree with the simulator's own counters, not just look plausible.
      const panel = page.locator('aside').filter({ hasText: 'Flits by join class' }).last();
      const number = async (testId: string) => Number(((await panel.getByTestId(testId).innerText()).match(/[\d,]+/) ?? ['0'])[0].replaceAll(',', ''));
      const measuredD = await number('attrib-joined');
      const measuredC = await number('attrib-joined-not');
      const sweepPlane = async (plane: string) => {
        await sweep.getByLabel('sweep native plane').selectOption(plane);
        await sweep.getByRole('button', { name: 'Sweep shared resources', exact: true }).click();
        await expect(sweep.getByRole('table', { name: 'Shared resource attribution' })).toBeVisible();
        return sweep.getByRole('table', { name: 'Shared resource attribution' }).locator('tbody tr').evaluateAll(nodes => nodes.reduce((sum, node) => sum + Number((node as HTMLTableRowElement).cells[4].innerText.replaceAll(',', '')), 0));
      };
      expect(measuredD).toBeGreaterThan(0);
      expect(measuredC).toBeGreaterThan(0);
      expect(await sweepPlane('0')).toBe(measuredD);
      expect(await sweepPlane('1')).toBe(measuredC);
      await sweep.getByLabel('sweep native plane').selectOption('all');
      const matrix = page.getByRole('group', { name: /Measured flits per window for the top/ });
      const viewbox = (await matrix.getAttribute('viewBox'))!.split(' ').map(Number);
      expect(viewbox[2]).toBeLessThan(2000);
      await page.screenshot({ path: 'test-results/srota-observed-and-channel-activity.png', fullPage: true });
    }
    await page.goto('/#/analysis/metrics');
    await expect(page.getByText('completion_cycles', { exact: true }).first()).toBeVisible();
    if (scenario.prefix === 'Flow test 02') {
      const run = await (await request.get(`/gw/api/v1/runs/${latest.run_id}`)).json();
      const dram = run.analyses.find((analysis: any) => analysis.question === 'DRAM_TIMING');
      expect(dram.status).toBe('EVALUATED');
      expect(dram.normalized_metrics.some((metric: any) => metric.key === 'average_read_latency_cycles' && typeof metric.value === 'number')).toBe(true);
    }
    const tabs = page.getByRole('tablist', { name: 'Analysis sections' });
    await expect(tabs).toBeVisible();
    const labels = await tabs.getByRole('tab').allTextContents();
    for (const label of labels) {
      await tabs.getByRole('tab', { name: label, exact: true }).click();
      await expect(tabs.getByRole('tab', { name: label, exact: true })).toHaveAttribute('aria-selected', 'true');
    }
    await page.reload();
    await expect(page.getByRole('tablist', { name: 'Analysis sections' })).toBeVisible();
  }
  await page.screenshot({ path: `test-results/${scenario.prefix.replaceAll(' ', '-')}.png`, fullPage: true });
  expect(errors).toEqual([]);
});
