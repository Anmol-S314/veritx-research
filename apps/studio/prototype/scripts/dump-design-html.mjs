// Dumps each Design page's rendered markup and measures how much of it is prose.
import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

const BASE = process.env.STUDIO_URL ?? 'http://127.0.0.1:5174';
const PAGES = ['fabric-topology', 'system', 'catalog', 'endpoints', 'mapping', 'addresses', 'domains', 'placement'];
const OUT = new URL('./design-html/', import.meta.url).pathname;

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

for (const id of PAGES) {
  await page.goto(`${BASE}/#/design/${id}`);
  await page.waitForSelector('.page-content .view-main');
  await page.waitForTimeout(600);
  const html = await page.locator('.page-content').innerHTML();
  await writeFile(`${OUT}${id}.html`, html);

  const stats = await page.evaluate(() => {
    const root = document.querySelector('.page-content');
    if (!root) return null;
    const text = root.innerText.replace(/\s+/g, ' ').trim();
    const words = text.split(' ').filter(Boolean);
    const controls = root.querySelectorAll('button, a, input, select').length;
    const cells = root.querySelectorAll('td, th').length;
    const numbers = (text.match(/\d+(\.\d+)?/g) ?? []).length;
    const paragraphs = [...root.querySelectorAll('p')].map(p => p.innerText.replace(/\s+/g, ' ').trim()).filter(Boolean);
    const assumptions = root.querySelector('details');
    const assumptionText = assumptions ? assumptions.innerText.replace(/\s+/g, ' ').trim() : '';
    const longest = paragraphs.sort((a, b) => b.length - a.length).slice(0, 3);
    return { words: words.length, controls, cells, numbers, paragraphs: paragraphs.length, assumptionWords: assumptionText.split(' ').filter(Boolean).length, longest };
  });
  console.log(JSON.stringify({ id, ...stats }));
}
await browser.close();

// A static gallery that renders the captured markup through the real stylesheet,
// so the HTML can be reviewed without a running app.
const titles = { 'fabric-topology': 'Fabric Topology', system: 'System / Block Diagram', catalog: 'IP Catalog', endpoints: 'Hardware Endpoints', mapping: 'Initiator–Target Mapping', addresses: 'Address Map', domains: 'Clock & Power Domains', placement: 'Placement Constraints' };
const sections = [];
for (const id of PAGES) {
  const fragment = await readFile(`${OUT}${id}.html`, 'utf8');
  sections.push(`<section class="snapshot">
  <h2>${titles[id]} <code>#/design/${id}</code></h2>
  <div class="snapshot-frame"><div class="page-content">${fragment}</div></div>
</section>`);
}
const gallery = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Design pages — captured markup</title>
<link rel="stylesheet" href="/src/styles.css">
<style>
body{background:#dde4ea;margin:0;padding:20px;font-family:var(--font, system-ui)}
.snapshot{margin:0 0 28px}
.snapshot>h2{font:600 14px/1.4 system-ui;margin:0 0 8px;color:#1d242c}
.snapshot>h2 code{font-weight:500;color:#536170}
.snapshot-frame{background:var(--ground,#f2f4f6);border:1px solid #aebbc7;box-shadow:0 10px 30px #16283a26}
.snapshot .workspace-shell{height:auto!important;display:block!important}
.snapshot .workspace{height:auto!important;overflow:visible!important;display:block!important;max-width:none!important}
.snapshot .page-content{height:auto!important;overflow:visible!important;display:block!important}
.snapshot .view-layout{height:auto!important;display:block!important;grid-template-columns:minmax(0,1fr)!important}
.snapshot .view-main{height:auto!important;overflow:visible!important}
.snapshot .inspector{position:static!important;display:block!important;width:auto!important;max-height:none!important;margin:12px 0 0!important;box-shadow:none!important}
.snapshot .inspector-close{display:none!important}
</style>
</head><body>${sections.join('\n')}</body></html>`;
await writeFile(new URL('../public/design-pages.html', import.meta.url).pathname, gallery);
console.log('gallery: /design-pages.html');
