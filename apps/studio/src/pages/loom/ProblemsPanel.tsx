import { useMemo, type ReactElement } from 'react';
import { Link } from '../../studio';
import { api, type PreflightView, type RunIntegrityView } from '../../api';
import { useAsync } from '../../studio';
import {
  problemsOf, type LoomData, type Problem, type ProblemSeverity,
} from './data';
import { Kv, RailSection } from './parts';

const LABEL: Record<ProblemSeverity, string> = {
  bad: 'BLOCKING',
  warn: 'ADVISORY',
  info: 'INFO',
  ok: 'CLEAR',
};

function tally(problems: Problem[]): Record<ProblemSeverity, number> {
  const out: Record<ProblemSeverity, number> = { bad: 0, warn: 0, info: 0, ok: 0 };
  for (const p of problems) out[p.severity] += 1;
  return out;
}

/** Every finding the engine actually emitted, in one list.
 *
 *  This panel collects verdicts from artifacts the workspace already loads —
 *  it introduces no new checks and no new authority. What it adds is a single
 *  place to see them, each naming the artifact it came from and linking to the
 *  view where the evidence lives. */
export default function ProblemsPanel({ data }: { data: LoomData }): ReactElement {
  const preflight = useAsync<PreflightView | null>(
    () => (data.revisionId
      ? api.preflight(data.revisionId).catch(() => null)
      : Promise.resolve(null)),
    [data.revisionId],
  );
  const integrity = useAsync<RunIntegrityView | null>(
    () => (data.latestRun
      ? api.integrity(data.latestRun.run_id).catch(() => null)
      : Promise.resolve(null)),
    [data.latestRun?.run_id],
  );

  const problems = useMemo(() => problemsOf(data, {
    preflight: preflight.result.state === 'ready' ? preflight.result.data : null,
    integrity: integrity.result.state === 'ready' ? integrity.result.data : null,
  }), [data, preflight.result, integrity.result]);

  const counts = tally(problems);
  const loading = preflight.result.state === 'loading'
    || integrity.result.state === 'loading';

  return (
    <RailSection
      title="Problems"
      note="Findings from the engine's own verdicts. Silence below means the artifacts reported nothing — not that the design is clean."
    >
      <div className="loom-problem-tally">
        <span className={`t-${counts.bad ? 'bad' : 'muted'}`}>
          {counts.bad} blocking
        </span>
        <span className={`t-${counts.warn ? 'warn' : 'muted'}`}>
          {counts.warn} advisory
        </span>
        {loading && <span className="muted" role="status">checking…</span>}
      </div>

      {problems.length === 0 && !loading && (
        <p className="muted">
          No blocking or advisory finding in the loaded artifacts: the
          certificate passed, every requirement was satisfied, the deadlock
          proof came back acyclic, conservation held and the draft matches the
          revision.
        </p>
      )}

      <ul className="loom-problems">
        {problems.map((p) => (
          <li key={p.id} className={`sev-${p.severity}`}>
            <div className="loom-problem-head">
              <span className={`loom-problem-sev sev-${p.severity}`}>
                {LABEL[p.severity]}
              </span>
              <b>{p.title}</b>
            </div>
            <p className="loom-problem-detail">{p.detail}</p>
            <div className="loom-problem-source">
              <code>{p.source}</code>
              {p.view && (
                <Link className="link" to={`/projects/${data.projectId}/loom/${p.view}`}>
                  open {p.view}
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>

      {problems.some((p) => p.severity === 'bad') && (
        <p className="loom-note">
          A blocking finding is an engine verdict on an artifact. Studio does
          not clear one, and generating from a blocked revision is refused
          upstream.
        </p>
      )}
    </RailSection>
  );
}

/** Compact form for the shell: a count that links to the full panel. Kept in
 *  this file so the tally and the list can never disagree. */
export function ProblemsSummary({ data }: { data: LoomData }): ReactElement | null {
  const preflight = useAsync<PreflightView | null>(
    () => (data.revisionId
      ? api.preflight(data.revisionId).catch(() => null)
      : Promise.resolve(null)),
    [data.revisionId],
  );
  const integrity = useAsync<RunIntegrityView | null>(
    () => (data.latestRun
      ? api.integrity(data.latestRun.run_id).catch(() => null)
      : Promise.resolve(null)),
    [data.latestRun?.run_id],
  );
  const problems = useMemo(() => problemsOf(data, {
    preflight: preflight.result.state === 'ready' ? preflight.result.data : null,
    integrity: integrity.result.state === 'ready' ? integrity.result.data : null,
  }), [data, preflight.result, integrity.result]);
  const counts = tally(problems);
  if (counts.bad === 0 && counts.warn === 0) {
    return (
      <Kv
        label="problems"
        value={<span className="muted">none reported</span>}
      />
    );
  }
  return (
    <Kv
      label="problems"
      value={
        <span>
          {counts.bad > 0 && <span className="t-bad">{counts.bad} blocking </span>}
          {counts.warn > 0 && <span className="t-warn">{counts.warn} advisory</span>}
        </span>
      }
    />
  );
}