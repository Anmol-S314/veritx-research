import { describe, expect, it } from 'vitest';
import { NAV_GROUPS, navHref, resolveNav } from '../App';
import { LOOM_VIEWS } from '../pages/loom/data';
import { parseRoute } from '../router';

const existingSections = [
  'overview', 'design', 'compile', 'evaluate', 'loom', 'runs',
  'performance', 'serving', 'optimize', 'synthesize', 'candidates',
  'compare', 'agents', 'verification', 'evidence', 'reproduce',
  'capabilities', 'validation', 'implementation', 'trust',
];

describe('workspace navigation contract', () => {
  it('keeps all existing destinations and gives Loom views a findable home', () => {
    expect(NAV_GROUPS.map((group) => group.label)).toEqual([
      'Architecture', 'Microarchitecture', 'Experiments', 'Implementation', 'Evidence',
    ]);
    const items = NAV_GROUPS.flatMap((group) => group.items);
    expect(new Set(items.map((item) => item.section))).toEqual(new Set(existingSections));
    const paths = items.map((item) => navHref(item, 'project-1'));
    expect(new Set(paths).size).toBe(paths.length);
    const loomDetails = items.filter((item) => item.section === 'loom').map((item) => item.detail);
    expect(new Set(loomDetails)).toEqual(new Set(LOOM_VIEWS.map((view) => view.id)));
    for (const section of existingSections) {
      expect(resolveNav(section)?.section).toBe(section);
      expect(parseRoute(`/projects/project-1/${section}`)).toMatchObject({
        kind: 'project', projectId: 'project-1', section,
      });
    }
  });

  it('links each workspace to its actual object or artifact, not just a heading', () => {
    const group = (name: string) => NAV_GROUPS.find((g) => g.label === name)!.items;
    expect(group('Architecture').some((item) => item.detail === 'graph')).toBe(true);
    expect(group('Architecture').some((item) => item.detail === 'access')).toBe(true);
    expect(group('Microarchitecture').some((item) => navHref(item, 'p') === '/projects/p/design/fabric')).toBe(true);
    expect(group('Microarchitecture').some((item) => navHref(item, 'p') === '/projects/p/design/goals')).toBe(true);
    expect(group('Experiments').some((item) => item.detail === 'simulation')).toBe(true);
    expect(group('Implementation').some((item) => item.detail === 'floorplan')).toBe(true);
    expect(group('Evidence').some((item) => item.section === 'capabilities')).toBe(true);
    expect(navHref({ section: 'runs', label: 'Runs' }, '')).toBe('/runs');
    expect(navHref({ section: 'design', label: 'Design' }, '')).toBeNull();
  });

  it('keeps route aliases and global Runs/Trust routes available', () => {
    expect(resolveNav('simulate')?.section).toBe('evaluate');
    expect(resolveNav('decide')?.section).toBe('compare');
    expect(resolveNav('verify')?.section).toBe('verification');
    expect(parseRoute('/runs')).toEqual({ kind: 'runs' });
    expect(parseRoute('/trust')).toEqual({ kind: 'trust' });
  });
});
