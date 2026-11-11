import { beforeEach, describe, expect, it, vi } from 'vitest';

const route = vi.hoisted(() => vi.fn());

vi.mock('../../api', () => ({ api: { route } }));

import {
  ROUTE_SWEEP_CONCURRENCY, sweepRoutes, type RouterPair,
} from './data';

const pair = (srcRouter: number, dstRouter: number): RouterPair => ({
  pair: { src: srcRouter, dst: dstRouter, flits: 1 },
  srcRouter,
  dstRouter,
  local: false,
} as unknown as RouterPair);

describe('route sweep concurrency', () => {
  beforeEach(() => route.mockReset());

  it('runs independent router-pair queries concurrently, within the bound', async () => {
    let inFlight = 0;
    let peak = 0;
    route.mockImplementation(async () => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      return { terminates: true, hops: [] };
    });
    const pairs = Array.from(
      { length: ROUTE_SWEEP_CONCURRENCY * 2 },
      (_, index) => pair(index, index + 1000),
    );

    const result = await sweepRoutes('rev', 'routing', pairs);

    expect(result.resolved).toBe(pairs.length);
    expect(peak).toBe(ROUTE_SWEEP_CONCURRENCY);
  });
});
