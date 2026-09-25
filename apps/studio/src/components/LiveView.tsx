import { useCallback, useEffect, useState, type ReactElement } from 'react';
import {
  api,
  type EngineQualification,
  type RunSummary,
  type WorkloadEntry,
} from '../api';
import { Hash } from './badges';

type Load<T> =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'ready'; data: T };

function useLive<T>(fn: () => Promise<T>): {
  result: Load<T>;
  reload: () => void;
} {
  const [result, setResult] = useState<Load<T>>({ state: 'loading' });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let alive = true;
    setResult({ state: 'loading' });
    fn()
      .then((data) => alive && setResult({ state: 'ready', data }))
      .catch(
        (err: unknown) =>
          alive &&
          setResult({
            state: 'error',
            message: err instanceof Error ? err.message : String(err),
          }),
      );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);
  return { result, reload: () => setNonce((n) => n + 1) };
}

function DataUnavailable({ message }: { message: string }): ReactElement {
  return (
    <div className="live-error" role="status">
      <strong>DATA NOT AVAILABLE</strong>
      <p>{message}</p>
      <p className="muted">
        The gateway is not reachable. Nothing is shown rather than a
        placeholder number.
      </p>
    </div>
  );
}

function TrustPanel(): ReactElement {
  const qual = useLive(api.qualification);
  const workloads = useLive(api.workloads);
  return (
    <div className="live-grid">
      <section className="live-card">
        <h3>Engine qualification</h3>
        {qual.result.state === 'loading' && <p className="muted">loading…</p>}
        {qual.result.state === 'error' && (
          <DataUnavailable message={qual.result.message} />
        )}
        {qual.result.state === 'ready' && (
          <table className="live-table">
            <thead>
              <tr>
                <th>engine</th>
                <th>integration</th>
                <th>numerical</th>
                <th>limitations</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(qual.result.data.engines).map(
                ([name, e]: [string, EngineQualification]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{e.integration}</td>
                    <td
                      className={
                        e.numerical === 'NOT_ESTABLISHED'
                          ? 'bad'
                          : 'good'
                      }
                    >
                      {e.numerical}
                    </td>
                    <td className="muted">{e.limitations.join('; ') || '—'}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        )}
      </section>
      <section className="live-card">
        <h3>Workload trust levels</h3>
        {qual.result.state === 'ready' && (
          <ul className="muted">
            {Object.entries(qual.result.data.workload_levels).map(
              ([level, text]) => (
                <li key={level}>
                  <strong>{level}</strong>: {text}
                </li>
              ),
            )}
          </ul>
        )}
        {workloads.result.state === 'ready' && (
          <>
            <h4>Workloads ({workloads.result.data.workloads.length})</h4>
            <ul className="muted">
              {workloads.result.data.workloads.slice(0, 12).map(
                (w: WorkloadEntry) => (
                  <li key={w.id}>{w.title || w.name || w.id}</li>
                ),
              )}
            </ul>
          </>
        )}
        {workloads.result.state === 'error' && (
          <DataUnavailable message={workloads.result.message} />
        )}
      </section>
    </div>
  );
}

function RunsPanel(): ReactElement {
  const runs = useLive(api.runs);
  const [selected, setSelected] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Load<Record<string, unknown>>>({
    state: 'loading',
  });

  const openEvidence = useCallback((id: string) => {
    setSelected(id);
    setEvidence({ state: 'loading' });
    api
      .evidence(id)
      .then((data) => setEvidence({ state: 'ready', data }))
      .catch((err: unknown) =>
        setEvidence({
          state: 'error',
          message: err instanceof Error ? err.message : String(err),
        }),
      );
  }, []);

  return (
    <div className="live-grid">
      <section className="live-card">
        <h3>Runs</h3>
        <button className="btn" onClick={runs.reload}>
          refresh
        </button>
        {runs.result.state === 'loading' && <p className="muted">loading…</p>}
        {runs.result.state === 'error' && (
          <DataUnavailable message={runs.result.message} />
        )}
        {runs.result.state === 'ready' &&
          (runs.result.data.runs.length === 0 ? (
            <p className="muted">no finalized run bundles</p>
          ) : (
            <table className="live-table">
              <thead>
                <tr>
                  <th>run</th>
                  <th>status</th>
                  <th>bundle</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.result.data.runs.map((r: RunSummary) => (
                  <tr key={r.run_id}>
                    <td>{r.run_id}</td>
                    <td className={r.status === 'VERIFIED' ? 'good' : 'bad'}>
                      {r.status}
                    </td>
                    <td>
                      {r.bundle_id ? <Hash value={r.bundle_id} /> : '—'}
                    </td>
                    <td>
                      <button className="btn" onClick={() => openEvidence(r.run_id)}>
                        evidence
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
      </section>
      <section className="live-card">
        <h3>Evidence {selected ? `· ${selected}` : ''}</h3>
        {!selected && <p className="muted">select a run</p>}
        {selected && evidence.state === 'loading' && (
          <p className="muted">loading…</p>
        )}
        {selected && evidence.state === 'error' && (
          <DataUnavailable message={evidence.message} />
        )}
        {selected && evidence.state === 'ready' && (
          <pre className="live-evidence">
            {JSON.stringify(evidence.data, null, 2)}
          </pre>
        )}
      </section>
    </div>
  );
}

export default function LiveView({
  view,
}: {
  view: 'runs' | 'trust';
}): ReactElement {
  return view === 'runs' ? <RunsPanel /> : <TrustPanel />;
}
