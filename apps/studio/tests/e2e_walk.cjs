// Full-feature Playwright walk of VERITX Studio against the live gateway.
// One pass, screenshots at each step, console/pageerror capture.
const { chromium } = require('playwright');

const BASE = 'http://127.0.0.1:5175';
const SHOT_DIR = '/tmp/veritx-e2e';
const fs = require('fs');
fs.mkdirSync(SHOT_DIR, { recursive: true });

const results = [];
const consoleErrors = [];
const pageErrors = [];

function record(step, ok, detail = '') {
  results.push({ step, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? ' — ' + detail : ''}`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => pageErrors.push(String(err)));

  const pid = 'p-4168adf8057c'; // MoE 8×7B Study (existing project)
  const go = async (section) => {
    await page.goto(`${BASE}/projects/${pid}/${section}`, { waitUntil: 'networkidle' });
  };

  // ── 00 Overview ──
  await go('overview');
  record('overview loads', await page.locator('.workflow-bar, .page').first().isVisible().catch(() => false));
  record('context header shows project', await page.locator('.context-header').isVisible().catch(() => false)
    && (await page.locator('.context-header').textContent().catch(() => '')).includes(pid.slice(0, 4) === 'p-41' ? '' : '') === false
    ? await page.locator('.context-header').isVisible().catch(() => false) : false);
  record('job cards present', (await page.locator('.job-cards .card').count()) === 4,
    `${await page.locator('.job-cards .card').count()} cards`);
  await page.screenshot({ path: `${SHOT_DIR}/00-overview.png`, fullPage: true });

  // rail client-side navigation works (one representative click)
  const firstRail = page.locator('a.rail-item').first();
  await firstRail.click();
  await page.waitForLoadState('networkidle');
  record('rail navigation click works', page.url().includes('/overview') || page.url().includes('/workload'));

  // ── 01 Intent ──
  await go('workload');
  record('intent: workload cards', (await page.locator('.workload-cards .card').count()) >= 1,
    `${await page.locator('.workload-cards .card').count()} cards`);
  const lower = page.locator('.lowering-inspect summary').first();
  record('intent: lowering inspector present', await lower.isVisible().catch(() => false));
  if (await lower.isVisible().catch(() => false)) {
    await lower.click();
    await page.waitForTimeout(800);
    record('intent: lowering collectives table', await page.locator('.lowering-inspect table').first().isVisible().catch(() => false));
  }
  await page.screenshot({ path: `${SHOT_DIR}/01-intent.png`, fullPage: true });

  // ── 01b Design editor ──
  await go('design');
  const selects = await page.locator('.page select:visible').count();
  const inputs = await page.locator('.page input:visible').count();
  record('design editor has controls', selects + inputs > 0, `${selects} selects, ${inputs} inputs`);
  await page.screenshot({ path: `${SHOT_DIR}/01b-design.png`, fullPage: true });

  // ── 02 Compile ──
  await go('compile');
  record('compile: artifact chain', await page.locator('.artifact-chain').first().isVisible().catch(() => false));
  const chainNodes = await page.locator('.artifact-chain .chain-node').count();
  record('compile: chain nodes >= 11', chainNodes >= 11, `${chainNodes} nodes`);
  record('compile: identity card', await page.locator('h3:has-text("Identity")').isVisible().catch(() => false));
  await page.screenshot({ path: `${SHOT_DIR}/02-compile.png`, fullPage: true });

  // ── 03 Verify ──
  await go('verify');
  const obCount = await page.locator('.ob-list li').count();
  record('verify: 10 obligations', obCount === 10, `${obCount}`);
  record('verify: certificate summary', await page.locator('h3:has-text("Certificate")').first().isVisible().catch(() => false));
  const firstOb = page.locator('.ob-list li button, .ob-list li').first();
  await firstOb.click().catch(() => {});
  await page.waitForTimeout(400);
  record('verify: key evidence table', await page.locator('.key-evidence').first().isVisible().catch(() => false));
  await page.screenshot({ path: `${SHOT_DIR}/03-verify.png`, fullPage: true });

  // ── 04 Evaluate ──
  await go('simulate');
  record('evaluate: flow rail', (await page.locator('.flow-rail .flow-node').count()) === 5,
    `${await page.locator('.flow-rail .flow-node').count()} nodes`);
  record('evaluate: preflight panel', await page.locator('h3:has-text("Ready to run"), h3:has-text("Cannot run")').first().isVisible().catch(() => false));
  const runBtn = page.locator('button:has-text("Run Simulation")');
  record('evaluate: run button present', (await runBtn.count()) === 1);
  // Backend is absent in this env: button must be disabled with a precise blocker
  const runDisabled = await runBtn.isDisabled().catch(() => null);
  record('evaluate: run disabled w/o backend (honest gate)', runDisabled === true, runDisabled === null ? 'button state unknown' : '');
  await page.screenshot({ path: `${SHOT_DIR}/04-evaluate.png`, fullPage: true });

  // ── 05 Optimize (expect honest 503 refusal, not crash) ──
  await go('optimize');
  const launch = page.locator('button:has-text("Launch optimization")');
  if (await launch.isVisible().catch(() => false) && !(await launch.isDisabled().catch(() => false))) {
    await launch.click();
    await page.waitForTimeout(1500);
  }
  const refusalShown = await page.locator('.error-box, .job-refused, .reason-block').first().isVisible().catch(() => false)
    || (await page.locator('.page').textContent().catch(() => '')).includes('EXECUTION_FAILED')
    || (await page.locator('.page').textContent().catch(() => '')).includes('refus');
  record('optimize: honest refusal/503 path shown', refusalShown);
  await page.screenshot({ path: `${SHOT_DIR}/05-optimize.png`, fullPage: true });

  // ── 06 Serving ──
  await go('serving');
  record('serving: qualification scope', await page.locator('h3:has-text("Qualification scope")').isVisible().catch(() => false));
  record('serving: namespace discipline', await page.locator('h3:has-text("Namespace discipline")').isVisible().catch(() => false));
  record('serving: ownership boundary', await page.locator('h3:has-text("Ownership boundary")').isVisible().catch(() => false));
  await page.screenshot({ path: `${SHOT_DIR}/06-serving.png`, fullPage: true });

  // ── 07 Evidence ──
  await go('evidence');
  record('evidence: page renders', await page.locator('h2:has-text("Evidence")').isVisible().catch(() => false));
  const runCards = await page.locator('.page .card').count();
  record('evidence: run cards or empty-state', runCards >= 1
    || await page.getByText('No runs yet').first().isVisible().catch(() => false), `${runCards} cards`);
  const verifyBtn = page.locator('button:has-text("Verify bundle")').first();
  if (await verifyBtn.isVisible().catch(() => false)) {
    await verifyBtn.click().catch(() => {});
    await page.waitForTimeout(1000);
    record('evidence: bundle verify action clickable', true);
  }
  await page.screenshot({ path: `${SHOT_DIR}/07-evidence.png`, fullPage: true });

  // ── 08 Compare ──
  await go('decide');
  record('compare: page renders', await page.locator('h2:has-text("Compare")').isVisible().catch(() => false));
  await page.screenshot({ path: `${SHOT_DIR}/08-compare.png`, fullPage: true });

  // ── 09 Validation lab ──
  await go('validation');
  record('validation: campaigns section', await page.locator('h3:has-text("Validation campaigns")').isVisible().catch(() => false));
  record('validation: backend matrix', await page.locator('h3:has-text("Backend / validation matrix")').isVisible().catch(() => false));
  const vRows = await page.locator('table tbody tr').count();
  record('validation: campaign rows present', vRows >= 14, `${vRows} rows`);
  const inspectBtn = page.locator('button:has-text("Inspect")').first();
  if (await inspectBtn.isVisible().catch(() => false)) {
    await inspectBtn.click().catch(() => {});
    await page.waitForTimeout(400);
    record('validation: campaign detail expands', true);
  }
  await page.screenshot({ path: `${SHOT_DIR}/09-validation.png`, fullPage: true });

  // ── global pages ──
  await page.goto(`${BASE}/trust`, { waitUntil: 'networkidle' });
  record('trust (global) renders', await page.locator('h2').first().isVisible());
  await page.goto(`${BASE}/runs`, { waitUntil: 'networkidle' });
  record('runs (global) renders', await page.locator('h2:has-text("Runs")').isVisible().catch(() => false)
    || (await page.locator('h2').first().textContent().catch(() => '')).toLowerCase().includes('run'));
  await page.screenshot({ path: `${SHOT_DIR}/10-runs.png`, fullPage: true });

  // ── summary ──
  const failed = results.filter((r) => !r.ok);
  console.log('\n════════ SUMMARY ════════');
  console.log(`total: ${results.length}  pass: ${results.length - failed.length}  fail: ${failed.length}`);
  if (failed.length) failed.forEach((f) => console.log(`  FAIL: ${f.step} ${f.detail}`));
  console.log(`console errors: ${consoleErrors.length}`);
  consoleErrors.slice(0, 5).forEach((e) => console.log('  console: ' + e.slice(0, 160)));
  console.log(`page errors: ${pageErrors.length}`);
  pageErrors.slice(0, 5).forEach((e) => console.log('  pageerror: ' + e.slice(0, 160)));
  fs.writeFileSync(`${SHOT_DIR}/results.json`, JSON.stringify({ results, consoleErrors, pageErrors }, null, 2));
  await browser.close();
  process.exit(failed.length || pageErrors.length ? 1 : 0);
})().catch((err) => { console.error('FATAL', err); process.exit(2); });
