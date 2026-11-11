import { useState } from 'react';
import { gateway, gatewayReason } from './gateway';
import type { LoadedProject } from './project';
import { useProject } from './project';
import type { PageId } from './model';
import { Assumptions, Badge, Button, Notice, PageLink, Properties, Section } from './ui';

type Option = {
  kind: string;
  label: string;
  description: string;
  authorable: boolean;
  size?: (seats: number) => Record<string, number>;
};

const TOPOLOGY_OPTIONS: Option[] = [
  {
    kind: 'mesh',
    label: 'Mesh',
    description: 'Regular grid with local links. Simple, predictable and the safest default for a small or medium fabric.',
    authorable: true,
    size: seats => ({ side_length: Math.max(1, Math.ceil(Math.sqrt(seats))), concentration: 1 }),
  },
  {
    kind: 'concentrated_mesh',
    label: 'CMesh',
    description: 'Fewer routers with several endpoints attached to each router. Useful when endpoints grow faster than routers.',
    authorable: true,
    size: seats => ({ side_length: Math.max(1, Math.ceil(Math.sqrt(seats / 4))), concentration: 4 }),
  },
  {
    kind: 'torus',
    label: 'Torus',
    description: 'A mesh with wraparound links. More path diversity at the edges, at the cost of longer wrap links.',
    authorable: true,
    size: seats => ({ side_length: Math.max(1, Math.ceil(Math.sqrt(seats))), concentration: 1 }),
  },
  {
    kind: 'fattree',
    label: 'Fat-tree',
    description: 'Hierarchical tree. Good for all-to-all at larger endpoint counts; needs an explicit switch radix and level count.',
    authorable: false,
  },
  {
    kind: 'flatfly',
    label: 'Flatfly',
    description: 'Low-diameter, high-radix network. Needs explicit radix-per-dimension and dimension-count fields.',
    authorable: false,
  },
  {
    kind: 'gec',
    label: 'GEC',
    description: 'Research fabric with express, multidrop and hybrid modes. The mode and grid fields are set in the Fabric editor.',
    authorable: false,
  },
  {
    kind: 'srota',
    label: 'SROTA',
    description: 'Research fabric with plane, MECS, path-shape and telemetry settings. Configure it in the Fabric editor.',
    authorable: false,
  },
];

const bytes = (value?: number | null) => value == null ? '—' : value >= 1e6 ? `${(value / 1e6).toFixed(2)} MB` : value >= 1e3 ? `${(value / 1e3).toFixed(1)} kB` : `${value} B`;

function previewFor(option: Option, seats: number): string {
  if (!option.size) {
    return option.kind === 'fattree' ? 'radix and levels configured in Fabric'
      : option.kind === 'flatfly' ? 'radix and dimensions configured in Fabric'
        : option.kind === 'srota' ? 'plane, MECS and telemetry configured in Fabric'
          : 'mode and grid configured in Fabric';
  }
  const fields = option.size(seats);
  const side = fields.side_length;
  const concentration = fields.concentration ?? 1;
  const routers = side * side;
  return `${side}×${side} routers · ${routers * concentration} endpoint seats${concentration > 1 ? ` · ${concentration} per router` : ''}`;
}

export function ProjectFabric({ project, navigate, notify }: {
  project: LoadedProject;
  navigate: (page: PageId) => void;
  notify: (message: string) => void;
}) {
  const { reload } = useProject();
  const request = (project.request ?? null) as Record<string, any> | null;
  const agents = (request?.agents ?? []) as { kind?: string; count?: number }[];
  const seats = Math.max(1, agents.reduce((total, agent) => total + (Number(agent.count) || 0), 0));
  const workload = request?.workload ?? null;
  const collectives = (workload?.collectives ?? []) as Record<string, any>[];
  const requirements = (request?.requirements ?? []) as Record<string, any>[];
  const currentKind = request?.topology?.kind ?? request?.noc_config?.topology_family ?? '';
  const [selected, setSelected] = useState(currentKind || 'mesh');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const option = TOPOLOGY_OPTIONS.find(item => item.kind === selected) ?? TOPOLOGY_OPTIONS[0];
  const topology = option.size ? { kind: option.kind, ...option.size(seats) } : null;
  const dirty = project.draftMeta?.dirty === true;
  const canApply = !!topology && selected !== currentKind && !dirty && !busy;

  if (!request) return <div className="view-main">
    <Notice tone="amber"><strong>No workload declared.</strong> Start in the project workflow: declare the workload, requirements and fabric, then compile a revision.</Notice>
    <PageLink page="workloads/workflow" primary>Open project workflow</PageLink>
  </div>;

  const apply = async () => {
    if (!topology) return;
    setBusy(true); setError('');
    try {
      // A v3 request rejects a root `topology` field before migration; send
      // the original document and the topology separately in that case.
      const withTopology = request.topology !== undefined ? { ...request, topology } : request;
      const preview = await gateway.topologyPreview(project.detail.project.project_id, withTopology, topology);
      const canonical = (preview.request ?? withTopology) as Record<string, any>;
      await gateway.putDraft(project.detail.project.project_id, canonical, project.draftMeta?.revisionToken);
      try { sessionStorage.setItem(`srota-intent-tab:${project.detail.project.project_id}`, 'fabric'); } catch { /* The tab hint is optional. */ }
      notify(`Topology applied: ${option.label} · ${previewFor(option, seats)}. Compile and evaluate to measure it on this workload.`);
      reload();
      navigate('workloads/workflow');
    } catch (caught) {
      setError(gatewayReason(caught));
    } finally {
      setBusy(false);
    }
  };

  const openFabric = () => {
    try { sessionStorage.setItem(`srota-intent-tab:${project.detail.project.project_id}`, 'fabric'); } catch { /* The tab hint is optional. */ }
    window.dispatchEvent(new Event('srota:open-draft-editor'));
    navigate('workloads/workflow');
  };

  return <div className="view-main">
    <Section title="Workload for this project" actions={<Badge tone="blue">{seats} endpoint seats</Badge>}>
      <p className="meta-line">This is the project's declared workload. Choose a fabric from the options below; the catalog reference is an optional comparison, not the starting point.</p>
      <Properties rows={[
        ['Model', workload?.model_name || 'No model name declared'],
        ['Model family', workload?.model_family ?? 'not declared'],
        ['Parallelism', `TP${workload?.tp ?? 1} · DP${workload?.dp ?? 1} · EP${workload?.ep ?? 1} · PP${workload?.pp ?? 1} · ${(workload?.tp ?? 1) * (workload?.dp ?? 1) * (workload?.ep ?? 1) * (workload?.pp ?? 1)} ranks`],
        ['Traffic', collectives.length ? collectives.map(item => `${item.kind ?? 'traffic'} ${item.dimension ?? ''} · ${bytes(item.payload_bytes)} · ${item.traffic_class ?? 'unclassified'}`).join(' · ') : 'None declared'],
        ['Endpoint agents', agents.length ? agents.map(agent => `${agent.count ?? 0} × ${agent.kind ?? 'agent'}`).join(' · ') : 'None declared'],
        ['Criteria', requirements.length ? requirements.map(item => `${item.traffic_class ?? 'class'} ${item.latency_ceiling_cycles != null ? `≤ ${item.latency_ceiling_cycles} cyc` : ''}${item.bandwidth_floor_gbps != null ? ` ≥ ${item.bandwidth_floor_gbps} GB/s` : ''}${item.binding === false ? ' · non-binding' : ''}`).join(' · ') : 'None declared'],
      ]} />
    </Section>

    <Section title="Choose a topology" actions={<Badge tone={selected === currentKind ? 'green' : 'amber'}>{selected === currentKind ? 'Current' : 'Selected'}</Badge>}>
      <p className="meta-line">The sizes below are derived from the declared endpoint count. They are a starting point, not a measured recommendation; compile and evaluate to produce evidence for this project.</p>
      <div className="form-grid" role="radiogroup" aria-label="Topology options">
        {TOPOLOGY_OPTIONS.map(item => <label className="strategy-option" key={item.kind}>
          <input type="radio" name="project-topology" checked={selected === item.kind} onChange={() => setSelected(item.kind)} />
          <div>
            <strong>{item.label}{item.kind === currentKind ? ' · current' : ''}</strong>
            <p>{item.description}</p>
            <small className="mono">{previewFor(item, seats)}</small>
          </div>
        </label>)}
      </div>
      <div className="toolbar">
        {option.authorable
          ? <Button primary disabled={!canApply} onClick={apply}>{busy ? 'Applying…' : `Apply ${option.label} to draft`}</Button>
          : <Button primary onClick={openFabric}>Configure {option.label} in Fabric</Button>}
        {option.authorable && <Button onClick={openFabric}>Configure link width and buffer depth</Button>}
      </div>
      {!option.authorable && <Notice tone="amber"><strong>{option.label} needs fields the one-click sizing cannot derive.</strong> Open Fabric to set them explicitly; nothing is guessed.</Notice>}
      {dirty && <Notice tone="amber">The saved draft has uncompiled changes. Compile or discard them before applying a different topology.</Notice>}
      {error && <Notice tone="red">{error}</Notice>}
    </Section>

    <details className="inline-details">
      <summary>Advanced: compare measured alternatives</summary>
      <p className="meta-line">The reference catalog measures repository traces, not this project. The revision study compares multiple candidate revisions on this project. Neither is required to choose a topology for a single design.</p>
      <div className="actions">
        <PageLink page="explore/fabric-search">Browse reference catalog</PageLink>
        <PageLink page="explore/brief">Compare revisions (study)</PageLink>
      </div>
    </details>

    <Assumptions rows={[
      ['Workload', 'The model, parallelism, traffic and criteria above come from this project draft, not a repository preset.'],
      ['Sizing', 'Topology dimensions are derived from the declared endpoint count. They are not measured evidence.'],
      ['Apply', 'Applying writes the topology intent to the draft only. The current link width, buffer depth and pipeline fields are preserved. Compile and evaluate to measure the result.'],
      ['Not derived', 'Fat-tree, Flatfly, GEC and SROTA need explicit structural fields; the one-click sizing refuses to guess them.'],
      ['Advanced', 'The reference catalog is measured on repository traces. The revision study is an optional comparison of candidate revisions.'],
    ]} />
  </div>;
}
