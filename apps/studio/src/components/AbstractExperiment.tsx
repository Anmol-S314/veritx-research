import { useEffect, useRef, useState, type ReactElement } from 'react';
import { api } from '../api';
import { parseExactJson } from '../strictJson';

export default function AbstractExperiment({ projectId, revisionId }: {
  projectId: string; revisionId: string;
}): ReactElement {
  const [workload, setWorkload] = useState('');
  const [placement, setPlacement] = useState('');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const identity = `${projectId}/${revisionId}`;
  const current = useRef(identity);
  current.current = identity;
  useEffect(() => { setResult(null); setError(null); setWorkload(''); setPlacement(''); }, [identity]);
  const run = async (): Promise<void> => {
    const submitted = identity;
    setRunning(true); setResult(null); setError(null);
    try {
      const inputs = { profile: 'ABSTRACT_DATA_MOVEMENT_V1', workload: parseExactJson(workload), placement: parseExactJson(placement) };
      const response = await api.abstractExperiment(projectId, revisionId, inputs);
      if (current.current === submitted) setResult(response);
    } catch (err) { if (current.current === submitted) setError(err instanceof Error ? err.message : String(err)); }
    finally { setRunning(false); }
  };
  return <details className="subtle">
    <summary>Explicit V5 abstract experiment · not native simulation</summary>
    <p className="muted">ABSTRACT_DATA_MOVEMENT_V1 on immutable revision {revisionId}. Supply a DataMovementWorkload/v1
      bound to its exact V5 design hash and a PhysicalPlacement/v1 bound to its resource graph. No requests, clocks,
      service cycles or placement are inferred. Generic backend support is unchanged; no hardware/native equivalence or qualification.</p>
    <p className="muted">Synchronous diagnostic limits: 256 KiB body, 64 operations/routers/endpoints, 64 KiB payload/control,
      4096 children and 65536 flits. Noncompletion refuses rather than returning success.</p>
    <label className="field"><span className="field-label">Explicit workload JSON</span>
      <textarea rows={8} aria-label="Explicit workload JSON" value={workload} onChange={e => setWorkload(e.target.value)} disabled={running} /></label>
    <label className="field"><span className="field-label">Explicit placement JSON</span>
      <textarea rows={8} aria-label="Explicit placement JSON" value={placement} onChange={e => setPlacement(e.target.value)} disabled={running} /></label>
    <button type="button" className="btn" disabled={running || !workload.trim() || !placement.trim()} onClick={() => void run()}>
      {running ? 'Running abstract diagnostic…' : 'Run explicit abstract experiment'}</button>
    {running && <p role="status">Executing explicit inputs; native readiness is unchanged.</p>}
    {error && <p className="bad" role="alert">{error}. Correct explicit inputs or inspect the immutable revision.</p>}
    {result && <><p role="status">DIAGNOSTIC_ABSTRACT · unqualified · result bound to submitted revision and inputs</p>
      <details className="subtle"><summary>Bound abstract evidence JSON · includes identities, conservation and trace</summary>
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </details></>}
  </details>;
}
