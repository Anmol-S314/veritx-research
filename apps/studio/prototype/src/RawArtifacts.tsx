import { useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import { useProject } from './project';
import { Button, Field, Notice, Section } from './ui';
import { decodeInjectionTrace, decodeRoutingDump } from './trace';

export async function fetchVerifiedArtifact(runId: string, path: string, expected: string) {
  const response = await fetch(gateway.artifactUrl(runId, path), { signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new Error(`Artifact unavailable (${response.status}).`);
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 16 * 1024 * 1024) throw new Error('Artifact exceeds 16 MiB.');
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(n => n.toString(16).padStart(2, '0')).join('');
  if (digest !== expected.replace(/^sha256:/, '') || digest !== response.headers.get('x-content-sha256')) throw new Error('Artifact digest mismatch; preview and download refused.');
  return bytes;
}
export function RawArtifacts({ runId, files, tracesOnly = false }: { runId: string; files: Record<string, string>; tracesOnly?: boolean }) {
  const { health } = useProject();
  const paths = Object.keys(files).filter(p => !tracesOnly || /\.trace$/.test(p) || /(^|\/)routing\.dump$/.test(p));
  const [selected, setSelected] = useState(paths[0] ?? ''), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [preview, setPreview] = useState(''), [decoded, setDecoded] = useState<ReturnType<typeof decodeInjectionTrace> | null>(null);
  const [decodedRoute, setDecodedRoute] = useState<ReturnType<typeof decodeRoutingDump> | null>(null);
  const path = paths.includes(selected) ? selected : paths[0] ?? '';
  const decodeLabel = path.endsWith('workload.trace') ? 'Decode injection schedule' : /(^|\/)routing\.dump$/.test(path) ? 'Decode first-hop realization' : 'Preview verified text';
  const read = async (download: boolean) => {
    if (!path || busy) return;
    setBusy(true); setError(''); setPreview(''); setDecoded(null); setDecodedRoute(null);
    try {
      const bytes = await fetchVerifiedArtifact(runId, path, files[path]);
      if (download) {
        const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
        const anchor = document.createElement('a'); anchor.href = url; anchor.download = path.split('/').pop()!; anchor.click(); URL.revokeObjectURL(url);
      } else if (path.endsWith('workload.trace')) setDecoded(decodeInjectionTrace(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
      else if (/(^|\/)routing\.dump$/.test(path)) setDecodedRoute(decodeRoutingDump(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
      else setPreview(new TextDecoder('utf-8', { fatal: true }).decode(bytes.slice(0, 1024 * 1024)));
    } catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); }
  };
  if (!paths.length) return null;
  return <Section title={tracesOnly ? 'Verified injection trace' : 'Original artifact bytes'}>
    {!health?.features?.artifact_bytes && <Notice tone="amber">Gateway upgrade required for verified file download.</Notice>}
    <Field label="Sealed artifact"><select value={path} disabled={busy} onChange={e => { setSelected(e.target.value); setPreview(''); setDecoded(null); setDecodedRoute(null); setError(''); }}>{paths.map(p => <option key={p}>{p}</option>)}</select></Field>
    <div className="toolbar"><Button disabled={busy || !health?.features?.artifact_bytes} onClick={() => read(false)}>{busy ? 'Reading…' : decodeLabel}</Button><Button disabled={busy || !health?.features?.artifact_bytes} onClick={() => read(true)}>Download original bytes</Button></div>
    {error && <Notice tone="red">{error}</Notice>}{preview && <><p>Text preview: first 1 MiB, after whole-file digest verification.</p><pre className="code-preview">{preview}</pre></>}
    {decodedRoute && <><Notice>Executed first-hop realization, not a full packet path. {decodedRoute.rows.length} of {decodedRoute.total} records shown.</Notice><div className="table-scroll"><table><thead><tr><th>Line</th><th>Source router</th><th>Destination node</th><th>Next router</th><th>Egress port</th></tr></thead><tbody>{decodedRoute.rows.map(row => <tr key={row.line}><td>{row.line}</td><td>{row.srcRouter}</td><td>{row.dstNode}</td><td>{row.nextRouter}</td><td>{row.port}</td></tr>)}</tbody></table></div></>}
    {decoded && <><Notice>Requested injection schedule, not observed delivery or packet hops. {decoded.rows.length} of {decoded.total} records shown ({decoded.dialect}).</Notice><div className="table-scroll"><table><thead><tr><th>Line</th><th>Cycle</th><th>Source</th><th>Destination</th><th>Class</th><th>Packet flits</th></tr></thead><tbody>{decoded.rows.map(row => <tr key={row.line}><td>{row.line}</td><td>{row.cycle}</td><td>{row.source}</td><td>{row.destination}</td><td>{row.trafficClass}</td><td>{row.flits}</td></tr>)}</tbody></table></div></>}
  </Section>;
}
