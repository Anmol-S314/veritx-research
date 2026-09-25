import { useEffect, useRef, useState, type ReactElement } from 'react';
import type { EvaluationView, RequirementReport } from '../types';
import { Hash, StatusBadge, fmtNum, humanize } from './badges';

type RunState = 'idle' | 'running' | 'refused';

/**
 * Evaluation states: NOT_RUN (no EvaluationView) / RUNNING (transient local
 * request) / BACKEND_UNAVAILABLE / EVALUATED / FAILED / UNSUPPORTED.
 * Metrics render ONLY when present — absent metrics are omitted, never
 * zero-filled or invented.
 */
export default function EvaluateView({
  evaluation,
  requirements,
  fixtureId,
  live = false,
}: {
  evaluation: EvaluationView | null;
  requirements: RequirementReport | null;
  fixtureId: string;
  live?: boolean;
}): ReactElement {
  const [run, setRun] = useState<RunState>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setRun('idle');
    if (timer.current) clearTimeout(timer.current);
  }, [fixtureId, evaluation]);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const requestEvaluation = (): void => {
    setRun('running');
    // Fixture mode: no engine connectivity. The honest terminal state of any
    // local request is a refused run — demonstrated, never fabricated.
    timer.current = setTimeout(() => setRun('refused'), 1500);
  };

  if (!evaluation) {
    return (
      <div>
        <div className="verdict-banner verdict-not_run">
          <StatusBadge status="NOT_RUN" />
          <span className="verdict-text">
            No evaluation has been run for this design. Preconditions for a real
            run: COMPILED status with a PASS certificate, then a qualified backend.
          </span>
        </div>
        <div className="card">
          <h3>Request evaluation</h3>
          {live ? (
            <p className="muted">
              No evaluation exists for this revision. Use the Simulate page to
              start a real, qualified run.
            </p>
          ) : (
            run === 'idle' && (
              <div>
                <p className="muted">
                  Fixture mode has no engine connectivity. A request demonstrates the
                  RUNNING state, then resolves honestly.
                </p>
                <button className="btn btn-primary" onClick={requestEvaluation}>
                  Request evaluation
                </button>
              </div>
            )
          )}
          {run === 'running' && (
            <div className="running">
              <StatusBadge status="RUNNING" />
              <span> Contacting backend… (fixture-mode demonstration)</span>
              <div className="spinner" aria-label="Running" />
            </div>
          )}
          {run === 'refused' && (
            <div className="verdict-banner verdict-backend_unavailable">
              <StatusBadge status="BACKEND_UNAVAILABLE" />
              <span className="verdict-text">
                No qualified backend reachable from fixture mode — no evaluation
                performed, no metrics produced. A real deployment would route this
                request through the gateway to a qualified BookSim producer.
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (evaluation.status !== 'EVALUATED') {
    return (
      <div className={`verdict-banner verdict-${evaluation.status.toLowerCase()}`}>
        <StatusBadge status={evaluation.status} />
        <span className="verdict-text">
          {evaluation.reason ?? `${evaluation.status} — no metrics carried.`}
          <span className="no-metrics-note"> No metrics present; none invented.</span>
        </span>
      </div>
    );
  }

  const win = evaluation.network_traffic_window;
  const metrics = evaluation.metrics ?? {};
  const metricKeys = Object.keys(metrics);
  const bp = evaluation.backend_producer;

  return (
    <div>
      <div className="verdict-banner verdict-evaluated">
        <StatusBadge status="EVALUATED" />
        <span className="verdict-text">
          Network window complete: {fmtNum(win?.window_cycles)} cycles
          {win?.cycles_only ? ' (cycles only — no wall-time authority)' : ''}. Workload{' '}
          <code>{evaluation.workload_id}</code>.
        </span>
      </div>

      <div className="eval-grid">
        <div className="card">
          <h3>Network completion</h3>
          <div className="kv">
            <span>window cycles</span>
            <span>{fmtNum(win?.window_cycles)}</span>
          </div>
          <div className="kv">
            <span>wall time</span>
            <span>{win?.wall_time_ns == null ? '— (cycles only)' : `${fmtNum(win.wall_time_ns)} ns`}</span>
          </div>
          <div className="kv">
            <span>performance_result_id</span>
            <Hash value={evaluation.performance_result_id} />
          </div>
          <h4>Backend metrics (present only)</h4>
          {metricKeys.length === 0 && (
            <p className="muted">Backend produced no metrics — nothing shown, nothing zero-filled.</p>
          )}
          <table className="tbl">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {metricKeys.map((k) => (
                <tr key={k}>
                  <td>{humanize(k)}</td>
                  <td className="num">{fmtNum(metrics[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <div className="card">
            <h3>Backend producer</h3>
            {!bp && <p className="muted">No producer identity carried.</p>}
            {bp && (
              <div>
                <div className="kv">
                  <span>backend</span>
                  <code>{bp.backend}</code>
                </div>
                <div className="kv">
                  <span>producer identity</span>
                  <code>{bp.producer_identity}</code>
                </div>
                <div className="kv">
                  <span>config hash</span>
                  <Hash value={bp.config_hash} />
                </div>
                <div className="kv">
                  <span>input hash</span>
                  <Hash value={bp.input_hash} />
                </div>
              </div>
            )}
            <h4>Evidence binding</h4>
            <div className="kv">
              <span>message artifact</span>
              <code>{evaluation.message_artifact_id ?? '—'}</code>
            </div>
            <div className="kv">
              <span>physical traffic</span>
              <code>{evaluation.physical_traffic_id ?? '—'}</code>
            </div>
            <div className="kv">
              <span>resolved fabric</span>
              <Hash value={evaluation.resolved_fabric_hash} />
            </div>
            {evaluation.evidence && (
              <div className="kv">
                <span>evidence digests</span>
                <span>
                  raw <code>{evaluation.evidence.raw_evidence_digest}</code> · stats{' '}
                  <code>{evaluation.evidence.stats_digest}</code>
                </span>
              </div>
            )}
          </div>

          {evaluation.fidelity_warning && (
            <div className="card warn">
              <h3>Fidelity warning</h3>
              <p>{evaluation.fidelity_warning}</p>
            </div>
          )}

          <div className="card">
            <h3>Requirements ({requirements?.entries.length ?? 0})</h3>
            {!requirements && (
              <p className="muted">No RequirementReport bound to this evaluation.</p>
            )}
            {requirements && (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Class</th>
                    <th>Verdict</th>
                    <th>Required</th>
                    <th>Measured</th>
                  </tr>
                </thead>
                <tbody>
                  {requirements.entries.map((e) => (
                    <tr key={e.requirement_index} title={e.reason}>
                      <td>{e.requirement_index}</td>
                      <td>
                        <code>{e.traffic_class ?? e.qos_class ?? '—'}</code>
                      </td>
                      <td>
                        <StatusBadge status={e.verdict} />
                      </td>
                      <td className="num">{fmtNum(e.required)}</td>
                      <td className="num">{fmtNum(e.measured)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
