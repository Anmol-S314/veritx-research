// Agent-level address mapping. The compile schema is the authority: these
// helpers only translate between the editable table and `address_map.ranges`,
// then check the constraints the schema and the resolved decode both rely on.
//
// The schema has no per-initiator permission field. This module therefore
// models address WINDOWS, not firewalls; a matrix cell means "a window exists",
// never "this initiator is allowed".

export type AgentGroup = {
  kind: string;
  count: number;
  data_width?: number;
  addr_width?: number;
  protocol?: string;
  clock_domain?: string | null;
  power_domain?: string | null;
  group_name?: string | null;
};

export type SelectionPolicy = 'FIXED_INSTANCE' | 'STRIPED';

export type AddressWindow = {
  id: string;
  name: string;
  base: bigint;
  size: bigint;
  targetAgentIdx: number;
  selectionPolicy: SelectionPolicy | null;
  targetInstanceIndex: number | null;
  interleaveBytes: bigint | null;
};

export type AddressIssue = {
  window: string;
  severity: 'error' | 'warning';
  code: string;
  detail: string;
};

export type AddressCoverage = {
  declaredBytes: bigint;
  mappedBytes: bigint;
  overlapBytes: bigint;
  maxEnd: bigint;
  byTarget: { agentIdx: number; windows: number; declaredBytes: bigint; mappedBytes: bigint }[];
};

// JS numbers are exact only up to 2^53−1. The BigInt path below is the
// authority for exactness; Number() is only ever called after a BigInt
// bound check against this limit, so no rounding can occur.
const U64_LIMIT = (1n << 64n) - 1n;
/** Largest unsigned 64-bit address value (2^64−1). */
export const MAX_U64 = U64_LIMIT;
/** Largest integer a JavaScript number carries exactly (2^53−1). */
export const MAX_SAFE_U64 = BigInt(Number.MAX_SAFE_INTEGER);
let nextId = 1;

/** v5 nests the v4 design under `base_v4`. Reads use it; writes are guarded
 *  by the page until a v5 authoring path exists. */
export function designDocument(request: unknown): Record<string, unknown> {
  const doc = (request ?? {}) as Record<string, unknown>;
  const base = doc.base_v4;
  return base && typeof base === 'object' && !Array.isArray(base)
    ? base as Record<string, unknown>
    : doc;
}

export const INITIATOR_KINDS = new Set(['compute_tile', 'nic']);
export const TARGET_KINDS = new Set(['hbm_controller', 'ucie_port', 'peripheral']);

export function newWindowId(): string {
  nextId += 1;
  return `window-${nextId}`;
}

export function emptyWindow(targetAgentIdx = 0): AddressWindow {
  return {
    id: newWindowId(),
    name: '',
    base: 0n,
    size: 0n,
    targetAgentIdx,
    selectionPolicy: null,
    targetInstanceIndex: null,
    interleaveBytes: null,
  };
}

/** Parse a declared address into an exact BigInt.
 *  Underscores and a 0x prefix are accepted; decimal input is read as
 *  decimal. Range is the full unsigned 64-bit space (0 ≤ v ≤ 2^64−1).
 *  No Number conversion happens here, so no rounding is possible at any
 *  width — including 48-bit addresses, HBM bases past 2^53, and beyond. */
export function parseAddressBigInt(text: string): bigint | null {
  const cleaned = text.trim().replaceAll('_', '').replaceAll(',', '');
  if (!cleaned) return null;
  if (cleaned.startsWith('-') || cleaned.startsWith('+')) return null;
  let value: bigint;
  try {
    value = /^0x/i.test(cleaned) ? BigInt(`0x${cleaned.slice(2)}`) : BigInt(cleaned);
  } catch {
    return null;
  }
  if (value < 0n || value > MAX_U64) return null;
  return value;
}

/** Canonical exact-string address (decimal). Use this on the wire for
 *  values above 2^53−1: a JS number cannot carry them exactly, so the
 *  compiler must receive the exact string, never a rounded Number. */
export function parseAddressCanonical(text: string): string | null {
  const value = parseAddressBigInt(text);
  return value === null ? null : value.toString(10);
}

/** Parse a declared address into a safe JS number, for in-memory editor
 *  state. Exactness proof: the BigInt value is bound-checked against
 *  2^53−1 BEFORE Number(), so Number() is an exact widening, never a
 *  rounding. Values above the safe range return null (refused, not
 *  rounded) — use parseAddressCanonical for the exact wire value. */
export function parseAddress(text: string): number | null {
  const value = parseAddressBigInt(text);
  if (value === null || value > MAX_SAFE_U64) return null;
  return Number(value);
}

/** Exact JSON wire value: a safe integer stays a number for schema
 *  compatibility, a value above 2^53−1 becomes a canonical decimal string
 *  so JSON.parse in any client keeps every digit. */
export function exactWireValue(value: bigint): number | string {
  if (value < 0n || value > U64_LIMIT) throw new RangeError(`address value out of unsigned 64-bit range: ${value}`);
  return value <= MAX_SAFE_U64 ? Number(value) : value.toString(10);
}

/** Read an exact value from a request field that may be a number, a decimal
 *  string, or a hex string. Missing or malformed values fall back to 0n so
 *  the editor can show a refusal instead of inventing an address. */
export function exactOrZero(value: unknown, parse: (text: string) => bigint | null): bigint {
  if (typeof value === 'bigint') return value >= 0n && value <= MAX_U64 ? value : 0n;
  if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) return BigInt(value);
  if (typeof value === 'string') return parse(value) ?? 0n;
  return 0n;
}

/** Compare a wire value (number or decimal/hex string) with an exact BigInt
 *  without ever widening the exact side through Number(). */
export function exactMatches(value: unknown, expected: bigint): boolean {
  if (typeof value === 'bigint') return value === expected;
  if (typeof value === 'number') return Number.isSafeInteger(value) && BigInt(value) === expected;
  if (typeof value === 'string') {
    const parsed = parseAddressBigInt(value) ?? parseSizeBigInt(value);
    return parsed !== null && parsed === expected;
  }
  return false;
}

const SIZE_UNITS: Record<string, number> = {
  '': 1,
  B: 1,
  K: 1024, KB: 1024, KIB: 1024,
  M: 1024 ** 2, MB: 1024 ** 2, MIB: 1024 ** 2,
  G: 1024 ** 3, GB: 1024 ** 3, GIB: 1024 ** 3,
  T: 1024 ** 4, TB: 1024 ** 4, TIB: 1024 ** 4,
};

/** Exact BigInt byte count. Hex is parsed exactly; decimal suffixes are
 *  read as binary (MiB) with exact integer arithmetic. A fractional part
 *  is only accepted when the product with the unit is an exact integer
 *  (e.g. 1.5 MiB); anything inexact is refused rather than rounded. */
export function parseSizeBigInt(text: string): bigint | null {
  const cleaned = text.trim().replaceAll('_', '').replaceAll(',', '');
  if (!cleaned) return null;
  if (/^0x/i.test(cleaned)) return parseAddressBigInt(cleaned);
  const match = /^(\d+(?:\.\d+)?)\s*([A-Za-z]*)$/.exec(cleaned);
  if (!match) return null;
  const unit = SIZE_UNITS[match[2].toUpperCase()];
  if (unit === undefined) return null;
  const dot = match[1].indexOf('.');
  if (dot === -1) {
    return BigInt(match[1]) * BigInt(unit);
  }
  const whole = BigInt(match[1].slice(0, dot));
  const fracText = match[1].slice(dot + 1);
  const scale = BigInt(10 ** fracText.length);
  const scaled = whole * scale + BigInt(fracText);
  const product = scaled * BigInt(unit);
  if (product % scale !== 0n) return null;
  return product / scale;
}

/** Parse a byte count. Decimal suffixes are read as binary (MiB), because
 *  every other quantity in this model is a power of two. Exactness is
 *  inherited from parseSizeBigInt: Number() widens only after the BigInt
 *  bound check, so no rounding is possible. */
export function parseSize(text: string): number | null {
  const value = parseSizeBigInt(text);
  if (value === null || value <= 0n || value > U64_LIMIT) return null;
  return Number(value);
}

/** Format an address as hex with four-digit groups. Accepts numbers,
 *  BigInts, and exact strings; the BigInt/string path formats without
 *  any Number conversion, so values above 2^53 format exactly. */
export function formatHexBig(value: bigint | number | string, minDigits = 8): string {
  let big: bigint;
  if (typeof value === 'bigint') {
    big = value < 0n ? 0n : value;
  } else if (typeof value === 'string') {
    const parsed = parseAddressBigInt(value);
    big = parsed === null ? 0n : parsed;
  } else {
    if (!Number.isFinite(value)) return `0x${'0'.repeat(Math.max(minDigits, 8))}`;
    big = BigInt(Math.max(0, Math.trunc(value)));
  }
  const raw = big.toString(16).toUpperCase();
  const digits = raw.length <= minDigits ? raw.padStart(minDigits, '0') : raw;
  const width = Math.max(minDigits, Math.ceil(digits.length / 4) * 4);
  const padded = digits.padStart(width, '0');
  const groups = padded.match(/.{1,4}/g) ?? [padded];
  return `0x${groups.join('_')}`;
}

export function formatHex(value: number | bigint | string, minDigits = 8): string {
  return formatHexBig(value, minDigits);
}

export function formatBytes(value: number | bigint | string): string {
  if (typeof value === 'string') {
    const parsed = parseAddressBigInt(value) ?? parseSizeBigInt(value);
    return parsed === null ? '—' : formatBytes(parsed);
  }
  if (typeof value === 'bigint') {
    if (value < 0n) return '—';
    if (value < 1024n) return `${value} B`;
    const units = ['KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB'];
    let unit = -1;
    let divisor = 1n;
    while (value / divisor >= 1024n && unit < units.length - 1) {
      divisor *= 1024n;
      unit += 1;
    }
    const whole = value / divisor;
    const tenth = (value % divisor) * 10n / divisor;
    const text = whole >= 100n ? whole.toString(10) : `${whole.toString(10)}.${tenth.toString(10)}`;
    return `${text.replace(/\.0$/, '')} ${units[unit]}`;
  }
  if (!Number.isFinite(value) || value < 0) return '—';
  if (value < 1024) return `${value} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
  let scaled = value;
  let unit = -1;
  while (scaled >= 1024 && unit < units.length - 1) {
    scaled /= 1024;
    unit += 1;
  }
  const rounded = scaled >= 100 ? scaled.toFixed(0) : scaled >= 10 ? scaled.toFixed(1) : scaled.toFixed(2);
  return `${rounded.replace(/\.0+$/, '').replace(/(\.\d)0$/, '$1')} ${units[unit]}`;
}

export function formatBits(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '—';
  if (value < 1024) return `${value} b`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(value % 1024 === 0 ? 0 : 1)} Kib`;
  return `${(value / 1024 ** 2).toFixed(value % (1024 ** 2) === 0 ? 0 : 2)} Mib`;
}

export function alignUp(value: number, alignment: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(alignment) || alignment <= 0) return value;
  return Math.ceil(value / alignment) * alignment;
}

export function alignUpBig(value: bigint, alignment: bigint): bigint {
  if (alignment <= 0n) return value;
  return ((value + alignment - 1n) / alignment) * alignment;
}

function numberOrNull(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') return parseAddress(value);
  return null;
}

export function windowsFromRequest(request: unknown, agents?: AgentGroup[]): AddressWindow[] {
  const doc = designDocument(request);
  const addressMap = (doc.address_map ?? {}) as Record<string, unknown>;
  const ranges = Array.isArray(addressMap.ranges) ? addressMap.ranges : [];
  return ranges.map((raw, index) => {
    const range = (raw ?? {}) as Record<string, unknown>;
    const policy = range.selection_policy === 'FIXED_INSTANCE' || range.selection_policy === 'STRIPED'
      ? range.selection_policy : null;
    const targetRaw = range.target_agent_idx ?? range.target;
    let targetAgentIdx = numberOrNull(targetRaw) ?? 0;
    if (typeof targetRaw === 'string' && agents) {
      const byKind = agents.findIndex(agent => agent.kind === targetRaw);
      if (byKind >= 0) targetAgentIdx = byKind;
    }
    const interleaveRaw = range.interleave_bytes;
    return {
      id: `range-${index}`,
      name: typeof range.name === 'string' ? range.name : '',
      base: exactOrZero(range.base, parseAddressBigInt),
      size: exactOrZero(range.size ?? range.size_bytes, parseSizeBigInt),
      targetAgentIdx,
      selectionPolicy: policy,
      targetInstanceIndex: numberOrNull(range.target_instance_index),
      interleaveBytes: interleaveRaw === null || interleaveRaw === undefined ? null : exactOrZero(interleaveRaw, parseSizeBigInt),
    };
  });
}

export function windowsToRequest(windows: AddressWindow[]): Record<string, unknown>[] {
  return [...windows].sort((a, b) => (a.base < b.base ? -1 : a.base > b.base ? 1 : 0) || (a.size < b.size ? -1 : a.size > b.size ? 1 : 0) || a.name.localeCompare(b.name)).map(window => {
    const range: Record<string, unknown> = {
      name: window.name.trim(),
      base: exactWireValue(window.base),
      size: exactWireValue(window.size),
      target_agent_idx: window.targetAgentIdx,
    };
    if (window.selectionPolicy === 'FIXED_INSTANCE') {
      range.selection_policy = 'FIXED_INSTANCE';
      range.target_instance_index = window.targetInstanceIndex ?? 0;
    } else if (window.selectionPolicy === 'STRIPED') {
      range.selection_policy = 'STRIPED';
      range.interleave_bytes = exactWireValue(window.interleaveBytes ?? 1n);
    }
    return range;
  });
}

export function agentsFromRequest(request: unknown): AgentGroup[] {
  const doc = designDocument(request);
  const agents = Array.isArray(doc.agents) ? doc.agents : [];
  return agents.map(raw => {
    const agent = (raw ?? {}) as Record<string, unknown>;
    return {
      kind: typeof agent.kind === 'string' ? agent.kind : 'unknown',
      count: typeof agent.count === 'number' && agent.count > 0 ? agent.count : 1,
      data_width: typeof agent.data_width === 'number' ? agent.data_width : undefined,
      addr_width: typeof agent.addr_width === 'number' ? agent.addr_width : undefined,
      protocol: typeof agent.protocol === 'string' ? agent.protocol : undefined,
      clock_domain: typeof agent.clock_domain === 'string' ? agent.clock_domain : null,
      power_domain: typeof agent.power_domain === 'string' ? agent.power_domain : null,
      group_name: typeof agent.group_name === 'string' ? agent.group_name : null,
    };
  });
}

export function agentsToRequest(agents: AgentGroup[]): Record<string, unknown>[] {
  return agents.map(agent => ({
    kind: agent.kind,
    count: agent.count,
    data_width: agent.data_width,
    addr_width: agent.addr_width,
    protocol: agent.protocol,
    clock_domain: agent.clock_domain ?? null,
    power_domain: agent.power_domain ?? null,
    group_name: agent.group_name ?? null,
  }));
}

export function validateWindows(windows: AddressWindow[], agents: AgentGroup[]): AddressIssue[] {
  const issues: AddressIssue[] = [];
  const names = new Map<string, number>();
  windows.forEach((window, index) => {
    const label = window.name.trim() || `window ${index + 1}`;
    if (!window.name.trim()) issues.push({ window: label, severity: 'error', code: 'NAME_REQUIRED', detail: 'A window needs a name; the resolved decode reports it verbatim.' });
    else names.set(window.name.trim(), (names.get(window.name.trim()) ?? 0) + 1);
    if (window.base < 0n || window.base > U64_LIMIT) issues.push({ window: label, severity: 'error', code: 'BASE_INVALID', detail: 'Base must be an exact non-negative unsigned 64-bit integer.' });
    if (window.size <= 0n || window.size > U64_LIMIT) issues.push({ window: label, severity: 'error', code: 'SIZE_INVALID', detail: 'Size must be a positive unsigned 64-bit byte count.' });
    if (window.base + window.size > U64_LIMIT) issues.push({ window: label, severity: 'error', code: 'RANGE_TOO_LARGE', detail: 'Base + size exceeds the unsigned 64-bit address space.' });
    const target = agents[window.targetAgentIdx];
    if (!target) {
      issues.push({ window: label, severity: 'error', code: 'TARGET_MISSING', detail: `Target agent index ${window.targetAgentIdx} does not name a declared agent group.` });
    } else {
      const width = target.addr_width ?? 64;
      if (width < 64) {
        const limit = 1n << BigInt(width);
        if (window.base + window.size > limit) issues.push({ window: label, severity: 'error', code: 'TARGET_ADDR_WIDTH', detail: `The window ends at ${formatHexBig(window.base + window.size)} but ${target.kind} declares only ${width} address bits.` });
      }
      if (target.count === 1 && window.selectionPolicy !== null) {
        issues.push({
          window: label, severity: 'error', code: 'SINGLETON_HAS_POLICY',
          detail: `${target.kind} declares one instance. The resolved decode refuses an explicit selection policy on a singleton target; use the legacy group selection.`,
        });
      }
      if (window.selectionPolicy === 'FIXED_INSTANCE') {
        if (window.targetInstanceIndex === null || !Number.isInteger(window.targetInstanceIndex) || window.targetInstanceIndex < 0) {
          issues.push({ window: label, severity: 'error', code: 'INSTANCE_REQUIRED', detail: 'FIXED_INSTANCE needs a target instance index.' });
        } else if (window.targetInstanceIndex >= target.count) {
          issues.push({ window: label, severity: 'error', code: 'INSTANCE_OUT_OF_RANGE', detail: `${target.kind} declares ${target.count} instance(s); instance ${window.targetInstanceIndex} does not exist.` });
        }
        if (window.interleaveBytes !== null) issues.push({ window: label, severity: 'error', code: 'FIXED_HAS_INTERLEAVE', detail: 'FIXED_INSTANCE cannot also declare an interleave.' });
      } else if (window.selectionPolicy === 'STRIPED') {
        if (window.targetInstanceIndex !== null) issues.push({ window: label, severity: 'error', code: 'STRIPED_HAS_INSTANCE', detail: 'STRIPED cannot pin one instance; it distributes across the group.' });
        const interleave = window.interleaveBytes;
        if (interleave === null || interleave <= 0n) {
          issues.push({ window: label, severity: 'error', code: 'INTERLEAVE_REQUIRED', detail: 'STRIPED needs a positive interleave size.' });
        } else {
          if ((interleave & (interleave - 1n)) !== 0n) issues.push({ window: label, severity: 'error', code: 'INTERLEAVE_NOT_POW2', detail: 'The interleave must be a power of two; the resolved decode refuses any other.' });
          if (window.base % interleave !== 0n) issues.push({ window: label, severity: 'error', code: 'INTERLEAVE_ALIGNMENT', detail: `Base ${formatHexBig(window.base)} is not aligned to the ${formatBytes(interleave)} interleave.` });
        }
      } else if (target.count > 1) {
        issues.push({
          window: label, severity: 'error', code: 'GROUP_SELECTION_REQUIRED',
          detail: `${target.kind} declares ${target.count} instances. The resolved decode refuses a multi-instance target without an explicit FIXED_INSTANCE or STRIPED selection.`,
        });
      } else if (window.targetInstanceIndex !== null || window.interleaveBytes !== null) {
        issues.push({ window: label, severity: 'error', code: 'POLICY_FIELDS_WITHOUT_POLICY', detail: 'Instance and interleave fields require an explicit selection policy.' });
      }
    }
  });
  for (const [name, count] of names) {
    if (count > 1) issues.push({ window: name, severity: 'warning', code: 'DUPLICATE_NAME', detail: `${count} windows use the same name. The compiler keys semantic identity by range, not name, so this is ambiguous for readers rather than a compile refusal.` });
  }
  const ordered = [...windows].sort((a, b) => (a.base < b.base ? -1 : a.base > b.base ? 1 : 0));
  for (let index = 1; index < ordered.length; index += 1) {
    const previous = ordered[index - 1];
    const current = ordered[index];
    if (previous.base + previous.size > current.base) {
      issues.push({
        window: current.name.trim() || `window ${index + 1}`,
        severity: 'error',
        code: 'OVERLAP',
        detail: `${current.name.trim() || 'This window'} overlaps ${previous.name.trim() || 'the previous window'}: ${formatHexBig(previous.base)}–${formatHexBig(previous.base + previous.size - 1n)} vs ${formatHexBig(current.base)}–${formatHexBig(current.base + current.size - 1n)}. The resolved decode refuses overlapping ranges.`,
      });
    }
  }
  return issues;
}

export function addressCoverage(windows: AddressWindow[]): AddressCoverage {
  const ordered = [...windows].filter(w => w.size > 0n).sort((a, b) => (a.base < b.base ? -1 : a.base > b.base ? 1 : 0));
  let mappedBytes = 0n;
  let cursor = -1n;
  let maxEnd = 0n;
  for (const window of ordered) {
    const start = window.base;
    const end = window.base + window.size;
    maxEnd = end > maxEnd ? end : maxEnd;
    if (start > cursor) {
      mappedBytes += end - start;
      cursor = end;
    } else if (end > cursor) {
      mappedBytes += end - cursor;
      cursor = end;
    }
  }
  const declaredBytes = ordered.reduce((sum, window) => sum + window.size, 0n);
  const byTarget = new Map<number, { windows: number; declaredBytes: bigint; ranges: AddressWindow[] }>();
  for (const window of ordered) {
    const entry = byTarget.get(window.targetAgentIdx) ?? { windows: 0, declaredBytes: 0n, ranges: [] };
    entry.windows += 1;
    entry.declaredBytes += window.size;
    entry.ranges.push(window);
    byTarget.set(window.targetAgentIdx, entry);
  }
  const unionBytes = (ranges: AddressWindow[]): bigint => {
    let total = 0n;
    let end = -1n;
    for (const range of [...ranges].sort((a, b) => (a.base < b.base ? -1 : a.base > b.base ? 1 : 0))) {
      const rangeEnd = range.base + range.size;
      if (range.base > end) total += rangeEnd - range.base;
      else if (rangeEnd > end) total += rangeEnd - end;
      end = rangeEnd > end ? rangeEnd : end;
    }
    return total;
  };
  return {
    declaredBytes,
    mappedBytes,
    overlapBytes: declaredBytes - mappedBytes,
    maxEnd,
    byTarget: [...byTarget.entries()].sort((a, b) => a[0] - b[0]).map(([agentIdx, entry]) => ({
      agentIdx,
      windows: entry.windows,
      declaredBytes: entry.declaredBytes,
      mappedBytes: unionBytes(entry.ranges),
    })),
  };
}

export type TargetCoverage = {
  agentIdx: number;
  kind: string;
  count: number;
  covered: number;
  windows: number;
  missingInstances: number[];
};

export function targetCoverage(agents: AgentGroup[], windows: AddressWindow[]): TargetCoverage[] {
  const byTarget = new Map<number, { covered: Set<number>; windows: number }>();
  agents.forEach((agent, index) => {
    if (TARGET_KINDS.has(agent.kind)) byTarget.set(index, { covered: new Set<number>(), windows: 0 });
  });
  for (const window of windows) {
    const entry = byTarget.get(window.targetAgentIdx) ?? { covered: new Set<number>(), windows: 0 };
    entry.windows += 1;
    const group = agents[window.targetAgentIdx];
    if (group) {
      if (window.selectionPolicy === 'STRIPED') {
        for (let instance = 0; instance < group.count; instance += 1) entry.covered.add(instance);
      } else {
        entry.covered.add(window.targetInstanceIndex ?? 0);
      }
    }
    byTarget.set(window.targetAgentIdx, entry);
  }
  return [...byTarget.entries()].sort((a, b) => a[0] - b[0]).map(([agentIdx, entry]) => {
    const group = agents[agentIdx];
    const missingInstances: number[] = [];
    for (let instance = 0; instance < (group?.count ?? 0); instance += 1) {
      if (!entry.covered.has(instance)) missingInstances.push(instance);
    }
    return {
      agentIdx,
      kind: group?.kind ?? `agent ${agentIdx}`,
      count: group?.count ?? 0,
      covered: entry.covered.size,
      windows: entry.windows,
      missingInstances,
    };
  });
}

export type AccessCell = { windows: number; bytes: bigint };
export type AccessMatrix = {
  rows: { agentIdx: number; kind: string; count: number }[];
  cols: { agentIdx: number; kind: string; count: number }[];
  cell: (rowIdx: number, colIdx: number) => AccessCell;
  targetIds: Set<number>;
};



/** Address-window reachability, grouped by agent kind. There is no
 *  permission field in the compile schema, so this is not a firewall matrix. */
export function accessMatrix(agents: AgentGroup[], windows: AddressWindow[]): AccessMatrix {
  const targetIds = new Set(windows.map(window => window.targetAgentIdx));
  const rowIdx = agents.map((agent, index) => ({ agent, index })).filter(({ agent, index }) =>
    INITIATOR_KINDS.has(agent.kind) || (!targetIds.has(index) && !TARGET_KINDS.has(agent.kind)));
  const colIdx = agents.map((agent, index) => ({ agent, index })).filter(({ agent, index }) =>
    targetIds.has(index) || TARGET_KINDS.has(agent.kind));
  const rows = (rowIdx.length ? rowIdx : agents.map((agent, index) => ({ agent, index }))).map(({ agent, index }) => ({ agentIdx: index, kind: agent.kind, count: agent.count }));
  const cols = colIdx.map(({ agent, index }) => ({ agentIdx: index, kind: agent.kind, count: agent.count }));
  const cell = (rowIdxValue: number, colIdxValue: number): AccessCell => {
    const row = rows[rowIdxValue];
    const col = cols[colIdxValue];
    if (!row || !col) return { windows: 0, bytes: 0n };
    const matching = windows.filter(window => window.targetAgentIdx === col.agentIdx);
    return { windows: matching.length, bytes: matching.reduce((sum, window) => sum + window.size, 0n) };
  };
  return { rows, cols, cell, targetIds };
}

export type AutoMapOptions = { base: bigint; size: bigint; targetKinds: string[] };

/** Allocate one fixed-instance window per target instance, in declaration
 *  order. This is an explicit operator action: no size or base is inferred
 *  from a model name. */
export function autoMapWindows(agents: AgentGroup[], options: AutoMapOptions): AddressWindow[] {
  const windows: AddressWindow[] = [];
  let cursor = alignUpBig(options.base, 4096n);
  for (const [agentIdx, agent] of agents.entries()) {
    if (!options.targetKinds.includes(agent.kind)) continue;
    for (let instance = 0; instance < agent.count; instance += 1) {
      const size = options.size;
      const baseName = `${agent.kind.toUpperCase()}_${instance}`.replace(/[^A-Z0-9_]/g, '_');
      const name = windows.some(window => window.name === baseName) ? `${baseName}_${agentIdx}` : baseName;
      windows.push({
        id: newWindowId(),
        name,
        base: cursor,
        size,
        targetAgentIdx: agentIdx,
        selectionPolicy: agent.count > 1 ? 'FIXED_INSTANCE' : null,
        targetInstanceIndex: agent.count > 1 ? instance : null,
        interleaveBytes: null,
      });
      cursor = alignUpBig(cursor + size, size < 1024n ** 2n ? (size > 4096n ? size : 4096n) : 1024n ** 2n);
    }
  }
  return windows;
}

const toRequestJsonCache = new WeakMap<AddressWindow[], string>();
const fromRequestCache = new WeakMap<object, { agents: AgentGroup[]; json: string }>();

/** Canonical ranges JSON for an editable window list; cached per array
 *  identity so re-renders with unchanged edits cost one Map lookup. */
export function memoizedRangesJson(windows: AddressWindow[]): string {
  const hit = toRequestJsonCache.get(windows);
  if (hit !== undefined) return hit;
  const json = JSON.stringify(windowsToRequest(windows));
  toRequestJsonCache.set(windows, json);
  return json;
}

/** Canonical saved-snapshot ranges JSON for a request; cached per request
 *  object identity so the saved-comparison is computed once per draft. */
export function memoizedSavedRangesJson(request: unknown, agents: AgentGroup[]): string {
  const key = (request ?? {}) as object;
  const hit = fromRequestCache.get(key);
  if (hit !== undefined && hit.agents === agents) return hit.json;
  const json = JSON.stringify(windowsToRequest(windowsFromRequest(key, agents)));
  fromRequestCache.set(key, { agents, json });
  return json;
}

export function hasUnsavedAgentMap(agents: AgentGroup[], windows: AddressWindow[], request: unknown): boolean {
  const current = designDocument(request);
  const normalizeAgent = (agent: Record<string, unknown>) => ({
    kind: agent.kind ?? 'unknown',
    count: agent.count ?? 1,
    data_width: agent.data_width ?? null,
    addr_width: agent.addr_width ?? null,
    protocol: agent.protocol ?? null,
    clock_domain: agent.clock_domain ?? null,
    power_domain: agent.power_domain ?? null,
    group_name: agent.group_name ?? null,
  });
  const currentAgents = (Array.isArray(current.agents) ? current.agents : []).map(raw => normalizeAgent((raw ?? {}) as Record<string, unknown>));
  const editedAgents = agentsToRequest(agents).map(normalizeAgent);
  return JSON.stringify(editedAgents) !== JSON.stringify(currentAgents)
    || memoizedRangesJson(windows) !== memoizedSavedRangesJson(current, agents);
}

// ── Workload → hardware fit resolver (docs/design/workload-fit-loop.md) ──────
//
// The workload envelope constrains only CAPACITY: how much outstanding work
// the design must absorb, how bursty it gets, and how much bandwidth and
// concurrency it demands. Routing law, VC counts, deadlock-freedom proofs and
// address decode are HARD SEMANTICS derived from the topology intent, not
// from the workload, so they never change per workload. When a new workload
// envelope fits inside the envelope the design was synthesized for, the RTL
// is already correct — regenerating it would be pure churn. That is why the
// resolver returns a fit verdict instead of a re-synthesis command: only
// `needs-re-synthesis` (envelope exceeded) calls for new hardware.

/** Demand side: what the workload asks for. All fields are plain counts or
 *  budgets; the resolver never fabricates a missing demand. */
export type WorkloadEnvelope = {
  /** Longest burst that must not overflow the outstanding budget, in flits. */
  burstiness: number;
  /** Peak concurrent actors / streams. */
  concurrency: number;
  /** Peak outstanding requests the workload can issue. */
  outstandingDemand: number;
  /** Count of dependency edges (compute / collective / coherence ordering). */
  dependencyCount: number;
  /** End-to-end latency budget the workload tolerates, in nanoseconds. */
  latencyBudgetNs: number;
  /** Sustained bandwidth demand, in GiB/s. */
  bandwidthDemandGbps: number;
};

/** Capacity side: the envelope the design was synthesized for. A workload
 *  fits when every demand is componentwise within capacity. */
export type DesignEnvelope = {
  maxBurstiness: number;
  maxConcurrency: number;
  maxOutstanding: number;
  maxDependencies: number;
  /** Achieved latency of the design, in nanoseconds. */
  latencyAchievedNs: number;
  /** Sustained bandwidth capacity of the design, in GiB/s. */
  bandwidthCapacityGbps: number;
};

/** (a) M2 sizing: AgentIntentV4.max_outstanding / split_at derived from the
 *  workload envelope. The design stores these; the resolver checks them. */
export type M2Sizing = {
  maxOutstanding: number;
  splitAt: number;
};

/** Deterministic M2 sizing: outstanding demand rounds up to the integer
 *  budget; the burst split threshold covers the bursty peak so one burst
 *  never exceeds the outstanding budget. */
export function sizeM2FromEnvelope(envelope: WorkloadEnvelope): M2Sizing {
  const outstanding = Number.isFinite(envelope.outstandingDemand) ? Math.ceil(envelope.outstandingDemand) : 0;
  const burst = Number.isFinite(envelope.burstiness) ? Math.ceil(envelope.burstiness) : 0;
  return {
    maxOutstanding: Math.max(1, outstanding),
    splitAt: Math.max(1, burst),
  };
}

/** (b) Fit verdict, stored on the revision beside the compile verdicts. */
export type FitVerdictStatus = 'satisfied' | 'same-design-fits' | 'needs-re-synthesis';

export type FitVerdict = {
  status: FitVerdictStatus;
  /** Componentwise evidence table: demand vs capacity per dimension. */
  checks: { dimension: string; demand: number; capacity: number; fits: boolean }[];
  /** Dimensions that exceeded capacity, verbatim for the operator. */
  exceeded: string[];
};

export type FitDesign = {
  /** Workload this design was synthesized for (workload design hash). */
  workloadHash: string;
  envelope: DesignEnvelope;
  m2: M2Sizing;
};

/** Resolver check: does this workload envelope fit the synthesized design?
 *
 *  - `satisfied`: same workload hash, envelope within capacity — nothing to do.
 *  - `same-design-fits`: workload CHANGED but every demand is within the
 *    design capacity envelope — same RTL stands; only re-run checks and the
 *    M2 sizing confirmation. This is the common case, and why workloads do
 *    not trigger RTL regeneration.
 *  - `needs-re-synthesis`: any demand exceeds capacity — the design must be
 *    re-synthesized for a larger envelope. `exceeded` names the dimensions.
 */
export function checkWorkloadFit(
  incomingHash: string,
  design: FitDesign,
  envelope: WorkloadEnvelope,
): FitVerdict {
  const capacity = design.envelope;
  const checks: FitVerdict['checks'] = [
    { dimension: 'outstanding (M2 max_outstanding)', demand: Math.ceil(envelope.outstandingDemand), capacity: design.m2.maxOutstanding, fits: Math.ceil(envelope.outstandingDemand) <= design.m2.maxOutstanding },
    { dimension: 'burstiness (M2 split_at)', demand: Math.ceil(envelope.burstiness), capacity: design.m2.splitAt, fits: Math.ceil(envelope.burstiness) <= design.m2.splitAt },
    { dimension: 'concurrency', demand: Math.ceil(envelope.concurrency), capacity: capacity.maxConcurrency, fits: Math.ceil(envelope.concurrency) <= capacity.maxConcurrency },
    { dimension: 'dependency ordering', demand: Math.ceil(envelope.dependencyCount), capacity: capacity.maxDependencies, fits: Math.ceil(envelope.dependencyCount) <= capacity.maxDependencies },
    { dimension: 'latency budget (ns)', demand: envelope.latencyBudgetNs, capacity: capacity.latencyAchievedNs, fits: envelope.latencyBudgetNs >= capacity.latencyAchievedNs },
    { dimension: 'bandwidth (GiB/s)', demand: envelope.bandwidthDemandGbps, capacity: capacity.bandwidthCapacityGbps, fits: envelope.bandwidthDemandGbps <= capacity.bandwidthCapacityGbps },
  ];
  const exceeded = checks.filter(check => !check.fits)
    .map(check => `${check.dimension}: needs ${check.demand}, design carries ${check.capacity}`);
  const status: FitVerdictStatus = exceeded.length > 0
    ? 'needs-re-synthesis'
    : incomingHash === design.workloadHash
      ? 'satisfied'
      : 'same-design-fits';
  return { status, checks, exceeded };
}
