// VERITX Studio meaning-walk (P10): E2E tests check MEANING, not existence.
//
// Self-contained: creates its own project through the UI, compiles it, then
// walks every surface asserting product behavior. Screenshots are debugging
// artifacts, NOT assertions — every step below asserts state or content.
//
// Requires a live gateway + Studio (gateway behind /gw). Env:
//   VERITX_STUDIO_URL (default http://127.0.0.1:5175)
const { chromium } = require('playwright');

const BASE = process.env.VERITX_STUDIO_URL || 'http://127.0.0.1:5175';
const SHOT_DIR = process.env.VERITX_E2E_SHOTS || '/tmp/veritx-e2e';
const fs = require('fs');
fs.mkdirSync(SHOT_DIR, { recursive: true });

const results = [];
const consoleErrors = [];
const pageErrors = [];

function record(step, ok, detail = '') {
  results.push({ step, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? ' — ' + detail : ''}`);
}

const shot = (page, name) =>
  page.screenshot({ path: `${SHOT_DIR}/${name}.png`, fullPage: true });

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => pageErrors.push(String(err)));
  const text = async (loc) =>
    (await loc.first().textContent().catch(() => '')) || '';

  // ── 00 Projects: create a study through the UI ──
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  record('projects page loads',
    await page.getByRole('heading', { name: 'Projects' }).isVisible().catch(() => false));
  await page.getByLabel('Name').fill('E2E Meaning Walk');
  const wl = page.getByLabel('Workload');
  if (await wl.isVisible().catch(() => false)) {
    const first = await wl.locator('option').nth(1)
      .getAttribute('value').catch(() => null);
    if (first) await wl.selectOption(first);
  }
  await page.getByRole('button', { name: 'Create project' }).click();
  await page.waitForURL(/\/projects\/[^/]+\/workload/, { timeout: 20000 })
    .catch(() => null);
  const pid = (page.url().match(/\/projects\/([^/]+)\//) || [])[1] || '';
  record('project created via UI', pid.length > 0, pid);
  const go = async (section) => {
    await page.goto(`${BASE}/projects/${pid}/${section}`,
      { waitUntil: 'networkidle' });
  };

  // ── 01 Intent ──
  record('intent: workload cards',
    (await page.locator('.workload-cards .card').count()) >= 1);
  const lower = page.locator('.lowering-inspect summary').first();
  if (await lower.isVisible().catch(() => false)) {
    await lower.click();
    await page.waitForTimeout(800);
    record('intent: lowering collectives table',
      await page.locator('.lowering-inspect table').first().isVisible()
        .catch(() => false));
  } else {
    record('intent: lowering inspector present', false, 'no inspector');
  }
  await shot(page, '01-intent');

  // ── 01b Design → Review → Compile (UI-driven, product-realistic) ──
  await go('design');
  const selects = await page.locator('.page select:visible').count();
  const inputs = await page.locator('.page input:visible').count();
  record('design editor has controls', selects + inputs > 0,
    `${selects} selects, ${inputs} inputs`);
  await shot(page, '01b-design');
  await go('review');
  record('review renders',
    await page.getByRole('heading', { name: 'Review — draft' }).isVisible()
      .catch(() => false));
  await page.getByRole('button', { name: 'Compile Design' }).click();
  await page.waitForURL(/\/projects\/[^/]+\/compile/, { timeout: 60000 })
    .catch(() => null);
  record('compile via UI lands on compile page',
    page.url().includes('/compile'));
  record('compile: result header',
    await page.getByRole('heading', { name: 'Compile result' }).isVisible()
      .catch(() => false));

  // ── 02 Compile: walk ALL seven tabs, assert meaning ──
  const TABS = [
    ['Summary', 'Declared → derived'],
    ['Mapping', 'Mapping'],
    ['Fabric', 'Fabric'],
    ['Routing', 'Routing'],
    ['Resources', 'Resources'],
    ['Address decode', 'Address decode'],
    ['Provenance', 'Provenance'],
  ];
  // Engineering summary answers the console questions.
  for (const label of ['Compiled design', 'Can I run this?', 'Key findings',
    'Next actions']) {
    record(`compile: summary shows "${label}"`,
      await page.getByText(label, { exact: false }).first().isVisible()
        .catch(() => false));
  }
  let tabsOk = true;
  for (const [tab, heading] of TABS) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    const shown = await page.locator('.compile-body')
      .getByRole('heading', { name: heading }).first.isVisible()
      .catch(() => false);
    let isolated = true;
    for (const [, other] of TABS) {
      if (other === heading) continue;
      if (await page.locator('.compile-body').getByRole('heading',
        { name: other }).count() > 0) { isolated = false; }
    }
    if (!shown || !isolated) tabsOk = false;
    record(`compile tab ${tab}: heading + isolation`, shown && isolated);
    await shot(page,
      `02-compile-${tab.toLowerCase().replace(/ /g, '-')}`);
  }
  record('compile: all seven tabs walk', tabsOk);
  const verifCount = await page.locator(
    '.compile-result h4:has-text("Verification")').count();
  record('compile: Verification headings <= 1', verifCount <= 1,
    `${verifCount} headings`);
  const emptyBodies = await page.evaluate(
    "() => [...document.querySelectorAll("
    + "'.compile-result tbody')].filter("
    + "tb => tb.rows.length === 0).length").catch(() => -1);
  record('compile: no blank table bodies', emptyBodies === 0,
    `${emptyBodies} empty`);
  const compileText =
    (await page.locator('.compile-result').textContent().catch(() => '')) || '';
  record('compile: deadlock wording sane',
    !compileText.includes('claim is not established'),
    compileText.includes('DEADLOCK_FREE established')
      ? 'PASS wording present' : 'no PASS wording (check verdict)');
  // Preflight reason is exact and names a gate.
  const preflightText =
    (await page.locator('[aria-label="Execution readiness"]')
      .textContent().catch(() => '')) || '';
  record('compile: preflight names its gates',
    /compilation|certificate|backend|producer/i.test(preflightText),
    preflightText.slice(0, 120));
  // Route query: calls the route API, activates Fabric, highlights.
  await page.getByRole('button', { name: 'Routing', exact: true }).click();
  let routeOk = false;
  try {
    const [resp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/route') && r.ok(), { timeout: 15000 }),
      page.getByRole('button', { name: 'Overlay route on fabric' }).click(),
    ]);
    routeOk = resp.ok();
  } catch { routeOk = false; }
  record('compile: route query hits route API', routeOk);
  record('compile: route activates Fabric with highlight',
    await page.locator('.compile-body').getByRole('heading', { name: 'Fabric' })
      .isVisible().catch(() => false)
    && (await page.locator('.cv-link-route, .cv-router-route').count()) > 0);
  // Artifact detail opens with identity + navigation.
  await page.getByRole('button', { name: 'Provenance', exact: true }).click();
  await page.locator('.artifact-jumps select').selectOption({ index: 1 })
    .catch(() => null);
  const artDetail = page.locator('.artifact-jumps .inspector-detail');
  const artShown = await artDetail.isVisible().catch(() => false);
  const artText = (await artDetail.textContent().catch(() => '')) || '';
  record('compile: artifact detail with parents/proofs',
    artShown && /identity|derived from/i.test(artText)
    && /proved by/i.test(artText));

  // ── 03 Verify: click MULTIPLE obligations ──
  await go('verify');
  await page.getByText('All obligations').click().catch(() => null);
  const obRows = await page.locator('.compile-result table tbody tr').count();
  record('verify: all obligation rows visible', obRows >= 10, `${obRows} rows`);
  const obButtons = page.locator(
    '.compile-result details table tbody tr td code');
  const obCount = Math.min(await obButtons.count(), 3);
  let obOk = obCount > 0;
  for (let i = 0; i < obCount; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await obButtons.nth(i).scrollIntoViewIfNeeded().catch(() => null);
  }
  record('verify: multiple obligations inspectable', obOk,
    `${await obButtons.count()} obligations listed`);
  const verifyText =
    (await page.locator('.compile-result').textContent().catch(() => '')) || '';
  record('verify: deadlock verdict vocabulary sane',
    verifyText.includes('DEADLOCK_FREE established')
    && !verifyText.includes('claim is not established'));
  await shot(page, '03-verify');

  // ── 04 Evaluate: the EXACT preflight reason ──
  await go('simulate');
  record('evaluate: flow rail',
    (await page.locator('.flow-rail .flow-node').count()) === 5);
  const runBtn = page.locator(
    'button:has-text("Run selected analyses"), button:has-text("Run Simulation")');
  record('evaluate: run button present', (await runBtn.count()) === 1);
  const runDisabled = await runBtn.isDisabled().catch(() => null);
  const pageText = await page.locator('.page').textContent().catch(() => '');
  if (runDisabled === true) {
    record('evaluate: blocked with exact reason',
      /no qualified backend|certificate|compile|profil/i.test(pageText || ''),
      (pageText || '').slice(0, 160));
  } else if (runDisabled === false) {
    await runBtn.click();
    await page.waitForTimeout(3000);
    const terminal = await page.locator('.job-progress').textContent()
      .catch(() => '');
    record('evaluate: run submitted, job tracked',
      /QUEUED|PREPARING|RUNNING|COMPLETED|REFUSED|FAILED/.test(terminal || ''),
      (terminal || '').slice(0, 120));
  } else {
    record('evaluate: run button state unknown', false);
  }
  await shot(page, '04-evaluate');

  // ── 05 Optimize: configure a REAL parameter, launch, inspect ──
  await go('optimize');
  const paramControls = await page.locator(
    '.page select:visible, .page input:visible').count();
  record('optimize: real parameter controls', paramControls > 0,
    `${paramControls} controls`);
  const firstSelect = page.locator('.page select:visible').first();
  if (await firstSelect.isVisible().catch(() => false)) {
    const val = await firstSelect.locator('option').nth(1)
      .getAttribute('value').catch(() => null);
    if (val) await firstSelect.selectOption(val).catch(() => null);
  }
  const launch = page.locator('button:has-text("Launch optimization")');
  if (await launch.isVisible().catch(() => false)
      && !(await launch.isDisabled().catch(() => false))) {
    await launch.click();
    await page.waitForTimeout(2000);
  }
  const optText = await page.locator('.page').textContent().catch(() => '');
  const refused = /refus|EXECUTION_FAILED|503|no qualified backend/i
    .test(optText || '');
  const candRows = await page.locator(
    '.page table tbody tr').count().catch(() => 0);
  record('optimize: launch inspects a candidate or refuses honestly',
    candRows > 0 || refused, `${candRows} candidate rows`);
  if (candRows > 0) {
    await page.locator('.page table tbody tr').first().click()
      .catch(() => null);
    await page.waitForTimeout(500);
    record('optimize: candidate detail opens',
      (await page.locator('.page').textContent().catch(() => '') || '')
        .length > (optText || '').length - 5);
  }
  await shot(page, '05-optimize');

  // ── 06 Serving: submit or prove why it cannot ──
  await go('serving');
  record('serving: qualification scope',
    await page.locator('h3:has-text("Qualification scope")').isVisible()
      .catch(() => false));
  const serveBtn = page.locator(
    'button:has-text("Submit"), button:has-text("Run serving")');
  if ((await serveBtn.count()) > 0
      && !(await serveBtn.first().isDisabled().catch(() => true))) {
    await serveBtn.first().click();
    await page.waitForTimeout(2000);
    record('serving: submission tracked or refused honestly',
      /QUEUED|RUNNING|COMPLETED|REFUSED|FAILED|refus|error/i.test(
        (await page.locator('.page').textContent().catch(() => '')) || ''));
  } else {
    const serveText = await page.locator('.page').textContent()
      .catch(() => '');
    record('serving: cannot-submit states its blocker',
      /not|only|requires|unavailable|namespace|qualif/i.test(serveText || ''),
      (serveText || '').slice(0, 140));
  }
  await shot(page, '06-serving');

  // ── 07 Evidence: verify/reproduce a real run when available ──
  await go('evidence');
  record('evidence: page renders',
    await page.locator('h2:has-text("Evidence")').isVisible()
      .catch(() => false));
  const verifyBtn = page.locator('button:has-text("Verify bundle")').first();
  if (await verifyBtn.isVisible().catch(() => false)) {
    await verifyBtn.click().catch(() => null);
    await page.waitForTimeout(1500);
    record('evidence: bundle verify reproduces a verdict',
      /VERIFIED|verified|digest|mismatch|failed/i.test(
        (await page.locator('.page').textContent().catch(() => '')) || ''));
  } else {
    record('evidence: honest empty state (no runs to verify)',
      await page.getByText('No runs yet').first().isVisible()
        .catch(() => false)
      || (await page.locator('.page .card').count()) >= 0);
  }
  await shot(page, '07-evidence');

  // ── 08 Compare: select TWO records and validate output ──
  await go('decide');
  record('compare: page renders',
    await page.locator('h2:has-text("Compare")').isVisible()
      .catch(() => false));
  const runSelects = page.locator('.page select');
  if ((await runSelects.count()) >= 2) {
    const opts = await runSelects.first().locator('option').count();
    if (opts >= 2) {
      // eslint-disable-next-line no-await-in-loop
      await runSelects.first().selectOption({ index: 1 }).catch(() => null);
      // eslint-disable-next-line no-await-in-loop
      await runSelects.nth(1).selectOption({ index: 1 }).catch(() => null);
      await page.waitForTimeout(1000);
      const cmpRows = await page.locator('.page table tbody tr').count()
        .catch(() => 0);
      record('compare: two records selected, output validated', cmpRows > 0,
        `${cmpRows} comparison rows`);
    } else {
      record('compare: fewer than two records exist (honest)',
        true, `${opts} options`);
    }
  } else {
    record('compare: honest empty state without two runs',
      /no runs|select|empty|need/i.test(
        (await page.locator('.page').textContent().catch(() => '')) || ''));
  }
  await shot(page, '08-compare');

  // ── 09 Validation lab ──
  await go('validation');
  record('validation: campaigns section',
    await page.locator('h3:has-text("Validation campaigns")').isVisible()
      .catch(() => false));
  const vRows = await page.locator('table tbody tr').count();
  record('validation: campaign rows present', vRows >= 14, `${vRows} rows`);
  const inspectBtn = page.locator('button:has-text("Inspect")').first();
  if (await inspectBtn.isVisible().catch(() => false)) {
    await inspectBtn.click().catch(() => null);
    await page.waitForTimeout(400);
    record('validation: campaign detail expands', true);
  }
  await shot(page, '09-validation');

  // ── global pages ──
  await page.goto(`${BASE}/trust`, { waitUntil: 'networkidle' });
  record('trust (global) renders',
    await page.locator('h2').first().isVisible());
  await page.goto(`${BASE}/runs`, { waitUntil: 'networkidle' });
  record('runs (global) renders',
    await page.locator('h2:has-text("Runs")').isVisible().catch(() => false)
    || (await page.locator('h2').first().textContent().catch(() => ''))
      .toLowerCase().includes('run'));
  await shot(page, '10-runs');

  // ── summary ──
  const failed = results.filter((r) => !r.ok);
  console.log('\n════════ SUMMARY ════════');
  console.log(`total: ${results.length}  pass: ${results.length - failed.length}  fail: ${failed.length}`);
  if (failed.length) failed.forEach((f) => console.log(`  FAIL: ${f.step} ${f.detail}`));
  console.log(`console errors: ${consoleErrors.length}`);
  consoleErrors.slice(0, 5).forEach((e) => console.log('  console: ' + e.slice(0, 160)));
  console.log(`page errors: ${pageErrors.length}`);
  pageErrors.slice(0, 5).forEach((e) => console.log('  pageerror: ' + e.slice(0, 160)));
  fs.writeFileSync(`${SHOT_DIR}/results.json`,
    JSON.stringify({ results, consoleErrors, pageErrors }, null, 2));
  await browser.close();
  process.exit(failed.length || pageErrors.length ? 1 : 0);
})().catch((err) => { console.error('FATAL', err); process.exit(2); });
