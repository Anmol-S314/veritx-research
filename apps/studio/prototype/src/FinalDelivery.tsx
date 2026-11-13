import { useEffect, useRef, useState } from 'react';
import { gateway, gatewayReason, type FinalImplementationEvidence, type RtlPreview, type RtlReadiness } from './gateway';
import type { LoadedProject } from './project';
import { evidenceFamilyKey } from './finalEvidence';
import { Badge, PageLink, Button, Notice, Properties, Section } from './ui';

const terminal = ['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'];

export function FinalDelivery({ project }: { project: LoadedProject }) {
  const id = project.detail.project.project_id;
  const [readiness, setReadiness] = useState<RtlReadiness | null>(null);
  const [finalEvidence, setFinalEvidence] = useState<FinalImplementationEvidence | null>(null);
  const [preview, setPreview] = useState<RtlPreview | null>(null);
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
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
    setReadiness(null); setFinalEvidence(null); setPreview(null); setJobId(''); setError(''); setConsent(false);
    let live = true;
    gateway.rtlReadiness(id).then(value => { if (live) { setReadiness(value); setScopeKey(currentScopeKey); } }).catch(caught => { if (live) { setError(gatewayReason(caught)); setScopeKey(currentScopeKey); } });
    gateway.finalImplementation().then(value => { if (live) setFinalEvidence(value); }).catch(() => { if (live) setFinalEvidence(null); });
    return () => { live = false; };
  // currentScopeKey captures project and revision-bearing inputs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentScopeKey]);
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
  const support = readiness?.preview_support;
  const familyKey = evidenceFamilyKey(support, project.request as Record<string, unknown> | null);
  const familyEvidence = finalEvidence?.families.find(row => row.family === familyKey) ?? null;
  const selectedDesignHash = readiness?.draft_design_hash?.replace(/^sha256:/i, '') ?? null;
  const familyMatches = !!familyEvidence?.design_hash && !!selectedDesignHash && familyEvidence.design_hash === selectedDesignHash;
  const vcMismatch = !!support && support.vc_count != null && support.vc_count !== support.emitted_vcs;
  const composed = readiness?.composed_family_preflight ?? null;
  return <Section title="Current project preview">
    {scopeIsCurrent && readiness && <>
      <Notice tone={readiness.final_rtl_available ? 'blue' : 'amber'}>
        <strong>{readiness.final_rtl_available ? 'Final RTL is available.' : 'Selected-project final RTL is not available.'}</strong>{' '}
        {readiness.final_rtl_available
          ? 'This revision carries a final implementation artifact.'
          : 'The selected revision can generate a topology-only preview. That preview is not final RTL, not simulation-equivalent for this design, and not hardware-qualified.'}
      </Notice>
      {support && <>
        <Properties rows={[
          ['Preview path', <Badge tone="amber">{support.code}</Badge>],
          ['Fabric', `${support.topology_family ?? support.topology_kind ?? '—'} · ${support.router_count ?? '—'} routers · ${support.connected ? 'connected' : 'not connected'} · ${support.reciprocal ? 'reciprocal' : 'not reciprocal'} · ${support.shared_wire_links} shared wire${support.shared_wire_links === 1 ? '' : 's'}`],
          ['VC scheme', <>{support.emitted_vcs} emitted{support.vc_count != null ? ` · ${support.vc_count} measured` : ''}{vcMismatch && <Badge tone="amber">Mismatch</Badge>}</>],
          ['Composed-family preflight', composed ? (composed.feasible ? 'Feasible · not run' : <Badge tone="red">Blocked</Badge>) : 'Not reported'],
          ['Family evidence', familyEvidence ? <>{familyEvidence.family} · {familyEvidence.final_implementation ? 'A1–A10 closed' : `${familyEvidence.open_rows.length} row${familyEvidence.open_rows.length === 1 ? '' : 's'} open`} · {familyMatches ? 'this design' : 'different design'}</> : 'Not exposed for this family'],
          ['Physical implementation', 'Not run for this revision; no placed or timed artifact'],
        ]} />
        {(composed?.blockers?.length || composed?.blocker) && <Notice tone="amber">
          <strong>Composed-family emission is blocked for this revision.</strong>
          <ul>{(composed.blockers?.length ? composed.blockers : [composed.blocker!]).map((blocker, index) => <li key={`${index}-${blocker}`}>{blocker}</li>)}</ul>
          The final artifact needs a packet width of at least {composed.required_flit_width_bits} bits (currently {composed.flit_width_bits}) or a data width of at most {composed.flit_width_bits - 6} bits (currently {composed.data_width_bits}), and a memory group with exactly one endpoint (currently {composed.memory_endpoints ?? 'not reported'}). Change the design, compile, and re-evaluate. The topology-only preview is not a substitute. <PageLink page="flow/optimize">Refine packet/link width</PageLink>
        </Notice>}
        {vcMismatch && <Notice tone="amber"><strong>VC scheme mismatch.</strong> The preview emits {support.emitted_vcs} VCs; this revision measured {support.vc_count}. The preview is not a simulation-equivalent version of this design.</Notice>}
        {familyEvidence && <Notice tone={familyMatches ? 'blue' : 'amber'}>
          <strong>{familyMatches ? 'Composed-family evidence is bound to this design.' : 'Composed-family evidence is for a different design.'}</strong>{' '}
          {familyEvidence.family} evidence design {familyEvidence.design_hash?.slice(0, 12) ?? '—'}… vs this revision {selectedDesignHash?.slice(0, 12) ?? '—'}…. {familyMatches ? 'A1–A10 are recorded; physical implementation and signoff are still not claimed.' : 'The selected-project preview above is the only RTL bound to this revision.'}
        </Notice>}
        <p className="meta-line">Preview includes address decode, OrderingFSM, CDC cells and AXI5/CHI/TileLink/custom adapters. Those features do not make it simulation-equivalent or hardware-qualified.</p>
      </>}
      {readiness.parameterized_source_available && readiness.revision_id && <div className="toolbar toolbar-start">
        <a className="button" href={gateway.revisionChipyardSourceArchiveUrl(readiness.revision_id)} download>Download Chipyard source</a>
        <small className="muted">Exact graph and recorded routes; native selector equivalence is unverified.</small>
      </div>}
      <div className="toolbar flow-rtl-actions">
        <label className="check-row"><input type="checkbox" checked={consent} disabled={!readiness.preview_available} onChange={event => setConsent(event.target.checked)} />Generate limited topology-only RTL. Not selected-project final RTL.{vcMismatch ? ` It emits ${support?.emitted_vcs} VCs while this design measured ${support?.vc_count}.` : ''}</label>
        <Button primary disabled={!readiness.preview_available || !consent || busy || (!!preview && !terminal.includes(preview.job.state))} onClick={launch}>{busy ? 'Submitting…' : 'Generate topology-only preview'}</Button>
        {!readiness.preview_available && <PageLink page="flow/search">Choose a supported fabric</PageLink>}
        <details className="inline-details"><summary>Limits</summary><p>{readiness.final_rtl_reason}</p><ul>{[...readiness.limitations, ...readiness.preview_blockers, 'Physical implementation: not run for this revision; no placed or timed artifact.'].map((reason, index) => <li key={`${index}-${reason}`}>{reason}</li>)}</ul></details>
      </div>
    </>}
    {!scopeIsCurrent && <p role="status">Loading delivery state for the selected project revision…</p>}
    {scopeIsCurrent && error && <Notice tone="red">{error}{jobId && <Button onClick={() => { setError(''); setStatusRetry(value => value + 1); }}>Retry preview status</Button>}</Notice>}
    {scopeIsCurrent && preview?.stale && <Notice tone="amber">This preview was generated from a different draft. Regenerate after compiling.</Notice>}
    {scopeIsCurrent && preview && <div className="toolbar">
      <span className="badge">{preview.job.state.toLowerCase()}</span>
      {preview.manifest && <>
        <span className="muted">Verilator lint · {preview.manifest.lint.status}</span>
        <Badge tone={preview.manifest.final_implementation ? 'green' : 'amber'}>{preview.manifest.final_implementation ? 'Final implementation' : 'Preview'}</Badge>
        {preview.manifest.lint.warning_count != null && <span className="muted">{preview.manifest.lint.warning_count} warnings</span>}
        <span className="muted">{preview.manifest.emitted_vcs} VCs</span>
      </>}
      {preview.job.error_message && <span className="error-text">{preview.job.error_message}</span>}
      <a className="button" href={gateway.rtlPreviewArchiveUrl(id, jobId)} download>Download preview archive &amp; manifest</a>
    </div>}
  </Section>;
}
