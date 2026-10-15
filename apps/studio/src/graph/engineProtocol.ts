/** Versioned boundary types for a future loom-sim sidecar. Defining these
 * types does not imply that this web-only build can spawn the engine. */
import type { LoomProject } from './project';

export const LOOM_SIM_PROTOCOL_VERSION = 1 as const;
export interface EngineHealthRequest { protocolVersion: typeof LOOM_SIM_PROTOCOL_VERSION; requestId: string; action: 'health' }
export interface EngineRunRequest {
  protocolVersion: typeof LOOM_SIM_PROTOCOL_VERSION;
  requestId: string;
  action: 'run';
  project: LoomProject;
  backend: string;
  workload: LoomProject['workload'];
  seed?: number;
}
export interface EngineCancelRequest { protocolVersion: typeof LOOM_SIM_PROTOCOL_VERSION; requestId: string; action: 'cancel'; runId: string }
export type EngineRequest = EngineHealthRequest | EngineRunRequest | EngineCancelRequest;
export interface EngineHealthResponse {
  protocolVersion: number;
  engineVersion: string;
  status: 'available' | 'unavailable';
  capabilities: string[];
}
export interface EngineRunResponse {
  protocolVersion: number;
  requestId: string;
  runId: string;
  state: 'completed' | 'failed' | 'cancelled';
  exitCode: number | null;
  artifacts: Record<string, string>;
  provenance: Record<string, string | number | boolean | null>;
}
export type EngineCompatibility =
  | { state: 'compatible'; engineVersion: string }
  | { state: 'incompatible'; expectedProtocol: number; actualProtocol: number; engineVersion: string }
  | { state: 'unavailable'; reason: string };

export function assessEngineHealth(value: unknown, expectedProtocol = LOOM_SIM_PROTOCOL_VERSION): EngineCompatibility {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return { state: 'unavailable', reason: 'invalid health response' };
  const response = value as Partial<EngineHealthResponse>;
  if (response.status !== 'available') return { state: 'unavailable', reason: 'engine reports unavailable' };
  if (typeof response.engineVersion !== 'string' || !response.engineVersion.trim() || !Array.isArray(response.capabilities)) {
    return { state: 'unavailable', reason: 'health response is missing version or capabilities' };
  }
  if (response.protocolVersion !== expectedProtocol) return {
    state: 'incompatible', expectedProtocol, actualProtocol: response.protocolVersion ?? -1, engineVersion: response.engineVersion,
  };
  return { state: 'compatible', engineVersion: response.engineVersion };
}

/** Deterministic JSON encoding for input fingerprints, not a security signature. */
export function canonicalJson(value: unknown): string {
  if (value === null) return 'null';
  if (typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('fingerprint input contains a non-finite number');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (typeof value !== 'object') throw new TypeError(`fingerprint input contains unsupported ${typeof value}`);
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) throw new TypeError('fingerprint input must contain only plain JSON objects');
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(',')}}`;
}
export async function sha256Hex(bytes: string | Uint8Array | ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('Web Crypto SHA-256 is unavailable');
  const input = typeof bytes === 'string' ? new TextEncoder().encode(bytes) : bytes;
  const digest = await globalThis.crypto.subtle.digest('SHA-256', input);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

export async function fingerprintInputs(value: unknown): Promise<string> {
  return sha256Hex(canonicalJson(value));
}

/** Verifies a raw artifact digest; it does not imply the expected digest is
 * trusted or that the artifact belongs to an authenticated producer. */
export async function verifySha256(bytes: string | Uint8Array | ArrayBuffer, expectedHex: string): Promise<boolean> {
  if (!/^[a-f\d]{64}$/i.test(expectedHex)) return false;
  return (await sha256Hex(bytes)).toLowerCase() === expectedHex.toLowerCase();
}
