import { useEffect, useState, type ReactNode } from 'react';
import type { LoadedProject } from './project';
import { useProject } from './project';
import { gateway, gatewayReason, type Topology } from './gateway';
import { SystemDiagram } from './SystemDiagram';
import { Badge, Button, Dialog, Empty, Field, Notice, PageLink, Properties, Section } from './ui';
import { EndpointSeatSections } from './EndpointSeats';
import { AddressSections } from './AddressSections';
import { DomainSections } from './DomainSections';
import { PlacementSections } from './PlacementSections';
import { INITIATOR_KINDS, agentsFromRequest, designDocument, windowsFromRequest } from './agentMap';
import { decodeGroup } from './fabricAnalysis';
import { M1AddressEditor } from './AddressWindowEditor';
import { ClockDomainEditor, EngineeringHandoff, RouteEvidence } from './DesignBackend';
import type { FloorplanView, RtlReadiness } from './gateway';

function useTopology(data: LoadedProject) {
  return data.topology;
}

function TopologyMissing({ data }: { data: LoadedProject }) {
  const { reload } = useProject();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const compile = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await gateway.compileProject(data.detail.project.project_id, data.draftMeta?.revisionToken);
      reload();
    } catch (failure) {
      setError(gatewayReason(failure));
    } finally {
      setBusy(false);
    }
  };
  return <Empty title="No topology available for this revision">
    <p>{data.topologyError || 'The gateway returned no topology document.'}</p>
    {error && <Notice tone="red">{error}</Notice>}
    <div className="toolbar toolbar-start">
      <Button primary disabled={busy} onClick={compile}>{busy ? 'Compiling…' : 'Compile draft'}</Button>
      <PageLink page="workloads/workflow">Open project workflow</PageLink>
    </div>
  </Empty>;
}

function PendingDraftNotice({ data, children }: { data: LoadedProject; children: ReactNode }) {
  if (!data.draftMeta?.dirty) return null;
  return <Notice tone="amber"><strong>Saved draft differs from active revision {data.detail.active_revision_id ?? '—'}.</strong> {children}</Notice>;
}

export function LiveEndpoints({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const request = data.request;
  const agents = agentsFromRequest(request);
  const endpoints = topology?.endpoints ?? [];
  const byRouter = new Map<number, number>();
  for (const e of endpoints) byRouter.set(e.router_id, (byRouter.get(e.router_id) ?? 0) + 1);
  const declaredByKind = new Map<string, number>();
  for (const agent of agents) declaredByKind.set(agent.kind, (declaredByKind.get(agent.kind) ?? 0) + agent.count);
  const seatedByKind = new Map<string, number>();
  for (const endpoint of endpoints) seatedByKind.set(endpoint.kind, (seatedByKind.get(endpoint.kind) ?? 0) + 1);
  const seatDelta = [...new Set([...declaredByKind.keys(), ...seatedByKind.keys()])]
    .map(kind => ({ kind, declared: declaredByKind.get(kind) ?? 0, seated: seatedByKind.get(kind) ?? 0 }))
    .filter(row => row.declared !== row.seated);
  const [selectedRouter, setSelectedRouter] = useState<number | null>(null);
  const agentForEndpoint = (e: Topology['endpoints'][number]) => {
    const gi = (e as any).group_index;
    if (typeof gi === 'number' && agents[gi]) return agents[gi];
    return agents.find(a => a.kind === e.kind) ?? null;
  };
  return <div className="view-layout"><div className="view-main">

    <PendingDraftNotice data={data}>Agent groups come from the saved draft; endpoint seats come from the active revision. Compile to align these views.</PendingDraftNotice>
    <Notice tone="blue"><strong>Seats are compiled, not attached here.</strong> To change an endpoint, edit its agent group or the fabric topology and compile a revision. <PageLink page="design/agent-map">Agents</PageLink> · <PageLink page="design/fabric-topology">Fabric topology</PageLink></Notice>
    <div className="toolbar">
      <Badge>{agents.length} agent groups</Badge>
      <Badge>{endpoints.length} endpoint seats</Badge>
      <Badge>{byRouter.size} routers carry endpoints</Badge>
      <PageLink page="design/agent-map">Inspect agents</PageLink>
    </div>
    {!topology && <TopologyMissing data={data} />}
    <EndpointSeatSections model={{ agents, endpoints, topology, agentForEndpoint }} selected={selectedRouter} onSelect={setSelectedRouter} />
    {topology && <Section title="Declared agents vs materialized seats" actions={<Badge tone={seatDelta.some(row => row.seated < row.declared) ? 'red' : seatDelta.length ? 'amber' : 'green'}>{seatDelta.length ? `${seatDelta.length} kind${seatDelta.length === 1 ? ' differs' : 's differ'}` : 'all seated'}</Badge>}>
      {seatDelta.length
        ? <div className="table-scroll"><table><thead><tr><th>Agent kind</th><th>Declared</th><th>Seats</th><th>Difference</th></tr></thead><tbody>
            {seatDelta.map(row => <tr key={row.kind}><th className="mono">{row.kind}</th><td className="numeric">{row.declared}</td><td className="numeric">{row.seated}</td><td className="numeric">{row.seated - row.declared > 0 ? `+${row.seated - row.declared}` : row.seated - row.declared}</td></tr>)}
          </tbody></table></div>
        : <p className="meta-line">Every declared agent has a materialized seat in the active revision.</p>}
      <p className="meta-line">Counts are grouped by agent kind; this payload does not carry a per-group seat index. A seat is a compiled endpoint, not an attachment edit.</p>
    </Section>}

  </div></div>;
}

export function LiveMapping({ data }: { data: LoadedProject }) {
  const windows = windowsFromRequest(data.request, agentsFromRequest(data.request));
  const initiators = agentsFromRequest(data.request).filter(agent => INITIATOR_KINDS.has(agent.kind)).reduce((sum, agent) => sum + agent.count, 0);
  return <div className="view-main">
    <PendingDraftNotice data={data}>Channel structure and compiler artifacts describe the active revision; address windows come from the saved draft. Compile before treating the joined view as one design.</PendingDraftNotice>
    <Notice tone="blue"><strong>Read-only context.</strong> Mapping is derived from address windows and the compiled route. Permissions are not in the compile schema. Edit windows on <PageLink page="design/addresses">Address map</PageLink>.</Notice>
    <div className="toolbar">
      <span className="mono fabric-counts">{initiators} initiators · {windows.length} address window{windows.length === 1 ? '' : 's'}</span>
      <PageLink page="design/agent-map">Open agent address map</PageLink>
    </div>
    <RouteEvidence data={data} />
    <Section title="Mapping intent">
      <div className="mapping-intent-empty" role="group" aria-label="Initiator to target mapping is declared in the agent fabric map">
        <div className="mapping-intent-node"><strong>Initiators</strong><span>{initiators} declared</span></div>
        <div className="mapping-intent-gap"><span>address windows</span><span>not permissions</span></div>
        <div className="mapping-intent-node"><strong>Targets</strong><span>{windows.length} window{windows.length === 1 ? '' : 's'}</span></div>
      </div>
      <Properties rows={[
        ['Initiator → target', windows.length ? 'Declared as address windows' : 'Not declared in this payload'],
        ['Access permission', 'Not in the compile schema'],
        ['Observed traffic', 'No run selected in this view'],
      ]} />
      <div className="inspector-links">
        <PageLink page="design/agent-map">Edit agent address map</PageLink>
        <PageLink page="design/addresses">Inspect address map</PageLink>
      </div>
    </Section>
  </div>;
}

export function LiveAddresses({ data }: { data: LoadedProject }) {
  const agents = agentsFromRequest(data.request);
  const windows = windowsFromRequest(data.request, agents);
  const decode = decodeGroup(data.compileResult);
  const resolvedRows = decode?.rows ?? [];
  const endpointById = new Map((data.topology?.endpoints ?? []).map(e => [e.endpoint_id, e]));
  const [selectedWindow, setSelectedWindow] = useState<string | null>(windows[0]?.id ?? null);
  const activeWindow = selectedWindow && windows.some(window => window.id === selectedWindow) ? selectedWindow : windows[0]?.id ?? null;
  if (!data.request) return <div className="view-main"><Empty title="No draft request is available">The gateway did not return a draft for this project. The address map is not inferred from the active revision.</Empty></div>;
  return <div className="view-layout"><div className="view-main">
    <PendingDraftNotice data={data}>Declared windows come from the saved draft; resolved rows and endpoint joins come from the active revision. Compile to align them.</PendingDraftNotice>
    <Notice tone="blue"><strong>Edit here.</strong> Add or edit address windows below; the system-wide map, resolved decode and blocking checks follow. <PageLink page="design/agent-map">Open agent map</PageLink> · <PageLink page="design/mapping">Query route mapping</PageLink></Notice>
    <M1AddressEditor data={data} />
    <AddressSections
      windows={windows}
      agents={agents}
      selected={activeWindow}
      onSelect={setSelectedWindow}
      resolvedRows={resolvedRows as any}
      resolvedColumns
      endpointById={endpointById}
      coverageExtra={[
        ['Address transform', decode?.address_transform ?? '—'],
        ['Unmatched policy', decode?.unmatched_address_policy ?? '—'],
      ]}
    />

  </div></div>;
}

export function LiveDomains({ data }: { data: LoadedProject }) {
  const physical = designDocument(data.request).physical as Record<string, any> | undefined;
  const agents = agentsFromRequest(data.request);
  const declaredClocks = agents.filter(a => a.clock_domain);
  return <div className="view-layout"><div className="view-main">

    <div className="toolbar">
      <Badge>{agents.length} agent group{agents.length === 1 ? '' : 's'}</Badge>
      <Badge tone={declaredClocks.length ? 'blue' : 'amber'}>{declaredClocks.length} declare a clock domain</Badge>
      <PageLink page="design/system">Inspect system composition</PageLink>
    </div>
    {!declaredClocks.length && <Notice tone="amber"><strong>No clock domain is declared.</strong> Type a domain name below, then Save &amp; compile. This declares intent; CDC and timing are not analysed.</Notice>}
    <ClockDomainEditor data={data} />
    <DomainSections agents={agents} physical={physical} />

  </div></div>;
}

export function LivePlacement({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const projectId = data.detail.project.project_id;
  const revisionId = data.detail.active_revision_id;
  const [view, setView] = useState<FloorplanView | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ pitch: 2000, footprint: 800, margin: 1000, psPerMm: 120, fixedPs: 40 });
  const valid = Object.values(form).every(value => Number.isFinite(value) && value > 0);

  useEffect(() => {
    let live = true;
    setError('');
    gateway.floorplan(projectId)
      .then(next => { if (live) setView(next); })
      .catch(failure => { if (live) setError(gatewayReason(failure)); });
    return () => { live = false; };
  }, [projectId, revisionId]);

  const declare = async () => {
    if (!valid) return;
    setSaving(true); setError('');
    try {
      const next = await gateway.putFloorplan(projectId, { mode: 'grid', grid: {
        origin_x_um: 0, origin_y_um: 0,
        pitch_x_um: form.pitch, pitch_y_um: form.pitch,
        router_width_um: form.footprint, router_height_um: form.footprint,
        margin_um: form.margin,
        wire: { ps_per_mm: form.psPerMm, fixed_ps: form.fixedPs },
      } });
      setView(next); setEditing(false);
    } catch (failure) {
      setError(gatewayReason(failure));
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    setError('');
    try { setView(await gateway.deleteFloorplan(projectId)); }
    catch (failure) { setError(gatewayReason(failure)); }
  };

  const derived = view?.derived ?? null;

  return <div className="view-layout"><div className="view-main">

    <div className="toolbar">
      <Badge>{topology?.routers.length ?? 0} routers</Badge>
      <Badge tone={derived ? 'blue' : 'amber'}>{derived ? 'floorplan declared' : 'no floorplan'}</Badge>
      <PageLink page="design/fabric-topology">Inspect fabric topology</PageLink>
      <Button primary onClick={() => setEditing(true)}>{derived ? 'Redeclare floorplan' : 'Declare floorplan'}</Button>
      {view?.declared && <Button onClick={remove}>Remove</Button>}
    </div>
    <PlacementSections
      view={view}
      derived={derived}
      topology={topology}
      banner={<>
        {!derived && <Notice tone="amber"><strong>No floorplan declared.</strong> Declare a die rule to derive area and link delay.</Notice>}
        {view?.stale && <Notice tone="amber">{view.reason ? view.reason.charAt(0).toUpperCase() + view.reason.slice(1) : 'The declared floorplan is bound to another topology.'}</Notice>}
        {error && <Notice tone="red">{error}</Notice>}
      </>}
    />

  </div>
  {editing && <Dialog title="Declare floorplan" onClose={() => { if (!saving) setEditing(false); }}>
    <div className="form-row">
      <Field label="Pitch (µm)"><input type="number" min={1} value={form.pitch} onChange={e => setForm({ ...form, pitch: e.target.valueAsNumber })} /></Field>
      <Field label="Router footprint (µm)"><input type="number" min={1} value={form.footprint} onChange={e => setForm({ ...form, footprint: e.target.valueAsNumber })} /></Field>
      <Field label="Die margin (µm)"><input type="number" min={1} value={form.margin} onChange={e => setForm({ ...form, margin: e.target.valueAsNumber })} /></Field>
    </div>
    <div className="form-row">
      <Field label="Wire delay (ps/mm)"><input type="number" min={1} value={form.psPerMm} onChange={e => setForm({ ...form, psPerMm: e.target.valueAsNumber })} /></Field>
      <Field label="Fixed link delay (ps)"><input type="number" min={0} value={form.fixedPs} onChange={e => setForm({ ...form, fixedPs: e.target.valueAsNumber })} /></Field>
    </div>
    <div className="dialog-actions">
      <Button onClick={() => setEditing(false)} disabled={saving}>Cancel</Button>
      <Button primary onClick={declare} disabled={saving || !valid}>{saving ? 'Declaring…' : 'Declare'}</Button>
    </div>
  </Dialog>}
  </div>;
}

function DesignToRtlHandoff({ data }: { data: LoadedProject }) {
  const projectId = data.detail.project.project_id;
  const revisionId = data.detail.active_revision_id;
  const [readiness, setReadiness] = useState<RtlReadiness | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setReadiness(null);
    setError('');
    gateway.rtlReadiness(projectId)
      .then(value => { if (live) setReadiness(value); })
      .catch(failure => { if (live) setError(gatewayReason(failure)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [projectId, revisionId, data.draftMeta?.revisionToken]);

  const draftState = data.draftMeta?.dirty ? 'Saved draft differs from the active revision' : 'Draft matches the active revision';
  const compileState = data.compileResult?.revision_id === revisionId
    ? `Compiled · ${data.compileResult.certificate?.overall ?? 'verdict recorded'}`
    : data.compileResult ? 'Compile result is for another revision' : 'No compile result for this revision';
  const rtlState = loading ? 'Checking preview support…'
    : error ? 'Readiness unavailable'
      : readiness?.final_rtl_available ? 'Final RTL available'
        : readiness?.preview_available ? 'Preview only · final unavailable'
          : readiness ? 'Preview blocked' : 'Readiness unavailable';
  const verdictCount = data.compileResult?.stage1_verdicts?.length;
  const finalRtlReason = readiness?.final_rtl_available ? 'available' : (readiness?.final_rtl_reason || 'not available').replace(/[.]+$/, '');
  const support = readiness?.preview_support;
  const vcMismatch = !!support && support.vc_count != null && support.vc_count !== support.emitted_vcs;
  const composed = readiness?.composed_family_preflight ?? null;

  return <Section title="Design → compiler → RTL preview" actions={<Badge tone={readiness?.final_rtl_available ? 'green' : error ? 'amber' : readiness?.preview_available ? 'amber' : 'neutral'}>{rtlState}</Badge>}>
    <div className="design-handoff-track">
      <div className="design-handoff-step"><span>01 · Design</span><strong className="mono">{revisionId ?? 'No active revision'}</strong><small>{draftState}</small></div>
      <div className="design-handoff-connector" aria-hidden="true">→</div>
      <div className="design-handoff-step"><span>02 · Compiler</span><strong>{compileState}</strong><small>{verdictCount === undefined ? 'Verdict data unavailable' : `${verdictCount} module verdict${verdictCount === 1 ? '' : 's'} · active revision only`}</small></div>
      <div className="design-handoff-connector" aria-hidden="true">→</div>
      <div className="design-handoff-step"><span>03 · RTL preview</span><strong>{rtlState}</strong><small>{support?.emitted_vcs ? `${support.emitted_vcs} emitted VC${support.emitted_vcs === 1 ? '' : 's'}${support.vc_count != null ? ` · ${support.vc_count} measured` : ''}` : 'Topology-only emitter'}</small></div>
    </div>
    {error && <Notice tone="amber">Could not read preview readiness: {error}</Notice>}
    {readiness?.preview_blockers?.length ? <ul className="design-handoff-blockers">{readiness.preview_blockers.slice(0, 3).map((blocker, index) => <li key={`${index}-${blocker}`}>{blocker}</li>)}</ul> : null}
    {(composed?.blockers?.length || composed?.blocker) && <Notice tone="amber"><strong>Composed-family emission is blocked.</strong> {(composed.blockers?.length ? composed.blockers : [composed.blocker!]).join('; ')}. The final artifact needs a compatible packet width or a memory group with exactly one endpoint; change it, compile, and re-evaluate. <PageLink page="flow/optimize">Refine packet/link width</PageLink></Notice>}
    {vcMismatch && <Notice tone="amber"><strong>VC scheme mismatch.</strong> The preview emits {support?.emitted_vcs} VCs; this revision measured {support?.vc_count}. The preview is not simulation-equivalent for this design.</Notice>}
    {readiness && <p className="meta-line design-handoff-note"><strong>Final implementation RTL:</strong> {finalRtlReason}. A supported preview is not a complete implementation, selected-project RTL or qualification.</p>}
    <div className="actions">
      <PageLink page="design/agent-map">Inspect compiler and RTL control reach</PageLink>
      <PageLink page="flow/run" primary>Open RTL handoff</PageLink>
    </div>
  </Section>;
}

export function LiveSystem({ data }: { data: LoadedProject }) {
  const topology = useTopology(data);
  const agents = data.request?.agents ?? [];
  const workload = data.request?.workload;
  const noc = data.request?.noc_controls;
  const design = (data.detail.active_revision?.design ?? {}) as Record<string, any>;
  const mapping = data.compileResult?.groups?.mapping ?? null;
  const certificate = (design.locked_derived ?? null) as Record<string, unknown> | null;
  const windows = windowsFromRequest(data.request, agents);
  const clockGroups = agents.filter(agent => agent.clock_domain).length;
  const protocolGroups = agents.filter(agent => agent.protocol).length;
  const derivedRouting = design.locked_derived as { routing?: string; vc_count?: number } | null;
  return <div className="view-main">

    <Notice tone="blue"><strong>Read-only composition.</strong> Agent groups are edited in <PageLink page="design/agent-map">Agents</PageLink>; the fabric in <PageLink page="design/fabric-topology">Fabric topology</PageLink>. Collateral actions are below.</Notice>
    <div className="toolbar">
      <span className="mono muted">{[topology?.family ?? 'family not declared', `${agents.length} agent groups`,
        topology ? `${topology.counts?.routers ?? topology.routers.length} routers · ${topology.counts?.endpoints ?? topology.endpoints.length} seats` : 'no topology',
        noc?.link_width ? `${noc.link_width} b links` : 'link width not declared',
        noc?.arbitration ?? 'arbitration not declared'].join(' · ')}</span>
      <PageLink page="design/fabric-topology">Open fabric topology</PageLink>
    </div>

    <Section title="System composition">
      <SystemDiagram agents={agents} workload={workload} topology={topology} mapping={mapping} certificate={certificate} />
    </Section>
    <Section title="Deep module checks" actions={<Badge>M1–M4</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Module</th><th>Scope</th><th>Live surface</th><th>Current declaration</th></tr></thead><tbody>
        <tr><th><span className="mono">M1</span> · Address &amp; permission</th><td>Address windows, overlap and coverage, permission intent</td><td><a href="#/design/addresses">Address Map</a></td><td>{windows.length ? <Badge tone="blue">{windows.length} window{windows.length === 1 ? '' : 's'} declared</Badge> : <Badge tone="amber">No windows declared</Badge>}</td></tr>
        <tr><th><span className="mono">M2</span> · Ordering &amp; VC</th><td>Routing law, VC derivation and cycle search</td><td><a href="#/design/fabric-topology">Fabric Topology</a></td><td>{derivedRouting?.routing ? <Badge tone="blue">{derivedRouting.routing} · VC {derivedRouting.vc_count ?? '—'}</Badge> : <Badge tone="amber">No derived routing</Badge>}</td></tr>
        <tr><th><span className="mono">M3</span> · Clock, power &amp; CDC</th><td>Domain assignment, power intent, CDC insertion points</td><td><a href="#/design/domains">Clock &amp; Power Domains</a></td><td><Badge tone={clockGroups ? 'blue' : 'amber'}>{clockGroups}/{agents.length} groups declare a clock domain</Badge> <Badge tone="amber">CDC not established</Badge></td></tr>
        <tr><th><span className="mono">M4</span> · Protocol adapter</th><td>Endpoint protocol/width compatibility and adapter requirements</td><td><a href="#/design/endpoints">Hardware Endpoints</a></td><td><Badge tone={protocolGroups ? 'blue' : 'amber'}>{protocolGroups}/{agents.length} groups declare a protocol</Badge> <Badge tone="amber">Adapter not emitted</Badge></td></tr>
      </tbody></table></div>
      <p className="meta-line">These are the compiler’s four deep-module checks. They report declared or derived structure; none is a hardware qualification.</p>
    </Section>
    <DesignToRtlHandoff data={data} />
    <EngineeringHandoff data={data} />
  </div>;
}

export function FixtureBanner({ projectName }: { projectName: string | null }) {
  if (!projectName) return null;
  return <Notice tone="amber"><strong>{projectName} loaded; this surface still shows the fixture.</strong></Notice>;
}

export function LiveCatalog({ data, notify }: { data: LoadedProject; notify?: (message: string) => void }) {
  const { reload } = useProject();
  const agents = data.request?.agents ?? [];
  const endpoints = data.topology?.endpoints ?? [];
  const kinds = [...new Set(['compute_tile', 'hbm_controller', 'nic', ...agents.map(agent => agent.kind)])];
  const [kind, setKind] = useState(agents[0]?.kind ?? 'compute_tile');
  const [count, setCount] = useState(1);
  const [width, setWidth] = useState(agents[0]?.data_width ?? 256);
  const [protocol, setProtocol] = useState(agents[0]?.protocol ?? 'AXI');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ tone: 'blue' | 'red'; text: string } | null>(null);
  const add = async () => {
    const request = data.request as Record<string, any> | null;
    if (!request || busy) return;
    setBusy(true); setFeedback(null);
    try {
      const next = { ...request, agents: [...(request.agents ?? []), { kind, count, data_width: width, addr_width: 64, protocol, clock_domain: null, power_domain: null }] };
      await gateway.putDraft(data.detail.project.project_id, next, data.draftMeta?.revisionToken);
      setFeedback({ tone: 'blue', text: `Added ${count} × ${kind} to the draft. Compile the revision to materialise topology, seats, and evaluation plans.` });
      notify?.(`Added ${count} × ${kind} to the draft. Compile the revision to materialise it.`);
      reload();
    } catch (error) {
      setFeedback({ tone: 'red', text: gatewayReason(error) });
    } finally { setBusy(false); }
  };
  return <div className="view-main">

    <PendingDraftNotice data={data}>Agent groups are saved-draft intent; endpoint seats still come from the active revision. Compile to materialise new counts.</PendingDraftNotice>
    {feedback && <Notice tone={feedback.tone}>{feedback.text}</Notice>}
    <div className="toolbar">
      <Badge>{agents.length} agent group{agents.length === 1 ? '' : 's'}</Badge>
      <Badge>{agents.reduce((n, agent) => n + (agent.count ?? 0), 0)} declared agents</Badge>
      <Badge>{endpoints.length} endpoint seats</Badge>
      <PageLink page="design/endpoints">Inspect endpoint attachments</PageLink>
    </div>
    <Section title="Add an agent group to the draft">
      <div className="form-grid">
        <Field label="Kind"><select value={kind} onChange={e => setKind(e.target.value)}>{kinds.map(value => <option key={value} value={value}>{value}</option>)}</select></Field>
        <Field label="Count"><input type="number" min={1} value={Number.isNaN(count) ? '' : count} onChange={e => setCount(e.target.valueAsNumber)} /></Field>
        <Field label="Data width (bits)"><input type="number" min={1} value={Number.isNaN(width) ? '' : width} onChange={e => setWidth(e.target.valueAsNumber)} /></Field>
        <Field label="Protocol"><input value={protocol} onChange={e => setProtocol(e.target.value)} /></Field>
      </div>
      <div className="toolbar toolbar-start">
        <Button primary disabled={busy || !data.request || !Number.isInteger(count) || count < 1 || !Number.isInteger(width) || width < 1} onClick={add}>{busy ? 'Saving…' : 'Add to draft'}</Button>
      </div>
      <p className="meta-line">Adds one agent group to the saved draft. Topology, seats and evaluation plans appear only after compilation.</p>
    </Section>
    <Section title="Declared agent groups" actions={<Badge>{agents.reduce((n, agent) => n + (agent.count ?? 0), 0)} agents</Badge>}>
      {agents.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Protocol</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
        {agents.map((agent, index) => <tr key={`${agent.kind}-${index}`}><th>{agent.kind}</th><td className="numeric">{agent.count}</td><td className="numeric">{agent.data_width ?? '—'} b</td><td>{agent.protocol ?? '—'}</td><td className="mono">{agent.clock_domain ?? 'null'}</td><td className="mono">{agent.power_domain ?? 'null'}</td></tr>)}
      </tbody></table></div> : <Empty title="This draft declares no agent groups">The request carries no agent inventory, so there is nothing to attach.</Empty>}
    </Section>
  </div>;
}

export type { Topology };
