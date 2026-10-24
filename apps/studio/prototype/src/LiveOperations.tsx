import { useEffect, useRef, useState } from 'react';
import { JobEvents } from './JobEvents';
import { StudyAdoption } from './StudyAdoption';
import { gateway, gatewayReason, type Job } from './gateway';
import { useProject, type LoadedProject } from './project';
import { Badge, Button, Field, Notice, PageLink, Properties, Section, downloadJson } from './ui';

export function useGatewayDocument(key: string, read: () => Promise<Record<string, any>>) {
  const reader = useRef(read); reader.current = read;
  const [result, setResult] = useState<{ key: string; data?: Record<string, any>; error?: string }>({ key: '' });
  useEffect(() => { let live = true; const call = reader.current; setResult({ key }); call().then(data => { if (live) setResult({ key, data }); }).catch(e => { if (live) setResult({ key, error: gatewayReason(e) }); }); return () => { live = false; }; }, [key]);
  return result.key === key ? result : { key };
}
function DocumentState({ error }: { error?: string }) { return error ? <Notice tone="red">{error}</Notice> : <p>Loading…</p>; }
const terminal = (job: Job) => ['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(job.state);
export function useGatewayJob(id: string) {
  const [job, setJob] = useState<Job | null>(null), [error, setError] = useState(''), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true, timer: number | undefined;
    setJob(null); setError('');
    const poll = async () => {
      try { const value = await gateway.job(id); if (!live) return; setJob(value); if (!terminal(value)) timer = window.setTimeout(poll, 2000); }
      catch (e) { if (live) setError(gatewayReason(e)); }
    };
    if (id) void poll();
    return () => { live = false; window.clearTimeout(timer); };
  }, [id, refresh]);
  return { job, error, retry: () => setRefresh(n => n + 1), cancel: async () => { try { await gateway.cancelJob(id); setRefresh(n => n + 1); } catch (e) { setError(gatewayReason(e)); } } };
}

export function LiveCapabilities({ project }: { project: LoadedProject }) {
  const { data, error } = useGatewayDocument(`capabilities:${project.detail.project.project_id}`, async () => ({ registry: await gateway.capabilities(), gaps: await gateway.capabilityGaps() }));
  if (!data) return <div className="view-main"><DocumentState error={error} /></div>;
  return <div className="view-main"><Notice>Backend registry and refusal sites. Installation is not configuration-specific qualification.</Notice>
    <Section title="Registered backend support"><div className="table-scroll"><table><thead><tr><th>Backend</th><th>Lowering</th><th>Execution</th><th>Evidence / scope</th></tr></thead><tbody>{Object.entries(data.registry.backends ?? {}).map(([name, value]: [string, any]) => <tr key={name}><th>{name}</th><td>{value.lowering ?? 'Not reported'}</td><td>{value.execution ?? 'Not reported'}</td><td>{value.fidelity_note ?? value.profile ?? 'Not reported'}</td></tr>)}</tbody></table></div></Section>
    <Section title="Backend capability gaps"><div className="table-scroll"><table><thead><tr><th>Capability</th><th>Source</th><th>State</th></tr></thead><tbody>{(data.gaps.gaps ?? []).map((g: any, i: number) => <tr key={i}><th>{g.capability}</th><td className="mono">{g.source}:{g.line}</td><td>Open</td></tr>)}</tbody></table></div><p>{data.gaps.note}</p></Section>
    <Section title="Deferred qualification"><Properties rows={Object.entries(data.registry.deferred ?? {}).map(([name, value]) => [name, String(value)])} /></Section>
    <Button onClick={() => downloadJson('backend-capabilities.json', data)}>Export registry JSON</Button><PageLink page="verify/obligations">Review this project’s design obligations</PageLink><PageLink page="analysis/summary">Review revision evaluation plan</PageLink>
  </div>;
}

const obligationTone = (state: string) => state === 'RESOLVED' ? 'green' as const : state === 'NOT_APPLICABLE' ? 'neutral' as const : 'amber' as const;
export function LiveObligations({ project }: { project: LoadedProject }) {
  const id = project.detail.project.project_id;
  const { data, error } = useGatewayDocument(`obligations:${id}:${project.detail.active_revision_id ?? ''}`, () => gateway.obligations(id));
  if (!data) return <div className="view-main"><DocumentState error={error} /></div>;
  const obligations = data.obligations ?? [];
  return <div className="view-main">
    <Notice tone="blue"><strong>Design obligations, not capability gaps.</strong> Every row is derived by the gateway from this project’s draft, latest active run, and declared product limits. Resolved means measured evidence satisfies that stated scope; it never means RTL or physical qualification.</Notice>
    <Properties rows={[[ 'Project', project.detail.project.name ], ['Revision', data.revision_id ?? 'No active revision' ], ['Run', data.run_id ?? 'No run' ], ['Open', String(data.counts.OPEN ?? 0) ], ['Blocking open', String(data.counts.blocking_open ?? 0) ], ['Resolved', String(data.counts.RESOLVED ?? 0) ], ['Not applicable', String(data.counts.NOT_APPLICABLE ?? 0) ], ['Source', data.source ]]} />
    <Section title="Outstanding engineering obligations" actions={<Button onClick={() => downloadJson(`${id}-obligations.json`, data)}>Download register</Button>}>
      <div className="table-scroll"><table><thead><tr><th>Obligation</th><th>Question</th><th>Scope</th><th>State</th><th>Evidence</th><th>Next action</th></tr></thead><tbody>
        {obligations.map((row: any) => <tr key={row.obligation_id}>
          <th><span className="mono">{row.obligation_id}</span><br />{row.title}{row.blocking && row.state === 'OPEN' && <><br /><Badge tone="red">Blocking</Badge></>}</th>
          <td>{row.question}</td>
          <td>{row.scope}</td>
          <td><Badge tone={obligationTone(row.state)}>{row.state}</Badge></td>
          <td><p>{row.evidence?.summary ?? 'No evidence summary.'}</p><details><summary>Evidence record</summary><pre className="code-preview">{JSON.stringify({ evidence: row.evidence, sources: row.sources }, null, 2)}</pre></details></td>
          <td>{row.next_action}</td>
        </tr>)}
      </tbody></table></div>
    </Section>
    <p>{data.note}</p>
    <PageLink page="verify/support">Backend capability gaps are separate</PageLink>
  </div>;
}
export function LiveDelivery({ project }: { project: LoadedProject }) {
  const { run } = useProject(), revision = project.detail.active_revision_id;
  const { data, error } = useGatewayDocument(`delivery:${revision}`, () => revision ? gateway.revisionArtifacts(revision) : Promise.reject(new Error('Compile a revision first.')));
  if (!data) return <div className="view-main"><DocumentState error={error} /></div>;
  return <div className="view-main"><Notice>Compiled artifact references, not generated RTL or physical signoff.</Notice>
    <Section title="Revision output manifest" actions={<Button primary onClick={() => downloadJson(`${revision}-manifest.json`, data)}>Download revision manifest</Button>}><Properties rows={[[ 'Project', project.detail.project.name ], ['Revision', revision ?? 'None' ], ['Design hash', data.design_hash ?? 'Not reported' ], ['Certificate', data.certificate_id ?? 'Not reported' ]]} />
      <div className="table-scroll"><table><thead><tr><th>Artifact</th><th>Identity</th><th>Compiler checks</th></tr></thead><tbody>{(data.nodes ?? []).map((node: any) => <tr key={node.artifact}><th>{node.label ?? node.artifact}</th><td className="mono">{node.hash}</td><td>{(node.proved_by ?? []).join(', ') || 'None reported'}</td></tr>)}</tbody></table></div>
    </Section><Section title="Export scope"><Properties rows={Object.entries(data.compiled_system?.scopes ?? {}).map(([name, value]) => [name, String(value)])} /><p>Manifest identities are backend-reported. File-body download, RTL generation, and ASIC/FPGA implementation are unavailable through this API.</p></Section>
    {run.phase === 'loaded' && <Button onClick={() => downloadJson(`${run.data.detail.run_id}-evidence-index.json`, { run: run.data.detail, artifacts: run.data.artifacts, integrity: run.data.integrity })}>Download run evidence index</Button>}
  </div>;
}

export function LiveExplore({ project }: { project: LoadedProject }) {
  const id = project.detail.project.project_id, revision = project.detail.active_revision_id;
  const { data: caps, error: capError } = useGatewayDocument(`optimization-capabilities:${id}`, gateway.optimizationCapabilities);
  const [parameter, setParameter] = useState('link_width'), [values, setValues] = useState('64,128'), [approved, setApproved] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const key = `srota-study:${id}:${revision}`;
  const [jobId, setJobId] = useState(() => { try { return sessionStorage.getItem(key) ?? ''; } catch { return ''; } });
  const { job, error: jobError, retry, cancel } = useGatewayJob(jobId);
  const optimizationId = (job?.result as any)?.optimization_id;
  const result = useGatewayDocument(`optimization:${optimizationId ?? ''}`, () => optimizationId ? gateway.optimization(optimizationId) : Promise.resolve({}));
  const numbers = values.split(',').map(v => Number(v.trim()));
  const eligible = (caps?.guided_parameters ?? []).filter((p: any) => p.executable === true && p.qualified_for_certified_optimization === true && ['int', 'bool', 'enum'].includes(p.kind));
  const field = eligible.find((p: any) => p.name === parameter);
  const valid = !!field && field.kind === 'int' && numbers.length > 0 && numbers.length <= 4 && numbers.every(n => Number.isSafeInteger(n) && n > 0) && new Set(numbers).size === numbers.length;
  const submit = async () => { if (!revision || !valid || !approved || busy) return; setBusy(true); setError(''); try {
    const value = await gateway.optimize(revision, { domain: [{ name: parameter, values: numbers }], objectives: [{ metric: 'completion_cycles', direction: 'MIN' }], constraints: [], method: 'grid', budget: { max_evaluations: numbers.length }, seed: 7 });
    if (!value.job_id) throw new Error('Gateway returned no optimization job ID.');
    setJobId(value.job_id); try { sessionStorage.setItem(key, value.job_id); } catch { /* Optional recovery. */ }
  } catch (e) { setError(gatewayReason(e)); } finally { setBusy(false); } };
  return <div className="view-main"><Section title="Bounded backend exploration"><Notice>Immutable revision input; at most four configurations. No candidate is adopted automatically.</Notice>
    <Properties rows={[[ 'Project', project.detail.project.name ], ['Revision', revision ?? 'Compile first' ], ['Objective', 'Minimize completion_cycles' ], ['Method', 'Grid, seed 7' ]]} />
    {capError && <Notice tone="red">{capError}</Notice>}<div className="form-grid"><Field label="Executable optimization parameter"><select value={parameter} onChange={e => { setParameter(e.target.value); setApproved(false); }}>{eligible.filter((p: any) => p.kind === 'int').map((p: any) => <option key={p.name}>{p.name}</option>)}</select></Field><Field label="Parameter values (comma-separated, maximum 4)"><input value={values} onChange={e => { setValues(e.target.value); setApproved(false); }} /></Field></div>
    <p>{field?.reason}</p><label className="check-row"><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} />Approve this revision, objective, and {numbers.length} configurations to run real backends.</label>
    <Button primary disabled={!revision || !valid || !approved || busy || (!!jobId && (!job || !terminal(job)))} onClick={submit}>{busy ? 'Submitting…' : 'Launch bounded study'}</Button>
    {(error || jobError) && <Notice tone="red">{error || jobError}</Notice>}{jobError && <Button onClick={retry}>Retry job status</Button>}
  </Section>
    {job && <Section title="Study job"><Properties rows={[[ 'Job', job.job_id ], ['State', job.state ], ['Error', job.error_message ?? 'None reported' ]]} />{!terminal(job) && <Button disabled={!job.cancellable} onClick={cancel}>Cancel study</Button>}</Section>}
    {jobId && <JobEvents key={jobId} jobId={jobId} />}
    {optimizationId && <Section title="Backend study results">{result.data ? <>
      {(result.data.study?.candidates ?? []).length > 0 && <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Parameter changes</th><th>Compilation</th><th>Eligibility</th></tr></thead><tbody>{result.data.study.candidates.map((candidate: any) => <tr key={candidate.candidate_id}><th className="mono">{candidate.candidate_id}</th><td className="mono">{JSON.stringify(candidate.guided_patch ?? {})}</td><td>{candidate.compilation_status ?? 'Not reported'}</td><td>{candidate.eligibility_reason ?? 'See study evidence'}</td></tr>)}</tbody></table></div>}
      <StudyAdoption key={`${optimizationId}:${project.draftMeta?.design_hash}`} project={project} study={result.data} />
      <Button onClick={() => downloadJson(`${optimizationId}.json`, result.data)}>Download study results</Button><pre className="code-preview">{JSON.stringify(result.data, null, 2)}</pre></> : <DocumentState error={result.error} />}</Section>}
    <PageLink page="analysis/comparison">Compare published runs</PageLink>
  </div>;
}
