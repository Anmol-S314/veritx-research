import { describe, expect, it } from 'vitest';
import { validateProject } from '../graph/project';
import { applyGraphCommand } from '../graph/history';
import { buildPreset } from '../graph/presets';
import { validateTraceEvent } from '../graph/trace';
import { validateWorkloadIssues } from '../graph/workload';
import { validateRunManifest } from '../graph/runManifest';
import { validateRunSummary } from '../graph/summary';
import SCHEMA from '../../../../contracts/loom/v1/validation-issue.schema.json';

describe('canonical validation issue v1', () => {
  it('defines stable issue fields, object references, and explicitly safe-only quick fixes', () => {
    expect(SCHEMA.required).toEqual(['severity', 'code', 'message', 'objectRef']);
    expect(SCHEMA.properties.severity.enum).toEqual(['error', 'warning', 'info']);
    expect(SCHEMA.properties.objectRef.required).toContain('path');
    expect(SCHEMA.properties.quickFix.required).toEqual(['action', 'safe']);
    expect(SCHEMA.properties.quickFix.properties.safe.const).toBe(true);
  });

  it('uses the same structured finding shape for project, workload, trace, manifest, summary and graph commands', () => {
    const graphRefusal = applyGraphCommand(buildPreset('ring-8'), { type: 'move_node', id: 'missing', x: 1, y: 1 });
    const findings = [
      ...validateProject({}),
      ...validateWorkloadIssues({ modelFamily: '', paramsB: 1, seqLen: 1, batch: 1, precision: 'fp16', phases: [] }, 0),
      ...validateTraceEvent(null),
      ...validateRunManifest({}),
      ...validateRunSummary({}),
      ...graphRefusal.issues,
    ];
    expect(findings.length).toBeGreaterThan(3);
    for (const finding of findings) {
      expect(finding).toEqual(expect.objectContaining({
        severity: 'error',
        code: expect.stringMatching(/^[A-Z][A-Z0-9_]+$/),
        message: expect.any(String),
        objectRef: expect.objectContaining({ path: expect.any(String) }),
      }));
      expect(finding.quickFix).toBeUndefined();
    }
    expect(findings.map(f => f.code)).toEqual(expect.arrayContaining([
      'LOOM_PROJECT_INVALID', 'LOOM_WORKLOAD_INVALID', 'LOOM_TRACE_INVALID', 'LOOM_RUN_MANIFEST_INVALID', 'LOOM_SUMMARY_INVALID', 'LOOM_GRAPH_COMMAND_INVALID',
    ]));
  });
});
