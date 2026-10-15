/** Stable node/edge identity rules (tracker M0-02).
 *
 *  Proves the four acceptance claims: ids survive save/load, copy/paste and
 *  migration; coordinates are never used as identifiers; fresh ids are
 *  deterministic; and malformed ids are refused with a precise code.
 */
import { describe, expect, it } from 'vitest';
import { applyGraphCommand } from '../graph/history';
import {
  GRAPH_ID_RE,
  graphIdProblem,
  nextEdgeId,
  nextNodeId,
  nextPasteToken,
  pasteClipboard,
} from '../graph/ids';
import { buildPreset } from '../graph/presets';
import { parseProject, serializeProject, validateProject, type LoomProject } from '../graph/project';
import { parseProjectDocument, serializeProjectDocument, wrapProjectDocument } from '../project/document';

const mesh = (): LoomProject => buildPreset('mesh-4x4');

describe('M0-02: id format rules', () => {
  it('accepts every production id shape and refuses the malformed ones', () => {
    for (const ok of ['n1', 'e1', 'n12-c3', 'e4-e5', 'extra', 'e-extra']) {
      expect(GRAPH_ID_RE.test(ok)).toBe(true);
      expect(graphIdProblem(ok)).toBeNull();
    }
    for (const bad of ['', '  ', 'has space', 'a'.repeat(65), 'coord:1,2', 42, null]) {
      expect(graphIdProblem(bad)).not.toBeNull();
    }
  });

  it('reports a malformed id through validateProject with a precise code', () => {
    const p = mesh();
    p.nodes[0].id = 'not an id';
    const codes = validateProject(p).map((i) => i.code);
    expect(codes).toContain('node.id_format');
  });
});

describe('M0-02: ids survive the document lifecycle', () => {
  it('survives save/load unchanged', () => {
    const p = mesh();
    const back = parseProjectDocument(serializeProjectDocument(wrapProjectDocument(p)));
    expect(back.graph.nodes.map((n) => n.id)).toEqual(p.nodes.map((n) => n.id));
    expect(back.graph.edges.map((e) => e.id)).toEqual(p.edges.map((e) => e.id));
  });

  it('survives the legacy -> v1 migration unchanged', () => {
    const p = mesh();
    const back = parseProjectDocument(JSON.stringify(p));
    expect(back.graph.nodes.map((n) => n.id)).toEqual(p.nodes.map((n) => n.id));
    expect(back.graph.edges.map((e) => e.id)).toEqual(p.edges.map((e) => e.id));
  });

  it('survives copy/paste: originals untouched, pasted ids fresh and unique', () => {
    const p = mesh();
    const clip = { nodes: p.nodes.slice(0, 3), edges: p.edges.slice(0, 2) };
    const pasted = pasteClipboard(p, clip);

    expect(p.nodes.slice(0, 3).map((n) => n.id)).toEqual(clip.nodes.map((n) => n.id));
    const originalIds = new Set(p.nodes.map((n) => n.id));
    for (const n of pasted.nodes) expect(originalIds.has(n.id)).toBe(false);
    expect(new Set(pasted.nodes.map((n) => n.id)).size).toBe(pasted.nodes.length);
    expect(new Set(pasted.edges.map((e) => e.id)).size).toBe(pasted.edges.length);

    const out = applyGraphCommand(p, { type: 'paste', nodes: pasted.nodes, edges: pasted.edges });
    expect(out.refused).toBeNull();
    for (const e of pasted.edges) {
      expect(pasted.nodes.some((n) => n.id === e.src)).toBe(true);
      expect(pasted.nodes.some((n) => n.id === e.dst)).toBe(true);
    }
  });
});

describe('M0-02: coordinates and order are never identity', () => {
  it('moving a node keeps its id', () => {
    const p = mesh();
    const before = p.nodes[0].id;
    const out = applyGraphCommand(p, { type: 'move_node', id: before, x: 9999, y: 1234 });
    expect(out.refused).toBeNull();
    expect(out.doc.nodes[0].id).toBe(before);
  });

  it('no node or edge id is a coordinate string', () => {
    const p = mesh();
    for (const n of p.nodes) {
      expect(n.id).not.toBe(`${n.x},${n.y}`);
      expect(n.id).not.toBe(`${n.x}:${n.y}`);
    }
  });

  it('mints fresh ids deterministically, never from position', () => {
    const p = mesh();
    expect(nextNodeId(p.nodes)).toBe(`n${p.nodes.length + 1}`);
    expect(nextEdgeId(p.edges)).toBe(`e${p.edges.length + 1}`);
    // Same document -> same next id; no clock/randomness involved.
    expect(nextNodeId(p.nodes)).toBe(nextNodeId(p.nodes));
    const token = nextPasteToken(p.nodes, p.edges);
    expect(nextPasteToken(p.nodes, p.edges)).toBe(token);
    // The round-trip through the flat serialize path preserves ids too.
    expect(parseProject(serializeProject(p)).nodes.map((n) => n.id)).toEqual(p.nodes.map((n) => n.id));
  });
});
