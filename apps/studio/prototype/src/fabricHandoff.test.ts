import { describe, expect, it } from 'vitest';
import { draftDepthFor, draftTopologyFor, handoffReason } from './fabricHandoff';

describe('catalog fabric handoff', () => {
  it('maps regular catalog meshes to the draft topology the editor can author', () => {
    expect(draftTopologyFor({ topology: 'mesh8x8', family: 'MESH', nodes: 64 })).toEqual({ kind: 'mesh', side_length: 8, concentration: 1 });
    expect(draftTopologyFor({ topology: 'torus8x8', family: 'TORUS', nodes: 64 })).toEqual({ kind: 'torus', side_length: 8, concentration: 1 });
    expect(draftTopologyFor({ topology: 'cmesh', family: 'CONCENTRATED_MESH', nodes: 64 })).toEqual({ kind: 'concentrated_mesh', side_length: 4, concentration: 4 });
  });

  it('refuses families the project editor cannot express instead of guessing dimensions', () => {
    expect(draftTopologyFor({ topology: 'fly64', family: 'FLY', nodes: 64 })).toBeNull();
    expect(draftTopologyFor({ topology: 'srota8x8', family: 'SROTA', nodes: 64 })).toBeNull();
    expect(draftTopologyFor({ topology: 'qtree', family: 'QTREE', nodes: 64 })).toBeNull();
    expect(handoffReason({ topology: 'fly64', family: 'FLY', nodes: 64, vcBufSize: 4 })).toContain('not authorable');
  });

  it('carries only an integer measured buffer depth', () => {
    expect(draftDepthFor({ topology: 'mesh8x8', vcBufSize: 4 })).toBe(4);
    expect(draftDepthFor({ topology: 'mesh8x8', vcBufSize: 0 })).toBeNull();
    expect(draftDepthFor({ topology: 'mesh8x8' })).toBeNull();
  });
});
