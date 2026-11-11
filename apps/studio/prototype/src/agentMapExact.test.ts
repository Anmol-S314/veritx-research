import { describe, expect, it } from 'vitest';
import {
  exactMatches, exactOrZero, formatBytes, formatHexBig, parseAddress, parseAddressBigInt,
  parseAddressCanonical, parseSizeBigInt, windowsFromRequest, windowsToRequest,
  type AddressWindow,
} from './agentMap';

const MAX_U64 = (1n << 64n) - 1n;
const HIGH = (1n << 63n) + 12345n;

const windowFor = (base: bigint, size: bigint): AddressWindow => ({
  id: 'w-high',
  name: 'HIGH',
  base,
  size,
  targetAgentIdx: 0,
  selectionPolicy: null,
  targetInstanceIndex: null,
  interleaveBytes: null,
});

describe('exact 64-bit address round-trip', () => {
  it('windowsFromRequest keeps a high base exactly', () => {
    const windows = windowsFromRequest({
      address_map: { ranges: [{ name: 'HIGH', base: HIGH.toString(10), size: '64', target_agent_idx: 0 }] },
    });
    expect(windows).toHaveLength(1);
    expect(windows[0].base).toBe(HIGH);
    expect(windows[0].size).toBe(64n);
  });

  it('windowsToRequest emits a decimal string above 2^53-1, never a rounded number', () => {
    const ranges = windowsToRequest([windowFor(HIGH, 4096n)]);
    expect(ranges).toHaveLength(1);
    expect(ranges[0].base).toBe(HIGH.toString(10));
    expect(typeof ranges[0].base).toBe('string');
    expect(ranges[0].size).toBe(4096);
  });

  it('a request round-trips byte-equivalently when written and re-read', () => {
    const original = windowFor(MAX_U64 - 4095n, 4096n);
    const written = windowsToRequest([original]);
    const reRead = windowsFromRequest({ address_map: { ranges: written } });
    expect(reRead[0].base).toBe(original.base);
    expect(reRead[0].size).toBe(4096n);
  });

  it('emits a number for values a JS number carries exactly', () => {
    const ranges = windowsToRequest([windowFor(0x1000_0000n, 0x1000n)]);
    expect(ranges[0].base).toBe(0x1000_0000);
    expect(typeof ranges[0].base).toBe('number');
  });

  it('the wire string parses back without loss', () => {
    expect(parseAddressBigInt(HIGH.toString(10))).toBe(HIGH);
    expect(parseSizeBigInt(HIGH.toString(10))).toBe(HIGH);
    expect(parseAddressCanonical('0xFFFF_FFFF_FFFF_FFFF')).toBe(MAX_U64.toString(10));
    expect(parseAddress('0x7FFF_FFFF_FFFF_FFFF_FFFF')).toBeNull();
  });

  it('restores legacy snapshot strings exactly and refuses unsafe numeric snapshots', () => {
    expect(exactOrZero(HIGH.toString(10), parseAddressBigInt)).toBe(HIGH);
    expect(exactOrZero(Number(HIGH), parseAddressBigInt)).toBe(0n);
    expect(exactOrZero(-1n, parseAddressBigInt)).toBe(0n);
  });

  it('formats the maximum unsigned 64-bit address exactly', () => {
    expect(formatHexBig(MAX_U64)).toBe('0xFFFF_FFFF_FFFF_FFFF');
    expect(formatBytes(MAX_U64)).toBe('15.9 EiB');
  });

  it('exactMatches compares numbers, strings and bigints without rounding', () => {
    expect(exactMatches(HIGH.toString(10), HIGH)).toBe(true);
    expect(exactMatches('0x8000_0000_0000_3039', HIGH)).toBe(true);
    expect(exactMatches(2147483648, 2147483648n)).toBe(true);
    expect(exactMatches('nope', HIGH)).toBe(false);
  });
});

describe('2^53 boundary', () => {
  it('exactOrZero keeps a base above 2^53 exact from string', () => {
    const base = '9007199254740993'; // 2^53 + 1, not representable as a Number
    expect(exactOrZero(base, parseAddressBigInt)).toBe(9007199254740993n);
    expect(exactOrZero('9007199254740992', parseAddressBigInt)).toBe(9007199254740992n);
  });

  it('exactOrZero refuses floats and lossy Numbers, accepts safe integers', () => {
    expect(exactOrZero(2 ** 53, parseAddressBigInt)).toBe(0n);
    expect(exactOrZero(Number.MAX_SAFE_INTEGER, parseAddressBigInt)).toBe(BigInt(Number.MAX_SAFE_INTEGER));
    expect(exactOrZero('18446744073709551615', parseAddressBigInt)).toBe((1n << 64n) - 1n);
    expect(exactOrZero('18446744073709551616', parseAddressBigInt)).toBe(0n);
  });

  it('parseSizeBigInt round-trips sizes above 2^53', () => {
    expect(parseSizeBigInt('9007199254740993')).toBe(9007199254740993n);
    expect(parseSizeBigInt('not-a-number')).toBeNull();
  });
});
