import { useState, type ReactElement } from 'react';
import { api, type RunVerifyView } from '../../api';

/** Gateway verification action for a run bundle. It does not claim to hash a
 * user-imported trace or a local loom-sim artifact. */
export default function RunArtifactVerify({ runId }: { runId: string | null }): ReactElement {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RunVerifyView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const verify = async (): Promise<void> => {
    if (!runId || busy) return;
    setBusy(true); setResult(null); setError(null);
    try { setResult(await api.verifyRun(runId)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <section aria-label="Run artifact integrity">
      <button type="button" className="btn" disabled={!runId || busy} onClick={() => { void verify(); }}>
        {busy ? 'Verifying run bundle…' : 'Verify run bundle'}
      </button>
      {result && <p className="t-ok" role="status">Gateway verification: {result.status} · {result.files_checked}/{result.file_count} files · bundle <code>{result.bundle_id}</code></p>}
      {error && <p className="t-bad" role="alert">Gateway verification failed: {error}</p>}
      <p className="muted">Verifies the gateway run bundle only; imported local traces are not covered.</p>
    </section>
  );
}
