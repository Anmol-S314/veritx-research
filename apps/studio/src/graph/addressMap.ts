/** Address-map analysis over the local authoring graph (tracker M3-23/M3-24).
 *
 *  Pure and deterministic. It reads the authored address windows carried on
 *  `agents[].ports[].addressWindows` — the same windows the agent/port
 *  inspector edits and `validateProject` range-checks — and derives the map a
 *  reader needs to see: the mapped intervals, overlaps, internal holes,
 *  coverage, and initiator ports that map no address at all.
 *
 *  It makes no claim about a compiled decoder, a vendor IP, or physical
 *  placement. A window is authoring intent; this module only reports how the
 *  authored intervals relate to one another.
 */
import type { AgentRole, LoomProject } from './project';

export interface AddressWindowRow {
  /** Stable key: agent / port / window index. */
  key: string;
  nodeId: string;
  agentId: string;
  portId: string;
  role: AgentRole;
  index: number;
  base: bigint;
  /** Exclusive end: base + size. */
  end: bigint;
  size: bigint;
  baseText: string;
  sizeText: string;
  permissions: ('read' | 'write')[];
  /** Declared address width, or the 64-bit default the validator uses. */
  addressWidth: number;
  /** The window does not fit its declared address width. */
  exceedsWidth: boolean;
}

export interface AddressOverlap {
  a: AddressWindowRow;
  b: AddressWindowRow;
  /** Overlapping byte count. */
  bytes: bigint;
}

export interface AddressHole {
  from: bigint;
  to: bigint;
  bytes: bigint;
}

export interface UnmappedInitiator {
  nodeId: string;
  agentId: string;
  portId: string;
  role: AgentRole;
}

export interface AddressMapReport {
  /** Every authored window, every role, in document order. */
  rows: AddressWindowRow[];
  /** target / bidirectional windows — the intervals the map is drawn from. */
  mapped: AddressWindowRow[];
  overlaps: AddressOverlap[];
  /** Gaps between mapped intervals; the leading and trailing space is not a hole. */
  holes: AddressHole[];
  /** Union of the mapped intervals, in bytes. */
  mappedBytes: bigint;
  /** Bytes inside the holes. */
  uncoveredBytes: bigint;
  /** last.end - first.base across the mapped set, in bytes (0n when empty). */
  spanBytes: bigint;
  unmappedInitiators: UnmappedInitiator[];
  /** Windows whose base/size text is not a hexadecimal quantity. */
  malformed: number;
  /** Distinct declared address widths among mapped rows, ascending. */
  addressWidths: number[];
  /** Distinct nodes that own at least one mapped window. */
  mappedNodes: number;
}

const HEX = /^0x[0-9a-fA-F]+$/;

/** Parse a hexadecimal quantity, or null when the text is not one. Never
 *  coerces a malformed string to a number. */
export function parseHexQuantity(text: unknown): bigint | null {
  if (typeof text !== 'string' || !HEX.test(text)) return null;
  try {
    return BigInt(text);
  } catch {
    return null;
  }
}

const compareRow = (a: AddressWindowRow, b: AddressWindowRow): number =>
  a.base < b.base ? -1 : a.base > b.base ? 1 : a.key < b.key ? -1 : a.key > b.key ? 1 : 0;

/** The mapped interval rows (target / bidirectional), matching the scope the
 *  project validator cross-checks for overlap. */
export function mappedRows(rows: readonly AddressWindowRow[]): AddressWindowRow[] {
  return rows.filter((row) => row.role === 'target' || row.role === 'bidirectional');
}

export function analyzeAddressMap(project: Pick<LoomProject, 'agents'>): AddressMapReport {
  const rows: AddressWindowRow[] = [];
  let malformed = 0;

  for (const agent of project.agents ?? []) {
    for (const port of agent.ports) {
      const addressWidth = typeof port.addressWidth === 'number' && port.addressWidth > 0
        ? port.addressWidth : 64;
      const limit = 1n << BigInt(addressWidth);
      (port.addressWindows ?? []).forEach((window, index) => {
        const base = parseHexQuantity(window.base);
        const size = parseHexQuantity(window.size);
        if (base === null || size === null || size <= 0n) { malformed += 1; return; }
        const end = base + size;
        rows.push({
          key: `${agent.id}/${port.id}/${index}`,
          nodeId: agent.nodeId,
          agentId: agent.id,
          portId: port.id,
          role: port.role,
          index,
          base,
          end,
          size,
          baseText: window.base,
          sizeText: window.size,
          permissions: [...window.permissions],
          addressWidth,
          exceedsWidth: base >= limit || end > limit,
        });
      });
    }
  }

  const mapped = mappedRows(rows).slice().sort(compareRow);

  // Overlaps: with rows sorted by base, a later row can only overlap an earlier
  // one while its base is below that earlier row's exclusive end.
  const overlaps: AddressOverlap[] = [];
  for (let i = 0; i < mapped.length; i += 1) {
    for (let j = i + 1; j < mapped.length; j += 1) {
      if (mapped[j]!.base >= mapped[i]!.end) break;
      const start = mapped[j]!.base > mapped[i]!.base ? mapped[j]!.base : mapped[i]!.base;
      const stop = mapped[j]!.end < mapped[i]!.end ? mapped[j]!.end : mapped[i]!.end;
      if (stop > start) overlaps.push({ a: mapped[i]!, b: mapped[j]!, bytes: stop - start });
    }
  }

  // Merge the mapped intervals so coverage and internal holes are read from one
  // canonical union, not recomputed per consumer.
  const merged: { from: bigint; to: bigint }[] = [];
  for (const row of mapped) {
    const last = merged[merged.length - 1];
    if (last && row.base <= last.to) {
      if (row.end > last.to) last.to = row.end;
    } else {
      merged.push({ from: row.base, to: row.end });
    }
  }
  let mappedBytes = 0n;
  const holes: AddressHole[] = [];
  let uncoveredBytes = 0n;
  for (let i = 0; i < merged.length; i += 1) {
    mappedBytes += merged[i]!.to - merged[i]!.from;
    const next = merged[i + 1];
    if (next && next.from > merged[i]!.to) {
      const bytes = next.from - merged[i]!.to;
      holes.push({ from: merged[i]!.to, to: next.from, bytes });
      uncoveredBytes += bytes;
    }
  }
  const spanBytes = merged.length > 0
    ? merged[merged.length - 1]!.to - merged[0]!.from : 0n;

  // An initiator or bidirectional port that maps no address cannot initiate
  // addressed traffic. Reported, never repaired here.
  const unmappedInitiators: UnmappedInitiator[] = [];
  for (const agent of project.agents ?? []) {
    for (const port of agent.ports) {
      if (port.role !== 'initiator' && port.role !== 'bidirectional') continue;
      if ((port.addressWindows ?? []).length === 0) {
        unmappedInitiators.push({ nodeId: agent.nodeId, agentId: agent.id, portId: port.id, role: port.role });
      }
    }
  }

  const addressWidths = [...new Set(mapped.map((row) => row.addressWidth))].sort((a, b) => a - b);
  const mappedNodes = new Set(mapped.map((row) => row.nodeId)).size;

  return {
    rows, mapped, overlaps, holes, mappedBytes, uncoveredBytes, spanBytes,
    unmappedInitiators, malformed, addressWidths, mappedNodes,
  };
}

/** Human-readable hex without a sign or a `n` suffix. */
export const hex = (value: bigint): string => `0x${value.toString(16)}`;
