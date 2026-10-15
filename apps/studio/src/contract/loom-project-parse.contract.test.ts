import { describe, expect, it } from 'vitest';
import { buildPreset } from '../graph/presets';
import { parseProject, parseProjectResult, serializeProject } from '../graph/project';

describe('canonical project parse result', () => {
  it('returns structured canonical findings for malformed JSON', () => {
    const result = parseProjectResult('{not-json');
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('expected parse refusal');
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0]).toMatchObject({ severity: 'error', code: 'LOOM_PROJECT_INVALID', path: '$' });
    expect(result.issues[0]!.objectRef).toBe('$');
    expect(result.issues[0]!.message).toContain('invalid project JSON');
  });

  it('returns the validator findings without losing paths and preserves the throwing compatibility API', () => {
    const invalid = buildPreset('ring-8');
    invalid.edges[0]!.src = 'missing-node';
    const encoded = JSON.stringify(invalid);
    const result = parseProjectResult(encoded);
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error('expected validation refusal');
    expect(result.issues.map(issue => issue.path)).toContain('$.edges[0].src');
    expect(result.issues.every(issue => issue.severity === 'error' && issue.objectRef === issue.path)).toBe(true);
    expect(() => parseProject(encoded)).toThrow(/unknown node missing-node/);
  });

  it('returns a typed project on success and matches the existing parser', () => {
    const text = serializeProject(buildPreset('ring-8'));
    const result = parseProjectResult(text);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('expected valid project');
    expect(result.project).toEqual(parseProject(text));
  });
});
