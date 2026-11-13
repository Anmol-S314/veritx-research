import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { STORAGE_KEY } from '../src/model';

test('manual workload creation preserves prior inputs and previews real primitive semantics', async ({ page }) => {
  await page.goto('/#/workloads/library');
  await page.getByRole('button', { name: 'New local workload' }).click();
  await page.getByLabel('Workload name').fill('Manual smoke workload');
  await page.getByRole('button', { name: 'Create local working copy' }).click();
  await page.getByRole('button', { name: 'Add operation' }).click();
  await page.getByLabel('Operation identifier').fill('OP_MANUAL');
  await page.getByLabel('Requested bytes').fill('128');
  await page.getByRole('button', { name: 'Save local primitive' }).click();
  await expect(page.getByRole('button', { name: 'OP_MANUAL', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Validate and preview intent' }).click();
  await expect(page.getByRole('row').filter({ hasText: 'OP_MANUAL' })).toContainText('8 data flits');
  await expect(page.getByRole('button', { name: 'Dispatch unavailable' })).toBeDisabled();
  await page.reload();
  const data = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(data.inputArchives).toHaveLength(1);
  expect(data.inputArchives[0].operations).toHaveLength(4);
  expect(data.inputs.operations[0].bytes).toBe(128);
});

test('working requirement revisions never rewrite captured r5 assessments', async ({ page }) => {
  await page.goto('/#/workloads/requirements');
  await page.getByLabel('Proposed transaction P95 ceiling (ns)').fill('40');
  await page.getByRole('button', { name: 'Review requirement revision' }).click();
  await expect(page.getByRole('dialog')).toContainText('relaxes');
  await page.getByRole('button', { name: 'Apply working requirement revision' }).click();
  await page.goto('/#/analysis/summary');
  const criterion = page.getByRole('row').filter({ hasText: 'REQ-LAT-04' });
  await expect(criterion).toContainText('25 ns');
  await expect(criterion).toContainText('Not evaluated');
  const data = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(data.inputs.transactionLimitNs).toBe(40);
  expect(data.inputArchives[0].transactionLimitNs).toBe(25);
});

test('binding role checks and assumption edits preserve explicit operation durations', async ({ page }) => {
  await page.goto('/#/workloads/bindings');
  await page.getByRole('row').filter({ hasText: 'COMPUTE_A' }).getByRole('button', { name: 'Review rebind' }).click();
  await page.getByLabel('Bound hardware endpoint').selectOption('EP_HBM_0');
  await expect(page.getByRole('button', { name: 'Apply reviewed binding' })).toBeDisabled();
  await page.getByLabel('Bound hardware endpoint').selectOption('EP_NPU_2');
  await page.getByRole('button', { name: 'Apply reviewed binding' }).click();
  await page.goto('/#/workloads/assumptions');
  await page.getByLabel('Default compute delay (ns)').fill('1500');
  await page.getByLabel('Memory service duration (ns)').fill('60');
  await page.getByRole('button', { name: 'Review assumption change' }).click();
  await page.getByRole('button', { name: 'Apply working assumptions' }).click();
  const data = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!), STORAGE_KEY);
  expect(data.inputs.bindings.COMPUTE_A).toBe('EP_NPU_2');
  expect(data.inputs.computeDurationNs).toBe(1500);
  expect(data.inputs.memoryServiceNs).toBe(60);
  expect(data.inputs.operations.find((o: {id: string}) => o.id === 'OP_COMPUTE').durationNs).toBe(2000);
});

test('analysis basis, selected run, comparison scope, and missing-capture scenario remain distinct', async ({ page }) => {
  await page.goto('/#/analysis/matrix');
  const cell = page.getByRole('button', { name: 'Inspect traffic EP_NPU_2 to EP_HBM_1', exact: true });
  await expect(cell).toHaveText('0');
  await page.getByLabel('Matrix data basis').selectOption('injection');
  await expect(cell).toHaveText('100');
  await page.getByLabel('Matrix data basis').selectOption('requested');
  await expect(cell).toHaveText('200');
  await page.getByLabel('Selected illustrative run').selectOption('SIM-451');
  await expect(page.getByRole('heading', { name: 'Endpoint-pair matrix unavailable' })).toBeVisible();
  await page.goto('/#/analysis/metrics');
  await expect(page.getByLabel('Selected illustrative run')).toHaveValue('SIM-451');
  await expect(page.getByRole('row').filter({ hasText: 'Aggregate delivered throughput' })).toContainText('20.8 GB/s');
  await page.goto('/#/analysis/comparison');
  await expect(page.getByText(/Direct performance deltas unavailable/)).toBeVisible();
  await page.getByLabel('Comparison run').selectOption('SIM-451');
  await expect(page.getByRole('row').filter({ hasText: 'Packet P99' }).first()).toContainText('-6.2 ns');
  await page.goto('/#/analysis/missing');
  await expect(page.getByText('Alternate missing-capture scenario.', { exact: true })).toBeVisible();
});

test('trace example and evaluation-intent download do not claim recorded traces or queued execution', async ({ page }) => {
  await page.goto('/#/analysis/trace');
  await expect(page.getByRole('heading', { name: 'No captured event trace supplied' })).toBeVisible();
  await page.getByRole('button', { name: 'Open independent example trace' }).click();
  await page.getByLabel('Filter example trace').fill('HOP');
  await expect(page.getByRole('table').getByRole('row')).toHaveCount(3);
  await expect(page.getByText(/Not captured by SIM-402/)).toBeVisible();
  await page.getByRole('button', { name: 'Review evaluation setup', exact: true }).click();
  await page.getByLabel('Evaluation input source').selectOption('draft');
  await page.getByLabel('Request event/packet trace').check();
  await expect(page.getByRole('button', { name: 'Queue evaluation unavailable' })).toBeDisabled();
  const promise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export reviewed setup intent' }).click();
  const download = await promise;
  const payload = JSON.parse(await readFile((await download.path())!, 'utf8'));
  expect(payload.executable).toBe(false);
  expect(payload.inputSource).toBe('draft');
  expect(payload.currentInputs.workingInputs.sourceRevision).toBe('w12');
  expect(payload.requestedCapture.eventTrace).toBe(true);
});

test('workload ablation names the candidate arms and keeps the knob audit out of the main flow', async ({ page }) => {
  await page.goto('/#/explore/ablations');
  const arms = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Candidate arms' }) });
  const gec = arms.getByRole('row').filter({ hasText: 'GEC MECS' });
  await expect(gec).toContainText('GEC_MECS');
  await expect(gec).toContainText('6');
  await expect(gec).toContainText('k=4');

  await expect(page.getByRole('heading', { name: 'Knob provenance' })).toHaveCount(0);
  const runner = page.locator('details.runner-command');
  await expect(runner.locator('.code-preview')).toBeHidden();
  await runner.locator('summary').click();
  await expect(runner.locator('.code-preview')).toContainText('ablate_workloads.py');
  await expect(runner.locator('.code-preview')).not.toContainText('--copy-to-prototype');
});

test('curves and Pareto carry workload power, area, energy, hops and VC evidence', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#/analysis/curves');
  const analysis = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Workload analysis', exact: true }) });
  await expect(analysis).toBeVisible();
  await expect(analysis.getByText('Lowest P95 latency', { exact: true })).toBeVisible();
  await expect(analysis.getByText('Lowest modeled power', { exact: true })).toBeVisible();
  await expect(analysis.getByText('Lowest energy per packet', { exact: true })).toBeVisible();

  const workbench = analysis.locator('section').filter({ has: page.getByRole('heading', { name: 'Curves and Pareto', exact: true }) });
  await expect(workbench.getByRole('group', { name: /^Workload arm analysis:/ })).toBeVisible();
  await workbench.getByRole('button', { name: 'Power · area', exact: true }).click();
  await expect(workbench.getByRole('group', { name: /^Workload arm analysis:/ })).toContainText('Modeled area');
  await workbench.getByRole('button', { name: 'Virtual channels', exact: true }).click();
  await expect(workbench.getByLabel('Horizontal objective')).toHaveValue('vcs');

  await page.getByLabel('Reference workload').selectOption('vision_transformer');
  await expect(page.getByLabel('Reference workload')).toHaveValue('vision_transformer');

  const armData = analysis.locator('summary').filter({ hasText: 'Workload arm data' });
  await armData.click();
  await expect(analysis.getByRole('table', { name: 'Workload arm analysis' }).getByRole('row').filter({ hasText: '8×8 mesh' })).toContainText('6.34');

  await workbench.getByRole('button', { name: 'Buffer depth', exact: true }).click();
  await expect(workbench.getByLabel('Horizontal objective')).toHaveValue('depth');
  await expect(workbench.getByRole('group', { name: /^Buffer-depth sweep:/ })).toContainText('Packet P95 latency');
  const depthDetails = workbench.locator('details.plot-data');
  if (await depthDetails.evaluate(details => !(details as HTMLDetailsElement).open)) {
    await depthDetails.locator('summary').click();
  }
  await expect(workbench.getByRole('table', { name: 'Buffer depth and virtual channels' })).toBeVisible();

  const power = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Power and energy characteristics', exact: true }) });
  await expect(power.getByText('Energy per packet', { exact: true }).first()).toBeVisible();
  await expect(power.getByText('Energy per flit', { exact: true }).first()).toBeVisible();
  await expect(power.getByText('Energy per hop', { exact: true })).toBeVisible();
  await expect(power.getByText('Power–delay product', { exact: true }).first()).toBeVisible();
  await expect(power.getByRole('table', { name: 'Power composition by component' })).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Reference: power versus offered load', exact: true })).toHaveCount(0);

  expect(errors).toEqual([]);
});
