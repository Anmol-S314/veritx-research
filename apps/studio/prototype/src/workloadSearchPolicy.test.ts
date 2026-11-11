import { describe, expect, it } from 'vitest';
import { expandSearchGrid, recommendSearch, searchObservation, searchProfiles } from './workloadSearchPolicy';
const row = (id: string, latency: number, throughput: number, energy: number, area: number) => ({ id, topology: id, status: 'ok', latency, throughput, energy, area, power: 1, modelId: 'm', request: {}, raw: {}, source: 'test', routers: 1, crosspoints: 1, storage: 1 });
describe('fabric search policy', () => {
  it('provides the four intended directions and frontier-stable Balanced ranking', () => {
    expect(searchProfiles.map(p => p.id)).toEqual(['balanced', 'performance', 'efficient', 'compact']);
    const candidates = [row('0', 83.514, 7.207, 35.976, 18.275), row('1', 94.059, 10.334, 44.501, 52.848), row('2', 98.571, 7.429, 33.429, 41.515), row('3', 23.939, 5.793, 21.465, 2.650)];
    const outlier = row('dominated-ring', 1e9, 0, 1e9, 1e9);
    const winner = recommendSearch(candidates, {})[0].winner?.id;
    expect(recommendSearch([...candidates, outlier], {})[0].winner?.id).toBe(winner);
  });
  it('applies hard constraints before objective ordering', () => {
    const rows = [row('fast', 10, 2, 80, 10), row('small', 20, 2, 20, 1)];
    expect(recommendSearch(rows, { area: 2 })[1].winner?.id).toBe('small');
    expect(recommendSearch(rows, { latency: 9 })[0].winner).toBeNull();
  });
  it('requires an identified compatible model for modeled objectives and uses replay energy, not watts', () => {
    const lowWatts = { ...row('low-watts', 100, 1, 20, 1), power: 1 };
    const lowEnergy = { ...row('low-energy', 10, 10, 10, 2), power: 50 };
    expect(recommendSearch([lowWatts, lowEnergy], {})[2].winner?.id).toBe('low-energy');
    const measured = searchObservation({ topology: 'mesh', status: 'ok', latency_p95: 1, throughput_packets_per_cycle: 1, native_power_w: 0 }, {}, 'run', 0);
    expect(recommendSearch([measured], {})[0].winner).toBeNull();
    expect(recommendSearch([measured], {})[1].winner?.topology).toBe('mesh');
  });
  it('refuses oversized and malformed grids instead of truncating', () => {
    expect(expandSearchGrid({ vc_buf_size: [4, 8] }, new Set(['vc_buf_size']), 24, 12).count).toBe(24);
    expect(() => expandSearchGrid({ vc_buf_size: [4, 8] }, new Set(['vc_buf_size']), 12, 12)).toThrow(/budget/);
    expect(() => expandSearchGrid({ secret: [1] }, new Set(['vc_buf_size']), 24, 12)).toThrow(/Unsupported/);
  });
});
