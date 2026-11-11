import type { DeclaredAgent, DeclaredCollective, DeclaredRequirement, DeclaredStage, LoadedProject } from './project';
import { Assumptions, Badge, Icon, PageLink, Section } from './ui';
import { DraftContext } from './draftSave';

function kindOf(agent: DeclaredAgent): string {
  return agent.kind ?? 'unspecified';
}

function byKind(agents: DeclaredAgent[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const agent of agents) counts.set(kindOf(agent), (counts.get(kindOf(agent)) ?? 0) + (agent.count ?? 0));
  return counts;
}

type Check = { check: string; observation: React.ReactNode; reading: React.ReactNode };

export function LiveValidatePage({ project, embedded = false }: { project: LoadedProject; embedded?: boolean }) {
  const request = project.request;
  const workload = request?.workload ?? null;
  const agents = request?.agents ?? [];
  const collectives = (workload?.collectives ?? []) as DeclaredCollective[];
  const requirements = (request?.requirements ?? []) as DeclaredRequirement[];
  const stages = (request?.compute?.stages ?? []) as DeclaredStage[];
  const endpoints = project.topology?.endpoints ?? [];
  const agentKinds = byKind(agents);
  const seats = new Map<string, number>();
  for (const endpoint of endpoints) seats.set(endpoint.kind ?? 'unspecified', (seats.get(endpoint.kind ?? 'unspecified') ?? 0) + 1);
  const allKinds = [...new Set([...agentKinds.keys(), ...seats.keys()])].sort();
  const tiles = agentKinds.get('compute_tile') ?? 0;
  const parallel = workload ? (workload.tp ?? 1) * (workload.dp ?? 1) * (workload.ep ?? 1) * (workload.pp ?? 1) : null;
  const totalAgents = agents.reduce((count, agent) => count + (agent.count ?? 0), 0);
  const classNames = new Map<string, { count: number; payload: number }>();
  for (const collective of collectives) {
    const key = collective.traffic_class ?? 'unclassified';
    const entry = classNames.get(key) ?? { count: 0, payload: 0 };
    entry.count += 1;
    entry.payload += collective.payload_bytes ?? 0;
    classNames.set(key, entry);
  }
  const requirementClasses = new Set(requirements.map(row => row.traffic_class).filter((name): name is string => !!name));
  const collectiveClasses = new Set(collectives.map(row => row.traffic_class).filter((name): name is string => !!name));
  const unmatchedTraffic = [...collectiveClasses].filter(name => !requirementClasses.has(name));
  const unproducedRequirements = [...requirementClasses].filter(name => !collectiveClasses.has(name));
  const moreAgents = allKinds.filter(kind => (agentKinds.get(kind) ?? 0) > (seats.get(kind) ?? 0));
  const ownerlessStages = stages.filter(stage => stage.owner === null || stage.owner === undefined).length;
  const addressRanges = request?.address_map?.ranges ?? [];
  const physical = request?.physical;
  const noc = ((request?.noc_controls ?? request?.noc_config) ?? null) as Record<string, any> | null;
  const clockDomains = [...new Set(agents.map(agent => agent.clock_domain).filter(Boolean))];
  const checks: Check[] = [
    {
      check: 'Workload declared',
      observation: workload
        ? <>{workload.model_name || 'unnamed model'} · TP{workload.tp ?? 1} / DP{workload.dp ?? 1} / EP{workload.ep ?? 1} / PP{workload.pp ?? 1}</>
        : 'No workload block in the draft.',
      reading: workload ? <Badge tone="green">Declared</Badge> : <Badge tone="amber">Absent</Badge>,
    },
    {
      check: 'Compute intent',
      observation: stages.length
        ? <>
          {stages.length} declared stage{stages.length === 1 ? '' : 's'} · {(stages.reduce((sum, stage) => sum + (stage.duration_ns ?? 0), 0) / 1e6).toFixed(3)} ms summed duration
          {ownerlessStages > 0 && <> · {ownerlessStages} without an owner index</>}
        </>
        : 'No compute stages. Network traffic is evaluable; execution timing is not derivable.',
      reading: stages.length
        ? ownerlessStages > 0 && totalAgents > 1 ? <Badge tone="amber">Owner missing</Badge> : <Badge tone="green">Declared</Badge>
        : <Badge tone="amber">Network only</Badge>,
    },
    {
      check: 'Traffic ↔ requirements',
      observation: <>
        {unmatchedTraffic.length
          ? <>Declared class without a criterion: <span className="mono">{unmatchedTraffic.join(', ')}</span>. </>
          : 'Every declared traffic class has a criterion. '}
        {unproducedRequirements.length
          ? <>Requirement has no matching traffic: <span className="mono">{unproducedRequirements.join(', ')}</span>.</>
          : 'Every requirement matches declared traffic.'}
      </>,
      reading: unmatchedTraffic.length || unproducedRequirements.length ? <Badge tone="amber">Coverage gap</Badge> : <Badge tone="green">Covered</Badge>,
    },
    {
      check: 'Parallelism ↔ agents',
      observation: parallel === null
        ? 'No workload parallelism declared.'
        : `${parallel} parallel rank${parallel === 1 ? '' : 's'} · ${tiles} compute tile${tiles === 1 ? '' : 's'} declared.`,
      reading: parallel !== null && tiles > 0 && parallel !== tiles
        ? <Badge tone="amber">Parallelism product {parallel} ≠ {tiles} tiles</Badge>
        : <Badge tone="green">Consistent</Badge>,
    },
    {
      check: 'Agents ↔ endpoint seats',
      observation: <>
        <strong>No binding table in this draft.</strong> {totalAgents} agent{totalAgents === 1 ? '' : 's'} declared against {endpoints.length} endpoint seat{endpoints.length === 1 ? '' : 's'}.
        {allKinds.length > 0 && <> By kind: {allKinds.map(kind => `${kind} ${agentKinds.get(kind) ?? 0}/${seats.get(kind) ?? 0}`).join(' · ')}.</>}
      </>,
      reading: moreAgents.length
        ? <Badge tone="amber">More agents than attached seats</Badge>
        : <Badge tone="green">Seat counts match</Badge>,
    },
    {
      check: 'Address map',
      observation: addressRanges.length ? `${addressRanges.length} range${addressRanges.length === 1 ? '' : 's'} declared.` : 'Memory access has no decode map.',
      reading: addressRanges.length ? <Badge tone="green">Declared</Badge> : <Badge tone="amber">Not declared</Badge>,
    },
    {
      check: 'Lowering adapter',
      observation: 'No lowering adapter. Coherence checks only; nothing executable is produced here.',
      reading: <Badge>Not connected</Badge>,
    },
  ];

  return <div className={embedded ? 'studio-embedded' : 'view-main studio-view'}>
    {!embedded && <DraftContext project={project} />}
    {embedded && <h2 className="studio-embedded-title">Readiness checks</h2>}
    {!embedded && <div className="studio-intro">
      <div>
        <h2>Readiness checks</h2>
      </div>
      <PageLink page="workloads/workflow">Compile in Project workflow <Icon name="arrow" /></PageLink>
    </div>}

    <Section title="Declaration checks">
      <div className="table-scroll"><table className="check-table">
        <thead><tr><th>Check</th><th>Observation</th><th>Reading</th></tr></thead>
        <tbody>{checks.map(row => <tr key={row.check}><th>{row.check}</th><td>{row.observation}</td><td>{row.reading}</td></tr>)}</tbody>
      </table></div>
    </Section>

    <Section title="Declared model inputs">
      <dl className="properties">
        <div><dt>Clock frequency</dt><dd>{physical?.clock_freq_mhz ? `${physical.clock_freq_mhz} MHz` : 'Not declared'}</dd></div>
        <div><dt>Data width</dt><dd>{physical?.data_width ? `${physical.data_width} bit` : 'Not declared'}</dd></div>
        <div><dt>Power domains</dt><dd>{physical?.num_power_domains ?? 'Not declared'}</dd></div>
        <div><dt>Process node</dt><dd>{physical?.process_node_nm ? `${physical.process_node_nm} nm` : 'Not declared'}</dd></div>
        <div><dt>Link width</dt><dd>{noc?.link_width ? `${noc.link_width} bit` : 'Not declared'}</dd></div>
        <div><dt>Arbitration</dt><dd>{noc?.arbitration ?? 'Not declared (null)'}</dd></div>
        <div><dt>Per-agent clock assignment</dt><dd>{agents.length === 0 ? 'No agents declared' : clockDomains.length === 0 ? 'null for every agent' : clockDomains.join(', ')}</dd></div>
        <div><dt>Achieved timing</dt><dd>Not evaluated; these are declared inputs.</dd></div>
      </dl>
    </Section>

    <details className="origin">
      <summary>Endpoint seats from the compiled revision ({endpoints.length})</summary>
      {endpoints.length ? <div className="table-scroll capped"><table>
        <thead><tr><th>Endpoint</th><th>Kind</th><th>Router</th><th>Port</th></tr></thead>
        <tbody>{endpoints.slice(0, 64).map(endpoint => <tr key={endpoint.endpoint_id}>
          <th className="mono">EP-{endpoint.endpoint_id}</th>
          <td>{endpoint.kind ?? '—'}</td>
          <td className="mono">R{endpoint.router_id}</td>
          <td className="numeric">{endpoint.port_id}</td>
        </tr>)}</tbody>
      </table></div> : <p>This revision's topology carries no endpoint seats.</p>}
      <PageLink page="design/endpoints">Inspect endpoint attachments</PageLink>
    </details>

    <details className="origin">
      <summary>Traffic classes and requirements</summary>
      <div className="table-scroll"><table>
        <thead><tr><th>Traffic class</th><th>Collectives</th><th>Payload</th><th>Criterion</th></tr></thead>
        <tbody>
          {[...new Set([...classNames.keys(), ...requirementClasses])].sort().map(name => {
            const entry = classNames.get(name);
            return <tr key={name}>
              <th>{name}</th>
              <td className="numeric">{entry?.count ?? 0}</td>
              <td className="numeric">{entry ? `${(entry.payload / 1024).toFixed(2)} KiB` : '—'}</td>
              <td>{requirementClasses.has(name) ? <Badge tone="green">Declared</Badge> : <Badge tone="amber">Missing</Badge>}</td>
            </tr>;
          })}
        </tbody>
      </table></div>
    </details>

    <Assumptions rows={[
      ['Scope', 'Declarative readiness checks only; not a compile, simulation or qualification.'],
      ['Lowering', 'No lowering adapter is connected; nothing executable is produced here.'],
      ['Topology', project.topology?.family ?? 'none (no compiled revision)'],
      ['Seats', "Seat order is the topology document's order, not a rank or participant assignment."],
      ['Timing', 'Achieved timing is not evaluated; physical and NoC fields are declared inputs.'],
    ]} />
  </div>;
}
