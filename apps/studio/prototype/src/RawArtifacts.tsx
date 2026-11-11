import { useEffect, useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useProject } from './project';
import { Badge, Button, Field, Notice, Section } from './ui';
import { decodeInjectionTrace, isInjectionTraceArtifact } from './trace';
import { InjectionTimeline } from './TraceView';
import { cappedClass, redactIdentityText, withoutIdentity } from './format';

export async function fetchVerifiedArtifact(runId: string, path: string, expectedChecksum: string) {
  const response = await fetch(gateway.artifactUrl(runId, path), { signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new Error(`Artifact unavailable (${response.status}).`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 16 * 1024 * 1024) throw new Error('Artifact exceeds 16 MiB.');
  const checksum = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('');
  if (checksum !== expectedChecksum.replace(/^sha256:/, '') || checksum !== response.headers.get('x-content-sha256')) throw new Error('Artifact bytes do not match the recorded manifest; preview and download refused.');
  return bytes;
}

function previewText(text: string) {
  const trimmed = text.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try { return JSON.stringify(withoutIdentity(JSON.parse(text)), null, 2); } catch { /* Truncated or not valid JSON; fall through. */ }
  }
  return redactIdentityText(text);
}

export function RawArtifacts({ runId, files, tracesOnly = false }: { runId: string; files: Record<string, string>; tracesOnly?: boolean }) {
  const { health } = useProject();
  const rawPaths = Object.keys(files).filter(p => !tracesOnly || isInjectionTraceArtifact(p));
  // Trace bundles repeat the same trace under several analyses. Show one artifact per content
  // identity and prefer the shortest path.
  const paths = tracesOnly
    ? (() => {
      const byContent = new Map<string, string>();
      const score = (path: string) => (path.includes('network_completion') ? 0 : 1000) + path.length;
      for (const path of rawPaths) {
        const content = files[path];
        const current = byContent.get(content);
        if (!current || score(path) < score(current)) byContent.set(content, path);
      }
      return [...byContent.values()].sort((a, b) => Number(/\.trace$/.test(b)) - Number(/\.trace$/.test(a)) || a.localeCompare(b));
    })()
    : rawPaths;
  const [selected, setSelected] = useState(paths[0] ?? ''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [preview, setPreview] = useState(''), [decoded, setDecoded] = useState<ReturnType<typeof decodeInjectionTrace> | null>(null);
  const [filter, setFilter] = useState(''), [page, setPage] = useState(0);
  const path = paths.includes(selected) ? selected : paths[0] ?? '';
  const available = !!health?.features?.artifact_bytes;
  const isInjection = /\.trace$/.test(path);
  const artifactLabel = (value: string) => /\.trace$/.test(value) ? 'Requested injections' : value.split('/').pop() ?? value;
  const read = async (download = false) => {
    if (!path || busy) return;
    setBusy(true); setError(''); setPreview(''); setDecoded(null);
    try {
      const bytes = await fetchVerifiedArtifact(runId, path, files[path]);
      const text = () => new TextDecoder('utf-8', { fatal: true }).decode(bytes);
      if (download) {
        const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
        const anchor = document.createElement('a'); anchor.href = url; anchor.download = path.split('/').pop()!; anchor.click(); URL.revokeObjectURL(url);
      } else if (isInjection) setDecoded(decodeInjectionTrace(text(), 200000));
      else setPreview(previewText(text()));
    } catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  // The viewer opens on the trace itself: decoding is not an action the user has to discover.
  useEffect(() => { if (available && path) void read(false); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [path, runId, available]);
  useEffect(() => { setPage(0); setFilter(''); }, [path]);
  if (!paths.length) return null;
  const query = filter.trim().toLowerCase();
  const injectionRows = decoded ? decoded.rows.filter(row => !query || `${row.source} ${row.destination} ${row.trafficClass}`.toLowerCase().includes(query)) : [];
  const PAGE = 100;
  const pages = Math.max(1, Math.ceil(injectionRows.length / PAGE));
  const current = Math.min(page, pages - 1);
  const shown = injectionRows.slice(current * PAGE, current * PAGE + PAGE);
  const traceMode = tracesOnly || isInjection;
  return <Section title={traceMode ? 'Trace workspace' : 'Original artifact bytes'} actions={busy ? <span className="muted">Reading verified bytes…</span> : decoded ? <Badge tone="green">Bytes verified</Badge> : null}>
    {!available && <Notice tone="amber">Gateway upgrade required for verified file download.</Notice>}
    {paths.length > 1 && (tracesOnly
      ? <div className="segmented trace-segmented">{paths.map(p => <button key={p} type="button" className={p === path ? 'active' : ''} onClick={() => setSelected(p)}>{artifactLabel(p)}</button>)}</div>
      : <Field label="Trace artifact"><select value={path} disabled={busy} onChange={e => setSelected(e.target.value)}>{paths.map(p => <option key={p}>{p}</option>)}</select></Field>)}
    <p className="trace-meta"><span className="mono">{path}</span>{decoded && <span>{decoded.total.toLocaleString()} records · {decoded.dialect}</span>}</p>
    <div className="toolbar toolbar-start"><Button disabled={busy || !available} onClick={() => void read(true)}>Download original bytes</Button>{error && <Button onClick={() => void read(false)}>Retry read</Button>}</div>
    {error && <Notice tone="red">{error}</Notice>}
    {decoded && <InjectionTimeline decoded={decoded} />}
    {decoded && <details className="trace-rows">
      <summary>Requested injection rows · {injectionRows.length.toLocaleString()}</summary>
      <div className="trace-table-head">
        <label className="search-field"><input aria-label="Filter requested injections" placeholder="Filter source, destination, class…" value={filter} onChange={event => setFilter(event.target.value)} /></label>
      </div>
      <div className={`table-scroll${cappedClass(shown.length)}`}><table><thead><tr><th>Line</th><th>Cycle</th><th>Source</th><th>Destination</th><th>Class</th><th>Flits</th></tr></thead><tbody>
        {shown.map(row => <tr key={row.line}><td>{row.line}</td><td>{row.cycle}</td><td>{row.source}</td><td>{row.destination}</td><td>{row.trafficClass}</td><td className="numeric">{row.flits}</td></tr>)}
        {!shown.length && <tr><td colSpan={6} className="muted">No requested injection matches the filter.</td></tr>}
      </tbody></table></div>
      <div className="table-footer">
        <span className="muted">{injectionRows.length ? `${current * PAGE + 1}–${Math.min(injectionRows.length, current * PAGE + PAGE)} of ${injectionRows.length.toLocaleString()} rows` : 'No rows'}</span>
        <span className="actions">
          <button type="button" className="button" disabled={current === 0} onClick={() => setPage(current - 1)}>Previous</button>
          <span className="mono">{current + 1} / {pages}</span>
          <button type="button" className="button" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Next</button>
        </span>
      </div>
    </details>}
    {preview && <><p>Text preview · first 1 MiB</p><pre className="code-preview">{preview}</pre></>}
  </Section>;
}
