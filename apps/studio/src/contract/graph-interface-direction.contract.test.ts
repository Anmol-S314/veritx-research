/** Port capacity and direction pairing (tracker M1-28).
 *
 *  Direction is a DECLARED property of an interface and is never inferred from
 *  the node's `role`/AgentKind (veritx_dse/model/agent_interface.py). Oversub-
 *  scribed ports and incompatible pairings are reported precisely, with a
 *  stable code and the object at fault.
 */
import { describe, expect, it } from 'vitest';
import { hasErrors, validateProject, type GraphNode, type LoomProject, type ProjectIssue } from '../graph/project';
import { directionPairProblem } from '../graph/interfaceRole';
import { parseProjectDocument, serializeProjectDocument, wrapProjectDocument } from '../project/document';

function node(id: string, extra: Partial<GraphNode> = {}): GraphNode {
  return { id, x: 0, y: 0, role: 'nic', ports: 5, ...extra };
}
function edge(id: string, src: string, dst: string): LoomProject['edges'][number] {
  return { id, src, dst, width: 512, pipelineStages: 1, vcClass: 0 };
}
function doc(nodes: GraphNode[], edges: LoomProject['edges']): LoomProject {
  return { schemaVersion: 1, presetHint: null, nodes, edges };
}
const codes = (issues: ProjectIssue[]): string[] => issues.map((i) => i.code);
const find = (issues: ProjectIssue[], code: string): ProjectIssue | undefined => issues.find((i) => i.code === code);

describe('M1-28: direction pairing capability model', () => {
  it('is legal when one side can issue and the other can receive', () => {
    expect(directionPairProblem('INITIATOR', 'TARGET')).toBeNull();
    expect(directionPairProblem('TARGET', 'INITIATOR')).toBeNull();
    expect(directionPairProblem('STREAM_SOURCE', 'STREAM_SINK')).toBeNull();
    expect(directionPairProblem('BIDIRECTIONAL', 'INITIATOR')).toBeNull();
    expect(directionPairProblem('BIDIRECTIONAL', 'TARGET')).toBeNull();
  });

  it('is illegal when neither side can receive the other', () => {
    for (const [a, b] of [
      ['INITIATOR', 'INITIATOR'], ['TARGET', 'TARGET'],
      ['STREAM_SOURCE', 'STREAM_SOURCE'], ['STREAM_SINK', 'STREAM_SINK'],
      ['INITIATOR', 'STREAM_SOURCE'], ['TARGET', 'STREAM_SINK'],
    ] as const) {
      expect(directionPairProblem(a, b)).toMatch(/cannot pair/);
    }
  });

  it('is unconstrained when either endpoint declares no role', () => {
    expect(directionPairProblem(undefined, 'INITIATOR')).toBeNull();
    expect(directionPairProblem('INITIATOR', null)).toBeNull();
  });
});

describe('M1-28: direction is declared, never inferred', () => {
  it('accepts a compatible INITIATOR -> TARGET link', () => {
    const d = doc([node('a', { interfaceRole: 'INITIATOR' }), node('b', { interfaceRole: 'TARGET' })], [edge('e1', 'a', 'b')]);
    expect(validateProject(d)).toEqual([]);
  });

  it('refuses an INITIATOR -> INITIATOR link naming the offending edge', () => {
    const d = doc([node('a', { interfaceRole: 'INITIATOR' }), node('b', { interfaceRole: 'INITIATOR' })], [edge('e9', 'a', 'b')]);
    const issues = validateProject(d);
    const bad = find(issues, 'edge.direction_incompatible');
    expect(bad?.severity).toBe('error');
    expect(bad?.objectRef).toBe('$.edges[id=e9]');
    expect(bad?.message).toContain('INITIATOR cannot pair with INITIATOR');
    expect(hasErrors(issues)).toBe(true);
  });

  it('does not derive direction from the node role', () => {
    // Same `role` on both endpoints and no declaration -> no direction issue.
    const undeclared = doc([node('a'), node('b')], [edge('e1', 'a', 'b')]);
    expect(codes(validateProject(undeclared))).not.toContain('edge.direction_incompatible');

    // Both endpoints 'hbm_controller' but explicitly INITIATOR/TARGET -> fine.
    const declared = doc(
      [node('a', { role: 'hbm_controller', interfaceRole: 'INITIATOR' }), node('b', { role: 'hbm_controller', interfaceRole: 'TARGET' })],
      [edge('e1', 'a', 'b')],
    );
    expect(codes(validateProject(declared))).not.toContain('edge.direction_incompatible');
  });

  it('rejects an unknown declared role precisely', () => {
    const d = doc([node('a', { interfaceRole: 'GATEWAY' as never }), node('b')], [edge('e1', 'a', 'b')]);
    const bad = find(validateProject(d), 'node.interface_role');
    expect(bad?.severity).toBe('error');
    expect(bad?.objectRef).toBe('$.nodes[id=a]');
  });

  it('keeps the declared role through save/load', () => {
    const d = doc([node('a', { interfaceRole: 'BIDIRECTIONAL' }), node('b', { interfaceRole: 'INITIATOR' })], [edge('e1', 'a', 'b')]);
    const back = parseProjectDocument(serializeProjectDocument(wrapProjectDocument(d)));
    expect(back.graph.nodes.map((n) => n.interfaceRole)).toEqual(['BIDIRECTIONAL', 'INITIATOR']);
  });
});

describe('M1-28: port capacity', () => {
  it('reports oversubscription with the node at fault', () => {
    const d = doc(
      [node('a', { ports: 1 }), node('b', { ports: 5 }), node('c', { ports: 5 })],
      [edge('e1', 'a', 'b'), edge('e2', 'a', 'c')],
    );
    const bad = find(validateProject(d), 'node.ports_oversubscribed');
    expect(bad?.severity).toBe('error');
    expect(bad?.objectRef).toBe('$.nodes[id=a]');
    expect(bad?.message).toMatch(/2 incident edges exceed 1 ports/);
  });

  it('accepts a node with exactly ports incident edges', () => {
    const d = doc(
      [node('a', { ports: 2 }), node('b', { ports: 5 }), node('c', { ports: 5 })],
      [edge('e1', 'a', 'b'), edge('e2', 'a', 'c')],
    );
    expect(codes(validateProject(d))).not.toContain('node.ports_oversubscribed');
  });
});
