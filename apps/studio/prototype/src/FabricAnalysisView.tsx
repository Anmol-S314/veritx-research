import { useMemo, useState } from 'react';
import type { LoadedProject } from './project';
import { agentsFromRequest, designDocument, exactMatches, formatBytes, formatHex, windowsFromRequest } from './agentMap';
import {
  buildFabricAnalysis, decodeGroup, portBudgetReadings,
  type AnalysisCheck, type CheckStatus, type FabricAnalysis,
} from './fabricAnalysis';
import { Assumptions, Badge, Empty, Inspector, Notice, PageLink, Properties, Section } from './ui';

const tone = (status: CheckStatus): 'green' | 'amber' | 'red' | 'neutral' =>
  status === 'PASS' ? 'green' : status === 'WARN' ? 'amber' : status === 'FAIL' ? 'red' : 'neutral';

const groupTitle: Record<AnalysisCheck['group'], string> = {
  address: 'Address map',
  agents: 'Agents & seats',
  routing: 'Routing & deadlock',
  topology: 'Topology',
  certificate: 'Compiler certificate',
  rtl: 'RTL reach',
};

function CheckTable({ checks, onSelect, selected }: { checks: AnalysisCheck[]; onSelect: (id: string) => void; selected: string | null }) {
  return <div className="table-scroll"><table><thead><tr><th>Check</th><th>Status</th><th>Finding</th><th>Citation</th></tr></thead><tbody>
    {checks.map(check => <tr key={check.id} className={selected === check.id ? 'selected' : ''}>
      <th><button className="text-button" onClick={() => onSelect(check.id)}>{check.title}</button></th>
      <td><Badge tone={tone(check.status)}>{check.status}</Badge></td>
      <td>{check.detail}</td>
      <td className="mono"><small>{check.citation}</small></td>
    </tr>)}
  </tbody></table></div>;
}

function CdgGraph({ analysis }: { analysis: FabricAnalysis }) {
  const { cdg } = analysis;
  if (!cdg.nodes.length) return <p className="meta-line">{cdg.model}</p>;
  const position = (node: string): { x: number; y: number } | null => {
    const match = /^(row|col)\[(\d+)\]/.exec(node);
    if (!match) return null;
    const partitioned = node.includes('@vc');
    const partition = node.includes('@vc1') ? 1 : 0;
    const x = partitioned
      ? (match[1] === 'row' ? (partition ? 250 : 70) : (partition ? 340 : 170))
      : (match[1] === 'row' ? 78 : 302);
    return { x, y: 38 + Number(match[2]) * 44 };
  };
  const partitioned = cdg.nodes.some(node => node.includes('@vc'));
  const maxIndex = Math.max(0, ...cdg.nodes.map(node => Number(/\[(\d+)\]/.exec(node)?.[1] ?? 0)));
  const viewHeight = Math.max(230, 70 + (maxIndex + 1) * 44);
  const edges = cdg.edges.map(([from, to]) => ({ from, to, a: position(from), b: position(to) })).filter(edge => edge.a && edge.b);
  const cycleEdges = new Set<string>();
  if (cdg.cycle && cdg.cycle.length > 1) {
    for (let index = 0; index < cdg.cycle.length - 1; index += 1) cycleEdges.add(`${cdg.cycle[index]}->${cdg.cycle[index + 1]}`);
  }
  return <div className="cdg-wrap">
    <svg className="cdg-graph" viewBox={`0 0 380 ${viewHeight}`} role="img" aria-label="Abstract row/column channel dependency graph">
      <defs><marker id="cdg-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6" fill="currentColor" /></marker></defs>
      {[...edges.filter(edge => cycleEdges.has(`${edge.from}->${edge.to}`)), ...edges.filter(edge => !cycleEdges.has(`${edge.from}->${edge.to}`))].slice(0, 48).map((edge, index) => {
        const key = `${edge.from}->${edge.to}`;
        const rowToCol = edge.from.startsWith('row');
        return <line key={index} x1={edge.a!.x} y1={edge.a!.y} x2={edge.b!.x} y2={edge.b!.y} className={`cdg-edge ${rowToCol ? 'row-to-col' : 'col-to-row'} ${cycleEdges.has(key) ? 'cycle' : ''}`} markerEnd="url(#cdg-arrow)" />;
      })}
      {cdg.nodes.map(node => {
        const point = position(node);
        if (!point) return null;
        const match = /^(row|col)\[(\d+)\]/.exec(node);
        return <g key={node} transform={`translate(${point.x},${point.y})`}>
          <rect x="-34" y="-13" width="68" height="26" rx="3" className={`cdg-node ${match?.[1] === 'row' ? 'row' : 'col'}`} />
          <text textAnchor="middle" dy="4">{node.replace(/@vc[01]/, '')}</text>
        </g>;
      })}
      {partitioned ? <>
        <text x="70" y="16" textAnchor="middle" className="cdg-label">row · vc0</text>
        <text x="170" y="16" textAnchor="middle" className="cdg-label">column · vc0</text>
        <text x="250" y="16" textAnchor="middle" className="cdg-label">row · vc1</text>
        <text x="340" y="16" textAnchor="middle" className="cdg-label">column · vc1</text>
      </> : <>
        <text x="78" y="16" textAnchor="middle" className="cdg-label">row channels</text>
        <text x="302" y="16" textAnchor="middle" className="cdg-label">column channels</text>
      </>}
    </svg>
    <div className="cdg-legend">
      <span><i className="legend-dot blue" />row → column (row-first)</span>
      <span><i className="legend-dot amber" />column → row (column-first)</span>
      {cdg.cycle && <span><i className="legend-dot red" />cycle witness</span>}
    </div>
    <p className="meta-line">{cdg.edges.length > 48 ? `Showing 48 of ${cdg.edges.length} edges. ` : ''}{cdg.model} {cdg.cycle ? <>Witness: <code>{cdg.cycle.join(' → ')}</code>.</> : 'No cycle in this abstraction.'}</p>
  </div>;
}

export function FabricAnalysisView({ data }: { data: LoadedProject }) {
  const analysis = useMemo(() => buildFabricAnalysis(data.request, data.topology, data.compileResult), [data.request, data.topology, data.compileResult]);
  const [selected, setSelected] = useState<string | null>(analysis.checks[0]?.id ?? null);
  const [filter, setFilter] = useState<'all' | CheckStatus>('all');
  const selectedCheck = analysis.checks.find(check => check.id === selected) ?? null;
  const decode = decodeGroup(data.compileResult);
  const windows = windowsFromRequest(data.request, agentsFromRequest(data.request));
  const declaredAgents = agentsFromRequest(data.request);
  const readings = portBudgetReadings(data.request);
  const claims = ((data.compileResult?.certificate?.claims ?? []) as { obligation?: string; claim?: string; status?: string; certificate_status?: string; method?: string; meaning?: string; scope?: string }[]);
  const shown = filter === 'all' ? analysis.checks : analysis.checks.filter(check => check.status === filter);
  const draftDiffers = !!data.draftMeta?.dirty;
  const overall = draftDiffers ? 'WARN' : analysis.counts.FAIL ? 'FAIL' : analysis.counts.WARN ? 'WARN' : 'PASS';
  const resources = (data.compileResult?.groups?.resources ?? {}) as Record<string, any>;
  const deadlock = (resources.deadlock ?? {}) as Record<string, any>;
  const evidence = (deadlock.evidence ?? {}) as Record<string, any>;
  const design = designDocument(data.request);
  const srota = (design.topology as Record<string, any> | undefined)?.kind === 'srota';
  const hasTopologyIntent = !!design.topology;
  const witness = (deadlock.witness ?? {}) as Record<string, any>;
  const proofMethod = evidence.proof_method ?? witness.route_realization_scheme ?? deadlock.method;
  const nodes = evidence.nodes ?? witness.node_count;
  const edges = evidence.edges ?? witness.edge_count;
  const cycleFound = Array.isArray(evidence.cycle) ? evidence.cycle.length > 0 : witness.acyclic === false;
  const routingClass = evidence.routing_class ?? (Array.isArray(witness.cdg_route_classes) ? witness.cdg_route_classes.join(', ') : undefined);

  if (!data.request) return <div className="view-main"><Empty title="No draft request is available">
    The gateway did not return a draft for this project. Address, routing and RTL checks need the saved draft; the active revision's topology is not substituted for it.
  </Empty></div>;

  return <div className="view-layout"><div className="view-main">
    <div className="toolbar">
      <div className="actions">
        <Badge tone={tone(overall)}>Static verdict · {overall}</Badge>
        <Badge>{analysis.checks.length} checks</Badge>
        <Badge>{data.detail.active_revision_id ?? 'no revision'}</Badge>
      </div>
      <div className="segmented" role="group" aria-label="Filter checks">
        {(['all', 'PASS', 'WARN', 'FAIL', 'N/A'] as const).map(value => <button key={value} type="button" className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{value === 'all' ? 'All' : value}</button>)}
      </div>
    </div>
    <div className="stat-strip">
      <div className="stat"><span>Pass</span><strong>{analysis.counts.PASS}</strong><small>declared controls that satisfy the static rule</small></div>
      <div className="stat"><span>Warnings</span><strong>{analysis.counts.WARN}</strong><small>open spec items or unsupported controls</small></div>
      <div className="stat"><span>Failures</span><strong>{analysis.counts.FAIL}</strong><small>would be refused or violates a rule</small></div>
      <div className="stat"><span>Not applicable</span><strong>{analysis.counts['N/A']}</strong><small>rule does not apply to this design</small></div>
    </div>
    <p className="meta-line">Static analysis of the saved draft and the active revision's compiled certificate. It does not replace the compiler's own re-derivation, a simulation, or hardware qualification.</p>
    {data.topologyError && <Notice tone="amber">Topology unavailable: {data.topologyError}</Notice>}
    {data.compileResultError && <Notice tone="amber">Compile result unavailable: {data.compileResultError}</Notice>}
    {draftDiffers && <Notice tone="amber"><strong>The saved draft differs from the active revision.</strong> Address checks describe the draft; certificate, deadlock and resolved decode describe {data.detail.active_revision_id ?? 'the active revision'}. Recompile to align them before treating the verdict as one claim.</Notice>}
    {!hasTopologyIntent && <Notice tone="amber">This draft has no topology intent block. The compiled revision is the only fabric authority; static Srota shape, port-budget and island checks are unavailable. Recompile the typed topology intent to analyse them.</Notice>}

    <Section title="Address map" actions={<><Badge tone={analysis.issues.some(issue => issue.severity === 'error') ? 'red' : 'green'}>{analysis.issues.filter(issue => issue.severity === 'error').length} blocking</Badge><PageLink page="design/agent-map">Edit agent map</PageLink></>}>
      <div className="stat-strip">
        <div className="stat"><span>Declared</span><strong>{windows.length} window(s)</strong><small>{formatBytes(analysis.coverage.declaredBytes)}</small></div>
        <div className="stat"><span>Mapped union</span><strong>{formatBytes(analysis.coverage.mappedBytes)}</strong><small>{formatBytes(analysis.coverage.overlapBytes)} overlapping</small></div>
        <div className="stat"><span>Resolved decode</span><strong>{decode?.available ? `${decode.rows?.length ?? 0} row(s)` : 'not compiled'}</strong><small>{decode?.address_transform ?? '—'} · {decode?.unmatched_address_policy ?? '—'}</small></div>
        <div className="stat"><span>Target groups</span><strong>{analysis.targets.length}</strong><small>{analysis.targets.reduce((sum, target) => sum + target.missingInstances.length, 0)} unaddressed instance(s)</small></div>
      </div>
      {windows.length ? <div className="table-scroll"><table><thead><tr><th>Name</th><th>Base</th><th>Size</th><th>Target</th><th>Selection</th><th>Resolved endpoint</th></tr></thead><tbody>
        {windows.map(window => {
          const resolved = decode?.rows?.find(row => exactMatches(row.base, window.base) && exactMatches(row.size, window.size));
          return <tr key={window.id}><th className="mono">{window.name || 'unnamed'}</th><td className="mono">{formatHex(window.base)}</td><td>{formatBytes(window.size)}</td><td>{window.targetAgentIdx}</td><td>{window.selectionPolicy ?? 'group'}</td><td>{resolved ? `${resolved.target_agent_kind ?? 'target'} · endpoint ${resolved.target_endpoint_id ?? '—'}` : 'not in active revision'}</td></tr>;
        })}
      </tbody></table></div> : <p className="meta-line">No window is declared. An empty address map resolves to an empty decode table, not an error.</p>}
      {analysis.issues.length > 0 && <div className="table-scroll"><table><thead><tr><th>Window</th><th>Severity</th><th>Code</th><th>Detail</th></tr></thead><tbody>
        {analysis.issues.map((issue, index) => <tr key={`${issue.code}-${index}`}><th>{issue.window}</th><td><Badge tone={issue.severity === 'error' ? 'red' : 'amber'}>{issue.severity}</Badge></td><td className="mono">{issue.code}</td><td>{issue.detail}</td></tr>)}
      </tbody></table></div>}
      <CheckTable checks={analysis.checks.filter(check => check.group === 'address')} onSelect={setSelected} selected={selected} />
      <Assumptions rows={[
        ['Source', 'request.address_map.ranges for the declared table; compileResult.groups.address_decode for the resolved table.'],
        ['Overlap', 'Declared bytes minus the merged union. The compiler refuses an overlap; this page shows it before save.'],
        ['Not claimed', 'A mapped range is not a permission, a firewall rule, a route or a transaction completion.'],
      ]} />
    </Section>

    <Section title="Agents & seats" actions={<Badge>{declaredAgents.length} group(s)</Badge>}>
      {declaredAgents.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Declared</th><th>Attached seats</th><th>Data width</th><th>Address width</th><th>Protocol</th><th>Clock domain</th></tr></thead><tbody>
        {declaredAgents.map((agent, index) => {
          const seats = data.topology?.endpoints.filter(endpoint => endpoint.kind === agent.kind
            && (endpoint.group_index === undefined || endpoint.group_index === index)).length;
          return <tr key={`${agent.kind}-${index}`}><th className="mono">{agent.kind}</th><td className="numeric">{agent.count}</td><td>{seats === undefined ? <Badge>topology unavailable</Badge> : <Badge tone={seats < agent.count ? 'red' : seats > agent.count ? 'amber' : 'green'}>{seats} / {agent.count}</Badge>}</td><td className="numeric">{agent.data_width ?? '—'} b</td><td className="numeric">{agent.addr_width ?? '—'} b</td><td>{agent.protocol ?? '—'}</td><td className="mono">{agent.clock_domain ?? 'not declared'}</td></tr>;
        })}
      </tbody></table></div> : <p className="meta-line">No agent group is declared.</p>}
      <CheckTable checks={analysis.checks.filter(check => check.group === 'agents')} onSelect={setSelected} selected={selected} />
      <Assumptions rows={[
        ['Source', 'request.agents for the declaration; revision topology endpoints for the attached seats.'],
        ['Attachment', 'The compiler refuses an agent universe the topology does not realize. A seat count is not a protocol or CDC qualification.'],
      ]} />
    </Section>

    <Section title="Routing & deadlock" actions={<Badge tone={srota ? 'blue' : 'neutral'}>{srota ? 'Srota O1TURN/MECS' : data.topology?.family ?? 'topology family'}</Badge>}>
      <div className="stat-strip">
        <div className="stat"><span>Compiler deadlock</span><strong>{String(deadlock.status ?? 'not compiled')}</strong><small>{String(deadlock.method ?? '—')}</small></div>
        <div className="stat"><span>Proof method</span><strong>{String(proofMethod ?? '—')}</strong><small>{String(routingClass ?? 'routing class not named')}</small></div>
        <div className="stat"><span>CDG</span><strong>{String(nodes ?? '—')} nodes</strong><small>{String(edges ?? '—')} edges · cycle {cycleFound ? 'found' : 'none'}</small></div>
        <div className="stat"><span>VCs in proof</span><strong>{resources.vc_count !== undefined ? String(resources.vc_count) : '—'}</strong><small>{Array.isArray(evidence.escape_vcs) && evidence.escape_vcs.length ? `escape ${evidence.escape_vcs.join(', ')}` : 'no escape VC declared'}</small></div>
      </div>
      {claims.length ? <div className="table-scroll"><table><thead><tr><th>Certificate claim</th><th>Status</th><th>Method</th><th>Scope</th></tr></thead><tbody>
        {claims.map((claim, index) => {
          const name = claim.obligation ?? claim.claim ?? `claim-${index}`;
          const status = claim.status ?? claim.certificate_status ?? 'unknown';
          const scope = claim.meaning ?? claim.scope ?? '—';
          return <tr key={`${name}-${index}`}><th className="mono">{name}</th><td><Badge tone={status === 'PASS' ? 'green' : 'red'}>{status}</Badge></td><td>{claim.method ?? '—'}</td><td>{scope}</td></tr>;
        })}
      </tbody></table></div> : <p className="meta-line">No compiled certificate is available. Compile the draft to obtain attachment, route and deadlock claims.</p>}
      {srota && <><h3 className="subsection-title">Abstract shape CDG</h3><CdgGraph analysis={analysis} /></>}
      <CheckTable checks={analysis.checks.filter(check => check.group === 'routing')} onSelect={setSelected} selected={selected} />
      <Assumptions rows={[
        ['Authority', 'The compiler\'s concrete (resource, VC) CDG is authoritative. The abstract graph above reproduces the document\'s §4.5 row/column argument; it is explanatory, not a second proof.'],
        ['Rank policy', 'The hop-rank partition is proved by the compiler. This page does not reconstruct ranks 0–3 as a second implementation.'],
        ['Citation', 'ROUTE-001 §3.4, §4.3–4.5, §5.4; VC-002 §4.1.2; shared_resource_cdg.py.'],
      ]} />
    </Section>

    <Section title="Port budget · VC-R5" actions={<Badge tone={!readings.length ? 'neutral' : analysis.checks.some(check => check.id === 'port-budget-open') ? 'amber' : 'green'}>{!readings.length ? 'not applicable' : analysis.checks.some(check => check.id === 'port-budget-open') ? 'open' : 'reconciled'}</Badge>}>
      {readings.length ? <div className="table-scroll"><table><thead><tr><th>Reading</th><th>Mesh stage</th><th>Express stage</th><th>P</th><th>Crosspoints</th><th>Mux bits at 512b</th></tr></thead><tbody>
        {readings.map(reading => <tr key={reading.label}><th>{reading.label}</th><td className="numeric">{reading.meshStage}</td><td className="numeric">{reading.expressStage}</td><td className="numeric">{reading.ports}</td><td className="numeric">{reading.crosspoints}</td><td className="numeric">{reading.muxBits.toLocaleString()}</td></tr>)}
      </tbody></table></div> : <p className="meta-line">The port budget rule applies to Srota topologies only.</p>}
      <CheckTable checks={analysis.checks.filter(check => check.id.startsWith('port-budget'))} onSelect={setSelected} selected={selected} />
      <Assumptions rows={[
        ['Why this is open', 'VC-002 §4.1.3 reads “≤6 total” for the mesh stage while enumerating c injection/ejection ports; at c=4 that is 8. §8 fixes P=12. The readings imply different crossbar port counts.'],
        ['Consequence', 'The P×P×512b crossbar is the largest router structure. P=12 vs P=10 is a 44% crosspoint difference; the port list cannot be finalized until VC-R5 is decided.'],
      ]} />
    </Section>

    <Section title="QoS island confinement" actions={<Badge>{data.topology?.island_columns?.length ? `${data.topology.island_columns.length} column(s)` : 'none'}</Badge>}>
      <CheckTable checks={analysis.checks.filter(check => check.id.startsWith('island'))} onSelect={setSelected} selected={selected} />
      <Assumptions rows={[
        ['Invariant', 'I-ISL: every route to a shared resource passes through exactly one island router, and it is the final router before the attach queue.'],
        ['Scope', 'This page checks target placement and the column-first rule. It does not prove the rate regulator or the attach-queue timing.'],
      ]} />
    </Section>

    <Section title="RTL reach" actions={<Badge tone={analysis.rtlRows.some(row => row.status === 'reaches-preview') ? 'green' : 'amber'}>{analysis.rtlRows.filter(row => row.status === 'reaches-preview').length} / {analysis.rtlRows.length} reach the preview</Badge>}>
      <div className="table-scroll"><table><thead><tr><th>Control</th><th>Declared</th><th>Compile</th><th>Preview emitter</th><th>Status</th><th>Why</th></tr></thead><tbody>
        {analysis.rtlRows.map(row => <tr key={row.control}><th>{row.control}</th><td>{row.declared}</td><td>{row.compile}</td><td>{row.preview}</td><td><Badge tone={row.status === 'reaches-preview' ? 'green' : row.status === 'compiled-only' ? 'amber' : row.status === 'refused' ? 'red' : 'neutral'}>{row.status}</Badge></td><td>{row.note}<br /><small className="mono">{row.citation}</small></td></tr>)}
      </tbody></table></div>
      <Assumptions rows={[
        ['Meaning', '“Compiled” means the compiler derives and checks the control. “Preview” means the certified topology-only emitter materialises it.'],
        ['Limit', 'The preview is a 2-VC free/escape router over a connected point-to-point graph. It is not a final Srota NoC and does not implement O1TURN-XY/MECS, the FIU, the shared side buffer or Plane T.'],
        ['Address decoder', 'The emitted addr_decode.sv is a real decode of the resolved address map. It does not implement permissions, protocol adaptation or packet routing.'],
      ]} />
    </Section>

    <Section title={`All checks · ${shown.length}`}>
      <CheckTable checks={shown} onSelect={setSelected} selected={selected} />
    </Section>
  </div>
  <Inspector title="Check detail">
    {selectedCheck ? <>
      <h3>{selectedCheck.title}</h3>
      <Badge tone={tone(selectedCheck.status)}>{selectedCheck.status}</Badge>
      <p>{selectedCheck.detail}</p>
      <Properties rows={[
        ['Group', groupTitle[selectedCheck.group]],
        ['Citation', selectedCheck.citation],
        ['Evidence', selectedCheck.evidence ?? '—'],
        ['Authority', 'Static rule check over the saved draft; the compiler re-derives on compile.'],
      ]} />
    </> : <Empty title="Select a check">Choose a check to read its citation and evidence.</Empty>}
    <PageLink page="design/agent-map">Edit the agent address map</PageLink>
    <PageLink page="flow/optimize">Edit fabric controls</PageLink>
  </Inspector>
  </div>;
}

export function FabricAnalysisEmpty() {
  return <Empty title="Load a gateway project to analyse its fabric">
    The analysis reads the project draft, the revision topology and the compiled certificate. It does not invent a fabric when none is loaded.
  </Empty>;
}

export const FABRIC_ANALYSIS_PURPOSE = 'Static, spec-grounded checks for agent addresses, routing shapes, port budget, island confinement and what actually reaches RTL.';
