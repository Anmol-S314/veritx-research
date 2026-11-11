import { describe, expect, it } from 'vitest';
import { redactIdentityText, withoutIdentity } from './format';

const digest = 'a'.repeat(64);

describe('evidence preview identity redaction', () => {
  it('drops identity keys and hash-valued fields without touching measurements', () => {
    const preview = withoutIdentity({
      run_id: 'run-1',
      binary_sha256: digest,
      config_hash: null,
      nested: { evidence_id: `sha256:${digest}`, note: 'kept' },
      list: [{ trace_sha256: digest, size: 4 }],
      items: [digest],
    });
    expect(preview).toEqual({ run_id: 'run-1', nested: { note: 'kept' }, list: [{ size: 4 }], items: ['[identity omitted]'] });
  });

  it('redacts identity looks in truncated text previews', () => {
    const text = redactIdentityText(`{"binary_sha256":"${digest}","size":4,"evidence_id":"sha256:${digest}"`);
    expect(text).not.toMatch(/sha256|[0-9a-f]{40}/i);
    expect(text).toContain('"size":4');
  });
});
