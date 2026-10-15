/** Golden project fixtures (tracker M0-20/M0-21).
 *
 *  Every fixture under `apps/studio/fixtures/projects/` validates against the
 *  frozen v1 document contract (M0-20) and survives
 *  load -> edit -> save -> reload with semantic equality (M0-21). If a fixture
 *  fails here, the v1 contract was broken, not the fixture.
 *
 *  The fixtures are frozen artifacts: a small custom graph, an 8x8 mesh, a
 *  multi-domain graph, a floorplanned graph and a workload-bound graph. To
 *  regenerate them after an intentional v1 change, build the same five
 *  documents from `buildPreset` + the `wrapProjectDocument` envelope and write
 *  `JSON.stringify(canonicalizeProjectDocument(doc), null, 2) + "\n"`.
 *
 *  The raw text is read through Vite's glob (as `loom-truth` does) so the test
 *  needs no Node type dependency and checks exactly the bytes the bundler sees. */
import { describe, expect, it } from 'vitest';
import {
  canonicalizeProjectDocument,
  fingerprintProjectDocument,
  parseProjectDocument,
  serializeProjectDocument,
  validateProjectDocument,
  type ProjectDocument,
} from '../project/document';

const RAW: Record<string, string> = import.meta.glob(
  '../../fixtures/projects/*.json',
  { query: '?raw', import: 'default', eager: true },
);

const TEXT_BY_NAME: Record<string, string> = Object.fromEntries(
  Object.entries(RAW).map(([path, text]) => [path.split('/').pop()!.replace(/\.json$/, ''), text]),
);

const fixtureNames = Object.keys(TEXT_BY_NAME).sort();
const rawOf = (name: string): string => TEXT_BY_NAME[name];

/** One row per fixture so `it.each` infers a single `string` argument. */
const fixtureRows: [string][] = fixtureNames.map((name) => [name]);

/** A deterministic, contract-legal edit: bump the first node's x by 1 and
 *  rename the project. Never touches referential integrity. */
const edit = (doc: ProjectDocument): ProjectDocument => {
  const next = JSON.parse(JSON.stringify(doc)) as ProjectDocument;
  if (next.graph.nodes.length > 0) next.graph.nodes[0].x += 1;
  next.metadata = { ...next.metadata, name: `${next.metadata.name ?? 'fixture'} (edited)` };
  return next;
};

describe('M0-20: every golden fixture validates against the v1 contract', () => {
  it('ships the required fixture set', () => {
    expect(fixtureNames).toEqual([
      'floorplanned', 'mesh-8x8', 'multi-domain', 'small-custom', 'workload-bound',
    ]);
  });

  it.each(fixtureRows)('%s is valid, current and canonical', (name) => {
    const text = rawOf(name);
    expect(text.endsWith('\n')).toBe(true);
    const doc = parseProjectDocument(text);
    expect(doc.schema_version).toBe(1);
    expect(validateProjectDocument(doc)).toEqual([]);
    // On-disk text is already the canonical form: re-serializing is a no-op.
    expect(serializeProjectDocument(doc)).toBe(text);
  });
});

describe('M0-21: load -> edit -> save -> reload preserves semantic equality', () => {
  it.each(fixtureRows)('%s round-trips an edit', (name) => {
    const original = parseProjectDocument(rawOf(name));
    const edited = edit(original);

    const saved = serializeProjectDocument(edited);
    const reloaded = parseProjectDocument(saved);

    expect(fingerprintProjectDocument(reloaded)).toBe(fingerprintProjectDocument(edited));
    expect(canonicalizeProjectDocument(reloaded)).toEqual(canonicalizeProjectDocument(edited));
    // The edit is real: the reloaded document differs from the untouched file.
    expect(fingerprintProjectDocument(reloaded)).not.toBe(fingerprintProjectDocument(original));
  });

  it.each(fixtureRows)('%s is stable across repeated loads', (name) => {
    const a = parseProjectDocument(rawOf(name));
    const b = parseProjectDocument(rawOf(name));
    expect(fingerprintProjectDocument(a)).toBe(fingerprintProjectDocument(b));
  });
});
