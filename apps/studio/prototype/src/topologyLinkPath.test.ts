import { expect, it } from 'vitest';
import { topologyLinkPath } from './TopologyGraph';

it('separates flatfly long links from nearest-neighbour links without changing connectivity', () => {
  const a = { x: 0, y: 0 }, b = { x: 100, y: 0 }, c = { x: 200, y: 0 };
  expect(topologyLinkPath(a, b, [a, b, c])).toBe('M 0 0 L 100 0');
  expect(topologyLinkPath(a, c, [a, b, c])).toBe('M 0 0 Q 100 60 200 0');
  expect(topologyLinkPath(a, { x: 0, y: 200 }, [a, { x: 0, y: 100 }])).toContain('Q -60 100');
});
