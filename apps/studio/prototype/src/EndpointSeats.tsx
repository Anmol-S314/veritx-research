import type { ReactNode } from 'react';
import type { AgentGroup } from './agentMap';
import type { Topology } from './gateway';
import { Badge, Empty, Icon, Section } from './ui';
import { TopologyGraph } from './TopologyGraph';
import { cappedClass } from './format';

const absent = <Badge tone="amber">Not declared in this payload</Badge>;

/** One shape for endpoint seats, used by both the local sample and a loaded
 *  project. The sample supplies declared intent; the project supplies the
 *  revision's seats. Nothing here infers a protocol adapter or a placement. */
export type EndpointSeatModel = {
  agents: AgentGroup[];
  endpoints: Topology['endpoints'];
  topology: Topology | null;
  /** Sample-only declared identifier and source classification, by endpoint id. */
  labelById?: Map<number, string>;
  sourceById?: Map<number, string>;
  agentForEndpoint?: (endpoint: Topology['endpoints'][number]) => AgentGroup | null;
};

export function EndpointSeatSections({ model, selected, onSelect, banner, query, onQuery, selectedEndpoint, onSelectEndpoint }: {
  model: EndpointSeatModel;
  selected?: number | null;
  onSelect?: (routerId: number) => void;
  banner?: ReactNode;
  query?: string;
  onQuery?: (value: string) => void;
  selectedEndpoint?: number | null;
  onSelectEndpoint?: (endpointId: number) => void;
}) {
  const { agents, endpoints, topology, labelById, sourceById, agentForEndpoint } = model;
  const byRouter = new Map<number, number>();
  for (const endpoint of endpoints) byRouter.set(endpoint.router_id, (byRouter.get(endpoint.router_id) ?? 0) + 1);
  const kinds = [...new Set(endpoints.map(endpoint => endpoint.kind))];
  const agentOf = agentForEndpoint ?? ((endpoint: Topology['endpoints'][number]) => agents.find(agent => agent.kind === endpoint.kind) ?? null);
  const labelOf = (endpoint: Topology['endpoints'][number]) => labelById?.get(endpoint.endpoint_id) ?? `EP-${endpoint.endpoint_id}`;
  const needle = (query ?? '').trim().toLowerCase();
  const shown = needle
    ? endpoints.filter(endpoint => `${labelOf(endpoint)} ${endpoint.kind} R${endpoint.router_id}`.toLowerCase().includes(needle))
    : endpoints;

  return <>
    {banner}
    {topology && <Section title="Endpoint seat attachment" actions={<Badge>declared topology</Badge>}>
      <div className="seat-attachment"><TopologyGraph topology={topology} selected={selected} onSelect={onSelect} labels={topology.routers.length <= 64} /></div>
    </Section>}

    <Section title="Declared agent groups" actions={<Badge>{agents.reduce((total, agent) => total + (agent.count ?? 0), 0)} agents</Badge>}>
      {agents.length ? <div className="table-scroll"><table><thead><tr><th>Kind</th><th>Count</th><th>Data width</th><th>Address width</th><th>Protocol</th><th>Clock domain</th><th>Power domain</th></tr></thead><tbody>
        {agents.map((agent, index) => <tr key={`${agent.kind}-${index}`}><th>{agent.kind}</th><td className="numeric">{agent.count}</td><td className="numeric">{agent.data_width !== undefined ? `${agent.data_width} b` : '—'}</td><td className="numeric">{agent.addr_width !== undefined ? `${agent.addr_width} b` : '—'}</td><td>{agent.protocol ?? absent}</td><td>{agent.clock_domain ?? absent}</td><td>{agent.power_domain ?? 'Not recorded'}</td></tr>)}
      </tbody></table></div> : <Empty title="No declared agents">This document declares no agents.</Empty>}
    </Section>

    <Section title="Attached endpoints" actions={<>
      {onQuery && <label className="search-field"><Icon name="search" /><input aria-label="Filter endpoints" placeholder="Filter identifiers, roles, routers…" value={query ?? ''} onChange={event => onQuery(event.target.value)} /></label>}
      <Badge>{needle ? `${shown.length} of ${endpoints.length} seats` : `${endpoints.length} seats`}</Badge>
    </>}>
      {endpoints.length ? <>
        <div className={`table-scroll${cappedClass(endpoints.length)}`}><table><thead><tr><th>Endpoint</th><th>Kind</th><th>Router</th><th>Port</th><th>Group / index</th><th>Protocol</th><th>Data width</th><th>Address width</th><th>Clock domain</th><th>Power domain</th>{sourceById && <th>Source</th>}</tr></thead><tbody>
          {shown.map(endpoint => {
            const agent = agentOf(endpoint);
            const isSelected = selectedEndpoint !== undefined && selectedEndpoint !== null && endpoint.endpoint_id === selectedEndpoint;
            return <tr key={endpoint.endpoint_id} className={isSelected ? 'selected' : ''}><td className="mono">{onSelectEndpoint
              ? <button className="text-button mono" onClick={() => onSelectEndpoint(endpoint.endpoint_id)}>{labelOf(endpoint)}</button>
              : labelOf(endpoint)}</td><td>{endpoint.kind}</td><td className="mono">R{endpoint.router_id}</td><td className="numeric">{endpoint.port_id}</td><td className="mono">{endpoint.group_index ?? '—'} / {endpoint.instance_index ?? '—'}</td><td>{agent?.protocol ?? 'Not recorded'}</td><td className="numeric">{agent?.data_width !== undefined ? `${agent.data_width} b` : 'Not recorded'}</td><td className="numeric">{agent?.addr_width !== undefined ? `${agent.addr_width} b` : 'Not recorded'}</td><td>{agent?.clock_domain ?? 'Not recorded'}</td><td>{agent?.power_domain ?? 'Not recorded'}</td>{sourceById && <td><Badge>{sourceById.get(endpoint.endpoint_id) ?? 'Declared'}</Badge></td>}</tr>;
          })}
        </tbody></table></div>
        {shown.length === 0 && <Empty title="No endpoint matches this filter">Clear the filter to see every declared seat.</Empty>}
        <div className="legend"><span>{kinds.join(' · ')}</span><span>{byRouter.size} routers carry endpoints</span></div>
      </> : <Empty title="No endpoints declared">The topology document declares no endpoint seats.</Empty>}
    </Section>
  </>;
}
