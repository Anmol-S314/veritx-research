/** Trace schema keyed on node_id/edge_id (P6a) + mock-trace fallback.
 * Mock traces are labelled MOCK and must never be presented as measured. */
import type { LoomProject } from './project';
import { validationIssue, type ValidationIssue } from './validation';

/** One validated record in the production JSONL trace protocol (distinct from MOCK frames). */
export interface TraceEventV1 {
  schemaVersion: 1;
  cycle: number;
  metricFamily: string;
  trafficClass: string;
  value: number;
  node_id?: string;
  edge_id?: string;
  phaseId?: string;
  runId?: string;
}
export type TraceParseResult = { ok: true; events: TraceEventV1[] } | { ok: false; issues: ValidationIssue[] };
/** @deprecated Use ValidationIssue results from parseTraceJsonlResult. */
export interface TraceParseIssue { line: number; message: string }

export function validateTraceEvent(value: unknown): ValidationIssue[] {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return [validationIssue('LOOM_TRACE_INVALID', '$', 'event must be an object')];
  }
  const e = value as Record<string, unknown>;
  const allowed = new Set(['schemaVersion', 'cycle', 'metricFamily', 'trafficClass', 'value', 'node_id', 'edge_id', 'phaseId', 'runId']);
  const issues: ValidationIssue[] = [];
  const issue = (path: string, message: string): void => { issues.push(validationIssue('LOOM_TRACE_INVALID', path, message)); };
  for (const key of Object.keys(e)) if (!allowed.has(key)) issue(`$.${key}`, `unknown field ${key}`);
  if (e.schemaVersion !== 1) issue('$.schemaVersion', 'schemaVersion must equal 1');
  if (!Number.isSafeInteger(e.cycle) || (e.cycle as number) < 0) issue('$.cycle', 'cycle must be a non-negative safe integer');
  if (typeof e.metricFamily !== 'string' || !e.metricFamily.trim()) issue('$.metricFamily', 'metricFamily must be a non-empty string');
  if (typeof e.trafficClass !== 'string' || !e.trafficClass.trim()) issue('$.trafficClass', 'trafficClass must be a non-empty string');
  if (typeof e.value !== 'number' || !Number.isFinite(e.value)) issue('$.value', 'value must be finite');
  for (const key of ['node_id', 'edge_id', 'phaseId', 'runId']) {
    if (e[key] !== undefined && (typeof e[key] !== 'string' || !e[key].trim())) issue(`$.${key}`, `${key} must be a non-empty string`);
  }
  if (e.node_id === undefined && e.edge_id === undefined) issue('$', 'event must reference node_id or edge_id');
  return issues;
}

/** Parse line-by-line, retaining exact 1-based line paths and no partial-success result. */
export function parseTraceJsonlResult(text: string): TraceParseResult {
  const events: TraceEventV1[] = [];
  const issues: ValidationIssue[] = [];
  text.split(/\r?\n/).forEach((line, index) => {
    if (!line.trim()) return;
    const lineNumber = index + 1;
    let raw: unknown;
    try { raw = JSON.parse(line); }
    catch (error) {
      issues.push(validationIssue('LOOM_TRACE_INVALID', `$.lines[${lineNumber}]`, `line ${lineNumber}: invalid JSON: ${error instanceof Error ? error.message : String(error)}`));
      return;
    }
    const errors = validateTraceEvent(raw);
    if (errors.length) for (const error of errors) {
      const eventRef = error.objectRef === '$' ? '' : error.objectRef.slice(1);
      issues.push({ ...error, message: `line ${lineNumber}: ${error.objectRef}: ${error.message}`, objectRef: `$.lines[${lineNumber}]${eventRef}` });
    }
    else events.push(raw as TraceEventV1);
  });
  return issues.length ? { ok: false, issues } : { ok: true, events };
}

/** Throwing compatibility API for existing trace consumers. */
export function parseTraceJsonl(text: string): TraceEventV1[] {
  const result = parseTraceJsonlResult(text);
  if (!result.ok) throw new Error(`invalid trace JSONL:\n${result.issues.map(issue => issue.message).join('\n')}`);
  return result.events;
}

export interface TraceFrame {
  cycle: number;
  phase: string;
  nodeLoad: Record<string, number>;
  edgeUtil: Record<string, number>;
  stalls: Record<string, number>;
}

export interface MockTrace {
  origin: 'MOCK';
  frames: TraceFrame[];
  cyclesSampled: number;
}

export interface MockTracePhase {
  kind: string;
  name?: string;
  startCycle?: number;
  durationCycles?: number;
}

/** Synthetic load values stay MOCK; phase labels appear only within explicit authored timing intervals. */
export function buildMockTrace(project: LoomProject, phases: readonly MockTracePhase[] = []): MockTrace {
  const frames: TraceFrame[] = [];
  const STEPS = 24;
  for (let s = 0; s < STEPS; s++) {
    const nodeLoad: Record<string, number> = {};
    const edgeUtil: Record<string, number> = {};
    const stalls: Record<string, number> = {};
    for (const n of project.nodes) {
      nodeLoad[n.id] = Math.round((50 + 40 * Math.sin(s / 3 + n.x / 200) + 10 * Math.cos(s / 2 + n.y / 200)) * 10) / 10;
    }
    for (const e of project.edges) {
      const hot = (s % 6 === 0 && e.vcClass === 0) ? 35 : 0;
      edgeUtil[e.id] = Math.round((30 + 25 * Math.sin(s / 4 + e.id.length) + hot) * 10) / 10;
      stalls[e.id] = Math.max(0, Math.round(edgeUtil[e.id] - 55));
    }
    const cycle = s * 100;
    const activePhases = phases.filter((phase) => phase.startCycle !== undefined && phase.durationCycles !== undefined
      && cycle >= phase.startCycle && cycle < phase.startCycle + phase.durationCycles);
    const phase = activePhases.length ? activePhases.map((item) => item.name || item.kind).join(' + ') : 'unphased';
    frames.push({ cycle, phase, nodeLoad, edgeUtil, stalls });
  }
  return { origin: 'MOCK', frames, cyclesSampled: STEPS };
}

export function topCongested(trace: Pick<MockTrace, 'frames'>, frameIdx: number, n = 5): { edge: string; util: number }[] {
  const f = trace.frames[Math.min(frameIdx, trace.frames.length - 1)];
  if (!f) return [];
  return Object.entries(f.edgeUtil).sort((a, b) => b[1] - a[1]).slice(0, n).map(([edge, util]) => ({ edge, util }));
}
