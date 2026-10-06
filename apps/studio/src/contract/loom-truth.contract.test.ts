/** Loom truth-foundation contract tests (fixtures only — no engine, no network).
 *
 * Three guarantees that the reference product cannot make and that Loom must:
 *
 *  1. CAPABILITY TRUTH. A client must not decide capability. Every capability
 *     the UI could offer comes from one server registry, and a capability that
 *     is not implemented is named as such rather than inferred from a topology
 *     or model name.
 *  2. PROVENANCE. A value that claims to be measured must name the run and
 *     backend that produced it, and only a measured value may be presented as
 *     a result.
 *  3. LIVE / DEMO ISOLATION. A fixture value must never reach a live project.
 *
 * The python side owns the vocabulary (veritx_dse.application.loom_capability
 * and .value_provenance); this suite pins that the TypeScript client mirrors it
 * rather than re-inventing it, which is where the two would otherwise drift.
 *
 * These rules are static source invariants, so they read the sources through
 * Vite's own glob rather than the filesystem — no extra type dependency, and
 * the set of files checked is exactly the set the bundler can see.
 */
import { describe, expect, it } from 'vitest';

/** Every production source file, keyed by its path relative to `src/`.
 *  Test files are excluded: they are allowed to mention the vocabulary. */
const SOURCES: Record<string, string> = import.meta.glob(
  ['../**/*.ts', '../**/*.tsx'],
  { query: '?raw', import: 'default', eager: true },
);

const FILES = Object.entries(SOURCES)
  .filter(([path]) => !/\.contract\.test\.tsx?$/.test(path) && !/__snapshots__/.test(path))
  .map(([path]) => path);

const READ = (path: string): string => SOURCES[path];

// Regexes live at module scope on purpose: a literal built inside the filter
// callback is re-evaluated per file, which is both slower and a place for the
// rule to differ from what it reads like.
const DECLARES_CAPABILITY_VOCABULARY =
  /export (const|type|enum)\s+\w*(CapabilityStatus|CapabilityState|CapabilityVerdict)\w*/;
const ASSIGNS_BARE_VERDICT =
  /(?:const|let|var)\s+\w+\s*(?::[^=]+)?=\s*['"](READY|PARTIAL|BLOCKED|NOT_IMPLEMENTED)['"]\s*;/;
const VERDICT_LITERAL =
  /['"](READY|PARTIAL|BLOCKED|UNSUPPORTED|NOT_IMPLEMENTED|NO ARTIFACT|VALIDATED)['"]/;
/** Topologies that exist as compiler kinds. `all` is deliberately absent: it is
 *  a list filter, not a topology. */
const KNOWN_FAMILIES = ['gec', 'torus', 'srota', 'mesh', 'flatfly', 'fat_tree',
  'dragonfly', 'concentrated_mesh', 'explicit', 'qtree', 'tree4', 'gec_express',
  'gec_mesh', 'gec_multidrop', 'gec_hybrid', 'fattree', 'flattened_butterfly'];

describe('capability truth is not decided in the client', () => {
  it('reads a server vocabulary rather than declaring one', () => {
    // Consuming a server status is REQUIRED: `row.readiness === 'READY'` is
    // the client rendering the engine's verdict, which is correct. What it
    // must not do is DECLARE the vocabulary — which would be a second
    // authority — or ASSIGN a verdict the server never returned.
    const offenders = FILES.filter((path) => {
      const src = READ(path);
      return DECLARES_CAPABILITY_VOCABULARY.test(src)
        || ASSIGNS_BARE_VERDICT.test(src);
    });
    expect(offenders).toEqual([]);
  });

  it('never maps a topology family name onto a capability verdict', () => {
    // Branching on a family name is legitimate for PRESENTATION — rendering a
    // torus wrap link, laying out a fat tree. Branching on one to decide what
    // the user may DO is the defect: that decision belongs to the server
    // registry. So the probe is a comparison against a KNOWN TOPOLOGY FAMILY in
    // a file that also emits a verdict literal.
    const offenders = FILES.filter((path) => {
      const src = READ(path);
      const comparesFamily = KNOWN_FAMILIES.some((family) => (
        new RegExp(
          `(?:family|topology|topology_family)\\s*={2,3}\\s*['"]${family}['"]`,
        ).test(src)
      ));
      return comparesFamily && VERDICT_LITERAL.test(src);
    });
    expect(offenders).toEqual([]);
  });
});

describe('demo isolation', () => {
  it('fixtures are reachable only from the offline demonstration', () => {
    const allowed = new Set(['../fixtures.ts', '../pages/offline.tsx']);
    const offenders = FILES.filter((path) => (
      /from '\.\.\/fixtures'|from '\.\/fixtures'|from '\.\.\/\.\.\/fixtures'/
        .test(READ(path)) && !allowed.has(path)
    ));
    expect(offenders).toEqual([]);
  });

  it('no live page imports the fixture module', () => {
    const offenders = FILES.filter((path) => (
      path.startsWith('../pages/')
      && path !== '../pages/offline.tsx'
      && /FIXTURES/.test(READ(path))
    ));
    expect(offenders).toEqual([]);
  });

  it('offline mode replaces the whole app rather than degrading a live view', () => {
    // The whole-app replacement is what stops a live project from ever being
    // rendered from a fixture. A per-view fallback would not.
    expect(READ('../App.tsx'))
      .toMatch(/mode === 'offline'\) return <OfflineDemo \/>/);
  });

  it('no reference screenshot value appears as a literal in a Loom view', () => {
    // The reference product's demo constants. One of these appearing in a Loom
    // view is either coincidence or an inherited hard-coded value; either way
    // it must be argued for, not assumed.
    const FORBIDDEN = [
      'Mixtral', 'MoE All-to-All', '1024b', 'TSMC', 'N3E', '6.8 Tbps',
      '2048 Gbps', 'Zero-Trust', '112 links', '36.8', '140B',
    ];
    const offenders: string[] = [];
    for (const path of FILES.filter((p) => p.startsWith('../pages/loom/'))) {
      const src = READ(path);
      for (const token of FORBIDDEN) {
        if (src.includes(token)) offenders.push(`${path}: ${token}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('counts have one source', () => {
  it('no Loom view hard-codes an agent, link or channel count', () => {
    // Counts must come from an artifact. A bare count literal in a view is the
    // mechanism behind the reference's "64 agents" versus "64 of 16" defect.
    const offenders: string[] = [];
    for (const path of FILES.filter((p) => p.startsWith('../pages/loom/'))) {
      const hit = READ(path).match(/(\{|\(|,|:)\s*(64|72|81|112|288|624|768)\s*[,)}]/);
      if (hit) offenders.push(`${path}: ${hit[0].trim()}`);
    }
    expect(offenders).toEqual([]);
  });
});