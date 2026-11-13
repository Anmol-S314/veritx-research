import type { DeclaredAgent, DraftRequest } from './project';
import type { MappingGroup, Topology } from './gateway';

const KIND_LABEL: Record<string, string> = {
  compute_tile: 'Compute tiles',
  hbm_controller: 'HBM controllers',
  nic: 'NICs',
  peripheral: 'Peripherals',
  ucie_port: 'UCIe ports',
};

function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind.replaceAll('_', ' ');
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function line(value: unknown): string {
  return value === undefined || value === null || value === '' ? '—' : String(value);
}

export function SystemDiagram({ agents, workload, topology, mapping, certificate }: {
  agents: DeclaredAgent[];
  workload: DraftRequest['workload'];
  topology: Topology | null;
  mapping: MappingGroup | null;
  certificate: Record<string, unknown> | null;
}) {
  const seats = new Map<string, { count: number; routers: Set<number> }>();
  for (const endpoint of topology?.endpoints ?? []) {
    const seat = seats.get(endpoint.kind) ?? { count: 0, routers: new Set<number>() };
    seat.count += 1;
    seat.routers.add(endpoint.router_id);
    seats.set(endpoint.kind, seat);
  }
  const agentByKind = new Map(agents.map(agent => [agent.kind, agent]));
  const kinds = [...agents.map(agent => agent.kind), ...seats.keys()].filter((kind, index, all) => all.indexOf(kind) === index);
  const rows = kinds.map(kind => ({ kind, agent: agentByKind.get(kind) }));
  const rowH = 62;
  const top = 74;
  const height = Math.max(258, top + Math.max(1, rows.length) * rowH + 20);
  const cardH = Math.max(150, rows.length * rowH - 8);
  const computeIndex = rows.findIndex(row => row.kind === 'compute_tile');
  const totalAgents = agents.reduce((sum, agent) => sum + (agent.count ?? 0), 0);
  const rankCount = mapping?.rank_count ?? mapping?.rows?.length ?? 0;
  const mapped = mapping?.idle_agents?.mapped ?? rankCount;
  const idle = mapping?.idle_agents?.count ?? 0;
  const shared = topology?.shared_links?.length ?? 0;
  const cert = certificate ?? {};
  const certText = cert.certificate_overall
    ? `${line(cert.routing)} · VC ${line(cert.vc_count)} · ${line(cert.certificate_overall)}`
    : 'No derived certificate';
  return <div className="system-composition-scroll">
    <svg className="system-composition" viewBox={`0 0 860 ${height}`} role="group" aria-label="Declared system composition diagram">
      <title>Workload, agent groups, attached endpoint seats, and fabric</title>
      <defs>
        <marker id="system-arrowhead" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 0 L 8 4 L 0 8 z" className="system-arrowhead" />
        </marker>
      </defs>
      <text className="system-diagram-heading" x={14} y={20}>Declared system composition</text>
      <text className="system-diagram-sub" x={14} y={37}>Workload → agent groups → attached endpoint seats → fabric</text>
      <text className="system-lane-label" x={14} y={60}>Workload</text>
      <text className="system-lane-label" x={218} y={60}>Agent groups</text>
      <text className="system-lane-label" x={430} y={60}>Attached endpoint seats</text>
      <text className="system-lane-label" x={616} y={60}>Fabric</text>

      <g className="system-card workload">
        <rect x={14} y={top} width={176} height={cardH} rx={6} />
        <text className="system-card-title" x={28} y={top + 20}>Workload</text>
        <text className="system-card-value" x={28} y={top + 40}>{truncate(workload?.model_name ?? 'Not declared', 22)}</text>
        <text className="system-card-line" x={28} y={top + 59}>{workload ? `TP${workload.tp ?? 1} · DP${workload.dp ?? 1} · EP${workload.ep ?? 1} · PP${workload.pp ?? 1}` : 'Parallelism not declared'}</text>
        <text className="system-card-line" x={28} y={top + 77}>{mapping ? `Mapped ${mapped}/${rankCount} · idle ${idle}` : 'Rank mapping not carried'}</text>
        <text className="system-card-line" x={28} y={top + 95}>{workload?.collectives?.length ? `${workload.collectives.length} declared collectives` : 'No collectives declared'}</text>
        <text className="system-card-line" x={28} y={top + 113}>{totalAgents} declared agents</text>
      </g>

      {rows.length === 0 && <g className="system-card agent missing">
        <rect x={218} y={top} width={184} height={52} rx={5} />
        <text className="system-card-title" x={232} y={top + 20}>No agent groups</text>
        <text className="system-card-line" x={232} y={top + 37}>The request declares no agents.</text>
      </g>}

      {rows.map(({ kind, agent }, index) => {
        const y = top + index * rowH;
        const seat = seats.get(kind);
        return <g key={kind}>
          <g className="system-card agent">
            <rect x={218} y={y} width={184} height={52} rx={5} />
            <text className="system-card-title" x={232} y={y + 18}>{truncate(kindLabel(kind), 22)}</text>
            <text className="system-card-value" x={232} y={y + 34}>{agent ? `${agent.count} × ${kind}` : 'Endpoint seats only'}</text>
            <text className="system-card-line" x={232} y={y + 48}>{agent ? `${line(agent.data_width)} b · ${line(agent.protocol)}` : 'No request agent group'}</text>
          </g>
          {index === computeIndex && <path className="system-arrow" d={`M 190 ${top + 31} C 204 ${top + 31}, 204 ${y + 26}, 218 ${y + 26}`} markerEnd="url(#system-arrowhead)" />}
          <g className={`system-card seat${seat ? '' : ' missing'}`}>
            <rect x={430} y={y + 4} width={158} height={44} rx={5} />
            <text className="system-card-title" x={444} y={y + 21}>{seat ? `${seat.count} attached` : 'No seat materialised'}</text>
            <text className="system-card-line" x={444} y={y + 37}>{seat ? `${seat.routers.size} router${seat.routers.size === 1 ? '' : 's'}` : 'Topology attachment absent'}</text>
          </g>
          <path className={`system-arrow${seat ? '' : ' missing'}`} d={`M 402 ${y + 26} H 430`} markerEnd={seat ? 'url(#system-arrowhead)' : undefined} />
          {seat && <path className="system-arrow" d={`M 588 ${y + 26} H 616`} markerEnd="url(#system-arrowhead)" />}
        </g>;
      })}

      <g className="system-card fabric">
        <rect x={616} y={top} width={230} height={cardH} rx={6} />
        <text className="system-card-title" x={630} y={top + 20}>Fabric</text>
        <text className="system-card-value" x={630} y={top + 40}>{topology ? topology.family : 'No topology document'}</text>
        <text className="system-card-line" x={630} y={top + 59}>{topology ? `${topology.routers.length} routers · ${topology.endpoints.length} endpoint seats` : 'No declared routers or seats'}</text>
        <text className="system-card-line" x={630} y={top + 77}>{topology ? `${topology.channels.length} channels · ${shared} shared wires` : 'No connection resources'}</text>
        <text className="system-card-line" x={630} y={top + 95}>{topology?.planes?.length ? `Planes ${topology.planes.map(plane => plane.toUpperCase()).join(' / ')}` : 'Plane declaration not carried'}</text>
        <text className="system-card-line" x={630} y={top + 113}>{certText}</text>
        <text className="system-card-line" x={630} y={top + 131}>{topology?.counts?.seats !== undefined ? `${topology.counts.seats} declared seats` : 'Seat capacity not declared'}</text>
      </g>
    </svg>
  </div>;
}
