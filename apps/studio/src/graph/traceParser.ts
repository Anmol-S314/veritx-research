/** Strict incremental JSONL trace reader. It never promotes malformed/unknown
 * references into renderable frames; source line numbers are retained in errors. */
import type { LoomProject } from './project';
import type { TraceFrame } from './trace';

export interface TraceIndex {
  byCycle: Map<number, number>;
  byNode: Map<string, number[]>;
  byEdge: Map<string, number[]>;
  byMetric: Map<string, number[]>;
  cycles: number[];
}
export interface ParsedTrace { frames: TraceFrame[]; index: TraceIndex }
export interface TraceParserOptions {
  unknownReferences?: 'error' | 'warn';
  /** Called after each validated frame so callers can preserve the valid prefix
   * if a later source line is corrupt. */
  onFrame?: (frame: TraceFrame, index: number) => void;
  onProgress?: (progress: { recordsIndexed: number; latestCycle: number }) => void;
}
export interface TraceWarning { line: number; message: string }
export class TraceParseError extends Error {
  constructor(readonly line: number, message: string) {
    super(`trace line ${line}: ${message}`);
    this.name = 'TraceParseError';
  }
}

const projectIds = new WeakMap<LoomProject, { nodes: Set<string>; edges: Set<string> }>();
function idsFor(project: LoomProject): { nodes: Set<string>; edges: Set<string> } {
  const existing = projectIds.get(project);
  if (existing) return existing;
  const ids = { nodes: new Set(project.nodes.map(n => n.id)), edges: new Set(project.edges.map(e => e.id)) };
  projectIds.set(project, ids);
  return ids;
}
function appendIndex(index: Map<string, number[]>, id: string, frameIndex: number): void {
  const entries = index.get(id);
  if (entries) entries.push(frameIndex);
  else index.set(id, [frameIndex]);
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function metricMap(value: unknown, line: number, name: string): Record<string, number> {
  if (!record(value)) throw new TraceParseError(line, `${name} must be an object keyed by stable IDs`);
  const out: Record<string, number> = {};
  for (const [id, raw] of Object.entries(value)) {
    if (!id || typeof raw !== 'number' || !Number.isFinite(raw) || raw < 0) {
      throw new TraceParseError(line, `${name}.${id} must be a finite non-negative number`);
    }
    out[id] = raw;
  }
  return out;
}

export function parseTraceLines(lines: Iterable<string>, project: LoomProject, options: TraceParserOptions = {}): ParsedTrace & { warnings: TraceWarning[] } {
  const { nodes: nodeIds, edges: edgeIds } = idsFor(project);
  const frames: TraceFrame[] = [];
  const warnings: TraceWarning[] = [];
  const index: TraceIndex = { byCycle: new Map(), byNode: new Map(), byEdge: new Map(), byMetric: new Map(), cycles: [] };
  let lineNumber = 0;
  for (const rawLine of lines) {
    lineNumber++;
    const text = rawLine.trim();
    if (!text) continue;
    let value: unknown;
    try { value = JSON.parse(text); }
    catch (error) { throw new TraceParseError(lineNumber, `invalid JSON: ${error instanceof Error ? error.message : String(error)}`); }
    if (!record(value)) throw new TraceParseError(lineNumber, 'record must be an object');
    if (!Number.isSafeInteger(value.cycle) || (value.cycle as number) < 0) throw new TraceParseError(lineNumber, 'cycle must be a non-negative safe integer');
    const cycle = value.cycle as number;
    if (index.cycles.length && cycle <= index.cycles[index.cycles.length - 1]) throw new TraceParseError(lineNumber, `cycle ${cycle} is not strictly greater than previous cycle ${index.cycles[index.cycles.length - 1]}`);
    const nodeLoad = metricMap(value.nodeLoad, lineNumber, 'nodeLoad');
    const edgeUtil = metricMap(value.edgeUtil, lineNumber, 'edgeUtil');
    const stalls = metricMap(value.stalls, lineNumber, 'stalls');
    if (typeof value.phase !== 'string' || !value.phase.trim()) throw new TraceParseError(lineNumber, 'phase must be a non-empty string');
    for (const [kind, metrics, ids] of [['node', nodeLoad, nodeIds], ['edge', edgeUtil, edgeIds], ['edge', stalls, edgeIds]] as const) {
      for (const id of Object.keys(metrics)) if (!ids.has(id)) {
        const message = `unknown ${kind}_id ${id}`;
        if (options.unknownReferences === 'warn') {
          warnings.push({ line: lineNumber, message });
          // A warning must not make a foreign identifier drawable by a caller.
          delete metrics[id];
        } else throw new TraceParseError(lineNumber, message);
      }
    }
    const frameIndex = frames.length;
    frames.push({ cycle, phase: value.phase, nodeLoad, edgeUtil, stalls });
    index.byCycle.set(cycle, frameIndex);
    index.cycles.push(cycle);
    for (const id of Object.keys(nodeLoad)) appendIndex(index.byNode, id, frameIndex);
    for (const id of new Set([...Object.keys(edgeUtil), ...Object.keys(stalls)])) appendIndex(index.byEdge, id, frameIndex);
    if (Object.keys(nodeLoad).length) appendIndex(index.byMetric, 'nodeLoad', frameIndex);
    if (Object.keys(edgeUtil).length) appendIndex(index.byMetric, 'edgeUtil', frameIndex);
    if (Object.keys(stalls).length) appendIndex(index.byMetric, 'stalls', frameIndex);
  }
  if (frames.length === 0) throw new TraceParseError(Math.max(1, lineNumber), 'trace contains no records');
  return { frames, index, warnings };
}

/** Byte-stream-friendly JSONL decoder. Carries partial UTF-8/lines between reads. */
export async function* decodeTraceStream(stream: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const pieces = pending.split(/\r?\n/);
      pending = pieces.pop() ?? '';
      yield* pieces;
      if (done) break;
    }
    if (pending.length) yield pending;
  } finally { reader.releaseLock(); }
}

export async function parseTraceStream(stream: ReadableStream<Uint8Array>, project: LoomProject, options?: TraceParserOptions): Promise<ParsedTrace & { warnings: TraceWarning[] }> {
  // Consume and discard each decoded line immediately: retain only normalized
  // frames/index, never a second full copy of the source JSONL file.
  const result: ParsedTrace & { warnings: TraceWarning[] } = {
    frames: [], warnings: [],
    index: { byCycle: new Map(), byNode: new Map(), byEdge: new Map(), byMetric: new Map(), cycles: [] },
  };
  let sourceLine = 0;
  for await (const line of decodeTraceStream(stream)) {
    sourceLine++;
    if (!line.trim()) continue;
    let one: ReturnType<typeof parseTraceLines>;
    try { one = parseTraceLines([line], project, options); }
    catch (error) {
      if (error instanceof TraceParseError) throw new TraceParseError(sourceLine, error.message.replace(/^trace line 1: /, ''));
      throw error;
    }
    const frame = one.frames[0];
    const previousCycle = result.index.cycles[result.index.cycles.length - 1];
    if (previousCycle !== undefined && frame.cycle <= previousCycle) {
      throw new TraceParseError(sourceLine, `cycle ${frame.cycle} is not strictly greater than previous cycle ${previousCycle}`);
    }
    const frameIndex = result.frames.length;
    result.frames.push(frame);
    options?.onFrame?.(frame, frameIndex);
    result.index.cycles.push(frame.cycle);
    result.index.byCycle.set(frame.cycle, frameIndex);
    for (const id of Object.keys(frame.nodeLoad)) appendIndex(result.index.byNode, id, frameIndex);
    for (const id of new Set([...Object.keys(frame.edgeUtil), ...Object.keys(frame.stalls)])) appendIndex(result.index.byEdge, id, frameIndex);
    if (Object.keys(frame.nodeLoad).length) appendIndex(result.index.byMetric, 'nodeLoad', frameIndex);
    if (Object.keys(frame.edgeUtil).length) appendIndex(result.index.byMetric, 'edgeUtil', frameIndex);
    if (Object.keys(frame.stalls).length) appendIndex(result.index.byMetric, 'stalls', frameIndex);
    options?.onProgress?.({ recordsIndexed: frameIndex + 1, latestCycle: frame.cycle });
    result.warnings.push(...one.warnings.map(w => ({ ...w, line: sourceLine })));
  }
  if (result.frames.length === 0) throw new TraceParseError(Math.max(1, sourceLine), 'trace contains no records');
  return result;
}
