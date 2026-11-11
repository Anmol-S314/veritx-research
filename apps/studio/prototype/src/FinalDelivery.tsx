import { useEffect, useRef, useState } from 'react';
import { gateway, gatewayReason, type M5RtlPrototype, type M5RtlPrototypesResponse, type RtlPreview, type RtlReadiness } from './gateway';
import { artifactSize, evidenceState, prototypeFileState } from './m5RtlRegistry';
import type { LoadedProject } from './project';
import { Assumptions, PageLink, Badge, Button, Notice, Section } from './ui';

const terminal = ['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'];

export function FinalDelivery({ project }: { project: LoadedProject }) {
  const id = project.detail.project.project_id;
  const [readiness, setReadiness] = useState<RtlReadiness | null>(null);
  const [preview, setPreview] = useState<RtlPreview | null>(null);
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [catalogError, setCatalogError] = useState('');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [protos, setProtos] = useState<M5RtlPrototypesResponse | null>(null);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [scopeKey, setScopeKey] = useState('');
  const [statusRetry, setStatusRetry] = useState(0);
  const launchGeneration = useRef(0);
  const currentScopeKey = JSON.stringify([id, project.detail.active_revision_id, project.detail.runs?.length, project.draftMeta?.revisionToken]);
  const scopeIsCurrent = scopeKey === currentScopeKey;
  const activeScope = useRef(currentScopeKey);
  activeScope.current = currentScopeKey;
  useEffect(() => {
    ++launchGeneration.current;
    setBusy(false); setScopeKey('');
    setReadiness(null); setPreview(null); setJobId(''); setConsent(false); setError('');
    let live = true;
    gateway.rtlReadiness(id).then(value => { if (live) { setReadiness(value); setScopeKey(currentScopeKey); } }).catch(caught => { if (live) { setError(gatewayReason(caught)); setScopeKey(currentScopeKey); } });
    return () => { live = false; };
  // currentScopeKey captures project and revision-bearing inputs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentScopeKey]);
  useEffect(() => {
    let live = true;
    setLoading(true); setProtos(null); setCatalogError('');
    gateway.rtlPrototypes().then(value => { if (live) { setProtos(value); setSelected(previous => value.prototypes.some(row => row.topology_id === previous) ? previous : value.prototypes.find(row => row.required)?.topology_id ?? ''); } }).catch(caught => { if (live) { setProtos(null); setSelected(''); setCatalogError(gatewayReason(caught)); } }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [refresh]);
  useEffect(() => {
    if (!jobId || !scopeIsCurrent) return;
    let live = true, timer: number | undefined;
    const requestedScope = currentScopeKey;
    const read = async () => {
      try { const value = await gateway.rtlPreview(id, jobId); if (!live || activeScope.current !== requestedScope) return; setPreview(value); setError(''); if (!terminal.includes(value.job.state)) timer = window.setTimeout(read, 2000); }
      catch (caught) { if (live && activeScope.current === requestedScope) setError(gatewayReason(caught)); }
    };
    void read(); return () => { live = false; window.clearTimeout(timer); };
  }, [id, jobId, statusRetry, scopeIsCurrent, currentScopeKey]);
  const launch = async () => {
    if (!scopeIsCurrent || !readiness?.preview_available || !consent || busy) return;
    const initiatingProjectId = id;
    const initiatingDraftHash = readiness.draft_design_hash;
    const initiatingScope = currentScopeKey;
    const generation = launchGeneration.current;
    setBusy(true); setError('');
    try {
      const job = await gateway.launchRtlPreview(initiatingProjectId, initiatingDraftHash);
      if (generation !== launchGeneration.current || activeScope.current !== initiatingScope) return;
      setJobId(job.job_id); setPreview(null);
    } catch (caught) {
      if (generation === launchGeneration.current && activeScope.current === initiatingScope) setError(gatewayReason(caught));
    } finally {
      if (generation === launchGeneration.current && activeScope.current === initiatingScope) setBusy(false);
    }
  };
  const renderRows = (rows: M5RtlPrototype[]) => rows.map(row => <tr key={row.topology_id} className={selected === row.topology_id ? 'is-selected' : ''}>
    <th><button className="delivery-row-select" aria-pressed={selected === row.topology_id} onClick={() => setSelected(row.topology_id)}>{row.label}<span className="mono">{row.topology_id}</span></button></th>
    <td>{prototypeFileState(row)}</td><td>{evidenceState(row.generation_completeness)}</td><td>{evidenceState(row.proof_status)}</td><td>{evidenceState(row.lint_status)} / {evidenceState(row.simulation_status)}</td><td>{evidenceState(row.qualification_status)}</td>
  </tr>);
  const selectedRow = protos?.prototypes.find(row => row.topology_id === selected);
  const required = protos?.prototypes.filter(row => row.required) ?? [];
  const optional = protos?.prototypes.filter(row => !row.required && row.catalog_family !== null) ?? [];
  const nonTarget = protos?.prototypes.filter(row => row.catalog_family === null) ?? [];
  return <>
    <Section title="Research RTL evidence" actions={<Button onClick={() => setRefresh(value => value + 1)} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh evidence'}</Button>}>
      <details className="delivery-details"><summary>Chipyard source · all 14 topologies</summary><p>Native exporters, shared source, and KNCube implementation. Source only; no build or qualification.</p><a className="button" href={gateway.rtlSourcesArchiveUrl()} download>Download all 14 sources</a></details>
      {loading && <p role="status">Loading current research RTL evidence…</p>}
      {catalogError && <Notice tone="red">Research catalog unavailable: {catalogError} Use Refresh evidence to retry. No offline snapshot is shown.</Notice>}
      {protos && <><div className="toolbar"><Badge tone="neutral">Required targets · {protos.counts.required_present} present / {protos.counts.required_total}</Badge><Badge tone="neutral">Missing or unknown · {protos.counts.required_missing_or_unknown}</Badge><Badge tone="neutral">Optional · {protos.counts.optional_total} · non-target · {protos.counts.non_target_total}</Badge></div>
        <div className="table-scroll"><table className="delivery-table"><thead><tr><th scope="col">Required target</th><th scope="col">File presence</th><th scope="col">Generation</th><th scope="col">Historical proof</th><th scope="col">Lint / simulation</th><th scope="col">Qualification</th></tr></thead><tbody>{renderRows(required)}</tbody></table></div>
        {optional.length > 0 && <details><summary>Optional targets ({optional.length})</summary><div className="table-scroll"><table className="delivery-table"><thead><tr><th>Target</th><th>File presence</th><th>Generation</th><th>Historical proof</th><th>Lint / simulation</th><th>Qualification</th></tr></thead><tbody>{renderRows(optional)}</tbody></table></div></details>}
        {nonTarget.length > 0 && <details><summary>Non-target entries ({nonTarget.length})</summary><div className="table-scroll"><table><thead><tr><th>Entry</th><th>Status</th></tr></thead><tbody>{nonTarget.map(row => <tr key={row.topology_id}><th>{row.label} <span className="mono">{row.topology_id}</span></th><td>{prototypeFileState(row)}</td></tr>)}</tbody></table></div></details>}
        {protos.artifacts.length > 0 && <details className="delivery-details"><summary>Generated evidence inventory</summary><p>These bounded metadata artifacts describe generated research output; they do not imply qualification.</p><ul className="delivery-artifacts">{protos.artifacts.map(file => <li key={file.artifact_id + file.name}><span className="mono delivery-filename" title={file.name}>{file.name}</span><span>{artifactSize(file.size_bytes)}</span><a className="button" href={gateway.rtlPrototypeArtifactUrl(file)} download>Download</a></li>)}</ul></details>}
        {selectedRow && <details className="delivery-details"><summary>{selectedRow.label} · {selectedRow.topology_id}</summary><p>{selectedRow.detail}</p><dl className="delivery-evidence"><dt>Source lineage</dt><dd>{evidenceState(selectedRow.lineage)}</dd><dt>Historical snapshot</dt><dd>{selectedRow.historical_snapshot.reported_verilog}; proof: {selectedRow.historical_snapshot.reported_proof}</dd><dt>Generation</dt><dd>{evidenceState(selectedRow.generation_completeness)}</dd><dt>Source reproduction</dt><dd>{evidenceState(selectedRow.source_reproduction_status)}</dd><dt>Project match</dt><dd>Not established.</dd></dl>
          <h4>Available artifacts</h4>{selectedRow.artifacts.length ? <ul className="delivery-artifacts">{selectedRow.artifacts.map(file => <li key={`${file.artifact_id}:${file.name}`}><span className="mono delivery-filename" title={file.name}>{file.name}</span><span>{artifactSize(file.size_bytes)}</span><a className="button" href={gateway.rtlPrototypeArtifactUrl(file)} download aria-label={`Download ${file.name} for ${selectedRow.label}`}>Download</a></li>)}</ul> : <p>No artifacts available.</p>}
        </details>}
      </>}
    </Section>
    <Section title="Current project preview">
      {scopeIsCurrent && readiness && <><Notice tone="amber"><strong>Final RTL unavailable.</strong> Preview may still be supported.</Notice>
        {readiness.parameterized_source_available && readiness.revision_id && <><a className="button" href={gateway.revisionChipyardSourceArchiveUrl(readiness.revision_id)} download>Download this revision’s Chipyard source</a><p className="meta-line">Exact graph and recorded routes. Source only; native selector and router-pipeline equivalence unverified.</p></>}
        {readiness.parameterized_source_blocker && <details><summary>Project source blocker</summary><p>{readiness.parameterized_source_blocker}</p></details>}
        <details><summary>Why / preview limits</summary><p>{readiness.final_rtl_reason}</p><ul>{[...readiness.limitations, ...readiness.preview_blockers].map((reason, index) => <li key={`${index}-${reason}`}>{reason}</li>)}</ul></details>
        {!readiness.preview_available && <p className="meta-line"><PageLink page="flow/search">Choose a supported fabric</PageLink> to enable preview.</p>}
        <label className="check-row"><input type="checkbox" checked={consent} disabled={!readiness.preview_available} onChange={event => setConsent(event.target.checked)} />Generate limited topology-only RTL.</label>
        <Button disabled={!readiness.preview_available || !consent || busy || (!!preview && !terminal.includes(preview.job.state))} onClick={launch}>{busy ? 'Submitting…' : 'Generate supported RTL preview'}</Button>
      </>}
      {!scopeIsCurrent && <p role="status">Loading delivery state for the selected project revision…</p>}
      {jobId && scopeIsCurrent && error && <Button onClick={() => { setError(''); setStatusRetry(value => value + 1); }}>Retry preview status</Button>}
      {scopeIsCurrent && preview?.stale && <Notice tone="amber">This preview was generated from a different draft. Its manifest is not evidence for the current address map; regenerate after compiling.</Notice>}
      {scopeIsCurrent && preview && <div className="toolbar"><Badge tone={preview.job.state === 'COMPLETED' ? 'green' : preview.job.state === 'FAILED' || preview.job.state === 'REFUSED' ? 'red' : 'blue'}>{preview.job.state.toLowerCase()}</Badge>{preview.manifest && <><span>Verilator lint · {preview.manifest.lint.status}</span>{preview.manifest.lint.warning_count !== undefined && <span>warnings · {preview.manifest.lint.warning_count}</span>}{preview.manifest.address_decode?.lint && <><span>addr_decode lint · {preview.manifest.address_decode.lint.status}</span>{preview.manifest.address_decode.lint.warning_count !== undefined && <span>warnings · {preview.manifest.address_decode.lint.warning_count}</span>}</>}<a className="button" href={gateway.rtlPreviewArchiveUrl(id, jobId)} download>Download preview archive & manifest</a></>}{preview.job.error_message && <Notice tone="red">{preview.job.error_message}</Notice>}</div>}
      {scopeIsCurrent && error && <Notice tone="red">{error}</Notice>}
    </Section>
    <Assumptions rows={[
      ['Research RTL presence', 'File presence of research Verilog says nothing about correctness, equivalence or qualification. Research never upgrades the product preview.'],
      ['Product preview scope', 'The preview is topology-only, final_implementation stays False; a stale manifest carries no address-map evidence.'],
      ['Qualification', 'A completed run says the flow ran; it does not certify hardware. Nothing here flips final_implementation.'],
    ]} />
  </>;
}
