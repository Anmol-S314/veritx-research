import { useState } from 'react';
import { useLoadedProject, useLoadedRun } from './project';
import type { DeclaredAgent, DeclaredCollective, DeclaredStage, LoadedProject } from './project';
import { Badge, Empty, Inspector, Notice, PageLink, Properties, Section } from './ui';

const num = (value: number | null | undefined, unit = '') => value === null || value === undefined ? '—' : `${value.toLocaleString(undefined, { maximumFractionDigits: 3 })}${unit}`;
const bytes = (value?: number | null) => value === null || value === undefined ? '—' : value >= 2 ** 30 ? `${(value / 2 ** 30).toFixed(3)} GiB` : value >= 2 ** 20 ? `${(value / 2 ** 20).toFixed(3)} MiB` : value >= 1024 ? `${(value / 1024).toFixed(2)} KiB` : `${value} B`;
const short = (value?: string | null, keep = 20) => value ? `${value.slice(0, keep)}…` : 'Not supplied';

export function WorkloadGate({ children }: { children: (project: LoadedProject) => React.ReactNode }) {
  const project = useLoadedProject();
  if (!project) return <div className="view-main"><Empty title="No project loaded">Load a project from <a href="#/shared/projects">Projects &amp; revisions</a> to read its declared workload, agents, and compute stages from the gateway.</Empty></div>;
  return <>{children(project)}</>;
}

export function LiveWorkloadBanner({ project }: { project: LoadedProject }) {
  const name = project.detail.project.name;
  return <Notice tone="blue"><strong>Live draft · {name}</strong> ({project.detail.active_revision_id ?? 'no revision'}).</Notice>;
}

const totalAgents = (agents: DeclaredAgent[]) => agents.reduce((n, a) => n + (a.count ?? 0), 0);
const kindOf = (a: DeclaredAgent) => a.kind ?? 'unspecified';
function byKind(agents: DeclaredAgent[]) {
  const map = new Map<string, number>();
  for (const a of agents) map.set(kindOf(a), (map.get(kindOf(a)) ?? 0) + (a.count ?? 0));
  return map;
}

export function LiveWorkloadLibrary({ project }: { project: LoadedProject }) {
  const request = project.request;
  const workload = request?.workload ?? null;
  const agents = request?.agents ?? [];
  const collectives = workload?.collectives ?? [];
  const kinds = byKind(agents);
  const parallel = workload ? (workload.tp ?? 1) * (workload.dp ?? 1) * (workload.ep ?? 1) * (workload.pp ?? 1) : null;
  const tiles = kinds.get('compute_tile') ?? 0;
  const mismatch = parallel !== null && tiles > 0 && parallel !== tiles;
  return <div className="view-layout"><div className="view-main">
    <LiveWorkloadBanner project={project} />
    {!request && <Notice tone="amber"><strong>No draft request.</strong> The project has no readable draft, so no workload is displayed.</Notice>}
    <Section title="Declared workload" actions={<Badge tone={workload ? 'green' : 'amber'}>{workload ? 'declared' : 'absent'}</Badge>}>
      {workload ? <Properties rows={[[ 'Model', workload.model_name ?? 'Not declared' ], ['Model family', workload.model_family ?? 'Not declared' ], ['Serving mode', workload.serving_mode ?? 'Not declared' ], ['Parallelism (TP × DP × EP × PP)', `${workload.tp ?? 1} × ${workload.dp ?? 1} × ${workload.ep ?? 1} × ${workload.pp ?? 1} = ${parallel}` ], ['Workload source reference', workload.workload_source_ref ? <span className="mono">{workload.workload_source_ref}</span> : 'None; declared inline' ], ['Collectives', String(collectives.length) ]] } /> : <Empty title="This draft declares no workload block">The request carries no <code>workload</code> object.</Empty>}
    </Section>
    {mismatch && <Notice tone="amber"><strong>Parallelism {parallel} ≠ {tiles} declared tiles.</strong> The draft does not explain it.</Notice>}
    <Section title="Collectives declared for this workload" actions={<Badge>{collectives.length}</Badge>}>
      {collectives.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Dimension</th><th>Payload</th><th>Traffic class</th><th>Source rank</th></tr></thead><tbody>
        {collectives.map((c, i) => <tr key={`${c.kind}-${c.dimension}-${i}`}><th>{c.kind ?? '—'}</th><td>{c.dimension ?? '—'}</td><td className="numeric">{bytes(c.payload_bytes)}</td><td>{c.traffic_class ? <Badge>{c.traffic_class}</Badge> : 'Not declared'}</td><td>{c.source_rank === null || c.source_rank === undefined ? 'All ranks' : c.source_rank}</td></tr>)}
      </tbody></table></div> : <Empty title="No collective declared">The workload has no collective list; any all-reduce or all-to-all traffic is undeclared.</Empty>}
      <p>Payloads are shown per collective as declared. This page does not multiply them by rank count, because the request does not state whether <code>payload_bytes</code> is per rank or per collective.</p>
    </Section>
    <Section title="Agent inventory" actions={<Badge>{totalAgents(agents)} agents · {kinds.size} kinds</Badge>}>
      {agents.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Address width</th><th>Protocol</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
        {agents.map((a, i) => <tr key={`${kindOf(a)}-${i}`}><th>{kindOf(a)}</th><td className="numeric">{num(a.count)}</td><td className="numeric">{a.data_width ? `${a.data_width} bit` : '—'}</td><td className="numeric">{a.addr_width ? `${a.addr_width} bit` : '—'}</td><td>{a.protocol ?? '—'}</td><td>{a.clock_domain ?? 'null (not declared)'}</td><td>{a.power_domain ?? 'null (not declared)'}</td></tr>)}
      </tbody></table></div> : <Empty title="No agents declared">The request carries no agent inventory.</Empty>}
    </Section>
  </div><Inspector title="Declaration provenance">
    <Properties rows={[[ 'Project', project.detail.project.name ], ['Project id', project.detail.project.project_id ], ['Revision', project.detail.active_revision_id ?? 'none' ], ['Design hash', <span className="mono">{short(project.detail.active_revision?.design_hash)}</span> ], ['Schema version', String(request?.schema_version ?? 'not declared') ], ['Compiler semantics', String(request?.compiler_semantics_version ?? 'not declared') ], ['Topology kind', request?.topology?.kind ?? 'not declared' ], ['Run verdicts', (project.detail.runs ?? []).length ? 'Available under Analysis' : 'No run recorded' ]]} />
    <PageLink page="workloads/editor">Inspect compute stages</PageLink>
    <PageLink page="analysis/summary">Read run verdicts</PageLink>
  </Inspector></div>;
}

export function LiveWorkloadEditor({ project }: { project: LoadedProject }) {
  const stages: DeclaredStage[] = project.request?.compute?.stages ?? [];
  const [selected, setSelected] = useState(stages[0]?.stage_id ?? '');
  const active = stages.find(s => s.stage_id === selected) ?? null;
  const owners = new Map<number, { stages: number; duration: number }>();
  for (const s of stages) { const o = owners.get(s.owner) ?? { stages: 0, duration: 0 }; o.stages += 1; o.duration += s.duration_ns ?? 0; owners.set(s.owner, o); }
  const totalDuration = stages.reduce((n, s) => n + (s.duration_ns ?? 0), 0);
  const tiles = byKind(project.request?.agents ?? []).get('compute_tile') ?? 0;
  return <div className="view-layout"><div className="view-main">
    <LiveWorkloadBanner project={project} />
    {stages.length ? <>
      <Notice tone="blue"><strong>{stages.length} stages · {owners.size} owners</strong> · no dependency edges. Sum is not a critical path.</Notice>
      <div className="toolbar"><Badge>{stages.length} stages</Badge><Badge>{owners.size} owners</Badge><Badge>compute source: {project.request?.compute?.source ?? 'not declared'}</Badge><Badge tone="amber">Not a schedule</Badge></div>
      <div className="report-strip"><span>Sum of declared durations <strong>{(totalDuration / 1e6).toFixed(3)} ms</strong></span><span>Compute tiles declared <strong>{tiles}</strong></span><span>Dependency edges <strong>{project.request?.dependencies?.length ?? 0}</strong></span></div>
      <Section title="Declared stages" actions={<Badge>showing {Math.min(stages.length, 48)} of {stages.length}</Badge>}>
        <div className="table-scroll"><table><thead><tr><th>Stage</th><th>Owner</th><th>Duration</th><th>Input</th><th>Output</th><th>Weight</th><th>Locality</th></tr></thead><tbody>
          {stages.slice(0, 48).map(s => <tr key={s.stage_id} className={s.stage_id === active?.stage_id ? 'selected' : ''}><th><button className="text-button mono" onClick={() => setSelected(s.stage_id)}>{s.stage_id}</button></th><td className="numeric">{s.owner}</td><td className="numeric">{num(s.duration_ns, ' ns')}</td><td className="numeric">{bytes(s.input_bytes)}</td><td className="numeric">{bytes(s.output_bytes)}</td><td className="numeric">{bytes(s.weight_bytes)}</td><td><small>{s.input_loc ?? '—'} / {s.output_loc ?? '—'} / {s.weight_loc ?? '—'}</small></td></tr>)}
        </tbody></table></div>
      </Section>
      <Section title="Owner distribution">
        <div className="table-scroll"><table><thead><tr><th>Owner index</th><th>Stages</th><th>Summed duration</th><th>Share of total</th></tr></thead><tbody>
          {[...owners.entries()].sort((a, b) => a[0] - b[0]).map(([owner, o]) => <tr key={owner}><th className="mono">owner {owner}</th><td className="numeric">{o.stages}</td><td className="numeric">{(o.duration / 1e6).toFixed(3)} ms</td><td className="numeric">{totalDuration ? `${(100 * o.duration / totalDuration).toFixed(2)} %` : '—'}</td></tr>)}
        </tbody></table></div>
        {tiles > owners.size && <p>Owner indices {owners.size <= 1 ? 'are' : 'cover'} {owners.size} of {tiles} declared compute tiles. Owners without stages are not assigned work by this draft.</p>}
      </Section>
    </> : <><Empty title="This draft declares no compute stages">The request has {project.request?.compute ? 'a compute object without stages' : 'no compute block'}. Workload traffic can still be evaluated by the network backends; execution timing cannot be derived from it.</Empty>
      <Section title="What the network evaluation does not cover"><Properties rows={[[ 'Declared stages', 'None' ], ['Declared dependencies', String(project.request?.dependencies?.length ?? 0) ], ['Execution timing', 'Not derivable without stages' ], ['Roofline / arithmetic intensity', 'Not computed' ]]} /></Section></>}
  </div><Inspector title="Selected stage">
    {active ? <><h3 className="mono">{active.stage_id}</h3><Properties rows={[[ 'Owner index', String(active.owner) ], ['Duration', num(active.duration_ns, ' ns') ], ['Input', `${bytes(active.input_bytes)} · ${active.input_loc ?? '—'}` ], ['Output', `${bytes(active.output_bytes)} · ${active.output_loc ?? '—'}` ], ['Weights', `${bytes(active.weight_bytes)} · ${active.weight_loc ?? '—'}` ], ['Dependencies', 'Not declared per stage' ], ['Backend execution', 'Not produced; this is a declaration' ]]} /></> : <p>Select a stage.</p>}
    <PageLink page="workloads/requirements">Declared requirements</PageLink>
  </Inspector></div>;
}

export function LiveRequirements({ project }: { project: LoadedProject }) {
  const requirements = project.request?.requirements ?? [];
  const run = useLoadedRun();
  const verdicts = run?.detail.requirements?.entries ?? [];
  const verdictFor = (req: { traffic_class?: string; qos_class?: string }) => verdicts.find(v => v.traffic_class === req.traffic_class && v.qos_class === req.qos_class) ?? null;
  return <div className="view-layout"><div className="view-main">
    <LiveWorkloadBanner project={project} />
    {run && <Notice tone={run.detail.revision_id === project.detail.active_revision_id ? 'blue' : 'amber'}><strong>Verdicts from run {run.detail.run_id.slice(0, 13)}…</strong> · revision {run.detail.revision_id}{run.detail.revision_id === project.detail.active_revision_id ? '' : ' (not the active revision)'}.</Notice>}
    <Section title="Requirements declared in the draft" actions={<Badge>{requirements.length}</Badge>}>
      {requirements.length ? <div className="table-scroll"><table><thead><tr><th>Traffic class</th><th>QoS class</th><th>Binding</th><th>Latency ceiling</th><th>Bandwidth floor</th><th>Verdict</th></tr></thead><tbody>
        {requirements.map((req, i) => { const v = verdictFor(req); return <tr key={`${req.traffic_class}-${req.qos_class}-${i}`}><th>{req.traffic_class ?? '—'}</th><td>{req.qos_class ?? '—'}</td><td>{req.binding ? 'Binding' : 'Advisory'}</td><td className="numeric">{num(req.latency_ceiling_cycles, ' cycles')}</td><td className="numeric">{num(req.bandwidth_floor_gbps, ' GB/s')}</td><td>{v ? <Badge tone={/SATISF|PASS/i.test(String(v.verdict)) ? 'green' : 'red'}>{v.verdict}</Badge> : <Badge tone="amber">No verdict</Badge>}</td></tr>; })}
      </tbody></table></div> : <Empty title="No requirements declared">The draft carries no requirement entries, so no verdict can be produced.</Empty>}
    </Section>
    <Section title="Requirement verdict detail">
      {verdicts.length ? <div className="table-scroll"><table><thead><tr><th>REQ</th><th>Measured</th><th>Required</th><th>Authority</th><th>Reason</th></tr></thead><tbody>
        {verdicts.map((v, i) => <tr key={i}><th className="mono">REQ-{v.requirement_index ?? i}</th><td className="numeric">{num(v.measured)}</td><td className="numeric">{v.required === null || v.required === undefined ? '—' : String(v.required)}</td><td><small>{v.metric_authority ?? '—'}</small></td><td><small>{v.reason ?? '—'}</small></td></tr>)}
      </tbody></table></div> : <Empty title="No measured verdicts in the loaded run">Open Analysis after selecting a run that carries an evaluation to read verdicts. This page never estimates one.</Empty>}
    </Section>
  </div><Inspector title="Requirement scope">
    <Properties rows={[[ 'Declared classes', [...new Set(requirements.map(r => r.traffic_class).filter(Boolean))].join(', ') || 'none' ], ['Verdict source', run ? `run ${run.detail.run_id.slice(0, 13)}…` : 'no run loaded' ], ['Bandwidth floors', requirements.some(r => r.bandwidth_floor_gbps !== null && r.bandwidth_floor_gbps !== undefined) ? 'Declared' : 'None declared' ], ['Transaction latency', 'Not measured by network evidence' ], ['Writes to gateway', 'None' ]]} />
    <PageLink page="verify/evidence">Inspect the evidence bundle</PageLink>
  </Inspector></div>;
}

export function LiveBindings({ project }: { project: LoadedProject }) {
  const agents = project.request?.agents ?? [];
  const kinds = byKind(agents);
  const endpoints = project.topology?.endpoints ?? [];
  const seats = new Map<string, number>();
  for (const e of endpoints) seats.set(e.kind ?? 'unspecified', (seats.get(e.kind ?? 'unspecified') ?? 0) + 1);
  const allKinds = [...new Set([...kinds.keys(), ...seats.keys()])].sort();
  return <div className="view-layout"><div className="view-main">
    <LiveWorkloadBanner project={project} />
    <Notice tone="amber"><strong>No binding table in this draft.</strong> Agent kinds vs topology seats only; seat order is not a rank.</Notice>
    <Section title="Declared agents versus topology endpoint seats">
      <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Agents declared</th><th>Endpoint seats</th><th>Difference</th><th>Reading</th></tr></thead><tbody>
        {allKinds.map(kind => { const a = kinds.get(kind) ?? 0; const s = seats.get(kind) ?? 0; return <tr key={kind}><th>{kind}</th><td className="numeric">{a}</td><td className="numeric">{s}</td><td className="numeric">{a === s ? '0' : `${a - s > 0 ? '+' : ''}${a - s}`}</td><td>{a === s ? 'Matches' : a > s ? 'More agents than attached seats' : 'More seats than declared agents'}</td></tr>; })}
      </tbody></table></div>
      {allKinds.length === 0 && <Empty title="Nothing declared">Neither the request nor the topology declares agents or endpoints.</Empty>}
    </Section>
    <Section title="Endpoint seats from the revision topology" actions={<Badge>{endpoints.length} seats</Badge>}>
      {endpoints.length ? <div className="table-scroll"><table><thead><tr><th>Endpoint</th><th>Kind</th><th>Router</th><th>Port</th></tr></thead><tbody>
        {endpoints.slice(0, 64).map((e, i) => <tr key={`${e.endpoint_id}-${i}`}><th className="mono">EP-{e.endpoint_id}</th><td>{e.kind ?? '—'}</td><td className="mono">R{e.router_id}</td><td className="numeric">{e.port_id}</td></tr>)}
        </tbody></table></div> : <Empty title="No endpoint seats">This revision's topology carries no endpoints; agent declaration cannot be attached.</Empty>}
      {endpoints.length > 64 && <p>Showing 64 of {endpoints.length} seats.</p>}
      <p className="muted">Seat order is the topology document's order. It is not a rank, node, or participant assignment.</p>
    </Section>
  </div><Inspector title="Binding scope">
    <Properties rows={[[ 'Binding table in draft', 'Absent' ], ['Attachment source', 'Revision topology endpoints' ], ['Specific seat per agent index', 'Not declared' ], ['Address ranges', (project.request?.address_map?.ranges ?? []).length ? 'Declared' : 'None declared' ], ['Permission / isolation', 'Not modelled' ]]} />
    <PageLink page="design/endpoints">Inspect endpoint attachments</PageLink>
  </Inspector></div>;
}

export function LiveAssumptions({ project }: { project: LoadedProject }) {
  const request = project.request;
  const physical = request?.physical;
  const noc = request?.noc_controls;
  const fidelity = useLoadedRun()?.detail.evaluation?.fidelity_warning ?? null;
  return <div className="view-layout"><div className="view-main">
    <LiveWorkloadBanner project={project} />
    <Section title="Physical parameters">
      <Properties rows={[[ 'Clock frequency', physical?.clock_freq_mhz ? `${physical.clock_freq_mhz} MHz` : 'Not declared' ], ['Data width', physical?.data_width ? `${physical.data_width} bit` : 'Not declared' ], ['Power domains', physical?.num_power_domains ?? 'Not declared' ], ['Process node', physical?.process_node_nm ? `${physical.process_node_nm} nm` : 'Not declared' ], ['Per-agent clock assignment', 'null for every agent' ], ['Voltage / corners', 'Not declared' ], ['Achieved timing', 'Not evaluated' ]]} />
    </Section>
    <Section title="NoC controls">
      <Properties rows={[[ 'Link width', noc?.link_width ? `${noc.link_width} bit` : 'Not declared' ], ['Arbitration', noc?.arbitration ?? 'Not declared (null)' ], ['Obfuscation level', noc?.obfuscation_level ?? 'Not declared' ], ['RCU enabled', noc?.rcu_enabled === null || noc?.rcu_enabled === undefined ? 'Not declared' : noc.rcu_enabled ? 'Yes' : 'No' ], ['Output formats', (noc?.output_formats ?? []).join(', ') || 'Not declared' ]] } />
    </Section>
    <Section title="Model fidelity of the loaded evaluation">
      {fidelity ? <><Notice tone="amber">{fidelity}</Notice><p>This string is the backend's own fidelity statement for the selected run. It is not a certification, and it does not transfer to other revisions.</p></> : <Empty title="No fidelity statement loaded">Select a run on Analysis to read the backend's fidelity warning. One is never written here.</Empty>}
    </Section>
    <Section title="Assumption editing">
      <p>These values are read-only in this session. Editing a real draft is a write operation the gateway would have to accept; this prototype performs no writes.</p>
    </Section>
  </div><Inspector title="Assumption scope">
    <Properties rows={[[ 'Schema version', String(request?.schema_version ?? '—') ], ['Compiler semantics version', String(request?.compiler_semantics_version ?? '—') ], ['Topology declaration', request?.topology ? `${request.topology.kind ?? 'kind not declared'}${request.topology.side_length ? ` · side ${request.topology.side_length}` : ''}${request.topology.concentration ? ` · concentration ${request.topology.concentration}` : ''}` : 'Not declared' ], ['Link width source', 'noc_controls.link_width' ], ['Writes', 'None' ]]} />
    <PageLink page="workloads/lowering">Validation and lowering preview</PageLink>
  </Inspector></div>;
}

export function LiveLowering({ project }: { project: LoadedProject }) {
  const request = project.request;
  const collectives: DeclaredCollective[] = request?.workload?.collectives ?? [];
  const classes = new Map<string, { count: number; payload: number }>();
  for (const c of collectives) { const key = c.traffic_class ?? 'unclassified'; const entry = classes.get(key) ?? { count: 0, payload: 0 }; entry.count += 1; entry.payload += c.payload_bytes ?? 0; classes.set(key, entry); }
  const requirementClasses = new Set((request?.requirements ?? []).map(r => r.traffic_class).filter(Boolean));
  const collectiveClasses = new Set(collectives.map(c => c.traffic_class).filter(Boolean));
  const unmatched = [...collectiveClasses].filter(c => !requirementClasses.has(c));
  const unproduced = [...requirementClasses].filter(c => !collectiveClasses.has(c));
  const stages = request?.compute?.stages ?? [];
  return <div className="view-layout"><div className="view-main">
    <LiveWorkloadBanner project={project} />
    <Notice tone="amber"><strong>No lowering adapter.</strong> Coherence checks only; nothing executable is produced.</Notice>
    <Section title="Declared traffic classes" actions={<Badge>{classes.size} classes</Badge>}>
      {classes.size ? <div className="table-scroll"><table><thead><tr><th>Traffic class</th><th>Collectives</th><th>Summed payload</th><th>Requirement declared</th><th>Status</th></tr></thead><tbody>
        {[...classes.entries()].map(([name, entry]) => <tr key={name}><th>{name}</th><td className="numeric">{entry.count}</td><td className="numeric">{bytes(entry.payload)}</td><td>{requirementClasses.has(name) ? 'Yes' : 'No'}</td><td>{requirementClasses.has(name) ? <Badge tone="green">Evaluable</Badge> : <Badge tone="amber">No requirement; no verdict expected</Badge>}</td></tr>)}
      </tbody></table></div> : <Empty title="No collective traffic">The draft declares no collectives, so no traffic class can be lowered.</Empty>}
    </Section>
    <Section title="Declaration coherence">
      <div className="table-scroll"><table><thead><tr><th>Check</th><th>Observation</th><th>Reading</th></tr></thead><tbody>
        <tr><th>Collective classes without a requirement</th><td className="mono">{unmatched.join(', ') || 'none'}</td><td>{unmatched.length ? <Badge tone="amber">Traffic declared but not measured against any ceiling</Badge> : <Badge tone="green">Every declared class has a requirement</Badge>}</td></tr>
        <tr><th>Requirements without declared traffic</th><td className="mono">{unproduced.join(', ') || 'none'}</td><td>{unproduced.length ? <Badge tone="amber">Requirement has no matching traffic</Badge> : <Badge tone="green">Every requirement matches traffic</Badge>}</td></tr>
        <tr><th>Compute stages</th><td>{stages.length ? `${stages.length} declared` : 'none'}</td><td>{stages.length ? 'Execution timing is declarable' : <Badge tone="amber">Network evaluation only; no execution timing</Badge>}</td></tr>
        <tr><th>Address ranges</th><td>{String((request?.address_map?.ranges ?? []).length)}</td><td>{(request?.address_map?.ranges ?? []).length ? 'Decode map declared' : <Badge tone="amber">Memory access has no decode map</Badge>}</td></tr>
        <tr><th>Agents vs parallelism</th><td>{`${byKind(request?.agents ?? []).get('compute_tile') ?? 0} tiles declared`}</td><td>{(() => { const w = request?.workload; const p = w ? (w.tp ?? 1) * (w.dp ?? 1) * (w.ep ?? 1) * (w.pp ?? 1) : null; const t = byKind(request?.agents ?? []).get('compute_tile') ?? 0; return p !== null && t > 0 && p !== t ? <Badge tone="amber">Parallelism product {p} ≠ {t} tiles</Badge> : <Badge tone="green">Consistent</Badge>; })()}</td></tr>
      </tbody></table></div>
    </Section>
    <Section title="What a lowering adapter would have to receive">
      <Properties rows={[[ 'Workload', request?.workload ? `${request.workload.model_name ?? 'unnamed'} · TP${request.workload.tp ?? 1}/DP${request.workload.dp ?? 1}/EP${request.workload.ep ?? 1}/PP${request.workload.pp ?? 1}` : 'none' ], ['Collectives', String(collectives.length) ], ['Stages', String(stages.length) ], ['Requirements', String((request?.requirements ?? []).length) ], ['Topology', request?.topology?.kind ?? 'not declared' ], ['Agent inventory', `${totalAgents(request?.agents ?? [])} agents` ], ['Produced here', 'Nothing; the table above is the input contract' ], ['Backend acceptance', 'Unknown until an adapter is wired' ]]} />
    </Section>
  </div><Inspector title="Lowering boundary">
    <Properties rows={[[ 'Executable output', 'None' ], ['Backend adapter', 'Not connected' ], ['Modifies draft', 'No' ], ['Estimated build cost', 'Not provided' ]] } />
    <PageLink page="analysis/summary">Compare with a produced evaluation</PageLink>
  </Inspector></div>;
}
