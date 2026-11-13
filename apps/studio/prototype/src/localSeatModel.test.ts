import { describe, expect, it } from 'vitest';
import { localEndpointSeats } from './localSeatModel';
import { initialState } from './model';

const BASE_DRAFT = initialState().draft;

describe('local sample seat model', () => {
  it('projects the draft mesh onto the revision topology shape', () => {
    const model = localEndpointSeats(BASE_DRAFT);
    expect(model.topology?.family).toBe('mesh');
    expect(model.topology?.counts.routers).toBe(16);
    expect(model.topology?.counts.channels).toBe(48);
    expect(model.endpoints).toHaveLength(BASE_DRAFT.endpoints.length);
  });

  it('attaches every seat to the router its endpoint declares', () => {
    const model = localEndpointSeats(BASE_DRAFT);
    BASE_DRAFT.endpoints.forEach((endpoint, index) => {
      const router = model.topology!.routers[model.endpoints[index].router_id];
      const [, row, column] = endpoint.router.split('_').map(Number);
      expect(router.coordinates).toEqual([column, row]);
    });
  });

  it('derives contiguous channels from the logical grid, both directions', () => {
    const model = localEndpointSeats(BASE_DRAFT);
    const pairs = new Set(model.topology!.channels.map(channel => `${channel.src_router}>${channel.dst_router}`));
    for (let index = 0; index < 16; index++) {
      const row = Math.floor(index / 4), column = index % 4;
      if (column < 3) expect(pairs.has(`${index}>${index + 1}`) && pairs.has(`${index + 1}>${index}`)).toBe(true);
      if (row < 3) expect(pairs.has(`${index}>${index + 4}`) && pairs.has(`${index + 4}>${index}`)).toBe(true);
    }
  });

  it('counts an agent group per declared interface identity and keeps the source classification', () => {
    const model = localEndpointSeats(BASE_DRAFT);
    const total = model.agents.reduce((count, agent) => count + agent.count, 0);
    expect(total).toBe(BASE_DRAFT.endpoints.length);
    expect(model.sourceById?.get(0)).toBe(BASE_DRAFT.endpoints[0].source);
    expect(model.agentForEndpoint!(model.endpoints[0])?.protocol).toBe(BASE_DRAFT.endpoints[0].profile);
  });

  it('follows a local attachment edit without inventing a seat', () => {
    const moved = { ...BASE_DRAFT, endpoints: BASE_DRAFT.endpoints.map((endpoint, index) => index === 0 ? { ...endpoint, router: 'R_3_3' } : endpoint) };
    const model = localEndpointSeats(moved);
    expect(model.topology!.routers[model.endpoints[0].router_id].coordinates).toEqual([3, 3]);
    expect(model.endpoints).toHaveLength(BASE_DRAFT.endpoints.length);
  });
});
