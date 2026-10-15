import { describe, expect, it } from 'vitest';
import { assessEngineHealth, canonicalJson, fingerprintInputs, LOOM_SIM_PROTOCOL_VERSION, sha256Hex, verifySha256 } from './engineProtocol';

describe('versioned loom-sim protocol helpers', () => {
  it('distinguishes compatible, incompatible, and unavailable engine health', () => {
    const base = { protocolVersion: LOOM_SIM_PROTOCOL_VERSION, engineVersion: '1.2.3', status: 'available', capabilities: [] };
    expect(assessEngineHealth(base)).toEqual({ state: 'compatible', engineVersion: '1.2.3' });
    expect(assessEngineHealth({ ...base, protocolVersion: 99 })).toMatchObject({ state: 'incompatible', expectedProtocol: 1, actualProtocol: 99 });
    expect(assessEngineHealth({ ...base, status: 'unavailable' })).toMatchObject({ state: 'unavailable' });
  });
  it('verifies raw artifact bytes against SHA-256 and rejects malformed hashes', async () => {
    const abcDigest = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad';
    expect(await sha256Hex('abc')).toBe(abcDigest);
    expect(await verifySha256(new TextEncoder().encode('abc'), abcDigest)).toBe(true);
    expect(await verifySha256('abd', abcDigest)).toBe(false);
    expect(await verifySha256('abc', 'not-a-digest')).toBe(false);
  });
  it('canonicalizes object key order, rejects non-JSON values, and computes SHA-256 fingerprints', async () => {
    expect(canonicalJson({ b: 2, a: 1 })).toBe(canonicalJson({ a: 1, b: 2 }));
    expect(() => canonicalJson({ invalid: undefined })).toThrow(/unsupported undefined/);
    expect(() => canonicalJson({ invalid: Number.NaN })).toThrow(/non-finite/);
    expect(() => canonicalJson(new Date(0))).toThrow(/plain JSON objects/);
    if (globalThis.crypto?.subtle) {
      expect(await fingerprintInputs({ b: 2, a: 1 })).toBe(await fingerprintInputs({ a: 1, b: 2 }));
    }
  });
});
