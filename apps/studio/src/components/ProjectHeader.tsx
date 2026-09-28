import type { ReactElement } from 'react';
import type { ProjectView, RunSummary } from '../api';
import type { DesignView } from '../types';
import { Hash, StatusBadge } from './badges';
import { Link } from '../studio';
import {
  ScientificValue,
  backendLabel,
} from './ScientificValue';

/**
 * Global project header (Studio vNext §3).
 *
 * Project / Revision / Workload / Latest analysis (with SIMULATED +
 * qualification origin, never a naked number) / Latest optimization +
 * a history dropdown for revision, workload and run history.
 */
export default function ProjectHeader({ project }: {
  project: ProjectView;
}): ReactElement {
  const active = project.active_revision;
  const design = active?.design ?? null;
  const wl = design?.workload ?? null;
  const evaluation = project.latest_static_evaluation
    ?? project.latest_active_run;
  const study = project.latest_optimization_study;
  return (
    <header className="card project-header">
      <div className="overview-grid">
        <div>
          <p className="kicker">PROJECT</p>
          <p className="next-action-large">{project.project.name}</p>
          {project.draft.dirty && (
            <p className="stale">UNCOMPILED DRAFT CHANGES present</p>
          )}
        </div>
        <div>
          <p className="kicker">REVISION</p>
          {active ? (
            <>
              <p>
                <span>{active.display_name}</span>{' '}
                <StatusBadge status={active.compilation.status} />
              </p>
              <p className="muted">
                certificate {active.certificate?.overall ?? '—'}
              </p>
            </>
          ) : (
            <p className="muted">No certified revision yet.</p>
          )}
        </div>
        <div>
          <p className="kicker">WORKLOAD</p>
          {wl ? (
            <p>
              {wl.model_name ?? wl.model_family} · TP{' '}
              {wl.parallelism.tp} / PP {wl.parallelism.pp} / EP{' '}
              {wl.parallelism.ep} / DP {wl.parallelism.dp}
            </p>
          ) : (
            <p className="muted">—</p>
          )}
        </div>
        <div>
          <p className="kicker">LATEST ANALYSIS</p>
          {evaluation ? (
            <p>
              {backendLabel(evaluation.backend)} ·{' '}
              <ScientificValue
                value={evaluation.completion_cycles}
                unit="cycles"
                epistemic="SIMULATED"
                source={evaluation.backend ?? undefined}
                qualification={evaluation.qualification ?? undefined}
              />
            </p>
          ) : (
            <p className="muted">No evaluation yet.</p>
          )}
        </div>
        <div>
          <p className="kicker">LATEST OPTIMIZATION</p>
          {study ? (
            <p>
              <ScientificValue
                value={study.candidate_count}
                unit="candidates"
                epistemic="DECLARED"
                source="optimization study"
              />{' '}
              ·{' '}
              <ScientificValue
                value={study.pareto_count}
                unit="pareto"
                epistemic="DECLARED"
                source="optimization study"
              />
            </p>
          ) : (
            <p className="muted">No study yet.</p>
          )}
        </div>
      </div>
      <details className="lowering-inspect">
        <summary>Revision, workload and run history</summary>
        <div className="kv">
          <span>revisions</span>
          <span>
            {project.revisions.length === 0
              ? '—'
              : project.revisions.map((r) => (
                <span key={r.revision_id}>
                  {r.display_name} ({r.compilation_status.toLowerCase()}
                  {r.certificate_overall
                    ? ` · cert ${r.certificate_overall}` : ''}) ·{' '}
                </span>
              ))}
          </span>
        </div>
        <div className="kv">
          <span>runs</span>
          <span>
            {project.runs.length === 0
              ? '—'
              : project.runs.map((r) => (
                <Link
                  className="link"
                  key={r.run_id}
                  to={`/runs/${r.run_id}`}
                >
                  {r.display_name ?? r.run_id}
                </Link>
              )).reduce<ReactElement[]>(
                (acc, el, i) => (i === 0 ? [el] : [...acc, <span key={`s${i}`}> · </span>, el]),
                [],
              )}
          </span>
        </div>
      </details>
    </header>
  );
}

/** Design summary strip (vNext §5 top): what is being designed. */
export function DesignSummary({ design }: {
  design: DesignView;
}): ReactElement {
  const agents = design.agents ?? [];
  const tiles = agents.find((a) => a.kind === 'compute_tile')?.count;
  const hbm = agents.find((a) => a.kind === 'hbm_controller')?.count;
  const nics = agents
    .filter((a) => a.kind === 'nic')
    .reduce((n, a) => n + a.count, 0);
  const wl = design.workload;
  const g = design.noc_guided;
  return (
    <section className="card">
      <h3>{wl.model_name ?? wl.model_family} fabric</h3>
      <div className="kv">
        <span>compute tiles</span>
        <ScientificValue
          value={tiles ?? agents.reduce((n, a) => n + a.count, 0)}
          epistemic="DECLARED"
          source="design intent · agents"
        />
      </div>
      <div className="kv">
        <span>HBM controllers</span>
        <ScientificValue
          value={hbm ?? 0}
          epistemic="DECLARED"
          source="design intent · agents"
        />
      </div>
      <div className="kv">
        <span>NICs</span>
        <ScientificValue
          value={nics}
          epistemic="DECLARED"
          source="design intent · agents"
        />
      </div>
      <div className="kv">
        <span>parallelism</span>
        <span>
          TP <ScientificValue value={wl.parallelism.tp} epistemic="DECLARED" /> ·{' '}
          PP <ScientificValue value={wl.parallelism.pp} epistemic="DECLARED" /> ·{' '}
          EP <ScientificValue value={wl.parallelism.ep} epistemic="DECLARED" /> ·{' '}
          DP <ScientificValue value={wl.parallelism.dp} epistemic="DECLARED" />
        </span>
      </div>
      <div className="kv">
        <span>topology</span>
        <span>{g.topology_family ?? '—'}{g.radix != null ? ` ${g.radix}×${g.radix}` : ''}</span>
      </div>
      <div className="kv">
        <span>links</span>
        {g.link_width != null ? (
          <ScientificValue
            value={g.link_width}
            unit="bits"
            epistemic="DECLARED"
            source="design intent"
          />
        ) : (
          <span className="muted">—</span>
        )}
      </div>
      <div className="kv">
        <span>routing / VCs</span>
        <span>
          {design.locked_derived?.routing ?? '—'} ·{' '}
          <ScientificValue
            value={design.locked_derived?.vc_count ?? null}
            unit="VCs"
            epistemic="DERIVED"
            source="compiler derivation"
          />
        </span>
      </div>
      <div className="kv"><span>design identity</span><Hash value={design.design_hash} /></div>
    </section>
  );
}

/** Design health card: compilation + certificate obligations. */
export function DesignHealth({ project }: {
  project: ProjectView;
}): ReactElement {
  const active = project.active_revision;
  const obligations = active?.certificate?.obligations ?? [];
  const passed = obligations.filter((o) => o.status === 'PASS').length;
  return (
    <section className="card">
      <h3>Design health</h3>
      {active ? (
        <>
          <div className="kv">
            <span>compilation</span>
            <StatusBadge status={active.compilation.status} />
          </div>
          <div className="kv">
            <span>certificate</span>
            <span>{active.certificate?.overall ?? '—'}</span>
          </div>
          <div className="kv">
            <span>verification obligations</span>
            <ScientificValue
              value={passed}
              unit={`of ${obligations.length} passed`}
              epistemic="VERIFIED"
              source="verification certificate"
            />
          </div>
        </>
      ) : (
        <p className="muted">No certified revision yet.</p>
      )}
    </section>
  );
}

/** Execution readiness, one row per backend from the latest runs. */
export function ExecutionReadiness({ runs }: {
  runs: RunSummary[];
}): ReactElement {
  const latestByBackend = new Map<string, RunSummary>();
  for (const r of runs) {
    latestByBackend.set(r.backend ?? 'unknown', r);
  }
  const backends = ['BOOKSIM', 'ASTRA', 'RAMULATOR', 'SERVING'];
  const rows = backends.map((key) => {
    const found = [...latestByBackend.entries()].find(([b]) =>
      b.toUpperCase().includes(key),
    );
    return { key, run: found?.[1] ?? null };
  });
  const others = [...latestByBackend.entries()].filter(([b]) =>
    !backends.some((key) => b.toUpperCase().includes(key)),
  );
  return (
    <section className="card">
      <h3>Execution</h3>
      {rows.map(({ key, run }) => (
        <div className="kv" key={key}>
          <span>{backendLabel(key)}</span>
          {run ? (
            <span>
              <StatusBadge status={run.status ?? 'UNKNOWN'} />{' '}
              {run.completion_cycles != null ? (
                <ScientificValue
                  value={run.completion_cycles}
                  unit="cycles"
                  epistemic="SIMULATED"
                  source={run.backend ?? undefined}
                  qualification={run.qualification ?? undefined}
                />
              ) : (
                <span className="muted">
                  {run.qualification ?? 'no measurement'}
                </span>
              )}
            </span>
          ) : (
            <span className="muted">no run</span>
          )}
        </div>
      ))}
      {others.map(([b, run]) => (
        <div className="kv" key={b}>
          <span>{backendLabel(b)}</span>
          <span>
            <StatusBadge status={run.status ?? 'UNKNOWN'} />{' '}
            <span className="muted">{run.qualification ?? ''}</span>
          </span>
        </div>
      ))}
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
    </section>
  );
}

/** Outstanding limitations: refused attempts, gated evaluation, flow blocks. */
export function OutstandingLimitations({ project, refusedError }: {
  project: ProjectView;
  refusedError: string | null;
}): ReactElement {
  const items: string[] = [];
  const evalGate = project.active_evaluation;
  if (evalGate && !evalGate.supported && evalGate.reason) {
    items.push(`Evaluation gated at ${evalGate.domain ?? 'gate'}: ${evalGate.reason}`);
  }
  if (refusedError) items.push(refusedError);
  if (project.flow.state === 'REFUSED') items.push(project.flow.reason);
  if (items.length === 0) return <></>;
  return (
    <section className="card">
      <h3>Outstanding limitations</h3>
      <ul>
        {items.map((item, i) => (
          <li key={i} className={i === 0 ? '' : 'muted'}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
