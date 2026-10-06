import type { LoomData } from './data';

export interface SectionFreshness {
  state: 'CURRENT' | 'STALE' | 'FOREIGN_REVISION';
  /** Why this state and not another, in the reader's terms. Shown on hover. */
  basis: string;
}

/**
 * How current one section's artifact is, or null when the question does not
 * apply. Three rules, each with its own authority, and nothing else:
 *
 * - Run-scoped artifacts (run, traffic_matrix, evidence) QUOTE the server.
 *   The gateway computes run freshness from server-owned facts; a client that
 *   recomputes staleness can disagree with the server about staleness, which
 *   is worse than no badge.
 * - The draft compares itself: uncompiled changes mean STALE.
 * - Revision-scoped compiler artifacts compare the revision they name against
 *   the active revision. Identity, not interpretation.
 *
 * backend, capability and lowering return null. Backend profiles are declared,
 * not versioned; the capability registry describes the installed system, not
 * a revision; the lowering view carries no revision to compare. A badge
 * claiming CURRENT for any of them would invent versioning that does not
 * exist. Absence of a badge is itself the statement: this artifact is not
 * revision-scoped.
 */
export function sectionFreshness(
  data: LoomData,
  artifact: string,
): SectionFreshness | null {
  switch (artifact) {
    case 'run':
    case 'traffic_matrix':
    case 'evidence': {
      const run = data.run.result.state === 'ready'
        ? data.run.result.data
        : null;
      const fresh = run?.freshness;
      if (!fresh) return null;
      return { state: fresh.state, basis: fresh.meaning };
    }
    case 'draft': {
      if (data.revisionId == null) return null;
      return data.dirty
        ? {
          state: 'STALE',
          basis: 'the draft has uncompiled changes, so authored values '
            + 'describe intent newer than the active revision '
            + short(data.revisionId),
        }
        : {
          state: 'CURRENT',
          basis: 'the draft matches the active revision ' + short(data.revisionId),
        };
    }
    case 'topology':
    case 'attachment':
    case 'route': {
      const topology = data.topology.result.state === 'ready'
        ? data.topology.result.data
        : null;
      return revisionFreshness(
        topology?.revision_id ?? null, data.revisionId, 'the certified topology');
    }
    case 'certificate':
    case 'compile_result':
    case 'vc_assignment': {
      const compiled = data.compileResult.result.state === 'ready'
        ? data.compileResult.result.data
        : null;
      return revisionFreshness(
        compiled?.revision_id ?? null, data.revisionId, 'the compile result');
    }
    default:
      return null;
  }
}

/**
 * One revision id against the active revision. Identity, not interpretation:
 * the artifact names a revision and the project has one active. Exported for
 * the run-comparison section, where two runs carry two revisions and a single
 * section badge cannot answer the question — each side is badged on its own.
 */
export function revisionFreshness(
  readRevision: string | null,
  active: string | null,
  what: string,
): SectionFreshness | null {
  if (readRevision == null || active == null) return null;
  return readRevision === active
    ? {
      state: 'CURRENT',
      basis: `${what} names revision ${short(active)}, the active revision`,
    }
    : {
      state: 'FOREIGN_REVISION',
      basis: `${what} was read from ${short(readRevision)}, not from the `
        + `active revision ${short(active)}`,
    };
}

function short(id: string): string {
  return id.length > 14 ? `${id.slice(0, 12)}…` : id;
}
