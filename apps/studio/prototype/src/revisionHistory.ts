import type { RevisionDiff, RevisionDiffRow, RevisionSummary, RunSummary } from './gateway';
import { revisionLabel, revisionNumber, runVersionOrder } from './runLabel';

export type RevisionGroup = {
  revisionId: string;
  label: string;
  displayName: string;
  createdAt: string | null;
  compilationStatus: string | null;
  certificateOverall: string | null;
  error: string | null;
  isActive: boolean;
  runs: RunSummary[];
};

/** Group every revision (including failed compile attempts) and nest its runs.
 *  The active revision is first; the rest follow newest-first. A revision with
 *  no run is kept visible so a gap in the sequence is explained, not hidden. */
export function buildRevisionGroups(
  revisions: RevisionSummary[],
  runs: RunSummary[],
  activeRevisionId?: string | null,
): RevisionGroup[] {
  const groups = new Map<string, RevisionGroup>();
  for (const revision of revisions) {
    groups.set(revision.revision_id, {
      revisionId: revision.revision_id,
      label: revisionLabel(revision.revision_id),
      displayName: revision.display_name || revisionLabel(revision.revision_id),
      createdAt: revision.created_at ?? null,
      compilationStatus: revision.compilation_status ?? (revision.certificate_overall ? 'COMPILED' : null),
      certificateOverall: revision.certificate_overall ?? null,
      error: revision.error ?? null,
      isActive: revision.revision_id === activeRevisionId,
      runs: [],
    });
  }
  for (const run of runs) {
    const revisionId = run.revision_id;
    let group = groups.get(revisionId);
    if (!group) {
      group = {
        revisionId,
        label: revisionLabel(revisionId),
        displayName: revisionLabel(revisionId),
        createdAt: run.completed_at ?? run.started_at ?? null,
        compilationStatus: null,
        certificateOverall: null,
        error: null,
        isActive: revisionId === activeRevisionId,
        runs: [],
      };
      groups.set(revisionId, group);
    }
    group.runs.push(run);
  }
  const ordered = [...groups.values()];
  for (const group of ordered) group.runs = runVersionOrder(group.runs);
  return ordered.sort((a, b) => {
    if (a.isActive !== b.isActive) return a.isActive ? -1 : 1;
    const left = revisionNumber(a.revisionId), right = revisionNumber(b.revisionId);
    if (left !== null && right !== null && left !== right) return right - left;
    if (left !== null && right === null) return -1;
    if (left === null && right !== null) return 1;
    return String(b.createdAt ?? '').localeCompare(String(a.createdAt ?? ''));
  });
}

/** The previous successful compile, skipping failed attempts in between. */
export function previousCompiledRevision(
  revisions: RevisionSummary[],
  revisionId: string,
): RevisionSummary | null {
  const target = revisionNumber(revisionId);
  if (target === null) return null;
  return revisions
    .filter(revision => revision.compilation_status === 'COMPILED' || revision.certificate_overall === 'PASS')
    .filter(revision => {
      const number = revisionNumber(revision.revision_id);
      return number !== null && number < target;
    })
    .sort((a, b) => (revisionNumber(b.revision_id) ?? 0) - (revisionNumber(a.revision_id) ?? 0))[0] ?? null;
}

export function runScopeLabel(run: RunSummary): string {
  const analyses = run.analysis_backends ?? [];
  if (!analyses.length) return run.backend ?? 'No analysis recorded';
  const first = analyses[0]?.question ?? analyses[0]?.backend_id ?? 'Analysis';
  return analyses.length === 1 ? first : `${first} + ${analyses.length - 1} more`;
}

export function revisionTone(group: RevisionGroup): 'green' | 'amber' | 'red' | 'neutral' {
  if (group.compilationStatus === 'COMPILED' && group.certificateOverall === 'PASS') return 'green';
  if (group.compilationStatus === 'UNSUPPORTED') return 'amber';
  if (group.compilationStatus === 'FAILED' || group.error) return 'red';
  return 'neutral';
}

export function diffRows(diff: RevisionDiff): RevisionDiffRow[] {
  return [
    ...(diff.design_changes ?? []),
    ...(diff.derived_changes ?? []),
    ...(diff.capability_changes ?? []),
  ];
}

export function diffValue(value: unknown): string {
  if (value === null || value === undefined) return 'none';
  if (typeof value === 'string') return value.length > 90 ? `${value.slice(0, 87)}…` : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? '' : 's'}`;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
