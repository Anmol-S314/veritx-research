import { afterEach, describe, expect, it, vi } from 'vitest';
import { decodeInjectionTrace, decodeRoutingDump } from './trace';
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
describe('first-hop realization decoding', () => {
  it('parses the executed routing dump row format', () => {
    const text = '# VeritX routing realization dump\nsrc_router 0 dst_node 1 next_router 0 port 1\nsrc_router 0 dst_node 2 next_router 3 port 4\n';
    const result = decodeRoutingDump(text);
    expect(result.total).toBe(2);
    expect(result.rows[0]).toMatchObject({ srcRouter: 0, dstNode: 1, nextRouter: 0, port: 1 });
    expect(result.rows[1]).toMatchObject({ srcRouter: 0, dstNode: 2, nextRouter: 3, port: 4 });
  });
  it('rejects anything that is not a first-hop record', () => {
    for (const text of ['0 1 2 3', 'src_router 0 dst_node 1 next_router 0', 'src_router -1 dst_node 1 next_router 0 port 1', 'src_router a dst_node 1 next_router 0 port 1', '# only comments\n']) expect(() => decodeRoutingDump(text)).toThrow();
    const result = decodeRoutingDump('src_router 0 dst_node 1 next_router 0 port 1\nsrc_router 0 dst_node 2 next_router 0 port 2\n', 1);
    expect(result.rows).toHaveLength(1); expect(result.total).toBe(2);
  });
});
describe('original-byte verification', () => {
  const digest = '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824';
  it('accepts only bytes matching both manifest and response digest', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('hello', { headers: { 'x-content-sha256': digest } }))));
    expect(new TextDecoder().decode(await fetchVerifiedArtifact('run', 'data', digest))).toBe('hello');
    await expect(fetchVerifiedArtifact('run', 'data', '0'.repeat(64))).rejects.toThrow('digest mismatch');
  });
  it('does not accept a response without verified-digest metadata', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('hello')));
    await expect(fetchVerifiedArtifact('run', 'data', digest)).rejects.toThrow('digest mismatch');
  });
});
