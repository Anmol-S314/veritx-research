import { expect, test, type Page } from '@playwright/test';

const REQUEST = {
  schema_version: 4,
  topology: { kind: 'mesh', side_length: 2, concentration: 1 },
  agents: [{ kind: 'compute_tile', count: 4, data_width: 128, protocol: 'AXI' }],
  workload: {
    model_name: 'traffic-class-fixture', tp: 2,
    collectives: [
      { kind: 'allreduce', dimension: 'TP', payload_bytes: 4096, traffic_class: 'tp_collective', source_rank: null },
      { kind: 'alltoall', dimension: 'EP', payload_bytes: 2048, traffic_class: 'ep_dispatch', source_rank: null },
    ],
  },
  requirements: [{ traffic_class: 'tp_collective', qos_class: 'latency_critical', binding: false, latency_ceiling_cycles: 50000 }],
  dependencies: [],
  address_map: { ranges: [] },
};

const PROJECT = {
  project: { project_id: 'tc-project', name: 'Traffic class fixture', created_at: '2026-01-01', updated_at: '2026-01-01' },
  active_revision_id: 'tc-r01',
  active_revision: { revision_id: 'tc-r01', display_name: 'r01', design: REQUEST },
  revisions: [{ revision_id: 'tc-r01', display_name: 'r01', design: REQUEST }],
  runs: [],
  optimizations: [],
};

const CAPABILITIES = {
  guided_parameters: [{ name: 'link_width', kind: 'int', executable: true, qualified_for_certified_optimization: true }],
  federated_metrics: [
    { metric: 'system_makespan_cycles', question: 'SYSTEM_MAKESPAN', optimization_eligible: true, dimensions: [] },
    { metric: 'flits_injected', question: 'NETWORK_COMPLETION', optimization_eligible: true, dimensions: ['traffic_class'] },
    { metric: 'packet_latency_avg', question: 'NETWORK_COMPLETION', optimization_eligible: true, unit: 'cycles', dimensions: ['traffic_class'] },
  ],
};

async function backend(page: Page) {
  const calls: { posts: { path: string; body: any }[] } = { posts: [] };
  await page.route('**/gw/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/gw/api/v1', '');
    const method = route.request().method();
    if (method === 'POST') calls.posts.push({ path, body: route.request().postDataJSON() });
    let json: any;
    if (path === '/health') json = { status: 'ok', backends: {} };
    else if (path === '/projects') json = { projects: [PROJECT] };
    else if (path === '/projects/tc-project') json = PROJECT;
    else if (path === '/projects/tc-project/draft') json = { request: REQUEST, design_hash: 'draft-hash', dirty: false };
    else if (path === '/optimization/capabilities') json = CAPABILITIES;
    else if (path.endsWith('/optimize')) json = { job_id: 'study-job', project_id: 'tc-project', state: 'QUEUED' };
    else if (path === '/jobs/study-job') json = { job_id: 'study-job', project_id: 'tc-project', kind: 'OPTIMIZATION', state: 'COMPLETED', result: { optimization_id: 'opt-tc' } };
    else if (path === '/optimizations/opt-tc') json = {
      contract_version: 1,
      optimization_id: 'opt-tc',
      project_id: 'tc-project',
      base_revision_id: 'tc-r01',
      definition: {
        objectives: [{ metric: 'flits_injected', direction: 'MIN', question: 'NETWORK_COMPLETION', traffic_class: 'tp_collective' }],
        constraints: [{ metric: 'flits_injected', op: '<=', threshold: 100, traffic_class: 'ep_dispatch' }],
      },
      study: {
        contract_version: 2,
        definition: {
          objectives: [{ metric: 'flits_injected', direction: 'MIN', question: 'NETWORK_COMPLETION', traffic_class: 'tp_collective', key: 'axis-objective' }],
          constraints: [{ metric: 'flits_injected', op: '<=', threshold: 100, traffic_class: 'ep_dispatch', key: 'axis-constraint' }],
        },
        candidates: [{
          candidate_id: 'cand-tc',
          guided_patch: { link_width: 64 },
          evaluation_status: 'EVALUATED',
          evaluation_authority: 'certified-backend',
          compilation_status: 'COMPILED',
          pareto_eligible: true,
          pareto_member: true,
          objective_values: { 'axis-objective': 123, completion_cycles: 900 },
          objective_availability: { 'axis-objective': 'MEASURED', completion_cycles: 'MEASURED' },
          constraint_verdicts: { 'axis-constraint': 'SATISFIED' },
          constraint_details: [{ metric: 'flits_injected', traffic_class: 'ep_dispatch', measured: 8, required: 100, verdict: 'SATISFIED' }],
        }],
        pareto_ids: ['cand-tc'],
        selected_candidate_id: 'cand-tc',
      },
    };
    else if (path === '/projects/tc-project/jobs') json = { jobs: [{ job_id: 'catalog-job', kind: 'CATALOG_EVALUATION' }] };
    else if (path === '/projects/tc-project/catalog-evaluation-plan') json = {
      draft_design_hash: 'draft-hash', workload_id: 'fixture', participant_count: 4, operation_count: 2, compute_stages: 0,
      topologies: [{ topology_id: 'mesh2', label: 'Mesh 2x2', topology: { kind: 'mesh', side_length: 2 }, reason: null }],
      selection: null, backends: ['BOOKSIM_STANDALONE', 'ASTRA2_EMBEDDED_BOOKSIM'],
    };
    else if (path === '/projects/tc-project/catalog-evaluations/catalog-job') json = {
      job: { job_id: 'catalog-job', project_id: 'tc-project', kind: 'CATALOG_EVALUATION', state: 'COMPLETED', cancellable: false },
      workload_id: 'fixture', participant_count: 4, operation_count: 2, compute_stages: 0, stale: false, selection: null, artifacts: [],
      rows: [{
        topology_id: 'mesh2', label: 'Mesh 2x2', topology: { kind: 'mesh', side_length: 2 }, attempt: 1, status: 'EVALUATED',
        candidate_id: 'cand-catalog', selectable: true, requirements_pass: true, objective_values: { completion_cycles: 900 },
        analyses: [
          {
            question: 'NETWORK_COMPLETION', backend_id: 'BOOKSIM_STANDALONE', status: 'EVALUATED',
            normalized_metrics: [
              { key: 'completion_cycles', value: 900, unit: 'cycles', dimensions: [] },
              { key: 'packet_latency_avg', value: 12, unit: 'cycles', dimensions: [] },
              { key: 'flits_injected', value: 10, unit: 'flits', dimensions: [['traffic_class', 'tp_collective']] },
              { key: 'flits_injected', value: 3, unit: 'flits', dimensions: [['traffic_class', 'ep_dispatch']] },
              { key: 'packet_latency_avg', value: 14, unit: 'cycles', dimensions: [['traffic_class', 'tp_collective']] },
              { key: 'packet_latency_avg', value: 8, unit: 'cycles', dimensions: [['traffic_class', 'ep_dispatch']] },
              { key: 'packets_received', value: 20, unit: 'packets', dimensions: [['traffic_class', 'tp_collective']] },
              { key: 'packets_received', value: 6, unit: 'packets', dimensions: [['traffic_class', 'ep_dispatch']] },
            ],
          },
          {
            question: 'SYSTEM_MAKESPAN', backend_id: 'ASTRA2_EMBEDDED_BOOKSIM', status: 'EVALUATED',
            normalized_metrics: [
              { key: 'system_makespan_cycles', value: 1500, unit: 'cycles', dimensions: [] },
              { key: 'compute_cycles', value: 600, unit: 'cycles', dimensions: [] },
              { key: 'completion_cycles', value: 450, unit: 'cycles', dimensions: [['traffic_class', 'tp_collective']] },
              { key: 'completion_cycles', value: 300, unit: 'cycles', dimensions: [['traffic_class', 'ep_dispatch']] },
            ],
          },
        ],
      }],
    };
    else if (/^\/revisions\/.*\/(topology|compile-result)$/.test(path)) return route.fulfill({ status: 404, json: { detail: 'not needed by this fixture' } });
    else return route.fulfill({ status: 404, json: { detail: `Unstubbed ${method} ${path}` } });
    await route.fulfill({ json });
  });
  await page.goto('/#/shared/projects');
  await page.getByRole('button', { name: 'Load', exact: true }).first().click();
  return calls;
}

test('a bounded study sends the chosen traffic class and renders class-scoped results', async ({ page }) => {
  const calls = await backend(page);
  await page.evaluate(() => { location.hash = '/explore/brief'; });
  await page.getByRole('button', { name: /Bounded study/ }).click();

  await page.getByLabel('Study objective').selectOption('flits_injected');
  const objectiveClass = page.getByLabel('Objective traffic class');
  await expect(objectiveClass).toBeVisible();
  await expect(objectiveClass.locator('option')).toHaveCount(3); // aggregate, ep_dispatch, tp_collective
  await objectiveClass.selectOption('tp_collective');

  await page.getByRole('button', { name: '+ Add constraint', exact: true }).click();
  await page.getByLabel('Constraint 1 metric').selectOption('flits_injected');
  const constraintClass = page.getByLabel('Constraint 1 traffic class');
  await expect(constraintClass).toBeVisible();
  await constraintClass.selectOption('ep_dispatch');
  await page.getByLabel('Constraint 1 threshold').fill('100');

  await page.getByRole('checkbox', { name: /Approve this revision, objective/ }).check();
  await page.getByRole('button', { name: 'Launch bounded study', exact: true }).click();
  await expect.poll(() => calls.posts.filter(post => post.path.endsWith('/optimize')).length).toBe(1);
  expect(calls.posts.find(post => post.path.endsWith('/optimize'))!.body).toMatchObject({
    objectives: [{ metric: 'flits_injected', direction: 'MIN', question: 'NETWORK_COMPLETION', traffic_class: 'tp_collective' }],
    constraints: [{ metric: 'flits_injected', op: '<=', threshold: 100, traffic_class: 'ep_dispatch' }],
  });

  await expect(page.getByRole('heading', { name: 'Class-scoped study results', exact: true })).toBeVisible();
  await expect(page.getByText('flits_injected · tp_collective', { exact: true })).toBeVisible();
  await expect(page.getByText('123', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('flits_injected · ep_dispatch verdict', { exact: true })).toBeVisible();
  await expect(page.getByText('SATISFIED', { exact: true })).toBeVisible();
  await expect(page.getByText('8 measured / 100 required', { exact: true })).toBeVisible();
  await expect(page.getByText(/@traffic_class=/)).toHaveCount(0);
});

test('catalog inspector immediately shows every aggregate and pivoted class metric', async ({ page }) => {
  await backend(page);
  await page.evaluate(() => { location.hash = '/flow/compare'; });
  await expect(page.getByRole('heading', { name: 'Fabric comparison', exact: true })).toBeVisible();
  const table = page.locator('table.catalog-results-table');
  await expect(table.locator('details, pre, a')).toHaveCount(0);
  await expect(table).not.toContainText(/Per traffic class|tp_collective|ep_dispatch|flits injected/);
  await table.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /^Mesh 2x2\b/ }) }).getByRole('button', { name: /^Inspect/, exact: false }).click();
  const review = page.locator('.catalog-inspector');
  await expect(review).toHaveCount(1);
  await expect(review).toHaveAttribute('aria-label', 'Mesh 2x2 fabric details');
  await expect(review.locator('header').getByRole('heading', { name: 'Mesh 2x2', exact: true })).toBeVisible();
  await expect(review.getByRole('tab', { name: 'Measurements', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(review.locator('details')).toHaveCount(0);
  const classes = review.getByRole('table').filter({ has: page.getByRole('columnheader', { name: 'tp_collective', exact: true }) });
  await expect(classes).toHaveCount(2);
  for (const pivot of await classes.all()) {
    await expect(pivot).toBeVisible();
    await expect(pivot.getByRole('columnheader')).toHaveText(['Metric', 'ep_dispatch', 'tp_collective']);
  }
  for (const [metric, ep, tp] of [
    ['flits injected', '3 flits', '10 flits'],
    ['packet latency avg', '8 cycles', '14 cycles'],
    ['packets received', '6 packets', '20 packets'],
    ['completion cycles', '300 cycles', '450 cycles'],
  ]) {
    const row = classes.getByRole('row').filter({ has: page.getByRole('rowheader', { name: metric, exact: true }) });
    await expect(row).toBeVisible();
    await expect(row.locator('th, td')).toHaveText([metric, ep, tp]);
  }
  const aggregate = review.getByRole('table').filter({ has: page.getByRole('columnheader', { name: 'Value', exact: true }) });
  for (const [metric, value] of [['completion cycles', '900'], ['packet latency avg', '12'], ['system makespan cycles', '1,500'], ['compute cycles', '600']]) {
    const row = aggregate.getByRole('row').filter({ has: page.getByRole('rowheader', { name: metric, exact: true }) });
    await expect(row).toBeVisible();
    await expect(row.locator('th, td')).toHaveText([metric, value, 'cycles']);
  }
  await expect(table.getByText('900', { exact: true })).toBeVisible();
  await expect(table.locator('td.numeric').first()).toContainText('cycles');
  await expect(table.locator('details, pre, a')).toHaveCount(0);
  await expect(table).not.toContainText(/tp_collective|ep_dispatch|flits injected/);
});
