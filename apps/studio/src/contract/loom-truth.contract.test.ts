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
import { SERVED_PROVENANCE as SERVED } from './servedProvenance.fixture';

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
/**
 * The invariant is AUTHORITY, not vocabulary.
 *
 * The client MUST mirror the server's status union as a TypeScript type —
 * without it the payload cannot be typed at all — and it MUST map a status to
 * a CSS tone so the row can be coloured. Neither is an authority.
 *
 * What it must not do is AUTHOR the vocabulary: ship a table pairing each
 * status with its own meaning, or a verdict literal assigned to a value the
 * server never judged. That second copy is what drifts, and a drifted
 * capability table is how a UI ends up offering something the compiler
 * cannot build.
 */
/**
 * A status -> CSS COLOUR map is presentation, not authority: the statuses in
 * it arrive from the server and the client only decides how to tint them. So
 * the refusal is narrower and sharper than "no status table": a client must
 * not PAIR a status with its own MEANING, because meaning is what a reader
 * relies on and a second copy of it is what drifts.
 */
const CLIENT_AUTHORS_STATUS_MEANING =
  /(?:const|enum)\s+\w*(CAPABILITY_)?(STATUS|VERDICT|VOCABULARY)\w*\s*(?::[^=]*)?=\s*\{[^}]*\b(meaning|means|description|explanation|label|summary)\b/i;
const CLIENT_ASSIGNS_A_VERDICT =
  /(?:const|let|var)\s+\w+\s*(?::[^=]+)?=\s*['"](READY|PARTIAL|BLOCKED|NOT_IMPLEMENTED)['"]\s*;/;
const VERDICT_LITERAL =
  /['"](READY|PARTIAL|BLOCKED|UNSUPPORTED|NOT_IMPLEMENTED|NO ARTIFACT|VALIDATED)['"]/;
/** Topologies that exist as compiler kinds. `all` is deliberately absent: it is
 *  a list filter, not a topology. */
const KNOWN_FAMILIES = ['gec', 'torus', 'srota', 'mesh', 'flatfly', 'fat_tree',
  'dragonfly', 'concentrated_mesh', 'explicit', 'qtree', 'tree4', 'gec_express',
  'gec_mesh', 'gec_multidrop', 'gec_hybrid', 'fattree', 'flattened_butterfly'];

describe('capability truth is not decided in the client', () => {
  it('reads a server vocabulary rather than authoring one', () => {
    // Consuming a server status is REQUIRED: `row.readiness === 'READY'` is
    // the client rendering the engine's verdict, which is correct, and so is
    // mirroring the union as a type. What it must not do is AUTHOR the
    // vocabulary or ASSIGN a verdict the server never returned.
    const offenders = FILES.filter((path) => {
      const src = READ(path);
      return CLIENT_AUTHORS_STATUS_MEANING.test(src)
        || CLIENT_ASSIGNS_A_VERDICT.test(src);
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
      // Reading the server row's status is not a family-authored verdict.
      const authored = src.replace(/\b\w+\.status\s*[!=]={2}\s*['"]READY['"]/g, '');
      return comparesFamily && VERDICT_LITERAL.test(authored);
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

describe('federation backend facts carry their own name', () => {
  it('serves the install probe under an explicitly-presence name', () => {
    // ProductService._backend_install_fact is a PRESENCE probe (binary
    // present / extension built), not a runtime-readiness fact — no runtime
    // probe exists. The server names it install_present, and the client
    // mirrors that name rather than re-inventing one.
    expect(READ('../api/types.ts')).toMatch(/install_present:\s*boolean/);
    expect(READ('../api/types.ts')).toMatch(/install_detail:\s*string/);
  });

  it('never names a runtime-readiness fact the server does not serve', () => {
    // `runtime_available` would assert a fact the server never computed:
    // the field it replaced was the install-presence probe. No client
    // source may carry the name.
    const offenders = FILES.filter((path) => (
      /runtime_available/.test(READ(path))
    ));
    expect(offenders).toEqual([]);
  });

  it('renders an installed column and no runtime column', () => {
    // A `runtime` column would render a fact that does not exist. Only the
    // install-presence fact gets a column.
    const src = READ('../pages/index.tsx');
    expect(src).toMatch(/<th>installed<\/th>/);
    expect(src).not.toMatch(/<th>runtime<\/th>/);
  });
});

describe('failed reads stay failed', () => {
  it('no data loader collapses an API failure to null', () => {
    // `.catch(() => null)` destroys the difference between ABSENT (the
    // artifact was never produced — a fact the UI may state) and FAILED
    // (the read broke — a fact the UI must state differently). Every loader
    // must let the rejection reach the Async error state so views can render
    // loading / ready(value) / ready(null) / error as four states.
    const offenders = FILES.filter((path) =>
      /\.catch\(\s*\(\s*\)\s*=>\s*null\s*\)/.test(READ(path)));
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
describe('displayed values carry their provenance', () => {
  it('origin words appear in Loom only inside From or the selection machinery', () => {
    // AUTHORED / DERIVED / DECLARED / MEASURED are the server's four words.
    // A view that prints one ad-hoc owns a second copy of the vocabulary,
    // and a second copy is what drifts. The two places allowed to state an
    // origin are the From component (section authority) and the selection
    // machinery (per-object authority, checked against the served map).
    const WORD = /\b(AUTHORED|DERIVED|DECLARED|MEASURED)\b/;
    const offenders: string[] = [];
    for (const path of FILES.filter((p) => p.startsWith('../pages/loom/'))) {
      if (path.endsWith('/parts.tsx')) continue;
      if (path.endsWith('/selection.ts')) continue;
      if (path.endsWith('/SelectionBar.tsx')) continue;
      // The ladder derivation in data.ts IS authority machinery: it assigns
      // the per-layer origin that From displays. Like selection.ts it is
      // exempt from the ad-hoc rule, and pinned by its own derivation tests.
      if (path.endsWith('/data.ts')) continue;
      const lines = READ(path).split('\n');
      // A From element can span lines, so track whether the scanner is
      // inside one: origin words between <From and its closing /> are the
      // component's own props, not ad-hoc vocabulary. The same holds for
      // OriginWord, the shared component per-side badges use so they never
      // reprint the vocabulary ad-hoc.
      let insideFrom = false;
      lines.forEach((line, i) => {
        if (/<From\b/.test(line)) insideFrom = true;
        const closes = insideFrom && /\/>/.test(line);
        if (!WORD.test(line)) {
          if (closes) insideFrom = false;
          return;
        }
        // A From prop, a From import, or a comment pointing at From.
        if (insideFrom) {
          if (closes) insideFrom = false;
          return;
        }
        // The shared vocabulary components, not ad-hoc words.
        if (/<OriginWord\b/.test(line)) return;
        if (/<FreshWord\b/.test(line)) return;
        if (/from '.\/parts'/.test(line) && /\bFrom\b/.test(line)) return;
        if (/^\s*(\/\/|\*)/.test(line)) return;
        offenders.push(`${path}:${i + 1}: ${line.trim().slice(0, 80)}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it('every RailSection in Loom states its authority with From', () => {
    // A section without From renders values whose source the reader must
    // guess from the prose. The prose can drift; the From line is checked by
    // the test above, so it cannot.
    //
    // RailSections that only hold controls (search, filters, view toggles)
    // or an ExtensionPoint (a panel that by construction shows no values)
    // are exempt: there is nothing whose authority needs stating.
    const offenders: string[] = [];
    for (const path of FILES.filter((p) => p.startsWith('../pages/loom/'))) {
      if (path.endsWith('/parts.tsx')) continue;
      if (path.endsWith('/index.tsx')) continue;
      if (path.endsWith('/SelectionBar.tsx')) continue;
      const src = READ(path);
      // Sections are matched open-to-close, not open-to-next-open: a left
      // rail's last section would otherwise swallow the whole stage and be
      // judged on values it never renders. RailSections never nest, so a
      // tempered match is sufficient.
      const opens = [...src.matchAll(
        /<RailSection\b[^>]*title="([^"]+)"[^>]*>((?:(?!<\/?RailSection\b)[\s\S])*)<\/RailSection>/g,
      )];
      opens.forEach((m) => {
        const title = m[1];
        const body = m[2];
        if (/<ExtensionPoint\b/.test(body) && !/<Kv\b|<table\b|<code>[^<]{2,}<\/code>/.test(body)) return;
        if (!/<Kv\b|<table\b|<SummaryStrip\b/.test(body)) return;
        // A section whose every row IS a provenance statement — each row an
        // origin word, a named artifact, or NO ARTIFACT — is the ledger
        // itself. A From line on it would restate what the rows already say.
        // Rows are split on the Kv openings because values can be JSX, not
        // just strings.
        const rows = body.split(/<Kv\b/).slice(1);
        if (rows.length > 0 && rows.every((row) =>
          /authored|derived|declared|measured|certified|attachment|no artifact|no attachment/i.test(row))) return;
        if (!/<From\b/.test(body)) offenders.push(`${path}: "${title}"`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it('every From carries data, and a null states why in its note', () => {
    // data={null} means "this section's artifact is not revision-scoped, so
    // no freshness badge by construction". Without a note saying that, null
    // is indistinguishable from a forgotten prop — so null without a note
    // fails. The tempered match spans the multiline element the same way the
    // section test does.
    const offenders: string[] = [];
    for (const path of FILES.filter((p) => p.startsWith('../pages/loom/'))) {
      const src = READ(path);
      for (const m of src.matchAll(/<From\b((?:(?!\/>)[\s\S])*)\/>/g)) {
        const body = m[1];
        if (!/data=\{/.test(body)) {
          offenders.push(`${path}: From without data`);
        } else if (/data=\{null\}/.test(body) && !/note=/.test(body)) {
          offenders.push(`${path}: From with data={null} and no note`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('From artifacts are kinds the server actually serves', () => {
    // An artifact prop the server never named is a word the reader cannot
    // check. The fixture is the served vocabulary, so this test fails when
    // either side drifts.
    const KINDS = SERVED.artifact_kinds as string[];
    const offenders: string[] = [];
    for (const path of FILES.filter((p) => p.startsWith('../pages/loom/'))) {
      const src = READ(path);
      for (const m of src.matchAll(/<From\b[^>]*artifact="([^"]+)"[^>]*>/g)) {
        if (!KINDS.includes(m[1])) offenders.push(`${path}: artifact="${m[1]}"`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
