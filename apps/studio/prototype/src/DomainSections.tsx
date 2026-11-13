import type { AgentGroup } from './agentMap';
import type { DraftRequest } from './project';
import { Badge, Properties, Section } from './ui';
import { DomainLaneMap, type DomainChip, type DomainLane } from './DomainLaneMap';

/** Lanes come from the declared clock domains; chips are the declared
 *  assignees. Nothing here analyses CDC, reset sequencing or achieved timing. */
export function DomainLanes(agents: AgentGroup[]) {
  const domains: DomainLane[] = [...new Set(agents.map(agent => agent.clock_domain ?? 'undeclared'))]
    .sort((a, b) => a === 'undeclared' ? 1 : b === 'undeclared' ? -1 : a.localeCompare(b))
    .map(id => ({ id, note: id === 'undeclared' ? 'undeclared' : 'declared assignment' }));
  const chips: DomainChip[] = agents.map((agent, index) => ({
    id: `${agent.kind}-${index}`,
    title: agent.kind,
    meta: `${agent.count} instanc${agent.count === 1 ? 'e' : 'es'}`,
    detail: `${agent.data_width ?? '—'} b · ${agent.protocol ?? 'protocol not declared'}`,
    domain: agent.clock_domain ?? 'undeclared',
  }));
  return { domains, chips };
}

export function DomainSections({ agents, physical, chips, domains, crossingDomain, selected, onSelect, figcaption, banner }: {
  agents: AgentGroup[];
  physical?: DraftRequest['physical'];
  chips?: DomainChip[];
  domains?: DomainLane[];
  crossingDomain?: string;
  selected?: string | null;
  onSelect?: (id: string) => void;
  figcaption?: string;
  banner?: React.ReactNode;
}) {
  const derived = DomainLanes(agents);
  const lanes = domains ?? derived.domains;
  const assigned = chips ?? derived.chips;
  const declaredClocks = agents.filter(agent => agent.clock_domain);
  return <>
    {banner}
    <Section title="Declared physical parameters">
      <Properties rows={[
        ...(physical?.clock_freq_mhz ? [['Network clock', `${physical.clock_freq_mhz} MHz`] as [string, string]] : []),
        ...(physical?.data_width ? [['Data width', `${physical.data_width} b`] as [string, string]] : []),
        ...(physical?.num_power_domains !== undefined ? [['Declared power domains', String(physical.num_power_domains)] as [string, string]] : []),
        ...(physical?.process_node_nm ? [['Process node', `${physical.process_node_nm} nm`] as [string, string]] : []),
      ]} />
      <p className="meta-line">Power domains: 1 supported; multi-domain intent is refused because the fabric artifact has no isolation or level-shifting semantics. Not analysed: achieved timing, clock-tree distance, isolation and retention.</p>
    </Section>
    {declaredClocks.length > 0 && <Section title="Clock-domain assignment" actions={<Badge tone="blue">declared</Badge>}>
      <DomainLaneMap domains={lanes} chips={assigned} crossingDomain={crossingDomain} selected={selected} onSelect={onSelect}
        figcaption={figcaption ?? `${declaredClocks.length} of ${agents.length} agent group${agents.length === 1 ? '' : 's'} declare a clock domain. Assignment is declared intent; no CDC or reset-domain analysis is implied.`} />
    </Section>}
  </>;
}
