import { describe, expect, it } from 'vitest';
import SUMMARY from '../../../../contracts/loom/v1/summary.schema.json';
import { validateRunSummary } from '../graph/summary';
import { PROVENANCE_STATES } from '../graph/provenance';

describe('summary.json v1 contract', () => {
  it('requires stable run/backend provenance, aggregate metrics and warnings', () => {
    expect(SUMMARY.required).toEqual(expect.arrayContaining(['schemaVersion', 'runId', 'backend', 'metrics', 'warnings']));
    expect(SUMMARY.properties.backend.required).toEqual(['id', 'version', 'provenance']);
    expect(SUMMARY.properties.backend.properties.provenance.enum).toEqual(PROVENANCE_STATES);
    expect(SUMMARY.properties.metrics.items.properties.provenance.enum).toEqual(PROVENANCE_STATES);
    expect(SUMMARY.properties.metrics.items.required).toEqual(expect.arrayContaining(['name', 'value', 'unit', 'provenance', 'unsupported', 'estimated']));
    expect(SUMMARY.properties.warnings.items.required).toEqual(['code', 'severity', 'message']);
  });
  it('encodes unknowns as null+unsupported and estimated values with explicit provenance', () => {
    const metrics = SUMMARY.properties.metrics.items;
    expect(metrics.properties.value.type).toEqual(['number', 'null']);
    expect(metrics.allOf[0]!.then!.properties!.value!.type).toBe('null');
    expect(metrics.allOf[1]!.then!.properties!.provenance!.const).toBe('estimated');
  });

  it('validates summaries using canonical issues and rejects unsupported numeric claims', () => {
    const valid = {
      schemaVersion: 1, runId: 'run-1',
      backend: { id: 'demo', version: null, provenance: 'mocked' },
      metrics: [
        { name: 'latency', value: null, unit: 'ns', provenance: 'unsupported', unsupported: true, estimated: false },
        { name: 'energy', value: 2.5, unit: 'nJ', provenance: 'estimated', unsupported: false, estimated: true },
      ],
      warnings: [{ code: 'BACKEND_GAP', severity: 'warning', message: 'No production backend attached.' }],
    };
    expect(validateRunSummary(valid)).toEqual([]);
    const invalid = { ...valid, metrics: [
      { ...valid.metrics[0], value: 7 },
      { ...valid.metrics[1], provenance: 'measured' },
    ] };
    expect(validateRunSummary(invalid)).toMatchObject([
      { code: 'LOOM_SUMMARY_INVALID', objectRef: '$.metrics[0].value' },
      { code: 'LOOM_SUMMARY_INVALID', objectRef: '$.metrics[1].provenance' },
    ]);
  });
});
