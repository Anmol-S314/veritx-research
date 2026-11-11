import { describe, expect, it } from 'vitest';
import { buildChannelIndex, channelMatchLabel, decodeLogicalChannel, matchMeasuredChannel } from './channelTopology';
import type { Topology } from './gateway';

const mesh = (family = 'mesh', coordinates: number[][] = []): Topology => {
  const points = coordinates.length ? coordinates : [[0, 0], [1, 0], [0, 1], [1, 1]];
  const routers = points.map((point, index) => ({ router_id: index, coordinates: point }));
  const edges: Topology['channels'] = [];
  let channel = 0;
  for (const router of routers) {
    const [x, y] = pointOf(router.coordinates);
    for (const [dx, dy] of [[1, 0], [0, 1]]) {
      const neighbour = routers.find(other => {
        const [nx, ny] = pointOf(other.coordinates);
        return nx === x + dx && ny === y + dy;
      });
      if (neighbour) edges.push({ channel_id: channel++, src_router: router.router_id, src_port: 42, dst_router: neighbour.router_id, dst_port: 7, width_bits: 128, latency_cycles: 1 });
    }
  }
  return { family, counts: { routers: routers.length, channels: edges.length }, routers, channels: edges, endpoints: [] };
};

const pointOf = (value: unknown): [number, number] => {
  const coordinates = value as number[];
  return [Number(coordinates[0]), Number(coordinates[1])];
};

describe('measured channel topology join', () => {
  it('decodes subnet, router, and output port without losing precision', () => {
    expect(decodeLogicalChannel(40001)).toEqual({ subnet: 0, router: 4, port: 1 });
    expect(decodeLogicalChannel(102_340_005)).toEqual({ subnet: 1, router: 234, port: 5 });
    expect(decodeLogicalChannel(-1)).toBeNull();
    expect(decodeLogicalChannel(1.5)).toBeNull();
  });

  it('maps BookSim E/W/S/N/eject ports to declared neighbours, not src_port values', () => {
    const index = buildChannelIndex(mesh());
    const east = matchMeasuredChannel(index, 0); // R0 port 0 = east
    expect(east).toMatchObject({ local: false, direction: 'east', neighbour: 1, unmatched: false });
    expect(east?.channel).toMatchObject({ src_router: 0, dst_router: 1 });
    const south = matchMeasuredChannel(index, 2); // R0 port 2 = south
    expect(south).toMatchObject({ direction: 'south', neighbour: 2, unmatched: false });
    const eject = matchMeasuredChannel(index, 4);
    expect(eject).toMatchObject({ local: true, unmatched: false, channel: null });
    const boundary = matchMeasuredChannel(index, 1); // R0 port 1 = west, no neighbour
    expect(boundary).toMatchObject({ local: false, direction: 'west', neighbour: null, channel: null, unmatched: true });
    expect(channelMatchLabel(east)).toContain('R0 p0 → R1 p7');
    expect(channelMatchLabel(eject)).toContain('local eject');
  });

  it('refuses a guessed join on a non-grid topology or a 3-D coordinate set', () => {
    expect(buildChannelIndex(mesh('fattree')).grid).toBe(false);
    expect(buildChannelIndex(mesh('cmesh')).grid).toBe(false);
    expect(buildChannelIndex(mesh('mesh', [[0, 0, 0], [1, 0, 0]])).grid).toBe(false);
    expect(matchMeasuredChannel(buildChannelIndex(mesh('fattree')), 0)).toMatchObject({ channel: null, unmatched: true });
  });

  it('honours torus wrap-around when the declared topology is a torus', () => {
    const torus = mesh('torus', [[0, 0], [1, 0], [2, 0]]);
    // Add the wrap link that the rectangular fixture omitted.
    torus.channels.push({ channel_id: 99, src_router: 2, src_port: 9, dst_router: 0, dst_port: 9, width_bits: 64, latency_cycles: 2 });
    const index = buildChannelIndex(torus);
    const wrap = matchMeasuredChannel(index, 20000); // R2 port 0 = east, wraps to R0
    expect(wrap).toMatchObject({ direction: 'east', neighbour: 0, unmatched: false });
    expect(wrap?.channel?.latency_cycles).toBe(2);
  });
});
