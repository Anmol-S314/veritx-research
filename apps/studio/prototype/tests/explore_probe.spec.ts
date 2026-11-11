import { test } from '@playwright/test';

const VIEWS = [
  ['explore/fabric-search', 'fabric search'],
  ['explore/ablations', 'workload ablations'],
  ['explore/fabric-ablations', 'fabric ablations'],
  ['explore/brief', 'brief'],
  ['explore/results', 'results'],
] as const;

for (const [route, label] of VIEWS) {
  test(`explore ${label}`, async ({ page }) => {
    const bad: string[] = [];
    const errs: string[] = [];
    page.on('response', r => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '').slice(0, 70)}`); });
    page.on('pageerror', e => errs.push(String(e).slice(0, 140)));
    await page.goto(`/#/${route}`, { waitUntil: 'load' });
    await page.waitForTimeout(3000);
    const text = (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 230);
    console.log(`\n=== ${route}`);
    console.log(`TEXT: ${text}`);
    if (bad.length) console.log(`HTTP: ${[...new Set(bad)].slice(0, 4).join(' | ')}`);
    if (errs.length) console.log(`ERR: ${errs.slice(0, 2).join(' | ')}`);
  });
}
