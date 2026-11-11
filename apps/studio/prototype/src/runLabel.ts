/** Human-readable run labels derived from the project's revision history.
 *
 *  A run id is a ULID: useful for identity, bad for reading a list. The
 *  label is revision + run ordinal, e.g. the first run of r01 is
 *  "r01 · run 1" and the second run of r12 is "r12 · run 2". A run is an
 *  evaluation attempt, not a design version; the revision is the version.
 *  The underlying ids and revision ids are never rewritten.
 */
export type RunVersionSource = {
  run_id: string;
  revision_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export function revisionNumber(revisionId?: string | null): number | null {
  const match = revisionId?.match(/-r0*(\d+)$/i);
  return match ? Number(match[1]) : null;
}

/** Short, stable display form for a revision id: r01, r12, … */
export function revisionLabel(revisionId?: string | null): string {
  const number = revisionNumber(revisionId);
  if (number !== null) return `r${String(number).padStart(2, '0')}`;
  const tail = revisionId?.split('-').filter(Boolean).slice(-1)[0];
  return tail || '—';
}

function recordedAt(run: RunVersionSource): string {
  return run.completed_at ?? run.started_at ?? '';
}

export function runVersionLabels(runs: RunVersionSource[]): Map<string, string> {
  const groups = new Map<string, RunVersionSource[]>();
  for (const run of runs) {
    const key = run.revision_id ?? `run:${run.run_id}`;
    const group = groups.get(key);
    if (group) group.push(run);
    else groups.set(key, [run]);
  }
  const orderedGroups = [...groups.entries()].sort(([left], [right]) => {
    const leftNumber = revisionNumber(left), rightNumber = revisionNumber(right);
    if (leftNumber !== null && rightNumber !== null && leftNumber !== rightNumber) return leftNumber - rightNumber;
    if (leftNumber !== null && rightNumber === null) return -1;
    if (leftNumber === null && rightNumber !== null) return 1;
    return left.localeCompare(right);
  });
  const labels = new Map<string, string>();
  orderedGroups.forEach(([revision, group]) => {
    const base = revisionNumber(revision) === null ? '' : `${revisionLabel(revision)} · `;
    [...group]
      .sort((a, b) => recordedAt(a).localeCompare(recordedAt(b)) || a.run_id.localeCompare(b.run_id))
      .forEach((run, index) => labels.set(run.run_id, `${base}run ${index + 1}`));
  });
  return labels;
}

function runSortKey(run: RunVersionSource): [number, string, string] {
  return [revisionNumber(run.revision_id) ?? Number.MAX_SAFE_INTEGER, recordedAt(run), run.run_id];
}

export function runVersionOrder<T extends RunVersionSource>(runs: T[]): T[] {
  return [...runs].sort((a, b) => {
    const left = runSortKey(a), right = runSortKey(b);
    if (left[0] !== right[0]) return left[0] - right[0];
    const byTime = left[1].localeCompare(right[1]);
    return byTime || left[2].localeCompare(right[2]);
  });
}
