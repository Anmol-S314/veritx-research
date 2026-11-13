import { useEffect, useState, type ChangeEvent } from 'react';
import { architecturePackage, localChecks } from './checks';
import { BASE_REVISION, candidateById, criteria, event, initialState, restoreState, type Draft, type PageId } from './model';
import { Assumptions, Badge, Button, Dialog, Empty, Field, Icon, Inspector, Notice, Outcome, PageLink, Properties, Section, StatusDot, downloadJson, type ViewProps } from './ui';
import { GatewayProjects } from './GatewayProjects';
import { desktopGatewayBase } from './desktop';
import { GATEWAY_START, gateway, type Job } from './gateway';
import { bytes as formatBytes, stamp } from './format';
import { LiveChecks, LiveEvidence, LiveGate } from './LiveAnalysis';
import { JobEvents } from './JobEvents';
import { useLoadedProject, useProject } from './project';
import { LiveCapabilities, LiveDelivery, LiveObligations, useGatewayDocument } from './LiveOperations';

export function OperationalViews(props: ViewProps & { page: PageId }) {
  const project = useLoadedProject();
  if (project && props.page === 'verify/support') return <LiveCapabilities project={project} />;
  if (project && props.page === 'verify/obligations') return <LiveObligations project={project} />;
  if (project && props.page.startsWith('deliver/')) return <LiveDelivery project={project} />;
  if (props.page.startsWith('verify/')) return <VerifyView {...props} />;
  if (props.page.startsWith('deliver/')) return <DeliverView {...props} />;
  if (props.page === 'shared/projects') return <ProjectsView {...props} />;
  if (props.page === 'shared/environment') return <EnvironmentView />;
  return <JobsView {...props} />;
}
const OBLIGATIONS = [
  { id: 'OBL-TXN-01', name: 'Transaction latency measurement', question: 'Which supported measurement captures complete transaction P95 for REQ-LAT-04?', scope: 'Requirement assessment', route: 'verify/evidence' as const },
  { id: 'OBL-CDC-01', name: 'Domain-crossing implementation', question: 'What implementation and reset strategy support the declared memory/host crossings?', scope: 'Interface implementation', route: 'design/domains' as const },
  { id: 'OBL-RTL-01', name: 'Configuration-specific RTL eligibility', question: 'Which generator and configuration envelope are actually integrated and qualified?', scope: 'Hardware output eligibility', route: 'verify/support' as const },
  { id: 'OBL-TGT-01', name: 'ASIC / FPGA qualification', question: 'Which target-specific tools, constraints, and evidence establish an implementation result?', scope: 'Target implementation', route: 'deliver/readiness' as const },
];
function VerifyView({ state, setState, notify, navigate, page }: ViewProps & { page: PageId }) {
  const live = useLoadedProject();
  const candidate = candidateById(state.selectedCandidate);
  const [selected, setSelected] = useState('LOCAL-ADDR-01'), [target, setTarget] = useState('ASIC'), [obligation, setObligation] = useState(OBLIGATIONS[0]);
  const recorded = state.checks?.findings.find(f => f.id === selected);
  const evidence = { origin: 'Authored illustrative fixture; not a simulator artifact', design: BASE_REVISION, workload: 'ResNet50_Burst [w12]', requirements: 'r5', candidate: candidate.id, run: candidate.run, window: { phase: 'Phase 2', cycles: 450000, networkClockMHz: 1400 }, observations: { packetP99Ns: candidate.latency, aggregateDeliveredGBps: candidate.throughput, transactionP95: null }, limitations: ['No complete transaction measurement', 'No observed packet-path trace', 'No RTL correspondence or target qualification'] };

  if (live && (page === 'verify/evidence' || page === 'verify/overview' || page === 'verify/checks')) return <LiveGate>{(project, loaded) => page === 'verify/checks' ? <LiveChecks project={project} run={loaded} /> : <LiveEvidence project={project} run={loaded} />}</LiveGate>;
  if (page === 'verify/evidence') return <div className="view-layout">
    <div className="view-main">
      <Section title={`${candidate.run ?? candidate.id} · claim scope`}>
        <Properties rows={[
          ['Captured design reference', BASE_REVISION],
          ['Workload', 'ResNet50_Burst [w12]'],
          ['Recorded packet P99', candidate.latency === null ? 'Unavailable' : `${candidate.latency} ns`],
          ['Aggregate delivered throughput', candidate.throughput === null ? 'Unavailable' : `${candidate.throughput} GB/s`],
          ['REQ-LAT-04 · transaction P95', 'Not evaluated'],
          ['Current draft', `${state.draft.id} edit ${state.draft.revision}; not evaluated by this fixture`],
          ['Integrity / signature', 'Not supplied'],
        ]} />
      </Section>
      <Section title="Safe read-only fixture preview" actions={<Button onClick={() => downloadJson('network-observation-fixture.json', evidence)}><Icon name="download" />Download sample JSON</Button>}>
        <pre className="code-preview">{JSON.stringify(evidence, null, 2)}</pre>
      </Section>
      <Assumptions rows={[
        ['Source', 'Authored illustrative fixture; not collected tool evidence.'],
        ['Scope', 'Packet P99 and aggregate delivered throughput for ResNet50_Burst [w12]. Packet measurements do not assess transaction P95.'],
        ['Not supplied', 'Collection process, backend version, proof certificate, tool run, or signature.'],
        ['Non-claims', 'Complete transaction latency, deadlock or starvation freedom, CDC correctness, RTL generation and synthesizability, achieved timing, power, or physical signoff.'],
      ]} />
    </div>
    <Inspector title="What this supports">
      <h3>Scoped network observations</h3>
      <PageLink page="explore/results">Return to candidate results</PageLink>
    </Inspector>
  </div>;
  if (page === 'verify/support') return <div className="view-layout">
    <div className="view-main">
      <div className="toolbar">
        <Field label="Implementation target context"><select value={target} onChange={e => setTarget(e.target.value)}><option>ASIC</option><option>FPGA</option></select></Field>
        <Badge>Target-specific qualification is independent</Badge>
      </div>
      <Section title="Configuration capabilities">
        <div className="table-scroll"><table><thead><tr><th>Configuration / component</th><th>Intent model</th><th>Live simulation</th><th>RTL generation</th><th>{target} implementation</th></tr></thead><tbody>
          {['4×4 mesh / 128-bit links', '2:1 declared concentrator', 'Host / memory interface intent', 'Compute traffic models'].map(name => <tr key={name}><th>{name}</th><td><Badge tone="blue">Editable description</Badge></td><td>Not connected</td><td>Not established</td><td>Not evaluated</td></tr>)}
        </tbody></table></div>
      </Section>
      <Section title="Local operations actually implemented">
        <Properties rows={[
          ['Address intervals', 'In-browser overlap arithmetic'],
          ['Endpoint references', 'In-browser reference and occupancy checks'],
          ['Queue storage', 'Declared-capacity calculation'],
          ['Architecture export', 'JSON description only'],
          ['Backend capture support', 'Unknown until integration'],
        ]} />
      </Section>
      <Assumptions rows={[
        ['Scope', 'Sample capability scope; installed tools and licences are not checked.'],
        ['Targets', 'ASIC libraries and FPGA device/tool mappings are distinct obligations. Changing the target context does not qualify it.'],
      ]} />
    </div>
    <Inspector title="Capability boundary">
      <h3>{target} context</h3>
      <PageLink page="verify/obligations">Inspect implementation obligations</PageLink>
      <PageLink page="deliver/readiness">Review available outputs</PageLink>
    </Inspector>
  </div>;
  if (page === 'verify/obligations') return <div className="view-layout">
    <div className="view-main">
      <Section title="Outstanding engineering questions">
        <div className="table-scroll"><table><thead><tr><th>Obligation</th><th>Question</th><th>Scope</th><th>State</th></tr></thead><tbody>
          {OBLIGATIONS.map(o => <tr key={o.id} className={o.id === obligation.id ? 'selected' : ''}><th><button className="text-button mono" onClick={() => setObligation(o)}>{o.id}</button></th><td>{o.question}</td><td>{o.scope}</td><td><Badge tone="amber">Open</Badge></td></tr>)}
        </tbody></table></div>
      </Section>
      <Assumptions rows={[
        ['Obligations', 'Four explicit open questions, not proven defects or invented tapeout rules.'],
        ['Acknowledgement', 'Records awareness only; it does not resolve an obligation.'],
      ]} />
    </div>
    <Inspector title="Selected obligation">
      <h3>{obligation.name}</h3><p>{obligation.question}</p>
      <Properties rows={[
        ['Required resolution', 'A scoped implementation/measurement and its supporting evidence'],
        ['Current status', 'Open'],
        ['Hardware output', 'Not established in this prototype'],
        ['Acknowledgement', 'Records awareness only'],
      ]} />
      <Button onClick={() => { setState(s => event(s, `Acknowledged ${obligation.id}; obligation remains open.`)); notify('Acknowledgement recorded. The obligation remains open.'); }}>Acknowledge, keep open</Button>
      <Button primary onClick={() => navigate(obligation.route)}>Inspect related context<Icon name="arrow" /></Button>
    </Inspector>
  </div>;
  if (page === 'verify/checks') return <div className="view-layout">
    <div className="view-main">
      <Section title="Local check setup" actions={<Button primary onClick={() => { setState(s => event({ ...s, checks: { revision: s.draft.revision, findings: localChecks(s.draft) } }, `Ran local declaration checks on edit ${s.draft.revision}. No hardware checks executed.`)); notify('Local declaration checks completed at their stated scope.'); }}><Icon name="check" />Run local declaration checks</Button>}>
        <Properties rows={[['Input snapshot', `${state.draft.id} · edit ${state.draft.revision}`]]} />
      </Section>
      {state.checks ? <Section title={`Recorded local results · edit ${state.checks.revision}`}>
        {state.checks.revision !== state.draft.revision && <Notice tone="amber">The current draft changed. These local results apply to the previously checked edit, not the current draft.</Notice>}
        <div className="table-scroll"><table><thead><tr><th>Check</th><th>Question</th><th>Result</th></tr></thead><tbody>
          {state.checks.findings.map(f => <tr key={f.id} className={f.id === selected ? 'selected' : ''}><th><button className="text-button mono" onClick={() => setSelected(f.id)}>{f.id}</button></th><td>{f.question}</td><td><Outcome value={f.outcome} /></td></tr>)}
        </tbody></table></div>
      </Section> : <Empty title="No local check record yet">Run the declared checks to capture their input edit and results.</Empty>}
      <Assumptions rows={[
        ['Methods', 'Interval arithmetic; identifier/reference/occupancy checks.'],
        ['Scope', 'Local declaration checks only; no solver, RTL linter, CDC tool, simulator, or physical checker is connected.'],
        ['Not included', 'Runtime decoding, functional behavior, formal proof, CDC, synthesis, physical checks.'],
        ['Provenance', 'No tool version, proof depth, certificate, or signoff result is recorded.'],
      ]} />
    </div>
    <Inspector title="Check finding">
      {recorded ? <><h3 className="mono">{recorded.id}</h3><Outcome value={recorded.outcome} /><p>{recorded.detail}</p><Button onClick={() => navigate(recorded.page)}>Inspect affected design</Button></> : <p>Select a recorded finding after running local checks.</p>}
    </Inspector>
  </div>;
  return <div className="view-layout">
    <div className="view-main">
      <Section title="Selected candidate requirement assessment">
        <div className="table-scroll"><table><thead><tr><th>Criterion</th><th>Value</th><th>Outcome</th><th>Scope</th></tr></thead><tbody>
          {criteria(candidate).map(r => <tr key={r.id}><th><code>{r.id}</code><br />{r.name}</th><td>{r.value}</td><td><Outcome value={r.outcome} /></td><td>{r.reason}</td></tr>)}
        </tbody></table></div>
      </Section>
      <Section title="Evidence domains">
        <div className="table-scroll"><table><thead><tr><th>Domain</th><th>Available evidence</th><th>Boundary</th></tr></thead><tbody>
          <tr><th>Local declaration checks</th><td>{state.checks ? `Recorded at edit ${state.checks.revision}` : 'Not run'}</td><td>In-browser interval and reference checks only</td></tr>
          <tr><th>Network observations</th><td>Authored illustrative fixture</td><td>Not actual collected simulator output</td></tr>
          <tr><th>Formal / RTL / CDC</th><td>Not evaluated</td><td>No tool integration</td></tr>
          <tr><th>ASIC / FPGA implementation</th><td>Not evaluated</td><td>Independent target qualification required</td></tr>
        </tbody></table></div>
      </Section>
      <Assumptions rows={[
        ['Evidence', 'Applies to captured inputs; simulation and hardware qualification are separate.'],
        ['Unmeasured', 'An unavailable value is not zero and not a pass.'],
      ]} />
    </div>
    <Inspector title="Verification context">
      <Properties rows={[
        ['Historical baseline', BASE_REVISION],
        ['Selected candidate', candidate.id],
        ['Current draft', `${state.draft.id} · edit ${state.draft.revision}`],
        ['Open questions', OBLIGATIONS.length],
        ['Whole-design qualification', 'Not established'],
      ]} />
      <div className="stack">
        <PageLink page="verify/checks">Run local checks</PageLink>
        <PageLink page="verify/evidence">Inspect fixture source</PageLink>
        <PageLink page="verify/obligations">Review obligations</PageLink>
        <PageLink page="deliver/readiness">Inspect output readiness</PageLink>
      </div>
    </Inspector>
  </div>;
}
function DeliverView({ state, setState, notify, navigate, page }: ViewProps & { page: PageId }) {
  const [profile, setProfile] = useState('Architecture JSON'), [name, setName] = useState('falcon8-architecture.json'), [includeFixture, setIncludeFixture] = useState(true);
  const output = state.lastExport;
  const validName = /^[a-zA-Z0-9_-]{1,64}\.json$/.test(name);
  const bytes = output ? new TextEncoder().encode(output.content).length : 0;
  function prepare() {
    if (profile !== 'Architecture JSON' || !validName) return;
    const content = JSON.stringify(architecturePackage(state.draft, includeFixture), null, 2) + '\n';
    setState(s => event({ ...s, lastExport: { name, draft: structuredClone(s.draft), content } }, `Prepared ${name} from local edit ${s.draft.revision}. No RTL generated.`)); navigate('deliver/package');
  }
  function download() {
    if (!output) return;
    downloadJson(output.name, JSON.parse(output.content));
    setState(s => event(s, `Requested browser download of ${output.name}. Filesystem completion is controlled by the browser.`));
    notify('Browser download requested. This is an architecture description, not qualified hardware.');
  }
  if (page === 'deliver/configuration') return <div className="view-layout">
    <div className="view-main">
      <Section title="Output profile">
        <Field label="Deliverable"><select value={profile} onChange={e => setProfile(e.target.value)}><option>Architecture JSON</option><option>RTL / SystemVerilog</option><option>ASIC implementation</option><option>FPGA implementation</option><option>Protected RTL</option></select></Field>
        {profile !== 'Architecture JSON' && <Notice tone="amber">{profile} is unavailable: integration and configuration-specific qualification are not established. Select Architecture JSON for a supported descriptive export.</Notice>}
      </Section>
      <Section title="Capture and package options">
        <Properties rows={[
          ['Source', `${state.draft.id} · edit ${state.draft.revision}`],
          ['Local findings', `${localChecks(state.draft).filter(f => f.outcome === 'Violated').length} declaration finding(s); included in export`],
        ]} />
        <Field label="Download filename" hint="Simple JSON filename only; no filesystem path or overwrite promise."><input value={name} onChange={e => setName(e.target.value)} /></Field>
        {!validName && <Notice tone="red">Use letters, digits, hyphens or underscores followed by .json.</Notice>}
        <label className="check-row"><input type="checkbox" checked={includeFixture} onChange={e => setIncludeFixture(e.target.checked)} />Include clearly labelled historical sample reference</label>
      </Section>
      <Button primary disabled={!validName || profile !== 'Architecture JSON'} onClick={prepare}>Prepare local export for review<Icon name="arrow" /></Button>
      <Assumptions rows={[
        ['Output', 'Local architecture-description JSON; no gateway, RTL emitter, synthesis, proprietary IP, or implementation tool is invoked.'],
        ['Included', 'Declared topology, endpoints, mappings, domains, regions, constraints.'],
        ['Not supplied', 'Compute datapaths, controller/PHY IP, RTL, bitstream, physical libraries.'],
        ['Download', 'Browser-controlled; no host directory selection or forced overwrite.'],
      ]} />
    </div>
    <Inspector title="Output boundary">
      <Badge tone="blue">Architecture description only</Badge>
      <PageLink page="verify/checks">Inspect local declaration checks</PageLink>
    </Inspector>
  </div>;
  if (['deliver/job', 'deliver/package', 'deliver/artifacts'].includes(page)) {
    if (!output) return <div className="view-main">
      <Empty title="No local output prepared">No hardware-generation jobs or artifacts exist in this prototype. Prepare an architecture-description package to inspect and download its actual contents.</Empty>
      <PageLink page="deliver/configuration" primary>Configure architecture export</PageLink>
      <Assumptions rows={[['Scope', 'Architecture-description JSON only; no RTL, bitstream, or hardware qualification.']]} />
    </div>;
    const changed = output.draft.revision !== state.draft.revision || output.draft.id !== state.draft.id;
    return <div className="view-layout">
      <div className="view-main">
        <Notice tone={changed ? 'amber' : 'blue'}>{changed ? `Current draft changed. This prepared file still captures ${output.draft.id}, edit ${output.draft.revision}.` : `Prepared from ${output.draft.id}, edit ${output.draft.revision}.`}</Notice>
        {page === 'deliver/job' ? <>
          <Section title="Local export preparation">
            <Properties rows={[
              ['Operation', 'Serialize architecture description'],
              ['Status', 'Prepared locally'],
              ['Input', `${output.draft.id} · edit ${output.draft.revision}`],
              ['Artifacts prepared', '1 JSON file'],
              ['Measured file size', `${bytes.toLocaleString()} UTF-8 bytes`],
              ['Backend / process / exit code', 'Not applicable; no background generator ran'],
              ['Hardware checks', 'Not evaluated'],
            ]} />
          </Section>
          <Section title="Preparation events"><ol className="activity-list">{state.events.filter(e => /[Pp]repared|download/.test(e)).map((e, i) => <li key={i}>{e}</li>)}</ol></Section>
        </> : page === 'deliver/package' ? <>
          <Section title="Package manifest · one actual file">
            <div className="table-scroll"><table><thead><tr><th>Artifact</th><th>Role</th><th>Size</th><th>Inclusion</th></tr></thead><tbody>
              <tr><th className="mono">{output.name}</th><td>Descriptive JSON</td><td>{bytes.toLocaleString()} bytes</td><td>Prepared</td></tr>
            </tbody></table></div>
          </Section>
          <PageLink page="deliver/artifacts">Inspect exact JSON contents<Icon name="arrow" /></PageLink>
        </> : <Section title={output.name} actions={<Badge>Read-only JSON preview</Badge>}><pre className="code-preview">{output.content}</pre></Section>}
        <div className="toolbar">
          <Button primary onClick={download}><Icon name="download" />Download architecture JSON</Button>
          <PageLink page="deliver/configuration">Configure another export</PageLink>
        </div>
        <Assumptions rows={[
          ['Output', 'Architecture-description JSON only; no generated RTL, compute datapath, bitstream, or GDS.'],
          ['Not supplied', 'Vendor IP, licence tokens, physical libraries, credentials.'],
          ['Limits', 'No assertion of timing, power, formal correctness, target qualification, or hardware correctness.'],
          ['Local findings', 'Included in the export, not hidden.'],
        ]} />
      </div>
      <Inspector title="Prepared artifact">
        <Properties rows={[
          ['Filename', output.name],
          ['Captured edit', output.draft.revision],
          ['UTF-8 bytes', bytes.toLocaleString()],
          ['Producer', 'Local prototype serializer'],
          ['Classification', 'Illustrative architecture intent'],
          ['Hardware eligibility', 'Not established'],
          ['Download location', 'Browser-controlled; no forced overwrite'],
        ]} />
        <div className="stack">
          <PageLink page="deliver/job">Preparation record</PageLink>
          <PageLink page="deliver/package">Review manifest</PageLink>
          <PageLink page="deliver/artifacts">Inspect artifact</PageLink>
        </div>
      </Inspector>
    </div>;
  }
  return <div className="view-layout">
    <div className="view-main">
      <Section title="Requested output readiness">
        <div className="table-scroll"><table><thead><tr><th>Output profile</th><th>Scope</th><th>Readiness</th><th>Action</th></tr></thead><tbody>
          <tr><th>Architecture JSON</th><td>Declared design intent and local findings</td><td><Badge tone="blue">Available locally</Badge></td><td><PageLink page="deliver/configuration">Configure</PageLink></td></tr>
          {['RTL / SystemVerilog', 'ASIC implementation', 'FPGA implementation', 'Protected / obfuscated RTL'].map(p => <tr key={p}><th>{p}</th><td>Requires separately integrated and qualified flow</td><td><Badge tone="amber">Not established</Badge></td><td><PageLink page="verify/support">Inspect scope</PageLink></td></tr>)}
        </tbody></table></div>
      </Section>
      <Assumptions rows={[
        ['Eligibility', 'Profile-specific; modeling a system does not mean every block can be generated or implemented.'],
        ['Actual local operation', 'JSON architecture-description export.'],
        ['Compute models', 'No generated datapath.'],
        ['Memory / PHY', 'Supplied integration boundary.'],
        ['ASIC / FPGA evidence', 'Neither is qualified by this prototype.'],
        ['Complete accelerator generation', 'Unsupported here.'],
        ['Obligations', 'Descriptive export remains possible with disclosed findings and does not waive hardware obligations.'],
      ]} />
    </div>
    <Inspector title="Delivery context">
      <h3 className="mono">{state.draft.id}</h3>
      <PageLink page="verify/obligations">Inspect outstanding obligations</PageLink>
      <PageLink page="deliver/configuration" primary>Configure supported export</PageLink>
    </Inspector>
  </div>;
}
function ProjectsView({ state, setState, notify }: ViewProps) {
  const { listPhase } = useProject();
  const [restoring, setRestoring] = useState<Draft | null>(null), [reset, setReset] = useState(false), [imported, setImported] = useState<Draft | null>(null), [error, setError] = useState('');
  function activate(draft: Draft) {
    if (state.archives.length >= 20) { setError('This preview preserves up to 20 prior drafts. Export your project before resetting.'); return; }
    setState(s => event({ ...s, archives: [...s.archives, structuredClone(s.draft)], draft: { ...structuredClone(draft), id: `restored-${s.archives.length + 1}`, revision: s.draft.revision + 1 }, selectedEndpoint: draft.endpoints[0].id }, 'Activated a local snapshot copy; prior active draft preserved.'));
    setRestoring(null); setImported(null); notify('Local snapshot copy activated. No historical evidence was retargeted.');
  }
  async function readImport(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; e.target.value = ''; if (!file) return;
    if (file.size > 2 * 1024 * 1024) { setError('Import is limited to 2 MiB for this local preview.'); return; }
    try { const result = restoreState(await file.text()); if (result.warning) throw new Error('Invalid local-preview project format. Original state was not changed.'); setImported(result.state.draft); setError(''); } catch (err) { setError(err instanceof Error ? err.message : 'Could not read the selected file.'); }
  }
  // The sample project is the offline fallback, not a second project store.
  // Once the gateway answers, this page lists only the user's own projects.
  if (desktopGatewayBase || listPhase !== 'offline') return <div className="view-main flow-page">
    <GatewayProjects />
    <Assumptions rows={[
      ['Source', 'Repository gateway project store at the configured base URL.'],
      ['Scope', 'Gateway projects, their revisions and runs only.'],
      ['Offline fallback', 'The browser sample project is used only when the gateway does not answer.'],
    ]} />
  </div>;
  return <div className="view-layout">
    <div className="view-main">
      <GatewayProjects />
      <Section title="Falcon8_NoC_Gen2" actions={<><Button onClick={() => downloadJson('srota-local-preview-project.json', state)}><Icon name="download" />Export local project</Button><label className="button file-input-label">Import preview project<input type="file" accept="application/json,.json" onChange={readImport} /></label></>}>
        <Properties rows={[
          ['Active draft', state.draft.id],
          ['Current edit', state.draft.revision],
          ['Historical fixture snapshot', BASE_REVISION],
          ['Saved locally', 'When browser storage is available'],
          ['Prior drafts preserved', state.archives.length],
          ['Generated hardware', 'None'],
        ]} />
      </Section>
      {error && <Notice tone="red">{error}</Notice>}
      <Section title="Preserved local drafts">
        <div className="table-scroll"><table><thead><tr><th>Draft</th><th>Edit</th><th>Source candidate</th><th>Queue parameters</th><th>Action</th></tr></thead><tbody>
          {state.archives.map((d, i) => <tr key={i}><th className="mono">{d.id}</th><td>{d.revision}</td><td>{d.fromCandidate ?? 'Manual draft'}</td><td>{d.vcs} VCs × {d.depth} flits</td><td><Button onClick={() => { setError(''); setRestoring(d); }}>Review restore copy</Button></td></tr>)}
        </tbody></table></div>
        {!state.archives.length && <p>No prior drafts yet.</p>}
      </Section>
      <Section title="Reset preview">
        <Button danger onClick={() => setReset(true)}>Review local reset</Button>
      </Section>
      <Assumptions rows={[
        ['Persistence', 'Browser localStorage when available; a browser can evict it. Export important edits.'],
        ['Recovery', 'Limited to explicitly preserved drafts and exported local-project JSON. Invalid saved state is reported, not treated as valid configuration.'],
        ['Reset scope', 'Clears this preview’s local state only; existing Studio data and original exports are untouched.'],
        ['Offline fallback', 'Once the gateway answers, this page lists only gateway projects.'],
        ['Branch adoption', 'Preserves the complete active draft here before switching.'],
      ]} />
    </div>
    <Inspector title="Recovery boundary">
      <PageLink page="shared/environment">Inspect local environment</PageLink>
    </Inspector>
    {(restoring || imported) && <Dialog title={imported ? 'Review imported draft copy' : 'Review restored draft copy'} onClose={() => { setRestoring(null); setImported(null); }}>
      <Properties rows={[
        ['Source draft', (restoring ?? imported)!.id],
        ['Current draft', state.draft.id],
        ['Protection', 'Archive the complete current draft before activating a copy'],
        ['Historical evidence', 'Remains attached to its original inputs'],
      ]} />
      {error && <Notice tone="red">{error}</Notice>}
      <div className="dialog-actions">
        <Button onClick={() => { setRestoring(null); setImported(null); }}>Cancel</Button>
        <Button primary onClick={() => activate((restoring ?? imported)!)}>Preserve current & activate copy</Button>
      </div>
    </Dialog>}
    {reset && <Dialog title="Reset only this local preview?" onClose={() => setReset(false)}>
      <Notice tone="red">This clears this preview’s local edits, preserved drafts, approval previews, and prepared exports.</Notice>
      <Button onClick={() => downloadJson('srota-local-preview-backup.json', state)}>Download project backup first</Button>
      <div className="dialog-actions">
        <Button onClick={() => setReset(false)}>Cancel</Button>
        <Button danger onClick={() => { setState(initialState()); setReset(false); notify('Local preview reset to its illustrative fixture.'); }}>Reset local preview</Button>
      </div>
    </Dialog>}
  </div>;
}
const BACKEND_META: Record<string, { label: string; scope: string }> = {
  BOOKSIM_STANDALONE: { label: 'BookSim standalone', scope: 'Network execution and differential parity' },
  ASTRA2_EMBEDDED_BOOKSIM: { label: 'ASTRA-SIM 2 · embedded BookSim', scope: 'Execution graph and system makespan' },
  RAMULATOR2_HBM3_V1: { label: 'Ramulator 2 · HBM3', scope: 'DRAM timing for declared memory demand' },
};
const FEATURE_LABEL: Record<string, string> = {
  draft_preconditions: 'Draft preconditions',
  optimization_adoption_preconditions: 'Adoption preconditions',
  artifact_bytes: 'Artifact bytes',
  job_events: 'Job events',
  job_logs: 'Job logs',
  agent_runtime: 'Agent runtime',
};
const valueText = (value: unknown) => typeof value === 'string' ? value : value === undefined || value === null ? '—' : JSON.stringify(value);
/** A register value is positive only when it is not negated. `NOT_ESTABLISHED`
 *  contains the substring `ESTABLISHED`, so a plain regex test would paint it
 *  green. */
const qualificationTone = (value?: string): 'green' | 'amber' => value && !/NOT|UNSUPPORTED|BLOCKED|UNKNOWN|UNMEASURED/i.test(value) && /QUALIFIED|ESTABLISHED/i.test(value) ? 'green' : 'amber';
const jobTone = (state?: string): 'neutral' | 'green' | 'red' | 'blue' | 'amber' => !state ? 'neutral' : /COMPLETED/i.test(state) ? 'green' : /FAILED|REFUSED|CANCELLED/i.test(state) ? 'red' : /RUNNING|QUEUED|PREPARING|SUBMITTED/i.test(state) ? 'blue' : 'amber';

function EnvironmentView() {
  const { health, listPhase, listError, refreshList } = useProject();
  const [refresh, setRefresh] = useState(0);
  const [compact, setCompact] = useState(() => { try { return localStorage.getItem('srota-compact-tables') === '1'; } catch { return false; } });
  const [reduced, setReduced] = useState(() => { try { return localStorage.getItem('srota-reduce-motion') === '1'; } catch { return false; } });
  useEffect(() => { document.documentElement.classList.toggle('compact-tables', compact); try { localStorage.setItem('srota-compact-tables', compact ? '1' : '0'); } catch { /* Optional preference. */ } }, [compact]);
  useEffect(() => { document.documentElement.classList.toggle('reduce-motion', reduced); try { localStorage.setItem('srota-reduce-motion', reduced ? '1' : '0'); } catch { /* Optional preference. */ } }, [reduced]);
  const capabilities = useGatewayDocument(`environment:capabilities:${refresh}`, () => gateway.capabilities());
  const qualification = useGatewayDocument(`environment:qualification:${refresh}`, () => gateway.qualification());
  const reports = useGatewayDocument(`environment:reports:${refresh}`, () => gateway.reports());
  const online = listPhase === 'ready' && !!health;
  const stale = !!health?.code?.stale;
  const connectionTone = online ? (stale ? 'amber' as const : 'green' as const) : listPhase === 'offline' ? 'red' as const : 'amber' as const;
  const backends = Object.entries(health?.backends ?? {});
  const present = backends.filter(([, value]) => value.binary_present);
  const features = Object.entries(health?.features ?? {});
  const engines = Object.entries((qualification.data?.engines ?? {}) as Record<string, { role?: string; integration?: string; numerical?: string; limitations?: string[] }>);
  const deferred = Object.entries((qualification.data?.deferred ?? capabilities.data?.deferred ?? {}) as Record<string, unknown>);
  const deferredByKey: Record<string, unknown> = Object.fromEntries(deferred);
  const reportRows = reports.data?.reports ?? [];
  const sourceAge = health?.code?.source_age_s;
  const sourceAgeLabel = sourceAge == null ? 'Not reported' : sourceAge >= 3600 ? `${(sourceAge / 3600).toFixed(1)} h` : sourceAge >= 60 ? `${Math.round(sourceAge / 60)} min` : `${sourceAge.toFixed(1)} s`;
  const refreshAll = () => { refreshList(); setRefresh(value => value + 1); };
  return <div className="view-layout">
    <div className="view-main">
      <Section title="Gateway connection" actions={<><Badge tone={connectionTone}>{online ? (stale ? 'Connected · stale' : 'Connected') : listPhase === 'offline' ? 'Offline' : 'Checking'}</Badge><Button onClick={refreshAll}>Refresh</Button><Button onClick={() => downloadJson('srota-environment-diagnostics.json', { gateway: gateway.base, health, capabilities: capabilities.data, qualification: qualification.data, reports: reports.data })}><Icon name="download" />Download diagnostics</Button></>}>
        <div className="stat-strip">
          <div className="stat"><span>Gateway status</span><strong className="status-line"><StatusDot tone={connectionTone} pulse={online && !stale} />{health?.status ? health.status.toUpperCase() : listPhase === 'offline' ? 'OFFLINE' : 'CHECKING'}</strong><small>{gateway.base}</small></div>
          <div className="stat"><span>API contract</span><strong>{health?.api ? `api/${health.api}` : '—'}</strong><small>Health, projects, revisions, runs, evidence</small></div>
          <div className="stat"><span>Backends present</span><strong>{present.length} / {backends.length}</strong><small>{present.length ? present.map(([key]) => BACKEND_META[key]?.label ?? key).join(' · ') : 'No binary reported'}</small></div>
          <div className="stat"><span>Gateway source</span><strong>{sourceAgeLabel}</strong><small>{health?.code?.stale ? 'Stale code loaded; restart the gateway' : health?.code?.pid ? `PID ${health.code.pid} · loaded source age` : 'Code age not reported'}</small></div>
        </div>
        {listPhase === 'offline' && <Notice tone="amber"><strong>The project gateway is not reachable.</strong> {listError} Start it with <code>{GATEWAY_START}</code> and retry.</Notice>}
        {health?.code?.stale && <Notice tone="amber">The gateway reports that its loaded code is older than the checkout. Restart it before trusting the result below.</Notice>}
        <p className="meta-line">Health and backend availability are host facts reported by the gateway. They do not qualify a design, approve a flow, or establish numerical fidelity.</p>
      </Section>

      <Section title="Execution backends" actions={<Badge>{present.length} of {backends.length} available</Badge>}>
        {backends.length ? <div className="table-scroll"><table className="backend-table"><thead><tr><th>Backend</th><th>Scope</th><th>Binary</th><th>Manifest</th><th>State</th></tr></thead><tbody>
          {backends.map(([key, value]) => <tr key={key}>
            <th><span className="mono">{key}</span><small>{BACKEND_META[key]?.label ?? 'Unmapped gateway backend'}</small></th>
            <td>{BACKEND_META[key]?.scope ?? 'Scope not described by this prototype'}</td>
            <td><Badge tone={value.binary_present ? 'green' : 'red'}>{value.binary_present ? 'Present' : 'Absent'}</Badge></td>
            <td>{value.manifest_present === undefined ? <span className="muted">Not reported</span> : <Badge tone={value.manifest_present ? 'green' : 'red'}>{value.manifest_present ? 'Present' : 'Absent'}</Badge>}</td>
            <td><span className={value.state === 'PRESENT' ? 'status-text green' : 'status-text amber'}>{value.state}</span></td>
          </tr>)}
        </tbody></table></div> : <Empty title="No backend list returned">The health endpoint reports no execution backends. Nothing is substituted here.</Empty>}
      </Section>

      <Section title="Gateway features" actions={<Badge>{features.filter(([, enabled]) => enabled).length} enabled</Badge>}>
        {features.length ? <div className="feature-grid">{features.map(([key, enabled]) => <div className="feature-cell" key={key}><StatusDot tone={enabled ? 'green' : 'neutral'} /><span>{FEATURE_LABEL[key] ?? key.replaceAll('_', ' ')}</span><Badge tone={enabled ? 'green' : 'neutral'}>{enabled ? 'On' : 'Off'}</Badge></div>)}</div> : <p className="meta-line">The gateway reports no optional feature flags.</p>}
      </Section>

      <Section title="Engine qualification" actions={<Badge>Gateway register</Badge>}>
        {qualification.error ? (listPhase === 'offline' ? <p className="meta-line">The qualification register requires the gateway connection above.</p> : <Notice tone="red">{qualification.error}</Notice>) : !qualification.data ? <p role="status">Reading the qualification register…</p> : <>
          {engines.length ? <div className="table-scroll"><table><thead><tr><th>Engine</th><th>Role</th><th>Integration</th><th>Numerical</th><th>Limitations</th></tr></thead><tbody>
            {engines.map(([key, engine]) => <tr key={key}>
              <th className="mono">{key}</th>
              <td>{engine.role ?? '—'}</td>
              <td><Badge tone={qualificationTone(engine.integration)}>{engine.integration ?? 'Not declared'}</Badge></td>
              <td><Badge tone={qualificationTone(engine.numerical)}>{engine.numerical ?? 'Not declared'}</Badge></td>
              <td>{engine.limitations?.length ? <ul className="compact-list">{engine.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul> : <span className="muted">None declared</span>}</td>
            </tr>)}
          </tbody></table></div> : <Empty title="No engine register returned">The qualification endpoint returned no engines.</Empty>}
          {deferred.length > 0 && <div className="deferred-grid">{deferred.map(([key, value]) => <div className="deferred-cell" key={key}><span>{key.replaceAll('_', ' ')}</span><Badge tone={/NOT_RUN|UNSUPPORTED|NOT_ESTABLISHED/i.test(valueText(value)) ? 'amber' : 'neutral'}>{valueText(value)}</Badge></div>)}</div>}
          <p className="meta-line">The register describes the gateway's own integration and numerical evidence. It does not qualify this project, its configuration, or hardware.</p>
        </>}
      </Section>

      <Section title="Generated reports" actions={<Badge>{reportRows.length} files</Badge>}>
        {reports.error ? (listPhase === 'offline' ? <p className="meta-line">The report index requires the gateway connection above.</p> : <Notice tone="red">{reports.error}</Notice>) : !reports.data ? <p role="status">Reading the report index…</p> : reportRows.length ? <div className="table-scroll"><table><thead><tr><th>Report</th><th>Kind</th><th>Size</th><th>Modified</th><th /></tr></thead><tbody>
          {reportRows.map((report: { report_id: string; title: string; kind: string; size_bytes: number; modified_at?: string; media_type?: string }) => <tr key={report.report_id}>
            <th>{report.title}<small className="mono">{report.media_type ?? 'type not reported'}</small></th>
            <td><Badge>{report.kind}</Badge></td>
            <td className="numeric">{formatBytes(report.size_bytes)}</td>
            <td className="mono">{stamp(report.modified_at)}</td>
            <td><a className="button" href={gateway.reportUrl(report.report_id)} target="_blank" rel="noreferrer">Open<Icon name="arrow" size={13} /></a></td>
          </tr>)}
        </tbody></table></div> : <Empty title="No reports generated">The repository report directory is empty. Reports are files produced by earlier runs, not this page.</Empty>}
      </Section>

      <Section title="Local settings" actions={<Badge>Stored in this browser</Badge>}>
        <label className="check-row"><input type="checkbox" checked={compact} onChange={event => setCompact(event.target.checked)} />Compact table rows</label>
        <label className="check-row"><input type="checkbox" checked={reduced} onChange={event => setReduced(event.target.checked)} />Reduce motion</label>
        <p className="meta-line">These preferences apply immediately and are stored locally; they do not change the gateway or the project.</p>
      </Section>
      <Section title="Actual prototype environment">
        <Properties rows={[
          ['Frontend', 'React · separate Vite entry point'],
          ['Assets', 'Local fonts and CSS; no CDN dependency'],
          ['Persistence', 'Browser localStorage, if available'],
          ['Execution backend', online ? `Gateway-managed · ${present.length} of ${backends.length} reported binaries` : 'Not connected'],
          ['Agent runtime / ACP', health?.features?.agent_runtime ? 'Gateway feature reported' : 'Not connected'],
          ['Remote AI', 'Not configured'],
          ['Local inference', 'Not bundled or required'],
        ]} />
      </Section>

      <Section title="Backend and target discovery">
        <div className="table-scroll"><table><thead><tr><th>Capability</th><th>Host availability</th><th>Integration here</th><th>Qualification</th></tr></thead><tbody>
          <tr><th>Network simulator</th><td>{online ? 'Reported by gateway health' : 'Not inspected'}</td><td>{online ? 'BookSim standalone / embedded' : 'Not connected'}</td><td>Not established for this project</td></tr>
          <tr><th>RTL emitter / linter</th><td>Preview emitter only</td><td>Flow · Finalize &amp; RTL</td><td>{valueText(deferredByKey.rtl_verification ?? 'Not established')}</td></tr>
          <tr><th>Formal solver</th><td>Not inspected</td><td>Not connected</td><td>{valueText(deferredByKey.formal_verification ?? 'Not established')}</td></tr>
          <tr><th>ASIC toolchain</th><td>Not inspected</td><td>Not connected</td><td>Not established</td></tr>
          <tr><th>FPGA toolchain</th><td>Not inspected</td><td>Not connected</td><td>Not established</td></tr>
        </tbody></table></div>
      </Section>

      <Assumptions rows={[
        ['Gateway', 'Configured separately; host credentials and network policy are not managed here. The connection chip and this page read health, capabilities, qualification and reports only.'],
        ['Qualification', 'Engine and backend declarations are the gateway\'s own claims about its integration and numerical evidence. They do not qualify the loaded project.'],
        ['Privacy', 'No remote AI or telemetry implementation. Local asset loading is not a claim of certified air-gap isolation, encrypted storage, host firewall enforcement, or secret scrubbing.'],
        ['Downloads', 'Browser downloads contain only the selected local illustrative state.'],
        ['Import caution', 'Do not import confidential artifacts into a prototype without an appropriate policy and implementation review.'],
        ['Not yet integrated', 'Tool discovery, runtime permissions, protected credentials, execution services, enforceable budgets.'],
      ]} />
    </div>
    <Inspector title="Integration boundary">
      <h3>{online ? 'Gateway-backed engineering workspace' : 'Manual-first local preview'}</h3>
      <Properties rows={[
        ['Gateway', online ? `${health?.status ?? 'connected'} · ${gateway.base}` : gateway.base],
        ['Source of truth', online ? 'Gateway project, revision and run records' : 'Browser local illustrative state'],
        ['Live reads', online ? 'Health · capabilities · qualification · reports' : 'None'],
        ['Qualification', 'Separate from backend availability'],
      ]} />
      <PageLink page="shared/projects">Export or recover local drafts</PageLink>
      <PageLink page="shared/jobs">Open jobs, problems &amp; logs</PageLink>
      <PageLink page="verify/support">Inspect capability distinctions</PageLink>
    </Inspector>
  </div>;
}
function JobsView({ state, navigate }: ViewProps) {
  const [tab, setTab] = useState('Jobs');
  const [refresh, setRefresh] = useState(0);
  const [logJobId, setLogJobId] = useState('');
  const { listPhase, listError, project, health, refreshList } = useProject();
  const loaded = project.phase === 'loaded' ? project.data : null;
  const findings = localChecks(state.draft);
  const jobsDocument = useGatewayDocument(`desktop-jobs:${loaded?.detail.project.project_id ?? 'none'}:${refresh}`, () =>
    loaded ? gateway.projectJobs(loaded.detail.project.project_id) : Promise.resolve({ jobs: [] as Job[] }));
  const jobs = (jobsDocument.data?.jobs ?? []) as Job[];
  const active = jobs.filter(job => !['COMPLETED', 'FAILED', 'REFUSED', 'CANCELLED'].includes(job.state));
  const failed = jobs.filter(job => ['FAILED', 'REFUSED', 'CANCELLED'].includes(job.state));
  const selectedLogJob = jobs.find(job => job.job_id === logJobId) ?? active[0] ?? jobs[0] ?? null;
  const refreshJobs = () => { refreshList(); setRefresh(value => value + 1); };
  return <div className="view-main">
    <div className="toolbar">
      <div className="segmented">{['Jobs', 'Problems', 'Logs'].map(t => <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
      {listPhase === 'offline' ? <Badge tone="amber">Gateway unreachable</Badge>
        : loaded ? <Badge tone={active.length ? 'blue' : 'green'}>{jobs.length} gateway job{jobs.length === 1 ? '' : 's'}{active.length ? ` · ${active.length} active` : ''}</Badge>
          : <Badge>No project loaded</Badge>}
    </div>
    {tab === 'Jobs' ? <>
      {listPhase === 'offline'
        ? <Empty icon="terminal" title="No execution backend connected" action={<Button onClick={refreshJobs}>Retry gateway</Button>}>The gateway is unreachable, so no job record can be read. Local preview operations remain available below.</Empty>
        : loaded ? <Section title="Gateway jobs" actions={<><Badge>{jobs.length} recorded</Badge><Button onClick={refreshJobs}>Refresh</Button></>}>
          {jobsDocument.error ? <Notice tone="red">{jobsDocument.error}</Notice> : !jobsDocument.data ? <p role="status">Reading gateway jobs…</p> : jobs.length ? <div className="table-scroll"><table><thead><tr><th>Job</th><th>Kind</th><th>State</th><th>Revision</th><th>Submitted</th><th>Error</th></tr></thead><tbody>
            {jobs.map(job => <tr key={job.job_id}>
              <th className="mono job-id">{job.job_id}</th>
              <td>{job.kind.replaceAll('_', ' ')}</td>
              <td><Badge tone={jobTone(job.state)}>{job.state}</Badge></td>
              <td className="mono">{job.revision_id ?? 'draft-scoped'}</td>
              <td className="mono">{stamp(job.submitted_at)}</td>
              <td>{job.error_message ?? '—'}</td>
            </tr>)}
          </tbody></table></div> : <Empty icon="terminal" title="No gateway jobs recorded">This project has no evaluation, catalog, compile, RTL or agent jobs in the gateway store.</Empty>}
        </Section> : <Empty icon="folder" title="No project loaded" action={<PageLink page="shared/projects" primary>Open projects &amp; revisions</PageLink>}>Gateway jobs are scoped to a project. Load one to inspect its recorded jobs; no job list is invented for the local sample.</Empty>}
      <Section title="Actual local operations">
        <Properties rows={[
          ['Declaration check', state.checks ? `Recorded at edit ${state.checks.revision}` : 'Not run'],
          ['Prepared architecture file', state.lastExport?.name ?? 'None'],
          ['Local scope approval', state.approvedBrief ? 'Preview recorded; no jobs authorized on a backend' : 'Not recorded'],
        ]} />
      </Section>
    </> : tab === 'Problems' ? <>
      <Section title="Gateway health" actions={<Badge tone={listPhase === 'offline' ? 'red' : health?.code?.stale ? 'amber' : 'green'}>{listPhase === 'offline' ? 'Offline' : health?.code?.stale ? 'Stale code' : 'Connected'}</Badge>}>
        <Properties rows={[
          ['Connection', listPhase === 'offline' ? 'Gateway unreachable' : listPhase === 'ready' ? 'Gateway reachable' : 'Checking'],
          ['Gateway status', health?.status ?? 'Not reported'],
          ['Loaded source', health?.code?.stale ? 'Older than the checkout; restart before trusting results' : health ? 'Current' : 'Not reported'],
          ['Absent backends', health ? Object.entries(health.backends).filter(([, value]) => !value.binary_present).map(([key]) => key).join(', ') || 'None' : 'Not reported'],
        ]} />
        {listPhase === 'offline' && <Notice tone="red">{listError} Start the gateway with <code>{GATEWAY_START}</code>.</Notice>}
      </Section>
      <Section title="Local declaration findings">
        <div className="table-scroll"><table><thead><tr><th>Finding</th><th>Outcome</th><th>Scope</th><th>Action</th></tr></thead><tbody>
          {findings.map(f => <tr key={f.id}><th className="mono">{f.id}</th><td><Outcome value={f.outcome} /></td><td>{f.detail}</td><td><Button onClick={() => navigate(f.page)}>Inspect</Button></td></tr>)}
        </tbody></table></div>
      </Section>
      {loaded && failed.length > 0 && <Section title="Gateway job failures" actions={<Badge tone="red">{failed.length}</Badge>}>
        <div className="table-scroll"><table><thead><tr><th>Job</th><th>Kind</th><th>State</th><th>Reason</th></tr></thead><tbody>
          {failed.map(job => <tr key={job.job_id}><th className="mono job-id">{job.job_id}</th><td>{job.kind.replaceAll('_', ' ')}</td><td><Badge tone={jobTone(job.state)}>{job.state}</Badge></td><td>{job.error_message ?? 'No reason reported'}</td></tr>)}
        </tbody></table></div>
      </Section>}
    </> : <>
      {loaded ? (jobs.length ? <>
        <Section title="Gateway job logs" actions={<Badge>{jobs.length} job{jobs.length === 1 ? '' : 's'}</Badge>}>
          <div className="toolbar toolbar-start">
            <Field label="Gateway job"><select value={selectedLogJob?.job_id ?? ''} onChange={event => setLogJobId(event.target.value)}>{jobs.map(job => <option key={job.job_id} value={job.job_id}>{job.job_id.slice(0, 12)} · {job.kind.replaceAll('_', ' ')} · {job.state}</option>)}</select></Field>
            <Button onClick={refreshJobs}>Refresh jobs</Button>
          </div>
          {selectedLogJob && <JobEvents jobId={selectedLogJob.job_id} state={selectedLogJob.state} defaultOpen />}
        </Section>
      </> : <Notice tone="amber">This project has no gateway job, so there is no worker log to stream.</Notice>)
        : <Notice tone="amber">Load a project from <a href="#/shared/projects">Projects &amp; revisions</a> to stream gateway job events and worker logs.</Notice>}
      <Section title="Local prototype activity" actions={<Button onClick={() => downloadJson('srota-local-activity.json', { illustrative: true, events: state.events })}><Icon name="download" />Export activity</Button>}>
        <p className="meta-line">Prototype events from this browser session, not gateway worker logs.</p>
        <ol className="activity-list">{state.events.map((e, i) => <li key={`${i}-${e}`}>{e}</li>)}</ol>
      </Section>
    </>}
    <Assumptions rows={[
      ['Backend', loaded ? `Gateway jobs are read from the project record; health currently reports ${health?.status ?? 'an unread state'}. Job state is the gateway's own state, not a percentage or client timer.` : listPhase === 'offline' ? 'The gateway is unreachable; no backend job is shown or inferred.' : 'No project is loaded; no backend job is shown or inferred.'],
      ['Fixtures', 'Captured candidate fixtures are historical illustrative objects, not running jobs.'],
      ['Activity log', 'Local prototype events, not backend logs.'],
    ]} />
  </div>;
}
