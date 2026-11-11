import { afterEach, describe, expect, it, vi } from 'vitest';
import { decodeInjectionTrace } from './trace';
import { fetchVerifiedArtifact } from './RawArtifacts';

afterEach(() => vi.unstubAllGlobals());
describe('injection trace decoding', () => {
  it('keeps the two BookSim dialects distinct', () => {
    expect(decodeInjectionTrace('# input\n0 1 2 3 8').rows[0]).toMatchObject({ cycle: 0, source: 1, trafficClass: '2', destination: 3, flits: 8 });
    expect(decodeInjectionTrace('timestamp,src,dst,type,size\n0,1,3,READ,8').rows[0]).toMatchObject({ cycle: 0, source: 1, destination: 3, trafficClass: 'READ', flits: 8 });
  });
  it('rejects malformed/unsafe fields rather than guessing', () => {
    for (const text of ['0 1 0 2 0', '9007199254740992 1 0 2 8', 'not a trace', '0,1,2,,8']) expect(() => decodeInjectionTrace(text)).toThrow();
    const result = decodeInjectionTrace('0 1 0 2 8\n1 2 0 1 8', 1);
    expect(result.rows).toHaveLength(1); expect(result.total).toBe(2);
  });
});
describe('original-byte verification', () => {
  const digest = '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824';
  it('accepts only bytes matching both manifest and response digest', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('hello', { headers: { 'x-content-sha256': digest } }))));
    expect(new TextDecoder().decode(await fetchVerifiedArtifact('run', 'data', digest))).toBe('hello');
    await expect(fetchVerifiedArtifact('run', 'data', '0'.repeat(64))).rejects.toThrow('do not match the recorded manifest');
  });
  it('does not accept a response without verified-byte metadata', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('hello')));
    await expect(fetchVerifiedArtifact('run', 'data', digest)).rejects.toThrow('do not match the recorded manifest');
  });
});
