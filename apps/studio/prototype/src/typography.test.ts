import { describe, expect, it } from 'vitest';
import analysisCharts from './analysisCharts.css?raw';
import styles from './styles.css?raw';
import fabricSearch from './fabricSearch.css?raw';

const css = [
  { name: 'styles.css', text: styles },
  { name: 'analysisCharts.css', text: analysisCharts },
  { name: 'fabricSearch.css', text: fabricSearch },
];

describe('typography contract', () => {
  it('uses one token scale plus named heading sizes across every stylesheet', () => {
    const sizes = new Set<string>();
    for (const { text } of css) {
      for (const match of text.matchAll(/font-size:\s*([^;}]+)/g)) sizes.add(match[1].trim());
    }
    expect([...sizes].sort()).toEqual([
      '13px', // root body size
      '15px', // section headings and embedded titles
      '17px', // in-page studio title
      '22px', // page title
      'calc(var(--text-lg) * 6.4)', // SVG user units, not a screen size
      'var(--text-lg)',
      'var(--text-md)',
      'var(--text-sm)',
    ]);
    expect(styles).toContain('--text-sm:11px;--text-md:13px;--text-lg:19px;');
  });

  it('uses one font family and no uppercased labels', () => {
    const families = new Set(css.flatMap(({ name, text }) => [...text.matchAll(/font-family:([^;}]+)/g)].map(match => `${name}:${match[1]}`)));
    expect([...families].sort()).toEqual(["styles.css:'IBM Plex Sans'", 'styles.css:inherit', 'styles.css:var(--font-ui)']);
    for (const { name, text } of css) {
      expect(text, name).not.toMatch(/text-transform/);
      expect(text, name).not.toMatch(/font:\s*(?:[0-9]+\s+)?[0-9.]+px/);
    }
  });
});
