import { describe, expect, it } from 'vitest';
import { parseTraceJsonl, parseTraceJsonlResult, validateTraceEvent, type TraceEventV1 } from '../graph/trace';
import SCHEMA from '../../../../contracts/loom/v1/trace-event.schema.json';

describe('trace.jsonl v1 contract', () => {
  const valid: TraceEventV1 = { schemaVersion: 1, cycle: 42, metricFamily: 'edge_utilization', trafficClass: 'bulk', value: 0.75, edge_id: 'edge-a', phaseId: 'phase-1', runId: 'run-1' };
  it('requires event version, cycle, metric family, traffic class, value and stable node/edge key', () => {
    expect(validateTraceEvent(valid)).toEqual([]);
    expect(validateTraceEvent({ ...valid, node_id: 'node-a' })).toEqual([]);
    expect(validateTraceEvent({ ...valid, edge_id: undefined })).toMatchObject([expect.objectContaining({ code: 'LOOM_TRACE_INVALID', message: 'event must reference node_id or edge_id', objectRef: '$' })]);
    expect(SCHEMA.required).toEqual(expect.arrayContaining(['cycle', 'metricFamily', 'trafficClass']));
    expect(SCHEMA.anyOf).toEqual([{ required: ['node_id'] }, { required: ['edge_id'] }]);
  });
  it('parses JSONL preserving event identity and optional run/phase metadata', () => {
    const parsed = parseTraceJsonl(`${JSON.stringify(valid)}\n${JSON.stringify({ ...valid, node_id: 'node-a', edge_id: undefined })}\n`);
    expect(parsed.map(e => [e.node_id, e.edge_id])).toEqual([[undefined, 'edge-a'], ['node-a', undefined]]);
    expect(parsed[0].phaseId).toBe('phase-1');
  });
  it('rejects a corrupt line with exact 1-based line and never returns partial results', () => {
    expect(() => parseTraceJsonl(`${JSON.stringify(valid)}\n{bad}\n`)).toThrow(/line 2: invalid JSON/);
    expect(validateTraceEvent({ ...valid, cycle: -1 })).toMatchObject([expect.objectContaining({ code: 'LOOM_TRACE_INVALID', message: 'cycle must be a non-negative safe integer', objectRef: '$.cycle' })]);
  });
  it('returns canonical structured JSONL syntax and event findings with exact line paths', () => {
    const malformed = parseTraceJsonlResult(`${JSON.stringify(valid)}\n{bad}\n`);
    expect(malformed.ok).toBe(false);
    if (malformed.ok) throw new Error('expected JSONL refusal');
    expect(malformed.issues[0]).toMatchObject({ severity: 'error', code: 'LOOM_TRACE_INVALID', objectRef: '$.lines[2]' });
    expect(malformed.issues[0]!.message).toContain('line 2: invalid JSON');
    const invalidEvent = parseTraceJsonlResult(`${JSON.stringify({ ...valid, cycle: -1 })}`);
    expect(invalidEvent.ok).toBe(false);
    if (invalidEvent.ok) throw new Error('expected event refusal');
    expect(invalidEvent.issues[0]).toMatchObject({ severity: 'error', code: 'LOOM_TRACE_INVALID', objectRef: '$.lines[1].cycle' });
  });
});
