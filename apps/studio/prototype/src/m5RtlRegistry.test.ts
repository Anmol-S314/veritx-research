import { describe, expect, it } from 'vitest';
import { artifactSize, evidenceState, prototypeFileState } from './m5RtlRegistry';

describe('research RTL evidence normalization', () => {
  it('does not promote unknown or unrecognized states', () => {
    expect(evidenceState(undefined)).toBe('Unknown');
    expect(evidenceState('UNRECOGNIZED')).toBe('UNRECOGNIZED');
    expect(prototypeFileState({ file_presence: 'UNKNOWN', verilog_status: 'MISSING' })).toBe('Presence unknown');
  });
  it('calls a current present file only present, not ready or qualified', () => {
    expect(prototypeFileState({ file_presence: 'PRESENT', verilog_status: 'PRESENT' })).toBe('Verilog present');
  });
  it('formats artifact sizes safely', () => {
    expect(artifactSize(1024)).toBe('1 KiB');
    expect(artifactSize(-1)).toBe('Size unknown');
  });
});
