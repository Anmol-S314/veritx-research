import { useState, type ChangeEvent } from 'react';
import { architecturePackage, localChecks } from './checks';
import { BASE_REVISION, candidateById, criteria, event, initialState, restoreState, type Draft, type PageId } from './model';
import { Assumptions, Badge, Button, Dialog, Empty, Field, Icon, Inspector, Notice, Outcome, PageLink, Properties, Section, downloadJson, type ViewProps } from './ui';
import { GatewayProjects } from './GatewayProjects';
import { desktopGatewayBase } from './desktop';
import { LiveChecks, LiveEvidence, LiveGate } from './LiveAnalysis';
import { useLoadedProject, useProject } from './project';
import { LiveCapabilities, LiveDelivery, LiveObligations } from './LiveOperations';

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
function EnvironmentView() {
  return <div className="view-layout">
    <div className="view-main">
      <Section title="Actual prototype environment">
        <Properties rows={[
          ['Frontend', 'React · separate Vite entry point'],
          ['Assets', 'Local fonts and CSS; no CDN dependency'],
          ['Persistence', 'Browser localStorage, if available'],
          ['Execution backend', 'Not connected'],
          ['Agent runtime / ACP', 'Not connected'],
          ['Remote AI', 'Not configured'],
          ['Local inference', 'Not bundled or required'],
        ]} />
      </Section>
      <Section title="Backend and target discovery">
        <div className="table-scroll"><table><thead><tr><th>Capability</th><th>Host availability</th><th>Integration here</th><th>Qualification</th></tr></thead><tbody>
          {['Network simulator', 'RTL emitter / linter', 'Formal solver', 'ASIC toolchain', 'FPGA toolchain'].map(t => <tr key={t}><th>{t}</th><td>Not inspected</td><td>Not connected</td><td>Not established</td></tr>)}
        </tbody></table></div>
      </Section>
      <Assumptions rows={[
        ['Gateway', 'Configured separately; host credentials and network policy are not managed here.'],
        ['Privacy', 'No remote AI or telemetry implementation. Local asset loading is not a claim of certified air-gap isolation, encrypted storage, host firewall enforcement, or secret scrubbing.'],
        ['Downloads', 'Browser downloads contain only the selected local illustrative state.'],
        ['Import caution', 'Do not import confidential artifacts into a prototype without an appropriate policy and implementation review.'],
        ['Not yet integrated', 'Tool discovery, runtime permissions, protected credentials, execution services, enforceable budgets.'],
      ]} />
    </div>
    <Inspector title="Integration boundary">
      <h3>Manual-first local preview</h3>
      <PageLink page="shared/projects">Export or recover local drafts</PageLink>
      <PageLink page="verify/support">Inspect capability distinctions</PageLink>
    </Inspector>
  </div>;
}
function JobsView({ state, navigate }: ViewProps) {
  const [tab, setTab] = useState('Jobs'); const findings = localChecks(state.draft);
  return <div className="view-main">
    <div className="toolbar">
      <div className="segmented">{['Jobs', 'Problems', 'Logs'].map(t => <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
      <Badge>0 live backend jobs</Badge>
    </div>
    {tab === 'Jobs' ? <>
      <Empty title="No execution backend connected">There are no live simulations, formal checks, generation workers, or cancellation controls.</Empty>
      <Section title="Actual local operations">
        <Properties rows={[
          ['Declaration check', state.checks ? `Recorded at edit ${state.checks.revision}` : 'Not run'],
          ['Prepared architecture file', state.lastExport?.name ?? 'None'],
          ['Local scope approval', state.approvedBrief ? 'Preview recorded; no jobs authorized on a backend' : 'Not recorded'],
        ]} />
      </Section>
    </> : tab === 'Problems' ? <Section title="Current declaration findings">
      <div className="table-scroll"><table><thead><tr><th>Finding</th><th>Outcome</th><th>Scope</th><th>Action</th></tr></thead><tbody>
        {findings.map(f => <tr key={f.id}><th className="mono">{f.id}</th><td><Outcome value={f.outcome} /></td><td>{f.detail}</td><td><Button onClick={() => navigate(f.page)}>Inspect</Button></td></tr>)}
      </tbody></table></div>
    </Section> : <Section title="Local activity log" actions={<Button onClick={() => downloadJson('srota-local-activity.json', { illustrative: true, events: state.events })}><Icon name="download" />Export activity</Button>}>
      <ol className="activity-list">{state.events.map((e, i) => <li key={`${i}-${e}`}>{e}</li>)}</ol>
    </Section>}
    <Assumptions rows={[
      ['Backend', 'No execution backend is connected.'],
      ['Fixtures', 'Captured candidate fixtures are historical illustrative objects, not running jobs.'],
      ['Activity log', 'Local prototype events, not backend logs.'],
    ]} />
  </div>;
}
